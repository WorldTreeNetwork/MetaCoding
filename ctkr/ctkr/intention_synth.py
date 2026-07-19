"""Intention synthesis — Stage T5b (ct-intention-extraction.md §8, §9.2).

The **LM** layer of the intention channel, downstream of T5a's mechanical harvest
(:mod:`ctkr.intention`). T5a froze the *what* (structural elements) and harvested
every incidental indicator of intention into ``intention_signals.parquet`` +
``intention_load.parquet`` + ``intention_conflicts.parquet``. T5b fuses those
into *synthesized intention* per element:

1. **Per-element intent synthesis** (cheap model, §8): the ranked harvest for one
   element → an INTENT block of the fusion triple (§4.1) — purpose statements,
   each *citing* the ``signal_id``s it rests on, plus a domain **glossary** for
   the element's vocabulary signals (A3/A4/A5/S2). The reading LM/human can always
   tell which claim is *read* (INTENT) from which is *checked* (SHAPE) or *raw*
   (EVIDENCE).
2. **Scenario distillation** (cheap model): S1 test signals → given/when/then
   behavioral scenarios (§4.2 item 7), each citing its source test signal rows.
   This is the port's acceptance list.
3. **Conflict adjudication** (strong model, §6.1 stage 2): only for a *flagged*
   subset — elements with a mechanical conflict candidate, low labeler confidence,
   or an ``ambiguous`` load class. Emits ``agreement ∈ {consistent, tension,
   contradiction}`` with citations, catching contradictions the mechanical table
   never anticipated.

**Determinism (§8).** Prompts are rendered from a *structured evidence digest* —
a canonical serialization of the element's ``intention_signals`` rows + its load
row + a small structural fact sheet — so the LLM-cache key is effectively
``(digest, prompt_version, model)``: unchanged evidence → a free, byte-identical
re-run; any harvest change flows into the digest and invalidates precisely the
affected elements. The ``intention_id`` is content-addressed over that same digest
+ provenance and is *independent of the LLM output text* — the T5 re-run-identity
contract (:mod:`ctkr.cards`), carried to the intention layer.

**Citations that resolve.** The LLM never sees or emits raw ``signal_id``s (they
are opaque hashes it would hallucinate). Instead every signal gets a stable,
1-based *tag* in the deterministically-ordered evidence list; the model cites tag
numbers; :func:`_resolve_citations` maps them back to ``signal_id``s and drops any
out-of-range tag. So every citation on every synthesized sentence resolves to a
real harvested signal (the §9.2 acceptance), by construction.

Output: ``intention.jsonl`` (§9.1) — one :class:`IntentionRow` per element,
extending the ``patterns.jsonl`` provenance conventions with ``agreement`` and
``conflict`` payloads. All four mandatory provenance fields per
``ctkr-l3-artifacts.md``.
"""

from __future__ import annotations

import json
import logging
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import blake3
import polars as pl
from pydantic import BaseModel, Field, field_validator, model_validator

from ctkr.llm import LLMClient
from ctkr.schema_l3 import SCHEMA_VERSION

logger = logging.getLogger("ctkr.intention_synth")

DEFAULT_PROMPT_VERSION = "intention-synth:v1"
# The cheap per-element pass — same default the role/spec labelers use (§8: "cheap
# haiku-class, high volume, narrow judgment").
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
# The strong adjudication pass (§8: "contradiction-finding is exactly where cheap
# models rubber-stamp"). Falls back to ``model`` when None so the mock/offline
# path stays single-model.
DEFAULT_ADJUDICATION_MODEL = "claude-sonnet-4-6"
DEFAULT_TEMPERATURE = 0.0

# Adjudication is filtered, not corpus-wide (§8). An element is a candidate when a
# mechanical screen or the cheap labeler flags it: a conflict candidate exists, an
# ``ambiguous`` load class (structure underdetermined *and* intention thin/
# contradictory — the likeliest home of a real contradiction), or the cheap intent
# pass reported low confidence.
DEFAULT_LOW_CONFIDENCE = 0.5

# Tier rank for deterministic evidence ordering (S strongest → C weakest, §1).
_TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}
_PORTABILITY_WORD = {"universal": "I", "convention": "N", "idiom": "A"}


# ───────────────────────── output-facing schemas (intention.jsonl) ─────────────────────────


class IntentTriple(BaseModel):
    """One INTENT statement of the fusion triple (§4.1) with resolved citations.

    ``statement`` is LM prose (a *read* claim, not verifier-checkable); ``citations``
    are the ``signal_id``s it rests on (all resolve to real harvested rows, §9.2);
    ``portability_tier`` is the §7.2 intent tag (``I`` universal / ``N`` convention
    / ``A`` idiom) — the brief restates N and drops A, keeps I verbatim.
    """

    statement: str
    citations: list[str]
    portability_tier: Literal["I", "N", "A"] = "I"


