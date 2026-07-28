"""The MetaCoding-b0s ghost channel — a probe about a subject that never existed.

The gap it closes (recorded on b0s from the MetaCoding-5xa fresh read): probes
reference aliases, and every alias was bound by a `given` that CREATED
something, so the DSL could not ask a question about a subject no `given` bound.
The property that could not be stated: **an implementation must not answer a
question about a thing it never created.**

5xa is what that costs. The shared store's `assetActive` looked for an archive
event, found none, and returned true — for any handle, including ones it had
never issued. The fix landed; no scored fixture could pin it, because the pack
had no way to ask. An adversarial port hardcoding `true` reproduced 100%.

A `ghost` given binds an alias to a handle the implementation never issued and
creates nothing. A probe on it must carry `unanswerable`, and the expectation is
OBSERVED like a refusal: the recorder asks the live source, and a source that
ANSWERS raises :class:`AnswerNotExpected` instead of becoming a fixture.

**The fake-it questions, and where each is answered here:**

* *Mark a real assertion unanswerable to escape a question you'd get wrong.*
  -> the pairing is exact in BOTH directions: unanswerable on a created subject
  is refused, and a ghost subject without it is refused.
* *Declare nothing and decline everything for a free pass.* -> the undeclared
  gate is upstream of the call; an undeclared probe is NO_VERDICT on the ghost
  row too. The pass requires DECLARING the probe and then declining honestly.
* *Keep the witness, discard what it said.* -> a ghost assertion's witness must
  record `response_status == "unanswerable"`; `None == None` is not enough.
* *Smuggle a value in beside the expectation.* -> `value` must stay None.
* *Let a ghost quietly become real.* -> `apply_given` short-circuits before every
  write, and a ghost is refused in every write position.
* *Declare a divergence to excuse the answer.* -> a sanction excuses a different
  ANSWER; answering at all fails before divergence is consulted.
"""

from __future__ import annotations

import json

import pytest

from ctkr.oracle.adapter import AdapterError, ImplementationAdapter
from ctkr.oracle.farmos_adapter import FarmOSAdapter, FarmOSClient
from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
    validate_fixture,
)
from ctkr.oracle.flowspec_io import FlowSpecError, flows_from_obj
from ctkr.oracle.port_adapter import Unanswerable
from ctkr.oracle.port_verify import AssertionStatus, NoVerdictCause, verify_fixture
from ctkr.oracle.recorder import (
    UNANSWERABLE_STATUS,
    AnswerNotExpected,
    FlowSpec,
    Probe,
    record_flow,
)
from ctkr.oracle.runner import run_fixture
from ctkr.oracle.steps import apply_given

GHOST = GivenStep(entity="land", alias="G", name="Field That Was Never Made",
                  ghost=True)


# --------------------------------------------------------------------------- #
# 1. A ghost creates nothing                                                   #
# --------------------------------------------------------------------------- #
class _Recording(ImplementationAdapter):
    """Records every write; answers `asset_active`, which is the 5xa probe.

    Every other abstract read/write is inherited from the ABC, whose stubs
    RAISE — so a test that accidentally exercises one fails loudly instead of
    passing on a default.
    """

    name = "recording"
    #: `record_flow` reads the client's observation log; this adapter has none.
    client = None

    def __init__(self, *, active: object = True) -> None:
        self.writes: list[str] = []
        self.active = active
        self.known: set[str] = set()

    def create_asset(self, entity, name, descriptor="", sex=""):
        self.writes.append(f"create_asset {entity} {name}")
        h = f"asset:{entity}:{len(self.writes)}"
        self.known.add(h)
        return h

    def asset_active(self, handle):
        if isinstance(self.active, BaseException):
            raise self.active
        return self.active

    # -- abstract surface this test never uses; the ABC's stubs raise. -------
    def record_log(self, *a, **k): return super().record_log(*a, **k)
    def set_log_status(self, *a, **k): return super().set_log_status(*a, **k)
    def assign_to_group(self, *a, **k): return super().assign_to_group(*a, **k)
    def archive_asset(self, *a, **k): return super().archive_asset(*a, **k)
    def asset_yield_total(self, *a, **k): return super().asset_yield_total(*a, **k)
    def log_status(self, *a, **k): return super().log_status(*a, **k)
    def log_count(self, *a, **k): return super().log_count(*a, **k)
    def group_member(self, *a, **k): return super().group_member(*a, **k)
    def quantity_recorded(self, *a, **k): return super().quantity_recorded(*a, **k)


def test_a_ghost_given_writes_nothing() -> None:
    a = _Recording()
    handle = apply_given(a, GHOST)
    assert a.writes == [], f"a ghost wrote to the implementation: {a.writes}"
    assert handle == a.ghost_handle("land")


def test_the_default_ghost_handle_is_never_a_real_one() -> None:
    a = _Recording()
    real = apply_given(a, GivenStep(entity="land", alias="R", name="Real Field"))
    assert a.ghost_handle("land") != real
    assert a.ghost_handle("land") not in a.known


