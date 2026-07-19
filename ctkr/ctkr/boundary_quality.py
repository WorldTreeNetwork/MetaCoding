"""Boundary-quality evaluation for the subsystem partition (MetaCoding-9h5.12).

The subsystem partition (:mod:`ctkr.subsystems`) emits islands and per-member
``boundary_confidence``. This module asks the *next* question: **are those island
boundaries real domain seams, or artifacts of framework wiring?**

For a Drupal codebase (farmOS) the distinction is sharp. A crossing edge — a
typed morphism with its two endpoints in different islands — is either:

* a **framework idiom**: a farmOS class ``EXTENDS`` a Drupal/Symfony base
  (``ContentEntityBase``, ``PluginBase``, ``ControllerBase``), ``IMPLEMENTS`` a
  framework interface, or ``REFERENCES`` a framework symbol. These edges cross
  the boundary because *every* Drupal module inherits the same scaffolding — the
  crossing says nothing about domain coupling between the two islands.
* **genuine domain coupling**: a crossing edge between two farmOS domain symbols
  (an asset plugin calling a log service, a quick-form constructing a quantity).
  These are the real inter-module dependencies a port must preserve.

Framework endpoints are recognised name-blind and LM-free: a node whose
``qualified_name`` starts with ``external::`` is a symbol the indexer resolved
*outside* the repo (a library/framework base) — the strongest possible signal
that an edge to it is scaffolding, not domain logic. A small explicit table of
Drupal/Symfony base-class name patterns (:data:`FRAMEWORK_BASE_PATTERNS`) catches
in-repo re-exports of the same bases; it is conservative and auditable.

Two headline products:

1. :func:`boundary_quality` — per-island boundary composition (framework-idiom
   fraction vs domain-coupling fraction), size, persistence, and the concrete
   domain-coupling seams (which islands are genuinely coupled, by what edges).
2. :func:`stability_diff` — re-runs the partition with all framework-idiom edges
   pruned and diffs the two partitions (adjusted Rand index + moved-node count).
   A boundary that survives the prune is a *domain* seam; one that dissolves was
   a *wiring* artifact. This is the empirical test the bead asks for.

Everything here is deterministic and LM-free.
"""

from __future__ import annotations

import re
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from math import comb

import networkx as nx
import polars as pl

# ── framework-endpoint recognition (name-blind, LM-free) ──

# A node whose qualified_name carries this prefix was resolved OUTSIDE the repo
# by the indexer — a library/framework base class or interface. An edge to it is
# framework scaffolding by construction.
EXTERNAL_PREFIX = "external::"

# In-repo re-exports / project base classes that are still framework scaffolding
# rather than domain coupling. Conservative and explicit: matched against a
# node's short_name (or the last ``::`` segment of its qualified_name). Drupal /
# Symfony convention is that framework bases end in ``Base`` and contracts end in
# ``Interface``; the named set catches the common concrete bases.
FRAMEWORK_BASE_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?:^|\\)(?:Content|Config)Entity(?:Base|Interface|Bundle\w*)$"),
    re.compile(r"(?:^|\\)(?:Default)?Plugin(?:Base|Manager|Interface)$"),
    re.compile(r"(?:^|\\)ControllerBase$"),
    re.compile(r"(?:^|\\)(?:Config)?FormBase$"),
    re.compile(r"(?:^|\\)EntityForm$"),
    re.compile(r"(?:^|\\)(?:Deriver|EntityAction)Base$"),
    re.compile(r"(?:^|\\)Constraint(?:Validator)?$"),
    re.compile(r"(?:^|\\)ConfirmFormBase$"),
)

# CONTAINS is the containment backbone (scaffolding), never a contract morphism —
# excluded from boundary composition exactly as ct-subsystem-extraction §3 excludes it.
CONTAINMENT_KIND = "CONTAINS"


