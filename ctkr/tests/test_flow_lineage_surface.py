"""The MetaCoding-b0s lineage batch — clear-a-mother, and the second parent.

Two of the thirteen named DSL expressibility gaps
(``eval/ctkr/results/wave1-readiness-2026-07-20.md`` §2):

* **no way to clear a birth's mother.** ``steps.py`` read ``parents: []`` as
  "leave unchanged" (``w.parents if w.parents else None``), and JSON cannot tell
  an empty list from an absent one anyway, so the semantic "a recorded birth's
  mother is retracted" was unauthorable. ``clear_parents`` says the empty set
  out loud; the three readings (a list / the empty set / unstated) are now three.
* **no second parent.** ``record_birth`` accepted a list and the farmOS adapter
  sent ``parent_handles[0]``, dropping the rest in silence. The flow could
  always SAY two — nobody was told the second went nowhere.

**The fake-it question.** For the clear: a port could implement it as a no-op,
or over-implement it by retracting the child's parentage too. Live farmOS does
neither (validated 2026-07-28), so the discriminating flow pins BOTH edges —
the birth record's mother goes, the child's parent stays. For the second parent:
an adapter could keep truncating and nothing would notice, so the test asserts
the exact boundary request carries every parent the step stated, and lets the
SOURCE state its own limit.

Live-source validation, farmOS 4.x oracle at ``localhost:8095``, 2026-07-28:

* two parents on a birth record ->
  ``422 "mother: Mother: this field cannot hold more than 1 values."``
* record birth from a dam -> child parent_count 1, dam is a parent;
  clear the mother -> mother gone, child parent_count STILL 1, dam STILL a
  parent (``farm_birth`` ``EntityHooks::syncBirthChildren`` appends on save and
  never retracts);
* child already has a sire -> recording a birth from a dam does NOT add her
  (the hook appends only when the child has no parents at all);
* ``set_parents([sire, dam])`` -> parent_count 2; ``set_parents([])`` -> 0.
"""

from __future__ import annotations

import json

import pytest

from ctkr.oracle.adapter import AdapterError, Handle
from ctkr.oracle.farmos_adapter import FarmOSAdapter, FarmOSClient
from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
    validate_fixture,
)
from ctkr.oracle.flowspec_io import (
    FlowSpecError,
    dump_flows,
    flows_from_obj,
    when_from_dict,
)
from ctkr.oracle.steps import apply_when


# --------------------------------------------------------------------------- #
# A recording adapter that captures the boundary requests                      #
# --------------------------------------------------------------------------- #
class _Transport:
    """Captures every request and answers with a plausible JSON:API document."""

    def __init__(self) -> None:
        self.calls: list[tuple[str, str, dict | None]] = []
        self.refuse_multi_mother = True

    def __call__(self, method: str, path: str, body: bytes | None, headers: dict):
        if path == "/oauth/token":
            return json.dumps({"access_token": "t", "expires_in": 3600})
        doc = json.loads(body) if body else None
        self.calls.append((method, path, doc))
        # The live source's own answer to a two-valued `mother` (validated
        # 2026-07-28). Modelled here so the refusal path is covered offline.
        if self.refuse_multi_mother and doc:
            mother = (((doc.get("data") or {}).get("relationships") or {})
                      .get("mother") or {}).get("data")
            if isinstance(mother, list) and len(mother) > 1:
                raise AdapterError(
                    f"{method} {path} -> 422: mother: Mother: this field "
                    f"cannot hold more than 1 values."
                )
        return json.dumps({"data": {"type": "log--birth", "id": "log-uuid"}})


def _adapter() -> tuple[FarmOSAdapter, _Transport]:
    t = _Transport()
    a = FarmOSAdapter(FarmOSClient("http://localhost:8095", "u", "p", transport=t))
    a.open()
    return a, t


def _last_body(t: _Transport, method: str) -> dict:
    return next(d for m, _, d in reversed(t.calls) if m == method and d)


