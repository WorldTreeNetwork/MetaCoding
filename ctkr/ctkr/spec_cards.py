"""NL lane + card fusion — Stage D + Stage E (§5, §8, T5).

This is the second, name-*full* lane of the pipeline. The structural lane (T1–T4)
has already fixed, name-blind, *what the units are and where they end*: the
partition (subsystems), the boundary (interfaces + data shapes), and the
presentation (role classes + composition operads). This module reads those fixed
units and, for each, assembles an **evidence pack** (tree-sitter code slices +
docstrings/comments harvested by :mod:`ctkr.evidence`, plus FTS hits over the
member set) and runs the L3 labeler to attach *intent* — what each unit is for,
what to call it. Structure decides what to read; language decides what it means
(§5.1). The two lanes fuse only here, in the card.

Trust policy (§5.3), enforced mechanically:

- **Structure owns identity and extent.** The labeler may not move a symbol
  between subsystems, merge role classes, or invent interface members. This
  module never lets an LLM output change a member set, a role membership, a
  boundary edge, or a card's extent — those come only from the Parquet.
- **Names own intent.** Every ``label``/``description``/``contract``/``meaning``/
  ``purpose`` field is the LLM's.
- **Disagreement is first-class.** :func:`detect_role_dissonance` runs a
  name-blind structural check (do the members of a structurally-unified role
  class share *any* naming stem?) and the labeler is also asked to flag when a
  name suggests a different purpose than the shared structure. Both feed
  ``intent_dissonance`` (§5.3) — often the highest-value finding in the deck.

Determinism: ``card_id`` is structural-only (:func:`ctkr.cards.card_id`), so a
re-run over the same inputs + ``prompt_version`` + ``llm_model`` yields identical
ids regardless of the label text.

Label reproducibility (MetaCoding-hqk): every prompt this module builds is a pure
function of the structural evidence — no set-iteration order, no timestamps — so
the LLM-cache key is stable and a re-run against a warm cache reproduces the exact
labels byte-for-byte. On a *cold* cache the labels are regenerated; at
``temperature=0`` the stronger subsystem model is materially more stable than a
cheap model but is not a hard guarantee, so the deck's labels are documented as a
**regenerable view over the structural ground truth**, not an immutable artifact.
The structural Parquet + ``card_id`` are the stable spine; the labels are cached
alongside them and re-derivable.
"""

from __future__ import annotations

import json
import logging
import re
import time
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import blake3
import networkx as nx
import polars as pl
from pydantic import BaseModel, Field, field_validator

from ctkr import cards as cardmod
from ctkr.cards import (
    CompositionRuleCard,
    DataFieldCard,
    DataShapeCard,
    ExemplarSlice,
    IntentDissonance,
    InterfaceCard,
    InterfaceConsumeCard,
    InterfaceExportCard,
    NlOnlySymbol,
    Provenance,
    RoleCard,
    SpecBasisSummary,
    SubsystemCard,
    TopologyCard,
)
from ctkr.evidence import EvidencePack, InstanceEvidence, build_evidence_pack
from ctkr.llm import LLMClient
from ctkr.schema_l3 import EvidenceRow, LineRange, PatternRow

logger = logging.getLogger("ctkr.spec_cards")

DEFAULT_PROMPT_VERSION = "spec-labeler:v2"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
# The subsystem name+intent is the highest-stakes label on the deck: a single
# wrong name mislabels thousands of members (MetaCoding-hqk). It is worth a
# stronger model than the cheap per-element labels. Configurable; falls back to
# the base model when None so tests and offline runs stay on the mock/haiku path.
DEFAULT_SUBSYSTEM_MODEL = "claude-sonnet-4-6"
DEFAULT_TEMPERATURE = 0.0

# Per-subsystem caps on how many elements get an LLM label (readability + cost).
# These bound the *labeled* subset only; structural coverage (spec_basis_summary,
# nl-only listing) is always computed over the full member set, so nothing is
# lost from the deck's accounting.
DEFAULT_ROLES_PER = 6
DEFAULT_OPS_PER = 6
DEFAULT_EXPORTS_PER = 8
DEFAULT_SHAPES_PER = 6
DEFAULT_NL_DESC_PER = 5


def _coerce_str_list(v: object) -> list[str]:
    """Tolerate a model that returns a list field as a string (some Haiku
    tool_use responses emit pseudo-XML/newline text instead of a JSON array).
    Extracts ``<item>…</item>`` entries when present, else splits on newlines /
    bullets, and strips any stray tag markup. A real list passes through."""
    if v is None:
        return []
    if isinstance(v, (list, tuple)):
        return [str(x).strip() for x in v if str(x).strip()]
    if isinstance(v, str):
        items = re.findall(r"<item>(.*?)</item>", v, flags=re.DOTALL)
        if not items:
            items = re.split(r"[\n;]+", re.sub(r"<[^>]+>", "", v))
        cleaned = [re.sub(r"^[\s\-*•]+", "", s).strip() for s in items]
        return [s for s in cleaned if s]
    return [str(v).strip()]


# ----- LLM output schemas (the LLM owns *only* these fields) -----


class SubsystemLabelOut(BaseModel):
    """Name + intent for a whole subsystem (source_kind='subsystem')."""

    name: str = Field(description="Short canonical subsystem name, 2-5 words, "
                       "capturing responsibility not implementation.")
    intent: str = Field(description="One paragraph: the subsystem's purpose — "
                        "what job it does for the rest of the system.")
    responsibilities: list[str] = Field(
        default_factory=list,
        description="3-6 bullet responsibilities, each a short phrase.",
    )
    non_goals: list[str] = Field(
        default_factory=list,
        description="0-3 things this subsystem deliberately does NOT do, if evident.",
    )
    dissonance_kind: str | None = Field(
        default=None,
        description="If the subsystem's members' names collectively suggest a "
        "different purpose than the one the structure implies, name the "
        "disagreement (short slug); else null.",
    )
    dissonance_evidence: str | None = Field(
        default=None, description="Concrete evidence for the dissonance; else null."
    )

    @field_validator("responsibilities", "non_goals", mode="before")
    @classmethod
    def _coerce_list(cls, v: object) -> list[str]:
        return _coerce_str_list(v)


class RoleLabelOut(BaseModel):
    """Label + intent for one role class (source_kind='role-class')."""

    label: str = Field(description="Short canonical role name, 2-4 words, for the "
                       "structural function these symbols share (e.g. 'Command "
                       "registrar', 'Profile writer'). Avoid 'class'/'function'.")
    description: str = Field(description="One paragraph: what this role does and "
                            "why it exists, grounded in the typed-edge neighborhood.")
    dissonance_kind: str | None = Field(
        default=None,
        description="If the members' names suggest DIFFERENT purposes despite "
        "their shared structure (a misleadingly-grouped role), name it; else null.",
    )
    dissonance_evidence: str | None = Field(default=None)