class GlossaryTerm(BaseModel):
    """One domain-vocabulary term (§4.2 item 2), distilled from A3/A4/A5/S2."""

    term: str
    meaning: str
    citations: list[str]


class BehavioralScenario(BaseModel):
    """One given/when/then behavior the S1 tests pin (§4.2 item 7).

    ``citations`` cite the S1 test signal rows the scenario was distilled from —
    the port's new suite must cover this behavior.
    """

    behavior: str
    given: str
    when: str
    then: str
    citations: list[str]


class AgreementRecord(BaseModel):
    """The strong model's §6.1-stage-2 verdict on structure↔intention agreement."""

    verdict: Literal["consistent", "tension", "contradiction"]
    rationale: str
    citations: list[str]
    model: str


class ConflictRecord(BaseModel):
    """A T5a mechanical conflict candidate, carried onto the card with the strong
    model's adjudicated verdict attached (``adjudicated`` is None when the element
    was not routed to adjudication)."""

    conflict_id: str
    detector_id: str
    severity: str
    claim: str
    structural_fact: str
    file: str
    line_range: str
    adjudicated: Literal["consistent", "tension", "contradiction"] | None = None


class IntentionRow(BaseModel):
    """One element's synthesized intention (§9.1 ``intention.jsonl``).

    Extends the ``patterns.jsonl`` provenance conventions (:mod:`ctkr.schema_l3`)
    with ``agreement`` and ``conflict`` payloads. ``intention_id`` is
    content-addressed over the evidence digest + prompt_version + model and is
    independent of the LLM output — the T5 re-run-identity contract carried to the
    intention layer. The ``intention_load`` fields are copied verbatim from T5a
    (§5.4 surfacing); the intent/glossary/scenarios/agreement are the synthesis.
    """

    intention_id: str
    element_id: str
    element_kind: str  # SourceKind: interface-export | role-class | data-shape | …
    subsystem_id: str | None
    # ── §5.4 load surfacing (verbatim from intention_load.parquet) ──
    load_class: str | None
    structural_determinacy: float | None
    intention_richness: float | None
    load_drivers: list[str] = Field(default_factory=list)
    port_critical_conflict: bool = False
    # ── the synthesis ──
    intent: list[IntentTriple] = Field(default_factory=list)
    glossary: list[GlossaryTerm] = Field(default_factory=list)
    behavioral_scenarios: list[BehavioralScenario] = Field(default_factory=list)
    agreement: AgreementRecord | None = None
    conflicts: list[ConflictRecord] = Field(default_factory=list)
    n_signals: int = 0
    evidence_digest: str = ""
    # ── mandatory provenance (ctkr-l3-artifacts.md) ──
    llm_model: str
    llm_temperature: float
    prompt_version: str
    schema_version: int = SCHEMA_VERSION
    generated_at: str


# ───────────────────────── LLM-facing schemas (the LLM owns ONLY these) ─────────────────────────
#
# Citations are TAG NUMBERS (1-based indices into the deterministically-ordered
# evidence list the prompt shows), never signal_ids — the model can't hallucinate
# an id it never saw. _resolve_citations maps tags → signal_ids and drops the rest.


def _coerce_int_tags(v: object) -> list[int]:
    """Tolerate tags returned as ["3"], "3", [3] or "3, 4" — a cheap model habit."""
    if v is None:
        return []
    if isinstance(v, int):
        return [v]
    if isinstance(v, str):
        out: list[int] = []
        for part in v.replace(";", ",").split(","):
            part = part.strip().lstrip("[#").rstrip("]")
            if part.isdigit():
                out.append(int(part))
        return out
    if isinstance(v, (list, tuple)):
        out2: list[int] = []
        for x in v:
            if isinstance(x, bool):
                continue
            if isinstance(x, int):
                out2.append(x)
            elif isinstance(x, str) and x.strip().lstrip("[#").rstrip("]").isdigit():
                out2.append(int(x.strip().lstrip("[#").rstrip("]")))
        return out2
    return []


def _coerce_obj_list(v: object) -> list:
    """Tolerate a nested-object list field returned as a JSON *string* — a cheap-
    model habit (the whole ``[{...}, {...}]`` arrives stringified, or a lone
    ``{...}`` for a one-item list). Pydantic then validates the inner dicts against
    the nested model as usual. Anything unparseable degrades to ``[]`` rather than
    crashing the run (the element gets an empty synthesis, not a lost batch)."""
    if v is None:
        return []
    if isinstance(v, list):
        return v
    if isinstance(v, dict):
        return [v]
    if isinstance(v, str):
        s = v.strip()
        if not s:
            return []
        try:
            parsed = json.loads(s)
        except (json.JSONDecodeError, ValueError):
            return []
        if isinstance(parsed, list):
            return parsed
        if isinstance(parsed, dict):
            return [parsed]
        return []
    return []


