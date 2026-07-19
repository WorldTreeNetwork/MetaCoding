"""Tests for boundary-quality evaluation (MetaCoding-9h5.12).

Hermetic: synthetic graphs + hand-built partition frames. Pins the framework vs
domain crossing-edge classification, per-island composition, the framework-graph
prune, the adjusted Rand index, and the stability diff (with a stub partitioner
so no Louvain runs here).
"""

from __future__ import annotations

import networkx as nx
import polars as pl

from ctkr.boundary_quality import (
    adjusted_rand_index,
    boundary_quality,
    classify_crossing_edges,
    framework_reason,
    is_framework_node,
    prune_framework_graph,
    stability_diff,
)


def _mk_graph() -> nx.MultiDiGraph:
    """Two domain islands (A, B) that each EXTENDS an external framework base, plus
    one genuine domain CALLS edge A→B. The external base is a third node."""
    g = nx.MultiDiGraph()

    def add(nid, qn, kind="class", file="", short=None):
        g.add_node(
            nid, repo="R", qualified_name=qn, file=file, kind=kind,
            short_name=short or qn.split("::")[-1],
        )

    # island A domain nodes
    add("a_base", "a/mod.php::AssetBase", file="a/mod.php")
    add("a1", "a/mod.php::AnimalAsset", file="a/mod.php")
    # island B domain nodes
    add("b_base", "b/mod.php::LogBase", file="b/mod.php")
    add("b1", "b/mod.php::BirthLog", file="b/mod.php")
    # external framework base (resolved outside repo)
    add("ext", "external::ContentEntityBase", file="")

    # framework idioms: both domain bases EXTENDS the external base (crosses A/B→ext island)
    g.add_edge("a_base", "ext", key="EXTENDS", kind="EXTENDS")
    g.add_edge("b_base", "ext", key="EXTENDS", kind="EXTENDS")
    # genuine domain coupling: A's animal CALLS B's birth log (cross-island)
    g.add_edge("a1", "b1", key="CALLS", kind="CALLS")
    # intra-island edges (not crossing)
    g.add_edge("a1", "a_base", key="EXTENDS", kind="EXTENDS")
    g.add_edge("b1", "b_base", key="EXTENDS", kind="EXTENDS")
    return g


def _partition(assign: dict[str, str]) -> tuple[pl.DataFrame, pl.DataFrame]:
    from collections import Counter

    sizes = Counter(assign.values())
    mem = pl.DataFrame(
        [{"symbol_id": k, "subsystem_id": v} for k, v in assign.items()]
    )
    sub = pl.DataFrame(
        [
            {"subsystem_id": s, "repo": "R", "n_members": n, "persistence_score": 1.0}
            for s, n in sizes.items()
        ]
    )
    return sub, mem


# island assignment: ext lives in its own island IX
ASSIGN = {"a_base": "IA", "a1": "IA", "b_base": "IB", "b1": "IB", "ext": "IX"}


def test_framework_reason_external_and_base() -> None:
    assert framework_reason({"qualified_name": "external::Foo"}) == "external"
    base = {"qualified_name": "x::ContentEntityBase", "short_name": "ContentEntityBase"}
    assert framework_reason(base) == "drupal-base"
    domain = {"qualified_name": "a/x.php::AnimalAsset", "short_name": "AnimalAsset"}
    assert framework_reason(domain) is None


def test_is_framework_node_base_heuristic_toggle() -> None:
    base = {"qualified_name": "x::PluginBase", "short_name": "PluginBase"}
    assert is_framework_node(base, include_base_heuristic=True) is True
    assert is_framework_node(base, include_base_heuristic=False) is False
    ext = {"qualified_name": "external::X", "short_name": "X"}
    assert is_framework_node(ext, include_base_heuristic=False) is True


def test_classify_crossing_edges_splits_framework_from_domain() -> None:
    g = _mk_graph()
    edges = classify_crossing_edges(g, ASSIGN)
    # crossing edges: a_base→ext, b_base→ext (framework), a1→b1 (domain). Intra-island
    # EXTENDS edges are not crossing.
    kinds = {(e.src, e.dst): e.is_framework_idiom for e in edges}
    assert kinds[("a_base", "ext")] is True
    assert kinds[("b_base", "ext")] is True
    assert kinds[("a1", "b1")] is False
    assert len(edges) == 3


def test_boundary_quality_fractions_and_domain_neighbor() -> None:
    g = _mk_graph()
    sub, mem = _partition(ASSIGN)
    rep = boundary_quality(g, mem, sub)
    assert rep.n_crossing == 3
    assert rep.n_framework_idiom == 2
    assert rep.n_domain_coupling == 1
    assert round(rep.framework_idiom_fraction, 3) == round(2 / 3, 3)
    # IA's only domain neighbor is IB (the a1→b1 CALLS edge)
    ia = next(i for i in rep.islands if i.island_id == "IA")
    assert ia.domain_neighbors == [("IB", 1)]
    assert ia.domain_kind_histogram == {"CALLS": 1}


def test_prune_framework_graph_drops_external() -> None:
    g = _mk_graph()
    gp = prune_framework_graph(g, include_base_heuristic=False)
    assert "ext" not in gp.nodes
    assert "a1" in gp.nodes and "b1" in gp.nodes
    # the two EXTENDS-to-ext edges are gone; the a1→b1 CALLS survives
    assert gp.has_edge("a1", "b1")
    assert not gp.has_edge("a_base", "ext")


def test_adjusted_rand_index_identical_and_random() -> None:
    a = {f"n{i}": ("X" if i < 5 else "Y") for i in range(10)}
    assert adjusted_rand_index(a, a) == 1.0
    # a relabeling is still ARI 1.0
    b = {k: ("P" if v == "X" else "Q") for k, v in a.items()}
    assert adjusted_rand_index(a, b) == 1.0


def test_stability_diff_domain_seam_survives_prune() -> None:
    g = _mk_graph()

    def stub_partition(graph):
        # deterministic partition ignoring framework wiring: group by file dir.
        out = {}
        for n in graph.nodes:
            f = graph.nodes[n].get("file") or ""
            out[n] = f.split("/")[0] if f else "ext"
        return out

    res = stability_diff(g, stub_partition, include_base_heuristic=False)
    # ext node dropped on prune; remaining domain nodes keep their island → ARI 1.0
    assert res.ari == 1.0
    assert res.n_moved == 0
    assert "ext" not in {n for n in prune_framework_graph(g).nodes}
