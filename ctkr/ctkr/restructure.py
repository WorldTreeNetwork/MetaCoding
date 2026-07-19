"""Restructure-proposal generator (MetaCoding-9h5.12).

Given a graph and its subsystem islands, emit a **restructure-proposal.md**: the
module boundaries the *structure* implies, the specific element moves that would
realise them, and a per-move justification drawn from graph evidence (cohesion
gained, coupling context) — every move checkable against the graph.

The proposal is a function of the disagreement between two partitions:

* the **declared** partition — the codebase's own module/directory boundaries
  (farmOS modules, or for a true monolith: one home);
* the **structural** partition — the Louvain islands (:mod:`ctkr.subsystems`).

Two disagreement shapes, both reported:

* **SPLIT** — one declared module whose symbols the graph scatters across several
  islands. Its members are candidate *realign moves*: the graph binds each more
  tightly to its island than to its declared module (verified: internal-island
  edge count > same-module edge count). For a monolith, *every* island is a split
  of the one home — the islands become the proposed modules.
* **MERGE** — one island absorbing many declared modules. The graph says those
  declared modules are a single structural unit; reported as narrative, with the
  internal-edge-density evidence, not per-symbol moves (you would not relocate
  code to merge — you would collapse the module boundary).

farmOS is *already* modular, so the interesting output is exactly where farmOS's
own boundaries disagree with the graph's islands — those disagreements are the
validation the bead asks for. LM-free and deterministic.
"""

from __future__ import annotations

import time
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.boundary_quality import CONTAINMENT_KIND, is_framework_node

# ── declared-home resolution (longest module-glob prefix) ──


def _home_prefixes(features_df: pl.DataFrame) -> list[tuple[str, str]]:
    """``[(prefix, module_name)]`` from feature ``member_globs``, longest-first.

    A feature's ``member_globs`` are ``<dir>/**`` patterns; the prefix is the dir.
    Sorted longest-first so :func:`_declared_home` picks the most specific module.
    """
    prefixes: list[tuple[str, str]] = []
    for r in features_df.iter_rows(named=True):
        for g in r.get("member_globs") or []:
            if g.endswith("/**"):
                prefixes.append((g[:-3], r["name"]))
            elif g == "**":
                prefixes.append(("", r["name"]))
    prefixes.sort(key=lambda pm: -len(pm[0]))
    return prefixes


def _declared_home(file_path: str, prefixes: list[tuple[str, str]]) -> str | None:
    """The owning module for *file_path*: the longest matching module prefix."""
    for prefix, name in prefixes:
        if prefix == "" or file_path == prefix or file_path.startswith(prefix + "/"):
            return name
    return None


@dataclass(slots=True, frozen=True)
class Move:
    """A proposed relocation of one element to align declared home with structure."""

    element_id: str
    qualified_name: str
    from_module: str
    to_island: str
    to_island_label: str
    cohesion_to_island: int  # non-CONTAINS edges to members of the target island
    coupling_to_home: int  # non-CONTAINS edges to members of its declared module
    justification: str


@dataclass(slots=True, frozen=True)
class ProposedModule:
    """One structural island, presented as a proposed module boundary."""

    island_id: str
    label: str
    n_members: int
    persistence_score: float
    internal_edge_density: float  # non-CONTAINS internal edges / member
    declared_modules_absorbed: list[tuple[str, int]]  # (module, #members) desc
    is_merge_of_many: bool  # island consolidates > 1 declared module


@dataclass(slots=True)
class RestructureProposal:
    repo: str
    generated_at: str
    n_islands: int
    n_declared_modules: int
    proposed_modules: list[ProposedModule]
    split_disagreements: list[dict]  # declared module -> islands it scatters into
    merge_disagreements: list[dict]  # island -> declared modules it consolidates
    realign_moves: list[Move]
    clean_slices: list[str]  # declared modules that map 1:1 to one island
    total_seconds: float = 0.0


