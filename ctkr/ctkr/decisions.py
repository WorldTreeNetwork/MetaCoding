"""Design-decision elicitation — surface, rank, and resolve the port's design
decisions BEFORE the build (bead MetaCoding-9h5.13).

When the target substrate differs from the source (every port), the major design
decisions ripple: post-hoc changes cost a refactor cascade. Duke's mandate (from
the first human CM review) is to SURFACE those decisions before build, rank them by
how far they ripple, and let the developer resolve each — or explicitly defer.

The pipeline already produces the raw material; this module is the interaction layer
over it. Three LM-free collectors read the existing artifacts:

* **intent-CM adjudications** (:mod:`ctkr.intent_cm`) — every CM-hard / CM-soft
  element carries a decision menu from the target profile. The canonical example is
  the ``UniqueBirthLog`` CM-hard constraint (evidence: the 9h5.4/9h5.8 ablations
  showed its resolution is *pure builder judgment* — same inputs, different builders
  chose ``preserve-via-convergence-rule`` vs ``weaken-to-eventual``).
* **paradigm-divergence declarations** — verifyPort's meta-structural pass
  (``docs/design/meta-structural-pass.md`` §a) declares which gates a cross-paradigm
  port makes non-informative. Accepting the declaration vs re-classifying a gate as
  binding is a design decision.
* **brief adaptation notes** — a subsystem card's role-level ``intent_dissonance``
  (name incoherence, name-purpose mismatch, mixed-purpose grouping) is an unresolved
  design question the port brief flags for human review.

Each collected :class:`Decision` carries a **blast radius** computed LM-free from the
exported code graph — the reach of the decision's element (how many symbols /
subsystems reference it). The menu ranks by ``uncertainty × blast-radius``.

Resolution flows (``ctkr decisions resolve``) — ``--interview`` (LLM-elicited
tradeoff doc, developer answers), ``--decide-for-me`` (agent picks via LLM with a
recorded rationale), ``--recommend`` (recommendations only, stays pending), and
``--roll-forward`` (explicit, logged, reversible-flagged). Every *committing*
resolution appends a Port Decision record (:mod:`portDecisions` format) to the
data-dir ledger, so the builder receives the choice as a pre-registered constraint
and verifyPort's waiver machinery can check it.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from collections.abc import Iterable, Mapping, Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Literal

import blake3
from pydantic import BaseModel, Field

if TYPE_CHECKING:  # heavy / optional deps kept out of the import path
    import networkx as nx
    import polars as pl

    from ctkr.intent_cm import AdjudicatedCM, TargetProfile
    from ctkr.llm import LLMClient, StructuredCompletion

logger = logging.getLogger("ctkr.decisions")

SCHEMA_VERSION = 1

# Output artifact (the registry) under ``<data_dir>/ctkr/``.
DECISIONS_FILE = "decisions.jsonl"

# Committing resolution modes append a Port Decision to the ledger; non-committing
# ones (interview / recommend) leave the decision pending.
DecisionStatus = Literal[
    "pending", "decided-by-developer", "decided-for-me", "rolled-forward"
]
DecisionSource = Literal["intent-cm", "paradigm-divergence", "brief-adaptation"]
ResolutionMode = Literal["interview", "decide", "decide-for-me", "recommend", "roll-forward"]

# The Port Decision `decision` kind (portDecisions.ts DecisionKind) each menu option
# maps to when it lands in the ledger. A choice that keeps the invariant (with a new
# mechanism) is "preserve-with-note"; one that relaxes it is "weaken"; one that
# replaces / relocates the mechanism is "supersede".
PD_KIND_BY_OPTION: dict[str, str] = {
    "preserve-via-convergence-rule": "preserve-with-note",
    "preserve-as-eventual-invariant": "preserve-with-note",
    "port-verbatim": "preserve-with-note",
    "weaken-to-eventual": "weaken",
    "move-to-coordination-layer": "supersede",
    "move-to-disclosure-layer": "supersede",
}

# Uncertainty weight per grade — how much builder judgment the decision demands.
# CM-hard is the canonical "pure builder judgment" case (9h5.4 ablation); a material
# paradigm divergence is nearly as load-bearing; role-tension notes are softer.
_UNCERTAINTY_WEIGHT: dict[str, float] = {
    "cm-hard": 1.0,
    "cm-soft": 0.6,
    "divergence-material": 0.9,
    "divergence-immaterial": 0.4,
    "role-name-purpose-mismatch": 0.7,
    "role-mixed-purpose": 0.6,
    "role-name-incoherence": 0.5,
    "role-tension": 0.5,
    "none": 0.2,
}


def uncertainty_weight(grade: str) -> float:
    """Map an uncertainty grade to its ranking weight (default 0.5 for unknowns)."""
    return _UNCERTAINTY_WEIGHT.get(grade, 0.5)


# ───────────────────────── models ─────────────────────────


class DecisionOption(BaseModel):
    """One menu option the developer chooses from."""

    id: str
    label: str = ""
    # The portDecisions.ts DecisionKind this option lands as when committed.
    pd_kind: str = "preserve-with-note"
    hint: str = ""


class BlastRadius(BaseModel):
    """The graph reach of a decision's element — LM-free, deterministic.

    ``affected_symbols`` counts the decision's own anchor node(s) plus every symbol
    that transitively references them (graph predecessors): the set whose
    re-implementation is constrained by resolving this decision. ``referencing_subsystems``
    is how many distinct subsystems that set spans (cross-cutting reach is the strongest
    ripple signal). ``containing_subsystem_member_count`` is context — the size of the
    subsystem the element lives in.
    """

    affected_symbols: int = 0
    referencing_subsystems: int = 0
    containing_subsystems: list[str] = Field(default_factory=list)
    containing_subsystem_member_count: int = 0
    anchor_node_ids: list[str] = Field(default_factory=list)
    score: float = 0.0

    def compute_score(self) -> float:
        """Blast score = affected symbols + a cross-subsystem-span bonus.

        Cross-subsystem reach (a decision that ripples past its own subsystem) is
        weighted heavily because those are the expensive-to-refactor decisions the
        pre-build surfacing exists to catch.
        """
        return float(self.affected_symbols) + 4.0 * max(0, self.referencing_subsystems - 1)


class Resolution(BaseModel):
    """The record of how a decision was resolved (or that it was rolled forward)."""

    mode: str
    chosen_option: str | None = None
    rationale: str = ""
    recommendation: str = ""
    reversible: bool = False
    resolved_at: str = ""
    author: str = ""
    # Provenance of the appended Port Decision (ledger), when the mode commits one.
    pd_record_id: str | None = None
    pd_ledger_path: str | None = None
    llm_model: str | None = None
    llm_cost_usd: float = 0.0


class Decision(BaseModel):
    """One pending (or resolved) design decision in the registry."""

    id: str
    source: str
    subsystem_id: str = ""
    feature: str = ""
    question: str = ""
    options: list[DecisionOption] = Field(default_factory=list)
    uncertainty_grade: str = "none"
    uncertainty_weight: float = 0.5
    blast_radius: BlastRadius = Field(default_factory=BlastRadius)
    rank_score: float = 0.0
    status: str = "pending"
    origin_ref: str = ""
    citations: list[str] = Field(default_factory=list)
    evidence: str = ""
    generated_at: str = ""
    schema_version: int = SCHEMA_VERSION
    resolution: Resolution | None = None


# ───────────────────────── blast radius (LM-free graph query) ─────────────────────────


def _members_index(members_df: pl.DataFrame | None) -> dict[str, str]:
    """symbol_id → subsystem_id, from subsystem_members.parquet (empty if absent)."""
    if members_df is None or members_df.height == 0:
        return {}
    idx: dict[str, str] = {}
    for r in members_df.iter_rows(named=True):
        idx[r["symbol_id"]] = r["subsystem_id"]
    return idx


def _subsystem_sizes(members_df: pl.DataFrame | None) -> dict[str, int]:
    if members_df is None or members_df.height == 0:
        return {}
    sizes: dict[str, int] = defaultdict(int)
    for r in members_df.iter_rows(named=True):
        sizes[r["subsystem_id"]] += 1
    return dict(sizes)


def _file_node_index(graph: nx.MultiDiGraph | None) -> dict[str, list[str]]:
    """Map a source file path → node ids declared in it (for CM element anchoring)."""
    idx: dict[str, list[str]] = defaultdict(list)
    if graph is None:
        return idx
    for nid, data in graph.nodes(data=True):
        f = data.get("file")
        if f:
            idx[f].append(nid)
    return idx


def map_cm_element_to_nodes(
    *,
    element_file: str,
    anchor: str,
    graph: nx.MultiDiGraph | None,
    file_index: Mapping[str, list[str]],
) -> list[str]:
    """Resolve a CM element (a file + enclosing-symbol anchor) to graph node id(s).

    The intent-CM ``element_id`` is ``{prefix}{category}:{anchor}:{file}`` and the file
    is the source-relative path the scanner saw (e.g. ``log/birth/src/Hook/FieldHooks.php``);
    the exported graph may carry a longer prefix (``modules/log/…``). Match on file
    *suffix*, then prefer the node whose short_name / qualified_name is the anchor
    (the method/class the constraint lives on); fall back to every node in the file.
    """
    if graph is None or not element_file:
        return []
    matched_files = [f for f in file_index if f == element_file or f.endswith("/" + element_file)]
    candidates: list[str] = []
    for f in matched_files:
        candidates.extend(file_index[f])
    if not candidates:
        return []
    named: list[str] = []
    if anchor:
        for nid in candidates:
            data = graph.nodes[nid]
            sn = data.get("short_name") or ""
            qn = data.get("qualified_name") or ""
            if sn == anchor or qn.endswith("::" + anchor) or qn.endswith(anchor):
                named.append(nid)
    return named or candidates


def compute_blast_radius(
    *,
    anchor_nodes: Sequence[str],
    graph: nx.MultiDiGraph | None,
    members_idx: Mapping[str, str],
    subsystem_sizes: Mapping[str, int],
) -> BlastRadius:
    """Blast radius = anchors ∪ transitive predecessors, plus subsystem span/context.

    LM-free and deterministic: uses only the directed reachability of the exported
    graph and the subsystem membership table.
    """
    anchors = [n for n in anchor_nodes if graph is not None and graph.has_node(n)]
    affected: set[str] = set(anchors)
    if graph is not None and anchors:
        import networkx as nx

        for n in anchors:
            affected |= nx.ancestors(graph, n)

    containing = sorted({members_idx[n] for n in anchors if n in members_idx})
    spanned = {members_idx[n] for n in affected if n in members_idx}
    member_count = sum(subsystem_sizes.get(s, 0) for s in containing)

    br = BlastRadius(
        affected_symbols=len(affected),
        referencing_subsystems=len(spanned),
        containing_subsystems=containing,
        containing_subsystem_member_count=member_count,
        anchor_node_ids=list(anchors),
    )
    br.score = br.compute_score()
    return br


# ───────────────────────── deterministic ids ─────────────────────────


def _decision_id(source: str, origin_ref: str) -> str:
    canon = json.dumps([source, origin_ref], sort_keys=True, separators=(",", ":")).encode("utf-8")
    return "dec:" + blake3.blake3(canon).hexdigest()[:20]


# ───────────────────────── collectors (LM-free) ─────────────────────────


def collect_cm_decisions(
    adjudicated: Sequence[AdjudicatedCM],
    profile: TargetProfile | None,
    *,
    graph: nx.MultiDiGraph | None = None,
    members_df: pl.DataFrame | None = None,
    include_soft: bool = True,
    generated_at: str | None = None,
) -> list[Decision]:
    """One decision per CM-hard (and CM-soft) adjudicated element.

    The menu is the target profile's ``decision_menu[sensitivity]`` — the exact
    machinery the port brief's target-adaptation section renders. Without a profile,
    a conservative default menu is used so the decision is still surfaced.
    """
    from ctkr.intent_cm import TargetProfile

    ts = generated_at or _now()
    file_index = _file_node_index(graph)
    members_idx = _members_index(members_df)
    sizes = _subsystem_sizes(members_df)
    default_menu = TargetProfile._default_menu()

    out: list[Decision] = []
    for a in adjudicated:
        if a.sensitivity == "hard":
            grade = "cm-hard"
        elif a.sensitivity == "soft":
            if not include_soft:
                continue
            grade = "cm-soft"
        else:
            continue

        menu = (profile.decision_menu if profile else default_menu).get(a.sensitivity) or []
        options = [
            DecisionOption(
                id=opt,
                label=opt.replace("-", " "),
                pd_kind=PD_KIND_BY_OPTION.get(opt, "preserve-with-note"),
            )
            for opt in menu
        ]

        anchor = _cm_anchor(a)
        efile = _cm_file(a)
        anchor_nodes = map_cm_element_to_nodes(
            element_file=efile, anchor=anchor, graph=graph, file_index=file_index
        )
        br = compute_blast_radius(
            anchor_nodes=anchor_nodes,
            graph=graph,
            members_idx=members_idx,
            subsystem_sizes=sizes,
        )
        subsystem_id = br.containing_subsystems[0] if br.containing_subsystems else ""

        cats = ", ".join(a.categories)
        cm = profile.consistency_model if profile else "eventual"
        question = (
            f"CM-{a.sensitivity} `{a.element_id}`: the source assumes {cats} under a "
            f"central authority. How should the {cm}-consistency target re-answer this "
            "invariant?"
        )
        w = uncertainty_weight(grade)
        d = Decision(
            id=_decision_id("intent-cm", a.element_id),
            source="intent-cm",
            subsystem_id=subsystem_id,
            feature=subsystem_id or (a.categories[0] if a.categories else "intent-cm"),
            question=question,
            options=options,
            uncertainty_grade=grade,
            uncertainty_weight=w,
            blast_radius=br,
            rank_score=round(w * br.score, 4),
            status="pending",
            origin_ref=a.element_id,
            citations=list(a.citations),
            evidence=a.rationale,
            generated_at=ts,
        )
        out.append(d)
    return out


def _cm_anchor(a: AdjudicatedCM) -> str:
    """The enclosing-symbol anchor from the intent-CM element_id (its 2nd ':' field)."""
    parts = a.element_id.split(":")
    return parts[1] if len(parts) >= 3 else ""


def _cm_file(a: AdjudicatedCM) -> str:
    parts = a.element_id.split(":")
    if len(parts) >= 3:
        return ":".join(parts[2:])
    if a.citations:
        return a.citations[0].rsplit(":", 1)[0]
    return ""


_DISSONANCE_MENU = [
    DecisionOption(
        id="confirm-role-intent",
        label="confirm role intent",
        pd_kind="preserve-with-note",
        hint="The stated intent is correct; port the role as one unit.",
    ),
    DecisionOption(
        id="split-role",
        label="split role",
        pd_kind="supersede",
        hint="The grouping conflates purposes; split into distinct target roles.",
    ),
    DecisionOption(
        id="defer-to-implementation",
        label="defer to implementation",
        pd_kind="weaken",
        hint="Resolve during the build from evidence; not decidable pre-build.",
    ),
]

_DISSONANCE_GRADE = {
    "name-purpose mismatch": "role-name-purpose-mismatch",
    "mixed-purpose grouping": "role-mixed-purpose",
    "name_incoherence": "role-name-incoherence",
}


def collect_brief_adaptation_decisions(
    cards: Iterable[Mapping[str, object]],
    *,
    graph: nx.MultiDiGraph | None = None,
    members_df: pl.DataFrame | None = None,
    generated_at: str | None = None,
) -> list[Decision]:
    """One decision per role carrying an ``intent_dissonance`` flag on a subsystem card.

    These are the unresolved brief-adaptation notes the port brief surfaces for human
    review (a role whose members cohere weakly, or whose name and purpose mismatch).
    Blast radius = the role's member set (they are all re-implemented under whatever the
    developer decides about the role).
    """
    ts = generated_at or _now()
    members_idx = _members_index(members_df)
    sizes = _subsystem_sizes(members_df)

    out: list[Decision] = []
    for card in cards:
        subsystem_id = str(card.get("subsystem_id") or "")
        for role in card.get("roles") or []:  # type: ignore[union-attr]
            if not isinstance(role, Mapping):
                continue
            diss = role.get("intent_dissonance")
            if not isinstance(diss, Mapping) or not diss:
                continue
            role_id = str(role.get("role_id") or "")
            kind = str(diss.get("kind") or "tension")
            grade = _DISSONANCE_GRADE.get(kind, "role-tension")
            label = str(role.get("label") or role_id)
            member_ids = [str(m) for m in (role.get("members") or []) if m]

            br = compute_blast_radius(
                anchor_nodes=member_ids,
                graph=graph,
                members_idx=members_idx,
                subsystem_sizes=sizes,
            )
            # Roles carry their own members even when the graph is absent; ensure the
            # blast reflects the role footprint so ranking is meaningful.
            if br.affected_symbols < len(member_ids):
                br.affected_symbols = len(member_ids)
                if not br.containing_subsystems and subsystem_id:
                    br.containing_subsystems = [subsystem_id]
                    br.referencing_subsystems = max(br.referencing_subsystems, 1)
                br.score = br.compute_score()

            w = uncertainty_weight(grade)
            question = (
                f"Role `{role_id}` ({label}) is flagged {kind}: its intent is "
                "underdetermined by structure. Confirm the intent, split the role, or "
                "defer to the build?"
            )
            d = Decision(
                id=_decision_id("brief-adaptation", f"{subsystem_id}/{role_id}"),
                source="brief-adaptation",
                subsystem_id=subsystem_id,
                feature=subsystem_id,
                question=question,
                options=[o.model_copy() for o in _DISSONANCE_MENU],
                uncertainty_grade=grade,
                uncertainty_weight=w,
                blast_radius=br,
                rank_score=round(w * br.score, 4),
                status="pending",
                origin_ref=f"{subsystem_id}/{role_id}",
                citations=[],
                evidence=str(diss.get("evidence") or ""),
                generated_at=ts,
            )
            out.append(d)
    return out


_DIVERGENCE_MENU = [
    DecisionOption(
        id="accept-divergence-as-declared",
        label="accept divergence as declared",
        pd_kind="preserve-with-note",
        hint="Pre-register the predicted-non-informative gates as expected waivers.",
    ),
    DecisionOption(
        id="reclassify-gate-binding",
        label="re-classify a predicted gate as binding",
        pd_kind="supersede",
        hint="Keep a gate's verdict authority; a waiver on it becomes a failure signal.",
    ),
    DecisionOption(
        id="revise-target-profile",
        label="revise the target profile",
        pd_kind="weaken",
        hint="The declared divergence is wrong; change the target profile axes.",
    ),
]


def collect_paradigm_divergence_decisions(
    reports: Iterable[Mapping[str, object]],
    *,
    members_df: pl.DataFrame | None = None,
    generated_at: str | None = None,
) -> list[Decision]:
    """One decision per port-verify report that declares a *material* paradigm divergence.

    Reads verifyPort's meta-structural declaration (``paradigmDivergence`` with
    ``diverges: true``). Accepting the declaration (pre-registering the predicted
    non-informative gates) vs re-classifying a gate as binding is a design decision
    (``docs/design/meta-structural-pass.md`` §a/§c). Gracefully empty when no report
    carries a divergence.
    """
    ts = generated_at or _now()
    sizes = _subsystem_sizes(members_df)
    out: list[Decision] = []
    for report in reports:
        pd = report.get("paradigmDivergence")
        if not isinstance(pd, Mapping) or not pd.get("diverges"):
            continue
        subsystem_id = str(report.get("subsystem") or report.get("subsystemId") or "")
        axes = [str(x) for x in (pd.get("axes") or [])]
        predicted = [str(x) for x in (pd.get("predictedNonInformative") or [])]
        member_count = sizes.get(subsystem_id, 0)
        br = BlastRadius(
            affected_symbols=member_count,
            referencing_subsystems=1 if subsystem_id else 0,
            containing_subsystems=[subsystem_id] if subsystem_id else [],
            containing_subsystem_member_count=member_count,
        )
        br.score = br.compute_score()
        grade = "divergence-material"
        w = uncertainty_weight(grade)
        axes_txt = ", ".join(axes) or "the verdict axes"
        gates_txt = ", ".join(predicted) or "(none)"
        question = (
            f"verifyPort declares a paradigm divergence on {axes_txt}; gates {gates_txt} "
            "are predicted non-informative and the verdict is ADVISORY. Accept the "
            "declaration, re-classify a gate as binding, or revise the profile?"
        )
        d = Decision(
            id=_decision_id("paradigm-divergence", subsystem_id or ",".join(axes)),
            source="paradigm-divergence",
            subsystem_id=subsystem_id,
            feature=subsystem_id or "paradigm",
            question=question,
            options=[o.model_copy() for o in _DIVERGENCE_MENU],
            uncertainty_grade=grade,
            uncertainty_weight=w,
            blast_radius=br,
            rank_score=round(w * br.score, 4),
            status="pending",
            origin_ref=subsystem_id or ",".join(axes),
            citations=[],
            evidence=str(pd.get("summary") or ""),
            generated_at=ts,
        )
        out.append(d)
    return out


# ───────────────────────── ranking ─────────────────────────


def rank_decisions(decisions: Sequence[Decision]) -> list[Decision]:
    """Sort by rank_score (uncertainty × blast) desc; id asc as a stable tiebreak."""
    return sorted(decisions, key=lambda d: (-d.rank_score, d.id))


# ───────────────────────── registry IO (merge-preserving) ─────────────────────────


def read_registry(path: str | Path) -> list[Decision]:
    p = Path(path).expanduser()
    out: list[Decision] = []
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line and not line.startswith("//"):
                out.append(Decision.model_validate_json(line))
    return out


def write_registry(decisions: Sequence[Decision], path: str | Path) -> None:
    p = Path(path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = rank_decisions(decisions)
    with p.open("w", encoding="utf-8") as f:
        for d in ordered:
            f.write(d.model_dump_json() + "\n")


def merge_registry(
    fresh: Sequence[Decision], existing: Sequence[Decision]
) -> list[Decision]:
    """Re-collect without losing resolutions.

    A freshly collected decision inherits the resolution + status of an existing
    decision with the same id (deterministic id = source + origin_ref, so a stable
    element keeps its history across re-runs). Newly disappeared decisions are dropped;
    new ones are added pending.
    """
    prior = {d.id: d for d in existing}
    merged: list[Decision] = []
    for d in fresh:
        old = prior.get(d.id)
        if old is not None and old.resolution is not None:
            d = d.model_copy(update={"resolution": old.resolution, "status": old.status})
        merged.append(d)
    return merged


# ───────────────────────── rendering ─────────────────────────

_STATUS_ICON = {
    "pending": "○ pending",
    "decided-by-developer": "● decided-by-developer",
    "decided-for-me": "◆ decided-for-me",
    "rolled-forward": "▷ rolled-forward",
}
_SOURCE_LABEL = {
    "intent-cm": "CM",
    "paradigm-divergence": "PARADIGM",
    "brief-adaptation": "BRIEF",
}


def render_menu(decisions: Sequence[Decision]) -> str:
    """Render the ranked decision menu (uncertainty × blast-radius), with per-decision
    status. Deterministic — no LLM."""
    ranked = rank_decisions(decisions)
    lines: list[str] = []
    lines.append("# Design decisions — ranked by uncertainty × blast-radius")
    lines.append("")
    n_pending = sum(1 for d in ranked if d.status == "pending")
    lines.append(
        f"_{len(ranked)} decision(s): {n_pending} pending, "
        f"{len(ranked) - n_pending} resolved._"
    )
    lines.append("")
    if not ranked:
        lines.append("(no pending design decisions surfaced)")
        return "\n".join(lines) + "\n"
    lines.append(
        "| # | rank | uncertainty | blast | subsystems | status | source | decision |"
    )
    lines.append("|---|------|-------------|-------|-----------|--------|--------|----------|")
    for i, d in enumerate(ranked, 1):
        br = d.blast_radius
        blast = f"{br.affected_symbols} sym"
        subs = f"{br.referencing_subsystems}"
        chosen = ""
        if d.resolution and d.resolution.chosen_option:
            chosen = f" → **{d.resolution.chosen_option}**"
        lines.append(
            f"| {i} | {d.rank_score:.1f} | {d.uncertainty_grade} "
            f"({d.uncertainty_weight:.1f}) | {blast} | {subs} | "
            f"{_STATUS_ICON.get(d.status, d.status)} | {_SOURCE_LABEL.get(d.source, d.source)} | "
            f"`{d.id}` {_menu_headline(d)}{chosen} |"
        )
    lines.append("")
    lines.append(
        "Resolve one with `ctkr decisions resolve <id> --interview` (or "
        "`--decide-for-me` / `--recommend` / `--roll-forward`)."
    )
    return "\n".join(lines) + "\n"


def _menu_headline(d: Decision) -> str:
    opts = " / ".join(o.id for o in d.options)
    return f"{d.origin_ref} — [{opts}]"


def render_interview_doc(
    d: Decision, elicitation: DecisionElicitationOut | None = None
) -> str:
    """Render the structured elicitation doc a developer answers: the question, each
    option with its per-option tradeoff analysis (LLM-generated + cited to source when
    an elicitation is supplied), and how to record the answer."""
    lines: list[str] = []
    lines.append(f"# Decision `{d.id}` — elicitation")
    lines.append("")
    lines.append(f"- **Source** — {d.source}")
    lines.append(f"- **Subsystem / feature** — {d.feature or '(n/a)'}")
    lines.append(f"- **Element** — `{d.origin_ref}`")
    lines.append(
        f"- **Uncertainty** — {d.uncertainty_grade} (weight {d.uncertainty_weight:.2f})"
    )
    br = d.blast_radius
    lines.append(
        f"- **Blast radius** — {br.affected_symbols} affected symbol(s) across "
        f"{br.referencing_subsystems} subsystem(s); containing subsystem has "
        f"{br.containing_subsystem_member_count} member(s). rank score "
        f"{d.rank_score:.2f}."
    )
    if d.citations:
        lines.append(f"- **Citations** — {'; '.join(d.citations)}")
    lines.append("")
    lines.append("## Question")
    lines.append("")
    lines.append(d.question)
    if d.evidence:
        lines.append("")
        lines.append(f"> _Source evidence:_ {d.evidence}")
    lines.append("")
    lines.append("## Options")
    lines.append("")

    tradeoffs: dict[str, OptionTradeoff] = {}
    recommendation = ""
    if elicitation is not None:
        tradeoffs = {t.option_id: t for t in elicitation.tradeoffs}
        recommendation = elicitation.recommendation
    for o in d.options:
        lines.append(f"### `{o.id}` — {o.label or o.id}")
        if o.hint:
            lines.append(f"- _{o.hint}_")
        lines.append(f"- Lands in the Port Decision ledger as `{o.pd_kind}`.")
        t = tradeoffs.get(o.id)
        if t is not None:
            if t.pros:
                lines.append(f"- **Pros** — {t.pros}")
            if t.cons:
                lines.append(f"- **Cons** — {t.cons}")
            if t.when_appropriate:
                lines.append(f"- **Choose when** — {t.when_appropriate}")
            if t.citation:
                lines.append(f"- **Cited to** — {t.citation}")
        lines.append("")
    if recommendation:
        lines.append("## Recommendation")
        lines.append("")
        lines.append(recommendation)
        lines.append("")
    lines.append("## How to answer")
    lines.append("")
    opt_ids = " | ".join(o.id for o in d.options)
    lines.append(
        f"Record your choice with `ctkr decisions resolve {d.id} --decide <{opt_ids}> "
        '--rationale "<why>"`. This appends a Port Decision to the ledger so the '
        "builder receives it as a pre-registered constraint."
    )
    return "\n".join(lines) + "\n"


# ───────────────────────── LLM elicitation ─────────────────────────


class OptionTradeoff(BaseModel):
    """Per-option tradeoff analysis (strong model, cited to source)."""

    option_id: str = Field(description="The exact option id from the decision menu.")
    pros: str = Field(default="", description="What this option buys, in one or two sentences.")
    cons: str = Field(default="", description="What it costs or risks.")
    when_appropriate: str = Field(
        default="", description="The condition under which this is the right choice."
    )
    citation: str = Field(
        default="", description="A source file:line or artifact reference the analysis rests on."
    )


class DecisionElicitationOut(BaseModel):
    """The strong model's tradeoff analysis for one decision (``--interview``)."""

    tradeoffs: list[OptionTradeoff] = Field(default_factory=list)
    recommendation: str = Field(
        default="", description="A strong recommendation naming one option, or '' to stay neutral."
    )