def _seg(qn: str) -> str:
    """Last identifier segment of a qualified name (``file::Class::method`` → method)."""
    if not qn:
        return ""
    return qn.split("::")[-1]


def framework_reason(attrs: dict) -> str | None:
    """Why this node is a framework endpoint, or ``None`` if it is a domain symbol.

    ``"external"`` — resolved outside the repo (strongest signal).
    ``"drupal-base"`` — an in-repo class matching a known Drupal/Symfony base pattern.
    """
    qn = attrs.get("qualified_name") or ""
    if qn.startswith(EXTERNAL_PREFIX):
        return "external"
    name = attrs.get("short_name") or _seg(qn)
    for rx in FRAMEWORK_BASE_PATTERNS:
        if rx.search(name):
            return "drupal-base"
    return None


def is_framework_node(attrs: dict, *, include_base_heuristic: bool = True) -> bool:
    """True when *attrs* names a framework/library symbol (see :func:`framework_reason`).

    ``include_base_heuristic=False`` restricts to the ``external::`` signal only —
    the maximally-conservative classification used for the headline stability diff.
    """
    reason = framework_reason(attrs)
    if reason is None:
        return False
    if reason == "drupal-base" and not include_base_heuristic:
        return False
    return True


@dataclass(slots=True, frozen=True)
class CrossingEdge:
    """One typed morphism whose endpoints lie in different islands."""

    src: str
    dst: str
    kind: str
    src_island: str
    dst_island: str
    is_framework_idiom: bool
    reason: str  # "external" | "drupal-base" | "domain"


def classify_crossing_edges(
    g: nx.MultiDiGraph,
    sym2sub: dict[str, str],
    *,
    include_base_heuristic: bool = True,
) -> list[CrossingEdge]:
    """Every non-CONTAINS morphism crossing an island boundary, classified.

    A crossing edge is a **framework idiom** when either endpoint is a framework
    node (:func:`is_framework_node`); otherwise it is **domain coupling**.
    """
    out: list[CrossingEdge] = []
    for u, v, kind in g.edges(keys=True):
        if u == v or kind == CONTAINMENT_KIND:
            continue
        su, sv = sym2sub.get(u), sym2sub.get(v)
        if su is None or sv is None or su == sv:
            continue
        r_src = framework_reason(g.nodes[u])
        r_dst = framework_reason(g.nodes[v])
        if not include_base_heuristic:
            r_src = r_src if r_src == "external" else None
            r_dst = r_dst if r_dst == "external" else None
        # Prefer the target's reason (edges point AT framework bases) then source.
        reason = r_dst or r_src
        is_fw = reason is not None
        out.append(
            CrossingEdge(
                src=u,
                dst=v,
                kind=kind,
                src_island=su,
                dst_island=sv,
                is_framework_idiom=is_fw,
                reason=reason or "domain",
            )
        )
    return out


@dataclass(slots=True, frozen=True)
class IslandBoundary:
    """Boundary composition for one island."""

    island_id: str
    n_members: int
    persistence_score: float
    n_crossing: int
    n_framework_idiom: int
    n_domain_coupling: int
    framework_idiom_fraction: float
    # target island -> #genuine (non-framework) crossing edges, sorted desc
    domain_neighbors: list[tuple[str, int]] = field(default_factory=list)
    # (edge_kind -> count) over this island's domain-coupling crossings
    domain_kind_histogram: dict[str, int] = field(default_factory=dict)


@dataclass(slots=True)
class BoundaryQualityReport:
    n_islands: int
    n_crossing: int
    n_framework_idiom: int
    n_domain_coupling: int
    framework_idiom_fraction: float
    crossing_kind_histogram: dict[str, int]
    domain_kind_histogram: dict[str, int]
    island_sizes: list[int]
    islands: list[IslandBoundary]


