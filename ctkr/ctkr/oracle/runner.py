"""Verifier runner — execute semantic fixtures against an adapter (Phase 2/4).

The runner is implementation-agnostic: it interprets the fixture DSL
(given/when/then) and drives an :class:`~ctkr.oracle.adapter.ImplementationAdapter`.
Run the *recorded-from-farmOS* fixtures against the *same* live farmOS and every
one must pass — that self-verification is the acceptance test of the oracle
itself (a fixture that cannot reproduce against its own source system is a bad
distillation, not a real value scenario). Run the same fixtures against a port's
adapter and the pass rate is the port's value-equivalence score.
"""

from __future__ import annotations

import math
import operator
import traceback
from collections.abc import Iterable

from pydantic import BaseModel, Field

from ctkr.oracle.adapter import AdapterError, Handle, ImplementationAdapter
from ctkr.oracle.fixtures import SemanticFixture, ThenAssertion
from ctkr.oracle.steps import apply_given, apply_when, flow_now

_OPS = {
    "==": operator.eq,
    "!=": operator.ne,
    ">": operator.gt,
    ">=": operator.ge,
    "<": operator.lt,
    "<=": operator.le,
}
_FLOAT_TOL = 1e-6


class AssertionResult(BaseModel):
    passed: bool
    assertion: str  # the glossary assert term
    subject: str
    op: str
    expected: object
    actual: object
    detail: str = ""


class FixtureResult(BaseModel):
    fixture_id: str
    title: str
    passed: bool
    error: str = ""  # set when setup/action raised (fixture could not run)
    assertions: list[AssertionResult] = Field(default_factory=list)


def _compare(op: str, actual: object, expected: object) -> bool:
    fn = _OPS[op]
    # Numeric tolerance for float totals.
    if isinstance(actual, (int, float)) and isinstance(expected, (int, float)):
        if op == "==":
            return math.isclose(actual, expected, rel_tol=1e-9, abs_tol=_FLOAT_TOL)
        if op == "!=":
            return not math.isclose(actual, expected, rel_tol=1e-9, abs_tol=_FLOAT_TOL)
        return fn(actual, expected)
    return fn(actual, expected)


def _evaluate(
    adapter: ImplementationAdapter,
    t: ThenAssertion,
    handles: dict[str, Handle],
) -> AssertionResult:
    subject = handles.get(t.subject)
    if subject is None:
        return AssertionResult(
            passed=False, assertion=t.assert_, subject=t.subject, op=t.op,
            expected=t.value, actual=None,
            detail=f"subject alias {t.subject!r} was never created",
        )
    try:
        if t.assert_ == "yield_total":
            actual: object = adapter.asset_yield_total(subject, t.measure, t.unit)
        elif t.assert_ == "log_status":
            actual = adapter.log_status(subject)
        elif t.assert_ == "log_count":
            actual = adapter.log_count(subject, t.kind)
        elif t.assert_ == "asset_active":
            actual = adapter.asset_active(subject)
        elif t.assert_ == "group_member":
            grp = handles.get(t.group)
            if grp is None:
                return AssertionResult(
                    passed=False, assertion=t.assert_, subject=t.subject, op=t.op,
                    expected=t.value, actual=None,
                    detail=f"group alias {t.group!r} was never created",
                )
            actual = adapter.group_member(subject, grp)
        elif t.assert_ == "quantity_recorded":
            actual = adapter.quantity_recorded(subject, t.measure, t.unit)
        elif t.assert_ == "stock_on_hand":
            actual = adapter.stock_on_hand(subject, t.measure, t.unit)
        elif t.assert_ == "stock_pair_count":
            actual = adapter.stock_pair_count(subject)
        elif t.assert_ == "adjustment_count":
            actual = adapter.adjustment_count(subject)
        elif t.assert_ == "animal_sex":
            actual = adapter.animal_sex(subject)
        elif t.assert_ == "nicknames":
            actual = adapter.nicknames(subject)
        elif t.assert_ == "birth_date":
            actual = adapter.birth_date(subject)
        elif t.assert_ == "parent_count":
            actual = adapter.parent_count(subject)
        elif t.assert_ == "has_parent":
            other = handles.get(t.other)
            if other is None:
                return AssertionResult(
                    passed=False, assertion=t.assert_, subject=t.subject, op=t.op,
                    expected=t.value, actual=None,
                    detail=f"animal alias {t.other!r} was never created",
                )
            actual = adapter.has_parent(subject, other)
        elif t.assert_ == "birth_record_count":
            actual = adapter.birth_record_count(subject)
        else:  # pragma: no cover — validator forbids this
            return AssertionResult(
                passed=False, assertion=t.assert_, subject=t.subject, op=t.op,
                expected=t.value, actual=None,
                detail=f"unknown assertion {t.assert_!r}",
            )
    except AdapterError as exc:
        return AssertionResult(
            passed=False, assertion=t.assert_, subject=t.subject, op=t.op,
            expected=t.value, actual=None, detail=f"adapter error: {exc}",
        )
    passed = _compare(t.op, actual, t.value)
    return AssertionResult(
        passed=passed, assertion=t.assert_, subject=t.subject, op=t.op,
        expected=t.value, actual=actual,
    )


def run_fixture(
    adapter: ImplementationAdapter, fx: SemanticFixture
) -> FixtureResult:
    """Execute one fixture against an adapter and collect per-assertion results."""
    handles: dict[str, Handle] = {}
    try:
        now = flow_now()
        for g in fx.given:
            handles[g.alias] = apply_given(adapter, g)
        for w in fx.when:
            apply_when(adapter, w, handles, now)
    except (AdapterError, KeyError) as exc:
        return FixtureResult(
            fixture_id=fx.fixture_id or fx.content_id(), title=fx.title,
            passed=False, error=f"{type(exc).__name__}: {exc}",
        )
    except Exception as exc:  # noqa: BLE001 — never let one fixture crash the run
        return FixtureResult(
            fixture_id=fx.fixture_id or fx.content_id(), title=fx.title,
            passed=False,
            error=f"unexpected {type(exc).__name__}: {exc}\n{traceback.format_exc()}",
        )

    results = [_evaluate(adapter, t, handles) for t in fx.then]
    return FixtureResult(
        fixture_id=fx.fixture_id or fx.content_id(), title=fx.title,
        passed=all(r.passed for r in results) and bool(results),
        assertions=results,
    )


class RunSummary(BaseModel):
    total: int
    passed: int
    failed: int
    pass_rate: float
    results: list[FixtureResult] = Field(default_factory=list)


def run_fixtures(
    adapter: ImplementationAdapter, fixtures: Iterable[SemanticFixture]
) -> RunSummary:
    """Run a batch through one adapter; open/close it once around the batch."""
    fixtures = list(fixtures)
    adapter.open()
    try:
        results = [run_fixture(adapter, fx) for fx in fixtures]
    finally:
        adapter.close()
    passed = sum(1 for r in results if r.passed)
    total = len(results)
    return RunSummary(
        total=total, passed=passed, failed=total - passed,
        pass_rate=(passed / total) if total else 0.0, results=results,
    )
