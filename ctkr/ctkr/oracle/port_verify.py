"""The mechanical JUDGE — replay an observed fixture pack against a built port.

``oracle-verify`` answers "does the source system still deliver what we recorded".
This module answers the other question: "does the PORT deliver it". The two share
the fixture DSL interpreter (:mod:`ctkr.oracle.steps`) and the probe-surface
contract (:mod:`ctkr.oracle.probes`) so a port is driven exactly as the source was
observed — a harness bug and a port bug are no longer indistinguishable, because
there is no per-feature harness.

It is a separate scorer from :func:`ctkr.oracle.runner.run_fixtures` for one
reason: that runner's result is a boolean per assertion and a single blended
``pass_rate``, and the whole point here is that **three outcomes are not two**.

The three honesty rules, each enforced structurally rather than by convention:

1. **An unanswerable assertion is a declared gap.** The port declares its probe
   surface; an assertion whose probe is undeclared is never called, never
   guessed, and is counted in its own bucket. There is no code path from
   :class:`~ctkr.oracle.port_adapter.Unanswerable` to
   :attr:`AssertionStatus.PASSED`, and the report has no field that blends
   answered and unanswerable into one percentage.

2. **A sanctioned divergence is declared up front.** Only a mismatch that a
   :class:`~ctkr.oracle.port_contract.Divergence` named *before the run*, and
   whose declared ``port_value`` the port actually delivered, is
   ``diverged_as_declared``. Any other mismatch fails. A declaration is consulted
   only for an ANSWERED assertion, so it can never launder a gap; and a
   declaration that did not fire is reported as a declaration problem, because a
   stale sanction is a lie about the port.

3. **A fixture whose value encodes source insertion order does not score.**
   Marked ``corroboration_only``/``order_sensitive``, it is executed and fully
   reported, but excluded from the value score's denominator and numerator alike.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, computed_field

from ctkr.oracle.adapter import AdapterError
from ctkr.oracle.fixtures import SemanticFixture, ThenAssertion
from ctkr.oracle.port_adapter import FalseDeclaration, PortAdapter, Unanswerable
from ctkr.oracle.port_contract import Divergence, FixtureMark, PortManifest
from ctkr.oracle.probes import PROBE_CONTRACT, methods_for_action
from ctkr.oracle.runner import UnresolvedAlias, compare_values, resolve_probe_args
from ctkr.oracle.steps import apply_given, apply_when, flow_now


class AssertionStatus:
    """The four outcomes. Not three, and emphatically not two."""

    PASSED = "passed"
    FAILED = "failed"
    DIVERGED = "diverged_as_declared"
    UNANSWERABLE = "unanswerable"


class ProbeOutcome(BaseModel):
    """One assertion, judged."""

    fixture_id: str
    assertion: str
    subject: str
    op: str
    expected: Any = None
    actual: Any = None
    status: str
    #: False for assertions the value score must not count (corroboration-only).
    scored: bool = True
    detail: str = ""
    #: Set when a declared divergence was applied (status DIVERGED).
    divergence_reason: str = ""
    decision_id: str = ""


class FixtureVerdict(BaseModel):
    fixture_id: str
    title: str
    flow: str = ""
    #: False when the port declares no operation the fixture's `when` needs, or
    #: when setup raised — either way, nothing about the values was learnt.
    ran: bool = True
    scored: bool = True
    mark_reason: str = ""
    error: str = ""
    outcomes: list[ProbeOutcome] = Field(default_factory=list)

    @property
    def counts(self) -> dict[str, int]:
        c = {k: 0 for k in
             (AssertionStatus.PASSED, AssertionStatus.FAILED,
              AssertionStatus.DIVERGED, AssertionStatus.UNANSWERABLE)}
        for o in self.outcomes:
            c[o.status] += 1
        return c


class PortScore(BaseModel):
    """The honest score. Deliberately has no single headline percentage.

    ``coverage`` (how much of the pack the port can even be asked about) and
    ``value_score`` (how much of what it CAN answer it gets right) are different
    facts about a build, and averaging them hides the one that matters most
    early in a port's life.
    """

    assertions_total: int = 0
    answered: int = 0
    unanswerable: int = 0

    #: Of the ANSWERED assertions, those a fixture mark excludes from scoring.
    excluded_corroboration: int = 0

    scored_answered: int = 0
    scored_passed: int = 0
    scored_diverged: int = 0
    scored_failed: int = 0

    fixtures_total: int = 0
    fixtures_unrunnable: int = 0
    fixtures_excluded: int = 0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def coverage(self) -> float:
        """Answered ÷ total assertions — how much of the pack the port can face."""
        return self.answered / self.assertions_total if self.assertions_total else 0.0

    @computed_field  # type: ignore[prop-decorator]
    @property
    def reproduced(self) -> int:
        """Assertions where the port DELIVERED THE SOURCE'S VALUE. The only
        number that is evidence of value equivalence."""
        return self.scored_passed

    @computed_field  # type: ignore[prop-decorator]
    @property
    def value_score(self) -> float:
        """passed ÷ (scored answered MINUS sanctioned divergences).

        A declared divergence is NOT a pass. It was previously counted in the
        numerator, which made declaring arithmetically identical to reproducing:
        a port answering 999 to everything declared 30 divergences and scored
        100%. Divergences now leave the fraction entirely — they are reported as
        their own count, and they block `clean` (see PortVerifyReport).

        The denominator is never the pack size. A port that answers two
        assertions and gets both right scores 2/2 with coverage 2/30, and the
        report always prints both numbers side by side.
        """
        denom = self.scored_answered - self.scored_diverged
        if denom <= 0:
            return 0.0
        return self.scored_passed / denom

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scored_nothing(self) -> bool:
        """Nothing was actually scored — an empty denominator is never innocent.

        A marks file that excludes every fixture produces zero failures and zero
        gaps; without this flag that run was indistinguishable from a perfect one.
        """
        return (self.scored_answered - self.scored_diverged) <= 0

    def headline(self) -> str:
        """A verdict sentence that cannot be quoted as one number."""
        denom = self.scored_answered - self.scored_diverged
        value = "nothing scored" if denom <= 0 else f"{self.scored_passed}/{denom}"
        return (
            f"reproduced {value} scored assertions, "
            f"{self.scored_diverged} sanctioned divergence"
            f"{'' if self.scored_diverged == 1 else 's'} (NOT counted as passes), "
            f"{self.unanswerable}/{self.assertions_total} unanswerable, "
            f"{self.excluded_corroboration} corroboration-only excluded"
        )


class PortVerifyReport(BaseModel):
    port: str
    fixtures_path: str = ""
    score: PortScore
    verdicts: list[FixtureVerdict] = Field(default_factory=list)
    #: Declarations that are wrong ABOUT THE PORT — a stale divergence, a
    #: capability the bridge refuses. Never silently tolerated.
    declaration_problems: list[str] = Field(default_factory=list)
    #: Where fixture exclusions came from, if an external marks file was used.
    #: Recorded so a reader can see that a score was shaped by a caller-supplied
    #: file — the marks path is not necessarily written by the port's author.
    marks_source: str = ""

    @property
    def failed(self) -> int:
        return self.score.scored_failed

    @computed_field  # type: ignore[prop-decorator]
    @property
    def clean(self) -> bool:
        """No failures, no gaps, no bad declarations, nothing sanctioned away,
        and something actually scored — the only real green.

        Every clause here was earned by an attack that produced a green verdict
        without it: sanctioned divergences (a liar port declaring 30 of them),
        and an empty denominator (a marks file excluding every fixture).
        """
        return (
            self.score.scored_failed == 0
            and self.score.unanswerable == 0
            and not self.declaration_problems
            and self.score.scored_diverged == 0
            and not self.score.scored_nothing
        )

    @computed_field  # type: ignore[prop-decorator]
    @property
    def needs_review(self) -> list[str]:
        """Why this run is not a clean pass, in words. Empty iff `clean`."""
        why: list[str] = []
        if self.score.scored_failed:
            why.append(f"{self.score.scored_failed} value failure(s)")
        if self.score.unanswerable:
            why.append(f"{self.score.unanswerable} unanswerable assertion(s) — missing surface")
        if self.declaration_problems:
            why.append(f"{len(self.declaration_problems)} declaration problem(s)")
        if self.score.scored_diverged:
            why.append(
                f"{self.score.scored_diverged} sanctioned divergence(s) — the port "
                f"deliberately differs from the source here, so this is "
                f"value-equivalence MODULO a declared exception, not value equivalence"
            )
        if self.score.scored_nothing:
            why.append(
                "NOTHING WAS SCORED — every answerable assertion was excluded or "
                "sanctioned; this run is evidence of nothing"
            )
        return why


# --------------------------------------------------------------------------- #
# Divergence resolution                                                        #
# --------------------------------------------------------------------------- #
def _occurrence_index(fx: SemanticFixture, i: int) -> int:
    """How many earlier assertions of the same shape precede ``fx.then[i]``."""
    t = fx.then[i]
    shape = (t.assert_, t.subject, t.measure, t.unit)
    return sum(
        1
        for j in range(i)
        if (fx.then[j].assert_, fx.then[j].subject,
            fx.then[j].measure, fx.then[j].unit) == shape
    )


def find_divergence(
    declarations: Iterable[Divergence],
    fx: SemanticFixture,
    index: int,
) -> Divergence | None:
    """The declaration addressing this assertion, or ``None``.

    Ambiguity is an error, not a coin flip: two declarations that both match one
    assertion mean nobody knows which value was sanctioned.
    """
    t = fx.then[index]
    occ = _occurrence_index(fx, index)
    hits = [
        d for d in declarations
        if d.fixture_id == fx.fixture_id and d.matches(t, occ)
    ]
    if len(hits) > 1:
        raise ValueError(
            f"{len(hits)} divergences all match {fx.fixture_id}/{t.assert_}"
            f"({t.subject}); a sanction must be unambiguous"
        )
    return hits[0] if hits else None


# --------------------------------------------------------------------------- #
# The judge                                                                    #
# --------------------------------------------------------------------------- #
def _marks_by_id(marks: Iterable[FixtureMark]) -> dict[str, FixtureMark]:
    return {m.fixture_id: m for m in marks}


def _unrunnable_verdict(
    fx: SemanticFixture, reason: str, mark: FixtureMark | None
) -> FixtureVerdict:
    scored = not (mark and mark.excluded_from_score)
    return FixtureVerdict(
        fixture_id=fx.fixture_id, title=fx.title, flow=fx.provenance.flow,
        ran=False, scored=scored, mark_reason=(mark.reason if mark else ""),
        error=reason,
        outcomes=[
            ProbeOutcome(
                fixture_id=fx.fixture_id, assertion=t.assert_, subject=t.subject,
                op=t.op, expected=t.value, actual=None,
                status=AssertionStatus.UNANSWERABLE, scored=scored,
                detail=reason,
            )
            for t in fx.then
        ],
    )


def _missing_operations(adapter: PortAdapter, fx: SemanticFixture) -> list[str]:
    """Glossary actions the fixture performs that the port does not declare."""
    missing: list[str] = []
    for w in fx.when:
        if not methods_for_action(w.action):
            missing.append(f"{w.action} (no operation binding in the contract)")
        elif not adapter.declares_operation(w.action) and w.action not in missing:
            missing.append(w.action)
    return missing


def verify_fixture(
    adapter: PortAdapter,
    fx: SemanticFixture,
    declarations: list[Divergence],
    mark: FixtureMark | None,
    declaration_problems: list[str],
) -> FixtureVerdict:
    """Replay one fixture against the port and judge every assertion."""
    scored = not (mark and mark.excluded_from_score)

    missing = _missing_operations(adapter, fx)
    if missing:
        return _unrunnable_verdict(
            fx,
            "port declares no operation " + ", ".join(repr(m) for m in missing)
            + " — the fixture's setup cannot be performed, so nothing about its "
              "values is known",
            mark,
        )

    adapter.reset()
    handles: dict[str, str] = {}
    try:
        now = flow_now()
        for g in fx.given:
            handles[g.alias] = apply_given(adapter, g)
        for w in fx.when:
            apply_when(adapter, w, handles, now)
    except Unanswerable as exc:  # a capability gate we did not pre-flight
        return _unrunnable_verdict(fx, str(exc), mark)
    except (AdapterError, KeyError) as exc:
        # The port DECLARED these operations and they broke. That is a failure of
        # the port, not a gap in it — the assertions are answered "wrongly".
        detail = f"setup failed: {type(exc).__name__}: {exc}"
        if isinstance(exc, FalseDeclaration):
            declaration_problems.append(f"{fx.fixture_id}: {exc}")
        return FixtureVerdict(
            fixture_id=fx.fixture_id, title=fx.title, flow=fx.provenance.flow,
            ran=False, scored=scored, mark_reason=(mark.reason if mark else ""),
            error=detail,
            outcomes=[
                ProbeOutcome(
                    fixture_id=fx.fixture_id, assertion=t.assert_,
                    subject=t.subject, op=t.op, expected=t.value, actual=None,
                    status=AssertionStatus.FAILED, scored=scored, detail=detail,
                )
                for t in fx.then
            ],
        )
    except Exception as exc:  # noqa: BLE001 — one fixture never kills the run
        detail = f"unexpected {type(exc).__name__}: {exc}\n{traceback.format_exc()}"
        return FixtureVerdict(
            fixture_id=fx.fixture_id, title=fx.title, flow=fx.provenance.flow,
            ran=False, scored=scored, error=detail,
            outcomes=[
                ProbeOutcome(
                    fixture_id=fx.fixture_id, assertion=t.assert_,
                    subject=t.subject, op=t.op, expected=t.value, actual=None,
                    status=AssertionStatus.FAILED, scored=scored,
                    detail=detail.splitlines()[0],
                )
                for t in fx.then
            ],
        )

    outcomes = [
        _judge_assertion(adapter, fx, i, handles, declarations, scored,
                         declaration_problems)
        for i in range(len(fx.then))
    ]
    return FixtureVerdict(
        fixture_id=fx.fixture_id, title=fx.title, flow=fx.provenance.flow,
        ran=True, scored=scored, mark_reason=(mark.reason if mark else ""),
        outcomes=outcomes,
    )


def _judge_assertion(
    adapter: PortAdapter,
    fx: SemanticFixture,
    index: int,
    handles: dict[str, str],
    declarations: list[Divergence],
    scored: bool,
    declaration_problems: list[str],
) -> ProbeOutcome:
    t: ThenAssertion = fx.then[index]

    def out(status: str, **kw: Any) -> ProbeOutcome:
        return ProbeOutcome(
            fixture_id=fx.fixture_id, assertion=t.assert_, subject=t.subject,
            op=t.op, expected=t.value, status=status, scored=scored, **kw,
        )

    spec = PROBE_CONTRACT.get(t.assert_)
    if spec is None:
        return out(AssertionStatus.UNANSWERABLE,
                   detail=f"no probe binds assertion {t.assert_!r}")
    if not adapter.declares_probe(t.assert_):
        return out(
            AssertionStatus.UNANSWERABLE,
            detail=(f"port declares no probe {t.assert_!r} (would need adapter "
                    f"method {spec.method!r}) — GAP, not a pass"),
        )

    subject = handles.get(t.subject)
    if subject is None:
        return out(AssertionStatus.FAILED,
                   detail=f"subject alias {t.subject!r} was never created")
    try:
        args = resolve_probe_args(spec, t, handles)
    except UnresolvedAlias as exc:
        return out(AssertionStatus.FAILED, detail=str(exc))

    try:
        actual = getattr(adapter, spec.method)(subject, *args)
    except Unanswerable as exc:
        # Runtime restatement of the same gap. Still a gap; still never a pass.
        return out(AssertionStatus.UNANSWERABLE, detail=str(exc))
    except FalseDeclaration as exc:
        declaration_problems.append(f"{fx.fixture_id}: {exc}")
        return out(AssertionStatus.FAILED, detail=str(exc))
    except AdapterError as exc:
        return out(AssertionStatus.FAILED, detail=f"port error: {exc}")

    matched = compare_values(t.op, actual, t.value)
    try:
        declared = find_divergence(declarations, fx, index)
    except ValueError as exc:
        # An ambiguous sanction is a bad declaration, not a crash. Falling back
        # to "no divergence" is the safe direction: the assertion is judged on
        # the source's value, so ambiguity can never excuse a wrong answer.
        declaration_problems.append(f"{fx.fixture_id}: {exc}")
        declared = None

    if matched:
        if declared is not None:
            declaration_problems.append(
                f"{fx.fixture_id}/{t.assert_}({t.subject}): a divergence is "
                f"declared ({declared.reason}) but the port delivered the "
                f"source's value {actual!r} — the declaration is stale"
            )
        return out(AssertionStatus.PASSED, actual=actual)

    if declared is None:
        return out(AssertionStatus.FAILED, actual=actual,
                   detail="undeclared mismatch")

    if not compare_values("==", actual, declared.port_value):
        return out(
            AssertionStatus.FAILED, actual=actual,
            detail=(f"declared divergence expects {declared.port_value!r} but the "
                    f"port delivered {actual!r} — a sanction covers ONE stated "
                    f"value, not any deviation"),
        )
    return out(AssertionStatus.DIVERGED, actual=actual,
               divergence_reason=declared.reason,
               decision_id=declared.decision_id)


def score_verdicts(verdicts: list[FixtureVerdict]) -> PortScore:
    """Aggregate per-assertion outcomes into the four separate buckets."""
    s = PortScore(fixtures_total=len(verdicts))
    for v in verdicts:
        if not v.ran:
            s.fixtures_unrunnable += 1
        if not v.scored:
            s.fixtures_excluded += 1
        for o in v.outcomes:
            s.assertions_total += 1
            if o.status == AssertionStatus.UNANSWERABLE:
                s.unanswerable += 1
                continue
            s.answered += 1
            if not o.scored:
                s.excluded_corroboration += 1
                continue
            s.scored_answered += 1
            if o.status == AssertionStatus.PASSED:
                s.scored_passed += 1
            elif o.status == AssertionStatus.DIVERGED:
                s.scored_diverged += 1
            else:
                s.scored_failed += 1
    return s


def verify_port(
    adapter: PortAdapter,
    fixtures: Iterable[SemanticFixture],
    manifest: PortManifest,
    extra_marks: Iterable[FixtureMark] = (),
    fixtures_path: str = "",
    known_decision_ids: Iterable[str] | None = None,
) -> PortVerifyReport:
    """Replay a fixture pack against a port and produce the honest report.

    ``known_decision_ids`` is the set of decision ids a divergence may cite. A
    sanction that names a decision no registry knows about is a declaration
    problem — otherwise "it's a sanctioned divergence" is self-certifying.
    """
    fixtures = list(fixtures)
    declaration_problems_pre: list[str] = []
    # Precedence, weakest first: the PACK's own evidence class (set by the
    # recorder from what it observed — the most trustworthy source, since it is
    # not written by anyone with a stake in the score), then the port's manifest,
    # then an external marks file. A pack-carried mark cannot be UNDONE by a
    # later one: a port must not be able to re-admit a fixture the recorder
    # judged unscoreable.
    marks = _marks_by_id(
        FixtureMark(
            fixture_id=fx.fixture_id,
            corroboration_only=True,
            order_sensitive=True,
            reason=fx.provenance.evidence_note or "recorded as corroboration-only",
        )
        for fx in fixtures
        if fx.provenance.evidence_class == "corroboration-only"
    )
    pack_marked = set(marks)
    for m in (*manifest.fixture_marks, *extra_marks):
        if m.fixture_id in pack_marked and not m.excluded_from_score:
            declaration_problems_pre.append(
                f"fixture {m.fixture_id} was recorded as corroboration-only; a "
                f"later mark cannot re-admit it to the value score"
            )
            continue
        marks[m.fixture_id] = m
    declaration_problems: list[str] = list(declaration_problems_pre)

    adapter.open()
    try:
        verdicts = [
            verify_fixture(adapter, fx, manifest.divergences,
                           marks.get(fx.fixture_id), declaration_problems)
            for fx in fixtures
        ]
    finally:
        adapter.close()

    # A declaration naming a fixture the pack does not contain is also a lie.
    ids = {fx.fixture_id for fx in fixtures}
    for d in manifest.divergences:
        if d.fixture_id not in ids:
            declaration_problems.append(
                f"divergence declared for {d.fixture_id!r}, which is not in this pack"
            )
    for mid in marks:
        if mid not in ids:
            declaration_problems.append(
                f"fixture mark declared for {mid!r}, which is not in this pack"
            )

    # A sanction must name a decision that EXISTS. Without this, `decision_id`
    # is decoration and any wrong value can be waved through by inventing one.
    if known_decision_ids is not None:
        known = set(known_decision_ids)
        for d in manifest.divergences:
            if d.decision_id.strip() and d.decision_id.strip() not in known:
                declaration_problems.append(
                    f"divergence on {d.fixture_id}/{d.assert_} cites decision "
                    f"{d.decision_id!r}, which no decision registry knows — a "
                    f"sanction must point at a real, resolvable decision"
                )

    return PortVerifyReport(
        port=manifest.port, fixtures_path=fixtures_path,
        score=score_verdicts(verdicts), verdicts=verdicts,
        declaration_problems=declaration_problems,
    )
