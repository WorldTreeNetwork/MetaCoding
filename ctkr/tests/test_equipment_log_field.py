"""MetaCoding-1cv — the cross-family `equipment` base field on LOG.

Source intention (modules/asset/equipment/src/Hook/FieldHooks.php,
entity_base_field_info): EVERY log gains a multi-valued entity_reference base
field ``equipment`` targeting asset--equipment ("Equipment used"). CSV/Views
wiring is excluded tier. These tests pin the oracle-side surface hermetically:
the DSL write path, the interpreter, the farmOS adapter's write/readback
shapes, and the fixture-hash discipline.

The fake-it question: an adapter could accept equipment and drop it (the probe
would then honestly read False — but the WRITE test asserts the relationship
reaches the boundary document); the readback could answer from anything (it is
asserted to GET the subject log's own resource and compare ids).
"""

from __future__ import annotations

import json

import pytest

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
from ctkr.oracle.steps import apply_when
from tests.test_flow_write_surface import (
    GOLDEN_PRE_XDT_ID,
    FakeTransport,
    _golden_fixture,
    _XdtAdapter,
)


# --------------------------------------------------------------------------- #
# Fixture-hash discipline                                                      #
# --------------------------------------------------------------------------- #
def test_equipment_is_hash_inert_at_default_and_discriminating_when_used() -> None:
    assert _golden_fixture().content_id() == GOLDEN_PRE_XDT_ID
    assert _golden_fixture(equipment=["E"]).content_id() != GOLDEN_PRE_XDT_ID


# --------------------------------------------------------------------------- #
# DSL validation                                                               #
# --------------------------------------------------------------------------- #
def _flow(when: list[dict], probes: list[dict] | None = None) -> dict:
    return {"version": 1, "flows": [{
        "key": "k", "title": "t", "feature": "equipment",
        "glossary_terms": ["land", "equipment", "activity", "record_log",
                           "equipment_used", "log_count"],
        "given": [{"entity": "land", "alias": "A", "name": "Bed"},
                  {"entity": "equipment", "alias": "E1", "name": "Tractor"},
                  {"entity": "equipment", "alias": "E2", "name": "Seeder"}],
        "when": when,
        "probes": probes or [{"assert": "log_count", "subject": "A",
                              "kind": "activity"}],
    }]}


def test_equipment_flows_parse_and_probe_other_resolves() -> None:
    flows = flows_from_obj(_flow(
        [{"action": "record_log", "alias": "L", "kind": "activity",
          "status": "done", "against": ["A"], "equipment": ["E1"]}],
        [{"assert": "equipment_used", "subject": "L", "other": "E1"},
         {"assert": "equipment_used", "subject": "L", "other": "E2"}],
    ))
    assert flows[0].when[0].equipment == ["E1"]


def test_an_unknown_equipment_alias_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="unknown entity alias"):
        flows_from_obj(_flow(
            [{"action": "record_log", "alias": "L", "kind": "activity",
              "status": "done", "against": ["A"], "equipment": ["NOPE"]}]))


def test_equipment_off_record_log_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="equipment"):
        flows_from_obj(_flow(
            [{"action": "record_log", "alias": "L", "kind": "activity",
              "status": "done", "against": ["A"]},
             {"action": "set_log_status", "ref": "L", "status": "done",
              "equipment": ["E1"]}]))


def test_validate_fixture_resolves_equipment_aliases() -> None:
    def fx(equipment: list[str]) -> SemanticFixture:
        return SemanticFixture(
            title="equipment used",
            glossary_terms=["land", "equipment", "activity", "record_log",
                            "equipment_used"],
            given=[GivenStep(entity="land", alias="A", name="Bed"),
                   GivenStep(entity="equipment", alias="E1", name="Tractor")],
            when=[WhenStep(action="record_log", alias="L", kind="activity",
                           status="done", against=["A"], equipment=equipment)],
            then=[ThenAssertion(**{"assert": "equipment_used"}, subject="L",
                                other="E1", value=True, witness="w1")],
            provenance=Provenance(source_system="farmOS"),
        )
    assert validate_fixture(fx(["E1"])) == []
    assert any("equipment" in i.where for i in validate_fixture(fx(["GHOST"])))


# --------------------------------------------------------------------------- #
# Interpreter                                                                  #
# --------------------------------------------------------------------------- #
class _EquipAdapter(_XdtAdapter):
    def record_log(self, kind, name, status, asset_handles, quantities,
                   lot_number="", equipment_handles=None):
        self.calls.append(("record_log", kind, tuple(equipment_handles or ())))
        return "log-1"


def test_equipment_handles_are_resolved_and_passed_only_when_stated() -> None:
    a = _EquipAdapter([])
    handles = {"A": "asset-A", "E1": "asset-E1"}
    apply_when(a, WhenStep(action="record_log", alias="L", kind="activity",
                           status="done", against=["A"], equipment=["E1"]),
               handles)
    apply_when(a, WhenStep(action="record_log", alias="L2", kind="activity",
                           status="done", against=["A"]), handles)
    assert ("record_log", "activity", ("asset-E1",)) in a.calls
    assert ("record_log", "activity", ()) in a.calls


# --------------------------------------------------------------------------- #
# farmOS adapter                                                               #
# --------------------------------------------------------------------------- #
def _adapter(routes=None):
    tp = FakeTransport(routes)
    client = FarmOSClient("http://fake", "admin", "admin", transport=tp)
    adapter = FarmOSAdapter(client)
    adapter.open()
    return adapter, tp


def test_record_log_writes_the_equipment_relationship() -> None:
    adapter, tp = _adapter({
        "POST /api/log/activity": {"data": {"type": "log--activity", "id": "u1"}},
    })
    adapter.record_log("activity", "Till", "done", ["asset:land:a1"], [],
                       equipment_handles=["asset:equipment:e1",
                                          "asset:equipment:e2"])
    (post,) = (c for c in tp.calls if c[0] == "POST")
    rel = post[2]["data"]["relationships"]["equipment"]["data"]
    assert rel == [{"type": "asset--equipment", "id": "e1"},
                   {"type": "asset--equipment", "id": "e2"}]


def test_equipment_used_reads_membership_off_the_subject_log() -> None:
    adapter, tp = _adapter({
        "GET /api/log/activity/u1": {
            "data": {"type": "log--activity", "id": "u1", "attributes": {},
                     "relationships": {"equipment": {"data": [
                         {"type": "asset--equipment", "id": "e1"}]}}}},
    })
    assert adapter.equipment_used("log:activity:u1", "asset:equipment:e1") is True
    assert adapter.equipment_used("log:activity:u1", "asset:equipment:e2") is False
    assert ("GET", "/api/log/activity/u1", None) in tp.calls


def test_equipment_used_on_a_bare_log_delivers_false_not_a_guess() -> None:
    adapter, _ = _adapter({
        "GET /api/log/activity/u2": {
            "data": {"type": "log--activity", "id": "u2", "attributes": {}}},
    })
    assert adapter.equipment_used("log:activity:u2", "asset:equipment:e1") is False
