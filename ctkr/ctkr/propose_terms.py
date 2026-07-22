"""Term-proposal synthesis (bead MetaCoding-5c5) — the naming joint.

For each surviving lexicon candidate (glossary-gaps config diff + role-gaps
role-equivalence sweep) an LLM produces a full **TERM-SPEC v1** naming brief:
term name, kind, description, probe semantics, and a discriminating flow sketch
that uses ONLY existing flow-DSL vocabulary plus the proposed term itself.

Posture (same as ``propose-adapter`` / decide-for-me): the LLM **proposes,
never binds**. Provenance is carried over from the candidate programmatically —
the model cannot author it — and ``first_pack_seal`` stays ``null``: every
proposal is PROVISIONAL until a real sealed recording fills the seal at the
binding gate (MetaCoding-b5r). Nothing in this module imports the glossary for
anything but READ access; a proposal never touches
:mod:`ctkr.oracle.glossary`.

TERM-SPEC v1 (the shared contract between propose-terms output and the
binding gate)::

    {"term": str, "kind": "entity"|"action"|"assertion", "description": str,
     "probe_semantics": str, "discriminating_flow": {<flow-DSL sketch>},
     "provenance": {"role_class_id": str|null, "config_source": str|null,
                    "punts": [str], "first_pack_seal": null}}
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

# READ-ONLY use of the shared instrument: the closed vocabulary a flow sketch
# is allowed to speak. This module never mutates or extends these sets.
from ctkr.oracle.glossary import ACTION_TERMS, ASSERTION_TERMS, all_terms


class SpendExceededError(RuntimeError):
    """Raised when accumulated real spend crosses the run's budget."""


# --------------------------------------------------------------------------- #
# Candidate loading + normalization                                           #
# --------------------------------------------------------------------------- #


@dataclass
class Candidate:
    """One naming candidate, normalized across the two channels.

    ``config_source`` set → surfaced by the deterministic config diff
    (glossary-gaps). ``role_class_id`` set → surfaced by the role-equivalence
    sweep (role-gaps). Both set → the same concept surfaced by BOTH channels:
    the strongest candidates, ordered first.
    """

    term_hint: str  # "" for unnamed role classes
    kind_hint: str
    description: str
    probe_hint: str
    flow_hint: dict
    punts: list[str] = field(default_factory=list)
    gap_kind: str | None = None
    config_source: str | None = None
    role_class_id: str | None = None
    member_names: list[str] = field(default_factory=list)
    features: list[str] = field(default_factory=list)
    value: Any = None  # e.g. an allowed-values list

    @property
    def channels(self) -> str:
        both = self.config_source is not None and self.role_class_id is not None
        if both:
            return "config+role"
        return "config" if self.config_source is not None else "role"


