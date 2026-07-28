"""The MetaCoding-b0s location surface — the verbs MetaCoding-4vh was blocked on.

`src/kernel/status.ts` labelled three location rows "observation agrees with the
original pick". No recorded observation existed: all ten location fixtures the
kernel cited carry `provenance: null`, and the OBSERVE pass could not be run
because the flow DSL had no way to say "move". This file pins the verbs that
unblocked it, and the properties that must survive them.

Live-source validation, farmOS 4.x oracle at ``localhost:8095``, 2026-07-28
(source authority: farm_location ``AssetLocation.php``):

* a done movement places the asset; a PENDING one does not; a done movement
  dated in the FUTURE does not;
* a movement naming two locations places the asset at both; one naming two
  assets moves both;
* a FIXED asset is at no location at all, however it is moved, and keeps its
  own shape;
* a movable asset's shape comes from its MOVEMENT — an asset moved with
  "POINT (30 40)" read back exactly that while the place it moved to read
  nothing;
* with neither flag stated, a land asset is a place and an animal is not — the
  per-entity default is the source's answer, which is why the DSL leaves both
  booleans tri-state rather than defaulting them to False.

**The fake-it questions.** An adapter could accept `locations` and drop them (so
the tests assert the exact boundary request); a movement could be recorded as an
ordinary log and never move anything (so `is_movement` is asserted on the wire);
the traits could be sent always, overwriting the source's own defaults with ours
(so the tests assert they are sent ONLY when stated); and a step could carry
movement fields on an action that ignores them (refused at author time).
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
from ctkr.oracle.probes import PROBE_CONTRACT
from ctkr.oracle.steps import apply_given, apply_when

LAND = "asset:land:field-uuid"
LAND2 = "asset:land:other-uuid"
COW = "asset:animal:cow-uuid"


class _Transport:
    def __init__(self, get: dict | None = None) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.get = get or {}

    def __call__(self, method: str, path: str, body: bytes | None, headers: dict):
        if path == "/oauth/token":
            return json.dumps({"access_token": "t", "expires_in": 3600})
        self.calls.append((method, path, json.loads(body) if body else None))
        if method == "GET":
            return json.dumps({"data": self.get})
        return json.dumps({"data": {"type": "log--activity", "id": "log-uuid"}})


def _adapter(get: dict | None = None) -> tuple[FarmOSAdapter, _Transport]:
    t = _Transport(get)
    a = FarmOSAdapter(FarmOSClient("http://fake", "u", "p", transport=t))
    a.open()
    return a, t


def _body(t: _Transport, method: str) -> dict:
    return next(d for m, _, d in reversed(t.calls) if m == method and d)


# --------------------------------------------------------------------------- #
# 1. The write reaches the boundary in the right shape                         #
# --------------------------------------------------------------------------- #
def test_a_movement_is_flagged_as_one() -> None:
    """farmOS has no movement BUNDLE — a movement is any log carrying
    `is_movement`, which is what AssetLocation::getMovementLog queries on. An
    activity log WITHOUT the flag is an ordinary activity and moves nothing, so
    a port could record every movement and change no location."""
    a, t = _adapter()
    a.move([COW], [LAND])
    doc = _body(t, "POST")["data"]
    assert doc["type"] == "log--activity"
    assert doc["attributes"]["is_movement"] is True


def test_every_asset_and_every_location_the_step_stated_is_transmitted() -> None:
    a, t = _adapter()
    apply_when(a, WhenStep(action="move", against=["C1", "C2"],
                           locations=["A", "B"], status="done"),
               {"C1": COW, "C2": "asset:animal:c2", "A": LAND, "B": LAND2})
    rels = _body(t, "POST")["data"]["relationships"]
    assert [x["id"] for x in rels["asset"]["data"]] == ["cow-uuid", "c2"]
    assert [x["id"] for x in rels["location"]["data"]] == \
        ["field-uuid", "other-uuid"]


def test_a_pending_movement_is_recorded_pending() -> None:
    """The whole kernel row: a pending movement must reach the source AS
    pending, or the semantic under test never happens."""
    a, t = _adapter()
    apply_when(a, WhenStep(action="move", against=["C"], locations=["A"],
                           status="pending"), {"C": COW, "A": LAND})
    assert _body(t, "POST")["data"]["attributes"]["status"] == "pending"


def test_the_movements_own_geometry_is_transmitted() -> None:
    a, t = _adapter()
    apply_when(a, WhenStep(action="move", against=["C"], locations=["A"],
                           geometry="POINT (30 40)"), {"C": COW, "A": LAND})
    assert _body(t, "POST")["data"]["attributes"]["geometry"] == "POINT (30 40)"


def test_the_location_traits_are_sent_only_when_stated() -> None:
    """PROPERTY: unstated means "the source decides", and the source's own
    default IS an observable (a land asset is a place, an animal is not —
    validated live). Sending False for an unstated flag would overwrite the
    source's answer with ours and no fixture could ever see it. This is the
    sensor `public` tri-state, applied to the two location flags."""
    a, t = _adapter()
    apply_given(a, GivenStep(entity="land", alias="A", name="Plain Field"))
    attrs = _body(t, "POST")["data"]["attributes"]
    assert "is_location" not in attrs and "is_fixed" not in attrs

    a, t = _adapter()
    apply_given(a, GivenStep(entity="land", alias="A", name="Stated Field",
                             is_location=True, is_fixed=False,
                             intrinsic_geometry="POINT (1 2)"))
    attrs = _body(t, "POST")["data"]["attributes"]
    assert attrs["is_location"] is True
    # False STATED is a value, not an absence — it must reach the boundary.
    assert attrs["is_fixed"] is False
    assert attrs["intrinsic_geometry"] == "POINT (1 2)"


# --------------------------------------------------------------------------- #
# 2. The read transcribes, and drops only representations                      #
# --------------------------------------------------------------------------- #
def _asset_doc(**over) -> dict:
    d = {"type": "asset--animal", "id": "cow-uuid",
         "attributes": {"is_location": False, "is_fixed": False,
                        "geometry": None},
         "relationships": {"location": {"data": []}}}
    d["attributes"].update(over.pop("attributes", {}))
    d["relationships"].update(over.pop("relationships", {}))
    return d


def test_current_geometry_takes_the_shape_and_drops_farmos_readings_of_it() -> None:
    """The boundary delivers the shape inside an object carrying farmOS's own
    readings OF it — geo_type, lat/lon, a bounding box, a geohash. Those are
    computed FROM the shape; a port is not obliged to reproduce farmOS's
    geohash to be right about where the thing is."""
    a, _ = _adapter(_asset_doc(attributes={"geometry": {
        "value": "POINT (30 40)", "geo_type": "Point", "lat": 40, "lon": 30,
        "geohash": "sxj7d", "latlon": "40,30"}}))
    assert a.current_geometry(COW) == "POINT (30 40)"


def test_an_asset_with_no_shape_reads_the_empty_value() -> None:
    a, _ = _adapter(_asset_doc())
    assert a.current_geometry(COW) == ""


def test_the_location_reads_come_from_the_source_computed_relationship() -> None:
    """None of these probes re-implements the latest-done-movement rule: farmOS
    computes it (AssetLocation.php) and publishes the answer as the asset's own
    `location` relationship. Re-deriving it here would be the `group_member`
    defect — a hand-written query standing in for the source's own."""
    a, _ = _adapter(_asset_doc(relationships={"location": {"data": [
        {"type": "asset--land", "id": "field-uuid"},
        {"type": "asset--land", "id": "other-uuid"}]}}))
    assert a.is_at_location(COW, LAND) is True
    assert a.is_at_location(COW, "asset:land:elsewhere") is False
    assert a.current_location_count(COW) == 2


