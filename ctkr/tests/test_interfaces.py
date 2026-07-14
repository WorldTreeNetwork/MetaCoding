"""Tests for interface + data-shape extraction (Stage B / §3, T2).

Hermetic: a small synthetic two-subsystem graph, no external corpus. The
src/ctkr acceptance run (precision/recall on the real self-index) lives in the
task evidence, not here — these pin the mechanism.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.interfaces import (
    compute_interfaces,
    write_data_shapes,
    write_interfaces,
)
from ctkr.schema import (
    DATA_SHAPES_COLUMNS,
    INTERFACES_COLUMNS,
    SUBSYSTEM_MEMBERS_COLUMNS,
    DataShapeRow,
    InterfaceRow,
)

FIXED_TS = "2026-07-14T00:00:00Z"


def _two_subsystem_graph() -> tuple[nx.MultiDiGraph, pl.DataFrame]:
    """Subsystem A (``a/svc.ts``) exposes an API; subsystem B (``b/main.ts``)
    consumes it. Returns ``(graph, members_df)``.

    A provides:
    - ``apiFn``          — referenced by B (provides / API surface).
    - ``AConfig``        — constructed by B + a field read by B (boundary type).
    - ``AConfig::x``     — read by B (external), written by A's ``helper``
                            (internal): an *output contract* field.
    A internal (must NOT be boundary): ``AInternal`` (private type),
    ``helper`` (private fn).
    """
    g = nx.MultiDiGraph()

    def add(nid: str, qn: str, file: str, kind: str) -> None:
        g.add_node(nid, repo="R", qualified_name=qn, file=file, kind=kind,
                   short_name=qn.split("::")[-1])

    # ── subsystem A ──
    add("aF", "a/svc.ts", "a/svc.ts", "file")
    add("apiFn", "a/svc.ts::apiFn", "a/svc.ts", "function")
    add("AConfig", "a/svc.ts::AConfig", "a/svc.ts", "class")
    add("acx", "a/svc.ts::AConfig::x", "a/svc.ts", "field")
    add("acy", "a/svc.ts::AConfig::y", "a/svc.ts", "field")
    add("helper", "a/svc.ts::helper", "a/svc.ts", "function")
    add("AInternal", "a/svc.ts::AInternal", "a/svc.ts", "class")
    add("aif", "a/svc.ts::AInternal::f", "a/svc.ts", "field")
    for child in ("apiFn", "AConfig", "helper", "AInternal"):
        g.add_edge("aF", child, key="CONTAINS", kind="CONTAINS")
    g.add_edge("AConfig", "acx", key="CONTAINS", kind="CONTAINS")
    g.add_edge("AConfig", "acy", key="CONTAINS", kind="CONTAINS")
    g.add_edge("AInternal", "aif", key="CONTAINS", kind="CONTAINS")
    # A-internal wiring
    g.add_edge("helper", "acx", key="WRITES_FIELD", kind="WRITES_FIELD")  # writes x
    g.add_edge("apiFn", "acy", key="READS_FIELD", kind="READS_FIELD")     # reads y (internal)
    g.add_edge("acx", "AInternal", key="TYPE_OF", kind="TYPE_OF")         # x: AInternal
    g.add_edge("helper", "aif", key="READS_FIELD", kind="READS_FIELD")    # internal field read

    # ── subsystem B ──
    add("bF", "b/main.ts", "b/main.ts", "file")
    add("bMain", "b/main.ts::bMain", "b/main.ts", "function")
    g.add_edge("bF", "bMain", key="CONTAINS", kind="CONTAINS")
    # cross-boundary B → A (provides for A / consumes for B)
    g.add_edge("bMain", "apiFn", key="REFERENCES", kind="REFERENCES")     # calls the API
    g.add_edge("bMain", "AConfig", key="CONSTRUCTS", kind="CONSTRUCTS")   # constructs config
    g.add_edge("bMain", "acx", key="READS_FIELD", kind="READS_FIELD")     # reads x (external)

    rows = []
    for n, d in g.nodes(data=True):
        sub = "ss:A" if d["file"].startswith("a/") else "ss:B"
        rows.append({
            "subsystem_id": sub, "symbol_id": n, "repo": "R",
            "qualified_name": d["qualified_name"], "boundary_confidence": 1.0,
            "placement": "structural", "schema_version": 1,
        })
    mem = pl.DataFrame(rows).select(SUBSYSTEM_MEMBERS_COLUMNS)
    return g, mem


def test_interfaces_schema_and_validation() -> None:
    g, mem = _two_subsystem_graph()
    iface, data, _ = compute_interfaces(g, mem, generated_at=FIXED_TS)
    assert list(iface.columns) == list(INTERFACES_COLUMNS)
    assert list(data.columns) == list(DATA_SHAPES_COLUMNS)
    for d in iface.to_dicts():
        InterfaceRow.model_validate(d)
    for d in data.to_dicts():
        DataShapeRow.model_validate(d)


def test_provides_and_consumes_are_dual() -> None:
    """Every cross-boundary edge yields a provides row for the target's
    subsystem and a consumes row for the source's subsystem."""
    g, mem = _two_subsystem_graph()
    iface, _, _ = compute_interfaces(g, mem, generated_at=FIXED_TS)
    provA = iface.filter((pl.col("subsystem_id") == "ss:A") & (pl.col("direction") == "provides"))
    consB = iface.filter((pl.col("subsystem_id") == "ss:B") & (pl.col("direction") == "consumes"))
    # three crossing edges → three provides for A, three consumes for B
    assert provA.height == 3
    assert consB.height == 3
    # apiFn is provided by A (its API surface)
    assert "a/svc.ts::apiFn" in provA["internal_qualified_name"].to_list()
    # B consumes into subsystem A
    assert set(consB["external_subsystem_id"].to_list()) == {"ss:A"}