class DecisionPickOut(BaseModel):
    """The strong model's pick for ``--decide-for-me``."""

    chosen_option: str = Field(description="The exact option id the agent selects.")
    rationale: str = Field(description="Why this option, cited to the source evidence.")


_SYS_ELICIT = (
    "You are a port architect. A source system built on a central authority is being "
    "re-implemented for a divergent target (typically local-first / eventually "
    "consistent). A specific design decision must be made BEFORE the build because it "
    "ripples through the code. Analyze the tradeoffs of EACH menu option honestly and "
    "specifically — name the concrete consequence, cite the source evidence line where "
    "possible. Do not invent options outside the menu. Be concise."
)
_SYS_DECIDE = (
    "You are a port architect making a design decision that must be recorded as a "
    "pre-registered constraint for the builder. Choose exactly one option from the "
    "menu and justify it against the source evidence and the target's constraints. "
    "Pick the option a disciplined builder would defend; cite the evidence."
)


def _elicit_prompt(d: Decision) -> str:
    opt_lines = [
        f"- `{o.id}` ({o.label}) — lands as Port Decision kind `{o.pd_kind}`."
        + (f" {o.hint}" if o.hint else "")
        for o in d.options
    ]
    parts = [
        f"# Decision {d.id} ({d.source})",
        f"Subsystem/feature: {d.feature or '(n/a)'}",
        f"Element: {d.origin_ref}",
        f"Uncertainty grade: {d.uncertainty_grade}",
        "",
        "## Question",
        d.question,
    ]
    if d.evidence:
        parts += ["", "## Source evidence", d.evidence]
    if d.citations:
        parts += ["", "## Citations", *[f"- {c}" for c in d.citations]]
    parts += ["", "## Menu options", *opt_lines]
    return "\n".join(parts)