class _IntentStatementOut(BaseModel):
    statement: str = Field(
        description="One purpose sentence for this element, "
        "stated stack-agnostically (what it is FOR, not how it "
        "is built). Must be supported by cited evidence."
    )
    citations: list[int] = Field(
        default_factory=list,
        description="Evidence tag numbers this sentence "
        "rests on (the [n] markers in the evidence list).",
    )
    portability: Literal["universal", "convention", "idiom"] = Field(
        default="universal",
        description="universal = survives any stack verbatim (behavior, policy, "
        "domain meaning); convention = real but stack-idiomatic, restate it; "
        "idiom = meaningful only in the source stack.",
    )

    @field_validator("citations", mode="before")
    @classmethod
    def _c(cls, v: object) -> list[int]:
        return _coerce_int_tags(v)


class _GlossaryOut(BaseModel):
    term: str = Field(
        description="A domain-vocabulary term (a type, field, "
        "parameter, constant, or role noun this element uses)."
    )
    meaning: str = Field(description="One line: what the term means in this domain.")
    citations: list[int] = Field(default_factory=list)

    @field_validator("citations", mode="before")
    @classmethod
    def _c(cls, v: object) -> list[int]:
        return _coerce_int_tags(v)


class ElementIntentOut(BaseModel):
    """Per-element intent synthesis (cheap model)."""

    intent: list[_IntentStatementOut] = Field(
        default_factory=list, description="1-4 purpose statements, each cited."
    )
    glossary: list[_GlossaryOut] = Field(
        default_factory=list,
        description="0-6 domain terms this element's names/fields introduce.",
    )
    confidence: float = Field(
        default=1.0,
        ge=0.0,
        le=1.0,
        description="Your confidence the intent is well-supported by the evidence. "
        "Low when the evidence is thin, generic, or self-contradictory.",
    )

    @field_validator("intent", "glossary", mode="before")
    @classmethod
    def _lists(cls, v: object) -> list:
        return _coerce_obj_list(v)

    @field_validator("confidence", mode="before")
    @classmethod
    def _conf(cls, v: object) -> float:
        try:
            return max(0.0, min(1.0, float(v)))  # type: ignore[arg-type]
        except (TypeError, ValueError):
            return 1.0


# Unambiguous synonyms a reasoning model emits for the given/when/then triple.
# Only 1:1 renames — mapping one of these onto the canonical field never invents
# content, it relabels a value the model already produced. Anything not on these
# lists is left alone (the item then fails validation and the repair retry / drop
# takes over) so we never guess.
_GIVEN_ALIASES = ("precondition", "preconditions", "context", "setup", "background", "arrange")
_WHEN_ALIASES = ("action", "act", "event", "trigger", "stimulus")
_THEN_ALIASES = (
    "outcome",
    "result",
    "expected",
    "expected_outcome",
    "expected_result",
    "expect",
    "assertion",
    "ensure",
)


def _canonicalize_scenario(v: object) -> object:
    """Map known near-miss GPT-5.6 scenario shapes onto the canonical
    given/when/then object. Two shapes are handled, both loss-free:

    * a nested triple emitted under ``behavior`` (``{"behavior": {"given": …,
      "when": …, "then": …}}``) is lifted to the top level, keeping any nested
      name; and
    * an unambiguous synonym for a *missing* canonical field (``outcome`` /
      ``result`` → ``then``, etc.) is copied onto it.

    A canonical field already present and non-empty is never overwritten, and a
    missing field with no known synonym is left missing — so a bare
    ``{"behavior": "…"}`` (no given/when/then, no synonyms) is deliberately NOT
    salvaged. That case is the repair retry's job; guessing it here would invent
    content.
    """
    if not isinstance(v, dict):
        return v
    d = dict(v)

    # Shape 1: a whole given/when/then object nested under "behavior".
    beh = d.get("behavior")
    if isinstance(beh, dict):
        nested = {str(k).lower(): val for k, val in beh.items()}
        if {"given", "when", "then"} & set(nested):
            name = nested.pop("behavior", None) or nested.pop("name", None) or nested.pop(
                "title", None
            )
            for key in ("given", "when", "then", "citations"):
                if key in nested and not d.get(key):
                    d[key] = nested[key]
            d["behavior"] = name if isinstance(name, str) else ""

    # Shape 2: an unambiguous synonym for a missing canonical field.
    lower = {str(k).lower(): k for k in d}
    for canon, aliases in (
        ("given", _GIVEN_ALIASES),
        ("when", _WHEN_ALIASES),
        ("then", _THEN_ALIASES),
    ):
        if d.get(canon):
            continue
        for alias in aliases:
            src = lower.get(alias)
            if src is not None and d.get(src) not in (None, ""):
                d[canon] = d[src]
                break
    return d


class _ScenarioItemOut(BaseModel):
    behavior: str = Field(description="A short name for the behavior this test pins.")
    given: str = Field(description="Preconditions / context.")
    when: str = Field(description="The action taken.")
    then: str = Field(description="The asserted outcome.")
    citations: list[int] = Field(
        default_factory=list, description="Tag numbers of the source test signals."
    )

    @model_validator(mode="before")
    @classmethod
    def _canonicalize(cls, v: object) -> object:
        return _canonicalize_scenario(v)

    @field_validator("citations", mode="before")
    @classmethod
    def _c(cls, v: object) -> list[int]:
        return _coerce_int_tags(v)