def test_contains_is_not_a_contract_morphism() -> None:
    g, mem = _two_subsystem_graph()
    iface, _, _ = compute_interfaces(g, mem, generated_at=FIXED_TS)
    assert "CONTAINS" not in iface["edge_kind"].to_list()


def test_nested_member_rolls_up_to_top_level_export() -> None:
    """A crossing edge onto ``AConfig::x`` reports the export as ``AConfig``."""
    g, mem = _two_subsystem_graph()
    iface, _, _ = compute_interfaces(g, mem, generated_at=FIXED_TS)
    row = iface.filter(pl.col("internal_qualified_name") == "a/svc.ts::AConfig::x").to_dicts()[0]
    assert row["internal_export_qualified_name"] == "a/svc.ts::AConfig"
    assert row["internal_export_symbol_id"] == "AConfig"


def test_boundary_vs_internal_data_shapes() -> None:
    g, mem = _two_subsystem_graph()
    _, data, _ = compute_interfaces(g, mem, generated_at=FIXED_TS)
    dA = data.filter(pl.col("subsystem_id") == "ss:A")
    boundary = set(dA.filter(pl.col("boundary"))["type_qualified_name"].to_list())
    internal = set(dA.filter(~pl.col("boundary"))["type_qualified_name"].to_list())
    # AConfig crosses the boundary (constructed + field read externally).
    assert "a/svc.ts::AConfig" in boundary
    # AInternal is private — never crosses.
    assert "a/svc.ts::AInternal" in internal
    assert "a/svc.ts::AConfig" not in internal


def test_field_flow_direction_recovers_output_contract() -> None:
    """``AConfig::x`` is written by A internally and read by B externally: an
    output contract (written_by_internal & read_by_external)."""
    g, mem = _two_subsystem_graph()
    _, data, _ = compute_interfaces(g, mem, generated_at=FIXED_TS)
    x = data.filter(pl.col("field_name") == "x").to_dicts()[0]
    assert x["written_by_internal"] is True
    assert x["read_by_external"] is True
    assert x["read_by_internal"] is False
    assert x["written_by_external"] is False
    # field type recovered from the TYPE_OF edge
    assert x["field_type"] == "a/svc.ts::AInternal"
    # AConfig is constructed by bMain
    assert "b/main.ts::bMain" in x["constructed_by"]


def test_alphabet_coverage_note_emitted_per_repo() -> None:
    g, mem = _two_subsystem_graph()
    _, _, stats = compute_interfaces(g, mem, generated_at=FIXED_TS)
    assert "R" in stats.alphabet_coverage
    cov = stats.alphabet_coverage["R"]
    assert "note" in cov and "data-edge kinds" in cov["note"]
    # this fixture has TYPE_OF, CONSTRUCTS, READS_FIELD, WRITES_FIELD present
    present = {k for k, c in cov["data_edge_kinds"].items() if c > 0}
    assert {"TYPE_OF", "CONSTRUCTS", "READS_FIELD", "WRITES_FIELD"} <= present


def test_interfaces_deterministic_byte_identical(tmp_path: Path) -> None:
    g, mem = _two_subsystem_graph()
    for tag in ("run1", "run2"):
        iface, data, _ = compute_interfaces(g, mem, generated_at=FIXED_TS)
        write_interfaces(iface, tmp_path / f"iface_{tag}.parquet")
        write_data_shapes(data, tmp_path / f"data_{tag}.parquet")
    assert (tmp_path / "iface_run1.parquet").read_bytes() == (
        tmp_path / "iface_run2.parquet"
    ).read_bytes()
    assert (tmp_path / "data_run1.parquet").read_bytes() == (
        tmp_path / "data_run2.parquet"
    ).read_bytes()