def elicit_decision(
    d: Decision,
    client: LLMClient,
    *,
    model: str,
    provider: str | None = None,
    max_tokens: int = 1400,
) -> StructuredCompletion[DecisionElicitationOut]:
    """Ask the strong model for a per-option tradeoff analysis (the interview doc body)."""
    return client.complete_structured(
        _elicit_prompt(d),
        schema=DecisionElicitationOut,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        system=_SYS_ELICIT,
    )


def decide_for_me(
    d: Decision,
    client: LLMClient,
    *,
    model: str,
    provider: str | None = None,
    max_tokens: int = 900,
) -> StructuredCompletion[DecisionPickOut]:
    """Ask the strong model to pick an option, with a recorded rationale."""
    return client.complete_structured(
        _elicit_prompt(d) + "\n\nChoose exactly one option id from the menu and justify it.",
        schema=DecisionPickOut,
        provider=provider,
        model=model,
        max_tokens=max_tokens,
        system=_SYS_DECIDE,
    )


# ───────────────────────── Port Decision ledger append ─────────────────────────


def append_pd_record(
    data_dir: str | Path,
    *,
    decision: Decision,
    chosen_option: str,
    rationale: str,
    author: str,
    reversible: bool = False,
    date: str | None = None,
) -> tuple[dict, Path]:
    """Append a Port Decision record (portDecisions.ts format) to the data-dir ledger.

    The record is enriched with decision-elicitation provenance (``decision_id``,
    ``chosen_option``, ``reversible``) — extra keys the TS loader tolerates.
    ``targetElement`` addresses the decision's origin so verifyPort's waiver machinery
    can relate it to a punch item. Returns ``(record, ledger_path)``.
    """
    opt = next((o for o in decision.options if o.id == chosen_option), None)
    pd_kind = opt.pd_kind if opt is not None else "preserve-with-note"
    subsystem = decision.subsystem_id or "unassigned"
    ledger = _pd_ledger_path(data_dir, subsystem)
    existing = _read_pd_ids(ledger)
    pd_id = _next_pd_id(existing, decision.id)
    record = {
        "id": pd_id,
        "date": date or _today(),
        "subsystem": subsystem,
        "targetElement": _pd_target_element(decision),
        "decision": pd_kind,
        "supersededSourceIntention": _superseded_intention(decision),
        "rationale": rationale,
        "author": author,
        # decision-elicitation provenance (extra keys; TS loader ignores unknown fields)
        "decision_id": decision.id,
        "decision_source": decision.source,
        "chosen_option": chosen_option,
        "reversible": reversible,
        "origin_ref": decision.origin_ref,
    }
    ledger.parent.mkdir(parents=True, exist_ok=True)
    with ledger.open("a", encoding="utf-8") as f:
        f.write(json.dumps(record, ensure_ascii=False) + "\n")
    return record, ledger