def test_the_farmos_ghost_handle_has_farmos_shape() -> None:
    """Shape matters: this adapter rebuilds a resource path from the handle, so
    a shapeless ghost would ask farmOS about a resource TYPE that does not exist
    — a 404 for the wrong reason. The nil UUID under a real bundle asks about an
    ASSET that does not exist, which is the question the flow meant."""
    a = FarmOSAdapter(FarmOSClient("http://fake", "u", "p", transport=lambda *_: ""))
    assert a.ghost_handle("land") == \
        "asset:land:00000000-0000-0000-0000-000000000000"
    assert a.ghost_handle("animal").startswith("asset:animal:")


# --------------------------------------------------------------------------- #
# 2. The pairing is exact in both directions                                   #
# --------------------------------------------------------------------------- #
def _pack(given: list[dict], probes: list[dict], when: list[dict] | None = None):
    return {"version": 1, "flows": [{
        "key": "k", "title": "t", "feature": "asset-lifecycle",
        "glossary_terms": ["land", "asset_active"],
        "given": given, "when": when or [], "probes": probes,
    }]}


_REAL = {"entity": "land", "alias": "A", "name": "Real Bed"}
_GHOST = {"entity": "land", "alias": "G", "name": "Never Bed", "ghost": True}


def test_unanswerable_on_a_created_subject_is_refused() -> None:
    """The escape hatch this would otherwise open: mark the one assertion you
    would get wrong as a declared gap and stop being asked."""
    with pytest.raises(FlowSpecError, match="fabricated gap"):
        flows_from_obj(_pack(
            [_REAL],
            [{"assert": "asset_active", "subject": "A", "unanswerable": True}]))


def test_a_ghost_subject_without_the_expectation_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="State `unanswerable`"):
        flows_from_obj(_pack(
            [_GHOST], [{"assert": "asset_active", "subject": "G"}]))


def test_a_ghost_probe_loads() -> None:
    flows = flows_from_obj(_pack(
        [_GHOST],
        [{"assert": "asset_active", "subject": "G", "unanswerable": True}]))
    assert flows[0].probes[0].unanswerable is True
    assert flows[0].given[0].ghost is True


def test_a_ghost_cannot_be_written_against() -> None:
    """A write against a subject declared never to exist is an authoring error,
    and the implementation would answer it with a crash or a phantom — neither
    is the semantic the flow meant to state."""
    for when in (
        [{"action": "archive_asset", "ref": "G"}],
        [{"action": "record_log", "alias": "L", "kind": "harvest",
          "status": "done", "against": ["G"]}],
        [{"action": "assign_to_group", "ref": "A", "group": "G"}],
    ):
        with pytest.raises(FlowSpecError, match="is a ghost"):
            flows_from_obj(_pack(
                [_REAL, _GHOST],
                [{"assert": "asset_active", "subject": "G",
                  "unanswerable": True}],
                when))


def test_a_ghost_may_not_describe_what_it_would_have_been() -> None:
    with pytest.raises(FlowSpecError, match="never created"):
        flows_from_obj(_pack(
            [{"entity": "land", "alias": "G", "name": "N", "ghost": True,
              "descriptor": "paddock"}],
            [{"assert": "asset_active", "subject": "G", "unanswerable": True}]))


def test_the_fixture_validator_enforces_the_same_pairing() -> None:
    """A flow and the fixture it distils into share one interpreter; the rule
    about the QUESTION is one function, called from both."""
    fx = _fixture(unanswerable=False, value=True)
    assert any("State `unanswerable`" in e.message for e in validate_fixture(fx))


def test_an_unanswerable_expectation_carries_no_value() -> None:
    fx = _fixture(unanswerable=True, value=True)
    assert any("carries no value" in e.message for e in validate_fixture(fx))


def test_a_valid_ghost_fixture_validates_clean() -> None:
    assert validate_fixture(_fixture()) == []


def _fixture(*, unanswerable: bool = True, value=None) -> SemanticFixture:
    return SemanticFixture(
        title="A never-created asset has no active state to read",
        feature="asset-lifecycle", glossary_terms=["land", "asset_active"],
        given=[GHOST],
        when=[],
        then=[ThenAssertion(**{"assert": "asset_active"}, subject="G",
                            value=value, unanswerable=unanswerable,
                            witness="w1")],
        provenance=Provenance(source_system="farmOS", source_version="4.x",
                              flow="ghost"),
    ).with_id()


# --------------------------------------------------------------------------- #
# 3. Seal stability                                                            #
# --------------------------------------------------------------------------- #
#: content_id() of _golden() computed with the PRE-b0s code, checked out from
#: git (240d768) into a clean tree and run there. The `then` clause is hashed
#: for EVERY fixture ever sealed, so a new assertion field appearing at its
#: default would re-id the whole corpus at once.
GOLDEN_PRE_B0S_ID = "82d594e99a0956afe54ce66b7e9780ca"


