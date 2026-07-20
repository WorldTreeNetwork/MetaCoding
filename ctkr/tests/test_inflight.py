"""In-flight decision emission (MetaCoding-9h5.22).

Every mechanism the port loop had was build-time or after-the-fact. These tests
pin the behaviours that make mid-wave surfacing possible, each modelled on a real
event from 2026-07-20 rather than an invented scenario.
"""

from __future__ import annotations

import json

import pytest

from ctkr import inflight
from ctkr.inflight import InflightError, InflightRecord


def _rec(agent: str, topic: str, kind: str = "punt", **kw) -> InflightRecord:
    return InflightRecord(
        agent=agent, feature=kw.pop("feature", "farm_x"), topic=topic,
        kind=kind, statement=kw.pop("statement", "something is undecided"), **kw,
    )


def test_a_record_round_trips_through_the_ledger(tmp_path) -> None:
    inflight.emit(_rec("w1-inventory", "same-time-tiebreak"), tmp_path)
    read = inflight.read(tmp_path)
    assert len(read.records) == 1
    assert read.records[0].agent == "w1-inventory"
    assert not read.malformed


def test_the_ledger_is_append_only_across_agents(tmp_path) -> None:
    inflight.emit(_rec("a", "t"), tmp_path)
    inflight.emit(_rec("b", "t"), tmp_path)
    assert [r.agent for r in inflight.read(tmp_path).records] == ["a", "b"]


def test_a_missing_ledger_reads_empty_rather_than_raising(tmp_path) -> None:
    """An orchestrator polls before anyone has emitted; that is not an error."""
    read = inflight.read(tmp_path)
    assert read.records == [] and read.malformed == []


def test_a_malformed_line_is_reported_not_silently_dropped(tmp_path) -> None:
    """An agent that got the shape wrong is still an agent telling us something."""
    inflight.emit(_rec("good", "t"), tmp_path)
    p = inflight.ledger_path(tmp_path)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps({"agent": "sloppy", "feature": "f", "topic": "t"}) + "\n")
        fh.write("not json at all\n")
    read = inflight.read(tmp_path)
    assert len(read.records) == 1
    assert len(read.malformed) == 2


def test_an_agent_may_append_a_raw_line_without_importing_anything(tmp_path) -> None:
    """The contract is deliberately trivial: a TS/bash agent appends one line."""
    p = inflight.ledger_path(tmp_path)
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps({
        "agent": "w1-ts-builder", "feature": "farm_seeding", "topic": "seed-rate",
        "kind": "punt", "statement": "no rule for fractional seed rates",
        "event_kinds": ["log_recorded"],
    }) + "\n", encoding="utf-8")
    read = inflight.read(tmp_path)
    assert read.records[0].agent == "w1-ts-builder"
    assert read.records[0].event_kinds == ("log_recorded",)


def test_an_unknown_kind_is_refused() -> None:
    with pytest.raises(InflightError, match="not one of"):
        inflight.validate({"agent": "a", "feature": "f", "topic": "t",
                           "kind": "vibes", "statement": "s"})


# --------------------------------------------------------------------------- #
# Punt-promotion — the 7/7 HLC pattern, mechanized                             #
# --------------------------------------------------------------------------- #
def test_two_distinct_agents_on_one_topic_promote_it() -> None:
    records = [
        _rec("w1-inventory", "same-time-tiebreak"),
        _rec("w1-harvest", "same-time-tiebreak"),
    ]
    [(topic, rs)] = inflight.promotion_candidates(records)
    assert topic == "same-time-tiebreak"
    assert len(rs) == 2


def test_one_agent_repeating_itself_is_one_signal_not_a_pattern() -> None:
    """Seven builders is the evidence; seven mentions by one builder is not."""
    records = [_rec("w1-inventory", "same-time-tiebreak") for _ in range(5)]
    assert inflight.promotion_candidates(records) == []


def test_an_invented_decision_counts_toward_promotion() -> None:
    """w0b-1 was invented mid-build; that is the same missing-kernel signal."""
    records = [
        _rec("a", "parent-lineage", kind="invented"),
        _rec("b", "parent-lineage", kind="punt"),
    ]
    assert [t for t, _ in inflight.promotion_candidates(records)] == ["parent-lineage"]


def test_a_conflict_does_not_accumulate_it_demands_attention() -> None:
    """A contradiction with a bound decision needs answering now, not counting."""
    records = [
        _rec("a", "pending-status-gates", kind="conflict"),
        _rec("b", "pending-status-gates", kind="conflict"),
    ]
    assert inflight.promotion_candidates(records) == []
    assert len(inflight.needs_attention(records)) == 2


def test_blocked_agents_surface_immediately() -> None:
    records = [_rec("a", "t", kind="blocked", statement="cannot proceed")]
    assert inflight.needs_attention(records)[0].agent == "a"


# --------------------------------------------------------------------------- #
# Interrupt targeting — the join to the feature x kind graph                    #
# --------------------------------------------------------------------------- #
def test_an_interrupt_targets_only_the_agents_touching_the_kind() -> None:
    records = [
        _rec("w1-animal", "parent-lineage", event_kinds=("birth_recorded",)),
        _rec("w1-lifecycle", "pending", event_kinds=("birth_recorded", "log_recorded")),
        _rec("w1-inventory", "tiebreak", event_kinds=("inventory_adjustment",)),
    ]
    assert inflight.affected_agents(records, {"birth_recorded"}) == [
        "w1-animal", "w1-lifecycle",
    ]
    # A wave-wide stop is what targeting exists to avoid.
    assert inflight.affected_agents(records, {"geometry_set"}) == []