def _pd_ledger_path(data_dir: str | Path, subsystem: str) -> Path:
    safe = subsystem
    for ch in (":", "/", "\\"):
        safe = safe.replace(ch, "__")
    return Path(data_dir).expanduser() / "port_decisions" / f"{safe}.jsonl"


def _read_pd_ids(path: Path) -> set[str]:
    if not path.exists():
        return set()
    ids: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                ids.add(json.loads(line).get("id", ""))
            except json.JSONDecodeError:
                continue
    return ids


def _next_pd_id(existing: set[str], decision_id: str) -> str:
    """Prefer a stable, decision-scoped id; ensure uniqueness against the ledger."""
    base = "PD-" + decision_id.replace("dec:", "")[:12]
    if base not in existing:
        return base
    i = 2
    while f"{base}-{i}" in existing:
        i += 1
    return f"{base}-{i}"


def _pd_target_element(d: Decision) -> str:
    if d.source == "intent-cm":
        return f"intent_cm[element_id={d.origin_ref}]"
    if d.source == "brief-adaptation":
        role = d.origin_ref.split("/")[-1]
        return f"roles[role_id={role}]"
    if d.source == "paradigm-divergence":
        return "functor.paradigm_divergence"
    return d.origin_ref


def _superseded_intention(d: Decision) -> str:
    ev = d.evidence.strip()
    if ev:
        return ev[:400]
    return d.question[:400]


