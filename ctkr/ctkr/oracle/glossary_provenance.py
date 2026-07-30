"""The glossary binding gate — term provenance rows and the provisional→bound flip.

A term enters the glossary the way a decision enters the registry: **cited,
witnessed, reversible**. Three channels converge on one lexicon — structural
(CT mining proposes candidates), empirical (builder punts prove need),
observational (the oracle validates before a term binds) — and this module is
where the third channel becomes enforceable:

* every FUTURE glossary term gets a row in ``glossary_provenance.jsonl``
  (version-controlled, beside :mod:`ctkr.oracle.glossary` — the registry
  governs the in-repo lexicon, so it lives with the code it governs, the same
  way ``PACKS.jsonl`` lives above the packs it vouches for);
* a row is **PROVISIONAL** until a real sealed recording exercises the term's
  discriminating flow, at which point :func:`bind_term` fills
  ``first_pack_seal`` and flips the status to **bound**;
* a row claiming ``status=bound`` with no ``first_pack_seal`` is INVALID — the
  loader refuses the whole registry, loudly, because a registry that tolerates
  an unwitnessed binding is not a registry;
* a PROVISIONAL assertion term is excluded from scoring by ``port-verify``
  (:func:`provisional_reason`, consulted in ``_judge_assertion`` exactly where
  the ``is_evidence`` and corroboration-only gates already live). ``bind-term``
  is therefore the only path from a proposed term to a scorable one.

The 25 terms that predate this registry carry no rows and are grandfathered:
absence from the registry means "not provisional", never "not a term".

Input contract: **TERM-SPEC v1**, shared with ``ctkr propose-terms``::

    {"term": str, "kind": "entity"|"action"|"assertion", "description": str,
     "probe_semantics": str, "discriminating_flow": {<flow-DSL sketch>},
     "provenance": {"role_class_id": str|null, "config_source": str|null,
                    "punts": [str], "first_pack_seal": null}}

Two OPTIONAL keys (MetaCoding-td9) let an assertion spec declare its probe
shape instead of defaulting to a param-less entity probe — the default forced
every entity-reference assertion (the ``has_parent`` shape) to be hand-edited
across five files after generation::

    "subject_kind": "entity"|"event"|"attempt"|"quantity",  # default "entity"
    "params": [{"field_name": "other",            # a ThenAssertion field
                "alias_noun": "animal"}]          # non-empty = alias, resolved
                                                  # to a handle before the call

A third OPTIONAL key (MetaCoding-wob) shapes the generated PortAdapter dispatch
only — a ``"list"`` probe guards the wire shape and coerces to names, a scalar
(the default) forwards raw::

    "value_shape": "scalar"|"list",               # default "scalar"
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

#: The kinds a TERM-SPEC may declare (terms are named surfaces of the DSL).
TERM_KINDS: frozenset[str] = frozenset({"entity", "action", "assertion"})
#: A closed-set VALUE (MetaCoding-852): not a term — it names no probe, action,
#: or entity — but a member of a glossary enum (LOG_STATUSES, LAND_TYPES,
#: STRUCTURE_TYPES, …). Enum growth previously bound with commit-message
#: provenance only; these rows give it the same cited-witnessed-reversible bar.
ENUM_VALUE_KIND: str = "enum_value"
#: Every kind a REGISTRY ROW may carry.
KINDS: frozenset[str] = TERM_KINDS | {ENUM_VALUE_KIND}
STATUSES: frozenset[str] = frozenset({"provisional", "bound"})

#: The glossary enums under provenance governance, each with the members
#: GRANDFATHERED at governance time (the same rule the module keeps for the 25
#: pre-registry terms: absence means "predates the registry", never "invalid").
#: A governed set's NON-grandfathered member with no registry row is a
#: governance failure the test suite refuses — growing the set requires a row.
GOVERNED_SETS: dict[str, frozenset[str]] = {
    # 'pending'/'done' predate the registry; 'abandoned' was the io6 growth.
    "LOG_STATUSES": frozenset({"pending", "done"}),
    # blessed whole at io6 with commit-message provenance only — nothing
    # grandfathered, every member gets a row.
    "LAND_TYPES": frozenset(),
    # blessed at the structure port (MetaCoding-xq7), same gap.
    "STRUCTURE_TYPES": frozenset(),
}

#: The version-controlled registry, beside the glossary it governs.
DEFAULT_REGISTRY: Path = Path(__file__).with_name("glossary_provenance.jsonl")

_TERM_RE = re.compile(r"[a-z][a-z0-9_]*\Z")

_SPEC_KEYS = ("term", "kind", "description", "probe_semantics",
              "discriminating_flow", "provenance")

#: ThenAssertion fields a probe param may bind (fixtures.ThenAssertion is
#: ``extra="forbid"``, so a spec cannot invent a new wire field — it reuses one
#: of the closed set the flow DSL already carries).
PROBE_PARAM_FIELDS: frozenset[str] = frozenset(
    {"measure", "unit", "kind", "group", "other",
     # the as-of instant (MetaCoding-b0s). A probe that declares this param
     # asks about a MOMENT, not about now — a different question, and for
     # farmOS a differently-authorised one (no boundary as-of read exists, so
     # the answer is a fold of ours). Never an alias.
     "as_of"}
)
SUBJECT_KINDS: frozenset[str] = frozenset(
    {"entity", "event", "attempt",
     # a QUANTITY: one recorded measurement, addressable by the alias a
     # record_log step minted for it (MetaCoding-xdt gave it a write surface,
     # MetaCoding-b0s a read one). Not an `event` — a log is the event, and a
     # quantity is a thing the event records.
     "quantity"}
)
#: The port-adapter dispatch shape (MetaCoding-wob): a ``scalar`` value is
#: forwarded raw so a type mismatch surfaces as a real comparison; a ``list`` is
#: guarded (a non-list answer is a BridgeError, NO VERDICT) and coerced to names.
#: This shapes the generated PortAdapter method ONLY — every other stub is Any.
VALUE_SHAPES: frozenset[str] = frozenset({"scalar", "list"})


class ProvenanceError(RuntimeError):
    """The registry (or a spec) is not in a state that permits the operation."""


# --------------------------------------------------------------------------- #
# TERM-SPEC v1                                                                 #
# --------------------------------------------------------------------------- #
def validate_term_spec(spec: Any) -> list[str]:
    """Why this object is not a TERM-SPEC v1, as a list of problems (empty = valid)."""
    if not isinstance(spec, dict):
        return ["a TERM-SPEC is a JSON object"]
    problems = [f"missing key {k!r}" for k in _SPEC_KEYS if k not in spec]
    term = spec.get("term")
    if isinstance(term, str):
        if not _TERM_RE.match(term):
            problems.append(
                f"term {term!r} is not a lower_snake_case identifier"
            )
    elif "term" in spec:
        problems.append("term must be a string")
    if "kind" in spec and spec.get("kind") not in TERM_KINDS:
        problems.append(
            f"kind {spec.get('kind')!r} is not one of {sorted(TERM_KINDS)} "
            f"(an enum VALUE is not a term — it enters via add_enum_value)"
        )
    for k in ("description", "probe_semantics"):
        if k in spec and not (isinstance(spec[k], str) and spec[k].strip()):
            problems.append(f"{k} must be a non-empty string")
    if "discriminating_flow" in spec and not (
        isinstance(spec["discriminating_flow"], dict) and spec["discriminating_flow"]
    ):
        problems.append("discriminating_flow must be a non-empty flow-DSL sketch")
    if "subject_kind" in spec and spec["subject_kind"] not in SUBJECT_KINDS:
        problems.append(
            f"subject_kind {spec['subject_kind']!r} is not one of "
            f"{sorted(SUBJECT_KINDS)}"
        )
    if "value_shape" in spec:
        if spec.get("kind") != "assertion":
            problems.append("value_shape is only meaningful on an assertion spec")
        elif spec["value_shape"] not in VALUE_SHAPES:
            problems.append(
                f"value_shape {spec['value_shape']!r} is not one of "
                f"{sorted(VALUE_SHAPES)}"
            )
    if "params" in spec:
        params = spec["params"]
        if spec.get("kind") != "assertion":
            problems.append("params is only meaningful on an assertion spec")
        if not isinstance(params, list):
            problems.append("params must be a list of {field_name, alias_noun?}")
        else:
            seen_fields: set[str] = set()
            for i, p in enumerate(params):
                where = f"params[{i}]"
                if not isinstance(p, dict):
                    problems.append(f"{where}: not an object")
                    continue
                fname = p.get("field_name")
                if fname not in PROBE_PARAM_FIELDS:
                    problems.append(
                        f"{where}.field_name {fname!r} is not one of "
                        f"{sorted(PROBE_PARAM_FIELDS)} (ThenAssertion is a "
                        f"closed field set)"
                    )
                elif fname in seen_fields:
                    problems.append(f"{where}: duplicate field_name {fname!r}")
                else:
                    seen_fields.add(fname)
                if "alias_noun" in p and not isinstance(p["alias_noun"], str):
                    problems.append(f"{where}.alias_noun must be a string")
    prov = spec.get("provenance")
    if "provenance" in spec:
        if not isinstance(prov, dict):
            problems.append("provenance must be an object")
        else:
            if not isinstance(prov.get("punts", []), list):
                problems.append("provenance.punts must be a list")
            if prov.get("first_pack_seal"):
                problems.append(
                    "provenance.first_pack_seal must be null in a spec: a term "
                    "arrives PROVISIONAL, and only bind-term — against a real "
                    "sealed recording — fills the seal"
                )
    return problems


# --------------------------------------------------------------------------- #
# Registry rows                                                                #
# --------------------------------------------------------------------------- #
def _row_problems(row: Any, line_no: int, seen: set[str]) -> list[str]:
    where = f"row {line_no}"
    if not isinstance(row, dict):
        return [f"{where}: not an object"]
    problems: list[str] = []
    term = row.get("term")
    kind = row.get("kind")
    if not (isinstance(term, str) and _TERM_RE.match(term)):
        problems.append(f"{where}: term {term!r} is not a valid identifier")
    else:
        # Enum values live in a per-set namespace (the value "other" is a
        # member of LAND_TYPES and STRUCTURE_TYPES both); terms share one.
        key = f"{row.get('set')}:{term}" if kind == ENUM_VALUE_KIND else term
        if key in seen:
            problems.append(f"{where}: duplicate row for {key!r}")
        seen.add(key)
    if kind not in KINDS:
        problems.append(f"{where}: kind {kind!r} is not one of {sorted(KINDS)}")
    if kind == ENUM_VALUE_KIND:
        # MetaCoding-852: an enum row must name a real glossary set that
        # actually contains the value — a row for a value the glossary does
        # not carry is drift, refused at load.
        from ctkr.oracle import glossary as _glossary

        set_name = row.get("set")
        members = getattr(_glossary, str(set_name), None)
        if not isinstance(members, frozenset):
            problems.append(
                f"{where}: enum_value row names set {set_name!r}, which is "
                f"not a glossary frozenset"
            )
        elif term not in members:
            problems.append(
                f"{where}: enum_value {term!r} is not a member of "
                f"glossary.{set_name} — the glossary and its provenance "
                f"registry disagree"
            )
        if isinstance(prov := row.get("provenance"), dict) and not str(
            prov.get("config_source") or ""
        ).strip():
            problems.append(
                f"{where}: enum_value {term!r} has no config_source — the "
                f"channel exists precisely because commit-message-only "
                f"provenance was the gap (MetaCoding-852)"
            )
    elif "set" in row:
        problems.append(
            f"{where}: only an enum_value row may carry 'set' (kind={kind!r})"
        )
    status = row.get("status")
    if status not in STATUSES:
        problems.append(f"{where}: status {status!r} is not one of {sorted(STATUSES)}")
    prov = row.get("provenance")
    if not isinstance(prov, dict):
        problems.append(f"{where}: provenance must be an object")
        return problems
    seal = prov.get("first_pack_seal")
    if status == "bound" and not seal:
        problems.append(
            f"{where}: term {term!r} claims status=bound with no "
            f"first_pack_seal — a binding without a sealed recording is not a "
            f"binding. INVALID."
        )
    if status == "provisional" and seal:
        problems.append(
            f"{where}: term {term!r} is provisional yet carries first_pack_seal "
            f"{seal!r} — a filled seal IS the binding; the statuses cannot disagree"
        )
    return problems


def load_registry(path: str | Path | None = None) -> list[dict[str, Any]]:
    """Every provenance row, validated. A registry with an invalid row REFUSES to load.

    A missing file is an empty registry (a tree that has never added a term),
    never an error — but a present file must be wholly valid.
    """
    p = Path(path) if path is not None else DEFAULT_REGISTRY
    if not p.exists():
        return []
    rows: list[dict[str, Any]] = []
    problems: list[str] = []
    seen: set[str] = set()
    for i, line in enumerate(p.read_text(encoding="utf-8").splitlines(), start=1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except json.JSONDecodeError as exc:
            problems.append(f"row {i}: unreadable JSON ({exc})")
            continue
        problems.extend(_row_problems(row, i, seen))  # adds the row's dedup key
        rows.append(row)
    if problems:
        raise ProvenanceError(
            f"{p}: the provenance registry is INVALID and nothing may consult "
            f"it until it is repaired:\n  - " + "\n  - ".join(problems)
        )
    return rows


def _write_registry(rows: list[dict[str, Any]], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(
        "".join(json.dumps(r, sort_keys=True) + "\n" for r in rows),
        encoding="utf-8",
    )
    tmp.replace(path)


def provisional_terms(path: str | Path | None = None) -> frozenset[str]:
    """The terms no sealed pack has exercised yet (enum values excluded —
    they live in a per-set namespace and gate nothing port-verify scores)."""
    return frozenset(
        r["term"] for r in load_registry(path)
        if r["status"] == "provisional" and r["kind"] != ENUM_VALUE_KIND
    )


def provisional_reason(term: str, path: str | Path | None = None) -> str:
    """Why values asserting ``term`` may not score, or ``""`` when they may.

    Consulted by ``port-verify`` per assertion, mirroring the shape of
    ``ProbeSpec.unvalidated_reason``: a term whose discriminating flow no sealed
    recording has exercised states OUR proposal about the domain, not an
    observed semantic of the source. Comparing a port to it cannot produce
    evidence in either direction. Absence from the registry means the term
    predates it (or is no term at all — the probe contract catches that), so
    this returns ``""`` for every grandfathered term.
    """
    for row in load_registry(path):
        if row["kind"] == ENUM_VALUE_KIND:
            continue  # per-set namespace; never shadows a term name
        if row["term"] == term and row["status"] == "provisional":
            return (
                f"{term!r} is PROVISIONAL: no sealed pack has exercised its "
                f"discriminating flow, so its semantics are a proposal, not an "
                f"observation. Record it against the live source and run "
                f"`ctkr bind-term {term}`. NO VERDICT."
            )
    return ""


def add_provisional(
    spec: dict[str, Any], path: str | Path | None = None
) -> dict[str, Any]:
    """Append a PROVISIONAL row for a validated TERM-SPEC. Returns the row."""
    problems = validate_term_spec(spec)
    if problems:
        raise ProvenanceError(
            "not a TERM-SPEC v1:\n  - " + "\n  - ".join(problems)
        )
    p = Path(path) if path is not None else DEFAULT_REGISTRY
    rows = load_registry(p)
    term = spec["term"]
    term_rows = [r for r in rows if r["kind"] != ENUM_VALUE_KIND]
    if any(r["term"] == term for r in term_rows):
        existing = next(r for r in term_rows if r["term"] == term)
        raise ProvenanceError(
            f"term {term!r} already has a provenance row "
            f"(status={existing['status']}); a term is registered once"
        )
    prov = dict(spec["provenance"])
    prov.setdefault("role_class_id", None)
    prov.setdefault("config_source", None)
    prov.setdefault("punts", [])
    prov["first_pack_seal"] = None
    row = {
        "term": term,
        "kind": spec["kind"],
        "description": spec["description"],
        "probe_semantics": spec["probe_semantics"],
        "discriminating_flow": spec["discriminating_flow"],
        "provenance": prov,
        "status": "provisional",
        "registered_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_registry(rows + [row], p)
    return row


# --------------------------------------------------------------------------- #
# The gate: provisional -> bound                                               #
# --------------------------------------------------------------------------- #
def _exercises(fx: Any, term: str, kind: str) -> bool:
    """Whether one VALID fixture exercises the term, per its kind."""
    if kind == "entity":
        return any(g.entity == term for g in fx.given)
    if kind == "action":
        return any(w.action == term for w in fx.when)
    return any(t.assert_ == term for t in fx.then)


def bind_term(
    term: str,
    fixtures_path: str | Path,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Flip a term provisional→bound because a sealed pack exercised it.

    The only path to a scorable term. Verifies, in order:

    1. the term has a provenance row and it is provisional;
    2. an assertion term's ProbeSpec can actually SCORE (``is_evidence`` —
       BOUNDARY, or DERIVED with ``validated_against``); binding a term
       port-verify must exclude is refused as a skipped authority
       refinement (MetaCoding-e6p);
    3. the pack LOADS — seal present, digests match, witnesses agree, ledger
       vouches where one exists (:func:`ctkr.oracle.pack.load_pack`; a
       :class:`~ctkr.oracle.pack.PackError` propagates untouched);
    4. at least one fixture that SURVIVED loading (never one in the invalid
       bucket) exercises the term in the position its kind allows.

    Then fills ``first_pack_seal`` with the pack's seal and rewrites the row.
    """
    # Imported here, not at module top: pack -> probes -> glossary is the
    # instrument stack, and this module must be importable beneath all of it.
    from ctkr.oracle.pack import load_pack

    p = Path(path) if path is not None else DEFAULT_REGISTRY
    rows = load_registry(p)
    row = next((r for r in rows
                if r["term"] == term and r["kind"] != ENUM_VALUE_KIND), None)
    if row is None:
        raise ProvenanceError(
            f"term {term!r} has no provenance row in {p} — a term is proposed "
            f"(propose-terms), registered (add-term --apply), and only then "
            f"bound. There is nothing to bind."
        )
    if row["status"] == "bound":
        raise ProvenanceError(
            f"term {term!r} is already bound (first_pack_seal="
            f"{row['provenance']['first_pack_seal']}); a binding is issued once"
        )

    kind = row["kind"]
    if kind == "assertion":
        # MetaCoding-e6p: a bound term whose ProbeSpec cannot score is almost
        # certainly a skipped authority refinement (add-term emits every probe
        # DERIVED with no validated_against by design; recording and binding
        # would otherwise both succeed and the miss surfaces only as 100%
        # NO VERDICT at port-verify — the plant_type lesson, 2026-07-23).
        from ctkr.oracle.lens import active_probe_contract

        pspec = active_probe_contract().get(term)
        if pspec is not None and not pspec.is_evidence:
            raise ProvenanceError(
                f"assertion term {term!r} cannot score: its ProbeSpec is still "
                f"DERIVED with no validated_against — the raw add-term state. "
                f"Binding it would issue a term port-verify must exclude as an "
                f"unvalidated derivation. Refine the probe's authority first "
                f"(BOUNDARY for a direct transcription of a source-stated "
                f"field, or keep DERIVED and record validated_against), then "
                f"bind. The refinement belongs BEFORE the recording: if it "
                f"changes a derivation_id, the pack's fixtures answer the old "
                f"question and must be re-recorded."
            )

    pack = load_pack(fixtures_path)  # PackError propagates: no seal, no binding
    if not any(_exercises(fx, term, kind) for fx in pack.fixtures):
        raise ProvenanceError(
            f"sealed pack {pack.seal.pack_id} contains no VALID fixture that "
            f"exercises {kind} term {term!r} ({len(pack.fixtures)} valid, "
            f"{len(pack.invalid)} invalid fixtures examined). A binding is "
            f"issued by observation, and this pack observed something else."
        )

    row["provenance"]["first_pack_seal"] = pack.seal.seal
    row["status"] = "bound"
    row["bound_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    row["bound_pack_id"] = pack.seal.pack_id
    _write_registry(rows, p)
    return row


# --------------------------------------------------------------------------- #
# Enum-vocabulary provenance (MetaCoding-852)                                  #
# --------------------------------------------------------------------------- #
def governance_problems(path: str | Path | None = None) -> list[str]:
    """Every member of a GOVERNED set that is neither grandfathered nor rowed.

    The teeth of the channel, enforced by the test suite (not the loader —
    the loader must stay usable mid-edit): once a set is governed, growing it
    in ``glossary.py`` without a provenance row fails the suite, exactly the
    bar terms already meet. The reverse direction (a row for a value the
    glossary dropped) is refused at load by ``_row_problems``.
    """
    from ctkr.oracle import glossary as _glossary

    rowed = {
        (r["set"], r["term"])
        for r in load_registry(path) if r["kind"] == ENUM_VALUE_KIND
    }
    problems: list[str] = []
    for set_name, grandfathered in GOVERNED_SETS.items():
        members = getattr(_glossary, set_name)
        for value in sorted(members - grandfathered):
            if (set_name, value) not in rowed:
                problems.append(
                    f"glossary.{set_name} member {value!r} has no enum_value "
                    f"provenance row — enum growth meets the same "
                    f"cited-witnessed-reversible bar as terms (MetaCoding-852)"
                )
    return problems


def add_enum_value(
    value: str,
    set_name: str,
    config_source: str,
    description: str = "",
    punts: list[str] | None = None,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Append a PROVISIONAL enum_value row. The glossary itself is not touched:
    the value must ALREADY be a member of ``glossary.{set_name}`` (the row
    validator refuses drift in both directions)."""
    if not config_source.strip():
        raise ProvenanceError(
            f"enum_value {value!r} needs a config_source: the channel exists "
            f"precisely because commit-message-only provenance was the gap"
        )
    p = Path(path) if path is not None else DEFAULT_REGISTRY
    rows = load_registry(p)
    if any(r["kind"] == ENUM_VALUE_KIND and r.get("set") == set_name
           and r["term"] == value for r in rows):
        raise ProvenanceError(
            f"enum_value {set_name}:{value} already has a provenance row; "
            f"a value is registered once"
        )
    row = {
        "term": value,
        "kind": ENUM_VALUE_KIND,
        "set": set_name,
        "description": description,
        "provenance": {
            "config_source": config_source,
            "first_pack_seal": None,
            "punts": list(punts or []),
            "role_class_id": None,
        },
        "status": "provisional",
        "registered_at": datetime.now(UTC).isoformat(timespec="seconds"),
    }
    _write_registry(rows + [row], p)  # load_registry on write validates membership
    load_registry(p)
    return row


def _enum_witness_positions(set_name: str, value: str, fx: Any) -> bool:
    """Whether one VALID fixture exercises the enum value in the position its
    set occupies in the DSL. A CLOSED map on purpose: a new governed set must
    state its witness position here, or its values cannot bind — 'appears
    somewhere in the fixture' would let any string constant witness anything.
    """
    if set_name in ("LAND_TYPES", "STRUCTURE_TYPES"):
        entity = "land" if set_name == "LAND_TYPES" else "structure"
        return any(
            g.entity == entity and g.descriptor == value for g in fx.given
        )
    if set_name == "LOG_STATUSES":
        return any(w.status == value for w in fx.when) or any(
            t.assert_ == "log_status" and t.value == value for t in fx.then
        )
    raise ProvenanceError(
        f"governed set {set_name!r} has no declared witness position — add it "
        f"to _enum_witness_positions before binding its values"
    )


def bind_enum_value(
    value: str,
    set_name: str,
    fixtures_path: str | Path,
    path: str | Path | None = None,
) -> dict[str, Any]:
    """Flip an enum value provisional→bound because a sealed pack exercised it
    in its set's witness position. The bind_term gate, one namespace over."""
    from ctkr.oracle.pack import load_pack

    p = Path(path) if path is not None else DEFAULT_REGISTRY
    rows = load_registry(p)
    row = next((r for r in rows if r["kind"] == ENUM_VALUE_KIND
                and r.get("set") == set_name and r["term"] == value), None)
    if row is None:
        raise ProvenanceError(
            f"enum_value {set_name}:{value} has no provenance row — register "
            f"it (add_enum_value) before binding"
        )
    if row["status"] == "bound":
        raise ProvenanceError(
            f"enum_value {set_name}:{value} is already bound "
            f"(first_pack_seal={row['provenance']['first_pack_seal']}); a "
            f"binding is issued once"
        )
    pack = load_pack(fixtures_path)  # PackError propagates: no seal, no binding
    if not any(_enum_witness_positions(set_name, value, fx)
               for fx in pack.fixtures):
        raise ProvenanceError(
            f"sealed pack {pack.seal.pack_id} contains no VALID fixture that "
            f"exercises {set_name}:{value} in its witness position "
            f"({len(pack.fixtures)} valid, {len(pack.invalid)} invalid "
            f"fixtures examined). A binding is issued by observation, and "
            f"this pack observed something else."
        )
    row["provenance"]["first_pack_seal"] = pack.seal.seal
    row["status"] = "bound"
    row["bound_at"] = datetime.now(UTC).isoformat(timespec="seconds")
    row["bound_pack_id"] = pack.seal.pack_id
    _write_registry(rows, p)
    return row
