"""Target-side feature × event-kind dependency graph (MetaCoding-9h5.21).

The composition run (`two-feature-composition-2026-07-20.md`, bead 9h5.16) proved the
fan-out's real product is **one event log, one asset model, one ID scheme** shared by
features whose projections overlap — and that N independent blind builders diverge on
every shared axis. Its shared-kernel prescription names the event kinds that MUST be
frozen before wave 1. This module makes that prescription *mechanical* instead of
judged: it builds the bipartite graph **features ↔ event kinds** and reads two analyses
straight off it.

For each feature we extract, from the committed adapter contract / build sources:

* which event **kinds its mutators EMIT** (append to the shared log), and
* which event **kinds each projection FOLDS** (reads over the log), plus whether that
  fold is **status-gated** (its inclusion of an event is conditioned on a status value —
  the pending-vs-done axis the kernel prescription flags).

Every 9h5.16 conflict is then an *edge* in this graph. Two analyses fall out:

1. :func:`kernel_surface` — **KERNEL SURFACE** = event kinds touched by ≥2 distinct
   features (cross-feature degree ≥2). These are the kinds a per-feature builder cannot
   own alone; they must be frozen centrally. Mechanically identified, not adjudicated.
2. :func:`wave_schedule` — **WAVE SCHEDULING** = connected components of the feature
   graph (features linked iff they share an event kind). Features in one component
   serialize through one builder (or block on a frozen kernel element); features in
   different components parallelize. Freezing the kernel (`freeze_kinds=`) decouples the
   shared kernel so the *domain* clusters that remain reveal the true parallel structure.

Extraction is **deterministic** where a build source exists (:func:`extract_from_build`,
a name-blind TypeScript parse — no LLM). A :func:`build_terra_fallback_prompt` +
:class:`FeatureKindProfile` schema gives a terra-structured fallback for prose-only
contracts (repair retry, cite the contract line). :data:`PROJECTED_FAMILY_KINDS` carries
the farmOS module-family kind-*guesses* used to project the fan-out forward — every such
edge is tagged ``projected``/``uncertain`` and never mixed with ``extracted`` ones.
"""

from __future__ import annotations

import re
from collections import defaultdict
from dataclasses import dataclass
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

Role = Literal["emit", "fold"]
Provenance = Literal["extracted", "terra", "projected"]


# --------------------------------------------------------------------------- #
# Structured profile — the extraction target AND the terra-fallback schema      #
# --------------------------------------------------------------------------- #


class FoldEdge(BaseModel):
    """One event kind a projection folds, with whether the fold is status-gated."""

    model_config = ConfigDict(extra="forbid")

    kind: str = Field(description="The event-kind the projection reads, e.g. 'movement_recorded'.")
    status_gated: bool = Field(
        default=False,
        description="True if the projection includes/excludes the event based on a status "
        "value (e.g. only 'done' movements apply to current location). The pending-vs-done "
        "axis the shared-kernel prescription flags as a status-semantics contract.",
    )


class MutatorEmit(BaseModel):
    """One mutator method and the event kinds it appends to the log."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Mutator method name on the feature adapter.")
    emits: list[str] = Field(default_factory=list, description="Event kinds this mutator appends.")


class ProjectionFold(BaseModel):
    """One projection method and the event kinds it folds."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Projection method name on the feature adapter.")
    folds: list[FoldEdge] = Field(default_factory=list)


class FeatureKindProfile(BaseModel):
    """A single feature's emit/fold profile over the shared event taxonomy."""

    model_config = ConfigDict(extra="forbid")

    feature: str = Field(description="Feature name, e.g. 'logs+quantities'.")
    mutators: list[MutatorEmit] = Field(default_factory=list)
    projections: list[ProjectionFold] = Field(default_factory=list)
    provenance: Provenance = Field(
        default="extracted",
        description="'extracted' (deterministic parse of a build source), 'terra' "
        "(LLM-extracted from a prose contract), or 'projected' (kind-guessed from a "
        "module family — NOT an observed edge).",
    )
    citation: str = Field(
        default="",
        description="For terra/prose extraction: the contract line(s) each edge was read "
        "from. Empty for deterministic extraction.",
    )


# --------------------------------------------------------------------------- #
# Deterministic extraction — name-blind TypeScript parse (LM-free)             #
# --------------------------------------------------------------------------- #

