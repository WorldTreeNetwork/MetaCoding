"""Tests for persistent-homology shape signatures."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import polars as pl
import pytest

gudhi = pytest.importorskip("gudhi", reason="install with `uv sync --extra topo`")

from ctkr.shape import (  # noqa: E402
    compute_shape_pds,
    wasserstein_distance_matrix,
    write_shape_pds,
)
from ctkr.schema import SHAPE_PDS_COLUMNS, ShapePDRow  # noqa: E402


def _cycle_repo(repo: str, n: int = 6) -> list[tuple[str, dict, list[tuple[str, str]]]]:
    """Generate node-and-edge specs for an n-cycle (one H_1 loop)."""
    nodes = [(f"{repo}-{i}", {"repo": repo, "qualified_name": f"{repo}.{i}", "kind": "class"}) for i in range(n)]
    edges = [(f"{repo}-{i}", f"{repo}-{(i + 1) % n}") for i in range(n)]
    return [(repo, dict(nodes), edges)]  # ignored


def _build_cycle(repo: str, n: int = 6) -> list[tuple[str, str]]:
    return [(f"{repo}-{i}", f"{repo}-{(i + 1) % n}") for i in range(n)]


def _build_tree(repo: str, n: int = 6) -> list[tuple[str, str]]:
    """Path graph — no loops, H_1 empty."""
    return [(f"{repo}-{i}", f"{repo}-{i + 1}") for i in range(n - 1)]


def _graph_with(repos: dict[str, list[tuple[str, str]]]) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for repo, edges in repos.items():
        for u, v in edges:
            for n in (u, v):
                if not g.has_node(n):
                    g.add_node(n, repo=repo, qualified_name=n, kind="class")
            g.add_edge(u, v, key="CALLS", kind="CALLS")
    return g


# ----- structural correctness -----


def test_h0_one_component_per_repo() -> None:
    """A connected repo → exactly one H_0 essential point.

    With INFINITY_REPLACEMENT=1.0, the death of the essential class is
    capped, but the count stays.
    """
    g = _graph_with({"r1": _build_cycle("r1", 5)})
    _, pds, _ = compute_shape_pds(g, min_repo_size=2)
    h0 = pds.get(("r1", 0), [])
    # All but one H_0 pair die at the global merge.
    assert len(h0) == 5, f"expected 5 H_0 points for a 5-node connected graph, got {len(h0)}"


def test_h1_detects_cycle() -> None:
    """A clean n-cycle has exactly one H_1 loop."""
    g = _graph_with({"r1": _build_cycle("r1", 6)})
    _, pds, _ = compute_shape_pds(g, min_repo_size=2)
    h1 = pds.get(("r1", 1), [])
    assert len(h1) == 1, f"expected exactly 1 H_1 point for a 6-cycle, got {len(h1)}"


def test_h1_empty_for_tree() -> None:
    """A path graph has no loops → H_1 empty."""
    g = _graph_with({"r1": _build_tree("r1", 6)})
    _, pds, _ = compute_shape_pds(g, min_repo_size=2)
    h1 = pds.get(("r1", 1), [])
    assert h1 == [], f"expected no H_1 for a tree, got {h1}"


# ----- schema and IO -----


def test_schema_columns_and_pydantic() -> None:
    g = _graph_with({"r1": _build_cycle("r1", 6)})
    df, _, _ = compute_shape_pds(g, min_repo_size=2)
    assert list(df.columns) == list(SHAPE_PDS_COLUMNS)
    for d in df.to_dicts():
        ShapePDRow.model_validate(d)


def test_parquet_roundtrip(tmp_path: Path) -> None:
    g = _graph_with({"r1": _build_cycle("r1", 6)})
    df, _, _ = compute_shape_pds(g, min_repo_size=2)
    out = tmp_path / "shape_pds.parquet"
    write_shape_pds(df, out)
    back = pl.read_parquet(out)
    assert list(back.columns) == list(SHAPE_PDS_COLUMNS)
    assert back.height == df.height


# ----- Wasserstein -----


def test_wasserstein_self_distance_is_zero() -> None:
    g = _graph_with({"r1": _build_cycle("r1", 6), "r2": _build_cycle("r2", 6)})
    _, pds, _ = compute_shape_pds(g, min_repo_size=2)
    wdf, repos = wasserstein_distance_matrix(pds, dim=1)
    # The matrix is upper-triangular, so self-distances aren't included
    # — instead we check identical-shape repos are close.
    same_shape = wdf.filter((pl.col("repo_a") == "r1") & (pl.col("repo_b") == "r2"))
    assert same_shape.height == 1
    # Two isomorphic 6-cycles should have Wasserstein distance ≈ 0.
    assert same_shape["distance"][0] < 1e-6


def test_wasserstein_distinguishes_shapes() -> None:
    """A repo with a cycle should be farther from a repo with no cycles
    than from a repo with the same cycle."""
    g = _graph_with(
        {
            "loopy_a": _build_cycle("loopy_a", 6),
            "loopy_b": _build_cycle("loopy_b", 6),
            "tree": _build_tree("tree", 6),
        }
    )
    _, pds, _ = compute_shape_pds(g, min_repo_size=2)
    wdf, _ = wasserstein_distance_matrix(pds, dim=1)
    d_same = wdf.filter(
        (pl.col("repo_a") == "loopy_a") & (pl.col("repo_b") == "loopy_b")
    )["distance"][0]
    d_diff = wdf.filter(
        ((pl.col("repo_a") == "loopy_a") & (pl.col("repo_b") == "tree"))
        | ((pl.col("repo_a") == "tree") & (pl.col("repo_b") == "loopy_a"))
    )["distance"][0]
    assert d_same < d_diff, f"d_same={d_same} d_diff={d_diff}"


def test_skip_small_repos() -> None:
    """Repos under min_repo_size are skipped silently."""
    g = nx.MultiDiGraph()
    g.add_node("a", repo="tiny", qualified_name="a", kind="class")
    g.add_node("b", repo="tiny", qualified_name="b", kind="class")
    g.add_edge("a", "b", key="CALLS", kind="CALLS")
    df, _, stats = compute_shape_pds(g, min_repo_size=8)
    assert df.height == 0
    assert stats.n_repos == 0


def test_subsampling_records_repo() -> None:
    """Large repos get subsampled and the repo name is recorded."""
    g = _graph_with({"big": _build_cycle("big", 100)})
    _, _, stats = compute_shape_pds(g, max_nodes_per_repo=20, min_repo_size=2)
    assert "big" in stats.sampled_repos


def test_stats_records_telemetry() -> None:
    g = _graph_with({"r1": _build_cycle("r1", 6), "r2": _build_tree("r2", 8)})
    _, _, stats = compute_shape_pds(g, min_repo_size=2)
    assert stats.n_repos == 2
    assert stats.seconds > 0
    assert stats.n_points_total > 0