class ScenarioDistillOut(BaseModel):
    """S1 → given/when/then behavioral scenarios (cheap model)."""

    scenarios: list[_ScenarioItemOut] = Field(default_factory=list)

    @field_validator("scenarios", mode="before")
    @classmethod
    def _lists(cls, v: object) -> list:
        return _coerce_obj_list(v)


class AdjudicationOut(BaseModel):
    """Structure↔intention agreement verdict (strong model, §6.1 stage 2)."""

    verdict: Literal["consistent", "tension", "contradiction"] = Field(
        description="consistent = intention and structure agree; tension = a soft "
        "mismatch (stale doc, weak naming); contradiction = the name/doc claims "
        "behavior the structure refutes — a port-critical divergence.",
    )
    rationale: str = Field(
        description="One or two sentences citing the specific "
        "evidence and structural fact that agree or conflict."
    )
    citations: list[int] = Field(default_factory=list)

    @field_validator("citations", mode="before")
    @classmethod
    def _c(cls, v: object) -> list[int]:
        return _coerce_int_tags(v)


# ───────────────────────── evidence digest + tagging ─────────────────────────


@dataclass(frozen=True)
class _TaggedSignal:
    tag: int
    signal_id: str
    indicator_kind: str
    tier: str
    content: str
    portability_tier: str
    file: str
    line_range: str


def _order_signals(sig_rows: Sequence[dict]) -> list[_TaggedSignal]:
    """Deterministically order an element's signals and assign 1-based tags.

    Order: tier rank (S→C), then indicator_kind, content, file, line_range — a
    total order independent of harvest/iteration order, so the tag list (and thus
    the digest, the prompt, and the cache key) is byte-stable across runs.
    """
    ordered = sorted(
        sig_rows,
        key=lambda r: (
            _TIER_RANK.get(r["tier"], 9),
            r["indicator_kind"],
            r["content"],
            r["file"],
            r["line_range"],
        ),
    )
    return [
        _TaggedSignal(
            tag=i + 1,
            signal_id=r["signal_id"],
            indicator_kind=r["indicator_kind"],
            tier=r["tier"],
            content=r["content"],
            portability_tier=r["portability_tier"],
            file=r["file"],
            line_range=r["line_range"],
        )
        for i, r in enumerate(ordered)
    ]


def evidence_digest(
    element_id: str,
    element_kind: str,
    tagged: Sequence[_TaggedSignal],
    load_row: dict | None,
    conflict_rows: Sequence[dict],
) -> str:
    """Canonical structured-evidence digest (§8) → blake3 hex.

    A pure function of the element's harvested evidence: the ordered signal tuples,
    the load scores/class/drivers, and the mechanical conflict candidates. No
    timestamps, no LLM text, no set-iteration order. Drives both the prompt-cache
    stability and the ``intention_id``.
    """
    payload = {
        "element_id": element_id,
        "element_kind": element_kind,
        "signals": [
            [t.tag, t.indicator_kind, t.tier, t.content, t.portability_tier, t.file, t.line_range]
            for t in tagged
        ],
        "load": None
        if load_row is None
        else {
            "class": load_row["load_class"],
            "D": load_row["structural_determinacy"],
            "R": load_row["intention_richness"],
            "port_critical": load_row["port_critical_conflict"],
            "drivers": list(load_row["drivers"]),
        },
        "conflicts": sorted(
            [
                [
                    c["conflict_id"],
                    c["detector_id"],
                    c["severity"],
                    c["claim"],
                    c["structural_fact"],
                ]
                for c in conflict_rows
            ]
        ),
    }
    canon = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return blake3.blake3(canon.encode("utf-8")).hexdigest()