def _golden() -> SemanticFixture:
    return SemanticFixture(
        title="Golden pre-b0s ghost-era fixture", feature="asset-lifecycle",
        glossary_terms=["land", "asset_active"],
        given=[GivenStep(entity="land", alias="A", name="North Field")],
        when=[WhenStep(action="archive_asset", ref="A")],
        then=[ThenAssertion(**{"assert": "asset_active"}, subject="A",
                            value=False, witness="w1")],
        provenance=Provenance(source_system="farmOS", source_version="4.x",
                              flow="golden",
                              recorded_at="2026-07-28T00:00:00+00:00"),
    )


def test_the_new_assertion_field_does_not_re_id_the_corpus() -> None:
    assert _golden().content_id() == GOLDEN_PRE_B0S_ID


def test_a_ghost_fixture_has_a_different_id() -> None:
    assert _fixture().content_id() != GOLDEN_PRE_B0S_ID


# --------------------------------------------------------------------------- #
# 4. The recorder OBSERVES the gap; it does not declare it                     #
# --------------------------------------------------------------------------- #
def _ghost_flow() -> FlowSpec:
    return FlowSpec(
        key="ghost", title="A never-created asset has no active state to read",
        feature="asset-lifecycle", glossary_terms=["land", "asset_active"],
        given=[GHOST], when=[],
        probes=[Probe(assert_="asset_active", subject="G", unanswerable=True)],
    )


def test_a_source_that_declines_is_recorded_as_the_gap() -> None:
    a = _Recording(active=AdapterError("404: no such asset"))
    fx, obs = record_flow(a, _ghost_flow())
    assert fx.then[0].unanswerable is True
    assert fx.then[0].value is None
    witness = next(o for o in obs if o.obs_id == fx.then[0].witness)
    assert witness.response_status == UNANSWERABLE_STATUS
    assert "404" in json.dumps(witness.response_excerpt)


def test_a_source_that_ANSWERS_is_a_finding_not_a_fixture() -> None:
    """The read-side twin of RefusalNotObserved. This is the 5xa defect caught
    at the source rather than in a port: an implementation that answers about a
    thing it never created cannot tell existence from non-existence, so every
    value it gives for the question is a guess."""
    a = _Recording(active=True)
    with pytest.raises(AnswerNotExpected, match="ANSWERED True"):
        record_flow(a, _ghost_flow())


def test_the_oracle_runner_passes_a_declining_adapter() -> None:
    a = _Recording(active=AdapterError("404: no such asset"))
    result = run_fixture(a, _fixture())
    assert result.passed, result.assertions


def test_the_oracle_runner_fails_an_adapter_that_answers() -> None:
    """The 5xa regression, at the row that would catch it."""
    a = _Recording(active=True)
    result = run_fixture(a, _fixture())
    assert not result.passed
    assert "read from nothing" in result.assertions[0].detail


# --------------------------------------------------------------------------- #
# 5. port-verify: the row an adversarial port cannot launder                   #
# --------------------------------------------------------------------------- #
class _Port:
    """Minimal stand-in for a PortAdapter, over the surface verify_fixture uses."""

    def __init__(self, *, declares: bool = True, answer: object = True) -> None:
        self._declares = declares
        self.answer = answer

    def declares_probe(self, term: str) -> bool:
        return self._declares

    def declares_operation(self, term: str) -> bool:
        return True

    def reset(self) -> None:
        pass

    def create_asset(self, entity, name, descriptor="", sex=""):
        return f"port:{entity}:1"

    def ghost_handle(self, entity: str) -> str:
        return f"ghost:{entity}:never-issued"

    def asset_active(self, handle):
        if isinstance(self.answer, BaseException):
            raise self.answer
        return self.answer


def _verify(port: _Port):
    problems: list[str] = []
    return verify_fixture(port, _fixture(), [], problems), problems


def test_a_port_that_declines_the_ghost_question_PASSES() -> None:
    verdict, _ = _verify(_Port(answer=Unanswerable("no such asset")))
    assert verdict.outcomes[0].status == AssertionStatus.PASSED


def test_a_port_that_ANSWERS_the_ghost_question_FAILS() -> None:
    """THE row. Before this channel existed the 5xa fix was pinned only in
    shared-store unit tests, and a port hardcoding `true` reproduced 100%."""
    verdict, _ = _verify(_Port(answer=True))
    assert verdict.outcomes[0].status == AssertionStatus.FAILED
    assert "read from nothing" in verdict.outcomes[0].detail


def test_answering_FALSE_fails_too() -> None:
    """Not "the wrong value" — ANY value. The 5xa note records the wave-boundary
    divergence where spine-asset's store answers FALSE for unknown handles with
    no unanswerable channel at all. False is a value; the subject has none."""
    verdict, _ = _verify(_Port(answer=False))
    assert verdict.outcomes[0].status == AssertionStatus.FAILED


def test_declaring_nothing_buys_no_verdict_not_a_pass() -> None:
    """The laundering attempt the inversion invites: decline everything by
    declaring nothing. The undeclared gate is upstream of the call, so it buys
    NO_VERDICT here as everywhere — never the pass."""
    verdict, _ = _verify(_Port(declares=False))
    assert verdict.outcomes[0].status == AssertionStatus.NO_VERDICT
    assert verdict.outcomes[0].cause == NoVerdictCause.UNDECLARED
