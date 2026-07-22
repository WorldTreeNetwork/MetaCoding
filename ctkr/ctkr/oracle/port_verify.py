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

Everything below is an instance of three invariants, not a list of guards:

**I1 — every value declares its authority.** An assertion is judged against a
recorded value, and that value came from either the source's own interface
(``boundary``) or from a computation of ours (``derived``). The probe contract
states which, and for a derived probe, what source authority the derivation was
validated against. A derived value with no such validation is **not evidence**:
:func:`_judge_assertion` reaches :data:`AssertionStatus.NO_VERDICT` before it
calls the port at all. This is why the C1 result inverts — a port that matches
farmOS can no longer be failed by a probe that never asked farmOS.

**I2 — the defendant never holds a pen that touches the verdict.** The only
inputs to this function that shape the score are the probe contract (repo), the
sealed pack (recorder), and the decision registry (repo). The port supplies its
capabilities and its divergences: two claims *about itself*, both of which can
only hurt it. There is no ``marks`` parameter, because there is no artifact in
which the party being judged may say which evidence counts.

**I3 — absence of an answer is never an answer.** One bucket,
:data:`AssertionStatus.NO_VERDICT`, absorbs every shape of "we did not learn the
answer": an undeclared probe, a runtime decline, a fixture whose setup could not
run, an invalid fixture, an unvalidated derivation, a bridge that stopped
speaking. It is never a pass, it always blocks ``clean``, and a run whose scored
denominator is empty says *"this run is evidence of nothing"* rather than 100%.
"""

from __future__ import annotations

import traceback
from collections.abc import Iterable
from typing import Any

from pydantic import BaseModel, Field, computed_field

from ctkr.oracle import glossary_provenance
from ctkr.oracle.adapter import AdapterError
from ctkr.oracle.fixtures import SemanticFixture, ThenAssertion
from ctkr.oracle.pack import Pack
from ctkr.oracle.port_adapter import (
    BridgeError,
    FalseDeclaration,
    PortAdapter,
    Unanswerable,
)
from ctkr.oracle.port_contract import Divergence, PortManifest, decision_covers
from ctkr.oracle.probes import PROBE_CONTRACT, methods_for_action
from ctkr.oracle.runner import UnresolvedAlias, compare_values, resolve_probe_args
from ctkr.oracle.steps import apply_given, apply_when, flow_now


class AssertionStatus:
    """The four outcomes. Not three, and emphatically not two."""

    PASSED = "passed"
    FAILED = "failed"
    DIVERGED = "diverged_as_declared"
    #: INVARIANT 3. Every shape of "we did not learn the answer" collapses here:
    #: undeclared probe, runtime decline, unrunnable setup, invalid fixture,
    #: unvalidated derivation, dead bridge. There is deliberately no separate
    #: `unanswerable` status any more — distinguishing the *kinds* of silence
    #: invited treating some of them as benign, and the sharpest attack on this
    #: judge was a port that declined exactly the inputs it would get wrong and
    #: reported "reproduced 24/24 = 100.0%".
    NO_VERDICT = "no_verdict"


#: Why an assertion produced no verdict. Reported per bucket so "the port
#: declined 6 calls it declared it could answer" cannot hide inside "6 gaps".
class NoVerdictCause:
    UNDECLARED = "probe not declared by the port"
    DECLINED = "port declined a call on a probe it declared"
    UNRUNNABLE = "the fixture's setup could not be performed"
    INVALID_EVIDENCE = "the recorded fixture is not valid evidence"
    UNVALIDATED_AUTHORITY = "the recorded value is a derived belief, not evidence"
    BRIDGE_DEAD = "the port's bridge stopped answering"
    EXCLUDED = "the recorder marked this evidence corroboration-only"
    PROVISIONAL = "the term is provisional — no sealed pack has exercised it"


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
    #: INVARIANT 1 — where the RECORDED value's authority came from.
    authority: str = ""
    #: INVARIANT 3 — which :class:`NoVerdictCause` applies (status NO_VERDICT).
    cause: str = ""


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
              AssertionStatus.DIVERGED, AssertionStatus.NO_VERDICT)}
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
    #: INVARIANT 3 — the single "we did not learn the answer" bucket.
    no_verdict: int = 0
    #: The same total, split by cause, so no cause can hide inside another.
    no_verdict_by_cause: dict[str, int] = Field(default_factory=dict)

    #: Of the ANSWERED assertions, those the RECORDER excluded from scoring.
    excluded_corroboration: int = 0

    scored_answered: int = 0
    scored_passed: int = 0
    scored_diverged: int = 0
    scored_failed: int = 0

    fixtures_total: int = 0
    fixtures_unrunnable: int = 0
    fixtures_excluded: int = 0
    #: Fixtures the pack itself could not vouch for (forged id, unresolvable
    #: witness, stale derivation). Counted here, never dropped.
    fixtures_invalid: int = 0

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
    def goal_fit(self) -> float:
        """(passed + sanctioned divergences) ÷ scored — agreement with the GOAL.

        ``value_score`` measures fidelity to the SOURCE, and a planned
        divergence honestly counts against it: we really do differ, by that
        much. But the port's goal is not the source verbatim — it is the source
        PLUS the bound, deliberately chosen divergences. This metric measures
        that: a sanctioned divergence that delivered exactly its declared
        target value is the goal being MET, not missed. An unplanned mismatch,
        or a divergence that missed even its own declared value, fails both
        metrics. The gap between ``value_score`` and ``goal_fit`` is therefore
        the measured footprint of the design decisions — and it should equal
        exactly what the registry sanctions, no more.
        """
        if self.scored_answered <= 0:
            return 0.0
        return (self.scored_passed + self.scored_diverged) / self.scored_answered

    @computed_field  # type: ignore[prop-decorator]
    @property
    def scored_nothing(self) -> bool:
        """Nothing was actually scored — an empty denominator is never innocent.

        A marks file that excludes every fixture produces zero failures and zero
        gaps; without this flag that run was indistinguishable from a perfect one.
        """
        return (self.scored_answered - self.scored_diverged) <= 0

    def headline(self) -> str:
        """A verdict sentence that cannot be quoted as one number.

        ``reproduced X/Y`` is always printed **out of the whole pack**, because
        the quotable number was the attack: a port that declined exactly the six
        inputs it would get wrong reported "reproduced 24/24 = 100.0%".
        """
        denom = self.scored_answered - self.scored_diverged
        value = "nothing scored" if denom <= 0 else f"{self.scored_passed}/{denom}"
        goal = (
            f"goal fit {self.scored_passed + self.scored_diverged}"
            f"/{self.scored_answered} = {self.goal_fit:.1%} "
            f"(source + {self.scored_diverged} planned divergence"
            f"{'' if self.scored_diverged == 1 else 's'} met exactly)"
            if self.scored_answered > 0 else "goal fit: nothing scored"
        )
        return (
            f"reproduced {value} scored assertions "
            f"(of {self.assertions_total} in the pack), "
            f"{self.scored_diverged} sanctioned divergence"
            f"{'' if self.scored_diverged == 1 else 's'} (NOT counted as passes), "
            f"{goal}, "
            f"{self.no_verdict}/{self.assertions_total} NO VERDICT, "
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
    #: The seal of the pack that was judged. A verdict names the evidence it was
    #: reached on, and that evidence is a whole sealed artifact — not a path.
    pack_seal: str = ""
    pack_id: str = ""
    #: Fixtures the pack could not vouch for, with the reason, verbatim.
    invalid_evidence: list[str] = Field(default_factory=list)

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
            and self.score.no_verdict == 0
            and not self.declaration_problems
            and not self.invalid_evidence
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
        if self.score.no_verdict:
            why.append(
                f"{self.score.no_verdict} assertion(s) reached NO VERDICT — "
                + "; ".join(
                    f"{n} × {cause}"
                    for cause, n in sorted(self.score.no_verdict_by_cause.items())
                )
            )
        if self.invalid_evidence:
            why.append(
                f"{len(self.invalid_evidence)} fixture(s) in this pack are not "
                f"valid evidence and were not judged"
            )
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
def _excluded_by_recorder(fx: SemanticFixture) -> str:
    """The RECORDER's reason for excluding this fixture's values, or ``""``.

    The one and only source of an evidence-quality exclusion. It travels inside
    the sealed pack, written by a party with no stake in any score. There is no
    second source, no override, and no re-admission.
    """
    if fx.provenance.evidence_class == "corroboration-only":
        return fx.provenance.evidence_note or "recorded as corroboration-only"
    return ""


def _no_verdict_verdict(
    fx: SemanticFixture, reason: str, cause: str
) -> FixtureVerdict:
    """Nothing was learnt about this fixture. Every assertion says exactly that."""
    excluded = _excluded_by_recorder(fx)
    return FixtureVerdict(
        fixture_id=fx.fixture_id, title=fx.title, flow=fx.provenance.flow,
        ran=False, scored=not excluded, mark_reason=excluded, error=reason,
        outcomes=[
            ProbeOutcome(
                fixture_id=fx.fixture_id, assertion=t.assert_, subject=t.subject,
                op=t.op, expected=t.value, actual=None,
                status=AssertionStatus.NO_VERDICT, scored=not excluded,
                detail=reason, cause=cause,
                authority=_authority_of(t.assert_),
            )
            for t in fx.then
        ],
    )


def _authority_of(assertion: str) -> str:
    spec = PROBE_CONTRACT.get(assertion)
    return spec.authority if spec else ""


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
    declaration_problems: list[str],
    decisions: dict[str, str] | None = None,
    declines: dict[str, int] | None = None,
) -> FixtureVerdict:
    """Replay one fixture against the port and judge every assertion."""
    scored = not _excluded_by_recorder(fx)

    missing = _missing_operations(adapter, fx)
    if missing:
        return _no_verdict_verdict(
            fx,
            "port declares no operation " + ", ".join(repr(m) for m in missing)
            + " — the fixture's setup cannot be performed, so nothing about its "
              "values is known",
            NoVerdictCause.UNRUNNABLE,
        )

    handles: dict[str, str] = {}
    try:
        adapter.reset()
        now = flow_now()
        for g in fx.given:
            handles[g.alias] = apply_given(adapter, g)
        for w in fx.when:
            apply_when(adapter, w, handles, now)
    except BridgeError as exc:
        # INVARIANT 3: a bridge that stopped speaking produces NO VERDICT within
        # its declared timeout, never an unbounded wait and never a crash that
        # loses the verdicts already reached.
        return _no_verdict_verdict(fx, str(exc), NoVerdictCause.BRIDGE_DEAD)
    except Unanswerable as exc:  # a capability gate we did not pre-flight
        return _no_verdict_verdict(fx, str(exc), NoVerdictCause.UNRUNNABLE)
    except (AdapterError, KeyError) as exc:
        # The port DECLARED these operations and they broke. That is a failure of
        # the port, not a gap in it — the assertions are answered "wrongly".
        detail = f"setup failed: {type(exc).__name__}: {exc}"
        if isinstance(exc, FalseDeclaration):
            declaration_problems.append(f"{fx.fixture_id}: {exc}")
        return FixtureVerdict(
            fixture_id=fx.fixture_id, title=fx.title, flow=fx.provenance.flow,
            ran=False, scored=scored, mark_reason=_excluded_by_recorder(fx),
            error=detail,
            outcomes=[
                ProbeOutcome(
                    fixture_id=fx.fixture_id, assertion=t.assert_,
                    subject=t.subject, op=t.op, expected=t.value, actual=None,
                    status=AssertionStatus.FAILED, scored=scored, detail=detail,
                    authority=_authority_of(t.assert_),
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
                         declaration_problems, decisions or {},
                         declines if declines is not None else {})
        for i in range(len(fx.then))
    ]
    return FixtureVerdict(
        fixture_id=fx.fixture_id, title=fx.title, flow=fx.provenance.flow,
        ran=True, scored=scored, mark_reason=_excluded_by_recorder(fx),
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
    decisions: dict[str, str],
    declines: dict[str, int],
) -> ProbeOutcome:
    t: ThenAssertion = fx.then[index]

    def out(status: str, **kw: Any) -> ProbeOutcome:
        return ProbeOutcome(
            fixture_id=fx.fixture_id, assertion=t.assert_, subject=t.subject,
            op=t.op, expected=t.value, status=status, scored=scored,
            authority=_authority_of(t.assert_), **kw,
        )

    spec = PROBE_CONTRACT.get(t.assert_)
    if spec is None:
        return out(AssertionStatus.NO_VERDICT,
                   cause=NoVerdictCause.INVALID_EVIDENCE,
                   detail=f"no probe binds assertion {t.assert_!r}")

    # ---- The glossary binding gate (MetaCoding-b5r) ------------------------- #
    # A PROVISIONAL term — registered by `add-term --apply`, not yet flipped by
    # `bind-term` against a sealed recording — is excluded from scoring the same
    # way corroboration-only evidence and unvalidated derivations are: NO
    # VERDICT, and the port is never called. bind-term is the only path from a
    # proposed term to a scorable one.
    provisional = glossary_provenance.provisional_reason(t.assert_)
    if provisional:
        return out(AssertionStatus.NO_VERDICT,
                   cause=NoVerdictCause.PROVISIONAL, detail=provisional)

    # ---- INVARIANT 1, before anything is asked of the port ------------------ #
    # The expected value is our own unvalidated computation. Comparing a port to
    # it cannot produce evidence in EITHER direction: agreement means the port
    # reproduced our belief, disagreement means it did not. That is the exact
    # shape that scored a farmOS-matching port at 95.2% NOT-CLEAN and a
    # farmOS-diverging one at 100% clean. The port is not called.
    if not spec.is_evidence:
        return out(AssertionStatus.NO_VERDICT,
                   cause=NoVerdictCause.UNVALIDATED_AUTHORITY,
                   detail=spec.unvalidated_reason)

    if not adapter.declares_probe(t.assert_):
        return out(
            AssertionStatus.NO_VERDICT,
            cause=NoVerdictCause.UNDECLARED,
            detail=(f"port declares no probe {t.assert_!r} (would need adapter "
                    f"method {spec.method!r}) — NO VERDICT, not a pass"),
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
    except BridgeError as exc:
        return out(AssertionStatus.NO_VERDICT,
                   cause=NoVerdictCause.BRIDGE_DEAD, detail=str(exc))
    except Unanswerable as exc:
        # The port DECLARED this probe and then declined THIS call. Still never a
        # pass — but it is also not the same thing as a missing surface, and
        # conflating them is what let a bridge decline exactly the six inputs it
        # would have got wrong and report "reproduced 24/24 = 100.0%". Counted by
        # probe, and surfaced as a declaration problem in `verify_port`.
        declines[t.assert_] = declines.get(t.assert_, 0) + 1
        return out(AssertionStatus.NO_VERDICT,
                   cause=NoVerdictCause.DECLINED, detail=str(exc))
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
    # A sanction must be TOPICALLY bound. Existence was not enough: five
    # stock-arithmetic divergences all citing `birth-uniqueness` — a real
    # decision, about birth logs — were accepted, and the exit code went 1 → 3.
    # And non-existence must never be SOFTER than existence: an id the registry
    # cannot resolve used to skip this check and score DIVERGED, so a fabricated
    # warrant landed in a milder bucket than a real-but-off-topic one
    # (MetaCoding-8x0). The unresolvable id itself is already reported as a
    # declaration problem by verify_port's manifest sweep.
    if decisions:
        did = declared.decision_id.strip()
        if did not in decisions:
            return out(AssertionStatus.FAILED, actual=actual,
                       detail=f"divergence cites {did!r}, which no registry "
                              f"resolves — an unverifiable sanction sanctions "
                              f"nothing")
        if not decision_covers(decisions[did], t.assert_):
            declaration_problems.append(
                f"{fx.fixture_id}/{t.assert_}({t.subject}): decision {did!r} "
                f"exists but does not CITE {t.assert_!r} in its sanctions — a "
                f"sanction is a typed citation of the glossary term, never a "
                f"prose mention (names never sanction)"
            )
            return out(AssertionStatus.FAILED, actual=actual,
                       detail=f"divergence cites {did!r}, which does not "
                              f"sanction {t.assert_!r}")
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
            if o.status == AssertionStatus.NO_VERDICT:
                s.no_verdict += 1
                cause = o.cause or "unclassified"
                s.no_verdict_by_cause[cause] = s.no_verdict_by_cause.get(cause, 0) + 1
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
    pack: Pack,
    manifest: PortManifest,
    decisions: dict[str, str] | None = None,
) -> PortVerifyReport:
    """Replay a SEALED pack against a port and produce the honest report.

    The signature is the invariant. There are exactly three inputs that can move
    the score, and the port authors none of them:

    * ``pack`` — a whole, hash-verified artifact written by the recorder,
      carrying its own evidence classes and its own list of what is in it. The
      port cannot choose a subset, cannot edit a value, and cannot re-classify
      evidence, because none of those survive :func:`ctkr.oracle.pack.load_pack`.
    * ``manifest`` — the port's claims *about itself*: capabilities (checked
      against its running bridge) and divergences (never a pass, always block
      ``clean``).
    * ``decisions`` — the repo's decision registry, resolved from a fixed path.

    There is no ``marks`` parameter and no ``fixtures`` parameter. Removing them
    is the fix: they were the two places the defendant reached into the verdict.
    """
    fixtures = list(pack.fixtures)
    declaration_problems: list[str] = []
    declines: dict[str, int] = {}

    # INVARIANT 3. A fixture the pack cannot vouch for is not dropped and not
    # judged: it is carried as NO VERDICT, so a pack cannot shrink its own
    # denominator by becoming unreadable.
    verdicts: list[FixtureVerdict] = [
        FixtureVerdict(
            fixture_id=inv.fixture_id, title=inv.title, ran=False, scored=True,
            error=inv.reason,
            outcomes=[ProbeOutcome(
                fixture_id=inv.fixture_id, assertion="", subject="", op="==",
                status=AssertionStatus.NO_VERDICT,
                cause=NoVerdictCause.INVALID_EVIDENCE, detail=inv.reason,
            )],
        )
        for inv in pack.invalid
    ]

    adapter.open()
    try:
        verdicts += [
            verify_fixture(adapter, fx, manifest.divergences,
                           declaration_problems, decisions or {}, declines)
            for fx in fixtures
        ]
    finally:
        adapter.close()

    # A declaration naming a fixture the pack does not contain is also a lie.
    ids = pack.all_fixture_ids
    for d in manifest.divergences:
        if d.fixture_id not in ids:
            declaration_problems.append(
                f"divergence declared for {d.fixture_id!r}, which is not in this pack"
            )

    # A sanction must name a decision that EXISTS, in the repo's registry.
    if decisions is not None:
        for d in manifest.divergences:
            did = d.decision_id.strip()
            if did and did not in decisions:
                declaration_problems.append(
                    f"divergence on {d.fixture_id}/{d.assert_} cites decision "
                    f"{did!r}, which the repo decision registry does not know — a "
                    f"sanction must point at a real, resolvable decision"
                )

    # A port that DECLARED a probe and then declined calls on it chose which of
    # its own answers would be scored. That is a claim about itself that turned
    # out to be false at run time, so it is a declaration problem, with the count.
    for term, n in sorted(declines.items()):
        declaration_problems.append(
            f"port declared probe {term!r} and then declined {n} call(s) on it — "
            f"a capability that is unavailable exactly where it is tested is not "
            f"a capability, and the declines are NOT gaps in the pack"
        )

    score = score_verdicts(verdicts)
    score.fixtures_invalid = len(pack.invalid)
    return PortVerifyReport(
        port=manifest.port, fixtures_path=str(pack.path),
        score=score, verdicts=verdicts,
        declaration_problems=declaration_problems,
        pack_seal=pack.seal.seal, pack_id=pack.seal.pack_id,
        invalid_evidence=[f"{i.fixture_id[:8]} {i.title}: {i.reason}"
                          for i in pack.invalid],
    )