def load_candidate_rows(paths: Iterable[Path]) -> list[dict]:
    """Read raw JSONL rows from one or more --candidates files."""
    rows: list[dict] = []
    for p in paths:
        with Path(p).open(encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if line:
                    rows.append(json.loads(line))
    return rows


def normalize_rows(rows: Iterable[Mapping[str, Any]]) -> list[Candidate]:
    """Turn raw rows from either channel into :class:`Candidate` objects.

    Skips role-gaps ``summary`` records and role classes without a candidate
    (named / non-gap classes). Dedups config candidates by term (extra source
    refs recorded as punts).
    """
    out: list[Candidate] = []
    seen_config: dict[str, Candidate] = {}
    for row in rows:
        rt = row.get("record_type")
        if rt == "summary":
            continue
        cand = row.get("candidate")
        if not cand:
            continue
        prov = cand.get("provenance") or {}
        punts = list(prov.get("punts") or [])
        if rt == "role_class":
            out.append(
                Candidate(
                    term_hint=str(cand.get("term") or ""),
                    kind_hint=str(cand.get("kind") or ""),
                    description=str(cand.get("description") or ""),
                    probe_hint=str(cand.get("probe_semantics") or ""),
                    flow_hint=dict(cand.get("discriminating_flow") or {}),
                    punts=punts,
                    role_class_id=str(row.get("class_id") or prov.get("role_class_id")),
                    member_names=list(row.get("member_names") or []),
                    features=list(row.get("features") or []),
                )
            )
            continue
        # glossary-gaps config row
        term = str(cand.get("term") or "")
        src = prov.get("config_source") or row.get("source_ref")
        if term in seen_config:
            seen_config[term].punts.append(f"also surfaced by config source {src}")
            continue
        c = Candidate(
            term_hint=term,
            kind_hint=str(cand.get("kind") or ""),
            description=str(cand.get("description") or ""),
            probe_hint=str(cand.get("probe_semantics") or ""),
            flow_hint=dict(cand.get("discriminating_flow") or {}),
            punts=punts,
            gap_kind=row.get("gap_kind"),
            config_source=str(src) if src else None,
            value=row.get("value"),
        )
        seen_config[term] = c
        out.append(c)
    return out


# --------------------------------------------------------------------------- #
# Cross-channel dedup (config_source + role_class_id both present = strongest)#
# --------------------------------------------------------------------------- #


def _tokens(s: str) -> list[str]:
    """Split an identifier-ish string into lowercase tokens (camelCase and
    underscore/punctuation boundaries)."""
    s = re.sub(r"([a-z0-9])([A-Z])", r"\1 \2", s)
    return [t.lower() for t in re.split(r"[^A-Za-z0-9]+", s) if t]


def _contains_seq(hay: Sequence[str], needle: Sequence[str]) -> bool:
    n = len(needle)
    if n == 0 or n > len(hay):
        return False
    return any(list(hay[i : i + n]) == list(needle) for i in range(len(hay) - n + 1))


def merge_channels(candidates: list[Candidate]) -> list[Candidate]:
    """Dedup candidates that are the same concept surfaced by both channels.

    A role class merges into the config candidate(s) whose term tokens appear
    as a contiguous subsequence in a member name — the LONGEST such match wins
    (so ``lab_test_type`` claims a lab-test role class over the shorter ``lab``).
    A merged config candidate carries the role_class_id; the role class itself
    is not emitted separately.

    Output ordering states the strength claim: both-channel candidates first,
    then config-only, then role-only.
    """
    config = [c for c in candidates if c.config_source is not None]
    role = [c for c in candidates if c.config_source is None]

    merged_role_ids: set[str] = set()
    for rc in role:
        member_toks = [_tokens(m) for m in rc.member_names]
        best_len = 0
        matches: list[Candidate] = []
        for cc in config:
            seq = _tokens(cc.term_hint)
            if not seq:
                continue
            if any(_contains_seq(mt, seq) for mt in member_toks):
                if len(seq) > best_len:
                    best_len, matches = len(seq), [cc]
                elif len(seq) == best_len:
                    matches.append(cc)
        if matches:
            for cc in matches:
                cc.role_class_id = rc.role_class_id
                cc.member_names = rc.member_names
                cc.features = rc.features
                cc.punts.append(
                    f"also surfaced by role-equivalence class {rc.role_class_id} "
                    f"(features: {', '.join(rc.features)})"
                )
            if rc.role_class_id:
                merged_role_ids.add(rc.role_class_id)

    role_only = [r for r in role if r.role_class_id not in merged_role_ids]
    both = [c for c in config if c.role_class_id is not None]
    config_only = [c for c in config if c.role_class_id is None]
    return both + config_only + role_only


# --------------------------------------------------------------------------- #
# The structured proposal schema (what the LLM is forced to emit)             #
# --------------------------------------------------------------------------- #


class FlowSketch(BaseModel):
    """A discriminating flow sketch in the fixture flow-DSL's given/when/then
    shape (plain strings at sketch granularity, like the deterministic
    candidates')."""

    given: list[str] = Field(default_factory=list)
    when: list[str] = Field(default_factory=list)
    then: list[str] = Field(default_factory=list)


class TermProposal(BaseModel):
    """A proposed glossary term: name, kind, probe semantics and a
    discriminating flow sketch using only existing flow-DSL vocabulary plus
    the proposed term itself. A proposal NEVER binds — the binding gate
    (MetaCoding-b5r) decides."""

    term: str
    kind: Literal["entity", "action", "assertion"]
    description: str = Field(min_length=1)
    probe_semantics: str = Field(min_length=1)
    discriminating_flow: FlowSketch

    @field_validator("term")
    @classmethod
    def _term_shape(cls, v: str) -> str:
        if not re.fullmatch(r"[a-z][a-z0-9_]*", v):
            raise ValueError(
                f"term {v!r} must be snake_case: lowercase letters, digits and "
                "underscores, starting with a letter"
            )
        if v in all_terms():
            raise ValueError(
                f"term {v!r} is ALREADY a bound glossary term; propose a NEW "
                "term for the unnamed concept"
            )
        return v

    @model_validator(mode="after")
    def _flow_vocabulary(self) -> TermProposal:
        flow = self.discriminating_flow
        if not flow.then:
            raise ValueError(
                "discriminating_flow.then must state at least one delivered-"
                "value assertion — a flow that asserts nothing discriminates "
                "nothing"
            )
        allowed_actions = ACTION_TERMS | {self.term}
        for step in flow.when:
            head = (step.split() or [""])[0]
            if head not in allowed_actions:
                raise ValueError(
                    f"when step {step!r} starts with unknown action {head!r}; "
                    "each when step must start with an existing flow-DSL "
                    f"action ({', '.join(sorted(ACTION_TERMS))}) or the "
                    f"proposed term {self.term!r} itself"
                )
        allowed_assertions = ASSERTION_TERMS | {self.term}
        for step in flow.then:
            head = (step.split() or [""])[0]
            if head not in allowed_assertions:
                raise ValueError(
                    f"then step {step!r} starts with unknown assertion "
                    f"{head!r}; each then step must start with an existing "
                    "glossary assertion term or the proposed term "
                    f"{self.term!r} itself"
                )
        return self


# --------------------------------------------------------------------------- #
# Prompt construction (pure — stable LLM cache keys)                          #
# --------------------------------------------------------------------------- #

PROPOSAL_SYS = (
    "You are the naming joint of a domain-glossary pipeline for a farm "
    "management system. Deterministic channels found recurring domain concepts "
    "the glossary has no term for; you write the naming brief. You PROPOSE — "
    "you never bind: a proposal becomes a term only later, when a real sealed "
    "recording exercises it at the binding gate. Name the domain CONCEPT (the "
    "value the boundary delivers), never an implementation artifact."
)


def _vocab_block() -> str:
    return "\n".join(
        [
            "Existing flow-DSL action terms (the ONLY verbs a `when` step may "
            "start with, besides the proposed term itself):",
            "  " + ", ".join(sorted(ACTION_TERMS)),
            "Existing assertion terms (the ONLY predicates a `then` step may "
            "start with, besides the proposed term itself):",
            "  " + ", ".join(sorted(ASSERTION_TERMS)),
            "Every already-bound glossary term (the proposed term must NOT be "
            "one of these):",
            "  " + ", ".join(sorted(all_terms())),
        ]
    )


def build_term_prompt(cand: Candidate) -> str:
    """Assemble the deterministic naming prompt for one candidate. Pure
    function of the candidate + the (frozen) glossary vocabulary."""
    parts: list[str] = [
        "# Candidate domain concept needing a glossary term",
        "",
        "## Channel provenance",
        f"channels: {cand.channels}",
    ]
    if cand.config_source:
        parts += [
            f"config_source: {cand.config_source}",
            f"gap_kind: {cand.gap_kind}",
        ]
        if cand.value is not None:
            parts.append(f"declared value(s): {json.dumps(cand.value)}")
    if cand.role_class_id:
        parts.append(f"role_class_id: {cand.role_class_id}")
        if cand.features:
            parts.append(f"recurring across features: {', '.join(cand.features)}")
        if cand.member_names:
            sample = cand.member_names[:12]
            parts += ["structurally role-equivalent members (sample):"]
            parts += [f"  - {m}" for m in sample]
    parts += [
        "",
        "## Deterministic candidate (partial TERM-SPEC — refine, don't parrot)",
        f"term hint: {cand.term_hint or '(unnamed — you must name it)'}",
        f"kind hint: {cand.kind_hint or '(undecided)'}",
        f"description: {cand.description}",
        f"probe hint: {cand.probe_hint}",
        f"flow hint: {json.dumps(cand.flow_hint, sort_keys=True)}",
    ]
    if cand.punts:
        parts += ["known punts (what the deterministic channel could NOT decide):"]
        parts += [f"  - {p}" for p in cand.punts]
    parts += [
        "",
        "## Bound vocabulary",
        _vocab_block(),
        "",
        "## Task",
        "Emit ONE TermProposal JSON object:",
        "- term: a NEW snake_case domain term for this concept (not an "
        "existing glossary term; name the concept, not a PHP class or field).",
        "- kind: entity | action | assertion — where the term lives in a "
        "flow (given / when / then).",
        "- description: one or two sentences, domain vocabulary only — no "
        "storage or framework words.",
        "- probe_semantics: what a probe must DELIVER at the boundary to "
        "answer assertions about this term (a value, never a representation).",
        "- discriminating_flow: a given/when/then sketch that would pass "
        "with this concept implemented and fail without it. Each `when` step "
        "MUST start with an existing action term or the proposed term; each "
        "`then` step MUST start with an existing assertion term or the "
        "proposed term. `then` must not be empty.",
    ]
    return "\n".join(parts)


# --------------------------------------------------------------------------- #
# Spend projection + the proposal loop                                        #
# --------------------------------------------------------------------------- #


def project_spend(
    prompts: Sequence[str], model: str, *, est_output_tokens: int = 2500
) -> float:
    """Pre-flight cost projection: chars/4 input tokens per prompt plus a
    conservative output allowance (reasoning models bill thinking tokens)."""
    from ctkr.llm import _estimate_cost

    return sum(
        _estimate_cost(model, len(p) // 4, est_output_tokens) for p in prompts
    )


def proposal_row(
    cand: Candidate, prop: TermProposal, *, provider: str, model: str
) -> dict:
    """One full TERM-SPEC v1 row. Provenance is carried over from the
    candidate — the LLM never writes it — and first_pack_seal stays null
    (PROVISIONAL until a real sealed recording fills it)."""
    return {
        "term": prop.term,
        "kind": prop.kind,
        "description": prop.description,
        "probe_semantics": prop.probe_semantics,
        "discriminating_flow": prop.discriminating_flow.model_dump(),
        "provenance": {
            "role_class_id": cand.role_class_id,
            "config_source": cand.config_source,
            "punts": [
                *cand.punts,
                f"proposed by {provider}:{model} (propose-terms); PROVISIONAL "
                "until first_pack_seal is filled by a real sealed recording",
            ],
            "first_pack_seal": None,
        },
    }


def propose_all(
    candidates: Sequence[Candidate],
    client: Any,
    *,
    provider: str,
    model: str,
    reasoning_effort: str | None = None,
    max_spend: float = 3.0,
    max_tokens: int = 3000,
) -> tuple[list[dict], float]:
    """Run the naming call over every candidate (structured output, one house
    repair retry each). Returns ``(rows, total_cost_usd)``. Raises
    :class:`SpendExceededError` the moment accumulated real spend crosses
    ``max_spend``; the caller writes what it has and reports."""
    rows: list[dict] = []
    total = 0.0
    for cand in candidates:
        res = client.complete_structured(
            build_term_prompt(cand),
            schema=TermProposal,
            provider=provider,
            model=model,
            system=PROPOSAL_SYS,
            max_tokens=max_tokens,
            reasoning_effort=reasoning_effort,
            repair=True,
        )
        total += float(res.cost_estimate_usd)
        rows.append(proposal_row(cand, res.parsed, provider=provider, model=model))
        if total > max_spend:
            raise SpendExceededError(
                f"accumulated spend ${total:.4f} exceeds budget ${max_spend:.2f} "
                f"after {len(rows)}/{len(candidates)} candidates"
            )
    return rows, total


def write_proposals_jsonl(rows: Iterable[Mapping[str, Any]], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", encoding="utf-8") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")


__all__ = [
    "Candidate",
    "FlowSketch",
    "PROPOSAL_SYS",
    "SpendExceededError",
    "TermProposal",
    "build_term_prompt",
    "load_candidate_rows",
    "merge_channels",
    "normalize_rows",
    "project_spend",
    "proposal_row",
    "propose_all",
    "write_proposals_jsonl",
]