ANIMAL: Handle = "asset:animal:child-uuid"
DAM: Handle = "asset:animal:dam-uuid"
SIRE: Handle = "asset:animal:sire-uuid"
BIRTH: Handle = "log:birth:birth-uuid"


# --------------------------------------------------------------------------- #
# 1. clear-a-mother: three readings, not two                                   #
# --------------------------------------------------------------------------- #
def test_clear_parents_sends_a_null_mother() -> None:
    a, t = _adapter()
    apply_when(a, WhenStep(action="correct_birth", ref="B", clear_parents=True),
               {"B": BIRTH})
    rels = _last_body(t, "PATCH")["data"]["relationships"]
    assert rels["mother"] == {"data": None}


def test_an_unstated_parentage_does_not_touch_the_mother() -> None:
    """`correct_birth` with no parentage clause restates the TIME only. This is
    the reading `parents: []` used to be collapsed into, and it must survive:
    conflating them in the other direction would silently clear every timed
    correction ever recorded."""
    a, t = _adapter()
    apply_when(a, WhenStep(action="correct_birth", ref="B", at="-3600"),
               {"B": BIRTH})
    assert "relationships" not in _last_body(t, "PATCH")["data"]


def test_naming_parents_sends_them() -> None:
    a, t = _adapter()
    apply_when(a, WhenStep(action="correct_birth", ref="B", parents=["D"]),
               {"B": BIRTH, "D": DAM})
    rels = _last_body(t, "PATCH")["data"]["relationships"]
    assert rels["mother"]["data"] == {"type": "asset--animal", "id": "dam-uuid"}


def test_set_parents_clear_sends_an_empty_set() -> None:
    a, t = _adapter()
    apply_when(a, WhenStep(action="set_parents", ref="A", clear_parents=True),
               {"A": ANIMAL})
    rels = _last_body(t, "PATCH")["data"]["relationships"]
    assert rels["parent"] == {"data": []}


# --------------------------------------------------------------------------- #
# 2. The second parent — transmitted, and refused by the SOURCE                #
# --------------------------------------------------------------------------- #
def test_record_birth_transmits_every_parent_the_step_stated() -> None:
    """PROPERTY: the adapter states what the flow said. It used to send
    ``parent_handles[0]`` and drop the rest, so a flow naming two parents was
    scored against a recording of one — the silent-drop family."""
    a, t = _adapter()
    t.refuse_multi_mother = False
    a.record_birth(ANIMAL, [DAM, SIRE], "birth", "done")
    mother = _last_body(t, "POST")["data"]["relationships"]["mother"]["data"]
    assert [m["id"] for m in mother] == ["dam-uuid", "sire-uuid"]


def test_a_second_parent_on_a_birth_record_is_refused_by_the_source() -> None:
    """The refusal is the SOURCE's, in its own words — not an adapter opinion.
    An adapter-side guard would have substituted our sentence for farmOS's, and
    a refusal is only BOUNDARY evidence while it is the source that states it."""
    a, _ = _adapter()
    with pytest.raises(AdapterError, match="cannot hold more than 1 values"):
        a.record_birth(ANIMAL, [DAM, SIRE], "birth", "done")


def test_a_single_parent_is_sent_as_one_reference_not_a_list() -> None:
    """JSON:API shape follows cardinality; a single-valued relationship takes an
    object. Sending `[ref]` for one parent would 422 every lineage flow ever
    recorded."""
    a, t = _adapter()
    a.record_birth(ANIMAL, [DAM], "birth", "done")
    mother = _last_body(t, "POST")["data"]["relationships"]["mother"]["data"]
    assert mother == {"type": "asset--animal", "id": "dam-uuid"}


def test_two_parents_on_the_ANIMAL_are_expressible() -> None:
    """What farmOS refuses is a birth RECORD with two mothers. The animal's own
    `parent` field is multi-valued (validated live), so the semantic itself is
    reachable — through `set_parents`, which is the point of the refusal."""
    a, t = _adapter()
    apply_when(a, WhenStep(action="set_parents", ref="A", parents=["D", "S"]),
               {"A": ANIMAL, "D": DAM, "S": SIRE})
    parent = _last_body(t, "PATCH")["data"]["relationships"]["parent"]["data"]
    assert [p["id"] for p in parent] == ["dam-uuid", "sire-uuid"]


