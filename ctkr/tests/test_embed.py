"""Tests for node2vec/DeepWalk embeddings.

These tests run only when the ``embed`` extra (gensim) is installed.
Network-scale tests of the real corpus live in a separate manual smoke
script — this file is fast, hermetic, and covers determinism + schema
contract.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

# gensim is the only dep we need to guard — its absence makes the
# entire `ctkr.embed` module unimportable.
gensim = pytest.importorskip("gensim", reason="install with `uv sync --extra embed`")

from ctkr.embed import (  # noqa: E402  — import after the guard
    DEFAULT_DIM,
    EmbedStats,
    compute_embeddings,
    write_embeddings,
)
from ctkr.schema import EMBEDDINGS_COLUMNS, EmbeddingRow  # noqa: E402


def _small_graph() -> nx.MultiDiGraph:
    """A 16-node toy graph: 2 clusters of 8 connected by a single edge."""
    g = nx.MultiDiGraph()
    for i in range(16):
        g.add_node(
            f"n{i}",
            repo="cluster0" if i < 8 else "cluster1",
            qualified_name=f"module.X{i}",
            kind="class",
        )
    # Dense intra-cluster CONTAINS edges.
    for i in range(8):
        for j in range(8):
            if i != j:
                g.add_edge(f"n{i}", f"n{j}", key="CONTAINS", kind="CONTAINS")
                g.add_edge(f"n{i + 8}", f"n{j + 8}", key="CONTAINS", kind="CONTAINS")
    # Single inter-cluster bridge.
    g.add_edge("n0", "n8", key="CALLS", kind="CALLS")
    return g


def test_basic_run_produces_schema_compliant_rows() -> None:
    g = _small_graph()
    df, stats = compute_embeddings(
        g, dim=16, num_walks=4, walk_length=8, epochs=2, seed=1, workers=1
    )
    assert list(df.columns) == list(EMBEDDINGS_COLUMNS)
    assert df.height == 16
    assert isinstance(stats, EmbedStats)
    assert stats.dim == 16
    assert stats.deterministic is True
    # Each row's vec must have the requested dim and validate through pydantic.
    for d in df.to_dicts():
        assert len(d["vec"]) == 16
        EmbeddingRow.model_validate(d)


def test_deterministic_with_seed() -> None:
    g = _small_graph()
    df1, _ = compute_embeddings(
        g, dim=16, num_walks=4, walk_length=8, epochs=2, seed=42, workers=1
    )
    df2, _ = compute_embeddings(
        g, dim=16, num_walks=4, walk_length=8, epochs=2, seed=42, workers=1
    )
    # Vectors should match bit-for-bit when workers=1.
    for a, b in zip(df1.iter_rows(named=True), df2.iter_rows(named=True), strict=False):
        assert a["symbol_id"] == b["symbol_id"]
        assert a["vec"] == b["vec"]


def test_different_seed_changes_embedding() -> None:
    g = _small_graph()
    df1, _ = compute_embeddings(
        g, dim=16, num_walks=4, walk_length=8, epochs=2, seed=1, workers=1
    )
    df2, _ = compute_embeddings(
        g, dim=16, num_walks=4, walk_length=8, epochs=2, seed=2, workers=1
    )
    # At least one row must differ — embeddings are seed-dependent.
    diffs = [
        (a, b)
        for a, b in zip(df1.iter_rows(named=True), df2.iter_rows(named=True), strict=False)
        if a["symbol_id"] == b["symbol_id"] and a["vec"] != b["vec"]
    ]
    assert diffs


def test_intra_cluster_neighbors_outrank_inter_cluster() -> None:
    """Sanity check — within a tightly-connected cluster, intra-cluster
    cosine similarity should beat the cross-cluster bridge."""
    import math

    g = _small_graph()
    df, _ = compute_embeddings(
        g, dim=16, num_walks=10, walk_length=10, epochs=10, seed=7, workers=1
    )
    rows = {r["symbol_id"]: r["vec"] for r in df.iter_rows(named=True)}

    def cos(a: list[float], b: list[float]) -> float:
        na = math.sqrt(sum(x * x for x in a))
        nb = math.sqrt(sum(x * x for x in b))
        if na == 0 or nb == 0:
            return 0.0
        return sum(x * y for x, y in zip(a, b)) / (na * nb)

    intra = cos(rows["n0"], rows["n1"])
    inter = cos(rows["n0"], rows["n8"])
    # Intra-cluster pairs share dense neighborhoods; inter-cluster sees
    # only the n0→n8 bridge. We expect intra > inter by a clear margin.
    assert intra > inter, f"intra={intra}, inter={inter}"


def test_node_filter_restricts_output() -> None:
    g = _small_graph()
    df, stats = compute_embeddings(
        g,
        dim=16,
        num_walks=4,
        walk_length=8,
        epochs=2,
        seed=1,
        workers=1,
        node_filter=["n0", "n1", "n8"],
    )
    assert stats.n_nodes == 3
    assert df.height == 3
    assert set(df["symbol_id"].to_list()) == {"n0", "n1", "n8"}


def test_write_embeddings_roundtrip(tmp_path: Path) -> None:
    import polars as pl

    g = _small_graph()
    df, _ = compute_embeddings(g, dim=8, num_walks=2, walk_length=4, epochs=1, seed=1)
    out = tmp_path / "embeddings.parquet"
    write_embeddings(df, out)
    back = pl.read_parquet(out)
    assert list(back.columns) == list(EMBEDDINGS_COLUMNS)
    assert back.height == df.height
    # Round-trip preserves dim.
    assert len(back["vec"][0]) == 8
    # Float32 cast survives the round trip.
    assert back.schema["vec"] == pl.List(pl.Float32)


def test_stats_records_timing() -> None:
    g = _small_graph()
    _, stats = compute_embeddings(g, dim=8, num_walks=2, walk_length=4, epochs=1, seed=1)
    assert stats.walk_seconds >= 0.0
    assert stats.train_seconds >= 0.0
    assert stats.total_seconds >= stats.walk_seconds + stats.train_seconds - 0.01


def test_default_dim_matches_issue_spec() -> None:
    """Issue Orchestrators-7u7 pins dim=128."""
    assert DEFAULT_DIM == 128


def test_isolated_node_does_not_crash() -> None:
    """A node with no neighbors generates length-1 walks. The pipeline
    must not crash; whether the isolated node appears in the output
    depends on min_count and num_walks, but the connected ones must
    always be there."""
    g = nx.MultiDiGraph()
    g.add_node("alone", repo="x", qualified_name="alone", kind="class")
    g.add_node("a", repo="x", qualified_name="a", kind="class")
    g.add_node("b", repo="x", qualified_name="b", kind="class")
    g.add_edge("a", "b", key="CONTAINS", kind="CONTAINS")
    g.add_edge("b", "a", key="CONTAINS", kind="CONTAINS")
    df, _ = compute_embeddings(
        g, dim=8, num_walks=4, walk_length=4, epochs=2, seed=1, min_count=1
    )
    ids = set(df["symbol_id"].to_list())
    assert {"a", "b"}.issubset(ids), "connected nodes must always be embedded"
