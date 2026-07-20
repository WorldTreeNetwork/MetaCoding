"""The fixture schema must not admit fixtures that cannot score (blocker B4).

Two defects, both found the expensive way — after the fixtures were already
recorded and, in one case, already used to judge a build:

1. A relative effective time plus a timestamp-returning probe distils a value
   computed from the recording run's wall clock. w0b first self-verified at
   63.6%, every failure a uniform +24s, caught only because someone happened to
   run the self-verify twice.
2. Several writes sharing one effective time leave the outcome to the SOURCE's
   tie-break. w0a observed 3.0, which is farmOS's insertion-id fingerprint — the
   same three events in six orders give four different values. It scored as a
   pass for the wrong reason.
"""

from __future__ import annotations

import pytest

from ctkr.oracle.fixtures import GivenStep, WhenStep
from ctkr.oracle.flowspec_io import FlowSpecError, flow_from_dict
from ctkr.oracle.recorder import FlowSpec, detect_order_sensitivity


def _pack(at: str, probe: str) -> dict:
    return {
        "key": "f", "title": "a flow", "feature": "birth",
        "glossary_terms": ["animal", "record_birth"],
        "given": [{"entity": "animal", "alias": "CHILD", "name": "Kid"}],
        "when": [{"action": "record_birth", "alias": "B", "ref": "CHILD",
                  "name": "birth", "status": "done", "at": at}],
        "probes": [{"assert": probe, "subject": "CHILD"}],
    }


def test_relative_time_plus_a_timestamp_probe_is_rejected() -> None:
    with pytest.raises(FlowSpecError, match="could never self-verify"):
        flow_from_dict(_pack("-604800", "birth_date"))


def test_absolute_time_with_a_timestamp_probe_is_fine() -> None:
    flow = flow_from_dict(_pack("2026-07-13T12:00:00+00:00", "birth_date"))
    assert flow.key == "f"


def test_relative_time_is_fine_when_no_probe_returns_an_instant() -> None:
    """Relativity is not the defect — relativity plus an observed instant is."""
    flow = flow_from_dict(_pack("-604800", "parent_count"))
    assert flow.when[0].at == "-604800"


def _timed_flow(ats: list[str]) -> FlowSpec:
    return FlowSpec(
        key="k", title="t", feature="core.inventory", glossary_terms=[],
        given=[GivenStep(entity="equipment", alias="bin", name="feed bin")],
        when=[
            WhenStep(action="record_inventory_adjustment", alias=f"a{i}",
                     kind="increment", status="done", against=["bin"],
                     quantities=[], at=at)
            for i, at in enumerate(ats)
        ],
    )


def test_writes_sharing_one_effective_time_are_detected_as_order_sensitive() -> None:
    why = detect_order_sensitivity(_timed_flow(["-20000", "-20000", "-20000"]))
    assert "share one effective time" in why
    assert "tie-break" in why


def test_distinct_effective_times_are_not_order_sensitive() -> None:
    assert detect_order_sensitivity(_timed_flow(["-30000", "-20000"])) == ""


def test_untimed_writes_are_not_order_sensitive() -> None:
    assert detect_order_sensitivity(_timed_flow(["", ""])) == ""


def test_declaring_corroboration_only_costs_a_reason() -> None:
    d = _pack("2026-07-13T12:00:00+00:00", "parent_count")
    d["corroboration_only"] = True
    with pytest.raises(FlowSpecError, match="requires a reason"):
        flow_from_dict(d)
