"""The as-of read and the multi-asset fan-out (MetaCoding-b0s).

Two more of the thirteen named gaps, and the two that could not be closed the
way the other location probes were.

The five location probes bound on 2026-07-28 all TRANSCRIBE: farmOS computes
the current-location rule itself (AssetLocation.php) and publishes the answer as
the asset's own `location` relationship. Neither probe here can do that.

* **as-of** — farmOS offers no as-of read at its boundary at all. Validated live
  2026-07-28: `?timestamp=` is not a boundary parameter and the working copy
  still delivers the CURRENT location. So the answer is a fold of ours.
* **fan-out** — farmOS answers the place's side only through
  `AssetLocation::getAssetsByLocation`, raw SQL with no boundary equivalent
  (`filter[location.id]` returns 500). So the enumeration is ours.

Both are therefore DERIVED-and-cited, the `group_member` SHAPE done deliberately
to avoid the `group_member` DEFECT — a hand-written rule silently standing in
for the source's, which once got a farmOS-matching port ranked below a diverging
one.

**Why they are separate terms rather than an `as_of` parameter on
`is_at_location`.** One ProbeSpec carries one authority. `is_at_location`
transcribes; `was_at_location` computes. Bolting the instant onto the bound term
would have given one term two authorities and let a transcription's standing
launder a derivation. It would also have rotated a bound term's derivation_id
and invalidated the pack recorded under it.

**The fake-it questions.** The fold could quietly ignore `status` and count
pending movements, or ignore the future and count movements that have not
happened, or forget that a fixed asset is nowhere — each is a live-observed rule
and each has a fixture. The fan-out could count assets a flow did not create
(the oracle is SHARED); that is a real hazard, disclosed in the probe's own
`validated_against` and handled by scoping flows to untouched locations.
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

COW = "asset:animal:cow-uuid"
A = "asset:land:field-a"
B = "asset:land:field-b"

JAN = "2026-01-01T00:00:00+00:00"
MAR = "2026-03-01T00:00:00+00:00"
JUN = "2026-06-01T00:00:00+00:00"
SEP = "2026-09-01T00:00:00+00:00"


def _log(ts: str, loc: str, *, internal_id: int, status: str = "done",
         is_movement: bool = True) -> dict:
    return {
        "type": "log--activity", "id": f"log-{internal_id}",
        "attributes": {"timestamp": ts, "status": status,
                       "is_movement": is_movement,
                       "drupal_internal__id": internal_id},
        "relationships": {"location": {"data": [
            {"type": "asset--land", "id": loc.split(":")[2]}]}},
    }


class _Transport:
    """Serves an asset doc plus a movement history, the way the boundary does."""

    def __init__(self, logs: list[dict] | None = None, *,
                 is_fixed: bool = False) -> None:
        self.logs = logs or []
        self.is_fixed = is_fixed
        self.paths: list[str] = []

    def __call__(self, method: str, path: str, body: bytes | None, headers: dict):
        if path == "/oauth/token":
            return json.dumps({"access_token": "t", "expires_in": 3600})
        self.paths.append(path)
        if path == "/api":
            return json.dumps({"links": {
                "log--activity": {}, "asset--animal": {}, "asset--land": {}}})
        if path.startswith("/api/log/"):
            return json.dumps({"data": self.logs})
        if path.startswith("/api/asset/"):
            doc = {"type": "asset--animal", "id": "cow-uuid",
                   "attributes": {"is_fixed": self.is_fixed, "geometry": None,
                                  "is_location": False},
                   "relationships": {"location": {"data": []}}}
            # A collection read (the fan-out) vs a single-resource read.
            return json.dumps({"data": [doc] if "?" in path else doc})
        raise AssertionError(f"unrouted {method} {path}")


def _adapter(logs=None, **kw) -> tuple[FarmOSAdapter, _Transport]:
    t = _Transport(logs, **kw)
    a = FarmOSAdapter(FarmOSClient("http://fake", "u", "p", transport=t))
    a.open()
    return a, t


# --------------------------------------------------------------------------- #
# 1. The as-of fold reproduces AssetLocation's rule                            #
# --------------------------------------------------------------------------- #
def test_the_as_of_read_answers_about_the_moment_not_about_now() -> None:
    a, _ = _adapter([_log(JAN, A, internal_id=1), _log(JUN, B, internal_id=2)])
    assert a.was_at_location(COW, A, MAR) is True
    assert a.was_at_location(COW, B, MAR) is False
    assert a.was_at_location(COW, B, SEP) is True
    assert a.was_at_location(COW, A, SEP) is False


def test_before_the_first_movement_the_asset_was_nowhere() -> None:
    a, _ = _adapter([_log(JUN, A, internal_id=1)])
    assert a.was_at_location(COW, A, JAN) is False
    assert a.was_at_location(COW, A, SEP) is True


def test_a_pending_movement_is_inert_at_every_moment() -> None:
    """Not merely at the present one. A fold that filtered status only for the
    now-read would answer this one wrongly and nothing else would notice."""
    a, _ = _adapter([_log(JAN, A, internal_id=1),
                     _log(MAR, B, internal_id=2, status="pending")])
    assert a.was_at_location(COW, A, JUN) is True
    assert a.was_at_location(COW, B, JUN) is False


def test_a_log_that_is_not_a_movement_never_moves_anything() -> None:
    a, _ = _adapter([_log(JAN, A, internal_id=1),
                     _log(MAR, B, internal_id=2, is_movement=False)])
    assert a.was_at_location(COW, B, JUN) is False


def test_a_tie_breaks_on_the_larger_internal_id() -> None:
    """AssetLocation's own tie-break (`lfd2.timestamp = lfd.timestamp AND
    lfd2.id > lfd.id`). A fold that took the first match would disagree with the
    source on exactly the case the source bothered to specify."""
    a, _ = _adapter([_log(JAN, A, internal_id=1), _log(JAN, B, internal_id=2)])
    assert a.was_at_location(COW, B, JUN) is True
    assert a.was_at_location(COW, A, JUN) is False


def test_a_fixed_asset_was_at_no_location_at_any_moment() -> None:
    """getLocation short-circuits on `is_fixed` BEFORE considering movements, so
    the fold must too — a fixed asset with a movement history is exactly the
    case where forgetting it produces a confident wrong answer."""
    a, _ = _adapter([_log(JAN, A, internal_id=1)], is_fixed=True)
    assert a.was_at_location(COW, A, JUN) is False


# --------------------------------------------------------------------------- #
# 2. The fan-out folds over the source's own index                             #
# --------------------------------------------------------------------------- #
def test_the_fan_out_reaches_candidates_through_the_movement_logs() -> None:
    """PROPERTY, and not merely a performance one. Walking every asset in every
    bundle and folding each one's whole history is O(assets x log-bundles) and
    does not finish against a shared oracle — it was written that way first and
    had to be killed mid-recording. The log-side filter is available where the
    asset-side one is not: `filter[location.id]` answers on a LOG (the
    relationship is stored) and 500s on an ASSET (its location is computed).

    Correctness is preserved in both directions: every candidate is re-checked
    against the source's own answer, so an asset that moved away is dropped; and
    an asset no movement log names cannot be at the location at all.
    """
    a, t = _adapter()
    a.assets_at_location_count(A)
    assert any("/api/log/" in p and "filter[location.id]" in p for p in t.paths)
    assert not any(p.startswith("/api/asset/animal?") for p in t.paths), (
        "the fan-out must not walk the whole asset index"
    )


def test_the_fan_out_counts_membership_the_source_states() -> None:
    """The stub's movement log names the cow, but the cow's own delivered
    location is empty — so the source says it is not there and the count is 0,
    even though a movement to A exists. Candidacy is not membership."""
    a, _ = _adapter([_log(JAN, A, internal_id=1)])
    assert a.assets_at_location_count(A) == 0


# --------------------------------------------------------------------------- #
# 3. Authority                                                                 #
# --------------------------------------------------------------------------- #
@pytest.mark.parametrize("term", ["was_at_location", "assets_at_location_count"])
def test_both_folds_are_derived_and_cited(term: str) -> None:
    from ctkr.oracle.probes import DERIVED

    spec = PROBE_CONTRACT[term]
    assert spec.authority == DERIVED, "a fold of ours is never a transcription"
    assert spec.is_evidence, spec.unvalidated_reason
    assert "AssetLocation" in spec.validated_against


def test_the_as_of_term_is_distinct_from_the_now_term() -> None:
    """One ProbeSpec carries one authority. is_at_location TRANSCRIBES the
    source's computed answer; was_at_location COMPUTES one. Folding them into a
    single term with an optional instant would let the transcription's standing
    launder the derivation — and would have rotated a bound term's
    derivation_id, invalidating the pack recorded under it."""
    now, past = PROBE_CONTRACT["is_at_location"], PROBE_CONTRACT["was_at_location"]
    assert now.assertion != past.assertion
    assert not any(p.field_name == "as_of" for p in now.params)
    assert any(p.field_name == "as_of" for p in past.params)
    assert now.derivation_id != past.derivation_id


# --------------------------------------------------------------------------- #
# 4. The as-of instant must be absolute, and must reach a probe that takes one  #
# --------------------------------------------------------------------------- #
def _pack(probes: list[dict]) -> dict:
    return {"version": 1, "flows": [{
        "key": "k", "title": "t", "feature": "asset-location-movement",
        "glossary_terms": ["land", "animal", "move", "was_at_location"],
        "given": [
            {"entity": "land", "alias": "A", "name": "Field", "is_location": True},
            {"entity": "animal", "alias": "COW", "name": "Cow"}],
        "when": [{"action": "move", "against": ["COW"], "locations": ["A"],
                  "status": "done", "at": JAN}],
        "probes": probes,
    }]}


def test_a_relative_as_of_is_refused() -> None:
    """The w0b defect, in the one place it could still happen: an offset is
    resolved against the clock of whoever is running, so a fixture carrying one
    asks a different question every run. w0b self-verified at 63.6% for exactly
    this, every failure a uniform +24s, and it was caught only because someone
    happened to self-verify twice."""
    with pytest.raises(FlowSpecError, match="ABSOLUTE ISO-8601 instant"):
        flows_from_obj(_pack([{"assert": "was_at_location", "subject": "COW",
                               "other": "A", "as_of": "-3600"}]))


def test_a_malformed_as_of_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="not an ISO-8601 instant"):
        flows_from_obj(_pack([{"assert": "was_at_location", "subject": "COW",
                               "other": "A", "as_of": "last March"}]))


def test_an_as_of_on_a_probe_that_does_not_take_one_is_refused() -> None:
    """It would never reach the implementation — the contract builds the call
    from `spec.params` — so the fixture would read NOW while claiming to ask
    about a moment. The silent-drop family, one level up."""
    with pytest.raises(FlowSpecError, match="does not take an as-of instant"):
        flows_from_obj(_pack([{"assert": "is_at_location", "subject": "COW",
                               "other": "A", "as_of": MAR}]))


def test_a_valid_as_of_probe_loads() -> None:
    flows = flows_from_obj(_pack([{"assert": "was_at_location", "subject": "COW",
                                   "other": "A", "as_of": MAR}]))
    assert flows[0].probes[0].as_of == MAR


def test_the_fixture_validator_enforces_the_same_as_of_rules() -> None:
    fx = SemanticFixture(
        title="t", feature="asset-location-movement",
        glossary_terms=["animal", "is_at_location"],
        given=[GivenStep(entity="animal", alias="COW", name="Cow"),
               GivenStep(entity="land", alias="A", name="Field")],
        when=[],
        then=[ThenAssertion(**{"assert": "is_at_location"}, subject="COW",
                            other="A", as_of="-3600", value=False,
                            witness="w1")],
        provenance=Provenance(source_system="farmOS"),
    )
    messages = " ".join(e.message for e in validate_fixture(fx))
    assert "ABSOLUTE ISO-8601 instant" in messages
    assert "does not take an as-of instant" in messages


# --------------------------------------------------------------------------- #
# 5. Seal stability + discrimination                                           #
# --------------------------------------------------------------------------- #
#: content_id() of _golden() computed with the PRE-b0s code, checked out from
#: git (240d768) into a clean tree and run there.
GOLDEN_PRE_B0S_ID = "674583c8ae642212c690ad5dec06478c"


def _golden(**over) -> SemanticFixture:
    t = ThenAssertion(**{"assert": "asset_active"}, subject="A", value=False,
                      witness="w1")
    return SemanticFixture(
        title="Golden pre-b0s location-era fixture", feature="asset-lifecycle",
        glossary_terms=["land", "asset_active"],
        given=[GivenStep(entity="land", alias="A", name="North Field")],
        when=[WhenStep(action="archive_asset", ref="A")],
        then=[t.model_copy(update=over)],
        provenance=Provenance(source_system="farmOS", source_version="4.x",
                              flow="golden",
                              recorded_at="2026-07-28T00:00:00+00:00"),
    )


def test_as_of_at_its_default_does_not_change_a_sealed_id() -> None:
    assert _golden().content_id() == GOLDEN_PRE_B0S_ID


def test_asking_about_a_moment_changes_the_id() -> None:
    assert _golden(as_of=MAR).content_id() != GOLDEN_PRE_B0S_ID


def test_a_witness_to_a_now_read_is_not_a_witness_to_an_as_of_read() -> None:
    """The descriptor is compared key-for-key at load, so the instant has to be
    part of the QUESTION or a now-read's witness would endorse an as-of claim."""
    from ctkr.oracle.fixtures import probe_descriptor

    now = ThenAssertion(**{"assert": "was_at_location"}, subject="COW",
                        other="A", value=True, witness="w")
    past = now.model_copy(update={"as_of": MAR})
    assert probe_descriptor(now) != probe_descriptor(past)
    # ...and a now-read's descriptor is unchanged from before the field existed,
    # so every pack already on disk still matches its own witnesses.
    assert "as_of" not in probe_descriptor(now)