# An event-tag object literal (`type: "asset_created"`) — a mutator EMITTING a kind.
_EMIT_RE = re.compile(r'type:\s*"([a-z_]+)"')
# A discriminant comparison (`e.type === "asset_created"`) — a projection FOLDING a kind.
_FOLD_RE = re.compile(r'\btype\s*===\s*"([a-z_]+)"')
# An intra-class call (`this.movementStatus(e)`) — for transitive closure of reads.
_CALL_RE = re.compile(r"this\.(\w+)\s*\(")
# A status-VALUE filter (`movementStatus(e) === "done"`, `.status === "pending"`) — the
# signal that a fold in this method is status-gated. NOT `log_status_changed` itself,
# which *carries* status rather than being gated by it.
_STATUS_GATE_RE = re.compile(r'(?:Status\s*\([^)]*\)|\.status)\s*===\s*"')
# The event kind that is the status carrier — never counted as "status-gated".
_STATUS_KIND = "log_status_changed"

# Class-body method header: exactly two-space indent (prettier/biome class-member level),
# optional modifiers, a name, an optional generic (which contains no `(`), then the param
# `(`. Bodies are indented ≥4 spaces so their statements never match.
_METHOD_HEADER_RE = re.compile(
    r"^  (?:private |public |protected |async |static )*([a-zA-Z_]\w*)[^(\n]*\(",
    re.MULTILINE,
)


@dataclass(slots=True)
class _Method:
    name: str
    body: str
    emits: frozenset[str]
    folds: frozenset[str]  # kinds folded *directly* in this method's body
    calls: frozenset[str]  # intra-class methods called
    status_gate: bool  # this body applies a status-value filter


def _match_balanced(text: str, open_idx: int, opener: str, closer: str) -> int:
    """Index just past the balanced ``closer`` for the ``opener`` at *open_idx*."""
    depth = 0
    i = open_idx
    n = len(text)
    while i < n:
        c = text[i]
        if c == opener:
            depth += 1
        elif c == closer:
            depth -= 1
            if depth == 0:
                return i + 1
        i += 1
    return n


def _parse_methods(ts_source: str) -> dict[str, _Method]:
    """Parse a TypeScript class file into ``{method_name: _Method}``.

    Name-blind and deterministic. Assumes prettier/biome formatting (two-space
    class-member indentation), which every committed build source uses.
    """
    methods: dict[str, _Method] = {}
    for m in _METHOD_HEADER_RE.finditer(ts_source):
        name = m.group(1)
        # Balance the parameter list, then find and balance the body braces.
        paren_open = ts_source.index("(", m.start())
        paren_end = _match_balanced(ts_source, paren_open, "(", ")")
        brace_open = ts_source.find("{", paren_end)
        if brace_open == -1:
            continue
        body_end = _match_balanced(ts_source, brace_open, "{", "}")
        body = ts_source[brace_open:body_end]
        methods[name] = _Method(
            name=name,
            body=body,
            emits=frozenset(_EMIT_RE.findall(body)),
            folds=frozenset(_FOLD_RE.findall(body)),
            calls=frozenset(_CALL_RE.findall(body)),
            status_gate=bool(_STATUS_GATE_RE.search(body)),
        )
    return methods


def _closure(name: str, methods: dict[str, _Method]) -> set[str]:
    """All methods reachable from *name* via intra-class calls (incl. itself)."""
    seen: set[str] = set()
    stack = [name]
    while stack:
        cur = stack.pop()
        if cur in seen or cur not in methods:
            continue
        seen.add(cur)
        stack.extend(methods[cur].calls)
    return seen


def _resolve_emits(entry: str, methods: dict[str, _Method]) -> set[str]:
    out: set[str] = set()
    for mn in _closure(entry, methods):
        out |= methods[mn].emits
    return out


def _resolve_folds(entry: str, methods: dict[str, _Method]) -> dict[str, bool]:
    """Kinds folded transitively from *entry* → whether the fold is status-gated.

    A folded kind is status-gated if any method in the closure that folds it *directly*
    also applies a status-value filter. The status carrier (:data:`_STATUS_KIND`) is
    never gated.
    """
    gated: dict[str, bool] = {}
    for mn in _closure(entry, methods):
        meth = methods[mn]
        for kind in meth.folds:
            g = meth.status_gate and kind != _STATUS_KIND
            gated[kind] = gated.get(kind, False) or g
    return gated


