"""Semantic-fixture schema, JSONL IO, and validator (port-loop Phase 2, D4).

A **semantic fixture** is a value-level given/when/then scenario in domain-
glossary terms. It states *what value the system delivers*, never *how it is
stored* — the discipline of ``decomposition-schema.md`` §5. The port's data
model (event log + materialized views) is free to differ everywhere below the
line the fixture draws; a fixture that mentions a table, column, id, or storage
primitive is a **defect** the storage-leak lint rejects.

The three clauses:

* ``given`` — domain-state setup: instantiate entities (assets/groups) and bind
  each to a **logical alias** (``"A"``). No ids; the adapter mints real
  identities at run time and the fixture never sees them.
* ``when`` — actions in glossary verbs (``record_log``, ``set_log_status``,
  ``assign_to_group``, ``archive_asset``), referencing entities by alias.
* ``then`` — assertions on **values**: totals, statuses, counts, visibilities,
  memberships, recorded quantities — every one an observable the oracle can read
  back through *any* implementation's adapter.

Each fixture carries ``provenance`` (which live observation produced it) and the
``glossary_terms`` it uses. ``fixture_id`` is a content hash over the scenario
body (excluding provenance timestamps) so re-distilling the same flow is stable.

This module is pure data + validation — no HTTP, no farmOS. The tests exercise
it with canned dicts (no Docker).
"""

from __future__ import annotations

import json
import re
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from blake3 import blake3
from pydantic import BaseModel, ConfigDict, Field

from ctkr.oracle import glossary

SCHEMA_VERSION: int = 1


# --------------------------------------------------------------------------- #
# Row-level models                                                            #
# --------------------------------------------------------------------------- #
class QuantitySpec(BaseModel):
    """A measured quantity recorded on a log — value level, unit by name.

    ``value`` is a plain number (the delivered magnitude); ``unit`` is a domain
    unit name (``"kilogram"``) the adapter resolves to whatever unit primitive
    the implementation uses. ``label`` is a glossary role for the measurement
    (``"yield"``), not a field name.
    """

    model_config = ConfigDict(extra="forbid")

    measure: str  # one of glossary.MEASURES
    value: float
    unit: str  # domain unit name, e.g. "kilogram", "head", "liter"
    label: str = ""  # glossary role, e.g. "yield" (free text, storage-free)


class GivenStep(BaseModel):
    """Instantiate a domain entity and bind it to a logical alias."""

    model_config = ConfigDict(extra="forbid")

    entity: str  # one of glossary.ENTITY_TERMS
    alias: str  # logical handle, unique within the fixture ("A")
    name: str  # domain display name ("North Field")
    descriptor: str = ""  # optional domain sub-classification ("paddock"); adapter maps
    sex: str = ""  # optional domain trait; one of glossary.ANIMAL_SEXES


class WhenStep(BaseModel):
    """A domain action. Fields used depend on ``action`` (validated below)."""

    model_config = ConfigDict(extra="forbid")

    action: str  # one of glossary.ACTION_TERMS
    alias: str = ""  # handle bound to the thing this action creates (record_log)
    ref: str = ""  # handle of an existing entity the action targets
    name: str = ""  # display name for a created log
    kind: str = ""  # log kind (record_log): one of glossary.LOG_KINDS
    # record_inventory_adjustment: one of glossary.ADJUSTMENT_KINDS
    status: str = ""  # log status (record_log / set_log_status)
    against: list[str] = Field(default_factory=list)  # asset aliases a log references
    group: str = ""  # group alias (assign_to_group)
    quantities: list[QuantitySpec] = Field(default_factory=list)
    # --- effective time -----------------------------------------------------
    # WHEN the recorded event took effect. Two accepted forms, both inputs (never
    # an expected value): an absolute ISO-8601 instant ("2026-03-01T12:00:00+00:00")
    # or a signed offset in seconds relative to the moment the flow runs
    # ("-3600", "+86400"). The relative form is what makes "an event dated in the
    # future does not count yet" reproducible on every re-run.
    at: str = ""
    # --- lineage ------------------------------------------------------------
    parents: list[str] = Field(default_factory=list)  # aliases of parent animals
    names: list[str] = Field(default_factory=list)  # ordered informal names


