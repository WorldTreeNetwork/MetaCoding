"""Tests for the typed 3-node motif miner."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.motif_mining import (
    DEFAULT_INTERESTING_KINDS,
    mine_motifs,
    write_motif_instances,
    write_motifs,
)
from ctkr.schema import (
    MOTIF_INSTANCES_COLUMNS,
    MOTIFS_COLUMNS,
    MotifInstanceRow,
    MotifRow,
)


def _wedge_graph() -> nx.MultiDiGraph:
    """Single 'abstract base + 2 concrete impls' wedge."""
    g = nx.MultiDiGraph()
    g.add_node("Base", repo="r1", kind="interface", file="src/base.py", line=10)
    g.add_node("ConcA", repo="r1", kind="class", file="src/concA.py", line=5)
    g.add_node("ConcB", repo="r1", kind="class", file="src/concB.py", line=5)
    g.add_edge("ConcA", "Base", key="IMPLEMENTS", kind="IMPLEMENTS")
    g.add_edge("ConcB", "Base", key="IMPLEMENTS", kind="IMPLEMENTS")
    return g


def _replicate_wedge(n_repos: int) -> nx.MultiDiGraph:
    """N copies of the wedge across N repos — perfect cross-repo support."""
    g = nx.MultiDiGraph()
    for i in range(n_repos):
        prefix = f"r{i}"
        g.add_node(
            f"{prefix}-Base",
            repo=prefix,
            kind="interface",
            file="src/base.py",
            line=10,
        )
        g.add_node(
            f"{prefix}-A",
            repo=prefix,
            kind="class",
            file="src/a.py",
            line=5,
        )
        g.add_node(
            f"{prefix}-B",
            repo=prefix,
            kind="class",
            file="src/b.py",
            line=5,
        )
        g.add_edge(f"{prefix}-A", f"{prefix}-Base", key="IMPLEMENTS", kind="IMPLEMENTS")
        g.add_edge(f"{prefix}-B", f"{prefix}-Base", key="IMPLEMENTS", kind="IMPLEMENTS")
    return g


# ----- enumeration correctness -----


def test_wedge_detected_with_correct_support() -> None:
    """A wedge of {ConcA, ConcB} IMPLEMENTS Base should produce one W motif."""
    g = _replicate_wedge(n_repos=6)
    motifs, instances, stats = mine_motifs(g, min_support=2)

    # Find the W (wedge) motif.
    wedges = motifs.filter(motifs["signature"].str.starts_with("W"))
    assert wedges.height >= 1, motifs
    # 6 anchors (one per repo).
    w = wedges.row(0, named=True)
    assert w["support"] == 6
    assert set(w["repo_coverage"]) == {f"r{i}" for i in range(6)}
    assert w["size_nodes"] == 3
    assert w["size_edges"] == 2


def test_path_motif_detected() -> None:
    """Path: class -CONTAINS-> method -CALLS-> function."""
    g = nx.MultiDiGraph()
    for i in range(8):
        prefix = f"r{i}"
        g.add_node(f"{prefix}-C", repo=prefix, kind="class", file="a.py", line=1)
        g.add_node(f"{prefix}-M", repo=prefix, kind="method", file="a.py", line=5)
        g.add_node(f"{prefix}-F", repo=prefix, kind="function", file="b.py", line=2)
        g.add_edge(f"{prefix}-C", f"{prefix}-M", key="CONTAINS", kind="CONTAINS")
        g.add_edge(f"{prefix}-M", f"{prefix}-F", key="CALLS", kind="CALLS")

    motifs, _, _ = mine_motifs(g, min_support=2)
    paths = motifs.filter(motifs["signature"].str.starts_with("path"))
    # Should detect the class→method→function path.
    sigs = [r["signature"] for r in paths.iter_rows(named=True)]
    assert any("CONTAINS" in s and "CALLS" in s for s in sigs), sigs


def test_min_support_filters_rare_motifs() -> None:
    g = _replicate_wedge(n_repos=3)
    rare, _, _ = mine_motifs(g, min_support=5)
    assert rare.height == 0, "wedge present 3 times shouldn't pass support=5"


def test_max_instances_per_motif_cap() -> None:
    """When a motif has many instances, only the first N anchors are kept."""
    g = _replicate_wedge(n_repos=10)
    _, instances, _ = mine_motifs(g, min_support=2, max_instances_per_motif=3)
    # Each wedge has one anchor per repo, so 10 candidates; cap to 3.
    assert instances.height <= 3 + 10  # path/V signatures may also produce rows
    # Wedge-specific count:
    by_motif = instances.group_by("motif_id").agg(pl.len().alias("n"))
    assert by_motif["n"].max() <= 3


# ----- schema and IO -----


def test_motifs_schema_pydantic() -> None:
    g = _replicate_wedge(6)
    motifs, _, _ = mine_motifs(g, min_support=2)
    assert list(motifs.columns) == list(MOTIFS_COLUMNS)
    for d in motifs.to_dicts():
        MotifRow.model_validate(d)


def test_instances_schema_pydantic() -> None:
    g = _replicate_wedge(6)
    _, instances, _ = mine_motifs(g, min_support=2)
    assert list(instances.columns) == list(MOTIF_INSTANCES_COLUMNS)
    for d in instances.to_dicts():
        MotifInstanceRow.model_validate(d)


def test_parquet_roundtrip(tmp_path: Path) -> None:
    g = _replicate_wedge(6)
    m, i, _ = mine_motifs(g, min_support=2)
    write_motifs(m, tmp_path / "motifs.parquet")
    write_motif_instances(i, tmp_path / "motif_instances.parquet")
    mb = pl.read_parquet(tmp_path / "motifs.parquet")
    ib = pl.read_parquet(tmp_path / "motif_instances.parquet")
    assert mb.height == m.height
    assert ib.height == i.height


def test_motif_id_deterministic() -> None:
    g = _replicate_wedge(5)
    m1, _, _ = mine_motifs(g, min_support=2)
    m2, _, _ = mine_motifs(g, min_support=2)
    assert sorted(m1["motif_id"].to_list()) == sorted(m2["motif_id"].to_list())


def test_kind_filter_excludes_others() -> None:
    """Anchor must have one of the interesting kinds."""
    g = nx.MultiDiGraph()
    for i in range(6):
        g.add_node(
            f"p{i}",
            repo=f"r{i}",
            kind="parameter",
            file="a.py",
            line=1,
        )
        g.add_node(
            f"c{i}",
            repo=f"r{i}",
            kind="class",
            file="a.py",
            line=1,
        )
        g.add_node(
            f"d{i}",
            repo=f"r{i}",
            kind="class",
            file="a.py",
            line=1,
        )
        # Path through a parameter — should be excluded by default.
        g.add_edge(f"c{i}", f"p{i}", key="CONTAINS", kind="CONTAINS")
        g.add_edge(f"p{i}", f"d{i}", key="REFERENCES", kind="REFERENCES")

    m_default, _, _ = mine_motifs(g, min_support=2)
    m_all, _, _ = mine_motifs(g, min_support=2, interesting_kinds=None)
    # With the default filter, parameter-centered paths are missed; opening up surfaces them.
    assert m_all.height >= m_default.height


def test_empty_graph_returns_empty_artifacts() -> None:
    g = nx.MultiDiGraph()
    m, i, stats = mine_motifs(g)
    assert list(m.columns) == list(MOTIFS_COLUMNS)
    assert list(i.columns) == list(MOTIF_INSTANCES_COLUMNS)
    assert m.height == 0 and i.height == 0
    assert stats.n_signatures_seen == 0


def test_default_interesting_kinds_includes_class() -> None:
    assert "class" in DEFAULT_INTERESTING_KINDS
    assert "interface" in DEFAULT_INTERESTING_KINDS
    assert "parameter" not in DEFAULT_INTERESTING_KINDS


# ----- cross-repo balance -----


def _skewed_wedge_graph(n_alpha_wedges: int, n_other_repos: int) -> nx.MultiDiGraph:
    """One repo (``alpha``) with many wedges; other repos with one each.

    Models the real-world bug: if the iteration order surfaces ``alpha``'s
    nodes first and the cap is small, the rare repos lose representation
    entirely. With the balanced sampler, each represented repo should
    contribute at least one anchor as long as cap >= n_repos.
    """
    g = nx.MultiDiGraph()
    # alpha gets many wedges
    for i in range(n_alpha_wedges):
        g.add_node(
            f"alpha-Base{i}", repo="alpha", kind="interface", file="b.py", line=1
        )
        g.add_node(f"alpha-A{i}", repo="alpha", kind="class", file="a.py", line=1)
        g.add_node(f"alpha-B{i}", repo="alpha", kind="class", file="b.py", line=1)
        g.add_edge(
            f"alpha-A{i}", f"alpha-Base{i}", key="IMPLEMENTS", kind="IMPLEMENTS"
        )
        g.add_edge(
            f"alpha-B{i}", f"alpha-Base{i}", key="IMPLEMENTS", kind="IMPLEMENTS"
        )
    # Each other repo gets exactly one wedge.
    for j in range(n_other_repos):
        repo = f"repo{j}"
        g.add_node(f"{repo}-Base", repo=repo, kind="interface", file="b.py", line=1)
        g.add_node(f"{repo}-A", repo=repo, kind="class", file="a.py", line=1)
        g.add_node(f"{repo}-B", repo=repo, kind="class", file="b.py", line=1)
        g.add_edge(
            f"{repo}-A", f"{repo}-Base", key="IMPLEMENTS", kind="IMPLEMENTS"
        )
        g.add_edge(
            f"{repo}-B", f"{repo}-Base", key="IMPLEMENTS", kind="IMPLEMENTS"
        )
    return g


def test_instances_balanced_across_repos_under_cap() -> None:
    """Multi-repo motif must surface every repo, not just the heavy one."""
    g = _skewed_wedge_graph(n_alpha_wedges=20, n_other_repos=5)
    # 25 candidate anchors total; cap at 6 so we must drop some.
    _, instances, _ = mine_motifs(g, min_support=2, max_instances_per_motif=6)
    # The wedge motif is the only one (all anchors are interfaces with
    # exactly two IMPLEMENTS in-edges).
    repos_seen = set(instances["repo"].to_list())
    expected_min = {"alpha", "repo0", "repo1", "repo2", "repo3", "repo4"}
    # With cap=6 and 6 repos, the round-robin should hit every repo at
    # least once.
    assert expected_min.issubset(repos_seen), (
        f"missing repos in instances: {expected_min - repos_seen}"
    )


def test_balanced_anchors_helper_deterministic() -> None:
    """The internal round-robin must be order-stable across calls."""
    from ctkr.motif_mining import _balanced_anchors

    by_repo = {
        "b": ["b1", "b2", "b3"],
        "a": ["a1", "a2"],
        "c": ["c1", "c2", "c3", "c4"],
    }
    out1 = _balanced_anchors(by_repo, cap=6)
    out2 = _balanced_anchors(by_repo, cap=6)
    assert out1 == out2
    # Order: sorted repos = a, b, c. Round 1: a1, b1, c1. Round 2: a2, b2, c2.
    assert out1 == ["a1", "b1", "c1", "a2", "b2", "c2"]


def test_balanced_anchors_drains_remaining_after_short_buckets() -> None:
    """When a repo runs out, others keep contributing until cap met."""
    from ctkr.motif_mining import _balanced_anchors

    by_repo = {"a": ["a1"], "b": ["b1", "b2", "b3", "b4"]}
    out = _balanced_anchors(by_repo, cap=4)
    # Round 1: a1, b1. Round 2: b2 (a empty). Round 3: b3.
    assert out == ["a1", "b1", "b2", "b3"]


def test_balanced_anchors_empty_input() -> None:
    from ctkr.motif_mining import _balanced_anchors

    assert _balanced_anchors({}, cap=10) == []
    assert _balanced_anchors({"a": ["x"]}, cap=0) == []