def _adapter_entry_methods(adapter_ts: str) -> list[str]:
    """Store methods a feature-adapter view delegates to (`store.recordLog(...)`),
    in first-seen order."""
    out: list[str] = []
    for m in re.finditer(r"store\.(\w+)\s*\(", adapter_ts):
        if m.group(1) not in out:
            out.append(m.group(1))
    return out


def extract_from_build(
    *,
    feature: str,
    store_ts: str,
    adapter_ts: str,
) -> FeatureKindProfile:
    """Deterministically extract a feature's emit/fold profile from build sources.

    *store_ts* is the shared store implementation (the one event log + folds);
    *adapter_ts* is the feature's thin adapter view, whose ``store.<method>(...)`` calls
    attribute the shared store's methods to *this* feature. LM-free.
    """
    methods = _parse_methods(store_ts)
    entries = _adapter_entry_methods(adapter_ts)

    mutators: list[MutatorEmit] = []
    projections: list[ProjectionFold] = []
    for entry in entries:
        if entry not in methods:
            continue
        emits = sorted(_resolve_emits(entry, methods))
        folds = _resolve_folds(entry, methods)
        if emits:
            mutators.append(MutatorEmit(name=entry, emits=emits))
        if folds:
            projections.append(
                ProjectionFold(
                    name=entry,
                    folds=[FoldEdge(kind=k, status_gated=folds[k]) for k in sorted(folds)],
                )
            )
    return FeatureKindProfile(
        feature=feature, mutators=mutators, projections=projections, provenance="extracted"
    )


# --------------------------------------------------------------------------- #
# Prose fallback — terra-structured extraction for contracts with no build      #
# --------------------------------------------------------------------------- #

FALLBACK_SYS = (
    "You extract a feature's EVENT-KIND dependency profile from a prose adapter "
    "contract for a local-first, event-log target. The target stores state as ONE "
    "append-only event log; mutators APPEND events (each of a named kind); projections "
    "FOLD (read) over the log. For the ONE feature described, list:\n"
    "  * each MUTATOR and the event KIND(S) it emits (use the shared taxonomy names when "
    "the contract implies them, e.g. asset_created, log_recorded, log_status_changed, "
    "group_assigned, asset_archived, movement_recorded, geometry_set);\n"
    "  * each PROJECTION and the event kind(s) it folds, marking status_gated=true when "
    "the read includes/excludes an event based on a status value (pending vs done).\n"
    "Cite the contract line each non-obvious edge is read from in `citation`. Do not "
    "invent kinds the contract does not imply."
)


def build_terra_fallback_prompt(*, feature: str, contract_text: str) -> str:
    """Assemble the deterministic prompt for the prose→profile fallback. Pure function."""
    return "\n".join(
        [
            f"# Feature: {feature}",
            "",
            "## Adapter contract (prose)",
            contract_text.strip(),
            "",
            "## Task",
            "Emit a FeatureKindProfile: mutators (name + emitted kinds) and projections "
            "(name + folded kinds, each with status_gated). Set provenance='terra' and "
            "cite the contract line(s) in `citation`.",
        ]
    )


def extract_from_prose(
    *,
    feature: str,
    contract_text: str,
    client,
    model: str,
    provider: str | None = None,
) -> tuple[FeatureKindProfile, float]:
    """One terra-structured extraction (repair retry) from a prose contract.

    Returns ``(profile, cost_estimate_usd)``. The client is a
    :class:`ctkr.llm.LLMClient`; tests inject a mock provider."""
    prompt = build_terra_fallback_prompt(feature=feature, contract_text=contract_text)
    res = client.complete_structured(
        prompt,
        schema=FeatureKindProfile,
        model=model,
        provider=provider,
        system=FALLBACK_SYS,
        max_tokens=4000,
        repair=True,
    )
    profile = res.parsed
    profile.feature = feature
    profile.provenance = "terra"
    return profile, float(res.cost_estimate_usd)


# --------------------------------------------------------------------------- #
# The bipartite graph                                                          #
# --------------------------------------------------------------------------- #


@dataclass(slots=True, frozen=True)
class KindEdge:
    """One (feature, kind, role) edge of the bipartite graph."""

    feature: str
    kind: str
    role: Role  # "emit" | "fold"
    status_gated: bool
    provenance: Provenance
    via: tuple[str, ...]  # method names that produce this edge


