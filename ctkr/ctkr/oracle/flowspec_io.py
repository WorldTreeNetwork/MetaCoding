"""FlowSpec (de)serialization — the bridge from a written scenario to observation.

Until this module existed, the only flows the recorder could observe were the
ones hardcoded in :mod:`ctkr.oracle.recorder`. A mined feature candidate is
prose; there was no way to turn it into something the oracle would actually run.
This is that way: a flow pack is a JSON file, ``load_flows`` validates it and
hands the recorder :class:`~ctkr.oracle.recorder.FlowSpec` objects.

**The observation guarantee is enforced here, structurally.** A flow says what to
DO (``given`` / ``when``) and what to PROBE (``probes``). It has nowhere to put
an expected value — :class:`~ctkr.oracle.recorder.Probe` has no such field, and a
pack that tries to smuggle one in (``value``, ``expected``, ``then``, ...) is
rejected by name with an explanation. Every expected value in the resulting
fixture is filled by ``record_flow`` from what the live system returned.

Loading fails **loudly**, never partially:

* an unknown action, entity, log kind, adjustment kind, status, measure, sex,
  comparison operator or probe assertion;
* a declared ``glossary_terms`` entry that is not in the glossary;
* an alias that is referenced but never bound;
* an unrecognized key anywhere (so a typo is an error, not a silently ignored
  field);
* any string value that names a table, column, id or storage primitive — the
  same storage-leak lint the distilled fixtures are held to. A flow that names
  a representation is a defect exactly as a fixture would be.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from ctkr.oracle import glossary
from ctkr.oracle.fixtures import (
    _ACTION_REQUIRED,
    _OFFSET_RE,
    GivenStep,
    QuantitySpec,
    WhenStep,
    _is_effective_time,
    _iter_string_values,
)
from ctkr.oracle.probes import PROBE_CONTRACT
from ctkr.oracle.recorder import FlowSpec, Probe

#: Current on-disk pack version.
PACK_VERSION: int = 1

_FLOW_KEYS = frozenset(
    {"key", "title", "feature", "glossary_terms", "given", "when", "probes",
     # expect_refusal declares that the source is expected to REFUSE this write.
     # It is NOT an expected value: the refusal is still observed, and a source
     # that accepts instead is reported as a contradiction, never recorded.
     "expect_refusal",
     # Evidence quality, carried BY THE PACK rather than a caller's side file.
     "corroboration_only", "corroboration_reason"}
)
_GIVEN_KEYS = frozenset({"entity", "alias", "name", "descriptor", "sex"})
_WHEN_KEYS = frozenset(
    {"action", "alias", "ref", "name", "kind", "status", "against", "group",
     "quantities", "at", "parents", "names"}
)
_QUANTITY_KEYS = frozenset({"measure", "value", "unit", "label"})
_PROBE_KEYS = frozenset(
    {"assert", "subject", "measure", "unit", "kind", "group", "other", "op"}
)

#: Keys that would let a hand-written expected value into a flow. Named
#: explicitly so the failure message can say *why* rather than "unknown key".
_EXPECTED_VALUE_KEYS = frozenset(
    {"value", "expected", "expect", "then", "result", "observed", "actual"}
)


class FlowSpecError(ValueError):
    """A flow pack is malformed, illegal, or smuggles an expected value."""


# --------------------------------------------------------------------------- #
# Serialization                                                               #
# --------------------------------------------------------------------------- #
def _drop_empty(d: dict[str, Any]) -> dict[str, Any]:
    return {k: v for k, v in d.items() if v not in ("", [], None)}


def probe_to_dict(p: Probe) -> dict[str, Any]:
    return _drop_empty({
        "assert": p.assert_, "subject": p.subject, "measure": p.measure,
        "unit": p.unit, "kind": p.kind, "group": p.group, "other": p.other,
        "op": p.op if p.op != "==" else "",
    })


def flow_to_dict(f: FlowSpec) -> dict[str, Any]:
    return {
        "key": f.key,
        "title": f.title,
        "feature": f.feature,
        "glossary_terms": list(f.glossary_terms),
        "given": [_drop_empty(g.model_dump()) for g in f.given],
        "when": [_drop_empty(w.model_dump()) for w in f.when],
        "probes": [probe_to_dict(p) for p in f.probes],
        **({"expect_refusal": True} if f.expect_refusal else {}),
        **({"corroboration_only": True,
            "corroboration_reason": f.corroboration_reason}
           if f.corroboration_only else {}),
    }


def dump_flows(flows: list[FlowSpec], path: str | Path) -> int:
    """Write a flow pack as JSON. Returns the number of flows written."""
    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(
        json.dumps(
            {"version": PACK_VERSION, "flows": [flow_to_dict(f) for f in flows]},
            indent=2,
        )
        + "\n",
        encoding="utf-8",
    )
    return len(flows)


# --------------------------------------------------------------------------- #
# Deserialization                                                             #
# --------------------------------------------------------------------------- #
def _check_keys(d: dict[str, Any], allowed: frozenset[str], where: str) -> None:
    if not isinstance(d, dict):
        raise FlowSpecError(f"{where}: expected an object, got {type(d).__name__}")
    smuggled = sorted(_EXPECTED_VALUE_KEYS & set(d) - allowed)
    if smuggled:
        raise FlowSpecError(
            f"{where}: key(s) {smuggled} would carry a hand-authored expected "
            "value. A flow states what to DO and what to PROBE; every expected "
            "value is filled from what the live system returns. Remove them."
        )
    unknown = sorted(set(d) - allowed)
    if unknown:
        raise FlowSpecError(
            f"{where}: unknown key(s) {unknown} (allowed: {sorted(allowed)})"
        )


def _str(d: dict[str, Any], key: str, where: str, default: str = "") -> str:
    v = d.get(key, default)
    if not isinstance(v, str):
        raise FlowSpecError(f"{where}.{key}: expected a string, got {v!r}")
    return v


def _str_list(d: dict[str, Any], key: str, where: str) -> list[str]:
    v = d.get(key, [])
    if not isinstance(v, list) or any(not isinstance(x, str) for x in v):
        raise FlowSpecError(f"{where}.{key}: expected a list of strings, got {v!r}")
    return list(v)


def quantity_from_dict(d: dict[str, Any], where: str) -> QuantitySpec:
    _check_keys(d, _QUANTITY_KEYS, where)
    # NOTE: `value` here is an INPUT — the magnitude to record — not an expected
    # value. That is why QuantitySpec is the one place the key is legal.
    raw = d.get("value")
    if not isinstance(raw, (int, float)) or isinstance(raw, bool):
        raise FlowSpecError(f"{where}.value: expected a number, got {raw!r}")
    measure = _str(d, "measure", where)
    if measure and measure not in glossary.MEASURES:
        raise FlowSpecError(
            f"{where}.measure: {measure!r} is not a glossary measure "
            f"({sorted(glossary.MEASURES)})"
        )
    return QuantitySpec(
        measure=measure, value=float(raw),
        unit=_str(d, "unit", where), label=_str(d, "label", where),
    )


def given_from_dict(d: dict[str, Any], where: str) -> GivenStep:
    _check_keys(d, _GIVEN_KEYS, where)
    entity = _str(d, "entity", where)
    if entity not in glossary.ENTITY_TERMS:
        raise FlowSpecError(
            f"{where}.entity: {entity!r} is not a glossary entity term "
            f"({sorted(glossary.ENTITY_TERMS)})"
        )
    alias = _str(d, "alias", where)
    if not alias:
        raise FlowSpecError(f"{where}.alias: an alias is required")
    sex = _str(d, "sex", where)
    if sex and sex not in glossary.ANIMAL_SEXES:
        raise FlowSpecError(
            f"{where}.sex: {sex!r} is not a glossary animal sex "
            f"({sorted(glossary.ANIMAL_SEXES)})"
        )
    return GivenStep(
        entity=entity, alias=alias, name=_str(d, "name", where),
        descriptor=_str(d, "descriptor", where), sex=sex,
    )


def when_from_dict(d: dict[str, Any], where: str) -> WhenStep:
    _check_keys(d, _WHEN_KEYS, where)
    action = _str(d, "action", where)
    if action not in glossary.ACTION_TERMS:
        raise FlowSpecError(
            f"{where}.action: {action!r} is not a glossary action term "
            f"({sorted(glossary.ACTION_TERMS)})"
        )
    kind = _str(d, "kind", where)
    if action == "record_inventory_adjustment":
        if kind not in glossary.ADJUSTMENT_KINDS:
            raise FlowSpecError(
                f"{where}.kind: {kind!r} is not a glossary stock adjustment kind "
                f"({sorted(glossary.ADJUSTMENT_KINDS)})"
            )
    elif kind and kind not in glossary.LOG_KINDS:
        raise FlowSpecError(
            f"{where}.kind: {kind!r} is not a glossary log kind "
            f"({sorted(glossary.LOG_KINDS)})"
        )
    status = _str(d, "status", where)
    if status and status not in glossary.LOG_STATUSES:
        raise FlowSpecError(
            f"{where}.status: {status!r} is not a glossary log status "
            f"({sorted(glossary.LOG_STATUSES)})"
        )
    at = _str(d, "at", where)
    if at and not _is_effective_time(at):
        raise FlowSpecError(
            f"{where}.at: {at!r} is neither an ISO-8601 instant nor a signed "
            "offset in seconds from the moment the flow runs (e.g. '-3600')"
        )
    step = WhenStep(
        action=action, alias=_str(d, "alias", where), ref=_str(d, "ref", where),
        name=_str(d, "name", where), kind=kind, status=status,
        against=_str_list(d, "against", where), group=_str(d, "group", where),
        quantities=[
            quantity_from_dict(q, f"{where}.quantities[{i}]")
            for i, q in enumerate(d.get("quantities") or [])
        ],
        at=at, parents=_str_list(d, "parents", where),
        names=_str_list(d, "names", where),
    )
    for req in _ACTION_REQUIRED.get(action, ()):
        if not getattr(step, req):
            raise FlowSpecError(f"{where}: action {action!r} requires {req!r}")
    return step


def probe_from_dict(d: dict[str, Any], where: str) -> Probe:
    _check_keys(d, _PROBE_KEYS, where)
    assertion = _str(d, "assert", where)
    if assertion not in glossary.ASSERTION_TERMS:
        raise FlowSpecError(
            f"{where}.assert: {assertion!r} is not a glossary assertion term "
            f"({sorted(glossary.ASSERTION_TERMS)})"
        )
    subject = _str(d, "subject", where)
    if not subject:
        raise FlowSpecError(f"{where}.subject: a subject alias is required")
    measure = _str(d, "measure", where)
    if measure and measure not in glossary.MEASURES:
        raise FlowSpecError(
            f"{where}.measure: {measure!r} is not a glossary measure"
        )
    kind = _str(d, "kind", where)
    if kind and kind not in glossary.LOG_KINDS:
        raise FlowSpecError(f"{where}.kind: {kind!r} is not a glossary log kind")
    op = _str(d, "op", where, "==") or "=="
    if op not in glossary.COMPARISON_OPS:
        raise FlowSpecError(f"{where}.op: {op!r} is not a comparison operator")
    return Probe(
        assert_=assertion, subject=subject, measure=measure,
        unit=_str(d, "unit", where), kind=kind, group=_str(d, "group", where),
        other=_str(d, "other", where), op=op,
    )


def _check_storage_leaks(d: dict[str, Any], where: str) -> None:
    """Reject a flow that names a table/column/id/storage primitive (§5)."""
    for path, s in _iter_string_values(d, where):
        low = s.lower()
        for bad in glossary.FORBIDDEN_SUBSTRINGS:
            if bad in low:
                raise FlowSpecError(
                    f"{path}: representation term {bad!r} leaked in value {s!r} — "
                    "a flow speaks domain vocabulary only"
                )
        words = {w.strip(".,;:!?()[]{}\"'").lower() for w in s.split()}
        leaked = sorted(glossary.FORBIDDEN_WORDS & words)
        if leaked:
            raise FlowSpecError(
                f"{path}: storage word {leaked[0]!r} leaked in value {s!r} — "
                "a flow speaks domain vocabulary only"
            )


def flow_from_dict(d: dict[str, Any], where: str = "flow") -> FlowSpec:
    """Validate and build one :class:`FlowSpec`. Raises :class:`FlowSpecError`."""
    _check_keys(d, _FLOW_KEYS, where)
    key = _str(d, "key", where)
    if not key:
        raise FlowSpecError(f"{where}.key: a flow key is required")
    where = f"flow[{key}]"
    _check_storage_leaks(d, where)

    for term in _str_list(d, "glossary_terms", where):
        if term not in glossary.all_terms():
            raise FlowSpecError(
                f"{where}.glossary_terms: {term!r} is not in the domain glossary"
            )

    given = [given_from_dict(g, f"{where}.given[{i}]")
             for i, g in enumerate(d.get("given") or [])]
    aliases = {g.alias for g in given}
    if len(aliases) != len(given):
        raise FlowSpecError(f"{where}.given: duplicate alias")

    when: list[WhenStep] = []
    log_aliases: set[str] = set()
    for i, w in enumerate(d.get("when") or []):
        step = when_from_dict(w, f"{where}.when[{i}]")
        known_logs = set(log_aliases)
        for field, pool, label in (
            ("against", aliases, "entity"),
            ("parents", aliases, "entity"),
        ):
            for a in getattr(step, field):
                if a not in pool:
                    raise FlowSpecError(
                        f"{where}.when[{i}].{field}: unknown {label} alias {a!r}"
                    )
        if step.group and step.group not in aliases:
            raise FlowSpecError(
                f"{where}.when[{i}].group: unknown entity alias {step.group!r}"
            )
        if step.ref:
            pool = (known_logs if step.action in
                    ("set_log_status", "set_effective_time", "correct_birth")
                    else aliases)
            if step.ref not in pool:
                raise FlowSpecError(
                    f"{where}.when[{i}].ref: unknown alias {step.ref!r}"
                )
        if step.alias:
            if step.alias in aliases or step.alias in log_aliases:
                raise FlowSpecError(
                    f"{where}.when[{i}].alias: duplicate alias {step.alias!r}"
                )
            log_aliases.add(step.alias)
        when.append(step)

    known = aliases | log_aliases
    probes: list[Probe] = []
    for i, p in enumerate(d.get("probes") or []):
        probe = probe_from_dict(p, f"{where}.probes[{i}]")
        if probe.subject not in known:
            raise FlowSpecError(
                f"{where}.probes[{i}].subject: unknown alias {probe.subject!r}"
            )
        for field in ("group", "other"):
            ref = getattr(probe, field)
            if ref and ref not in aliases:
                raise FlowSpecError(
                    f"{where}.probes[{i}].{field}: unknown entity alias {ref!r}"
                )
        probes.append(probe)
    expect_refusal = bool(d.get("expect_refusal", False))
    corroboration_only = bool(d.get("corroboration_only", False))
    corroboration_reason = str(d.get("corroboration_reason", "") or "")
    if corroboration_only and not corroboration_reason.strip():
        raise FlowSpecError(
            f"{where}.corroboration_reason: excluding a fixture from the value "
            "score requires a reason"
        )

    # A relative effective time plus a timestamp-returning probe distils a fixture
    # that cannot reproduce: the value recorded is an absolute instant derived
    # from THIS run's wall clock, so a verify minutes later reads a different one.
    # w0b first self-verified at 63.6% for exactly this reason — every failure a
    # uniform +24s — and it was caught only because a self-verify happened to be
    # run twice. The schema now refuses to express it.
    timestamp_probes = sorted({
        pr.assert_ for pr in probes
        if (spec := PROBE_CONTRACT.get(pr.assert_)) and spec.returns_timestamp
    })
    relative_steps = sorted({
        w.at for w in when if w.at and _OFFSET_RE.match(w.at)
    })
    if timestamp_probes and relative_steps:
        raise FlowSpecError(
            f"{where}: probe(s) {timestamp_probes} return an instant, but this "
            f"flow dates its events RELATIVE to the run ({relative_steps}). The "
            "distilled fixture would record an absolute instant computed from the "
            "recording run's clock and could never self-verify. Use absolute "
            "ISO-8601 instants for a flow that observes a timestamp."
        )
    if not probes and not expect_refusal:
        raise FlowSpecError(
            f"{where}.probes: a flow with no probe observes nothing and would "
            "distil an empty fixture"
        )
    if expect_refusal and not when:
        raise FlowSpecError(
            f"{where}.expect_refusal: a refusal flow must attempt something — "
            "there is no write for the source to refuse"
        )

    return FlowSpec(
        key=key, title=_str(d, "title", where), feature=_str(d, "feature", where),
        glossary_terms=_str_list(d, "glossary_terms", where),
        given=given, when=when, probes=probes, expect_refusal=expect_refusal,
        corroboration_only=corroboration_only,
        corroboration_reason=corroboration_reason,
    )


def flows_from_obj(obj: Any, where: str = "pack") -> list[FlowSpec]:
    """Build flows from an already-parsed pack (an object or a bare list)."""
    if isinstance(obj, list):
        raw = obj
    elif isinstance(obj, dict):
        unknown = sorted(set(obj) - {"version", "flows"})
        if unknown:
            raise FlowSpecError(f"{where}: unknown key(s) {unknown}")
        version = obj.get("version", PACK_VERSION)
        if version != PACK_VERSION:
            raise FlowSpecError(
                f"{where}.version: {version!r} is not the supported pack version "
                f"({PACK_VERSION})"
            )
        raw = obj.get("flows")
        if not isinstance(raw, list):
            raise FlowSpecError(f"{where}.flows: expected a list of flows")
    else:
        raise FlowSpecError(f"{where}: expected an object or a list of flows")

    flows = [flow_from_dict(f, f"{where}.flows[{i}]") for i, f in enumerate(raw)]
    if not flows:
        raise FlowSpecError(f"{where}: the pack is empty — nothing to observe")
    seen: set[str] = set()
    for f in flows:
        if f.key in seen:
            raise FlowSpecError(f"{where}: duplicate flow key {f.key!r}")
        seen.add(f.key)
    return flows


def load_flows(path: str | Path) -> list[FlowSpec]:
    """Load and validate a flow pack from a JSON file. Fails loudly."""
    p = Path(path)
    try:
        obj = json.loads(p.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise FlowSpecError(f"{p}: no such flow pack") from exc
    except json.JSONDecodeError as exc:
        raise FlowSpecError(f"{p}: not valid JSON — {exc}") from exc
    return flows_from_obj(obj, where=str(p))
