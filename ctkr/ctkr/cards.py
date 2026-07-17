"""Subsystem specification cards — the Stage-E output artifact (§8.1, T5).

One :class:`SubsystemCard` per subsystem; the *deck* (all cards + the subsystem
dependency graph + a repo preamble) is the cross-stack re-implementation
reference. Cards are **derived**: regenerable from the structural Parquet
artifacts (subsystems / interfaces / data_shapes / presentations / operads) plus
an L3 labeler run. The Parquet is ground truth; this JSONL is the human- and
port-facing *fusion* of the two lanes (§5) — structure decides identity and
extent, names decide intent, and the card is where they meet.

JSONL (not Parquet) per the L3 convention (:mod:`ctkr.schema_l3`): human-read,
append-friendly, ``git diff``-able. Every card carries ``spec_basis_summary``
(the honest structural-vs-nl-only floor, §5.4) and complete ``provenance``.

Determinism (the T5 acceptance contract): ``card_id`` is content-addressed over
the *structural* inputs + ``prompt_version`` + ``llm_model`` only — never the LLM
output text and never ``generated_at``. So re-running the deck over the same
inputs and the same prompt/model yields byte-identical ``card_id``s (the labels
themselves are also stable via the LLM cache at ``temperature=0``, but the id
guarantee does not depend on that).
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import blake3
from pydantic import BaseModel, Field, NonNegativeInt

# The intention channel (T5b) is a strict downstream of this schema module — the
# card *consumes* synthesized intention, never the reverse — so importing its
# output models here introduces no cycle (intention_synth imports neither cards
# nor spec_cards).
from ctkr.intention_synth import (
    AgreementRecord,
    BehavioralScenario,
    ConflictRecord,
    GlossaryTerm,
    IntentTriple,
    read_intention_jsonl,
)

SCHEMA_VERSION: int = 1

InvarianceTier = Literal["I", "N", "A"]
SpecBasis = Literal["structural", "nl-only"]


# ----- shared sub-models -----


class SpecBasisSummary(BaseModel):
    """The honest floor, on every card (§5.4). Fractions of the subsystem's
    members whose spec rests on structure vs. on natural-language text alone.
    ``structural + nl_only == 1.0`` (up to float rounding)."""

    structural: float = Field(ge=0.0, le=1.0)
    nl_only: float = Field(ge=0.0, le=1.0)


class IntentDissonance(BaseModel):
    """A first-class disagreement between structure and names (§5.3).

    Structure owns identity/extent, names own intent; when they disagree the
    card records it rather than forcing a name. ``kind`` is a short slug
    (``"name_incoherence"``, ``"role_purpose_split"``, ``"boundary_crossing"``,
    ``"low_confidence"``, ``"name_vs_structure"``); ``evidence`` is the concrete
    supporting observation a reviewer/porter reads before trusting either lane.
    ``source`` records which detector raised it (``"structural"`` = the
    name-blind deterministic check; ``"llm"`` = the labeler's judgment)."""

    kind: str
    evidence: str
    source: Literal["structural", "llm"] = "structural"


class RoleCard(BaseModel):
    """One generator (role class) of the subsystem's presentation (§4.1)."""

    role_id: str
    view: Literal["orbit", "similarity"]
    label: str  # L3
    description: str  # L3
    cardinality: int
    members: list[str]
    exemplar_symbol: str | None
    exemplar_qualified_name: str | None
    profile_depth: int
    granularity: str
    interface_participation: list[str]
    invariance_tier: InvarianceTier
    intent_dissonance: IntentDissonance | None = None


class CompositionRuleCard(BaseModel):
    """One relation (composition operation) of the subsystem (§4.3)."""

    operation_id: str
    label: str  # L3
    description: str  # L3
    op_kind: str
    arity: int
    input_roles: list[str]
    output_role: str
    edge_kinds: list[str]
    support: int
    is_boundary_op: bool
    law_notes: dict  # {"associative_observed": bool, "violations": int, "violation_kind": str}
    exemplar_paths: list[str]
    invariance_tier: InvarianceTier


class InterfaceExportCard(BaseModel):
    """One provided (API-surface) symbol crossing the boundary (§3)."""

    symbol: str
    symbol_id: str
    role_id: str | None
    usage_modes: list[str]
    contract: str  # L3
    n_external_callers: int


class InterfaceConsumeCard(BaseModel):
    """One dependency the subsystem reaches for across its boundary (§3)."""

    target: str
    target_subsystem: str | None  # None = external package / unpartitioned
    edge_kinds: list[str]
    purpose: str  # L3


class InterfaceCard(BaseModel):
    provides: list[InterfaceExportCard] = Field(default_factory=list)
    consumes: list[InterfaceConsumeCard] = Field(default_factory=list)


class DataFieldCard(BaseModel):
    name: str | None
    type: str | None
    flow: Literal["in", "out", "internal", "unknown"]


class DataShapeCard(BaseModel):
    """One type in the subsystem's data vocabulary (§3)."""

    type: str
    type_symbol_id: str
    boundary: bool
    meaning: str  # L3
    fields: list[DataFieldCard] = Field(default_factory=list)
    invariance_tier: InvarianceTier
    alphabet_coverage_note: str


class TopologyCard(BaseModel):
    """Cheap per-subsystem structural invariants (§4.4). H₁ is null until T7."""

    n_members: int
    internal_edge_histogram: dict[str, int] = Field(default_factory=dict)
    h1_summary: None = None  # until T7 (per-subsystem PD)
    cycles: int | None = None
    interface_degree: dict[str, int] = Field(default_factory=dict)  # {"in":.., "out":..}


class ExemplarSlice(BaseModel):
    """A materialized code slice a porter reads when name+label are not enough."""

    purpose: str  # e.g. "role:Validator exemplar"
    symbol_id: str
    file: str
    line_start: int
    line_end: int
    code: str


class NlOnlySymbol(BaseModel):
    """A member specced entirely by the NL lane (§5.4) — a zero-profile /
    unprofiled symbol structure could not place into any role class. Listed on
    exactly one card (its subsystem's) so the deck loses nothing. ``description``
    is the L3 reading of its source text when one was produced, else ``""``."""

    symbol_id: str
    qualified_name: str
    file: str | None
    placement: str  # "locality" | "structural"
    spec_basis: SpecBasis = "nl-only"
    description: str = ""  # L3, may be empty when not sampled for labeling


class ElementIntention(BaseModel):
    """One structural element's synthesized intention (T5b), landed on the card.

    Sourced from ``intention.jsonl`` (:mod:`ctkr.intention_synth`) and joined onto
    a card by ``element_id`` (an export/data-shape symbol_id or a role_id). Carries
    the fusion-triple INTENT block (§4.1): cited ``intent`` statements, the domain
    ``glossary``, S1 ``behavioral_scenarios``, the §5.4 ``load_class``, and the
    §6.1 ``agreement``/``conflicts``. All citations are ``intention_signals`` row
    ids (they resolve by construction, §9.2)."""

    element_id: str
    element_kind: str
    load_class: str | None = None
    intent: list[IntentTriple] = Field(default_factory=list)
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    behavioral_scenarios: list[BehavioralScenario] = Field(default_factory=list)
    agreement: AgreementRecord | None = None
    conflicts: list[ConflictRecord] = Field(default_factory=list)


class Provenance(BaseModel):
    generated_at: str  # ISO-8601
    schema_version: int = SCHEMA_VERSION
    partition_config: dict = Field(default_factory=dict)
    llm_model: str
    llm_temperature: float
    prompt_version: str
    hom_profiles_generated_at: str | None = None
    indexed_with_scip: bool = False


class SubsystemCard(BaseModel):
    """One subsystem's fused specification card (§8.1)."""

    card_id: str  # blake3(subsystem_id + structural digest + prompt_version + llm_model)
    subsystem_id: str  # FK → subsystems.parquet
    repo: str
    name: str  # L3
    intent: str  # L3 paragraph: purpose
    responsibilities: list[str] = Field(default_factory=list)  # L3
    non_goals: list[str] = Field(default_factory=list)  # L3
    spec_basis_summary: SpecBasisSummary
    intent_dissonance: list[IntentDissonance] = Field(default_factory=list)
    roles: list[RoleCard] = Field(default_factory=list)
    composition_rules: list[CompositionRuleCard] = Field(default_factory=list)
    interface: InterfaceCard = Field(default_factory=InterfaceCard)
    data_shapes: list[DataShapeCard] = Field(default_factory=list)
    topology: TopologyCard
    exemplar_slices: list[ExemplarSlice] = Field(default_factory=list)
    nl_only_symbols: list[NlOnlySymbol] = Field(default_factory=list)
    # ── intention channel (T5b, ct-intention-extraction.md §5.4/§9.1) ──
    # The §5.4 honesty gauge: fractions of the subsystem's elements per load class
    # ({structure_clear, intention_critical, ambiguous}); None until T5b runs.
    intention_load_summary: dict[str, float] | None = None
    # Per-element synthesized intention, joined from intention.jsonl by element_id.
    intention: list[ElementIntention] = Field(default_factory=list)
    n_members: NonNegativeInt
    provenance: Provenance
    schema_version: int = SCHEMA_VERSION


# ----- card_id (deterministic, structure-only) -----


def structural_digest(
    *,
    member_ids: list[str],
    role_ids: list[str],
    operation_ids: list[str],
    interface_keys: list[str],
    data_shape_keys: list[str],
) -> str:
    """Content digest over every *structural* input that feeds a card.

    Deliberately excludes all L3 text and ``generated_at`` so the digest — and
    therefore ``card_id`` — is a pure function of the partition + presentation +
    operad + interface + data-shape artifacts. Each id list is sorted before
    hashing so input order never perturbs the digest.
    """
    h = blake3.blake3()
    for name, ids in (
        ("members", member_ids),
        ("roles", role_ids),
        ("operations", operation_ids),
        ("interfaces", interface_keys),
        ("data_shapes", data_shape_keys),
    ):
        h.update(name.encode("utf-8"))
        h.update(b"\x00")
        for x in sorted(ids):
            h.update(x.encode("utf-8"))
            h.update(b"\x01")
        h.update(b"\x02")
    return h.hexdigest()


def card_id(
    *,
    subsystem_id: str,
    struct_digest: str,
    prompt_version: str,
    llm_model: str,
) -> str:
    """Deterministic card id (§8.1): blake3 of the subsystem id, its structural
    digest, and the labeler provenance (prompt_version + model). Independent of
    LLM output text and ``generated_at`` — the T5 re-run-identity contract."""
    canon = json.dumps(
        [subsystem_id, struct_digest, prompt_version, llm_model],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "card:" + blake3.blake3(canon).hexdigest()[:24]


# ----- JSONL IO -----


def write_cards(cards: list[SubsystemCard], out_path: str | Path) -> None:
    """Write the deck to ``subsystem_cards.jsonl`` (one card per line).

    Overwrites — cards are derived and a full re-run replaces the deck. Ordered
    by ``card_id`` for a stable, ``git diff``-able file.
    """
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(cards, key=lambda c: c.card_id)
    with p.open("w", encoding="utf-8") as f:
        for c in ordered:
            f.write(c.model_dump_json() + "\n")


def read_cards(path: str | Path) -> list[SubsystemCard]:
    p = Path(path).expanduser().resolve()
    out: list[SubsystemCard] = []
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            out.append(SubsystemCard.model_validate_json(line))
    return out


# ----- intention landing (T5b) -----


def _card_element_ids(card: SubsystemCard) -> set[str]:
    """Every structural element on a card that an ``intention.jsonl`` row can key
    to: role ids, provided-export symbol ids, and data-shape type symbol ids."""
    ids: set[str] = {r.role_id for r in card.roles}
    ids |= {e.symbol_id for e in card.interface.provides}
    ids |= {s.type_symbol_id for s in card.data_shapes}
    return ids


def attach_intention_to_deck(
    cards: list[SubsystemCard], intention_path: str | Path
) -> list[SubsystemCard]:
    """Join ``intention.jsonl`` (T5b) onto an existing deck (§9.1 card extension).

    For each card, attaches every :class:`ElementIntention` whose ``element_id``
    names one of the card's elements (:func:`_card_element_ids`) and computes the
    card's ``intention_load_summary`` header (§5.4) from those elements' load
    classes. Cards are mutated in place and returned. Idempotent: re-running
    replaces the attached intention. Elements with no card (rare — a harvested
    element the deck capped out of its labeled subset) are simply not attached.
    """
    rows = read_intention_jsonl(intention_path)
    by_element = {r.element_id: r for r in rows}
    for card in cards:
        attached: list[ElementIntention] = []
        class_counts: dict[str, int] = {}
        for eid in sorted(_card_element_ids(card)):
            r = by_element.get(eid)
            if r is None:
                continue
            attached.append(
                ElementIntention(
                    element_id=r.element_id,
                    element_kind=r.element_kind,
                    load_class=r.load_class,
                    intent=r.intent,
                    glossary=r.glossary,
                    behavioral_scenarios=r.behavioral_scenarios,
                    agreement=r.agreement,
                    conflicts=r.conflicts,
                )
            )
            if r.load_class:
                class_counts[r.load_class] = class_counts.get(r.load_class, 0) + 1
        card.intention = attached
        total = sum(class_counts.values())
        card.intention_load_summary = (
            {
                "structure_clear": round(class_counts.get("structure-clear", 0) / total, 4),
                "intention_critical": round(class_counts.get("intention-critical", 0) / total, 4),
                "ambiguous": round(class_counts.get("ambiguous", 0) / total, 4),
            }
            if total
            else None
        )
    return cards


__all__ = [
    "ElementIntention",
    "attach_intention_to_deck",
    "SCHEMA_VERSION",
    "InvarianceTier",
    "SpecBasis",
    "SpecBasisSummary",
    "IntentDissonance",
    "RoleCard",
    "CompositionRuleCard",
    "InterfaceExportCard",
    "InterfaceConsumeCard",
    "InterfaceCard",
    "DataFieldCard",
    "DataShapeCard",
    "TopologyCard",
    "ExemplarSlice",
    "NlOnlySymbol",
    "Provenance",
    "SubsystemCard",
    "structural_digest",
    "card_id",
    "write_cards",
    "read_cards",
]
