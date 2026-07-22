"""Real-implementation tests for the MetaCoding-io6 glossary-growth batch.

The `ctkr add-term` skeletons (tests/test_term_*.py) pin only that each term is
registered and that its UNIMPLEMENTED surface raises. These tests pin the real
farmOS adapter bodies and the two closed-vocabulary extensions (``abandoned``
LOG_STATUS, ``LAND_TYPES`` descriptor set) — hermetically, against an injected
transport, so no live oracle is touched.

The terms stay PROVISIONAL: none of this validates a derivation against farmOS's
own authority, and nothing here records or seals a pack. The adapter reads/writes
the JSON:API boundary honestly; binding is a later phase's job.

The fake-it question, per term:
  * lot_number / material_quantity — a constant would pass a naive test, so each
    assertion checks the adapter issued the RIGHT GET against the boundary and
    returned exactly what the boundary delivered (including "" for absence).
  * delete_log / delete_quantity — a no-op would pass a "returns None" test, so
    each checks the exact DELETE method+path reached the transport.
"""

from __future__ import annotations

import json

import pytest

from ctkr.oracle import glossary
from ctkr.oracle.farmos_adapter import FarmOSAdapter, FarmOSClient
from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
    validate_fixture,
)
from ctkr.oracle.probes import PROBE_CONTRACT
from ctkr.oracle.steps import apply_when


def _fixture(*, given, when, then, title="io6 scenario") -> SemanticFixture:
    return SemanticFixture(
        title=title, given=given, when=when, then=then,
        provenance=Provenance(source_system="farmOS"),
    )


class FakeTransport:
    """Records every request and serves canned JSON:API responses.

    ``routes`` maps ``"{METHOD} {path-without-query}"`` to a response dict; a GET
    whose path is not routed 404s loudly, so a test cannot pass on a request the
    adapter never actually made.
    """

    def __init__(self, routes: dict[str, dict] | None = None) -> None:
        self.routes = routes or {}
        self.calls: list[tuple[str, str]] = []

    def __call__(self, method, path, body, headers):
        if path == "/oauth/token":
            return json.dumps({"access_token": "faketoken", "expires_in": 3600})
        base = path.split("?", 1)[0]
        self.calls.append((method, path))
        key = f"{method} {base}"
        if key in self.routes:
            return json.dumps(self.routes[key])
        if method == "DELETE":
            return ""  # 204 No Content
        raise AssertionError(f"unrouted {key}")


def _adapter(routes: dict[str, dict] | None = None) -> tuple[FarmOSAdapter, FakeTransport]:
    tp = FakeTransport(routes)
    client = FarmOSClient("http://fake", "admin", "admin", transport=tp)
    adapter = FarmOSAdapter(client)
    adapter.open()
    return adapter, tp


# --------------------------------------------------------------------------- #
# lot_number (assertion) — boundary readback of the log field                  #
# --------------------------------------------------------------------------- #
def test_lot_number_reads_the_recorded_field() -> None:
    adapter, tp = _adapter({
        "GET /api/log/harvest/u1": {
            "data": {"type": "log--harvest", "id": "u1",
                     "attributes": {"lot_number": "LOT-2026-01"}}},
    })
    assert adapter.lot_number("log:harvest:u1") == "LOT-2026-01"
    # It went to the SUBJECT log's own resource, not somewhere it could guess.
    assert ("GET", "/api/log/harvest/u1") in tp.calls


def test_lot_number_absent_reads_empty_not_a_guess() -> None:
    adapter, _ = _adapter({
        "GET /api/log/harvest/u2": {
            "data": {"type": "log--harvest", "id": "u2", "attributes": {}}},
    })
    assert adapter.lot_number("log:harvest:u2") == ""


# --------------------------------------------------------------------------- #
# material_quantity (assertion) — the delivered quantity classification        #
# --------------------------------------------------------------------------- #
def test_material_quantity_returns_the_quantity_bundle_classification() -> None:
    adapter, tp = _adapter({
        "GET /api/log/input/u3": {
            "data": {"type": "log--input", "id": "u3", "attributes": {},
                     "relationships": {"quantity": {"data": [
                         {"type": "quantity--material", "id": "q1"}]}}},
            "included": [{"type": "quantity--material", "id": "q1",
                          "attributes": {"measure": "weight"}}]},
    })
    assert adapter.material_quantity("log:input:u3") == "material"
    assert ("GET", "/api/log/input/u3?include=quantity") in tp.calls