class OpLabelOut(BaseModel):
    """Label + intent for one composition operation (source_kind='operad-op')."""

    label: str = Field(description="Short name for what this composition "
                       "accomplishes, 2-5 words.")
    description: str = Field(description="One sentence. For a boundary/protocol "
                            "op, phrase as a caller contract ('callers must …').")


class ExportLabelOut(BaseModel):
    """Contract semantics for one provided symbol (source_kind='interface-export')."""

    contract: str = Field(description="One sentence: the contract semantics of "
                         "this exported symbol — what a caller may rely on.")


class ShapeLabelOut(BaseModel):
    """Meaning of one data type (source_kind='data-shape')."""

    meaning: str = Field(description="One sentence: what this type represents and "
                        "what its fields carry.")


class NlSymbolLabelOut(BaseModel):
    """Reading of one structurally-invisible symbol (source_kind='nl-only')."""

    description: str = Field(description="One sentence: what this symbol is for, "
                            "read from its name, comments, and body alone.")


# ----- pattern_id / provenance -----


def spec_pattern_id(
    source_kind: str, source_ref: str, *, prompt_version: str, llm_model: str
) -> str:
    """Deterministic pattern_id for a spec label. Same source + prompt + model →
    same id (overwrite, don't accumulate), per the L3 convention."""
    canon = json.dumps(
        [source_kind, source_ref, prompt_version, llm_model],
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return f"{source_kind}:{blake3.blake3(canon).hexdigest()[:16]}"


# ----- structural (name-blind) dissonance detection (§5.3) -----

_TOKEN_SPLIT = re.compile(r"[^a-zA-Z0-9]+|(?<=[a-z0-9])(?=[A-Z])|(?<=[A-Z])(?=[A-Z][a-z])")
_STOPWORDS = {"", "the", "a", "get", "set", "is", "to", "of", "and", "self", "cls",
              "py", "ts", "js", "tsx", "impl", "base", "test"}


def name_tokens(qualified_name: str) -> set[str]:
    """Lowercased identifier stems from a qualified name's *last* segment."""
    last = qualified_name.replace("\\", "/").split("/")[-1]
    last = last.split(".")[-1] if "." in last and "/" not in last else last
    last = re.split(r"[.#:]", last)[-1]
    toks = {t.lower() for t in _TOKEN_SPLIT.split(last) if t}
    return {t for t in toks if t not in _STOPWORDS and len(t) > 1}


def detect_role_dissonance(
    member_qnames: Sequence[str], *, cardinality: int
) -> IntentDissonance | None:
    """Name-blind check: a structurally-unified role class whose members share
    *no* naming stem is a candidate dissonance — structure says "one role", the
    names disagree (§5.3). Only fires for classes big enough for the signal to
    mean something (≥3 members). Returns None when names cohere."""
    if cardinality < 3:
        return None
    token_sets = [name_tokens(q) for q in member_qnames]
    token_sets = [t for t in token_sets if t]
    if len(token_sets) < 3:
        return None
    counts: Counter[str] = Counter()
    for ts in token_sets:
        counts.update(ts)
    n = len(token_sets)
    # Fraction of members sharing the single most common stem.
    top_share = (counts.most_common(1)[0][1] / n) if counts else 0.0
    if top_share < 0.34:  # fewer than ~a third share any single stem
        sample = ", ".join(q.split("/")[-1] for q in list(member_qnames)[:6])
        return IntentDissonance(
            kind="name_incoherence",
            evidence=(
                f"{cardinality} members share this structural role but their names "
                f"cohere weakly (top stem in {top_share:.0%} of members): {sample}"
            ),
            source="structural",
        )
    return None


# ----- FTS harvest (§5.1 evidence pack: FTS over the member set) -----


def harvest_fts(
    sqlite_path: str | Path, repo: str, terms: Sequence[str], *, limit: int = 8
) -> list[dict]:
    """Best-effort FTS hits for a few dominant name stems of a subsystem — the
    comment/README/string context the typed graph is blind to. Never raises:
    a missing or unqueryable index just yields no hits."""
    from ctkr.graph_loader import search_tokens

    p = Path(sqlite_path)
    if not p.exists() or not terms:
        return []
    # OR the stems together; FTS5 quotes each term to avoid syntax injection.
    query = " OR ".join(f'"{t}"' for t in terms if t)
    if not query:
        return []
    try:
        df = search_tokens(p, query, limit=limit, repo=repo)
    except Exception as e:  # noqa: BLE001
        logger.debug("FTS harvest skipped: %s", e)
        return []
    out: list[dict] = []
    for row in df.iter_rows(named=True):
        out.append({k: row.get(k) for k in ("text", "kind", "file", "line")})
    return out


# ----- the labeler (wraps LLMClient; tests inject a mock provider) -----


@dataclass(slots=True)
class LabelResult:
    parsed: BaseModel
    pattern: PatternRow
    evidence: list[EvidenceRow]
    cost_usd: float
    cache_hit: bool


@dataclass(slots=True)
class SpecLabeler:
    client: LLMClient
    model: str = DEFAULT_MODEL
    # Optional stronger model for the highest-stakes subsystem name+intent pass
    # (MetaCoding-hqk). None → use ``model`` (keeps the mock/offline path single-
    # model). Cheap per-element labels (roles/ops/exports/shapes/nl) stay on
    # ``model``; only the subsystem call is routed here.
    subsystem_model: str | None = None
    temperature: float = DEFAULT_TEMPERATURE
    prompt_version: str = DEFAULT_PROMPT_VERSION
    max_tokens: int = 1024

    def _label(
        self,
        *,
        source_kind: str,
        source_ref: str,
        prompt: str,
        system: str,
        schema: type[BaseModel],
        instances: Sequence[str],
        evidence_rows: list[EvidenceRow],
        model: str | None = None,
    ) -> LabelResult:
        use_model = model or self.model
        result = self.client.complete_structured(
            prompt,
            schema=schema,
            model=use_model,
            temperature=self.temperature,
            max_tokens=self.max_tokens,
            system=system,
        )
        pid = spec_pattern_id(
            source_kind, source_ref, prompt_version=self.prompt_version, llm_model=use_model
        )
        parsed = result.parsed
        # A short human label + description drawn from whatever field the schema
        # carries — for the shared PatternRow shape.
        label = getattr(parsed, "label", None) or getattr(parsed, "name", None) or source_kind
        desc = (
            getattr(parsed, "description", None)
            or getattr(parsed, "intent", None)
            or getattr(parsed, "contract", None)
            or getattr(parsed, "meaning", None)
            or ""
        )
        conf = float(getattr(parsed, "confidence", 1.0) or 1.0)
        pattern = PatternRow(
            pattern_id=pid,
            source_kind=source_kind,  # type: ignore[arg-type]
            source_ref=source_ref,
            label=str(label),
            description=str(desc),
            instances=list(instances),
            confidence=max(0.0, min(1.0, conf)),
            llm_model=use_model,
            llm_temperature=self.temperature,
            prompt_version=self.prompt_version,
            generated_at=datetime.now(tz=UTC),
        )
        for ev in evidence_rows:
            ev.pattern_id = pid
        return LabelResult(
            parsed=parsed,
            pattern=pattern,
            evidence=evidence_rows,
            cost_usd=result.cost_estimate_usd,
            cache_hit=result.cache_hit,
        )


_SYS_SUBSYSTEM = (
    "You are a software-architecture analyst producing a stack-agnostic "
    "specification of ONE subsystem, extracted structurally (name-blind) from a "
    "codebase so it can be re-implemented in a different language. Name the "
    "subsystem and describe its intent.\n\n"
    "The single strongest evidence for what a subsystem IS is (1) what it EXPORTS "
    "across its boundary — the symbols external code depends on — and (2) what its "
    "role classes DO. These are given to you already labeled from structure. "
    "Ground the name and intent in THOSE, not in the raw volume of internal "
    "members. A subsystem whose exports are types and query functions is an API/"
    "data layer; one whose exports are handlers/tools is a server; one whose "
    "exports are training routines is a pipeline — read the exports, do not guess.\n\n"
    "CRITICAL de-bias rule: you are labeling a codebase that is ITSELF about code "
    "analysis, so its identifiers are saturated with words like graph, embedding, "
    "node, walk, vector, motif, pipeline. Do NOT put any such domain buzzword in "
    "the subsystem name or intent unless the EXPORTS and ROLE descriptions below "
    "actually support it (e.g. only call it an 'embedding' subsystem if it exports "
    "embedding-producing symbols). Prefer a name that states the subsystem's "
    "responsibility in plain architectural terms.\n\n"
    "If the members' NAMES collectively imply a different purpose than the "
    "STRUCTURE, flag the disagreement — do not smooth it over."
)
_SYS_ROLE = (
    "You label the ROLE that a cluster of structurally-equivalent symbols plays, "
    "for a cross-stack spec. Give the role a short canonical name and describe "
    "what it does and why it exists, grounded in the typed-edge neighborhood. If "
    "the members' names suggest DIFFERENT purposes despite identical structure "
    "(a misleadingly-grouped role), flag it."
)
_SYS_OP = (
    "You describe one recovered COMPOSITION operation (how role classes combine "
    "into behavior) for a cross-stack spec. Say what the composition accomplishes. "
    "If it is a boundary/protocol operation, phrase it as a caller contract."
)
_SYS_EXPORT = (
    "You describe the CONTRACT of one exported symbol at a subsystem boundary — "
    "what an external caller may rely on. One sentence, grounded in the code."
)
_SYS_SHAPE = (
    "You describe the MEANING of one data type in a subsystem's boundary "
    "vocabulary — what it represents and what its fields carry. One sentence."
)
_SYS_NL = (
    "You read one structurally-isolated symbol (no typed-edge signal) and say "
    "what it is for, from its name, comments, and body alone. One sentence."
)


# ----- evidence helpers -----


def _slice_for(
    graph: nx.MultiDiGraph, symbol_id: str, root: str | Path
) -> InstanceEvidence | None:
    """One symbol's code slice (tree-sitter window + docstring) via the shared
    evidence builder. Returns None when the symbol has no readable source."""
    pack = build_evidence_pack(
        graph,
        [symbol_id],
        source_kind="role-class",
        source_ref=symbol_id,
        orchestrators_root=root,
        token_budget=4000,
    )
    return pack.instances[0] if pack.instances else None


def _ev_row(inst: InstanceEvidence, repo: str) -> EvidenceRow:
    return EvidenceRow(
        pattern_id="",  # filled by the labeler
        repo=repo,
        file=inst.file,
        line_range=LineRange(start=inst.line_range.start, end=inst.line_range.end),
        snippet=inst.snippet,
        context=inst.qualified_name,
    )


def _render_instance(inst: InstanceEvidence, header: str) -> list[str]:
    parts = [header, f"- `{inst.qualified_name}` ({inst.file}:{inst.line_range.start})"]
    if inst.docstring:
        parts.append(f"- doc: {inst.docstring[:400]}")
    parts.append("```")
    parts.append(inst.snippet)
    parts.append("```")
    return parts


# ----- deck-run stats -----


@dataclass(slots=True)
class DeckStats:
    n_subsystems: int = 0
    n_cards: int = 0
    n_labels: int = 0
    n_role_labels: int = 0
    n_op_labels: int = 0
    n_export_labels: int = 0
    n_shape_labels: int = 0
    n_nl_labels: int = 0
    n_dissonance_structural: int = 0
    n_dissonance_llm: int = 0
    n_nl_only_symbols: int = 0
    n_members_total: int = 0
    n_members_structural: int = 0
    total_cost_usd: float = 0.0
    cache_hits: int = 0
    total_seconds: float = 0.0
    per_card: dict = field(default_factory=dict)


# ----- structural helpers -----


def _short(qn: str) -> str:
    return qn.replace("\\", "/").split("/")[-1]


def _is_zero_centroid(centroid: object) -> bool:
    """True when a role class's hom-profile centroid is all-zeros — the §2.3
    edgeless 'isolated' class (the zero-profile floor), not a real role."""
    if not centroid:
        return True
    try:
        return all(abs(float(x)) < 1e-12 for x in centroid)  # type: ignore[union-attr]
    except (TypeError, ValueError):
        return False


def _induced_edge_stats(
    graph: nx.MultiDiGraph, member_ids: set[str]
) -> tuple[dict[str, int], int]:
    """Internal typed-edge histogram + a cheap cycle count over the subsystem-
    induced subgraph. ``cycles`` = number of non-trivial strongly-connected
    components (feedback/dispatch loops — the H₁-flavored signal the card carries
    until per-subsystem PD lands in T7)."""
    hist: dict[str, int] = {}
    sub = nx.MultiDiGraph()
    sub.add_nodes_from(m for m in member_ids if graph.has_node(m))
    for u, v, k in graph.edges(keys=True):
        if u in member_ids and v in member_ids:
            hist[k] = hist.get(k, 0) + 1
            sub.add_edge(u, v, key=k)
    n_cycles = sum(1 for c in nx.strongly_connected_components(sub) if len(c) > 1)
    return hist, n_cycles


def _partition_config(subsystems_df: pl.DataFrame) -> dict:
    if subsystems_df.height == 0:
        return {}
    try:
        return json.loads(subsystems_df.row(0, named=True)["config"])
    except Exception:  # noqa: BLE001
        return {}


# ----- per-subsystem card build -----


def _build_card(
    *,
    subsystem_id: str,
    repo: str,
    members: list[dict],
    presentations: list[dict],
    interfaces: list[dict],
    data_shapes: list[dict],
    operads: list[dict],
    graph: nx.MultiDiGraph,
    root: str | Path,
    fts_path: Path | None,
    labeler: SpecLabeler,
    view: str,
    caps: dict[str, int],
    partition_config: dict,
    alphabet_note: str,
    hom_profiles_generated_at: str | None,
    indexed_with_scip: bool,
    generated_at: str,
    stats: DeckStats,
) -> tuple[SubsystemCard, list[PatternRow], list[EvidenceRow]]:
    patterns: list[PatternRow] = []
    evidences: list[EvidenceRow] = []

    def _record(res: LabelResult) -> None:
        patterns.append(res.pattern)
        evidences.extend(res.evidence)
        stats.n_labels += 1
        stats.total_cost_usd += res.cost_usd
        if res.cache_hit:
            stats.cache_hits += 1

    member_ids = {m["symbol_id"] for m in members}
    member_qn = {m["symbol_id"]: (m.get("qualified_name") or m["symbol_id"]) for m in members}
    n_total = len(members)

    # The zero-profile floor (§2.3, §5.4): the "isolated" role class groups
    # members whose profile vector is all-zeros (no typed-edge signal). Structure
    # genuinely cannot discriminate them, so they are NOT a real role — they are
    # specced by the NL lane. Detect such classes by an all-zero centroid and
    # route their members to the nl-only floor rather than counting them as
    # structural (which would inflate spec_basis_summary and leak a pseudo-role).
    isolated_role_ids = {r["role_id"] for r in presentations if _is_zero_centroid(r.get("profile_centroid"))}
    isolated_member_ids: set[str] = set()
    for r in presentations:
        if r["role_id"] in isolated_role_ids:
            isolated_member_ids.update(r["members"])
    isolated_member_ids &= member_ids

    # Structural coverage = a member in a NON-isolated presentation class.
    structural_ids: set[str] = set()
    for r in presentations:
        if r["role_id"] in isolated_role_ids:
            continue
        structural_ids.update(r["members"])
    structural_ids &= member_ids
    structural_ids -= isolated_member_ids
    n_struct = len(structural_ids)
    nl_only_ids = sorted(member_ids - structural_ids, key=lambda s: member_qn.get(s, s))

    # Role rows for the card's view, by descending cardinality — real roles only
    # (the isolated floor is excluded so it never gets labeled as a role).
    view_pres = sorted(
        (r for r in presentations if r["view"] == view and r["role_id"] not in isolated_role_ids),
        key=lambda r: (-int(r["cardinality"]), r["role_id"]),
    )
    # role_id -> a display name (LLM label once labeled, else exemplar short name).
    role_display: dict[str, str] = {
        r["role_id"]: _short(r.get("exemplar_qualified_name") or "") or r["role_id"][:10]
        for r in view_pres
    }

    # ---- roles ----
    role_cards: list[RoleCard] = []
    subsystem_dissonances: list[IntentDissonance] = []
    exemplar_slices: list[ExemplarSlice] = []
    seen_slice_ids: set[str] = set()
    for r in view_pres[: caps["roles"]]:
        mem = list(r["members"])
        exemplar = r.get("exemplar_symbol_id")
        ev_rows: list[EvidenceRow] = []
        slices_txt: list[str] = []
        for sid in ([exemplar] + mem[:2] if exemplar else mem[:2]):
            if sid is None:
                continue
            inst = _slice_for(graph, sid, root)
            if inst is None:
                continue
            ev_rows.append(_ev_row(inst, repo))
            slices_txt.extend(_render_instance(inst, f"#### member `{_short(inst.qualified_name)}`"))
            if sid == exemplar and sid not in seen_slice_ids:
                exemplar_slices.append(
                    ExemplarSlice(
                        purpose=f"role:{role_display.get(r['role_id'], r['role_id'])} exemplar",
                        symbol_id=sid,
                        file=inst.file,
                        line_start=inst.line_range.start,
                        line_end=inst.line_range.end,
                        code=inst.snippet,
                    )
                )
                seen_slice_ids.add(sid)
        prompt = "\n".join(
            [
                f"# Role class in subsystem `{subsystem_id[:12]}` (repo {repo})",
                f"- cardinality: {r['cardinality']}",
                f"- interface participation: {r.get('interface_participation') or 'none (internal)'}",
                f"- members (short names): {', '.join(_short(member_qn.get(s, s)) for s in mem[:12])}",
                "",
                "## Evidence slices",
                *slices_txt,
                "",
                "Emit a RoleLabelOut. Flag name-vs-structure dissonance if present.",
            ]
        )
        res = labeler._label(
            source_kind="role-class",
            source_ref=r["role_id"],
            prompt=prompt,
            system=_SYS_ROLE,
            schema=RoleLabelOut,
            instances=mem[:12],
            evidence_rows=ev_rows,
        )
        _record(res)
        stats.n_role_labels += 1
        out: RoleLabelOut = res.parsed  # type: ignore[assignment]
        role_display[r["role_id"]] = out.label

        # Dissonance: structural (name-blind) OR llm-flagged.
        diss: IntentDissonance | None = detect_role_dissonance(
            [member_qn.get(s, s) for s in mem], cardinality=int(r["cardinality"])
        )
        if diss is not None:
            stats.n_dissonance_structural += 1
        if out.dissonance_kind and out.dissonance_evidence:
            stats.n_dissonance_llm += 1
            llm_diss = IntentDissonance(
                kind=out.dissonance_kind, evidence=out.dissonance_evidence, source="llm"
            )
            diss = diss or llm_diss
            subsystem_dissonances.append(llm_diss)
        elif diss is not None:
            subsystem_dissonances.append(diss)

        role_cards.append(
            RoleCard(
                role_id=r["role_id"],
                view=view,
                label=out.label,
                description=out.description,
                cardinality=int(r["cardinality"]),
                members=mem,
                exemplar_symbol=exemplar,
                exemplar_qualified_name=r.get("exemplar_qualified_name"),
                profile_depth=int(r.get("profile_depth") or 1),
                granularity=str(r.get("granularity") or ""),
                interface_participation=list(r.get("interface_participation") or []),
                invariance_tier="I",
                intent_dissonance=diss,
            )
        )

    # ---- composition rules (operations) ----
    op_rows = sorted(
        (o for o in operads if o["view"] == view and o["op_kind"] != "non_operadic"),
        key=lambda o: (not o["is_boundary_op"], -int(o["support"]), o["operation_id"]),
    )
    rule_cards: list[CompositionRuleCard] = []
    for o in op_rows[: caps["ops"]]:
        in_names = [role_display.get(rid, rid[:10]) for rid in o["input_roles"]]
        out_name = role_display.get(o["output_role"], o["output_role"][:10])
        prompt = "\n".join(
            [
                f"# Composition operation in subsystem `{subsystem_id[:12]}`",
                f"- kind: {o['op_kind']} (arity {o['arity']})",
                f"- role-path: {' ∘ '.join(in_names)} -> {out_name}",
                f"- edge kinds: {o['edge_kinds']}   support: {o['support']}",
                f"- boundary/protocol op: {o['is_boundary_op']}",
                f"- concrete exemplar paths: {list(o['exemplar_paths'])[:4]}",
                "",
                "Emit an OpLabelOut.",
            ]
        )
        res = labeler._label(
            source_kind="operad-op",
            source_ref=o["operation_id"],
            prompt=prompt,
            system=_SYS_OP,
            schema=OpLabelOut,
            instances=list(o["exemplar_paths"])[:4],
            evidence_rows=[],
        )
        _record(res)
        stats.n_op_labels += 1
        oout: OpLabelOut = res.parsed  # type: ignore[assignment]
        rule_cards.append(
            CompositionRuleCard(
                operation_id=o["operation_id"],
                label=oout.label,
                description=oout.description,
                op_kind=o["op_kind"],
                arity=int(o["arity"]),
                input_roles=list(o["input_roles"]),
                output_role=o["output_role"],
                edge_kinds=list(o["edge_kinds"]),
                support=int(o["support"]),
                is_boundary_op=bool(o["is_boundary_op"]),
                law_notes={
                    "associative_observed": bool(o["associative_observed"]),
                    "violations": int(o["law_violations"]),
                    "violation_kind": o.get("violation_kind") or "",
                },
                exemplar_paths=list(o["exemplar_paths"]),
                invariance_tier=str(o.get("invariance_tier") or "I"),  # type: ignore[arg-type]
            )
        )

    # ---- interface ----
    # Provides: group by rolled-up export symbol, sum callers, collect usage modes.
    prov: dict[str, dict] = {}
    for r in interfaces:
        if r["direction"] != "provides":
            continue
        key = r.get("internal_export_symbol_id") or r["internal_symbol_id"]
        qn = r.get("internal_export_qualified_name") or r["internal_qualified_name"]
        e = prov.setdefault(key, {"qn": qn, "modes": set(), "callers": 0, "member": r["internal_symbol_id"]})
        e["modes"].add(r["edge_kind"])
        e["callers"] += int(r["edge_count"])
    # role lookup for exports: which role_id contains the export symbol
    sym_to_role: dict[str, str] = {}
    for rc in role_cards:
        for s in rc.members:
            sym_to_role.setdefault(s, rc.role_id)
    export_cards: list[InterfaceExportCard] = []
    for key, e in sorted(prov.items(), key=lambda kv: (-kv[1]["callers"], kv[0]))[: caps["exports"]]:
        inst = _slice_for(graph, key, root) or _slice_for(graph, e["member"], root)
        ev_rows = [_ev_row(inst, repo)] if inst else []
        slices_txt = _render_instance(inst, "#### export") if inst else ["(no readable source)"]
        prompt = "\n".join(
            [
                f"# Exported symbol `{_short(e['qn'])}` of subsystem `{subsystem_id[:12]}`",
                f"- usage modes (how external code references it): {sorted(e['modes'])}",
                f"- external references: {e['callers']}",
                "",
                *slices_txt,
                "",
                "Emit an ExportLabelOut (the caller-facing contract).",
            ]
        )
        res = labeler._label(
            source_kind="interface-export",
            source_ref=f"{subsystem_id}:{key}",
            prompt=prompt,
            system=_SYS_EXPORT,
            schema=ExportLabelOut,
            instances=[key],
            evidence_rows=ev_rows,
        )
        _record(res)
        stats.n_export_labels += 1
        eout: ExportLabelOut = res.parsed  # type: ignore[assignment]
        export_cards.append(
            InterfaceExportCard(
                symbol=_short(e["qn"]),
                symbol_id=key,
                role_id=sym_to_role.get(key) or sym_to_role.get(e["member"]),
                usage_modes=sorted(e["modes"]),
                contract=eout.contract,
                n_external_callers=e["callers"],
            )
        )
    # Consumes: structural summary grouped by target subsystem / external package
    # (purpose derived structurally — kept name-blind to bound cost, §3 topology).
    cons: dict[str, dict] = {}
    for r in interfaces:
        if r["direction"] != "consumes":
            continue
        tgt_sub = r.get("external_subsystem_id")
        key = tgt_sub or "(external package)"
        e = cons.setdefault(key, {"modes": set(), "count": 0, "sample": r["external_qualified_name"]})
        e["modes"].add(r["edge_kind"])
        e["count"] += int(r["edge_count"])
    consume_cards = [
        InterfaceConsumeCard(
            target=_short(e["sample"]) if key == "(external package)" else key,
            target_subsystem=None if key == "(external package)" else key,
            edge_kinds=sorted(e["modes"]),
            purpose=f"Depends on {key} via {', '.join(sorted(e['modes']))} "
            f"({e['count']} crossing morphisms).",
        )
        for key, e in sorted(cons.items(), key=lambda kv: -kv[1]["count"])[:12]
    ]

    # ---- data shapes ----
    shapes_by_type: dict[str, dict] = {}
    for r in data_shapes:
        t = r["type_symbol_id"]
        e = shapes_by_type.setdefault(
            t, {"qn": r["type_qualified_name"], "boundary": bool(r["boundary"]), "fields": []}
        )
        if r.get("field_name"):
            flow = _field_flow(r)
            raw_ftype = r.get("field_type")
            # Normalize: strip any absolute worktree-checkout path prefix so that a
            # deck built from a worktree produces identical DataFieldCard.type values
            # to one built from the main checkout (§MetaCoding-j3y).
            # _short() already strips everything before the last "/" which covers both
            # "/abs/.../file.ts::Type" → "file.ts::Type" and "pkg/file.ts::Type" →
            # "file.ts::Type" consistently.  Scalar primitives ("str", "int", …) have
            # no "/" so they pass through unchanged.
            norm_ftype = _short(raw_ftype) if raw_ftype else raw_ftype
            e["fields"].append(DataFieldCard(name=r["field_name"], type=norm_ftype, flow=flow))
    # boundary types first, then by field count
    ordered_types = sorted(
        shapes_by_type.items(), key=lambda kv: (not kv[1]["boundary"], -len(kv[1]["fields"]), kv[0])
    )
    shape_cards: list[DataShapeCard] = []
    for t, e in ordered_types[: caps["shapes"]]:
        inst = _slice_for(graph, t, root)
        ev_rows = [_ev_row(inst, repo)] if inst else []
        fields_desc = ", ".join(f"{f.name}:{f.type or '?'}({f.flow})" for f in e["fields"][:20])
        prompt = "\n".join(
            [
                f"# Data type `{_short(e['qn'])}` ({'boundary' if e['boundary'] else 'internal'})",
                f"- fields: {fields_desc or '(none recovered)'}",
                "",
                *(_render_instance(inst, "#### type") if inst else []),
                "",
                "Emit a ShapeLabelOut.",
            ]
        )
        res = labeler._label(
            source_kind="data-shape",
            source_ref=f"{subsystem_id}:{t}",
            prompt=prompt,
            system=_SYS_SHAPE,
            schema=ShapeLabelOut,
            instances=[t],
            evidence_rows=ev_rows,
        )
        _record(res)
        stats.n_shape_labels += 1
        sout: ShapeLabelOut = res.parsed  # type: ignore[assignment]
        shape_cards.append(
            DataShapeCard(
                type=_short(e["qn"]),
                type_symbol_id=t,
                boundary=e["boundary"],
                meaning=sout.meaning,
                fields=e["fields"],
                invariance_tier="I" if e["boundary"] else "A",
                alphabet_coverage_note=alphabet_note,
            )
        )

    # ---- nl-only symbols (the §5.4 floor: list ALL, describe a capped sample) ----
    nl_cards: list[NlOnlySymbol] = []
    placement_of = {m["symbol_id"]: (m.get("placement") or "structural") for m in members}
    file_of = {}
    for sid in nl_only_ids:
        node = graph.nodes.get(sid, {}) if graph.has_node(sid) else {}
        file_of[sid] = node.get("file") or node.get("file_path")
    described = 0
    for sid in nl_only_ids:
        desc = ""
        if described < caps["nl_desc"]:
            inst = _slice_for(graph, sid, root)
            if inst is not None:
                prompt = "\n".join(
                    [
                        f"# Structurally-isolated symbol `{_short(inst.qualified_name)}`",
                        "(no typed-edge signal — specced from source text alone)",
                        "",
                        *_render_instance(inst, "#### source"),
                        "",
                        "Emit an NlSymbolLabelOut.",
                    ]
                )
                res = labeler._label(
                    source_kind="nl-only",
                    source_ref=f"{subsystem_id}:{sid}",
                    prompt=prompt,
                    system=_SYS_NL,
                    schema=NlSymbolLabelOut,
                    instances=[sid],
                    evidence_rows=[_ev_row(inst, repo)],
                )
                _record(res)
                stats.n_nl_labels += 1
                desc = res.parsed.description  # type: ignore[attr-defined]
                described += 1
        nl_cards.append(
            NlOnlySymbol(
                symbol_id=sid,
                qualified_name=member_qn.get(sid, sid),
                file=file_of.get(sid),
                placement=placement_of.get(sid, "structural"),
                spec_basis="nl-only",
                description=desc,
            )
        )
    stats.n_nl_only_symbols += len(nl_cards)

    # ---- topology ----
    hist, n_cycles = _induced_edge_stats(graph, member_ids)
    n_prov = sum(1 for r in interfaces if r["direction"] == "provides")
    n_cons = sum(1 for r in interfaces if r["direction"] == "consumes")
    topology = TopologyCard(
        n_members=n_total,
        internal_edge_histogram=hist,
        cycles=n_cycles,
        interface_degree={"in": n_prov, "out": n_cons},
    )

    # ---- subsystem name + intent (HIERARCHICAL, MetaCoding-hqk) ----
    # The name+intent is summarized FROM the already-extracted structure — the
    # labeled role classes, the interface (what the subsystem provides/consumes),
    # and the top composition ops — NOT from a raw dump of thousands of diluted
    # members. For a 2000-member subsystem the 8 top exports + role labels are far
    # more discriminative than any member sample, and grounding the summary in
    # them is what stops the labeler falling back on generic domain boilerplate
    # (§5.1, §4.1). Exports lead: they are the strongest single signal for "what
    # this subsystem IS" (a data/API layer vs. a server vs. a pipeline).
    role_lines = [
        "- "
        + f"{rc.label} (x{rc.cardinality}"
        + (f", {'/'.join(rc.interface_participation)}" if rc.interface_participation else "")
        + f"): {rc.description[:200]}"
        for rc in role_cards[:8]
    ] or ["(no role classes — structurally sparse subsystem)"]
    provides_lines = [
        f"- `{ec.symbol}` [{'/'.join(ec.usage_modes)}], {ec.n_external_callers} external refs: "
        f"{ec.contract[:200]}"
        for ec in export_cards[:12]
    ] or ["(no exported symbols cross this subsystem's boundary)"]
    consumes_lines = [
        f"- {cc.target_subsystem or cc.target} via {', '.join(cc.edge_kinds)}"
        for cc in consume_cards[:8]
    ] or ["(no outgoing dependencies)"]
    op_lines = [
        "- "
        + f"{rc_.label}: "
        + " ∘ ".join(role_display.get(rid, rid[:8]) for rid in rc_.input_roles)
        + f" -> {role_display.get(rc_.output_role, rc_.output_role[:8])} (support {rc_.support})"
        for rc_ in rule_cards[:6]
    ] or ["(no recurring composition operations recovered)"]
    shape_lines = [
        f"- `{sc.type}`{' [boundary]' if sc.boundary else ''}: {sc.meaning[:160]}"
        for sc in shape_cards[:6]
    ] or ["(no data shapes recovered)"]
    # FTS context stays a *secondary* signal (comments/strings the graph is blind
    # to). Reproducibility (MetaCoding-hqk): `structural_ids` is a set — sort it
    # before slicing so the prompt text, and thus the LLM-cache key and the label,
    # are byte-stable across re-runs.
    # ``name_tokens`` returns a *set*; iterate it sorted so the Counter's
    # insertion order — and therefore ``most_common`` tie-breaking — is stable
    # across processes (PYTHONHASHSEED-independent). Without this the top FTS
    # terms, the FTS query, and thus one subsystem's label wobble run-to-run
    # (MetaCoding-hqk).
    fts_terms: list[str] = [
        w for w, _ in Counter(
            t for s in nl_only_ids[:30] + sorted(structural_ids)[:30]
            for t in sorted(name_tokens(member_qn.get(s, s)))
        ).most_common(5)
    ]
    fts_hits = harvest_fts(fts_path, repo, fts_terms) if fts_path else []
    fts_txt = "\n".join(f"- {h.get('kind')} `{h.get('text')}` ({h.get('file')}:{h.get('line')})" for h in fts_hits[:8])
    sub_prompt = "\n".join(
        [
            f"# Subsystem `{subsystem_id[:12]}` of repo {repo}",
            f"{n_total} members ({n_struct} structural, {n_total - n_struct} nl-only). "
            "Name and describe it from the structure below — lead with the interface.",
            "",
            "## Interface — what this subsystem PROVIDES (its API surface; primary signal)",
            *provides_lines,
            "",
            "## Role classes — what its members DO (labeled from structure)",
            *role_lines,
            "",
            "## Composition — how the roles combine",
            *op_lines,
            "",
            "## Data shapes crossing the boundary",
            *shape_lines,
            "",
            "## Depends on (outgoing boundary)",
            *consumes_lines,
            "",
            "## Secondary: naming/comment/string context (do not over-weight)",
            fts_txt or "(none)",
            "",
            "Emit a SubsystemLabelOut. Name the subsystem for the responsibility its "
            "interface and roles reveal — not for domain buzzwords in the identifiers. "
            "Flag any name-vs-structure dissonance.",
        ]
    )
    sub_res = labeler._label(
        source_kind="subsystem",
        source_ref=subsystem_id,
        prompt=sub_prompt,
        system=_SYS_SUBSYSTEM,
        schema=SubsystemLabelOut,
        instances=sorted(member_ids)[:20],
        evidence_rows=[],
        model=labeler.subsystem_model or labeler.model,
    )
    _record(sub_res)
    sout2: SubsystemLabelOut = sub_res.parsed  # type: ignore[assignment]
    if sout2.dissonance_kind and sout2.dissonance_evidence:
        stats.n_dissonance_llm += 1
        subsystem_dissonances.insert(
            0,
            IntentDissonance(
                kind=sout2.dissonance_kind, evidence=sout2.dissonance_evidence, source="llm"
            ),
        )

    # ---- spec basis + provenance + id ----
    basis = SpecBasisSummary(
        structural=round(n_struct / n_total, 4) if n_total else 0.0,
        nl_only=round((n_total - n_struct) / n_total, 4) if n_total else 0.0,
    )
    struct_dig = cardmod.structural_digest(
        member_ids=sorted(member_ids),
        role_ids=[r["role_id"] for r in presentations],
        operation_ids=[o["operation_id"] for o in operads],
        interface_keys=[
            f"{r['direction']}:{r['internal_symbol_id']}->{r['external_symbol_id']}:{r['edge_kind']}"
            for r in interfaces
        ],
        data_shape_keys=[
            f"{r['type_symbol_id']}:{r.get('field_symbol_id') or ''}" for r in data_shapes
        ],
    )
    cid = cardmod.card_id(
        subsystem_id=subsystem_id,
        struct_digest=struct_dig,
        prompt_version=labeler.prompt_version,
        llm_model=labeler.model,
    )
    provenance = Provenance(
        generated_at=generated_at,
        partition_config=partition_config,
        llm_model=labeler.model,
        llm_temperature=labeler.temperature,
        prompt_version=labeler.prompt_version,
        hom_profiles_generated_at=hom_profiles_generated_at,
        indexed_with_scip=indexed_with_scip,
    )
    card = SubsystemCard(
        card_id=cid,
        subsystem_id=subsystem_id,
        repo=repo,
        name=sout2.name,
        intent=sout2.intent,
        responsibilities=list(sout2.responsibilities),
        non_goals=list(sout2.non_goals),
        spec_basis_summary=basis,
        intent_dissonance=subsystem_dissonances,
        roles=role_cards,
        composition_rules=rule_cards,
        interface=InterfaceCard(provides=export_cards, consumes=consume_cards),
        data_shapes=shape_cards,
        topology=topology,
        exemplar_slices=exemplar_slices,
        nl_only_symbols=nl_cards,
        n_members=n_total,
        provenance=provenance,
    )
    stats.n_members_total += n_total
    stats.n_members_structural += n_struct
    stats.per_card[cid] = {
        "subsystem_id": subsystem_id,
        "name": sout2.name,
        "n_members": n_total,
        "structural_frac": basis.structural,
        "n_roles": len(role_cards),
        "n_rules": len(rule_cards),
        "n_provides": len(export_cards),
        "n_data_shapes": len(shape_cards),
        "n_nl_only": len(nl_cards),
        "n_dissonance": len(subsystem_dissonances),
    }
    return card, patterns, evidences


def _field_flow(r: dict) -> str:
    """Per-field flow direction from the read/write-by-internal/external flags (§3)."""
    ri, re_, wi, we = (
        bool(r.get("read_by_internal")),
        bool(r.get("read_by_external")),
        bool(r.get("written_by_internal")),
        bool(r.get("written_by_external")),
    )
    if we and ri and not wi and not re_:
        return "in"
    if wi and re_ and not we and not ri:
        return "out"
    if re_ or we:
        return "out" if we else "in"
    return "internal"


# ----- deck orchestration (Stage D + E) -----


def build_deck(
    *,
    data_dir: str | Path,
    repo_root: str | Path,
    client: LLMClient,
    model: str = DEFAULT_MODEL,
    subsystem_model: str | None = DEFAULT_SUBSYSTEM_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    view: str = "similarity",
    roles_per: int = DEFAULT_ROLES_PER,
    ops_per: int = DEFAULT_OPS_PER,
    exports_per: int = DEFAULT_EXPORTS_PER,
    shapes_per: int = DEFAULT_SHAPES_PER,
    nl_desc_per: int = DEFAULT_NL_DESC_PER,
    repo_filter: str | None = None,
    max_subsystems: int | None = None,
    generated_at: str | None = None,
    graph: nx.MultiDiGraph | None = None,
) -> tuple[list[SubsystemCard], list[PatternRow], list[EvidenceRow], DeckStats]:
    """Assemble the full deck (Stages D + E) from the structural Parquet artifacts.

    Reads ``subsystems`` / ``subsystem_members`` / ``presentations`` /
    ``interfaces`` / ``data_shapes`` / ``operads`` under ``<data_dir>/ctkr/`` and
    the exported graph under ``<data_dir>``; assembles evidence and labels each
    element; fuses one :class:`SubsystemCard` per subsystem. ``repo_root`` is the
    parent directory containing the indexed repo as a subdirectory (source slices
    are read from ``<repo_root>/<repo>/<file>``).
    """
    start = time.perf_counter()
    ddir = Path(data_dir).expanduser().resolve()
    ctkr_dir = ddir / "ctkr"
    gen_at = generated_at or datetime.now(tz=UTC).isoformat()

    def _load(name: str) -> pl.DataFrame:
        p = ctkr_dir / f"{name}.parquet"
        if not p.exists():
            raise FileNotFoundError(
                f"{p} not found — run the earlier stages (subsystems/interfaces/"
                f"roles/operads) before extract-spec."
            )
        return pl.read_parquet(p)

    subs_df = _load("subsystems")
    mem_df = _load("subsystem_members")
    pres_df = _load("presentations")
    iface_df = _load("interfaces")
    shape_df = _load("data_shapes")
    op_df = _load("operads")

    if repo_filter:
        subs_df = subs_df.filter(pl.col("repo") == repo_filter)

    manifest = _read_manifest(ctkr_dir)
    hom_gen = manifest.get("generated_at")
    alphabet = (manifest.get("alphabet_coverage") or {})
    scip_any = any((v or {}).get("scip_fraction", 0) > 0 for v in alphabet.values()) or bool(alphabet)

    if graph is None:
        from ctkr.graph_loader import load_graph

        graph = load_graph(ddir)

    fts_path = _find_fts(ddir)

    labeler = SpecLabeler(
        client=client,
        model=model,
        subsystem_model=subsystem_model,
        temperature=temperature,
        prompt_version=prompt_version,
    )
    caps = {"roles": roles_per, "ops": ops_per, "exports": exports_per,
            "shapes": shapes_per, "nl_desc": nl_desc_per}

    # group by subsystem
    def _by_sub(df: pl.DataFrame) -> dict[str, list[dict]]:
        out: dict[str, list[dict]] = {}
        for row in df.iter_rows(named=True):
            out.setdefault(row["subsystem_id"], []).append(row)
        return out

    mem_by = _by_sub(mem_df)
    pres_by = _by_sub(pres_df)
    iface_by = _by_sub(iface_df)
    shape_by = _by_sub(shape_df)
    op_by = _by_sub(op_df)
    partition_config = _partition_config(subs_df)

    stats = DeckStats()
    cards: list[SubsystemCard] = []
    all_patterns: list[PatternRow] = []
    all_evidence: list[EvidenceRow] = []

    sub_rows = sorted(subs_df.iter_rows(named=True), key=lambda r: -int(r["n_members"]))
    if max_subsystems is not None:
        sub_rows = sub_rows[:max_subsystems]
    stats.n_subsystems = len(sub_rows)

    for i, srow in enumerate(sub_rows, 1):
        ssid = srow["subsystem_id"]
        repo = srow["repo"]
        members = mem_by.get(ssid, [])
        if not members:
            continue
        alpha_note = ((alphabet.get(repo) or {}).get("note")) or "alphabet coverage: n/a"
        logger.info("card %d/%d — subsystem %s (%d members)", i, len(sub_rows), ssid[:12], len(members))
        card, pats, evs = _build_card(
            subsystem_id=ssid,
            repo=repo,
            members=members,
            presentations=pres_by.get(ssid, []),
            interfaces=iface_by.get(ssid, []),
            data_shapes=shape_by.get(ssid, []),
            operads=op_by.get(ssid, []),
            graph=graph,
            root=repo_root,
            fts_path=fts_path,
            labeler=labeler,
            view=view,
            caps=caps,
            partition_config=partition_config,
            alphabet_note=alpha_note,
            hom_profiles_generated_at=hom_gen,
            indexed_with_scip=scip_any,
            generated_at=gen_at,
            stats=stats,
        )
        cards.append(card)
        all_patterns.extend(pats)
        all_evidence.extend(evs)
        stats.n_cards += 1

    stats.total_seconds = round(time.perf_counter() - start, 2)
    stats.total_cost_usd = round(stats.total_cost_usd, 6)
    return cards, all_patterns, all_evidence, stats


# ----- artifact writers (additive/idempotent) -----


def merge_patterns_jsonl(path: Path, new_rows: list[PatternRow]) -> None:
    """Additively merge spec PatternRows into a shared patterns.jsonl: drop any
    existing rows with a pattern_id we are re-emitting (overwrite, don't
    accumulate) and preserve every other labeler's rows (motif/role-cluster)."""
    _merge_jsonl(path, [r.model_dump_json() for r in new_rows], {r.pattern_id for r in new_rows}, "pattern_id")


def merge_evidence_jsonl(path: Path, new_rows: list[EvidenceRow]) -> None:
    new_pids = {r.pattern_id for r in new_rows}
    _merge_jsonl(path, [r.model_dump_json() for r in new_rows], new_pids, "pattern_id")


def _merge_jsonl(path: Path, new_lines: list[str], drop_keys: set[str], key: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    kept: list[str] = []
    if path.exists():
        with path.open("r", encoding="utf-8") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    d = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if d.get(key) in drop_keys:
                    continue
                kept.append(line)
    with path.open("w", encoding="utf-8") as f:
        for line in kept:
            f.write(line + "\n")
        for line in new_lines:
            f.write(line + "\n")


def write_deck_manifest(data_dir: str | Path, *, n_cards: int, generated_at: str | None = None) -> Path:
    base = Path(data_dir).expanduser().resolve()
    manifest_path = base / "ctkr" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    merged = {
        **existing,
        "metacoding_data_dir": str(base),
        "subsystem_cards": True,
        "n_subsystem_cards": int(n_cards),
    }
    if generated_at:
        merged["generated_at"] = generated_at
    manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return manifest_path


def _read_manifest(ctkr_dir: Path) -> dict:
    p = ctkr_dir / "manifest.json"
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return {}


def _find_fts(data_dir: Path) -> Path | None:
    for cand in (data_dir / "tokens.fts.sqlite", data_dir / "ctkr" / "tokens.fts.sqlite"):
        if cand.exists():
            return cand
    return None


__all__ = [
    "DEFAULT_MODEL",
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_TEMPERATURE",
    "SpecLabeler",
    "DeckStats",
    "build_deck",
    "detect_role_dissonance",
    "name_tokens",
    "harvest_fts",
    "spec_pattern_id",
    "merge_patterns_jsonl",
    "merge_evidence_jsonl",
    "write_deck_manifest",
]