@dataclass(slots=True)
class FeatureKindGraph:
    features: list[str]
    kinds: list[str]
    edges: list[KindEdge]

    def kinds_of(self, feature: str) -> set[str]:
        return {e.kind for e in self.edges if e.feature == feature}

    def features_of(self, kind: str) -> set[str]:
        return {e.feature for e in self.edges if e.kind == kind}


def build_graph(profiles: list[FeatureKindProfile]) -> FeatureKindGraph:
    """Assemble the bipartite feature ↔ kind graph from per-feature profiles."""
    edges: list[KindEdge] = []
    # (feature, kind, role) -> (status_gated_any, via methods)
    agg: dict[tuple[str, str, Role], tuple[bool, list[str]]] = {}
    features: list[str] = []
    kinds: list[str] = []
    for p in profiles:
        if p.feature not in features:
            features.append(p.feature)
        for mut in p.mutators:
            for kind in mut.emits:
                if kind not in kinds:
                    kinds.append(kind)
                key = (p.feature, kind, "emit")
                g, via = agg.get(key, (False, []))
                agg[key] = (g, [*via, mut.name])
        for proj in p.projections:
            for fe in proj.folds:
                if fe.kind not in kinds:
                    kinds.append(fe.kind)
                key = (p.feature, fe.kind, "fold")
                g, via = agg.get(key, (False, []))
                agg[key] = (g or fe.status_gated, [*via, proj.name])
    prov_by_feature = {p.feature: p.provenance for p in profiles}
    for (feature, kind, role), (gated, via) in agg.items():
        edges.append(
            KindEdge(
                feature=feature,
                kind=kind,
                role=role,
                status_gated=gated,
                provenance=prov_by_feature.get(feature, "extracted"),
                via=tuple(dict.fromkeys(via)),
            )
        )
    edges.sort(key=lambda e: (e.feature, e.kind, e.role))
    return FeatureKindGraph(features=features, kinds=sorted(kinds), edges=edges)


# --------------------------------------------------------------------------- #
# Analysis 1 — kernel surface                                                  #
# --------------------------------------------------------------------------- #


@dataclass(slots=True, frozen=True)
class KernelKind:
    """An event kind and the features that touch it (emit or fold)."""

    kind: str
    degree: int  # number of DISTINCT features touching the kind
    emit_features: tuple[str, ...]
    fold_features: tuple[str, ...]
    status_gated_features: tuple[str, ...]  # features whose fold of this kind is status-gated
    is_kernel: bool  # degree >= threshold

    @property
    def touching_features(self) -> tuple[str, ...]:
        return tuple(sorted(set(self.emit_features) | set(self.fold_features)))


def kernel_surface(graph: FeatureKindGraph, *, threshold: int = 2) -> list[KernelKind]:
    """Rank every event kind by cross-feature degree; a kind with degree ≥ *threshold*
    is a **kernel** kind (no single feature builder can own it). Sorted degree-desc."""
    emit: dict[str, set[str]] = defaultdict(set)
    fold: dict[str, set[str]] = defaultdict(set)
    gated: dict[str, set[str]] = defaultdict(set)
    for e in graph.edges:
        (emit if e.role == "emit" else fold)[e.kind].add(e.feature)
        if e.role == "fold" and e.status_gated:
            gated[e.kind].add(e.feature)
    out: list[KernelKind] = []
    for kind in graph.kinds:
        touching = emit[kind] | fold[kind]
        out.append(
            KernelKind(
                kind=kind,
                degree=len(touching),
                emit_features=tuple(sorted(emit[kind])),
                fold_features=tuple(sorted(fold[kind])),
                status_gated_features=tuple(sorted(gated[kind])),
                is_kernel=len(touching) >= threshold,
            )
        )
    out.sort(key=lambda k: (-k.degree, k.kind))
    return out


@dataclass(slots=True, frozen=True)
class TaxonomyTension:
    """Two distinct emit-kinds from different features that a fan-out might collapse.

    The CP2 movement-vs-log conflict: `log_recorded` (logs) and `movement_recorded`
    (location) are distinct kinds *because one mind chose so*, but one feature's fold is
    kind-filtered (`logCount(asset, kind)`), so a builder who modeled movements as
    activity logs would collapse them into one degree-≥2 kernel kind. A **latent** edge,
    not an extracted one.
    """

    kind_a: str
    kind_b: str
    feature_a: str
    feature_b: str
    kind_filtered_by: tuple[str, ...]  # features whose fold reads a kind param (would merge)


