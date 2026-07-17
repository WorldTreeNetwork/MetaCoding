"""Port-brief renderer — Stage T5c (ct-intention-extraction.md §4).

The **re-implementation payload**: the subsystem card (:mod:`ctkr.cards`) rendered
*for a builder*, with shape and intention fused. A port brief is a **view** over the
decomposition document set (decomposition-schema.md §10) — derived, regenerable,
never hand-edited — that a language model (or human) reads to re-implement one
subsystem in a different stack.

Three lanes, three epistemic labels, on every element block (§4.1 fusion rule):

* **SHAPE** — machine-derived structural facts (roles, arities, laws, edge kinds,
  cardinalities, flow directions). Deterministic; the port-verifier checks these.
* **INTENT** — the T5b-synthesized purpose statement (:mod:`ctkr.intention_synth`),
  distilled from the harvest; LM prose, *not* verifier-checkable; every sentence
  cites ``intention_signals`` rows.
* **EVIDENCE** — verbatim quotes/slices (test names, error strings, docstrings),
  budget-ranked (§4.4) into the raw-evidence appendix.

The builder must always be able to tell which claims are *checked* (SHAPE), which
are *read* (INTENT), and which are *raw* (EVIDENCE) — fuse the presentation, keep
the attribution separate.

Structure (§4.2): **orientation → vocabulary → contract → internals → behavior →
warnings → raw appendix.** Distilled first, raw last.

Two pieces of machinery:

1. **Evidence budget allocator** (§4.4): raw-evidence budget is allocated
   *proportional to intention load, not element size* — ``structure-clear`` elements
   get ~0 raw evidence (the shape suffices), ``intention-critical`` the maximum,
   ``ambiguous`` everything we have plus a human-review flag. :func:`allocate_evidence_budget`.
2. **Brief fusion** (§8): one *strong-model* call per subsystem that writes the
   distilled cross-element narrative — the reading-orientation, the consolidated
   domain glossary (dedup across elements; drop idiom-only terms, restate
   convention-encoded ones), and the ordered warnings. Deterministic: the prompt is
   rendered from a canonical **structured-evidence digest**, so the LLM cache key is
   ``(digest, prompt_version, model)`` — unchanged inputs re-run free and
   byte-identical. :func:`fuse_brief`.

**Brief digest** (§8, §9.1): ``blake3`` over the card's ``card_id`` + the fusion
evidence digest + the budget config + ``prompt_version`` + ``fusion_model`` — a pure
function of the backing rows and the render config, independent of the LLM output
text and any timestamp. Recorded in ``port_briefs/manifest.json`` and embedded in
the brief header. Regenerating from identical inputs reproduces the same digest (the
T5 re-run-identity contract, extended to the brief).
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import blake3
import polars as pl
from pydantic import BaseModel, Field, field_validator

from ctkr.cards import (
    CompositionRuleCard,
    DataShapeCard,
    ElementIntention,
    InterfaceExportCard,
    RoleCard,
    SubsystemCard,
)
from ctkr.intention_synth import BehavioralScenario, GlossaryTerm, IntentTriple
from ctkr.llm import LLMClient

logger = logging.getLogger("ctkr.port_brief")

DEFAULT_PROMPT_VERSION = "port-brief:v1"
# The brief fusion is "the highest-judgment artifact in the pipeline" (§8) — a
# strong (sonnet/opus-class) model, one call per subsystem.
DEFAULT_FUSION_MODEL = "claude-sonnet-4-6"
DEFAULT_TEMPERATURE = 0.0

# Marker vocabulary for declared-debt (A6) surfacing (§4.2 item 8d, §7.1 point 3).
_DEBT_MARKER_RE = re.compile(r"\b(TODO|FIXME|HACK|XXX|SAFETY|PERF|BUG)\b", re.IGNORECASE)

# The glossary is built from these vocabulary-bearing indicator kinds (§4.2 item 2).
_VOCAB_INDICATORS = {"S2", "A3", "A4", "A5"}

# Tier rank for deterministic evidence ordering (S strongest → C weakest, §1).
_TIER_RANK = {"S": 0, "A": 1, "B": 2, "C": 3}

_PORTABILITY_LABEL = {"I": "universal", "N": "convention", "A": "idiom"}


# ───────────────────────── config (dials, §4.3 / §4.4) ─────────────────────────


@dataclass(frozen=True)
class BudgetConfig:
    """Evidence-budget dials (§4.3, §4.4). Every value is a dial, not a truth.

    ``distilled_tokens_per_element`` — the §4.3 "few hundred tokens per element"
    target for the distilled sections 1–7. ``appendix_multiple`` — the appendix's
    per-brief budget as a multiple of the distilled budget (§4.3 default 6×). The
    ``*_weight`` dials are the §4.4 load-proportional allocation: structure-clear
    near-zero, intention-critical/ambiguous maximum. ``ambiguous_uncapped`` gives
    ambiguous elements *everything we have* regardless of budget (§4.4 "everything
    plus the human flag"). ``chars_per_token`` is the cheap token estimator.
    """

    distilled_tokens_per_element: int = 300
    appendix_multiple: float = 6.0
    weight_structure_clear: float = 0.0
    weight_intention_critical: float = 1.0
    weight_ambiguous: float = 1.0
    weight_unclassified: float = 0.3
    ambiguous_uncapped: bool = True
    chars_per_token: int = 4
    # A per-element hard ceiling so one giant element can't eat the whole appendix.
    max_signals_per_element: int = 40

    def weight_for(self, load_class: str | None) -> float:
        return {
            "structure-clear": self.weight_structure_clear,
            "intention-critical": self.weight_intention_critical,
            "ambiguous": self.weight_ambiguous,
        }.get(load_class or "", self.weight_unclassified)


@dataclass(frozen=True)
class PortBriefConfig:
    """Top-level render config."""

    budget: BudgetConfig = field(default_factory=BudgetConfig)
    fusion_model: str = DEFAULT_FUSION_MODEL
    temperature: float = DEFAULT_TEMPERATURE
    prompt_version: str = DEFAULT_PROMPT_VERSION
    max_tokens: int = 2000

    def canonical(self) -> str:
        """Canonical JSON of every dial that affects the rendered brief — folded
        into the brief digest so a config change invalidates precisely."""
        b = self.budget
        return json.dumps(
            {
                "distilled_tokens_per_element": b.distilled_tokens_per_element,
                "appendix_multiple": b.appendix_multiple,
                "weights": [
                    b.weight_structure_clear,
                    b.weight_intention_critical,
                    b.weight_ambiguous,
                    b.weight_unclassified,
                ],
                "ambiguous_uncapped": b.ambiguous_uncapped,
                "chars_per_token": b.chars_per_token,
                "max_signals_per_element": b.max_signals_per_element,
                "fusion_model": self.fusion_model,
                "temperature": self.temperature,
                "prompt_version": self.prompt_version,
            },
            sort_keys=True,
            separators=(",", ":"),
        )


# ───────────────────────── raw evidence (from intention_signals.parquet) ─────────────────────────


@dataclass(frozen=True)
class RawSignal:
    """One harvested ``intention_signals`` row, ready to materialize in the appendix."""

    signal_id: str
    indicator_kind: str
    tier: str
    content: str
    file: str
    line_range: str
    portability_tier: str

    def est_tokens(self, chars_per_token: int) -> int:
        # content + a fixed per-line overhead (the ``[tier/kind] … (file:line)`` frame).
        return max(1, (len(self.content) + 40) // max(1, chars_per_token))


def _signals_by_element(signals_df: pl.DataFrame) -> dict[str, list[RawSignal]]:
    """Group harvested signals by ``element_id``, each list deterministically ordered
    (tier S→C, then indicator_kind, content, file, line) — the same total order T5b
    uses, so tags/citations line up across the two stages."""
    by: dict[str, list[RawSignal]] = {}
    for r in signals_df.iter_rows(named=True):
        by.setdefault(r["element_id"], []).append(
            RawSignal(
                signal_id=r["signal_id"],
                indicator_kind=r["indicator_kind"],
                tier=r["tier"],
                content=r["content"],
                file=r["file"] or "",
                line_range=str(r["line_range"]) if r["line_range"] is not None else "",
                portability_tier=r["portability_tier"] or "I",
            )
        )
    for eid in by:
        by[eid].sort(
            key=lambda s: (
                _TIER_RANK.get(s.tier, 9), s.indicator_kind, s.content, s.file, s.line_range
            )
        )
    return by


# ───────────────────────── evidence budget allocator (§4.4) ─────────────────────────


@dataclass
class ElementAllocation:
    """The appendix allocation for one element."""

    element_id: str
    load_class: str | None
    weight: float
    token_budget: int
    chosen: list[RawSignal]
    n_available: int
    human_flag: bool = False

    @property
    def n_elided(self) -> int:
        return max(0, self.n_available - len(self.chosen))


@dataclass
class BudgetReport:
    """The whole-brief allocation outcome (deterministic; auditable)."""

    total_distilled_budget: int
    appendix_budget: int
    allocations: dict[str, ElementAllocation]
    n_elements: int
    n_signals_materialized: int
    n_signals_elided: int


def allocate_evidence_budget(
    element_ids: Sequence[str],
    load_by_element: dict[str, str | None],
    signals_by_element: dict[str, list[RawSignal]],
    cfg: BudgetConfig,
) -> BudgetReport:
    """Allocate the raw-evidence appendix budget across elements *by intention load*
    (§4.4), not by element size — the budget-level expression of the §5 indicator.

    - ``ambiguous`` elements are allocated **all** their signals (``ambiguous_uncapped``)
      and carry a ``human_flag``: even intention is unclear, so hand the reader
      everything and tell them to consult a human.
    - ``structure-clear`` elements get **near-zero** raw evidence (weight 0 by
      default): the shape suffices and the verifier will check it.
    - the remaining ``appendix_budget`` is split among the rest **proportional to
      load weight**; within an element, signals are taken in tier order (S→C) until
      the element's token budget is spent.

    Deterministic: a pure function of the element list, their load classes, their
    (already tier-ordered) signals, and the dials.
    """
    ordered_ids = sorted(element_ids)
    n = len(ordered_ids)
    total_distilled = n * cfg.distilled_tokens_per_element
    appendix_budget = int(round(cfg.appendix_multiple * total_distilled))

    allocations: dict[str, ElementAllocation] = {}

    # Pass 1 — ambiguous elements take all their signals up-front (off-budget: the
    # human-review flag means we never want to hide evidence from them).
    remaining = appendix_budget
    weighted: list[str] = []
    for eid in ordered_ids:
        lc = load_by_element.get(eid)
        avail = signals_by_element.get(eid, [])[: cfg.max_signals_per_element]
        if lc == "ambiguous" and cfg.ambiguous_uncapped:
            spend = sum(s.est_tokens(cfg.chars_per_token) for s in avail)
            allocations[eid] = ElementAllocation(
                element_id=eid,
                load_class=lc,
                weight=cfg.weight_for(lc),
                token_budget=spend,
                chosen=list(avail),
                n_available=len(signals_by_element.get(eid, [])),
                human_flag=True,
            )
            remaining -= spend
        else:
            weighted.append(eid)
    remaining = max(0, remaining)

    # Pass 2 — distribute the remaining budget over the weighted elements.
    total_weight = sum(cfg.weight_for(load_by_element.get(eid)) for eid in weighted)
    for eid in weighted:
        lc = load_by_element.get(eid)
        w = cfg.weight_for(lc)
        avail = signals_by_element.get(eid, [])[: cfg.max_signals_per_element]
        n_avail_full = len(signals_by_element.get(eid, []))
        if w <= 0.0 or total_weight <= 0.0:
            allocations[eid] = ElementAllocation(
                element_id=eid, load_class=lc, weight=w, token_budget=0,
                chosen=[], n_available=n_avail_full,
            )
            continue
        elem_budget = int(round(remaining * (w / total_weight)))
        chosen: list[RawSignal] = []
        spent = 0
        for s in avail:  # already tier-ordered S→C
            cost = s.est_tokens(cfg.chars_per_token)
            if chosen and spent + cost > elem_budget:
                break
            chosen.append(s)
            spent += cost
        allocations[eid] = ElementAllocation(
            element_id=eid, load_class=lc, weight=w, token_budget=elem_budget,
            chosen=chosen, n_available=n_avail_full,
        )

    mat = sum(len(a.chosen) for a in allocations.values())
    eli = sum(a.n_elided for a in allocations.values())
    return BudgetReport(
        total_distilled_budget=total_distilled,
        appendix_budget=appendix_budget,
        allocations=allocations,
        n_elements=n,
        n_signals_materialized=mat,
        n_signals_elided=eli,
    )


# ───────────────────────── brief fusion (strong model, §8) ─────────────────────────
#
# One structured call per subsystem writing the distilled cross-element narrative.
# The LLM owns ONLY these schemas; everything else in the brief is rendered
# deterministically from the card + signals.


class _FusedGlossaryTerm(BaseModel):
    term: str = Field(description="A domain-vocabulary term (canonical spelling).")
    meaning: str = Field(description="One line: what the term means in this domain.")
    portability: Literal["universal", "convention", "idiom"] = Field(
        default="universal",
        description="universal = a domain term that survives any stack; convention = "
        "stack-idiomatic, RESTATE the meaning not the affix; idiom = source-stack-only "
        "(DROP it — do not include idiom terms in the glossary).",
    )


class _FusedWarning(BaseModel):
    severity: Literal["port-critical", "intention-critical", "ambiguous", "declared-debt"] = Field(
        description="port-critical = a name/doc contradicts a structural fact; "
        "intention-critical = shape underdetermines, the names/tests ARE the spec; "
        "ambiguous = even intention is thin, flag for human; declared-debt = a "
        "TODO/HACK/FIXME the port may resolve but must decide about."
    )
    element: str = Field(default="", description="The element this warning is about.")
    message: str = Field(description="What the reader must not trust / must decide.")
    instruction: str = Field(
        default="", description="The concrete builder instruction (e.g. 'trust structure "
        "for what happens, the name for what was meant')."
    )


class BriefFusionOut(BaseModel):
    """The strong model's per-subsystem distilled narrative (§4.2 items 1, 2, 8)."""

    orientation: str = Field(
        description="1-3 sentences telling the builder HOW to read this brief, keyed to "
        "the intention-load mix: which sections are 'implement the shape' vs 'read the "
        "evidence'."
    )
    glossary: list[_FusedGlossaryTerm] = Field(
        default_factory=list,
        description="The consolidated domain glossary — dedup terms across elements, "
        "restate convention terms, DROP idiom-only terms. The language to think in.",
    )
    warnings: list[_FusedWarning] = Field(
        default_factory=list,
        description="Ordered warnings: port-critical conflicts first, then "
        "intention-critical, then ambiguous, then declared debt.",
    )

    @field_validator("glossary", "warnings", mode="before")
    @classmethod
    def _lists(cls, v: object) -> list:
        if v is None:
            return []
        if isinstance(v, dict):
            return [v]
        if isinstance(v, str):
            try:
                parsed = json.loads(v)
            except (json.JSONDecodeError, ValueError):
                return []
            return parsed if isinstance(parsed, list) else [parsed]
        return v if isinstance(v, list) else []


_SYS_FUSE = (
    "You are the strong-model fuser for a cross-stack re-implementation brief. A "
    "name-blind structural pass fixed each element's identity/extent; a mechanical "
    "harvest + a cheap synthesis pass produced per-element intent, glossary terms, "
    "and structure-vs-intention verdicts. Your job is the SUBSYSTEM-level narrative: "
    "(1) an orientation that tells the builder how to read the brief given its load "
    "mix; (2) a CONSOLIDATED domain glossary — merge duplicate terms, restate "
    "convention-encoded ones in stack-agnostic language, and DROP source-idiom terms; "
    "(3) ordered warnings (port-critical conflicts first, then intention-critical, "
    "then ambiguous, then declared debt). Be concise and stack-agnostic. State what "
    "things are FOR, never how the source stack builds them."
)


def _fusion_evidence(card: SubsystemCard, signals_by_element: dict[str, list[RawSignal]]) -> dict:
    """Canonical structured evidence for the fusion call — a pure function of the
    card's synthesized intention + the harvested debt markers. Drives both the prompt
    and the cache key (§8)."""
    elements = []
    for ei in sorted(card.intention, key=lambda e: e.element_id):
        elements.append(
            {
                "element_id": ei.element_id,
                "kind": ei.element_kind,
                "load_class": ei.load_class,
                "intent": [[t.statement, t.portability_tier] for t in ei.intent],
                "glossary": [[g.term, g.meaning] for g in ei.glossary],
                "agreement": ei.agreement.verdict if ei.agreement else None,
                "conflicts": sorted(
                    [[c.claim, c.structural_fact, c.severity] for c in ei.conflicts]
                ),
            }
        )
    debt = sorted(
        {
            s.content
            for sigs in signals_by_element.values()
            for s in sigs
            if s.indicator_kind == "A6" and _DEBT_MARKER_RE.search(s.content)
        }
    )
    return {
        "subsystem_id": card.subsystem_id,
        "name": card.name,
        "intent": card.intent,
        "load_summary": card.intention_load_summary,
        "elements": elements,
        "declared_debt": debt,
    }


def fusion_digest(evidence: dict, cfg: PortBriefConfig) -> str:
    canon = json.dumps(evidence, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return blake3.blake3((canon + "|" + cfg.canonical()).encode("utf-8")).hexdigest()


def render_fusion_prompt(evidence: dict) -> str:
    lines = [
        f"# Subsystem `{evidence['subsystem_id']}` — {evidence['name']}",
        "",
        f"Purpose (from the card): {evidence['intent']}",
        f"Intention-load mix: {evidence['load_summary']}",
        "",
        "## Per-element synthesized intention + glossary",
    ]
    for e in evidence["elements"]:
        lines.append(f"- [{e['kind']} / load={e['load_class']}] {e['element_id']}")
        for stmt, port in e["intent"]:
            lines.append(f"    intent ({port}): {stmt}")
        for term, meaning in e["glossary"]:
            lines.append(f"    term: {term} — {meaning}")
        if e["agreement"]:
            lines.append(f"    agreement: {e['agreement']}")
        for claim, fact, sev in e["conflicts"]:
            lines.append(f"    conflict[{sev}]: name/doc says {claim!r} vs structure {fact!r}")
    if evidence["declared_debt"]:
        lines += ["", "## Declared debt (TODO/HACK/FIXME markers harvested)"]
        lines += [f"- {d}" for d in evidence["declared_debt"]]
    lines += [
        "",
        "Emit a BriefFusionOut: orientation + consolidated glossary + ordered warnings.",
    ]
    return "\n".join(lines)


def fuse_brief(
    card: SubsystemCard,
    signals_by_element: dict[str, list[RawSignal]],
    client: LLMClient,
    cfg: PortBriefConfig,
) -> tuple[BriefFusionOut, str, float, bool]:
    """Run the one-per-subsystem strong-model fusion. Returns
    ``(output, fusion_digest, cost_usd, cache_hit)``. Degrades to an empty
    ``BriefFusionOut`` (never aborts) on a provider/validation failure."""
    evidence = _fusion_evidence(card, signals_by_element)
    digest = fusion_digest(evidence, cfg)
    prompt = render_fusion_prompt(evidence)
    try:
        res = client.complete_structured(
            prompt,
            schema=BriefFusionOut,
            model=cfg.fusion_model,
            temperature=cfg.temperature,
            max_tokens=cfg.max_tokens,
            system=_SYS_FUSE,
        )
        return res.parsed, digest, res.cost_estimate_usd, res.cache_hit
    except Exception as e:  # noqa: BLE001 — provider/validation errors vary
        logger.warning("brief fusion failed for %s: %s", card.subsystem_id, e)
        return BriefFusionOut(orientation=""), digest, 0.0, False


# ───────────────────────── brief digest + filename ─────────────────────────


def brief_digest(card: SubsystemCard, fusion_dig: str, cfg: PortBriefConfig) -> str:
    """The regenerable brief digest (§8, §9.1): blake3 over the card id, the fusion
    evidence digest, and the render config. Independent of LLM output text and any
    timestamp — identical inputs reproduce it."""
    canon = json.dumps(
        [card.card_id, fusion_dig, cfg.canonical()], sort_keys=True, separators=(",", ":")
    ).encode("utf-8")
    return "brief:" + blake3.blake3(canon).hexdigest()[:24]


def brief_filename(subsystem_id: str) -> str:
    """Filesystem-safe ``<subsystem>.md`` name. Subsystem ids carry ``:`` / ``/``;
    replace anything unsafe with ``__`` (mirrors the TS ``portDecisionsPath`` helper)."""
    safe = re.sub(r"[^A-Za-z0-9._-]", "__", subsystem_id)
    return f"{safe}.md"


# ───────────────────────── markdown rendering (deterministic) ─────────────────────────


@dataclass
class BriefRenderStats:
    subsystem_id: str = ""
    brief_digest: str = ""
    fusion_digest: str = ""
    n_roles: int = 0
    n_exports: int = 0
    n_ops: int = 0
    n_shapes: int = 0
    n_scenarios: int = 0
    n_warnings: int = 0
    n_glossary_terms: int = 0
    n_signals_materialized: int = 0
    n_signals_elided: int = 0
    n_structure_clear: int = 0
    n_intention_critical: int = 0
    n_ambiguous: int = 0
    fusion_cost_usd: float = 0.0
    fusion_cache_hit: bool = False


def _epi(label: str, body: str) -> str:
    """One epistemic-attributed line of the SHAPE/INTENT/EVIDENCE triple."""
    return f"- **{label}** — {body}" if body else f"- **{label}** — _(none harvested)_"


def _intent_lines(intent: Sequence[IntentTriple], *, restate_only_i_and_n: bool = True) -> str:
    """Render INTENT statements, epistemically labeled, with citation counts. Idiom
    (``A``) statements are dropped; convention (``N``) are kept but marked 'restated'
    (§7.2 — the brief restates convention, never copies the source idiom)."""
    parts: list[str] = []
    for t in intent:
        if restate_only_i_and_n and t.portability_tier == "A":
            continue
        tag = {"I": "", "N": " _(convention — restated)_"}.get(t.portability_tier, "")
        cite = f" [cites {len(t.citations)} signal(s)]" if t.citations else ""
        parts.append(f"{t.statement}{tag}{cite}")
    return " ".join(parts)


def _evidence_lines(alloc: ElementAllocation | None) -> list[str]:
    if alloc is None or not alloc.chosen:
        if alloc and alloc.load_class == "structure-clear":
            return ["    - _(structure-clear — evidence elided by budget; implement the SHAPE)_"]
        return ["    - _(no evidence budgeted)_"]
    out: list[str] = []
    for s in alloc.chosen:
        loc = f" ({s.file}:{s.line_range})" if s.file else ""
        out.append(f"    - `{s.indicator_kind}/{s.tier}` {s.content}{loc}")
    if alloc.n_elided:
        out.append(f"    - _(+{alloc.n_elided} more signal(s) elided by budget)_")
    return out


def _fmt_scenarios(scs: Sequence[BehavioralScenario]) -> list[str]:
    out: list[str] = []
    for sc in scs:
        cite = f" _[cites {len(sc.citations)} test(s)]_" if sc.citations else ""
        out.append(f"- **{sc.behavior}**{cite}")
        out.append(f"  - given {sc.given}; when {sc.when}; then {sc.then}")
    return out


def render_brief(
    card: SubsystemCard,
    fusion: BriefFusionOut,
    budget: BudgetReport,
    signals_by_element: dict[str, list[RawSignal]],
    *,
    fusion_dig: str,
    cfg: PortBriefConfig,
    generated_at: str | None = None,
    stats: BriefRenderStats | None = None,
) -> str:
    """Render the port brief markdown per §4.2's exact section order. Deterministic
    given the card, fusion output, budget allocation, and signals."""
    st = stats or BriefRenderStats()
    st.subsystem_id = card.subsystem_id
    intent_by_el: dict[str, ElementIntention] = {e.element_id: e for e in card.intention}
    dig = brief_digest(card, fusion_dig, cfg)
    st.brief_digest = dig
    st.fusion_digest = fusion_dig

    L: list[str] = []

    # ── 1. Header (§4.2 item 1) ──
    L.append(f"# Port brief — {card.name}")
    L.append("")
    L.append(
        f"<!-- brief_digest={dig} card_id={card.card_id} "
        f"prompt_version={cfg.prompt_version} fusion_model={cfg.fusion_model} -->"
    )
    L.append(
        f"> Derived, regenerable view over the decomposition document set "
        f"(subsystem `{card.subsystem_id}`, repo `{card.repo}`). "
        f"Not hand-edited. Every block is labeled **SHAPE** (checked structure), "
        f"**INTENT** (read from names/tests — cites evidence), or **EVIDENCE** (raw)."
    )
    L.append("")
    if fusion.orientation:
        L.append(f"**How to read this brief.** {fusion.orientation}")
        L.append("")
    L.append(f"**Purpose.** {card.intent}")
    if card.responsibilities:
        L.append("")
        L.append("**Responsibilities.**")
        L += [f"- {r}" for r in card.responsibilities]
    if card.non_goals:
        L.append("")
        L.append("**Non-goals.**")
        L += [f"- {r}" for r in card.non_goals]
    L.append("")
    sb = card.spec_basis_summary
    L.append(
        f"**Spec basis.** {sb.structural:.0%} structural / {sb.nl_only:.0%} nl-only. "
    )
    if card.intention_load_summary:
        ils = card.intention_load_summary
        st.n_structure_clear = round(ils.get("structure_clear", 0) * len(card.intention))
        L.append(
            f"**Intention load.** structure-clear {ils.get('structure_clear', 0):.0%} · "
            f"intention-critical {ils.get('intention_critical', 0):.0%} · "
            f"ambiguous {ils.get('ambiguous', 0):.0%} — "
            f"structure-clear elements: implement the SHAPE; intention-critical: the "
            f"names/tests ARE the spec, read the EVIDENCE; ambiguous: flagged for review."
        )
    L.append("")

    # ── 2. Domain glossary (§4.2 item 2) — from the fusion (consolidated) ──
    L.append("## Domain glossary")
    L.append("")
    glossary = fusion.glossary or _fallback_glossary(card)
    st.n_glossary_terms = len(glossary)
    if glossary:
        for g in glossary:
            port = getattr(g, "portability", None)
            if port == "idiom":
                continue  # idiom terms never enter the brief (§7.2)
            suffix = " _(convention — restated)_" if port == "convention" else ""
            L.append(f"- **{g.term}** — {g.meaning}{suffix}")
    else:
        L.append("_(no domain vocabulary harvested for this subsystem)_")
    L.append("")

    # ── 3. Interface contract (§4.2 item 3) ──
    L.append("## Interface contract")
    L.append("")
    exports = card.interface.provides
    st.n_exports = len(exports)
    if not exports:
        L.append("_(no exported symbols cross this subsystem's boundary)_")
        L.append("")
    for e in exports:
        L += _render_export(e, intent_by_el.get(e.symbol_id), budget.allocations.get(e.symbol_id))
    # consumes — a short dependency list (SHAPE only).
    if card.interface.consumes:
        L.append("### Dependencies (consumes)")
        for c in card.interface.consumes:
            tgt = c.target_subsystem or "external"
            L.append(f"- `{c.target}` ({tgt}) via {', '.join(c.edge_kinds)} — {c.purpose}")
        L.append("")

    # ── 4. Roles (§4.2 item 4) ──
    L.append("## Roles")
    L.append("")
    st.n_roles = len(card.roles)
    if not card.roles:
        L.append("_(no role classes recovered)_")
        L.append("")
    for r in card.roles:
        L += _render_role(r, intent_by_el.get(r.role_id), budget.allocations.get(r.role_id))

    # ── 5. Composition laws & protocol (§4.2 item 5) ──
    L.append("## Composition laws & protocol")
    L.append("")
    st.n_ops = len(card.composition_rules)
    if not card.composition_rules:
        L.append("_(no composition operations recovered)_")
        L.append("")
    for op in card.composition_rules:
        L += _render_op(op)

    # ── 6. Data shapes (§4.2 item 6) ──
    L.append("## Data shapes")
    L.append("")
    st.n_shapes = len(card.data_shapes)
    if not card.data_shapes:
        L.append("_(no boundary data shapes recovered)_")
        L.append("")
    for s in card.data_shapes:
        L += _render_shape(
            s, intent_by_el.get(s.type_symbol_id), budget.allocations.get(s.type_symbol_id)
        )

    # ── 7. Behavioral spec (§4.2 item 7) — the port's acceptance list ──
    L.append("## Behavioral spec (acceptance list)")
    L.append("")
    L.append(
        "_The port's new test suite must cover these. Distilled from the original "
        "tests (S1); each scenario cites its source test._"
    )
    L.append("")
    any_scen = False
    for ei in sorted(card.intention, key=lambda e: e.element_id):
        if ei.behavioral_scenarios:
            any_scen = True
            st.n_scenarios += len(ei.behavioral_scenarios)
            L.append(f"### `{ei.element_id}` ({ei.element_kind})")
            L += _fmt_scenarios(ei.behavioral_scenarios)
            L.append("")
    if not any_scen:
        L.append(
            "_(no behavioral scenarios distilled — the harvest linked no tests to "
            "this subsystem's elements)_"
        )
        L.append("")

    # ── 8. Warnings (§4.2 item 8) — ordered ──
    L.append("## Warnings")
    L.append("")
    warnings = fusion.warnings
    st.n_warnings = len(warnings)
    order = {"port-critical": 0, "intention-critical": 1, "ambiguous": 2, "declared-debt": 3}
    icon = {
        "port-critical": "⚠ **port-critical**",
        "intention-critical": "● intention-critical",
        "ambiguous": "? ambiguous",
        "declared-debt": "✎ declared-debt",
    }
    fused_ok = bool(warnings)
    if not fused_ok:
        warnings = _fallback_warnings(card, signals_by_element)
        st.n_warnings = len(warnings)
    if not warnings:
        L.append("_(no warnings — no conflicts, all elements structure-clear, no declared debt)_")
        L.append("")
    for w in sorted(warnings, key=lambda w: (order.get(_sev(w), 9), _elem(w))):
        head = icon.get(_sev(w), _sev(w))
        el = _elem(w)
        elpart = f" `{el}`" if el else ""
        L.append(f"- {head}{elpart} — {_msg(w)}")
        instr = _instr(w)
        if instr:
            L.append(f"  - _{instr}_")
    L.append("")

    # ── 9. Appendix: raw evidence (§4.2 item 9) ──
    L.append("## Appendix — raw evidence")
    L.append("")
    L.append(
        f"_Budget: {budget.appendix_budget} tokens (≈{cfg.budget.appendix_multiple:g}× the "
        f"{budget.total_distilled_budget}-token distilled budget), allocated by intention "
        f"load — structure-clear ≈0, intention-critical/ambiguous maximal. "
        f"{budget.n_signals_materialized} signal(s) materialized, "
        f"{budget.n_signals_elided} elided._"
    )
    L.append("")
    st.n_signals_materialized = budget.n_signals_materialized
    st.n_signals_elided = budget.n_signals_elided
    any_ev = False
    for eid in sorted(budget.allocations):
        alloc = budget.allocations[eid]
        if not alloc.chosen:
            continue
        any_ev = True
        flag = " — **human review flagged** (ambiguous)" if alloc.human_flag else ""
        L.append(f"### `{eid}` ({alloc.load_class or 'unclassified'}){flag}")
        for s in alloc.chosen:
            loc = f" ({s.file}:{s.line_range})" if s.file else ""
            L.append(f"- `{s.indicator_kind}/{s.tier}` [{s.portability_tier}] {s.content}{loc}")
        if alloc.n_elided:
            L.append(f"- _(+{alloc.n_elided} more elided by budget)_")
        L.append("")
    if not any_ev:
        L.append("_(no raw evidence materialized — all elements structure-clear or unbudgeted)_")
        L.append("")

    L.append("---")
    gen = generated_at or datetime.now(tz=UTC).isoformat()
    L.append(f"_Brief digest `{dig}` · generated {gen}_")
    L.append("")
    return "\n".join(L)


# ---- per-element block renderers ----


def _render_export(
    e: InterfaceExportCard, ei: ElementIntention | None, alloc: ElementAllocation | None
) -> list[str]:
    L = [f"### `{e.symbol}`"]
    load = f" · load: {ei.load_class}" if ei and ei.load_class else ""
    L.append(
        _epi(
            "SHAPE",
            f"usage modes {', '.join(e.usage_modes) or '—'}; "
            f"{e.n_external_callers} external caller(s){load}",
        )
    )
    intent = _intent_lines(ei.intent) if ei else ""
    L.append(_epi("INTENT", intent or e.contract))
    L.append(_epi("EVIDENCE", ""))
    L += _evidence_lines(alloc)
    L.append("")
    return L


def _render_role(
    r: RoleCard, ei: ElementIntention | None, alloc: ElementAllocation | None
) -> list[str]:
    L = [f"### {r.label} _(role)_"]
    load = f" · load: {ei.load_class}" if ei and ei.load_class else ""
    L.append(
        _epi(
            "SHAPE",
            f"cardinality {r.cardinality}; invariance tier {r.invariance_tier}; "
            f"profile depth {r.profile_depth}; "
            f"interface participation: {', '.join(r.interface_participation) or 'none'}{load}",
        )
    )
    intent = _intent_lines(ei.intent) if ei else ""
    L.append(_epi("INTENT", intent or r.description))
    if r.intent_dissonance:
        L.append(f"  - ⚠ dissonance ({r.intent_dissonance.kind}): {r.intent_dissonance.evidence}")
    L.append(_epi("EVIDENCE", ""))
    L += _evidence_lines(alloc)
    L.append("")
    return L


def _render_op(op: CompositionRuleCard) -> list[str]:
    law = op.law_notes or {}
    law_txt = (
        f"associative={law.get('associative_observed')}; "
        f"violations={law.get('violations', 0)}"
    )
    proto = " **[boundary protocol op]**" if op.is_boundary_op else ""
    L = [f"### {op.label}{proto}"]
    L.append(
        _epi(
            "SHAPE",
            f"{op.op_kind}, arity {op.arity}; roles {', '.join(op.input_roles)} → "
            f"{op.output_role}; edges {', '.join(op.edge_kinds)}; support {op.support}; "
            f"laws: {law_txt}; invariance tier {op.invariance_tier}",
        )
    )
    L.append(_epi("INTENT", op.description))
    L.append("")
    return L


def _render_shape(
    s: DataShapeCard, ei: ElementIntention | None, alloc: ElementAllocation | None
) -> list[str]:
    L = [f"### `{s.type}`" + (" _(boundary)_" if s.boundary else "")]
    L.append(_epi("SHAPE", f"invariance tier {s.invariance_tier}; {s.alphabet_coverage_note}"))
    intent = _intent_lines(ei.intent) if ei else ""
    L.append(_epi("INTENT", intent or s.meaning))
    if s.fields:
        L.append("  - fields (SHAPE type/flow · INTENT meaning):")
        for f_ in s.fields:
            L.append(f"    - `{f_.name or '?'}`: {f_.type or '?'} [{f_.flow}]")
    L.append(_epi("EVIDENCE", ""))
    L += _evidence_lines(alloc)
    L.append("")
    return L


# ---- fallbacks (deterministic; used when the fusion call is empty/offline) ----


def _fallback_glossary(card: SubsystemCard) -> list[GlossaryTerm]:
    """Dedup per-element glossary terms when the fusion produced none — keeps the
    brief self-contained on the offline/degraded path."""
    seen: dict[str, GlossaryTerm] = {}
    for ei in card.intention:
        for g in ei.glossary:
            key = g.term.strip().lower()
            if key and key not in seen:
                seen[key] = g
    return [seen[k] for k in sorted(seen)]


def _fallback_warnings(
    card: SubsystemCard, signals_by_element: dict[str, list[RawSignal]]
) -> list[_FusedWarning]:
    """Deterministic warnings from the card's own fields when fusion is empty:
    conflicts, intention-critical/ambiguous elements, declared debt (§4.2 item 8)."""
    out: list[_FusedWarning] = []
    for ei in card.intention:
        for c in ei.conflicts:
            out.append(
                _FusedWarning(
                    severity="port-critical",
                    element=ei.element_id,
                    message=f"name/doc claims {c.claim!r} but structure shows "
                    f"{c.structural_fact!r}",
                    instruction="trust structure for what happens, the name for what was meant",
                )
            )
        if ei.load_class == "intention-critical":
            out.append(
                _FusedWarning(
                    severity="intention-critical",
                    element=ei.element_id,
                    message="shape underdetermines this element; the names/tests are the spec",
                    instruction="read the EVIDENCE; do not reconstruct from the algorithm's shape",
                )
            )
        elif ei.load_class == "ambiguous":
            out.append(
                _FusedWarning(
                    severity="ambiguous",
                    element=ei.element_id,
                    message="structure and intention are both thin; consult a human "
                    "or the original authors",
                )
            )
    debt = sorted(
        {
            s.content
            for sigs in signals_by_element.values()
            for s in sigs
            if s.indicator_kind == "A6" and _DEBT_MARKER_RE.search(s.content)
        }
    )
    for d in debt:
        out.append(
            _FusedWarning(
                severity="declared-debt",
                message=d,
                instruction="the port may resolve this, but each is a conscious decision",
            )
        )
    return out


# _FusedWarning-or-dict accessors (fusion output vs. fallback both flow through here).
def _sev(w: object) -> str:
    return w.severity if isinstance(w, _FusedWarning) else str(w.get("severity", ""))  # type: ignore[union-attr]


def _elem(w: object) -> str:
    return w.element if isinstance(w, _FusedWarning) else str(w.get("element", ""))  # type: ignore[union-attr]


def _msg(w: object) -> str:
    return w.message if isinstance(w, _FusedWarning) else str(w.get("message", ""))  # type: ignore[union-attr]


def _instr(w: object) -> str:
    return w.instruction if isinstance(w, _FusedWarning) else str(w.get("instruction", ""))  # type: ignore[union-attr]


# ───────────────────────── orchestrator ─────────────────────────


def build_port_brief(
    card: SubsystemCard,
    signals_df: pl.DataFrame,
    client: LLMClient,
    cfg: PortBriefConfig | None = None,
    *,
    generated_at: str | None = None,
) -> tuple[str, BriefRenderStats]:
    """Build one subsystem's port brief end-to-end: fuse (one strong call), allocate
    the evidence budget, render the markdown. Returns ``(markdown, stats)``.

    ``card`` must already carry its attached intention
    (:func:`ctkr.cards.attach_intention_to_deck`). ``signals_df`` is the whole
    ``intention_signals.parquet``; only this subsystem's element signals are used.
    """
    cfg = cfg or PortBriefConfig()
    t0 = time.perf_counter()
    sigs_by = _signals_by_element(signals_df)

    element_ids = [e.element_id for e in card.intention]
    load_by = {e.element_id: e.load_class for e in card.intention}
    # restrict signals to this card's elements
    card_sigs = {eid: sigs_by.get(eid, []) for eid in element_ids}
    budget = allocate_evidence_budget(element_ids, load_by, card_sigs, cfg.budget)

    fusion, fdig, fcost, fhit = fuse_brief(card, card_sigs, client, cfg)

    stats = BriefRenderStats(fusion_cost_usd=round(fcost, 6), fusion_cache_hit=fhit)
    md = render_brief(
        card, fusion, budget, card_sigs,
        fusion_dig=fdig, cfg=cfg, generated_at=generated_at, stats=stats,
    )
    for e in card.intention:
        if e.load_class == "intention-critical":
            stats.n_intention_critical += 1
        elif e.load_class == "ambiguous":
            stats.n_ambiguous += 1
        elif e.load_class == "structure-clear":
            stats.n_structure_clear += 1
    logger.info("built brief for %s in %.2fs", card.subsystem_id, time.perf_counter() - t0)
    return md, stats


def write_brief(markdown: str, out_dir: str | Path, subsystem_id: str) -> Path:
    """Write ``port_briefs/<subsystem>.md`` and return its path."""
    d = Path(out_dir).expanduser().resolve()
    d.mkdir(parents=True, exist_ok=True)
    p = d / brief_filename(subsystem_id)
    p.write_text(markdown, encoding="utf-8")
    return p


__all__ = [
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_FUSION_MODEL",
    "DEFAULT_TEMPERATURE",
    "BudgetConfig",
    "PortBriefConfig",
    "RawSignal",
    "ElementAllocation",
    "BudgetReport",
    "allocate_evidence_budget",
    "BriefFusionOut",
    "fuse_brief",
    "fusion_digest",
    "render_fusion_prompt",
    "brief_digest",
    "brief_filename",
    "render_brief",
    "build_port_brief",
    "write_brief",
    "BriefRenderStats",
]