def boundary_quality(
    g: nx.MultiDiGraph,
    members_df: pl.DataFrame,
    subsystems_df: pl.DataFrame,
    *,
    include_base_heuristic: bool = True,
) -> BoundaryQualityReport:
    """Per-island boundary composition: framework wiring vs domain coupling.

    Uses the partition in *members_df* (``symbol_id`` → ``subsystem_id``) and the
    per-island ``persistence_score`` / ``n_members`` from *subsystems_df*.
    """
    sym2sub = {r["symbol_id"]: r["subsystem_id"] for r in members_df.iter_rows(named=True)}
    ps = {
        r["subsystem_id"]: float(r["persistence_score"])
        for r in subsystems_df.iter_rows(named=True)
    }
    sizes = {r["subsystem_id"]: int(r["n_members"]) for r in subsystems_df.iter_rows(named=True)}

    edges = classify_crossing_edges(g, sym2sub, include_base_heuristic=include_base_heuristic)

    per_island_cross: dict[str, int] = defaultdict(int)
    per_island_fw: dict[str, int] = defaultdict(int)
    per_island_dom: dict[str, int] = defaultdict(int)
    per_island_neighbors: dict[str, Counter] = defaultdict(Counter)
    per_island_domkinds: dict[str, Counter] = defaultdict(Counter)
    kind_hist: Counter = Counter()
    dom_kind_hist: Counter = Counter()

    for e in edges:
        kind_hist[e.kind] += 1
        # Count each crossing once per endpoint island (a boundary has two sides).
        for side, other in ((e.src_island, e.dst_island), (e.dst_island, e.src_island)):
            per_island_cross[side] += 1
            if e.is_framework_idiom:
                per_island_fw[side] += 1
            else:
                per_island_dom[side] += 1
                per_island_neighbors[side][other] += 1
                per_island_domkinds[side][e.kind] += 1
        if not e.is_framework_idiom:
            dom_kind_hist[e.kind] += 1

    islands: list[IslandBoundary] = []
    for sid in sorted(sizes, key=lambda s: -sizes[s]):
        nc = per_island_cross.get(sid, 0)
        fw = per_island_fw.get(sid, 0)
        dom = per_island_dom.get(sid, 0)
        islands.append(
            IslandBoundary(
                island_id=sid,
                n_members=sizes[sid],
                persistence_score=ps.get(sid, 1.0),
                n_crossing=nc,
                n_framework_idiom=fw,
                n_domain_coupling=dom,
                framework_idiom_fraction=(fw / nc) if nc else 0.0,
                domain_neighbors=per_island_neighbors[sid].most_common(),
                domain_kind_histogram=dict(per_island_domkinds[sid]),
            )
        )

    n_fw = sum(1 for e in edges if e.is_framework_idiom)
    n_dom = len(edges) - n_fw
    return BoundaryQualityReport(
        n_islands=len(sizes),
        n_crossing=len(edges),
        n_framework_idiom=n_fw,
        n_domain_coupling=n_dom,
        framework_idiom_fraction=(n_fw / len(edges)) if edges else 0.0,
        crossing_kind_histogram=dict(kind_hist),
        domain_kind_histogram=dict(dom_kind_hist),
        island_sizes=sorted(sizes.values(), reverse=True),
        islands=islands,
    )


# ── stability diff: does the boundary survive framework-idiom pruning? ──


def prune_framework_graph(
    g: nx.MultiDiGraph, *, include_base_heuristic: bool = False
) -> nx.MultiDiGraph:
    """A copy of *g* with all framework nodes and every edge touching one removed.

    This strips the scaffolding entirely — inheritance to library bases, framework
    references — leaving only domain-to-domain structure. Re-partitioning the
    result and diffing against the baseline (:func:`stability_diff`) tells you
    whether the islands were held together by domain cohesion or by shared
    framework wiring. Default ``include_base_heuristic=False`` prunes only the
    unambiguous ``external::`` nodes, so the diff never over-credits the heuristic.
    """
    keep = {
        n
        for n, d in g.nodes(data=True)
        if not is_framework_node(d, include_base_heuristic=include_base_heuristic)
    }
    gp = nx.MultiDiGraph()
    for n in keep:
        gp.add_node(n, **g.nodes[n])
    for u, v, k, d in g.edges(keys=True, data=True):
        if u in keep and v in keep:
            gp.add_edge(u, v, key=k, **d)
    return gp


