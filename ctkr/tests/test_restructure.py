"""Tests for the restructure-proposal generator (MetaCoding-9h5.12).

Hermetic: synthetic graphs + hand-built partition/feature frames. Pins the
declared-home resolution, SPLIT/MERGE disagreement detection, edge-justified
realign moves, and markdown rendering.
"""

from __future__ import annotations

import networkx as nx
import polars as pl

from ctkr.restructure import (
    build_restructure_proposal,
    render_proposal_md,
    write_proposal,
)


def _features(rows: list[tuple[str, str]]) -> pl.DataFrame:
    """rows = [(module_name, glob_prefix)] → a minimal features frame."""
    return pl.DataFrame(
        [
            {"name": name, "member_globs": [f"{prefix}/**"]}
            for name, prefix in rows
        ],
        schema={"name": pl.Utf8, "member_globs": pl.List(pl.Utf8)},
    )


def _partition(assign: dict[str, str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    from collections import Counter

    sizes = Counter(assign.values())
    mem = pl.DataFrame([{"symbol_id": k, "subsystem_id": v} for k, v in assign.items()])
    sub = pl.DataFrame(
        [
            {"subsystem_id": s, "repo": "R", "n_members": n, "persistence_score": 1.0}
            for s, n in sizes.items()
        ]
    )
    return sub, mem


def _mk_graph() -> nx.MultiDiGraph:
    """Module 'alpha' (a/**) is internally split by the graph into two islands; a
    lone element from 'beta' (b/**) is bound (by CALLS) to alpha's island I1."""
    g = nx.MultiDiGraph()

    def add(nid, file):
        g.add_node(nid, repo="R", qualified_name=f"{file}::{nid}", file=file, kind="class")

    for i in range(3):
        add(f"a1_{i}", "a/one.php")
    for i in range(3):
        add(f"a2_{i}", "a/two.php")
    add("b_stray", "b/stray.php")
    # dense CALLS within each alpha half
    for i in range(3):
        for j in range(3):
            if i != j:
                g.add_edge(f"a1_{i}", f"a1_{j}", key="CALLS", kind="CALLS")
                g.add_edge(f"a2_{i}", f"a2_{j}", key="CALLS", kind="CALLS")
    # b_stray is pulled into island I1 by two CALLS to a1 members, zero to its own module
    g.add_edge("b_stray", "a1_0", key="CALLS", kind="CALLS")
    g.add_edge("b_stray", "a1_1", key="CALLS", kind="CALLS")
    return g


# island I1 = alpha-half-one + the stray; I2 = alpha-half-two
ASSIGN = {
    "a1_0": "I1", "a1_1": "I1", "a1_2": "I1", "b_stray": "I1",
    "a2_0": "I2", "a2_1": "I2", "a2_2": "I2",
}
FEATURES = _features([("alpha", "a"), ("beta", "b")])


def test_split_disagreement_detected() -> None:
    g = _mk_graph()
    sub, mem = _partition(ASSIGN)
    p = build_restructure_proposal(g, mem, sub, FEATURES, generated_at="T")
    # alpha's symbols land in both I1 and I2 → a SPLIT
    splits = {d["module"]: d for d in p.split_disagreements}
    assert "alpha" in splits
    assert splits["alpha"]["n_islands"] == 2
    # beta maps to exactly one island → clean slice
    assert "beta" in p.clean_slices


def test_realign_move_for_stray_with_edge_justification() -> None:
    g = _mk_graph()
    sub, mem = _partition(ASSIGN)
    p = build_restructure_proposal(g, mem, sub, FEATURES, generated_at="T")
    # b_stray declared home 'beta', assigned island I1 whose dominant module is 'alpha'
    strays = [m for m in p.realign_moves if m.element_id == "b_stray"]
    assert len(strays) == 1
    mv = strays[0]
    assert mv.from_module == "beta"
    assert mv.cohesion_to_island == 2  # two CALLS into I1
    assert mv.coupling_to_home == 0  # no edges to other beta members
    assert "graph binds it to the island" in mv.justification


def test_merge_disagreement_when_island_absorbs_many_modules() -> None:
    g = nx.MultiDiGraph()
    for nid, f in [("x", "a/x.php"), ("y", "b/y.php")]:
        g.add_node(nid, repo="R", qualified_name=f"{f}::{nid}", file=f, kind="class")
    g.add_edge("x", "y", key="CALLS", kind="CALLS")
    assign = {"x": "IM", "y": "IM"}
    sub, mem = _partition(assign)
    feats = _features([("alpha", "a"), ("beta", "b")])
    p = build_restructure_proposal(g, mem, sub, feats, generated_at="T")
    # one island IM holds both declared modules alpha + beta → a MERGE
    assert len(p.merge_disagreements) == 1
    assert p.merge_disagreements[0]["n_declared_modules"] == 2


def test_render_md_has_sections_and_is_deterministic() -> None:
    g = _mk_graph()
    sub, mem = _partition(ASSIGN)
    p1 = build_restructure_proposal(g, mem, sub, FEATURES, generated_at="T")
    p2 = build_restructure_proposal(g, mem, sub, FEATURES, generated_at="T")
    md1 = render_proposal_md(p1)
    md2 = render_proposal_md(p2)
    assert md1 == md2  # deterministic
    assert "# Restructure proposal" in md1
    assert "## Proposed modules" in md1
    assert "## Realign moves" in md1


def test_write_proposal_roundtrips(tmp_path) -> None:
    g = _mk_graph()
    sub, mem = _partition(ASSIGN)
    p = build_restructure_proposal(g, mem, sub, FEATURES, generated_at="T")
    out = write_proposal(p, tmp_path / "restructure-proposal.md")
    assert out.exists()
    assert out.read_text(encoding="utf-8").startswith("# Restructure proposal")
