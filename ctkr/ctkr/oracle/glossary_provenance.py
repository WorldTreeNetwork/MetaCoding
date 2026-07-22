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
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

KINDS: frozenset[str] = frozenset({"entity", "action", "assertion"})
STATUSES: frozenset[str] = frozenset({"provisional", "bound"})

#: The version-controlled registry, beside the glossary it governs.
DEFAULT_REGISTRY: Path = Path(__file__).with_name("glossary_provenance.jsonl")

_TERM_RE = re.compile(r"[a-z][a-z0-9_]*\Z")

_SPEC_KEYS = ("term", "kind", "description", "probe_semantics",
              "discriminating_flow", "provenance")


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
    if "kind" in spec and spec.get("kind") not in KINDS:
        problems.append(
            f"kind {spec.get('kind')!r} is not one of {sorted(KINDS)}"
        )
    for k in ("description", "probe_semantics"):
        if k in spec and not (isinstance(spec[k], str) and spec[k].strip()):
            problems.append(f"{k} must be a non-empty string")
    if "discriminating_flow" in spec and not (
        isinstance(spec["discriminating_flow"], dict) and spec["discriminating_flow"]
    ):
        problems.append("discriminating_flow must be a non-empty flow-DSL sketch")
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
    if not (isinstance(term, str) and _TERM_RE.match(term)):
        problems.append(f"{where}: term {term!r} is not a valid identifier")
    elif term in seen:
        problems.append(f"{where}: duplicate row for term {term!r}")
    if row.get("kind") not in KINDS:
        problems.append(f"{where}: kind {row.get('kind')!r} is not one of {sorted(KINDS)}")
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
        problems.extend(_row_problems(row, i, seen))
        if isinstance(row, dict) and isinstance(row.get("term"), str):
            seen.add(row["term"])
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
    """The terms no sealed pack has exercised yet."""
    return frozenset(
        r["term"] for r in load_registry(path) if r["status"] == "provisional"
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
    if any(r["term"] == term for r in rows):
        existing = next(r for r in rows if r["term"] == term)
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
    2. the pack LOADS — seal present, digests match, witnesses agree, ledger
       vouches where one exists (:func:`ctkr.oracle.pack.load_pack`; a
       :class:`~ctkr.oracle.pack.PackError` propagates untouched);
    3. at least one fixture that SURVIVED loading (never one in the invalid
       bucket) exercises the term in the position its kind allows.

    Then fills ``first_pack_seal`` with the pack's seal and rewrites the row.
    """
    # Imported here, not at module top: pack -> probes -> glossary is the
    # instrument stack, and this module must be importable beneath all of it.
    from ctkr.oracle.pack import load_pack

    p = Path(path) if path is not None else DEFAULT_REGISTRY
    rows = load_registry(p)
    row = next((r for r in rows if r["term"] == term), None)
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

    pack = load_pack(fixtures_path)  # PackError propagates: no seal, no binding
    kind = row["kind"]
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