def taxonomy_tensions(
    graph: FeatureKindGraph, profiles: list[FeatureKindProfile], *, suffix: str = "_recorded"
) -> list[TaxonomyTension]:
    """Detect emit-kind pairs across features sharing a structural *suffix* — candidates
    a naive fan-out would merge into one shared kind. Reproduces CP2 honestly as latent."""
    emit_owner: dict[str, str] = {}
    for e in graph.edges:
        if e.role == "emit" and e.kind.endswith(suffix) and e.kind not in emit_owner:
            emit_owner[e.kind] = e.feature
    # Features with a kind-filtered projection (a *count*-by-kind read that would merge
    # two emit-kinds if they shared a name).
    kind_filtered = {
        p.feature
        for p in profiles
        for proj in p.projections
        if proj.name.lower().endswith("count")
    }
    kinds = sorted(emit_owner)
    out: list[TaxonomyTension] = []
    for i, a in enumerate(kinds):
        for b in kinds[i + 1 :]:
            if emit_owner[a] != emit_owner[b]:
                out.append(
                    TaxonomyTension(
                        kind_a=a,
                        kind_b=b,
                        feature_a=emit_owner[a],
                        feature_b=emit_owner[b],
                        kind_filtered_by=tuple(sorted(kind_filtered)),
                    )
                )
    return out


# --------------------------------------------------------------------------- #
# Analysis 2 — wave scheduling (connected components)                          #
# --------------------------------------------------------------------------- #


@dataclass(slots=True, frozen=True)
class Cluster:
    """A connected component of features that share ≥1 (non-frozen) event kind."""

    features: tuple[str, ...]
    shared_kinds: tuple[str, ...]  # kinds coupling ≥2 features within this cluster

    @property
    def size(self) -> int:
        return len(self.features)

    @property
    def serializes(self) -> bool:
        return self.size > 1


def wave_schedule(
    graph: FeatureKindGraph, *, freeze_kinds: frozenset[str] = frozenset()
) -> list[Cluster]:
    """Connected components over features, linked iff they share an event kind not in
    *freeze_kinds*. Features in one cluster **serialize** (through one builder or a frozen
    element); distinct clusters **parallelize**. Freezing the kernel decouples it so the
    domain clusters underneath surface. Sorted by size desc."""
    parent: dict[str, str] = {f: f for f in graph.features}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: str, b: str) -> None:
        parent[find(a)] = find(b)

    kind_to_features: dict[str, set[str]] = defaultdict(set)
    for e in graph.edges:
        if e.kind not in freeze_kinds:
            kind_to_features[e.kind].add(e.feature)
    for feats in kind_to_features.values():
        fl = sorted(feats)
        for other in fl[1:]:
            union(fl[0], other)

    comp_feats: dict[str, set[str]] = defaultdict(set)
    for f in graph.features:
        comp_feats[find(f)].add(f)

    clusters: list[Cluster] = []
    for feats in comp_feats.values():
        shared = tuple(sorted(k for k, kf in kind_to_features.items() if len(kf & feats) >= 2))
        clusters.append(Cluster(features=tuple(sorted(feats)), shared_kinds=shared))
    clusters.sort(key=lambda c: (-c.size, c.features))
    return clusters


# --------------------------------------------------------------------------- #
# Projection forward — farmOS module-family kind guesses (labelled projected)   #
# --------------------------------------------------------------------------- #