# --------------------------------------------------------------------------- #
# 3. The rule a flow and a fixture are both held to                            #
# --------------------------------------------------------------------------- #
def _flow(when: list[dict]) -> dict:
    return {"version": 1, "flows": [{
        "key": "k", "title": "t", "feature": "lineage",
        "glossary_terms": ["animal", "record_birth", "parent_count"],
        "given": [{"entity": "animal", "alias": "A", "name": "Kid"},
                  {"entity": "animal", "alias": "D", "name": "Dam", "sex": "F"}],
        "when": when,
        "probes": [{"assert": "parent_count", "subject": "A"}],
    }]}


def test_a_step_cannot_both_name_parents_and_clear_them() -> None:
    with pytest.raises(FlowSpecError, match="cannot both name parents"):
        flows_from_obj(_flow([{"action": "set_parents", "ref": "A",
                               "parents": ["D"], "clear_parents": True}]))


def test_set_parents_must_state_a_parent_set() -> None:
    """An empty `set_parents` is either an authoring slip or a deliberate clear.
    The DSL makes the author say which rather than guessing."""
    with pytest.raises(FlowSpecError, match="not a clear"):
        flows_from_obj(_flow([{"action": "set_parents", "ref": "A"}]))


def test_correct_birth_with_no_parentage_clause_is_legal() -> None:
    """It means "restate the time only" — a real instruction, not an omission."""
    flows = flows_from_obj(_flow([
        {"action": "record_birth", "alias": "B", "ref": "A", "parents": ["D"]},
        {"action": "correct_birth", "ref": "B",
         "at": "2026-03-01T12:00:00+00:00"},
    ]))
    assert flows[0].when[1].parents == [] and not flows[0].when[1].clear_parents


def test_parentage_on_an_action_that_ignores_it_is_refused() -> None:
    with pytest.raises(FlowSpecError, match="state parentage"):
        flows_from_obj(_flow([{"action": "archive_asset", "ref": "A",
                               "clear_parents": True}]))


def test_the_fixture_validator_enforces_the_same_rule_as_the_loader() -> None:
    """A flow and the fixture it distils into share one interpreter; they must
    share one rule, or a pack can be recorded that no validator accepts."""
    fx = SemanticFixture(
        title="t", feature="lineage", glossary_terms=["animal", "parent_count"],
        given=[GivenStep(entity="animal", alias="A", name="Kid")],
        when=[WhenStep(action="set_parents", ref="A")],
        then=[ThenAssertion(**{"assert": "parent_count"}, subject="A", value=0,
                            witness="w1")],
        provenance=Provenance(source_system="farmOS"),
    )
    assert any("not a clear" in e.message for e in validate_fixture(fx))


# --------------------------------------------------------------------------- #
# 4. Seal stability + discrimination                                           #
# --------------------------------------------------------------------------- #
#: content_id() of _golden() computed with the PRE-b0s code — checked out from
#: git (240d768) into a clean tree and run there, not derived from the code
#: under test. A failure here means every sealed pack has been silently
#: re-identified; do not update the literal without understanding why.
GOLDEN_PRE_B0S_ID = "a4bb767a7ce459d451f41a1266772b37"


def _golden(**when_overrides) -> SemanticFixture:
    return SemanticFixture(
        title="Golden pre-b0s lineage fixture",
        feature="lineage",
        glossary_terms=["animal", "set_parents", "parent_count"],
        given=[GivenStep(entity="animal", alias="A", name="Kid"),
               GivenStep(entity="animal", alias="D", name="Dam", sex="F")],
        when=[WhenStep(action="set_parents", ref="A", parents=["D"],
                       **when_overrides)],
        then=[ThenAssertion(**{"assert": "parent_count"}, subject="A", value=1,
                            witness="w1")],
        provenance=Provenance(source_system="farmOS", source_version="4.x",
                              flow="golden",
                              recorded_at="2026-07-28T00:00:00+00:00"),
    )