def test_material_quantity_without_quantity_reads_empty() -> None:
    adapter, _ = _adapter({
        "GET /api/log/input/u4": {
            "data": {"type": "log--input", "id": "u4", "attributes": {}},
            "included": []},
    })
    assert adapter.material_quantity("log:input:u4") == ""


# --------------------------------------------------------------------------- #
# delete_log / delete_quantity (actions) — the write reaches the boundary      #
# --------------------------------------------------------------------------- #
def test_delete_log_issues_delete_to_the_logs_own_path() -> None:
    adapter, tp = _adapter()
    adapter.delete_log("log:harvest:u5")
    assert ("DELETE", "/api/log/harvest/u5") in tp.calls


def test_delete_quantity_issues_delete_to_the_quantitys_own_path() -> None:
    adapter, tp = _adapter()
    adapter.delete_quantity("quantity:standard:q9")
    assert ("DELETE", "/api/quantity/standard/q9") in tp.calls


def test_delete_log_is_flow_reachable_through_the_interpreter() -> None:
    """The generated steps arm dispatches delete_log to the adapter by ref."""
    adapter, tp = _adapter()
    apply_when(adapter, WhenStep(action="delete_log", ref="L"),
               {"L": "log:harvest:u7"})
    assert ("DELETE", "/api/log/harvest/u7") in tp.calls


def test_delete_log_ref_loads_as_a_log_alias_not_an_asset_alias() -> None:
    """The pack loader must resolve delete_log's ref against LOG aliases (the
    thing record_log bound), not the given assets. Without delete_log in the
    log-ref set, a legal deletion flow fails to load with 'unknown alias'."""
    from ctkr.oracle.flowspec_io import flows_from_obj

    flows = flows_from_obj({"version": 1, "flows": [{
        "key": "del", "title": "delete a recorded log", "feature": "harvest",
        "glossary_terms": ["land", "harvest", "record_log", "delete_log",
                           "log_count"],
        "given": [{"entity": "land", "alias": "A", "name": "Bed"}],
        "when": [
            {"action": "record_log", "alias": "L", "kind": "harvest",
             "status": "done", "against": ["A"]},
            {"action": "delete_log", "ref": "L"},
        ],
        "probes": [{"assert": "log_count", "subject": "A", "kind": "harvest"}],
    }]})
    assert [f.key for f in flows] == ["del"]


def test_delete_quantity_ref_stays_unresolvable_not_flow_reachable() -> None:
    """delete_quantity is deliberately NOT in the log-ref set: the DSL cannot
    mint a quantity alias, so a delete_quantity flow must fail loudly rather
    than silently bind to an asset alias — the honest 'adapter-reachable but
    not flow-reachable' signal recorded in its provenance punt."""
    from ctkr.oracle.flowspec_io import FlowSpecError, flows_from_obj

    with pytest.raises(FlowSpecError, match="unknown alias"):
        flows_from_obj({"version": 1, "flows": [{
            "key": "delq", "title": "delete a quantity", "feature": "log.input",
            "glossary_terms": ["land", "input", "record_log", "delete_quantity"],
            "given": [{"entity": "land", "alias": "A", "name": "Plot"}],
            "when": [
                {"action": "record_log", "alias": "L", "kind": "input",
                 "status": "done", "against": ["A"]},
                {"action": "delete_quantity", "ref": "L"},
            ],
            "probes": [{"assert": "log_count", "subject": "A", "kind": "input"}],
        }]})


@pytest.mark.parametrize("term", ["lot_number", "material_quantity"])
def test_recorder_observe_probe_dispatches_new_assertions(term: str) -> None:
    """The recorder's probe dispatch must call the adapter method for each new
    PROVISIONAL assertion. Before wiring, both raised 'unknown probe assertion'
    and no flow could exercise them toward a binding."""
    from ctkr.oracle.recorder import Probe, _observe_probe

    called: dict[str, str] = {}

    class _Stub:
        def lot_number(self, subject):  # noqa: ANN001
            called["term"] = "lot_number"
            return "LOT-1"

        def material_quantity(self, subject):  # noqa: ANN001
            called["term"] = "material_quantity"
            return "standard"

    out = _observe_probe(_Stub(), Probe(assert_=term, subject="L"),
                         {"L": "log:harvest:u1"})
    assert called["term"] == term
    assert out in ("LOT-1", "standard")


