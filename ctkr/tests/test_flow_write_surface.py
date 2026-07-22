"""The MetaCoding-xdt flow-DSL write-surface batch.

Three bound-or-provisional io6 terms were capped by the DSL's WRITE surface:
lot_number had no write path (only "" was reachable, so no contrast), record_log
did not alias its owned quantities (delete_quantity adapter-reachable but not
flow-reachable), and only quantity--standard could be created (material_quantity
could never observe 'material'). This file pins the opened surface AND the two
properties that must survive it:

* **Seal stability** — every fixture sealed before these fields existed keeps
  its id (golden id computed with the pre-change code, pinned literally), and
  the committed lexicon-bind packs still validate.
* **Discrimination** — using any new field CHANGES a fixture's id; a wrong port
  cannot be scored against a fixture whose inputs it did not reproduce.

The fake-it question: an adapter could accept lot_number and drop it, alias
binding could hand back invented handles, and a 'material' quantity could be
posted as standard. So every adapter test asserts the exact boundary request,
and alias binding is checked against the handles the boundary itself stated.
"""

from __future__ import annotations

import json

import pytest

from ctkr.oracle.adapter import AdapterError, ImplementationAdapter
from ctkr.oracle.farmos_adapter import FarmOSAdapter, FarmOSClient
from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    QuantitySpec,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
    validate_fixture,
)
from ctkr.oracle.flowspec_io import FlowSpecError, flows_from_obj
from ctkr.oracle.steps import apply_when

# --------------------------------------------------------------------------- #
# Seal stability + discrimination (the fixture-hash surface)                   #
# --------------------------------------------------------------------------- #
#: content_id() of _golden_fixture() computed with the PRE-xdt code
#: (commit a693043). If this assertion ever fails, every sealed pack recorded
#: before the change has been silently re-identified — do not update the
#: literal without understanding why.
GOLDEN_PRE_XDT_ID = "6c1f18ba507bf9c0c2441371ee3af398"


def _golden_fixture(**when_overrides) -> SemanticFixture:
    q = {"measure": "weight", "value": 5.0, "unit": "kilogram", "label": "yield"}
    q.update(when_overrides.pop("quantity", {}))
    return SemanticFixture(
        title="Golden pre-xdt fixture",
        feature="harvest-logging",
        glossary_terms=["land", "harvest", "weight", "yield_total", "record_log"],
        given=[GivenStep(entity="land", alias="A", name="North Field")],
        when=[WhenStep(action="record_log", alias="L", kind="harvest",
                       status="done", name="First cut", against=["A"],
                       quantities=[QuantitySpec(**q)], **when_overrides)],
        then=[ThenAssertion(**{"assert": "yield_total"}, subject="A",
                            measure="weight", unit="kilogram", value=5.0,
                            witness="w1")],
        provenance=Provenance(source_system="farmOS", source_version="4.x",
                              flow="golden",
                              recorded_at="2026-07-22T00:00:00+00:00",
                              evidence_class="scoring"),
    )


def test_new_fields_at_their_defaults_do_not_change_a_sealed_id() -> None:
    assert _golden_fixture().content_id() == GOLDEN_PRE_XDT_ID


@pytest.mark.parametrize("override", [
    {"lot_number": "LOT-1"},
    {"quantity": {"alias": "Q"}},
    {"quantity": {"bundle": "material"}},
])
def test_using_a_new_field_changes_the_id(override) -> None:
    assert _golden_fixture(**override).content_id() != GOLDEN_PRE_XDT_ID


def test_committed_lexicon_bind_flow_packs_still_load() -> None:
    """The flow packs in the repo (including the new delete_quantity pack) must
    parse under the extended DSL."""
    from pathlib import Path

    root = Path(__file__).resolve().parents[2] / "eval" / "ctkr" / "port_runs" \
        / "lexicon-bind"
    if not root.is_dir():
        pytest.skip(f"no lexicon-bind tree at {root}")
    packs = sorted(root.glob("*/*-flows.json"))
    assert packs, f"no flow packs under {root}"
    for p in packs:
        flows = flows_from_obj(json.loads(p.read_text(encoding="utf-8")))
        assert flows, f"{p} parsed to zero flows"


# --------------------------------------------------------------------------- #
# DSL validation                                                               #
# --------------------------------------------------------------------------- #
def _one_flow(when: list[dict], glossary_terms: list[str]) -> dict:
    return {"version": 1, "flows": [{
        "key": "k", "title": "t", "feature": "harvest",
        "glossary_terms": glossary_terms,
        "given": [{"entity": "land", "alias": "A", "name": "Bed"}],
        "when": when,
        "probes": [{"assert": "log_count", "subject": "A", "kind": "harvest"}],
    }]}


def test_lot_number_is_refused_off_record_log() -> None:
    with pytest.raises(FlowSpecError, match="lot_number"):
        flows_from_obj(_one_flow(
            [{"action": "record_log", "alias": "L", "kind": "harvest",
              "status": "done", "against": ["A"]},
             {"action": "set_log_status", "ref": "L", "status": "done",
              "lot_number": "LOT-1"}],
            ["land", "harvest", "record_log", "set_log_status", "log_count"],
        ))


