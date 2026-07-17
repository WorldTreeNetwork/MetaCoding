"""Runner (verifier) tests over an in-memory fake adapter — no Docker.

A ``FakeAdapter`` implements the domain contract with plain dicts, so we can
drive the runner end-to-end and assert pass/fail behavior deterministically.
This also proves the adapter *contract* is implementable by something that is
not farmOS — the whole point of the value line.
"""

from __future__ import annotations

from ctkr.oracle.adapter import Handle, ImplementationAdapter
from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    QuantitySpec,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
)
from ctkr.oracle.runner import run_fixture, run_fixtures


class FakeAdapter(ImplementationAdapter):
    """A tiny event-log-style implementation of the domain (a stand-in port)."""

    name = "fake"

    def __init__(self) -> None:
        self._n = 0
        self.assets: dict[str, dict] = {}
        self.logs: dict[str, dict] = {}
        self.memberships: dict[str, str] = {}  # asset handle -> group handle

    def _mint(self, prefix: str) -> str:
        self._n += 1
        return f"{prefix}-{self._n}"

    def create_asset(self, entity: str, name: str, descriptor: str = "") -> Handle:
        h = self._mint("asset")
        self.assets[h] = {"entity": entity, "name": name, "archived": False}
        return h

    def record_log(self, kind, name, status, asset_handles, quantities) -> Handle:
        h = self._mint("log")
        self.logs[h] = {
            "kind": kind, "status": status or "done", "assets": list(asset_handles),
            "quantities": [q.model_dump() for q in quantities],
        }
        return h

    def set_log_status(self, log_handle, status) -> None:
        self.logs[log_handle]["status"] = status

    def assign_to_group(self, asset_handle, group_handle) -> None:
        self.memberships[asset_handle] = group_handle

    def archive_asset(self, asset_handle) -> None:
        self.assets[asset_handle]["archived"] = True

    def asset_yield_total(self, asset_handle, measure, unit) -> float:
        total = 0.0
        for lg in self.logs.values():
            if asset_handle in lg["assets"]:
                for q in lg["quantities"]:
                    if q["measure"] == measure and (not unit or q["unit"] == unit):
                        total += q["value"]
        return total

    def log_status(self, log_handle) -> str:
        return self.logs[log_handle]["status"]

    def log_count(self, asset_handle, kind) -> int:
        return sum(
            1 for lg in self.logs.values()
            if lg["kind"] == kind and asset_handle in lg["assets"]
        )

    def asset_active(self, asset_handle) -> bool:
        return not self.assets[asset_handle]["archived"]

    def group_member(self, asset_handle, group_handle) -> bool:
        return self.memberships.get(asset_handle) == group_handle

    def quantity_recorded(self, log_handle, measure, unit) -> float:
        return sum(
            q["value"] for q in self.logs[log_handle]["quantities"]
            if q["measure"] == measure and (not unit or q["unit"] == unit)
        )


def _prov() -> Provenance:
    return Provenance(source_system="test")


def test_harvest_yield_passes():
    fx = SemanticFixture(
        title="harvest yield",
        given=[GivenStep(entity="land", alias="A", name="Field")],
        when=[WhenStep(action="record_log", alias="L", kind="harvest", status="done",
                       against=["A"],
                       quantities=[QuantitySpec(measure="weight", value=5,
                                                unit="kilogram")])],
        then=[
            ThenAssertion(assert_="yield_total", subject="A", measure="weight",
                          unit="kilogram", op="==", value=5),
            ThenAssertion(assert_="log_count", subject="A", kind="harvest",
                          op="==", value=1),
            ThenAssertion(assert_="quantity_recorded", subject="L", measure="weight",
                          unit="kilogram", op="==", value=5),
        ],
        provenance=_prov(),
    )
    r = run_fixture(FakeAdapter(), fx)
    assert r.passed, r.assertions


def test_yield_accumulates():
    fx = SemanticFixture(
        title="two harvests sum",
        given=[GivenStep(entity="land", alias="A", name="Field")],
        when=[
            WhenStep(action="record_log", alias="L1", kind="harvest", against=["A"],
                     quantities=[QuantitySpec(measure="weight", value=3,
                                              unit="kilogram")]),
            WhenStep(action="record_log", alias="L2", kind="harvest", against=["A"],
                     quantities=[QuantitySpec(measure="weight", value=4,
                                              unit="kilogram")]),
        ],
        then=[ThenAssertion(assert_="yield_total", subject="A", measure="weight",
                            unit="kilogram", op="==", value=7)],
        provenance=_prov(),
    )
    assert run_fixture(FakeAdapter(), fx).passed


def test_status_transition():
    fx = SemanticFixture(
        title="pending -> done",
        given=[GivenStep(entity="land", alias="A", name="Field")],
        when=[
            WhenStep(action="record_log", alias="L", kind="harvest", status="pending",
                     against=["A"]),
            WhenStep(action="set_log_status", ref="L", status="done"),
        ],
        then=[ThenAssertion(assert_="log_status", subject="L", op="==", value="done")],
        provenance=_prov(),
    )
    assert run_fixture(FakeAdapter(), fx).passed


def test_archive_makes_inactive():
    fx = SemanticFixture(
        title="archive",
        given=[GivenStep(entity="land", alias="A", name="Field")],
        when=[WhenStep(action="archive_asset", ref="A")],
        then=[ThenAssertion(assert_="asset_active", subject="A", op="==",
                            value=False)],
        provenance=_prov(),
    )
    assert run_fixture(FakeAdapter(), fx).passed


def test_group_membership():
    fx = SemanticFixture(
        title="membership",
        given=[GivenStep(entity="animal", alias="A", name="Bessie"),
               GivenStep(entity="group", alias="G", name="Herd")],
        when=[WhenStep(action="assign_to_group", ref="A", group="G")],
        then=[ThenAssertion(assert_="group_member", subject="A", group="G", op="==",
                            value=True)],
        provenance=_prov(),
    )
    assert run_fixture(FakeAdapter(), fx).passed


def test_wrong_expected_value_fails():
    fx = SemanticFixture(
        title="bad expectation",
        given=[GivenStep(entity="land", alias="A", name="Field")],
        when=[WhenStep(action="record_log", alias="L", kind="harvest", against=["A"],
                       quantities=[QuantitySpec(measure="weight", value=5,
                                                unit="kilogram")])],
        then=[ThenAssertion(assert_="yield_total", subject="A", measure="weight",
                            unit="kilogram", op="==", value=999)],
        provenance=_prov(),
    )
    r = run_fixture(FakeAdapter(), fx)
    assert not r.passed
    assert r.assertions[0].actual == 5


def test_run_fixtures_summary():
    good = SemanticFixture(
        title="good",
        given=[GivenStep(entity="land", alias="A", name="F")],
        when=[WhenStep(action="archive_asset", ref="A")],
        then=[ThenAssertion(assert_="asset_active", subject="A", value=False)],
        provenance=_prov(),
    )
    bad = SemanticFixture(
        title="bad",
        given=[GivenStep(entity="land", alias="A", name="F")],
        then=[ThenAssertion(assert_="asset_active", subject="A", value=False)],
        provenance=_prov(),
    )
    summary = run_fixtures(FakeAdapter(), [good, bad])
    assert summary.total == 2
    assert summary.passed == 1
    assert summary.failed == 1
    assert summary.pass_rate == 0.5