def test_clear_parents_at_its_default_does_not_change_a_sealed_id() -> None:
    assert _golden().content_id() == GOLDEN_PRE_B0S_ID


def test_using_clear_parents_changes_the_id() -> None:
    """Discrimination: a port cannot be scored against a fixture whose inputs
    it did not reproduce."""
    fx = _golden()
    fx.when[0] = WhenStep(action="set_parents", ref="A", clear_parents=True)
    assert fx.content_id() != GOLDEN_PRE_B0S_ID


def test_an_unstated_clear_does_not_appear_in_a_round_tripped_pack(tmp_path) -> None:
    pack = _flow([{"action": "set_parents", "ref": "A", "parents": ["D"]}])
    dump_flows(flows_from_obj(pack), tmp_path / "p.json")
    text = (tmp_path / "p.json").read_text(encoding="utf-8")
    assert "clear_parents" not in text
    # ...and a STATED one does.
    pack2 = _flow([{"action": "set_parents", "ref": "A", "clear_parents": True}])
    dump_flows(flows_from_obj(pack2), tmp_path / "q.json")
    assert "clear_parents" in (tmp_path / "q.json").read_text(encoding="utf-8")


# --------------------------------------------------------------------------- #
# 5. The silent-drop property, for the WHEN clause                             #
# --------------------------------------------------------------------------- #
def test_every_accepted_when_key_reaches_the_when_step() -> None:
    """PROPERTY (the `_GIVEN_KEYS` guard in test_flow_write_surface, lifted to
    the WHEN clause — where `clear_parents` would have been the next victim): a
    key `_WHEN_KEYS` accepts but `when_from_dict` does not map is SILENTLY
    DROPPED. The flow validates, the recording proceeds with defaults, and the
    stated value is lost."""
    from ctkr.oracle.flowspec_io import _WHEN_KEYS

    sample: dict[str, object] = {
        "action": "record_log", "alias": "L", "ref": "", "name": "N",
        "kind": "harvest", "status": "done", "against": ["A"], "group": "",
        "quantities": [], "at": "2026-03-01T12:00:00+00:00", "parents": [],
        "names": ["Nick"], "lot_number": "LOT-1", "equipment": ["E"],
        "clear_parents": False,
        # movement (MetaCoding-b0s). `locations`/`geometry` cannot be set HERE:
        # only `move` states them and this sample is a record_log. Their
        # mapping is asserted on its own below.
        "locations": [], "geometry": "",
        "lab_received_date": "2026-03-01T12:00:00+00:00",
        "lab_processed_date": "2026-03-02T12:00:00+00:00",
        "lab_test_type": "soil", "soil_texture": "loam", "lab": "Ag Lab",
    }
    assert set(sample) == set(_WHEN_KEYS), (
        "extend `sample` when _WHEN_KEYS grows — that is the point"
    )
    w = when_from_dict(dict(sample), "when[0]")
    defaults = WhenStep(action="record_log")
    dropped = [
        k for k, v in sample.items()
        if k != "action" and getattr(w, k) == getattr(defaults, k)
        and getattr(w, k) != v
    ]
    assert not dropped, f"accepted but silently dropped: {dropped}"

    # `clear_parents` specifically, at its non-default value, on an action that
    # owns parentage (the sample above uses record_log, where True is refused).
    w2 = when_from_dict(
        {"action": "set_parents", "ref": "A", "clear_parents": True}, "when[0]")
    assert w2.clear_parents is True

    # ...and the movement fields, on the one action that states them.
    w3 = when_from_dict(
        {"action": "move", "against": ["A"], "locations": ["L"],
         "geometry": "POINT (30 40)", "status": "done"}, "when[0]")
    assert w3.locations == ["L"] and w3.geometry == "POINT (30 40)"