def test_an_asset_at_no_location_counts_zero() -> None:
    a, _ = _adapter(_asset_doc())
    assert a.current_location_count(COW) == 0
    assert a.is_at_location(COW, LAND) is False


# --------------------------------------------------------------------------- #
# 3. Authority — the refinement `add-term` cannot do                           #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("term", [
    "is_at_location", "current_location_count", "current_geometry",
    "is_location", "is_fixed",
])
def test_every_location_probe_can_score(term: str) -> None:
    """`add-term` emits DERIVED-with-no-validated_against for everything. A term
    left that way is bound but unscorable — NO VERDICT on every assertion in its
    name, silently (the e6p lesson)."""
    assert PROBE_CONTRACT[term].is_evidence, \
        PROBE_CONTRACT[term].unvalidated_reason


def test_the_two_flags_are_boundary_and_claim_no_derivation() -> None:
    """A boundary value has nothing of ours to validate; claiming a derivation
    for one is a contract hole `contract_gaps` reports."""
    from ctkr.oracle.probes import BOUNDARY, contract_gaps

    for term in ("is_location", "is_fixed", "current_geometry"):
        assert PROBE_CONTRACT[term].authority == BOUNDARY
    assert contract_gaps() == []


# --------------------------------------------------------------------------- #
# 4. DSL validation                                                            #
# --------------------------------------------------------------------------- #
def _pack(when: list[dict], given: list[dict] | None = None) -> dict:
    return {"version": 1, "flows": [{
        "key": "k", "title": "t", "feature": "asset-location-movement",
        "glossary_terms": ["land", "animal", "move", "is_at_location"],
        "given": given or [
            {"entity": "land", "alias": "A", "name": "Field", "is_location": True},
            {"entity": "animal", "alias": "COW", "name": "Cow"}],
        "when": when,
        "probes": [{"assert": "is_at_location", "subject": "COW", "other": "A"}],
    }]}


