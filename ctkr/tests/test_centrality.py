"""Tests for centrality + per-repo community decomposition."""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import polars as pl
import pytest

from ctkr.centrality import (
    compute_centrality,
    compute_clusters,
    write_centrality,
    write_clusters,
)
from ctkr.schema import (
    CENTRALITY_COLUMNS,
    SPECTRAL_CLUSTERS_COLUMNS,
    CentralityRow,
    SpectralClusterRow,
)


def _two_clusters() -> nx.MultiDiGraph:
    """Two tightly-connected clusters of 8 nodes joined by one bridge."""
    g = nx.MultiDiGraph()
    for i in range(8):
        g.add_node(f"a{i}", repo="r1", qualified_name=f"A{i}", kind="class")
    for i in range(8):
        g.add_node(f"b{i}", repo="r2", qualified_name=f"B{i}", kind="class")
    for i in range(8):
        for j in range(8):
            if i != j:
                g.add_edge(f"a{i}", f"a{j}", key="CALLS", kind="CALLS")
                g.add_edge(f"b{i}", f"b{j}", key="CALLS", kind="CALLS")
    g.add_edge("a0", "b0", key="CALLS", kind="CALLS")  # bridge
    return g


# ----- centrality -----


def test_centrality_basic_run_and_schema() -> None:
    g = _two_clusters()
    df, stats = compute_centrality(g, betweenness_k=8)
    assert list(df.columns) == list(CENTRALITY_COLUMNS)
    assert df.height == 16
    assert stats.n_nodes == 16
    for d in df.to_dicts():
        CentralityRow.model_validate(d)


def test_centrality_pagerank_sums_near_one() -> None:
    g = _two_clusters()
    df, _ = compute_centrality(g, betweenness_k=8)
    pr_sum = df["pagerank"].sum()
    # NetworkX normalizes pagerank so it sums to 1 over the graph.
    assert 0.99 < pr_sum < 1.01


def test_centrality_bridge_is_high_betweenness() -> None:
    """a0 and b0 sit on every path between the two clusters → high
    betweenness."""
    g = _two_clusters()
    df, _ = compute_centrality(g, betweenness_k=16)  # full enumeration on this small graph
    rows = {r["symbol_id"]: r["betweenness"] for r in df.to_dicts()}
    bridge_avg = (rows["a0"] + rows["b0"]) / 2
    other_avg = sum(rows[n] for n in rows if n not in {"a0", "b0"}) / 14
    assert bridge_avg > other_avg, f"bridge={bridge_avg} other={other_avg}"


def test_centrality_eigenvector_converges_on_connected() -> None:
    g = _two_clusters()
    _, stats = compute_centrality(g, betweenness_k=8)
    assert stats.eigenvector_converged is True


def test_centrality_write_roundtrip(tmp_path: Path) -> None:
    g = _two_clusters()
    df, _ = compute_centrality(g, betweenness_k=8)
    out = tmp_path / "centrality.parquet"
    write_centrality(df, out)
    back = pl.read_parquet(out)
    assert list(back.columns) == list(CENTRALITY_COLUMNS)
    assert back.height == df.height
    for d in back.to_dicts():
        CentralityRow.model_validate(d)


# ----- clusters -----


def test_clusters_basic_run_and_schema() -> None:
    g = _two_clusters()
    df, stats = compute_clusters(g)
    assert list(df.columns) == list(SPECTRAL_CLUSTERS_COLUMNS)
    assert df.height == 16
    assert stats.n_repos == 2
    for d in df.to_dicts():
        SpectralClusterRow.model_validate(d)


def test_clusters_recover_two_repos() -> None:
    """Each repo is internally one tight cluster of 8 nodes."""
    g = _two_clusters()
    df, _ = compute_clusters(g)
    by_repo = df.group_by("repo").agg(pl.col("cluster_id").n_unique().alias("n_clusters"))
    # Each repo's subgraph is one fully-connected component → one cluster each.
    for row in by_repo.iter_rows(named=True):
        assert row["n_clusters"] == 1


def test_clusters_skip_small_repos() -> None:
    g = _two_clusters()
    g.add_node("tiny1", repo="tiny", qualified_name="T1", kind="class")
    g.add_node("tiny2", repo="tiny", qualified_name="T2", kind="class")
    df, stats = compute_clusters(g, min_repo_size=4)
    # `tiny` repo has 2 nodes, below threshold → no rows.
    assert "tiny" not in set(df["repo"].to_list())
    assert stats.n_repos == 2  # 'tiny' filtered out


def test_clusters_repos_filter() -> None:
    g = _two_clusters()
    df, stats = compute_clusters(g, repos=["r1"])
    assert set(df["repo"].to_list()) == {"r1"}
    assert stats.n_repos == 1


def test_clusters_write_roundtrip(tmp_path: Path) -> None:
    g = _two_clusters()
    df, _ = compute_clusters(g)
    out = tmp_path / "spectral_clusters.parquet"
    write_clusters(df, out)
    back = pl.read_parquet(out)
    assert list(back.columns) == list(SPECTRAL_CLUSTERS_COLUMNS)
    assert back.height == df.height


def test_clusters_cluster_id_zero_is_largest() -> None:
    """cluster_id=0 should be the largest community in each repo."""
    # 12 mutually-connected nodes + 4 isolated-but-tightly-connected
    # subcluster — Louvain should put the 12 as cluster_id=0.
    g = nx.MultiDiGraph()
    for i in range(12):
        g.add_node(f"big{i}", repo="r", qualified_name=f"Big{i}", kind="class")
    for i in range(12):
        for j in range(12):
            if i != j:
                g.add_edge(f"big{i}", f"big{j}", key="CALLS", kind="CALLS")
    for i in range(4):
        g.add_node(f"small{i}", repo="r", qualified_name=f"Small{i}", kind="class")
    for i in range(4):
        for j in range(4):
            if i != j:
                g.add_edge(f"small{i}", f"small{j}", key="CALLS", kind="CALLS")
    # One weak bridge keeps the subgraph connected.
    g.add_edge("big0", "small0", key="CALLS", kind="CALLS")

    df, _ = compute_clusters(g)
    rows = {r["symbol_id"]: r["cluster_id"] for r in df.to_dicts()}
    sizes = df.group_by("cluster_id").agg(pl.len().alias("n")).sort("cluster_id")
    # cluster_id 0 is largest.
    assert sizes.row(0, named=True)["n"] == sizes["n"].max()
