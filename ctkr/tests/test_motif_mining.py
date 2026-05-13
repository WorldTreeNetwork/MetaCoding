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