def test_a_movement_must_say_what_moved_and_where_to() -> None:
    """`add-term` writes no required-fields row for a generated action, so
    without one a movement naming neither would record an event that moves
    nothing — inert at the boundary, and silent."""
    with pytest.raises(FlowSpecError, match="requires 'locations'"):
        flows_from_obj(_pack([{"action": "move", "against": ["COW"]}]))
    with pytest.raises(FlowSpecError, match="requires 'against'"):
        flows_from_obj(_pack([{"action": "move", "locations": ["A"]}]))


def test_movement_fields_are_refused_off_move() -> None:
    """On any other action the interpreter never reads them — silently inert,
    which is worse than a refusal (the lab_test-field discipline)."""
    with pytest.raises(FlowSpecError, match="only move states locations"):
        flows_from_obj(_pack([{"action": "archive_asset", "ref": "COW",
                               "locations": ["A"]}]))
    with pytest.raises(FlowSpecError, match="only move states a geometry"):
        flows_from_obj(_pack([{"action": "archive_asset", "ref": "COW",
                               "geometry": "POINT (1 2)"}]))


def test_a_movement_to_an_unknown_place_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="unknown entity alias 'NOWHERE'"):
        flows_from_obj(_pack([{"action": "move", "against": ["COW"],
                               "locations": ["NOWHERE"]}]))


def test_a_movement_to_a_ghost_is_refused() -> None:
    """Moving something to a place declared never to exist is an authoring
    error, and it composes with the ghost channel (MetaCoding-b0s)."""
    with pytest.raises(FlowSpecError, match="is a ghost"):
        flows_from_obj(_pack(
            [{"action": "move", "against": ["COW"], "locations": ["G"]}],
            [{"entity": "land", "alias": "A", "name": "Field"},
             {"entity": "animal", "alias": "COW", "name": "Cow"},
             {"entity": "land", "alias": "G", "name": "Never", "ghost": True}]))


def test_a_valid_movement_loads() -> None:
    flows = flows_from_obj(_pack([{"action": "move", "against": ["COW"],
                                   "locations": ["A"], "status": "done"}]))
    step = flows[0].when[0]
    assert step.against == ["COW"] and step.locations == ["A"]
    assert flows[0].given[0].is_location is True


def test_the_fixture_validator_enforces_the_same_rules() -> None:
    fx = SemanticFixture(
        title="t", feature="asset-location-movement",
        glossary_terms=["animal", "move", "is_at_location"],
        given=[GivenStep(entity="animal", alias="COW", name="Cow")],
        when=[WhenStep(action="move", against=["COW"], locations=["MISSING"])],
        then=[ThenAssertion(**{"assert": "is_at_location"}, subject="COW",
                            other="COW", value=False, witness="w1")],
        provenance=Provenance(source_system="farmOS"),
    )
    assert any("unknown asset alias 'MISSING'" in e.message
               for e in validate_fixture(fx))


# --------------------------------------------------------------------------- #
# 5. Seal stability + discrimination                                           #
# --------------------------------------------------------------------------- #
#: content_id() of _golden() computed with the PRE-b0s code, checked out from
#: git (240d768) into a clean tree and run there.
GOLDEN_PRE_B0S_ID = "674583c8ae642212c690ad5dec06478c"


def _golden(**over) -> SemanticFixture:
    g = GivenStep(entity="land", alias="A", name="North Field")
    fx = SemanticFixture(
        title="Golden pre-b0s location-era fixture", feature="asset-lifecycle",
        glossary_terms=["land", "asset_active"],
        given=[g.model_copy(update=over)],
        when=[WhenStep(action="archive_asset", ref="A")],
        then=[ThenAssertion(**{"assert": "asset_active"}, subject="A",
                            value=False, witness="w1")],
        provenance=Provenance(source_system="farmOS", source_version="4.x",
                              flow="golden",
                              recorded_at="2026-07-28T00:00:00+00:00"),
    )
    return fx


def test_the_new_given_fields_do_not_re_id_a_sealed_fixture() -> None:
    assert _golden().content_id() == GOLDEN_PRE_B0S_ID


@pytest.mark.parametrize("override", [
    {"is_location": True},
    # False STATED is a VALUE at the boundary (unstated leaves the source's own
    # default, which for a land asset is True — validated live), so it must
    # discriminate even where it looks like a no-op.
    {"is_location": False},
    {"is_fixed": True},
    {"intrinsic_geometry": "POINT (1 2)"},
])
def test_stating_a_location_trait_changes_the_id(override) -> None:
    assert _golden(**override).content_id() != GOLDEN_PRE_B0S_ID
