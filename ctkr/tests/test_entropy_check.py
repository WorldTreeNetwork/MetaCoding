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