def adjusted_rand_index(a: dict[str, str], b: dict[str, str]) -> float:
    """Adjusted Rand Index over the shared keys of two labelings (no sklearn dep)."""
    shared = [k for k in a if k in b]
    n = len(shared)
    if n < 2:
        return 1.0
    contingency: dict[tuple[str, str], int] = defaultdict(int)
    ra: dict[str, int] = defaultdict(int)
    rb: dict[str, int] = defaultdict(int)
    for k in shared:
        contingency[(a[k], b[k])] += 1
        ra[a[k]] += 1
        rb[b[k]] += 1
    sum_comb = sum(comb(v, 2) for v in contingency.values())
    sa = sum(comb(v, 2) for v in ra.values())
    sb = sum(comb(v, 2) for v in rb.values())
    total = comb(n, 2)
    expected = (sa * sb) / total if total else 0.0
    maximum = (sa + sb) / 2
    if maximum == expected:
        return 1.0
    return (sum_comb - expected) / (maximum - expected)


@dataclass(slots=True)
class StabilityResult:
    n_shared: int
    ari: float
    n_moved: int
    moved_fraction: float
    baseline_sizes: list[int]
    pruned_sizes: list[int]
    n_pruned_nodes: int
    n_pruned_edges: int


def stability_diff(
    g: nx.MultiDiGraph,
    compute_partition,
    *,
    include_base_heuristic: bool = False,
) -> StabilityResult:
    """Prune framework wiring, re-partition, and diff against the baseline.

    *compute_partition* is a callable ``graph -> {symbol_id: island_id}`` (in the
    runner this is a thin wrapper over :func:`ctkr.subsystems.compute_subsystems`,
    injected so this module stays free of the heavy partition import and is easy
    to test with a stub partitioner).

    A high ARI means the boundaries are **domain seams** (they persist without the
    framework scaffolding); a low ARI means they were **wiring artifacts**.
    """
    baseline = compute_partition(g)
    gp = prune_framework_graph(g, include_base_heuristic=include_base_heuristic)
    pruned = compute_partition(gp)

    shared = [k for k in baseline if k in pruned]
    ari = adjusted_rand_index(baseline, pruned)

    # Per-node "moved" = not in its baseline island's majority image under the
    # pruned partition (a re-labeling-invariant churn measure).
    overlap: dict[str, Counter] = defaultdict(Counter)
    for k in shared:
        overlap[baseline[k]][pruned[k]] += 1
    majority = {isl: cnt.most_common(1)[0][0] for isl, cnt in overlap.items()}
    n_moved = sum(1 for k in shared if pruned[k] != majority[baseline[k]])

    return StabilityResult(
        n_shared=len(shared),
        ari=round(ari, 4),
        n_moved=n_moved,
        moved_fraction=round(n_moved / len(shared), 4) if shared else 0.0,
        baseline_sizes=sorted(Counter(baseline.values()).values(), reverse=True),
        pruned_sizes=sorted(Counter(pruned.values()).values(), reverse=True),
        n_pruned_nodes=gp.number_of_nodes(),
        n_pruned_edges=gp.number_of_edges(),
    )


__all__ = [
    "EXTERNAL_PREFIX",
    "FRAMEWORK_BASE_PATTERNS",
    "CONTAINMENT_KIND",
    "framework_reason",
    "is_framework_node",
    "CrossingEdge",
    "classify_crossing_edges",
    "IslandBoundary",
    "BoundaryQualityReport",
    "boundary_quality",
    "prune_framework_graph",
    "adjusted_rand_index",
    "StabilityResult",
    "stability_diff",
]