class ThenAssertion(BaseModel):
    """A value-level assertion. Fields used depend on ``assert_`` (validated)."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    # `assert` is a Python keyword; accept it from JSON via alias.
    assert_: str = Field(alias="assert")  # one of glossary.ASSERTION_TERMS
    subject: str  # handle the assertion is about
    measure: str = ""  # yield_total / quantity_recorded
    unit: str = ""  # yield_total / quantity_recorded
    kind: str = ""  # log_count
    group: str = ""  # group_member
    other: str = ""  # second entity alias (has_parent)
    op: str = "=="  # one of glossary.COMPARISON_OPS
    value: Any = None  # expected value (number | bool | status string)

    def dump_aliased(self) -> dict[str, Any]:
        """Serialize with the JSON ``assert`` key (round-trips through JSONL)."""
        return self.model_dump(by_alias=True, exclude_none=False)


class Provenance(BaseModel):
    """Where a fixture came from — the live observation that produced it."""

    model_config = ConfigDict(extra="forbid")

    source_system: str  # e.g. "farmOS"
    source_version: str = ""  # e.g. "4.x"
    flow: str = ""  # the recorded value-flow this fixture was distilled from
    recorded_at: str = ""  # ISO-8601 of the recording session (not hashed)
    observation_refs: list[str] = Field(default_factory=list)  # recorded-obs ids

    #: Whether this fixture's VALUE may be used to score an implementation
    #: (MetaCoding-bdy / blocker B4). `"scoring"` is the default. A fixture is
    #: `"corroboration-only"` when its observed value is an artifact of how the
    #: SOURCE happened to order things rather than a semantic any correct port
    #: must reproduce — w0a's three same-instant adjustments observed 3.0, which
    #: is farmOS's insertion-id order fingerprint (six permutations of the same
    #: events give four different values). Scoring a port against it is a false
    #: green under one replica ordering and a false failure under another.
    #:
    #: This travels WITH the pack, where the recorder can set it from what it
    #: saw, rather than only in a caller-supplied side file that a reader may
    #: never see.
    evidence_class: str = "scoring"  # "scoring" | "corroboration-only"
    #: Why, when the class is not "scoring". Excluding evidence costs a reason.
    evidence_note: str = ""


class SemanticFixture(BaseModel):
    """One value-level given/when/then scenario (D4), storage-free by rule."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    fixture_id: str = ""  # blake3 over the scenario body; filled by content_id()
    title: str
    feature: str = ""  # glossary feature/flow name this scenario rolls up to
    glossary_terms: list[str] = Field(default_factory=list)
    given: list[GivenStep] = Field(default_factory=list)
    when: list[WhenStep] = Field(default_factory=list)
    then: list[ThenAssertion] = Field(default_factory=list)
    provenance: Provenance
    schema_version: int = SCHEMA_VERSION

    # ---- content addressing ------------------------------------------------ #
    def _body_for_hash(self) -> dict[str, Any]:
        return {
            "title": self.title,
            "feature": self.feature,
            "glossary_terms": sorted(self.glossary_terms),
            "given": [g.model_dump() for g in self.given],
            "when": [w.model_dump() for w in self.when],
            "then": [t.dump_aliased() for t in self.then],
            "schema_version": self.schema_version,
        }

    def content_id(self) -> str:
        """Deterministic id from the scenario body (provenance excluded)."""
        canonical = json.dumps(self._body_for_hash(), sort_keys=True, default=str)
        return blake3(canonical.encode("utf-8")).hexdigest()[:32]

    def with_id(self) -> SemanticFixture:
        """Return a copy with ``fixture_id`` set to the content hash."""
        return self.model_copy(update={"fixture_id": self.content_id()})

    def to_jsonl_dict(self) -> dict[str, Any]:
        d = self.model_dump()
        # Re-key the assert alias for the on-disk form.
        d["then"] = [t.dump_aliased() for t in self.then]
        return d


