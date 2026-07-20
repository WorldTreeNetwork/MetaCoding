"""Refusal is evidence, not a crash (MetaCoding-o8b / blocker B3).

The wave-0 pilot lost farmOS's sharpest semantic — "you may not record a second
birth for this animal" (HTTP 422) — because the recorder died on the first
AdapterError. The refusal killed the run instead of becoming a fixture, and the
whole tail of that pack went unrecorded with it.

These tests are hermetic: a fake adapter refuses on command, no Docker, no oracle.
"""

from __future__ import annotations

import pytest

from ctkr.oracle.adapter import AdapterError
from ctkr.oracle.fixtures import GivenStep, WhenStep
from ctkr.oracle.recorder import (
    FlowSpec,
    Probe,
    RefusalNotObserved,
    record_flow,
    record_session_result,
)
from ctkr.oracle.runner import run_fixture


class _FakeClient:
    def __init__(self) -> None:
        self.observations: list = []

    def authenticate(self) -> None:
        pass


class _RefusingAdapter:
    """Creates assets happily; refuses the Nth write of a given action."""

    name = "fake"

    def __init__(self, refuse_action: str | None = "record_log",
                 refuse_after: int = 0) -> None:
        self.client = _FakeClient()
        self.refuse_action = refuse_action
        self.refuse_after = refuse_after
        self._seen = 0
        self.accepted: list[str] = []

    def open(self) -> None:
        pass

    def close(self) -> None:
        pass

    def create_asset(self, entity: str, name: str, descriptor: str = "",
                     sex: str = "") -> str:
        # Each flow starts from a fresh animal, so the "already has a birth log"
        # rule is per-asset, as it is in farmOS.
        self._seen = 0
        self.accepted = []
        return f"asset:{entity}:{name}"

    def record_log(self, kind: str, name: str, status: str, assets: list[str],
                   quantities: list, at: str = "") -> str:
        self._seen += 1
        if self.refuse_action == "record_log" and self._seen > self.refuse_after:
            raise AdapterError(
                "asset.0.target_id: Kid Fennel already has a birth log. More than "
                "one birth log cannot reference the same child."
            )
        self.accepted.append(name)
        return f"log:{name}"

    def log_count(self, asset: str, kind: str) -> int:
        return len(self.accepted)


def _flow(key: str, *, expect_refusal: bool, n_writes: int = 2,
          probes: list[Probe] | None = None) -> FlowSpec:
    return FlowSpec(
        key=key, title=f"flow {key}", feature="animal-lifecycle",
        glossary_terms=["animal", "record_log"],
        given=[GivenStep(entity="animal", alias="A", name="Kid Fennel")],
        when=[
            WhenStep(action="record_log", alias=f"L{i}", kind="birth",
                     status="done", name=f"birth {i}", against=["A"])
            for i in range(n_writes)
        ],
        probes=probes or [],
        expect_refusal=expect_refusal,
    )


def test_a_refusal_becomes_a_fixture_instead_of_killing_the_run() -> None:
    adapter = _RefusingAdapter(refuse_after=1)
    fixture, _obs = record_flow(adapter, _flow("two-births", expect_refusal=True))

    assert [t.assert_ for t in fixture.then] == ["refused"]
    assert fixture.then[0].value is True
    # The refusal is the ONLY thing asserted: probing state after a write that
    # never happened would read a world the source refused to create.
    assert len(fixture.then) == 1


def test_an_expected_refusal_that_does_not_happen_is_never_fabricated() -> None:
    """The expectation is not the observation."""
    adapter = _RefusingAdapter(refuse_action=None)  # accepts everything
    with pytest.raises(RefusalNotObserved, match="accepted the write"):
        record_flow(adapter, _flow("two-births", expect_refusal=True))


def test_an_undeclared_refusal_still_raises() -> None:
    """A flow that did not expect a refusal must not quietly absorb one."""
    adapter = _RefusingAdapter(refuse_after=1)
    with pytest.raises(AdapterError):
        record_flow(adapter, _flow("oops", expect_refusal=False))


def test_one_unrecordable_flow_does_not_cost_the_rest_of_the_pack() -> None:
    """The pilot lost a pack's tail this way."""
    adapter = _RefusingAdapter(refuse_after=1)
    flows = [
        _flow("a", expect_refusal=False, n_writes=1,
              probes=[Probe(assert_="log_count", subject="A", kind="birth")]),
        _flow("boom", expect_refusal=False, n_writes=3),   # will refuse -> unrecorded
        _flow("c", expect_refusal=False, n_writes=1,
              probes=[Probe(assert_="log_count", subject="A", kind="birth")]),
    ]
    result = record_session_result(adapter, flows)

    assert [f.provenance.flow for f in result.fixtures] == ["a", "c"]
    assert [u.key for u in result.unrecorded] == ["boom"]
    assert "already has a birth log" in result.unrecorded[0].error


def test_an_unrecorded_flow_is_never_silently_dropped() -> None:
    adapter = _RefusingAdapter(refuse_after=0)
    result = record_session_result(adapter, [_flow("x", expect_refusal=False)])
    assert not result.fixtures
    assert len(result.unrecorded) == 1  # the pack is 0 of 1, and says so


def test_a_recorded_refusal_verifies_by_refusing_again() -> None:
    """Self-verification for a refusal: the implementation must also refuse."""
    fixture, _ = record_flow(_RefusingAdapter(refuse_after=1),
                             _flow("two-births", expect_refusal=True))
    result = run_fixture(_RefusingAdapter(refuse_after=1), fixture)
    assert result.passed


def test_an_implementation_that_ACCEPTS_a_refused_write_fails() -> None:
    """The divergence a read-side probe can never see."""
    fixture, _ = record_flow(_RefusingAdapter(refuse_after=1),
                             _flow("two-births", expect_refusal=True))
    result = run_fixture(_RefusingAdapter(refuse_action=None), fixture)
    assert not result.passed
    assert "ACCEPTED where the source refused" in result.assertions[0].detail
