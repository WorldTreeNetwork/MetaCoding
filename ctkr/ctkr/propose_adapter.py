"""``ctkr propose-adapter`` core — synthesize a port adapter CONTRACT.

Bead MetaCoding-9h5.15 (second-opinion T1). Every prior port experiment presupposed
a *hand-authored* adapter signature surface (``ADAPTER_SIGNATURES.md``) — the mutator
+ projection interface a blind builder ports against. Authoring it is the hardest
cognitive act in the port: someone who understood the source decided the read surface
(``currentLocations(at)``, ``assetsAtLocation(at)`` …) and the event surface
(``recordMovement`` …), inventing concepts a value-equivalent port must expose that no
single source method names.

This module asks whether the *pipeline* can PROPOSE that surface. Given deterministic
pipeline artifacts for a scoped feature —

* **subsystem members / roles** — the in-scope class/interface inventory + method
  signatures the graph carries (:func:`extract_subsystem_members`);
* **mined fixture candidates** — the non-obvious value semantics ``ctkr mine-fixtures``
  surfaced (what a port must get right);
* **the target profile** — the local-first / event-log architecture and its
  consistency-model decision menu;
* optional **glossary / intent** text —

it builds one deterministic synthesis prompt (:func:`build_contract_prompt`) and asks a
strong model (default ``gpt-5.6-terra``) for a structured :class:`AdapterContract`:
typed mutators + projections, each tagged with whether it is as-of-time parameterized,
its one-line behavioral contract, and what source concept it derives from (or that it
is invented). Structured output + one repair retry (via :class:`ctkr.llm.LLMClient`).

Blindness (the experiment's whole point): the inputs assembled here are pipeline
artifacts + scoped SOURCE only. The generation path never reads a reference signature
surface, a prior builder's output, or a fixtures pack. The caller is responsible for
keeping those out of the ``--glossary`` / artifact paths it passes.
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

# --------------------------------------------------------------------------- #
# Output schema — the proposed adapter contract                               #
# --------------------------------------------------------------------------- #


class AdapterParam(BaseModel):
    """One typed parameter of a proposed adapter method."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Parameter name in the target language.")
    type: str = Field(description="Target-language type, e.g. 'Handle', 'number', 'string[]'.")
    optional: bool = Field(default=False, description="True if the parameter is optional.")


class AdapterMethod(BaseModel):
    """One proposed method of the adapter surface (a mutator or a projection)."""

    model_config = ConfigDict(extra="forbid")

    name: str = Field(description="Method name on the adapter, target-language convention.")
    kind: Literal["mutator", "projection"] = Field(
        description="'mutator' appends an event to the log; 'projection' is a read over it."
    )
    params: list[AdapterParam] = Field(default_factory=list)
    returns: str = Field(description="Target-language return type (Promise-wrapped is fine).")
    as_of_time: bool = Field(
        default=False,
        description="True if the read is parameterized by an as-of query timestamp "
        "(projections whose value changes over event time). Mutators are false.",
    )
    semantics: str = Field(
        description="One-line observable behavioral contract — the value rule the port "
        "must reproduce (e.g. 'latest done movement at-or-before t; [] if fixed')."
    )
    derived_from: str = Field(
        default="",
        description="The source method/concept this derives from (e.g. "
        "'AssetLocation::getLocation'), or 'invented: <why>' when no single source "
        "method names it (a concept the port surface must expose that source does not).",
    )


class AdapterContract(BaseModel):
    """The proposed adapter contract for one feature."""

    model_config = ConfigDict(extra="forbid")

    adapter_name: str = Field(description="The adapter type name, e.g. 'LocationAdapter'.")
    factory_signature: str = Field(
        description="The factory the builder implements, e.g. 'makeAdapter(): LocationAdapter'."
    )
    mutators: list[AdapterMethod] = Field(default_factory=list)
    projections: list[AdapterMethod] = Field(default_factory=list)
    rationale: str = Field(
        default="",
        description="Brief: how the surface was decomposed into events vs reads, and which "
        "fixture candidates drove which method.",
    )


# --------------------------------------------------------------------------- #
# Deterministic pipeline-artifact extraction (graph + scoped source)          #
# --------------------------------------------------------------------------- #