def _island_label(declared_counts: Counter, top_dirs: Counter) -> str:
    """Human label for an island: dominant declared module family, else top dir."""
    if declared_counts:
        top_mod = declared_counts.most_common(1)[0][0]
        return top_mod
    if top_dirs:
        return top_dirs.most_common(1)[0][0]
    return "(unlabelled)"


def build_restructure_proposal(
    g: nx.MultiDiGraph,
    members_df: pl.DataFrame,
    subsystems_df: pl.DataFrame,
    features_df: pl.DataFrame,
    *,
    repo: str | None = None,
    generated_at: str | None = None,
    min_move_cohesion: int = 1,
) -> RestructureProposal:
    """Compute the restructure proposal from graph + islands + declared modules."""
    start = time.perf_counter()
    gen_at = generated_at or datetime.now(tz=UTC).isoformat()

    sym2sub = {r["symbol_id"]: r["subsystem_id"] for r in members_df.iter_rows(named=True)}
    ps = {
        r["subsystem_id"]: float(r["persistence_score"])
        for r in subsystems_df.iter_rows(named=True)
    }
    sizes = {r["subsystem_id"]: int(r["n_members"]) for r in subsystems_df.iter_rows(named=True)}
    repo = repo or (subsystems_df["repo"][0] if subsystems_df.height else "repo")

    prefixes = _home_prefixes(features_df)

    # symbol -> declared home; skip framework (external) nodes for declared-home
    # accounting (they own no module).
    home_of: dict[str, str | None] = {}
    for n in sym2sub:
        fp = g.nodes[n].get("file") or ""
        home_of[n] = _declared_home(fp, prefixes)

    # per-island: declared-module composition, top dirs
    isl_declared: dict[str, Counter] = defaultdict(Counter)
    isl_dirs: dict[str, Counter] = defaultdict(Counter)
    for n, sid in sym2sub.items():
        if is_framework_node(g.nodes[n], include_base_heuristic=False):
            continue
        home = home_of.get(n)
        if home:
            isl_declared[sid][home] += 1
        fp = g.nodes[n].get("file") or ""
        parts = [p for p in fp.split("/") if p]
        isl_dirs[sid]["/".join(parts[:3]) if parts else "(root)"] += 1

    # per-island internal non-CONTAINS edge count (cohesion)
    isl_internal_edges: dict[str, int] = defaultdict(int)
    for u, v, k in g.edges(keys=True):
        if k == CONTAINMENT_KIND or u == v:
            continue
        su, sv = sym2sub.get(u), sym2sub.get(v)
        if su is not None and su == sv:
            isl_internal_edges[su] += 1

    labels: dict[str, str] = {
        sid: _island_label(isl_declared[sid], isl_dirs[sid]) for sid in sizes
    }

    proposed: list[ProposedModule] = []
    for sid in sorted(sizes, key=lambda s: -sizes[s]):
        n = sizes[sid]
        absorbed = isl_declared[sid].most_common()
        proposed.append(
            ProposedModule(
                island_id=sid,
                label=labels[sid],
                n_members=n,
                persistence_score=ps.get(sid, 1.0),
                internal_edge_density=round(isl_internal_edges.get(sid, 0) / n, 3) if n else 0.0,
                declared_modules_absorbed=absorbed,
                is_merge_of_many=len(absorbed) > 1,
            )
        )

    # declared module -> islands it scatters into (SPLIT)
    mod_islands: dict[str, Counter] = defaultdict(Counter)
    for n, sid in sym2sub.items():
        home = home_of.get(n)
        if home:
            mod_islands[home][sid] += 1

    split_disagreements: list[dict] = []
    clean_slices: list[str] = []
    for mod in sorted(mod_islands):
        isl_counts = mod_islands[mod]
        if len(isl_counts) == 1:
            clean_slices.append(mod)
            continue
        split_disagreements.append(
            {
                "module": mod,
                "n_islands": len(isl_counts),
                "distribution": [
                    {"island": s, "island_label": labels.get(s, s[:12]), "n_members": c}
                    for s, c in isl_counts.most_common()
                ],
            }
        )
    split_disagreements.sort(key=lambda d: (-d["n_islands"], d["module"]))

    # island -> declared modules it consolidates (MERGE)
    merge_disagreements: list[dict] = []
    for sid in sorted(sizes, key=lambda s: -sizes[s]):
        absorbed = isl_declared[sid].most_common()
        if len(absorbed) > 1:
            merge_disagreements.append(
                {
                    "island": sid,
                    "island_label": labels[sid],
                    "n_members": sizes[sid],
                    "persistence_score": ps.get(sid, 1.0),
                    "n_declared_modules": len(absorbed),
                    "internal_edge_density": round(
                        isl_internal_edges.get(sid, 0) / sizes[sid], 3
                    ),
                    "top_modules": absorbed[:8],
                }
            )

    # ── realign moves: for a symbol whose island's dominant declared module is not
    #    its own declared home, and which is bound more tightly to the island than
    #    to its declared module (edge evidence). ──
    # Precompute adjacency (non-CONTAINS, undirected) once.
    adj: dict[str, list[str]] = defaultdict(list)
    for u, v, k in g.edges(keys=True):
        if k == CONTAINMENT_KIND or u == v:
            continue
        adj[u].append(v)
        adj[v].append(u)

    isl_dominant: dict[str, str | None] = {
        sid: (isl_declared[sid].most_common(1)[0][0] if isl_declared[sid] else None)
        for sid in sizes
    }

    moves: list[Move] = []
    for n, sid in sym2sub.items():
        if is_framework_node(g.nodes[n], include_base_heuristic=False):
            continue
        home = home_of.get(n)
        dom = isl_dominant.get(sid)
        if home is None or dom is None or home == dom:
            continue
        # cohesion to island members / coupling to same-home members
        coh = sum(1 for m in adj.get(n, ()) if sym2sub.get(m) == sid)
        cpl = sum(1 for m in adj.get(n, ()) if home_of.get(m) == home)
        if coh < min_move_cohesion or coh <= cpl:
            continue
        moves.append(
            Move(
                element_id=n,
                qualified_name=g.nodes[n].get("qualified_name") or "",
                from_module=home,
                to_island=sid,
                to_island_label=labels[sid],
                cohesion_to_island=coh,
                coupling_to_home=cpl,
                justification=(
                    f"{coh} structural edge(s) into island '{labels[sid]}' vs "
                    f"{cpl} into declared module '{home}' — graph binds it to the island."
                ),
            )
        )
    moves.sort(key=lambda m: (-m.cohesion_to_island, m.from_module, m.qualified_name))

    return RestructureProposal(
        repo=repo,
        generated_at=gen_at,
        n_islands=len(sizes),
        n_declared_modules=len(mod_islands),
        proposed_modules=proposed,
        split_disagreements=split_disagreements,
        merge_disagreements=merge_disagreements,
        realign_moves=moves,
        clean_slices=sorted(clean_slices),
        total_seconds=round(time.perf_counter() - start, 3),
    )