# ───────────────────────── resolution state machine ─────────────────────────


def apply_resolution(
    decision: Decision,
    *,
    mode: ResolutionMode,
    chosen_option: str | None = None,
    rationale: str = "",
    recommendation: str = "",
    author: str = "",
    reversible: bool = False,
    resolved_at: str | None = None,
    pd_record_id: str | None = None,
    pd_ledger_path: str | None = None,
    llm_model: str | None = None,
    llm_cost_usd: float = 0.0,
) -> Decision:
    """Return a new Decision with the resolution applied and status transitioned.

    Committing modes (``decide`` — a developer's answer, ``decide-for-me``,
    ``roll-forward``) set a resolved status; non-committing modes (``interview``,
    ``recommend``) leave the decision ``pending`` but attach the produced artifact.
    """
    if mode == "decide":
        status = "decided-by-developer"
    elif mode == "decide-for-me":
        status = "decided-for-me"
    elif mode == "roll-forward":
        status = "rolled-forward"
    else:  # interview / recommend — non-committing
        status = "pending"

    if chosen_option is not None:
        valid = {o.id for o in decision.options}
        if chosen_option not in valid:
            raise ValueError(
                f"chosen_option {chosen_option!r} not in menu for {decision.id}: {sorted(valid)}"
            )

    resolution = Resolution(
        mode=mode,
        chosen_option=chosen_option,
        rationale=rationale,
        recommendation=recommendation,
        reversible=reversible,
        resolved_at=resolved_at or _now(),
        author=author,
        pd_record_id=pd_record_id,
        pd_ledger_path=pd_ledger_path,
        llm_model=llm_model,
        llm_cost_usd=round(llm_cost_usd, 6),
    )
    return decision.model_copy(update={"status": status, "resolution": resolution})


# ───────────────────────── time helpers ─────────────────────────


def _now() -> str:
    return datetime.now(tz=UTC).isoformat()


def _today() -> str:
    return datetime.now(tz=UTC).strftime("%Y-%m-%d")


__all__ = [
    "SCHEMA_VERSION",
    "DECISIONS_FILE",
    "Decision",
    "DecisionOption",
    "BlastRadius",
    "Resolution",
    "uncertainty_weight",
    "map_cm_element_to_nodes",
    "compute_blast_radius",
    "collect_cm_decisions",
    "collect_brief_adaptation_decisions",
    "collect_paradigm_divergence_decisions",
    "rank_decisions",
    "read_registry",
    "write_registry",
    "merge_registry",
    "render_menu",
    "render_interview_doc",
    "OptionTradeoff",
    "DecisionElicitationOut",
    "DecisionPickOut",
    "elicit_decision",
    "decide_for_me",
    "append_pd_record",
    "apply_resolution",
]