def intention_id(element_id: str, digest: str, *, prompt_version: str, llm_model: str) -> str:
    """Deterministic ``intention_id`` — blake3 of the element id, its evidence
    digest, and the provenance (prompt_version + model). Independent of the LLM
    output text and ``generated_at`` (the §8 re-run-identity contract)."""
    canon = json.dumps(
        [element_id, digest, prompt_version, llm_model],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return "intent:" + blake3.blake3(canon).hexdigest()[:24]


def _resolve_citations(tags: Sequence[int], tagged: Sequence[_TaggedSignal]) -> list[str]:
    """Map cited tag numbers → ``signal_id``s; drop out-of-range tags; dedupe in
    first-seen order. Guarantees every returned id is a real harvested signal."""
    by_tag = {t.tag: t.signal_id for t in tagged}
    out: list[str] = []
    seen: set[str] = set()
    for n in tags:
        sid = by_tag.get(n)
        if sid and sid not in seen:
            seen.add(sid)
            out.append(sid)
    return out


# ───────────────────────── prompt rendering (pure) ─────────────────────────

_VOCAB_INDICATORS = {"S2", "A3", "A4", "A5"}  # the glossary source tiers (§4.2 item 2)

_SYS_INTENT = (
    "You synthesize the INTENT of one structural code element for a cross-stack "
    "re-implementation spec. The element's identity and extent were fixed name-"
    "blind by a prior structural pass; your job is the SECOND lane — read the "
    "incidental evidence of intention (names, docstrings, error strings, "
    "decorators, tests, constants) and state what the element is FOR and why it "
    "exists.\n\n"
    "Rules:\n"
    "- Every intent statement MUST cite the evidence tag numbers ([n]) that "
    "support it. Do not state anything the evidence does not support.\n"
    "- State intent stack-agnostically: what behavior/policy/purpose, never the "
    "source idiom. Tag each statement's portability: universal (survives any "
    "stack), convention (real but idiomatic — will be restated), idiom (source-"
    "stack-only).\n"
    "- The glossary is the domain vocabulary the element introduces (its types, "
    "fields, parameters, constants, role nouns) — each term one line, cited.\n"
    "- Report LOW confidence when the evidence is thin, generic, or contradictory."
)

_SYS_SCENARIO = (
    "You distill test evidence into behavioral scenarios for a re-implementation "
    "acceptance list. Each test signal names a behavior the original suite has "
    "been checking. Turn the tests below into given/when/then scenarios — one per "
    "distinct behavior — each citing the tag numbers of the tests it came from. "
    "Transcribe faithfully; do not invent behaviors the tests do not name."
)

_SYS_ADJUDICATE = (
    "You are the strong-model adjudicator for structure↔intention agreement. A "
    "name-blind structural pass observed hard facts about this element (edges, "
    "field-flow, caller counts, laws). A separate harvest collected what the "
    "element's names/docs/tests CLAIM. Decide whether the claimed intention is "
    "consistent with the observed structure, in soft tension, or in outright "
    "contradiction (a name/doc asserting behavior the structure refutes — the "
    "port would be built wrong if it trusted the name). Cite the specific "
    "evidence tags. Be conservative: reserve 'contradiction' for a genuine "
    "structural refutation, not mere vagueness."
)


def _render_evidence_block(
    tagged: Sequence[_TaggedSignal], *, only: set[str] | None = None
) -> list[str]:
    lines: list[str] = []
    for t in tagged:
        if only is not None and t.indicator_kind not in only:
            continue
        loc = f" ({t.file}:{t.line_range})" if t.file else ""
        lines.append(f"[{t.tag}] {t.indicator_kind}/{t.tier} {t.content}{loc}")
    return lines


def _fact_sheet(element_id: str, element_kind: str, load_row: dict | None) -> list[str]:
    lines = [f"- element kind: {element_kind}", f"- element id: {element_id[:16]}"]
    if load_row is not None:
        lines.append(
            f"- structural determinacy D={load_row['structural_determinacy']}, "
            f"intention richness R={load_row['intention_richness']}, "
            f"load class: {load_row['load_class']}"
        )
        if load_row["drivers"]:
            lines.append("- score drivers: " + "; ".join(load_row["drivers"][:6]))
    return lines


def render_intent_prompt(
    element_id: str, element_kind: str, tagged: Sequence[_TaggedSignal], load_row: dict | None
) -> str:
    ev = _render_evidence_block(tagged)
    return "\n".join(
        [
            f"# Element `{element_id[:16]}` ({element_kind})",
            "",
            "## Structural fact sheet (name-blind — checked, not read)",
            *_fact_sheet(element_id, element_kind, load_row),
            "",
            "## Harvested intention evidence (cite these tag numbers)",
            *(ev or ["(no evidence harvested)"]),
            "",
            "Emit an ElementIntentOut: cited intent statements + a domain glossary.",
        ]
    )


def render_scenario_prompt(element_id: str, element_kind: str, s1: Sequence[_TaggedSignal]) -> str:
    ev = [f"[{t.tag}] {t.content}" + (f" ({t.file}:{t.line_range})" if t.file else "") for t in s1]
    return "\n".join(
        [
            f"# Tests exercising `{element_id[:16]}` ({element_kind})",
            "",
            *(ev or ["(no tests)"]),
            "",
            "Emit a ScenarioDistillOut: one given/when/then per distinct behavior, "
            "each citing the test tag numbers it came from.",
        ]
    )


def render_adjudication_prompt(
    element_id: str,
    element_kind: str,
    tagged: Sequence[_TaggedSignal],
    load_row: dict | None,
    conflict_rows: Sequence[dict],
) -> str:
    conflict_lines = [
        f"- [{c['detector_id']}/{c['severity']}] claim: {c['claim']} — "
        f"structure: {c['structural_fact']}"
        for c in conflict_rows
    ]
    return "\n".join(
        [
            f"# Adjudicate `{element_id[:16]}` ({element_kind})",
            "",
            "## Structural facts (name-blind, observed)",
            *_fact_sheet(element_id, element_kind, load_row),
            "",
            "## Mechanical conflict candidates (may be empty)",
            *(conflict_lines or ["(none — assess the evidence against the facts directly)"]),
            "",
            "## Harvested intention evidence (cite tag numbers)",
            *(_render_evidence_block(tagged) or ["(no evidence)"]),
            "",
            "Emit an AdjudicationOut: verdict ∈ {consistent, tension, contradiction} "
            "+ cited rationale.",
        ]
    )


# ───────────────────────── synthesis driver ─────────────────────────


@dataclass
class SynthStats:
    n_elements: int = 0
    n_intent_calls: int = 0
    n_scenario_calls: int = 0
    n_adjudications: int = 0
    n_flagged: int = 0
    n_intent_statements: int = 0
    n_glossary_terms: int = 0
    n_scenarios: int = 0
    n_citations_resolved: int = 0
    n_citations_dropped: int = 0
    agreement_counts: dict[str, int] = field(default_factory=dict)
    n_confirmed_contradictions: int = 0
    by_element_kind: dict[str, int] = field(default_factory=dict)
    n_intent_fallbacks: int = (
        0  # elements where empty cheap intent was refilled by the strong model
    )
    n_failed_calls: int = 0  # LLM calls whose response didn't parse (degraded, not fatal)
    total_cost_usd: float = 0.0
    cache_hits: int = 0
    total_seconds: float = 0.0


@dataclass
class _Synthesizer:
    client: LLMClient
    model: str = DEFAULT_MODEL
    adjudication_model: str | None = DEFAULT_ADJUDICATION_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    prompt_version: str = DEFAULT_PROMPT_VERSION
    low_confidence: float = DEFAULT_LOW_CONFIDENCE
    max_tokens: int = 1200

    def _call(
        self, prompt: str, *, schema: type[BaseModel], system: str, model: str, stats: SynthStats
    ) -> tuple[BaseModel | None, float, bool]:
        """One resilient structured call. On a provider/validation failure returns
        ``(None, 0.0, False)`` and bumps ``n_failed_calls`` — a single bad response
        degrades one element's synthesis rather than aborting the whole batch
        (mirrors :func:`ctkr.label_roles.label_roles`'s per-cluster try/except)."""
        try:
            res = self.client.complete_structured(
                prompt,
                schema=schema,
                model=model,
                temperature=self.temperature,
                max_tokens=self.max_tokens,
                system=system,
                # One-shot repair: reasoning models trip the nested ScenarioDistillOut
                # required-field validation stochastically (MetaCoding-9h5.9). Re-prompt
                # once with the error rather than degrade the element to 0 scenarios.
                repair=True,
            )
            return res.parsed, res.cost_estimate_usd, res.cache_hit
        except Exception as e:  # noqa: BLE001 — provider/validation errors vary
            logger.warning("synthesis call failed (%s): %s", schema.__name__, e)
            stats.n_failed_calls += 1
            return None, 0.0, False

    def synthesize_element(
        self,
        *,
        element_id: str,
        element_kind: str,
        subsystem_id: str | None,
        sig_rows: Sequence[dict],
        load_row: dict | None,
        conflict_rows: Sequence[dict],
        stats: SynthStats,
    ) -> IntentionRow:
        tagged = _order_signals(sig_rows)
        digest = evidence_digest(element_id, element_kind, tagged, load_row, conflict_rows)
        iid = intention_id(
            element_id, digest, prompt_version=self.prompt_version, llm_model=self.model
        )

        # ── intent synthesis (cheap) ──
        intent_prompt = render_intent_prompt(element_id, element_kind, tagged, load_row)
        iparsed, icost, ihit = self._call(
            intent_prompt,
            schema=ElementIntentOut,
            system=_SYS_INTENT,
            model=self.model,
            stats=stats,
        )
        iout: ElementIntentOut = iparsed or ElementIntentOut()  # type: ignore[assignment]
        stats.n_intent_calls += 1
        stats.total_cost_usd += icost
        stats.cache_hits += 1 if ihit else 0

        # Empty-intent fallback: when the cheap model produces no intent statement
        # for an element that *does* carry evidence, retry once on the strong model
        # (thin/ambiguous signal is where cheap models give up but a stronger reader
        # can still extract purpose). Deterministic + cached (distinct model key);
        # the intention_id stays keyed on ``self.model`` so ids do not move.
        strong = self.adjudication_model or self.model
        if not iout.intent and tagged and strong != self.model:
            fparsed, fcost, fhit = self._call(
                intent_prompt,
                schema=ElementIntentOut,
                system=_SYS_INTENT,
                model=strong,
                stats=stats,
            )
            stats.total_cost_usd += fcost
            stats.cache_hits += 1 if fhit else 0
            if fparsed is not None and fparsed.intent:  # type: ignore[attr-defined]
                iout = fparsed  # type: ignore[assignment]
                stats.n_intent_fallbacks += 1

        intent: list[IntentTriple] = []
        for st in iout.intent:
            cites = _resolve_citations(st.citations, tagged)
            stats.n_citations_resolved += len(cites)
            stats.n_citations_dropped += max(0, len(st.citations) - len(cites))
            intent.append(
                IntentTriple(
                    statement=st.statement,
                    citations=cites,
                    portability_tier=_PORTABILITY_WORD.get(st.portability, "I"),  # type: ignore[arg-type]
                )
            )
        glossary: list[GlossaryTerm] = []
        for gt in iout.glossary:
            cites = _resolve_citations(gt.citations, tagged)
            stats.n_citations_resolved += len(cites)
            stats.n_citations_dropped += max(0, len(gt.citations) - len(cites))
            glossary.append(GlossaryTerm(term=gt.term, meaning=gt.meaning, citations=cites))
        stats.n_intent_statements += len(intent)
        stats.n_glossary_terms += len(glossary)

        # ── scenario distillation (cheap; only when S1 tests link the element) ──
        scenarios: list[BehavioralScenario] = []
        s1 = [t for t in tagged if t.indicator_kind == "S1"]
        if s1:
            sprompt = render_scenario_prompt(element_id, element_kind, s1)
            sparsed, scost, shit = self._call(
                sprompt,
                schema=ScenarioDistillOut,
                system=_SYS_SCENARIO,
                model=self.model,
                stats=stats,
            )
            sout: ScenarioDistillOut = sparsed or ScenarioDistillOut()  # type: ignore[assignment]
            stats.n_scenario_calls += 1
            stats.total_cost_usd += scost
            stats.cache_hits += 1 if shit else 0
            for sc in sout.scenarios:
                cites = _resolve_citations(sc.citations, tagged)
                stats.n_citations_resolved += len(cites)
                stats.n_citations_dropped += max(0, len(sc.citations) - len(cites))
                scenarios.append(
                    BehavioralScenario(
                        behavior=sc.behavior,
                        given=sc.given,
                        when=sc.when,
                        then=sc.then,
                        citations=cites,
                    )
                )
            stats.n_scenarios += len(scenarios)

        # ── conflict adjudication (strong; only the flagged subset) ──
        agreement: AgreementRecord | None = None
        low_conf = iout.confidence < self.low_confidence
        ambiguous = bool(load_row and load_row["load_class"] == "ambiguous")
        flagged = bool(conflict_rows) or low_conf or ambiguous
        if flagged:
            stats.n_flagged += 1
            adj_model = self.adjudication_model or self.model
            aprompt = render_adjudication_prompt(
                element_id, element_kind, tagged, load_row, conflict_rows
            )
            aparsed, acost, ahit = self._call(
                aprompt,
                schema=AdjudicationOut,
                system=_SYS_ADJUDICATE,
                model=adj_model,
                stats=stats,
            )
            stats.total_cost_usd += acost
            stats.cache_hits += 1 if ahit else 0
            if aparsed is not None:
                aout: AdjudicationOut = aparsed  # type: ignore[assignment]
                stats.n_adjudications += 1
                cites = _resolve_citations(aout.citations, tagged)
                stats.n_citations_resolved += len(cites)
                stats.n_citations_dropped += max(0, len(aout.citations) - len(cites))
                agreement = AgreementRecord(
                    verdict=aout.verdict, rationale=aout.rationale, citations=cites, model=adj_model
                )
                stats.agreement_counts[aout.verdict] = (
                    stats.agreement_counts.get(aout.verdict, 0) + 1
                )
                if aout.verdict == "contradiction":
                    stats.n_confirmed_contradictions += 1

        conflicts = [
            ConflictRecord(
                conflict_id=c["conflict_id"],
                detector_id=c["detector_id"],
                severity=c["severity"],
                claim=c["claim"],
                structural_fact=c["structural_fact"],
                file=c["file"],
                line_range=c["line_range"],
                adjudicated=agreement.verdict if agreement else None,
            )
            for c in conflict_rows
        ]

        stats.by_element_kind[element_kind] = stats.by_element_kind.get(element_kind, 0) + 1
        return IntentionRow(
            intention_id=iid,
            element_id=element_id,
            element_kind=element_kind,
            subsystem_id=subsystem_id,
            load_class=load_row["load_class"] if load_row else None,
            structural_determinacy=load_row["structural_determinacy"] if load_row else None,
            intention_richness=load_row["intention_richness"] if load_row else None,
            load_drivers=list(load_row["drivers"]) if load_row else [],
            port_critical_conflict=bool(load_row["port_critical_conflict"]) if load_row else False,
            intent=intent,
            glossary=glossary,
            behavioral_scenarios=scenarios,
            agreement=agreement,
            conflicts=conflicts,
            n_signals=len(tagged),
            evidence_digest=digest,
            llm_model=self.model,
            llm_temperature=self.temperature,
            prompt_version=self.prompt_version,
            generated_at=datetime.now(tz=UTC).isoformat(),
        )


def synthesize_intention(
    *,
    signals_df: pl.DataFrame,
    load_df: pl.DataFrame,
    conflicts_df: pl.DataFrame,
    members_df: pl.DataFrame | None,
    client: LLMClient,
    model: str = DEFAULT_MODEL,
    adjudication_model: str | None = DEFAULT_ADJUDICATION_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    low_confidence: float = DEFAULT_LOW_CONFIDENCE,
    max_elements: int | None = None,
) -> tuple[list[IntentionRow], SynthStats]:
    """Run T5b synthesis over every harvested element. Deterministic given the same
    inputs + prompt_version + model (via the evidence digest + LLM cache, §8).

    Iterates the union of load-scored elements and signal-bearing elements (the
    latter picks up data-shapes, which carry glossary vocabulary but no load row),
    in a stable ``(element_kind, element_id)`` order.
    """
    start = time.perf_counter()
    stats = SynthStats()

    sig_by: dict[str, list[dict]] = {}
    kind_by: dict[str, str] = {}
    for r in signals_df.iter_rows(named=True):
        sig_by.setdefault(r["element_id"], []).append(r)
        kind_by[r["element_id"]] = r["element_kind"]

    load_by: dict[str, dict] = {}
    for r in load_df.iter_rows(named=True):
        load_by[r["element_id"]] = r
        kind_by.setdefault(r["element_id"], r["element_kind"])

    conf_by: dict[str, list[dict]] = {}
    for r in conflicts_df.iter_rows(named=True):
        conf_by.setdefault(r["element_id"], []).append(r)

    sub_by: dict[str, str] = {}
    if members_df is not None:
        for r in members_df.iter_rows(named=True):
            sub_by[r["symbol_id"]] = r["subsystem_id"]

    element_ids = sorted(set(sig_by) | set(load_by), key=lambda e: (kind_by.get(e, ""), e))
    if max_elements is not None:
        element_ids = element_ids[:max_elements]
    stats.n_elements = len(element_ids)

    synth = _Synthesizer(
        client=client,
        model=model,
        adjudication_model=adjudication_model,
        temperature=temperature,
        prompt_version=prompt_version,
        low_confidence=low_confidence,
    )

    rows: list[IntentionRow] = []
    for i, eid in enumerate(element_ids, 1):
        row = synth.synthesize_element(
            element_id=eid,
            element_kind=kind_by.get(eid, "symbol"),
            subsystem_id=sub_by.get(eid),
            sig_rows=sig_by.get(eid, []),
            load_row=load_by.get(eid),
            conflict_rows=conf_by.get(eid, []),
            stats=stats,
        )
        rows.append(row)
        if i % 25 == 0:
            logger.info("synthesized %d/%d elements", i, len(element_ids))

    rows.sort(key=lambda r: r.intention_id)
    stats.total_cost_usd = round(stats.total_cost_usd, 6)
    stats.total_seconds = round(time.perf_counter() - start, 3)
    return rows, stats


# ───────────────────────── intention.jsonl IO ─────────────────────────


def write_intention_jsonl(rows: Sequence[IntentionRow], out_path: str | Path) -> None:
    """Write ``intention.jsonl`` (§9.1), one row per line, ordered by
    ``intention_id`` for a stable, ``git diff``-able file."""
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    ordered = sorted(rows, key=lambda r: r.intention_id)
    with p.open("w", encoding="utf-8") as f:
        for r in ordered:
            f.write(r.model_dump_json() + "\n")


def read_intention_jsonl(path: str | Path) -> list[IntentionRow]:
    p = Path(path).expanduser().resolve()
    out: list[IntentionRow] = []
    if not p.exists():
        return out
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(IntentionRow.model_validate_json(line))
    return out


def intention_load_summary(load_df: pl.DataFrame) -> dict[str, float]:
    """The card-header aggregate (§5.4): fractions of elements per load class."""
    if load_df.height == 0:
        return {"structure_clear": 0.0, "intention_critical": 0.0, "ambiguous": 0.0}
    counts = Counter(load_df["load_class"].to_list())
    total = sum(counts.values())
    return {
        "structure_clear": round(counts.get("structure-clear", 0) / total, 4),
        "intention_critical": round(counts.get("intention-critical", 0) / total, 4),
        "ambiguous": round(counts.get("ambiguous", 0) / total, 4),
    }


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_ADJUDICATION_MODEL",
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_TEMPERATURE",
    "IntentTriple",
    "GlossaryTerm",
    "BehavioralScenario",
    "AgreementRecord",
    "ConflictRecord",
    "IntentionRow",
    "ElementIntentOut",
    "ScenarioDistillOut",
    "AdjudicationOut",
    "SynthStats",
    "evidence_digest",
    "intention_id",
    "render_intent_prompt",
    "render_scenario_prompt",
    "render_adjudication_prompt",
    "synthesize_intention",
    "write_intention_jsonl",
    "read_intention_jsonl",
    "intention_load_summary",
]