# ── markdown rendering ──


def render_proposal_md(p: RestructureProposal) -> str:
    """Render a :class:`RestructureProposal` to restructure-proposal.md text."""
    L: list[str] = []
    L.append(f"# Restructure proposal — `{p.repo}`")
    L.append("")
    L.append(
        f"_Generated {p.generated_at} · deterministic, LLM-free · "
        f"MetaCoding-9h5.12._"
    )
    L.append("")
    n_clean = len(p.clean_slices)
    L.append(
        f"The graph implies **{p.n_islands} structural modules** (islands) over "
        f"{p.n_declared_modules} declared modules. "
        f"{n_clean} declared module(s) map cleanly to one island (clean vertical "
        f"slices); {len(p.split_disagreements)} are **split** across islands; "
        f"{len(p.merge_disagreements)} island(s) **merge** multiple declared modules. "
        f"{len(p.realign_moves)} element-level realign move(s) proposed, each "
        f"justified by graph edges below."
    )
    L.append("")

    L.append("## Proposed modules (structural islands)")
    L.append("")
    L.append("| island | label | members | persistence | internal edge density | declared modules absorbed |")  # noqa: E501
    L.append("|---|---|--:|--:|--:|--:|")
    for m in p.proposed_modules:
        L.append(
            f"| `{m.island_id[:12]}` | {m.label} | {m.n_members} | "
            f"{m.persistence_score:.3f} | {m.internal_edge_density:.2f} | "
            f"{len(m.declared_modules_absorbed)} |"
        )
    L.append("")

    if p.split_disagreements:
        L.append("## SPLIT — declared modules the graph scatters across islands")
        L.append("")
        L.append(
            "> A declared module whose symbols land in several islands. Either the "
            "module is a cross-cutting concern, or it bundles independent units the "
            "graph separates. These are the boundaries where farmOS's own module "
            "map disagrees with structure."
        )
        L.append("")
        for d in p.split_disagreements:
            dist = ", ".join(
                f"{x['island_label']} ({x['n_members']})" for x in d["distribution"]
            )
            L.append(f"- **`{d['module']}`** → {d['n_islands']} islands: {dist}")
        L.append("")

    if p.merge_disagreements:
        L.append("## MERGE — islands the graph consolidates from many declared modules")
        L.append("")
        L.append(
            "> An island absorbing many declared modules: the graph says these "
            "declared boundaries are one structural unit. A high internal edge "
            "density with low persistence is the signature of a directory-driven "
            "grab-bag rather than a cohesive module."
        )
        L.append("")
        L.append("| island | members | persistence | declared modules | internal edge density | top modules |")  # noqa: E501
        L.append("|---|--:|--:|--:|--:|---|")
        for d in p.merge_disagreements:
            top = ", ".join(f"{mod}({c})" for mod, c in d["top_modules"])
            L.append(
                f"| {d['island_label']} | {d['n_members']} | "
                f"{d['persistence_score']:.3f} | {d['n_declared_modules']} | "
                f"{d['internal_edge_density']:.2f} | {top} |"
            )
        L.append("")

    L.append("## Realign moves (element → island)")
    L.append("")
    if p.realign_moves:
        L.append(
            "> Each move relocates one element from its declared module to the "
            "structural island it is more tightly bound to. Verifiable: re-count "
            "the edges named in the justification against the graph."
        )
        L.append("")
        L.append("| element | from module | to island | cohesion | home coupling | justification |")
        L.append("|---|---|---|--:|--:|---|")
        for m in p.realign_moves[:200]:
            qn = m.qualified_name or m.element_id
            L.append(
                f"| `{qn}` | {m.from_module} | {m.to_island_label} | "
                f"{m.cohesion_to_island} | {m.coupling_to_home} | {m.justification} |"
            )
        if len(p.realign_moves) > 200:
            L.append("")
            L.append(f"_… {len(p.realign_moves) - 200} more moves omitted._")
    else:
        L.append(
            "_No element-level realign moves: every symbol is bound at least as "
            "tightly to its declared module as to any other island. The declared "
            "boundaries and structure agree at the element level; disagreement is "
            "confined to the module-level SPLIT/MERGE shapes above._"
        )
    L.append("")
    return "\n".join(L)


def write_proposal(p: RestructureProposal, out_path: str | Path) -> Path:
    path = Path(out_path).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render_proposal_md(p), encoding="utf-8")
    return path


__all__ = [
    "Move",
    "ProposedModule",
    "RestructureProposal",
    "build_restructure_proposal",
    "render_proposal_md",
    "write_proposal",
]