def test_an_unknown_bundle_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="bundle"):
        flows_from_obj(_one_flow(
            [{"action": "record_log", "alias": "L", "kind": "harvest",
              "status": "done", "against": ["A"],
              "quantities": [{"measure": "weight", "value": 1,
                              "unit": "kilogram", "bundle": "pricing"}]}],
            ["land", "harvest", "weight", "record_log", "log_count"],
        ))


def test_alias_or_bundle_off_record_log_is_refused_not_inert() -> None:
    with pytest.raises(FlowSpecError, match="only record_log"):
        flows_from_obj(_one_flow(
            [{"action": "record_inventory_adjustment", "alias": "J",
              "kind": "increment", "against": ["A"],
              "quantities": [{"measure": "weight", "value": 1,
                              "unit": "kilogram", "alias": "Q"}]}],
            ["land", "weight", "record_inventory_adjustment", "log_count"],
        ))


def test_a_duplicate_quantity_alias_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="duplicate"):
        flows_from_obj(_one_flow(
            [{"action": "record_log", "alias": "L", "kind": "harvest",
              "status": "done", "against": ["A"],
              "quantities": [
                  {"measure": "weight", "value": 1, "unit": "kilogram",
                   "alias": "Q"},
                  {"measure": "count", "value": 2, "unit": "head",
                   "alias": "Q"}]}],
            ["land", "harvest", "weight", "count", "record_log", "log_count"],
        ))


def test_validate_fixture_accepts_the_new_surface_and_resolves_refs() -> None:
    fx = SemanticFixture(
        title="delete one of two measurements",
        glossary_terms=["land", "harvest", "weight", "record_log",
                        "delete_quantity"],
        given=[GivenStep(entity="land", alias="A", name="Bed")],
        when=[
            WhenStep(action="record_log", alias="L", kind="harvest",
                     status="done", against=["A"], lot_number="LOT-1",
                     quantities=[QuantitySpec(measure="weight", value=3.0,
                                              unit="kilogram", alias="Q",
                                              bundle="material")]),
            WhenStep(action="delete_quantity", ref="Q"),
        ],
        then=[ThenAssertion(**{"assert": "log_count"}, subject="A",
                            kind="harvest", value=0, witness="w1")],
        provenance=Provenance(source_system="farmOS"),
    )
    assert validate_fixture(fx) == []
    bad = fx.model_copy(update={"when": [
        fx.when[0],
        WhenStep(action="delete_quantity", ref="L"),  # a log, not a quantity
    ]})
    assert any("quantity alias" in i.message for i in validate_fixture(bad))


# --------------------------------------------------------------------------- #
# Interpreter (steps.apply_when)                                               #
# --------------------------------------------------------------------------- #
class _LegacyAdapter(ImplementationAdapter):
    """An adapter with the PRE-xdt record_log signature: must keep working for
    every step that does not use the new surface."""

    name = "legacy"

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def create_asset(self, entity, name, descriptor="", sex=""):
        return f"asset-{name}"

    def record_log(self, kind, name, status, asset_handles, quantities):
        self.calls.append(("record_log", kind, tuple(asset_handles)))
        return "log-1"

    def set_log_status(self, log_handle, status): ...
    def assign_to_group(self, asset_handle, group_handle): ...
    def archive_asset(self, asset_handle): ...
    def asset_yield_total(self, asset_handle, measure, unit): return 0.0
    def log_status(self, log_handle): return "done"
    def log_count(self, asset_handle, kind): return 0
    def asset_active(self, asset_handle): return True
    def group_member(self, asset_handle, group_handle): return False
    def quantity_recorded(self, log_handle, measure, unit): return 0.0


class _XdtAdapter(_LegacyAdapter):
    name = "xdt"

    def __init__(self, qhandles: list[str]) -> None:
        super().__init__()
        self._qhandles = qhandles

    def record_log(self, kind, name, status, asset_handles, quantities,
                   lot_number=""):
        self.calls.append(("record_log", kind, lot_number,
                           tuple(q.alias for q in quantities)))
        return "log-1"

    def quantities_of(self, log_handle):
        self.calls.append(("quantities_of", log_handle))
        return list(self._qhandles)

    def delete_quantity(self, subject_handle):
        self.calls.append(("delete_quantity", subject_handle))


def test_a_legacy_adapter_still_records_plain_logs() -> None:
    a = _LegacyAdapter()
    handles = {"A": "asset-A"}
    apply_when(a, WhenStep(action="record_log", alias="L", kind="harvest",
                           status="done", against=["A"]), handles)
    assert a.calls == [("record_log", "harvest", ("asset-A",))]
    assert handles["L"] == "log-1"


def test_lot_number_reaches_the_adapter_only_when_stated() -> None:
    a = _XdtAdapter([])
    apply_when(a, WhenStep(action="record_log", alias="L", kind="harvest",
                           status="done", lot_number="LOT-9"), {})
    assert ("record_log", "harvest", "LOT-9", ()) in a.calls