class SubsystemMethod(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    signature: str = ""
    visibility: str = ""


class SubsystemMember(BaseModel):
    """A role/member of the scoped subsystem (a class or interface)."""

    model_config = ConfigDict(extra="forbid")

    kind: str  # class | interface
    name: str
    file: str
    is_interface: bool = False
    methods: list[SubsystemMethod] = Field(default_factory=list)


def _in_scope(file_path: str, prefixes: Sequence[str]) -> bool:
    return any(p in file_path for p in prefixes)


def _canon_path(file_path: str, prefixes: Sequence[str]) -> str:
    """Canonicalize a duplicated source path to a scope-relative tail so the two
    copies farmOS ships (``core/location/...`` and ``modules/core/location/...``,
    graph-as-tool §4 duplication) collapse to one member."""
    for p in prefixes:
        idx = file_path.find(p)
        if idx != -1:
            return file_path[idx:]
    return file_path


def extract_subsystem_members(
    g: Any,
    *,
    scope_prefixes: Sequence[str],
    include_tests: bool = False,
    public_only: bool = True,
) -> list[SubsystemMember]:
    """Extract the in-scope class/interface members + their method signatures from a
    loaded graph, de-duplicating farmOS's compiled/source path duplication.

    This is the *roles / subsystem-members* pipeline artifact: what the port must
    re-express, named as the source named it, with the method signatures the graph
    carries. LM-free and deterministic."""
    # 1. Bucket in-scope class/interface nodes by canonical path.
    members: dict[str, SubsystemMember] = {}
    canon_by_file: dict[str, str] = {}
    for _n, d in g.nodes(data=True):
        fp = str(d.get("file", "") or "")
        if not _in_scope(fp, scope_prefixes):
            continue
        low = fp.lower()
        if not include_tests and ("/tests/" in low or "/test/" in low):
            continue
        kind = d.get("kind")
        if kind not in ("class", "interface"):
            continue
        short = str(d.get("short_name") or d.get("qualified_name") or "")
        if not short:
            continue
        canon = _canon_path(fp, scope_prefixes)
        canon_by_file[fp] = canon
        if canon not in members:
            members[canon] = SubsystemMember(
                kind=str(kind), name=short, file=canon, is_interface=(kind == "interface")
            )

    # 2. Attach method signatures (method nodes grouped by canonical file).
    seen_methods: dict[str, set[str]] = {c: set() for c in members}
    for _n, d in g.nodes(data=True):
        if d.get("kind") != "method":
            continue
        fp = str(d.get("file", "") or "")
        if not _in_scope(fp, scope_prefixes):
            continue
        canon = _canon_path(fp, scope_prefixes)
        member = members.get(canon)
        if member is None:
            continue
        name = str(d.get("short_name") or "")
        if not name or name in seen_methods[canon]:
            continue
        vis = str(d.get("visibility") or "")
        if public_only and vis not in ("", "public"):
            continue
        seen_methods[canon].add(name)
        member.methods.append(
            SubsystemMethod(
                name=name, signature=str(d.get("signature") or ""), visibility=vis
            )
        )

    # Interfaces first (they name the role surface), then by name.
    return sorted(members.values(), key=lambda m: (not m.is_interface, m.name))


# --------------------------------------------------------------------------- #
# Prompt assembly + synthesis                                                 #
# --------------------------------------------------------------------------- #

CONTRACT_SYS = (
    "You are designing the ADAPTER CONTRACT for porting ONE feature of a legacy "
    "record-keeping system to a new LOCAL-FIRST, eventually-consistent runtime. The "
    "target's state is an append-only EVENT LOG; every read is a materialized VIEW "
    "projected over that log, evaluated AS OF a query timestamp.\n\n"
    "The contract is the typed interface a blind builder will implement — split into:\n"
    "  * MUTATORS — the events that change state (append to the log). Name the domain "
    "events, not CRUD; a mutator returns a handle to what it created.\n"
    "  * PROJECTIONS — the reads over the log. A projection whose value depends on WHEN "
    "you ask (because later events supersede earlier ones) MUST take an as-of timestamp "
    "and set as_of_time=true.\n\n"
    "You are given: the subsystem's source members/roles and their method signatures; the "
    "mined non-obvious value semantics a port must get right (fixture candidates); the "
    "target profile; and optional glossary. Design the SMALLEST contract that lets a "
    "builder reproduce every mined semantic. Some methods will echo a source method; "
    "others are concepts the port surface must expose that NO single source method names "
    "(e.g. a value the source computes inline, or an event the source models as a generic "
    "write) — mark those 'invented: <why>' in derived_from. Prefer handles (opaque ids) "
    "over entity objects. Do NOT invent unrelated features; stay within this feature."
)


def _fmt_members(members: Sequence[SubsystemMember], *, max_methods: int = 30) -> str:
    lines: list[str] = []
    for m in members:
        tag = "interface" if m.is_interface else "class"
        lines.append(f"- {tag} {m.name}  ({m.file})")
        for meth in m.methods[:max_methods]:
            sig = meth.signature.strip() or meth.name
            lines.append(f"    · {sig}")
    return "\n".join(lines) if lines else "(none extracted)"


def _fmt_candidates(candidates: Sequence[Mapping[str, Any]], *, top: int = 24) -> str:
    # Rank-sorted if a rank_score is present; keep the most load-bearing.
    cs = list(candidates)
    cs.sort(key=lambda c: -float(c.get("rank_score", 0.0)))
    lines: list[str] = []
    for c in cs[:top]:
        title = str(c.get("title", "")).strip()
        why = str(c.get("why_non_obvious", "")).strip()
        scen = c.get("scenario") or {}
        then = scen.get("then") if isinstance(scen, Mapping) else None
        lines.append(f"- {title}")
        if why:
            lines.append(f"    why non-obvious: {why[:220]}")
        if then:
            lines.append(f"    observed: {'; '.join(str(t) for t in then)[:220]}")
    return "\n".join(lines) if lines else "(no fixture candidates provided)"


def build_contract_prompt(
    *,
    feature_name: str,
    members: Sequence[SubsystemMember],
    fixture_candidates: Sequence[Mapping[str, Any]],
    target_profile_text: str,
    glossary_text: str = "",
    target_language: str = "TypeScript",
) -> str:
    """Assemble the deterministic synthesis prompt. Pure function of its inputs —
    the same artifacts always produce the same prompt (so the LLM cache keys stably)."""
    parts: list[str] = [
        f"# Feature to port: {feature_name}",
        f"# Target language for the contract: {target_language}",
        "",
        "## Subsystem members / roles (source inventory + signatures)",
        _fmt_members(members),
        "",
        "## Mined non-obvious value semantics (fixture candidates the port must satisfy)",
        _fmt_candidates(fixture_candidates),
        "",
        "## Target profile (local-first architecture + consistency-model menu)",
        target_profile_text.strip(),
    ]
    if glossary_text.strip():
        parts += ["", "## Domain glossary / intent", glossary_text.strip()]
    parts += [
        "",
        "## Task",
        "Propose the adapter contract: an AdapterContract with typed mutators + "
        "projections. For EACH method give typed params, a return type, whether it is "
        "as-of-time parameterized, a one-line behavioral `semantics`, and `derived_from` "
        "(a source method, or 'invented: <why>'). Cover every mined semantic. Keep it "
        "minimal and faithful to the target profile's event-log model.",
    ]
    return "\n".join(parts)


def synthesize_contract(
    prompt: str,
    client: Any,
    *,
    model: str,
    provider: str | None = None,
    system: str = CONTRACT_SYS,
    max_tokens: int = 6000,
    reasoning_effort: str | None = None,
) -> tuple[AdapterContract, float]:
    """One structured synthesis call (with repair retry). Returns
    ``(contract, cost_estimate_usd)``."""
    res = client.complete_structured(
        prompt,
        schema=AdapterContract,
        model=model,
        provider=provider,
        system=system,
        max_tokens=max_tokens,
        reasoning_effort=reasoning_effort,
        repair=True,
    )
    return res.parsed, float(res.cost_estimate_usd)


# --------------------------------------------------------------------------- #
# Rendering                                                                   #
# --------------------------------------------------------------------------- #


def _ts_params(params: Sequence[AdapterParam]) -> str:
    return ", ".join(
        f"{p.name}{'?' if p.optional else ''}: {p.type}" for p in params
    )


def render_contract_markdown(contract: AdapterContract, *, feature_name: str = "") -> str:
    """Render the proposed contract as an ADAPTER_SIGNATURES-style markdown doc a blind
    builder can port against (a TypeScript interface + a per-method semantics table)."""
    lines: list[str] = [
        f"# Proposed adapter contract — {feature_name or contract.adapter_name}",
        "",
        "> Generated by `ctkr propose-adapter` from pipeline artifacts + scoped source.",
        "> Mutators append events to the log; projections read over it, as-of a timestamp.",
        "",
        "```typescript",
        f"export interface {contract.adapter_name} {{",
    ]
    for m in [*contract.mutators, *contract.projections]:
        lines.append(f"  {m.name}({_ts_params(m.params)}): {m.returns};")
    lines += ["}", "", f"export function {contract.factory_signature.rstrip(';')};", "```", ""]

    lines += ["## Methods", "", "| method | kind | as-of | semantics | derived_from |",
              "|---|---|---|---|---|"]
    for m in [*contract.mutators, *contract.projections]:
        sem = m.semantics.replace("|", "\\|")
        dfrom = m.derived_from.replace("|", "\\|")
        lines.append(
            f"| `{m.name}` | {m.kind} | {'yes' if m.as_of_time else 'no'} | {sem} | {dfrom} |"
        )
    if contract.rationale.strip():
        lines += ["", "## Rationale", "", contract.rationale.strip()]
    return "\n".join(lines) + "\n"


def load_fixture_candidates(path: str | Path) -> list[dict[str, Any]]:
    """Load a ``fixture_candidates.jsonl`` (mine-fixtures output). Tolerates blank lines."""
    out: list[dict[str, Any]] = []
    p = Path(path)
    for line in p.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line:
            out.append(json.loads(line))
    return out


__all__ = [
    "AdapterContract",
    "AdapterMethod",
    "AdapterParam",
    "SubsystemMember",
    "SubsystemMethod",
    "CONTRACT_SYS",
    "build_contract_prompt",
    "extract_subsystem_members",
    "synthesize_contract",
    "render_contract_markdown",
    "load_fixture_candidates",
]
