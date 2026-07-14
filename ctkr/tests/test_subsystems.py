"""Tests for the subsystem partition (Stage A / DECOMPOSE, T1).

Pure-Louvain path — no scipy dependency (Louvain ships in networkx), so these
run in the base ctkr venv unlike the centrality tests.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.schema import (
    SUBSYSTEM_MEMBERS_COLUMNS,
    SUBSYSTEMS_COLUMNS,
    SubsystemMemberRow,
    SubsystemRow,
)
from ctkr.subsystems import (
    compute_subsystems,
    write_subsystem_members,
    write_subsystems,
)

FIXED_TS = "2026-07-14T00:00:00Z"


def _two_dir_graph(*, with_isolate: bool = True) -> nx.MultiDiGraph:
    """Two directory-cohesive clusters joined by one weak bridge.

    Cluster A lives under ``a/mod`` (a file + 6 methods), cluster B under
    ``b/mod``. Each cluster is internally dense (CALLS), the two are joined by a
    single cross edge. An optional isolated symbol (no edges) sits in ``a/mod``.
    """
    g = nx.MultiDiGraph()

    def add(nid: str, qn: str, file: str, kind: str = "function") -> None:
        g.add_node(nid, repo="R", qualified_name=qn, file=file, kind=kind)

    add("aF", "a/mod/x.py", "a/mod/x.py", kind="file")
    for i in range(6):
        add(f"a{i}", f"a/mod/x.py::f{i}", "a/mod/x.py")
        g.add_edge("aF", f"a{i}", key="CONTAINS", kind="CONTAINS")
    add("bF", "b/mod/y.py", "b/mod/y.py", kind="file")
    for i in range(6):
        add(f"b{i}", f"b/mod/y.py::g{i}", "b/mod/y.py")
        g.add_edge("bF", f"b{i}", key="CONTAINS", kind="CONTAINS")
    for i in range(6):
        for j in range(6):
            if i != j:
                g.add_edge(f"a{i}", f"a{j}", key="CALLS", kind="CALLS")
                g.add_edge(f"b{i}", f"b{j}", key="CALLS", kind="CALLS")
    g.add_edge("a0", "b0", key="CALLS", kind="CALLS")  # weak bridge

    if with_isolate:
        # Zero-profile symbol: no edges at all, lives in a/mod.
        add("aIso", "a/mod/x.py::CONST", "a/mod/x.py", kind="variable")
    return g


def test_subsystems_basic_schema_and_validation() -> None:
    g = _two_dir_graph()
    sub_df, mem_df, stats = compute_subsystems(g, generated_at=FIXED_TS)
    assert list(sub_df.columns) == list(SUBSYSTEMS_COLUMNS)
    assert list(mem_df.columns) == list(SUBSYSTEM_MEMBERS_COLUMNS)
    for d in sub_df.to_dicts():
        SubsystemRow.model_validate(d)
    for d in mem_df.to_dicts():
        SubsystemMemberRow.model_validate(d)
    # Every real symbol appears in exactly one subsystem.
    assert mem_df.height == g.number_of_nodes()
    assert mem_df["symbol_id"].n_unique() == g.number_of_nodes()


def test_subsystems_recovers_two_directories() -> None:
    """The two directory-cohesive clusters land in separate subsystems."""
    g = _two_dir_graph(with_isolate=False)
    _, mem_df, _ = compute_subsystems(g, generated_at=FIXED_TS)
    assign = {r["symbol_id"]: r["subsystem_id"] for r in mem_df.iter_rows(named=True)}
    a_ids = {assign[n] for n in ["a0", "a1", "a2", "a3", "a4", "a5"]}
    b_ids = {assign[n] for n in ["b0", "b1", "b2", "b3", "b4", "b5"]}
    assert len(a_ids) == 1, f"cluster A split: {a_ids}"
    assert len(b_ids) == 1, f"cluster B split: {b_ids}"
    assert a_ids != b_ids, "the two directories collapsed into one subsystem"


def test_subsystems_isolated_symbol_is_locality_placed() -> None:
    """A zero-profile (edgeless) symbol is flagged placement='locality' and still
    lands in a subsystem (via its directory prior)."""
    g = _two_dir_graph(with_isolate=True)
    _, mem_df, stats = compute_subsystems(g, generated_at=FIXED_TS)
    iso = mem_df.filter(pl.col("symbol_id") == "aIso").to_dicts()[0]
    assert iso["placement"] == "locality"
    # It should share the subsystem of the a/mod cluster it lives in.
    a0 = mem_df.filter(pl.col("symbol_id") == "a0").to_dicts()[0]
    assert iso["subsystem_id"] == a0["subsystem_id"]
    # Connected symbols are structural.
    assert a0["placement"] == "structural"
    assert stats.n_locality == 1


def test_subsystems_boundary_confidence_and_persistence_bounded() -> None:
    g = _two_dir_graph()
    sub_df, mem_df, _ = compute_subsystems(g, generated_at=FIXED_TS)
    bc = mem_df["boundary_confidence"].to_list()
    assert all(0.0 <= x <= 1.0 for x in bc)
    ps = sub_df["persistence_score"].to_list()
    assert all(0.0 <= x <= 1.0 for x in ps)


def test_subsystems_deterministic_byte_identical(tmp_path: Path) -> None:
    """Same graph + same fixed timestamp → byte-identical parquet across runs."""
    g = _two_dir_graph()
    for tag in ("run1", "run2"):
        sub_df, mem_df, _ = compute_subsystems(g, generated_at=FIXED_TS)
        write_subsystems(sub_df, tmp_path / f"sub_{tag}.parquet")
        write_subsystem_members(mem_df, tmp_path / f"mem_{tag}.parquet")
    assert (tmp_path / "sub_run1.parquet").read_bytes() == (
        tmp_path / "sub_run2.parquet"
    ).read_bytes()
    assert (tmp_path / "mem_run1.parquet").read_bytes() == (
        tmp_path / "mem_run2.parquet"
    ).read_bytes()


def test_subsystems_id_is_content_addressed_not_time_dependent() -> None:
    """subsystem_id excludes generated_at — two different timestamps produce the
    same ids for the same partition."""
    g = _two_dir_graph()
    sub_a, _, _ = compute_subsystems(g, generated_at="2026-01-01T00:00:00Z")
    sub_b, _, _ = compute_subsystems(g, generated_at="2099-12-31T00:00:00Z")
    assert set(sub_a["subsystem_id"].to_list()) == set(sub_b["subsystem_id"].to_list())


def test_subsystems_skips_tiny_repos() -> None:
    g = nx.MultiDiGraph()
    g.add_node("x", repo="tiny", qualified_name="x", file="t/x.py", kind="function")
    g.add_node("y", repo="tiny", qualified_name="y", file="t/y.py", kind="function")
    sub_df, mem_df, stats = compute_subsystems(g, min_repo_size=4, generated_at=FIXED_TS)
    assert sub_df.height == 0
    assert mem_df.height == 0
    assert stats.n_repos == 0