def test_quantity_aliases_bind_the_handles_the_boundary_states() -> None:
    a = _XdtAdapter(["quantity:standard:q1", "quantity:material:q2"])
    handles: dict[str, str] = {}
    step = WhenStep(
        action="record_log", alias="L", kind="harvest", status="done",
        quantities=[
            QuantitySpec(measure="weight", value=1.0, unit="kilogram",
                         alias="Q1"),
            QuantitySpec(measure="count", value=2.0, unit="head",
                         alias="Q2", bundle="material"),
        ])
    apply_when(a, step, handles)
    assert handles["Q1"] == "quantity:standard:q1"
    assert handles["Q2"] == "quantity:material:q2"
    apply_when(a, WhenStep(action="delete_quantity", ref="Q2"), handles)
    assert ("delete_quantity", "quantity:material:q2") in a.calls


def test_a_quantity_count_mismatch_fails_loudly_never_guesses() -> None:
    a = _XdtAdapter(["quantity:standard:q1"])  # boundary states ONE
    step = WhenStep(
        action="record_log", alias="L", kind="harvest", status="done",
        quantities=[
            QuantitySpec(measure="weight", value=1.0, unit="kilogram",
                         alias="Q1"),
            QuantitySpec(measure="count", value=2.0, unit="head", alias="Q2"),
        ])
    with pytest.raises(AdapterError, match="refusing to bind"):
        apply_when(a, step, {})


def test_no_aliases_means_no_quantities_of_call() -> None:
    """The mechanism is invoked only when a flow declares aliases, so legacy
    adapters are never asked for a capability no flow uses."""
    a = _XdtAdapter(["quantity:standard:q1"])
    apply_when(a, WhenStep(action="record_log", alias="L", kind="harvest",
                           status="done",
                           quantities=[QuantitySpec(measure="weight", value=1.0,
                                                    unit="kilogram")]), {})
    assert not any(c[0] == "quantities_of" for c in a.calls)


# --------------------------------------------------------------------------- #
# farmOS adapter — the writes reach the boundary in the right shape            #
# --------------------------------------------------------------------------- #
class FakeTransport:
    def __init__(self, routes: dict[str, dict] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, str, dict | None]] = []

    def __call__(self, method, path, body, headers):
        if path == "/oauth/token":
            return json.dumps({"access_token": "t", "expires_in": 3600})
        base = path.split("?", 1)[0]
        self.calls.append((method, path, json.loads(body) if body else None))
        key = f"{method} {base}"
        if key in self.routes:
            return json.dumps(self.routes[key])
        if method == "DELETE":
            return ""
        raise AssertionError(f"unrouted {key}")


def _adapter(routes=None):
    tp = FakeTransport(routes)
    client = FarmOSClient("http://fake", "admin", "admin", transport=tp)
    adapter = FarmOSAdapter(client)
    adapter.open()
    return adapter, tp


def test_record_log_writes_the_stated_lot_number_and_omits_it_otherwise() -> None:
    adapter, tp = _adapter({
        "POST /api/log/harvest": {"data": {"type": "log--harvest", "id": "u1"}},
    })
    adapter.record_log("harvest", "H", "done", [], [], lot_number="LOT-7")
    adapter.record_log("harvest", "H2", "done", [], [])
    with_lot, without_lot = (c[2]["data"]["attributes"] for c in tp.calls
                             if c[0] == "POST")
    assert with_lot["lot_number"] == "LOT-7"
    assert "lot_number" not in without_lot


def test_a_material_quantity_is_created_as_its_own_bundle() -> None:
    adapter, tp = _adapter({
        "POST /api/quantity/material": {
            "data": {"type": "quantity--material", "id": "qm"}},
        "POST /api/log/input": {"data": {"type": "log--input", "id": "u2"}},
    })
    q = QuantitySpec(measure="weight", value=2.0, unit="", bundle="material")
    adapter.record_log("input", "I", "done", [], [q])
    (qpost,) = (c for c in tp.calls if c[1] == "/api/quantity/material")
    assert qpost[2]["data"]["type"] == "quantity--material"
    (lpost,) = (c for c in tp.calls if c[1] == "/api/log/input")
    rel = lpost[2]["data"]["relationships"]["quantity"]["data"]
    assert rel == [{"type": "quantity--material", "id": "qm"}]


def test_quantities_of_reads_back_the_logs_own_relationship() -> None:
    adapter, tp = _adapter({
        "GET /api/log/harvest/u3": {
            "data": {"type": "log--harvest", "id": "u3", "attributes": {},
                     "relationships": {"quantity": {"data": [
                         {"type": "quantity--standard", "id": "qa"},
                         {"type": "quantity--material", "id": "qb"}]}}}},
    })
    assert adapter.quantities_of("log:harvest:u3") == [
        "quantity:standard:qa", "quantity:material:qb"]
    assert ("GET", "/api/log/harvest/u3", None) in tp.calls