# Kind-GUESSES per farmOS module family (boundary-quality-farmos-v2 islands). These are
# projections from module family, NOT extracted edges — every profile built from this
# table carries provenance="projected". New guessed kinds beyond the 7-kind observed
# taxonomy are named with a `?` marker so no reader mistakes them for observed ones.
PROJECTED_FAMILY_KINDS: dict[str, dict[str, list[str]]] = {
    # island ss:7044ab31 — asset/{group, sensor, structure}
    "asset+group": {
        "emit": ["asset_created", "asset_archived", "group_assigned"],
        "fold": ["asset_created", "asset_archived", "group_assigned"],
    },
    # island ss:761b7d53 — log/{birth, input, lab_test}
    "logs+birth+input": {
        "emit": ["asset_created", "log_recorded", "log_status_changed"],
        "fold": ["log_recorded", "log_status_changed", "asset_created"],
    },
    # island ss:f7ae0f4c — quick/{movement, inventory, planting}
    "quick+movement+inventory": {
        "emit": ["movement_recorded", "geometry_set", "log_recorded", "inventory_adjusted?"],
        "fold": ["movement_recorded", "geometry_set", "log_recorded", "inventory_adjusted?"],
    },
    # island ss:2cb2e7ea — quantity/{material, test, standard}
    "quantity": {
        "emit": ["log_recorded"],
        "fold": ["log_recorded"],
    },
    # island ss:aa700b0a — taxonomy/{log_category, plant_type}
    "taxonomy": {
        "emit": ["term_assigned?"],
        "fold": ["term_assigned?", "log_recorded"],
    },
    # island ss:f49e059c — organization/farm
    "organization": {
        "emit": ["group_assigned"],
        "fold": ["group_assigned", "asset_created"],
    },
}


def projected_profiles(
    families: dict[str, dict[str, list[str]]] = PROJECTED_FAMILY_KINDS,
) -> list[FeatureKindProfile]:
    """Build ``provenance='projected'`` profiles from module-family kind guesses.

    Each family becomes one synthetic feature whose emit/fold edges are GUESSES. Used
    only to project the fan-out's wave structure forward; never mixed with extracted
    profiles in the kernel-confirmation table."""
    out: list[FeatureKindProfile] = []
    for fam, spec in families.items():
        emits = spec.get("emit", [])
        folds = spec.get("fold", [])
        out.append(
            FeatureKindProfile(
                feature=fam,
                mutators=[MutatorEmit(name=f"{fam}:mutators", emits=sorted(set(emits)))]
                if emits
                else [],
                projections=[
                    ProjectionFold(
                        name=f"{fam}:projections",
                        folds=[FoldEdge(kind=k) for k in sorted(set(folds))],
                    )
                ]
                if folds
                else [],
                provenance="projected",
                citation="module-family kind guess (PROJECTED_FAMILY_KINDS)",
            )
        )
    return out


# --------------------------------------------------------------------------- #
# Rendering                                                                    #
# --------------------------------------------------------------------------- #


def render_mermaid(graph: FeatureKindGraph, *, kernel_threshold: int = 2) -> str:
    """A left-right bipartite mermaid graph: features on the left, event kinds on the
    right; solid arrows = emit, dashed = fold; ``|gated|`` marks status-gated folds;
    kernel kinds (degree ≥ threshold) get a distinct class."""
    kernel = {k.kind for k in kernel_surface(graph, threshold=kernel_threshold) if k.is_kernel}
    lines = ["graph LR"]

    def fid(f: str) -> str:
        return "F_" + re.sub(r"\W", "_", f)

    def kid(k: str) -> str:
        return "K_" + re.sub(r"\W", "_", k)

    for f in graph.features:
        lines.append(f'  {fid(f)}["{f}"]')
    for k in graph.kinds:
        shape = f'{{"{k}"}}' if k in kernel else f'("{k}")'
        lines.append(f"  {kid(k)}{shape}")
    for e in graph.edges:
        if e.role == "emit":
            lines.append(f"  {fid(e.feature)} --> {kid(e.kind)}")
        else:
            label = "|gated|" if e.status_gated else ""
            lines.append(f"  {fid(e.feature)} -.->{label} {kid(e.kind)}")
    lines.append("  classDef kernel fill:#f9d,stroke:#933,stroke-width:2px;")
    kernel_ids = " ".join(kid(k) for k in kernel)
    if kernel_ids:
        lines.append(f"  class {kernel_ids} kernel;")
    return "\n".join(lines) + "\n"


__all__ = [
    "FoldEdge",
    "MutatorEmit",
    "ProjectionFold",
    "FeatureKindProfile",
    "extract_from_build",
    "build_terra_fallback_prompt",
    "extract_from_prose",
    "FALLBACK_SYS",
    "KindEdge",
    "FeatureKindGraph",
    "build_graph",
    "KernelKind",
    "kernel_surface",
    "TaxonomyTension",
    "taxonomy_tensions",
    "Cluster",
    "wave_schedule",
    "PROJECTED_FAMILY_KINDS",
    "projected_profiles",
    "render_mermaid",
]
