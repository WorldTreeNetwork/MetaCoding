"""Tests for ctkr entropy-check command (bead MetaCoding-ijo.4 fix)."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from ctkr.commands.entropy_check import run
from ctkr.graph_loader import EDGE_KINDS


def _sparse_graph() -> nx.MultiDiGraph:
    """A graph with very few edges to trigger a BLOCKED verdict,
    which exercises the recommendation code path."""
    g = nx.MultiDiGraph()
    # Only CONTAINS edges — low entropy, should trigger BLOCKED.
    g.add_node("f1", repo="r", qualified_name="r.f1", kind="file")
    g.add_node("m_a", repo="r", qualified_name="r.f1.m_a", kind="method")
    g.add_node("m_b", repo="r", qualified_name="r.f1.m_b", kind="method")
    g.add_edge("f1", "m_a", key="CONTAINS", kind="CONTAINS")
    g.add_edge("f1", "m_b", key="CONTAINS", kind="CONTAINS")
    return g


def test_blocked_recommendation_lists_only_absent_kinds(tmp_path: Path) -> None:
    """The BLOCKED recommendation must NOT name edge kinds that already
    exist in the graph. (Fixes MetaCoding-ijo.4 where READS_FIELD etc.
    were hardcoded despite being present.)"""
    g = _sparse_graph()

    # Write synthetic export.
    with (tmp_path / "nodes.jsonl").open("w") as f:
        for nid, attrs in g.nodes(data=True):
            f.write(json.dumps({"id": nid, **attrs}) + "\n")
    with (tmp_path / "edges.jsonl").open("w") as f:
        for src, dst, data in g.edges(data=True):
            f.write(json.dumps({"src_id": src, "dst_id": dst, "kind": data["kind"]}) + "\n")

    import argparse
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    args = argparse.Namespace(
        data_dir=str(tmp_path),
        as_json=False,
        sample_size=10,
        seed=42,
        top_k_profiles=5,
    )
    with redirect_stdout(buf):
        run(args)

    output = buf.getvalue()

    # Should be BLOCKED (very low entropy with only CONTAINS edges).
    assert "BLOCKED" in output

    # The recommendation must NOT mention CONTAINS (which is present).
    # It should mention absent kinds like CALLS, REFERENCES, etc.
    assert "CONTAINS" not in output.split("BLOCKED")[1]

    # Should mention at least one absent kind.
    absent = [ek for ek in EDGE_KINDS if ek != "CONTAINS"]
    mentioned_absent = [ek for ek in absent if ek in output]
    assert len(mentioned_absent) > 0, (
        f"Expected at least one absent edge kind in the recommendation, "
        f"but found none. Output: {output}"
    )


def _write_export(g: "nx.MultiDiGraph", tmp_path: Path) -> None:
    with (tmp_path / "nodes.jsonl").open("w") as f:
        for nid, attrs in g.nodes(data=True):
            f.write(json.dumps({"id": nid, **attrs}) + "\n")
    with (tmp_path / "edges.jsonl").open("w") as f:
        for src, dst, data in g.edges(data=True):
            f.write(json.dumps({"src_id": src, "dst_id": dst, "kind": data["kind"]}) + "\n")


def _run_entropy(tmp_path: Path, kind_weight: list[str] | None) -> str:
    import argparse
    import io
    from contextlib import redirect_stdout

    buf = io.StringIO()
    args = argparse.Namespace(
        data_dir=str(tmp_path),
        as_json=False,
        sample_size=10,
        seed=42,
        top_k_profiles=5,
        kind_weight=kind_weight,
    )
    with redirect_stdout(buf):
        run(args)
    return buf.getvalue()


def _entropy_of(output: str) -> float:
    import re

    m = re.search(r"shannon_entropy=([0-9.]+)", output)
    assert m, f"no shannon_entropy in output: {output}"
    return float(m.group(1))


def test_kind_weight_is_not_ignored(tmp_path: Path) -> None:
    """entropy-check must honor --kind-weight (it previously recomputed from
    the raw graph and ignored weighting entirely). Zeroing CONTAINS here MERGES
    the x* nodes into the y* class, which strictly lowers Shannon entropy."""
    g = nx.MultiDiGraph()
    g.add_node("src", repo="r", qualified_name="r.src", kind="method")
    # x* nodes: one CONTAINS-in + one REFERENCES-in → profile [CONT, REF].
    # y* nodes: REFERENCES-in only → profile [REF]. Distinct while CONTAINS=1.
    for i in range(3):
        x, y = f"x{i}", f"y{i}"
        g.add_node(x, repo="r", qualified_name=f"r.x{i}", kind="method")
        g.add_node(y, repo="r", qualified_name=f"r.y{i}", kind="method")
        g.add_edge("src", x, key=f"c{i}", kind="CONTAINS")
        g.add_edge("src", x, key=f"rx{i}", kind="REFERENCES")
        g.add_edge("src", y, key=f"ry{i}", kind="REFERENCES")
    _write_export(g, tmp_path)

    baseline = _entropy_of(_run_entropy(tmp_path, None))
    zeroed = _entropy_of(_run_entropy(tmp_path, ["CONTAINS=0.0"]))

    # With CONTAINS present, x* and y* are distinct profiles; zeroing CONTAINS
    # collapses x* onto y*, so entropy must strictly drop. If weighting were
    # ignored (the bug), these would be equal.
    assert zeroed < baseline, (
        f"expected weighted entropy < baseline, got zeroed={zeroed} "
        f"baseline={baseline} — --kind-weight is being ignored"
    )