# --------------------------------------------------------------------------- #
# JSONL IO                                                                     #
# --------------------------------------------------------------------------- #
def load_fixtures(path: str | Path) -> list[SemanticFixture]:
    """Read a semantic-fixture JSONL file into models (order preserved)."""
    fixtures: list[SemanticFixture] = []
    with Path(path).open("r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, start=1):
            line = line.strip()
            if not line:
                continue
            try:
                fixtures.append(SemanticFixture.model_validate_json(line))
            except Exception as exc:  # noqa: BLE001 — surface the line number
                raise ValueError(f"{path}:{lineno}: {exc}") from exc
    return fixtures


def write_fixtures(fixtures: Iterable[SemanticFixture], path: str | Path) -> int:
    """Write fixtures as JSONL (one per line), filling ``fixture_id``. Returns n."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    n = 0
    with p.open("w", encoding="utf-8") as fh:
        for fx in fixtures:
            fx = fx.with_id() if not fx.fixture_id else fx
            fh.write(json.dumps(fx.to_jsonl_dict(), default=str) + "\n")
            n += 1
    return n


# --------------------------------------------------------------------------- #
# Validation                                                                  #
# --------------------------------------------------------------------------- #
class ValidationIssue(BaseModel):
    """One problem found by :func:`validate_fixture` — a hard error or a lint."""

    fixture_id: str
    severity: str  # "error" | "leak"
    where: str  # clause/step locator, e.g. "when[1].kind"
    message: str


def _iter_string_values(obj: Any, prefix: str) -> Iterator[tuple[str, str]]:
    """Yield ``(path, string)`` for every string VALUE (not dict keys)."""
    if isinstance(obj, str):
        yield prefix, obj
    elif isinstance(obj, dict):
        for k, v in obj.items():
            yield from _iter_string_values(v, f"{prefix}.{k}")
    elif isinstance(obj, (list, tuple)):
        for i, v in enumerate(obj):
            yield from _iter_string_values(v, f"{prefix}[{i}]")


def storage_leaks(fx: SemanticFixture) -> list[ValidationIssue]:
    """Reject any string value that smuggles a data model across the line (§5).

    Scans the *scenario body* (given/when/then/title/feature/glossary_terms) —
    not ``provenance`` (which legitimately names the source system). Both the
    substring blacklist and the whole-word blacklist from the glossary apply.
    """
    issues: list[ValidationIssue] = []
    body = {
        "title": fx.title,
        "feature": fx.feature,
        "glossary_terms": fx.glossary_terms,
        "given": [g.model_dump() for g in fx.given],
        "when": [w.model_dump() for w in fx.when],
        "then": [t.dump_aliased() for t in fx.then],
    }
    for path, s in _iter_string_values(body, "fixture"):
        low = s.lower()
        for bad in glossary.FORBIDDEN_SUBSTRINGS:
            if bad in low:
                issues.append(
                    ValidationIssue(
                        fixture_id=fx.fixture_id or fx.content_id(),
                        severity="leak",
                        where=path,
                        message=f"representation term {bad!r} leaked in value {s!r}",
                    )
                )
        words = {w.strip(".,;:!?()[]{}\"'").lower() for w in s.split()}
        for bad in glossary.FORBIDDEN_WORDS & words:
            issues.append(
                ValidationIssue(
                    fixture_id=fx.fixture_id or fx.content_id(),
                    severity="leak",
                    where=path,
                    message=f"storage word {bad!r} leaked in value {s!r}",
                )
            )
    return issues


# --------------------------------------------------------------------------- #
# Effective time                                                              #
# --------------------------------------------------------------------------- #
_OFFSET_RE = re.compile(r"^[+-]\d+$")


def _is_effective_time(at: str) -> bool:
    """True if ``at`` is a legal effective-time input (instant OR signed offset)."""
    if _OFFSET_RE.match(at):
        return True
    try:
        datetime.fromisoformat(at)
    except ValueError:
        return False
    return True


def resolve_effective_time(at: str, now: datetime | None = None) -> datetime:
    """Resolve an effective-time input to an absolute instant.

    A signed integer string is an offset in seconds from ``now`` (the moment the
    flow runs) — that relativity is what lets a flow say "dated in the future"
    or "dated in the past" reproducibly on every re-run. Anything else must be
    an ISO-8601 instant. This is an INPUT resolution only: no observed value
    ever passes through here.
    """
    now = now or datetime.now(UTC)
    if _OFFSET_RE.match(at):
        return now + timedelta(seconds=int(at))
    parsed = datetime.fromisoformat(at)
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


# Required fields per action / assertion — the DSL contract the runner relies on.
_ACTION_REQUIRED: dict[str, tuple[str, ...]] = {
    "record_log": ("alias", "kind"),
    "set_log_status": ("ref", "status"),
    "assign_to_group": ("ref", "group"),
    "archive_asset": ("ref",),
    "record_inventory_adjustment": ("alias", "kind", "against", "quantities"),
    "set_effective_time": ("ref", "at"),
    "record_birth": ("alias", "ref"),
    "correct_birth": ("ref",),
    "set_parents": ("ref",),
    "set_nicknames": ("ref",),
}
_ASSERT_REQUIRED: dict[str, tuple[str, ...]] = {
    "yield_total": ("measure", "value"),
    "log_status": ("value",),
    "log_count": ("kind", "value"),
    "asset_active": ("value",),
    "group_member": ("group", "value"),
    "quantity_recorded": ("measure", "value"),
    "stock_on_hand": ("measure", "value"),
    "stock_pair_count": ("value",),
    "adjustment_count": ("value",),
    "animal_sex": ("value",),
    "nicknames": ("value",),
    "birth_date": ("value",),
    "parent_count": ("value",),
    "has_parent": ("other", "value"),
    "birth_record_count": ("value",),
}

#: Which actions bind ``alias`` to a *log* handle (as opposed to an asset).
_LOG_PRODUCING_ACTIONS: frozenset[str] = frozenset(
    {"record_log", "record_inventory_adjustment", "record_birth"}
)


def validate_fixture(fx: SemanticFixture) -> list[ValidationIssue]:
    """Full validation: term legality, alias resolution, per-step required fields,
    and the storage-leak lint. Returns every issue found (empty == valid)."""
    fid = fx.fixture_id or fx.content_id()
    issues: list[ValidationIssue] = []

    def err(where: str, msg: str) -> None:
        issues.append(
            ValidationIssue(fixture_id=fid, severity="error", where=where, message=msg)
        )

    # --- given: entity terms legal, aliases unique --------------------------
    aliases: dict[str, str] = {}  # alias -> entity term
    for i, g in enumerate(fx.given):
        if g.entity not in glossary.ENTITY_TERMS:
            err(f"given[{i}].entity", f"{g.entity!r} is not a glossary entity term")
        if not g.alias:
            err(f"given[{i}].alias", "alias is required")
        elif g.alias in aliases:
            err(f"given[{i}].alias", f"duplicate alias {g.alias!r}")
        else:
            aliases[g.alias] = g.entity
        if g.sex and g.sex not in glossary.ANIMAL_SEXES:
            err(f"given[{i}].sex", f"{g.sex!r} is not a glossary animal sex")

    # --- when: action terms legal, refs resolve, required fields present ----
    log_aliases: set[str] = set()
    for i, w in enumerate(fx.when):
        if w.action not in glossary.ACTION_TERMS:
            err(f"when[{i}].action", f"{w.action!r} is not a glossary action term")
            continue
        for req in _ACTION_REQUIRED.get(w.action, ()):
            if not getattr(w, req):
                err(f"when[{i}].{req}", f"{w.action} requires {req!r}")
        if w.action == "record_log":
            if w.kind and w.kind not in glossary.LOG_KINDS:
                err(f"when[{i}].kind", f"{w.kind!r} is not a glossary log kind")
            if w.status and w.status not in glossary.LOG_STATUSES:
                err(f"when[{i}].status", f"{w.status!r} is not a glossary log status")
            for j, a in enumerate(w.against):
                if a not in aliases:
                    err(f"when[{i}].against[{j}]", f"unknown asset alias {a!r}")
            for j, q in enumerate(w.quantities):
                if q.measure not in glossary.MEASURES:
                    err(f"when[{i}].quantities[{j}].measure",
                        f"{q.measure!r} is not a glossary measure")
            if w.alias:
                log_aliases.add(w.alias)
        elif w.action == "set_log_status":
            if w.ref and w.ref not in log_aliases:
                err(f"when[{i}].ref", f"set_log_status ref {w.ref!r} is not a log alias")
            if w.status and w.status not in glossary.LOG_STATUSES:
                err(f"when[{i}].status", f"{w.status!r} is not a glossary log status")
        elif w.action == "assign_to_group":
            if w.ref and w.ref not in aliases:
                err(f"when[{i}].ref", f"unknown asset alias {w.ref!r}")
            if w.group and w.group not in aliases:
                err(f"when[{i}].group", f"unknown group alias {w.group!r}")
        elif w.action == "archive_asset":
            if w.ref and w.ref not in aliases:
                err(f"when[{i}].ref", f"unknown asset alias {w.ref!r}")
        elif w.action == "record_inventory_adjustment":
            if w.kind and w.kind not in glossary.ADJUSTMENT_KINDS:
                err(f"when[{i}].kind",
                    f"{w.kind!r} is not a glossary stock adjustment kind")
            if w.status and w.status not in glossary.LOG_STATUSES:
                err(f"when[{i}].status", f"{w.status!r} is not a glossary log status")
            for j, a in enumerate(w.against):
                if a not in aliases:
                    err(f"when[{i}].against[{j}]", f"unknown asset alias {a!r}")
            for j, q in enumerate(w.quantities):
                if q.measure not in glossary.MEASURES:
                    err(f"when[{i}].quantities[{j}].measure",
                        f"{q.measure!r} is not a glossary measure")
            if w.alias:
                log_aliases.add(w.alias)
        elif w.action == "set_effective_time":
            if w.ref and w.ref not in log_aliases:
                err(f"when[{i}].ref",
                    f"set_effective_time ref {w.ref!r} is not a recorded-event alias")
            if w.at and not _is_effective_time(w.at):
                err(f"when[{i}].at", f"{w.at!r} is neither an instant nor an offset")
        elif w.action == "record_birth":
            if w.ref and w.ref not in aliases:
                err(f"when[{i}].ref", f"unknown animal alias {w.ref!r}")
            for j, p in enumerate(w.parents):
                if p not in aliases:
                    err(f"when[{i}].parents[{j}]", f"unknown animal alias {p!r}")
            if w.status and w.status not in glossary.LOG_STATUSES:
                err(f"when[{i}].status", f"{w.status!r} is not a glossary log status")
            if w.at and not _is_effective_time(w.at):
                err(f"when[{i}].at", f"{w.at!r} is neither an instant nor an offset")
            if w.alias:
                log_aliases.add(w.alias)
        elif w.action == "correct_birth":
            if w.ref and w.ref not in log_aliases:
                err(f"when[{i}].ref",
                    f"correct_birth ref {w.ref!r} is not a recorded-birth alias")
            for j, p in enumerate(w.parents):
                if p not in aliases:
                    err(f"when[{i}].parents[{j}]", f"unknown animal alias {p!r}")
            if w.at and not _is_effective_time(w.at):
                err(f"when[{i}].at", f"{w.at!r} is neither an instant nor an offset")
        elif w.action == "set_parents":
            if w.ref and w.ref not in aliases:
                err(f"when[{i}].ref", f"unknown animal alias {w.ref!r}")
            for j, p in enumerate(w.parents):
                if p not in aliases:
                    err(f"when[{i}].parents[{j}]", f"unknown animal alias {p!r}")
        elif w.action == "set_nicknames":
            if w.ref and w.ref not in aliases:
                err(f"when[{i}].ref", f"unknown animal alias {w.ref!r}")

    # --- then: assertion terms legal, subjects resolve, required fields -----
    known = set(aliases) | log_aliases
    for i, t in enumerate(fx.then):
        if t.assert_ not in glossary.ASSERTION_TERMS:
            err(f"then[{i}].assert", f"{t.assert_!r} is not a glossary assertion term")
            continue
        for req in _ASSERT_REQUIRED.get(t.assert_, ()):
            got = getattr(t, req)
            # `value` is the OBSERVED value. Absence is ``None``; "" / 0 / False /
            # [] are values the live system genuinely delivered and must survive
            # distillation intact (an animal with no sex reads back as "").
            missing = got is None if req == "value" else got in (None, "")
            if missing:
                err(f"then[{i}].{req}", f"{t.assert_} requires {req!r}")
        if t.subject and t.subject not in known:
            err(f"then[{i}].subject", f"unknown subject alias {t.subject!r}")
        if t.op not in glossary.COMPARISON_OPS:
            err(f"then[{i}].op", f"{t.op!r} is not a comparison operator")
        if t.assert_ == "group_member" and t.group and t.group not in aliases:
            err(f"then[{i}].group", f"unknown group alias {t.group!r}")
        if t.assert_ == "has_parent" and t.other and t.other not in aliases:
            err(f"then[{i}].other", f"unknown animal alias {t.other!r}")

    # --- declared glossary_terms are all legal ------------------------------
    for term in fx.glossary_terms:
        if term not in glossary.all_terms():
            err("glossary_terms", f"{term!r} is not in the domain glossary")

    # --- storage-leak lint --------------------------------------------------
    issues.extend(storage_leaks(fx))
    return issues