# --------------------------------------------------------------------------- #
# abandoned (LOG_STATUS) — expressible in flows, observable via log_status      #
# --------------------------------------------------------------------------- #
def test_abandoned_is_a_glossary_log_status() -> None:
    assert "abandoned" in glossary.LOG_STATUSES
    # Added as a VALUE, not a new assertion term or probe.
    assert "abandoned" not in glossary.ASSERTION_TERMS


def test_set_log_status_to_abandoned_validates_clean() -> None:
    fx = _fixture(
        given=[GivenStep(entity="land", alias="A", name="North Field")],
        when=[
            WhenStep(action="record_log", alias="L", kind="harvest",
                     against=["A"], status="done"),
            WhenStep(action="set_log_status", ref="L", status="abandoned"),
        ],
        then=[ThenAssertion(assert_="log_status", subject="L", value="abandoned")],
    )
    assert validate_fixture(fx) == []


def test_abandoned_reads_back_through_the_existing_log_status_probe() -> None:
    adapter, _ = _adapter({
        "GET /api/log/harvest/u8": {
            "data": {"type": "log--harvest", "id": "u8",
                     "attributes": {"status": "abandoned"}}},
    })
    # No new probe: the existing BOUNDARY log_status delivers the new value.
    assert adapter.log_status("log:harvest:u8") == "abandoned"


# --------------------------------------------------------------------------- #
# LAND_TYPES (descriptor vocabulary) — the land-only gate                       #
# --------------------------------------------------------------------------- #
def test_land_types_is_the_farmos_closed_vocabulary() -> None:
    assert glossary.LAND_TYPES == frozenset(
        {"bed", "field", "landmark", "other", "paddock", "property"})
    assert glossary.LAND_TYPES <= glossary.all_terms()


def _land_fixture(descriptor: str) -> SemanticFixture:
    return _fixture(
        given=[GivenStep(entity="land", alias="A", name="Plot",
                         descriptor=descriptor)],
        when=[],
        then=[ThenAssertion(assert_="asset_active", subject="A", value=True)],
    )


def test_land_descriptor_in_vocabulary_validates() -> None:
    assert validate_fixture(_land_fixture("bed")) == []


def test_land_descriptor_outside_vocabulary_is_rejected() -> None:
    issues = validate_fixture(_land_fixture("meadow"))
    assert any("land descriptor" in i.message for i in issues)


def test_non_land_descriptor_stays_free_text() -> None:
    # An animal's descriptor is its animal_type name — NOT gated by LAND_TYPES.
    fx = _fixture(
        given=[GivenStep(entity="animal", alias="A", name="Bossy",
                         descriptor="Cattle")],
        when=[],
        then=[ThenAssertion(assert_="asset_active", subject="A", value=True)],
    )
    assert validate_fixture(fx) == []


# --------------------------------------------------------------------------- #
# The whole batch stays PROVISIONAL / non-evidence                             #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("term", ["lot_number", "material_quantity"])
def test_new_assertion_probes_are_not_yet_evidence(term: str) -> None:
    spec = PROBE_CONTRACT[term]
    assert spec.authority == "derived"
    assert not spec.is_evidence  # DERIVED, no validated_against
    assert spec.subject_kind == "event"  # subject is a recorded log


@pytest.mark.parametrize("term", ["lot_number", "material_quantity"])
def test_new_assertion_terms_are_usable_in_then(term: str) -> None:
    """Each new assertion binds to a recorded-log subject and requires its
    observed value — the full flow-DSL plumbing, not just the probe contract."""
    fx = _fixture(
        given=[GivenStep(entity="land", alias="A", name="North Field")],
        when=[WhenStep(action="record_log", alias="L", kind="input",
                       against=["A"], status="done")],
        then=[ThenAssertion(assert_=term, subject="L", value="material")],
    )
    assert validate_fixture(fx) == []
    # And the observed value is required: an assertion with no value is rejected.
    bad = _fixture(
        given=[GivenStep(entity="land", alias="A", name="North Field")],
        when=[WhenStep(action="record_log", alias="L", kind="input",
                       against=["A"], status="done")],
        then=[ThenAssertion(assert_=term, subject="L")],
    )
    assert any(i.where == "then[0].value" for i in validate_fixture(bad))
