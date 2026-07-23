"""Recorder + distiller — observe live farmOS, distill semantic fixtures (Phase 2).

A **scripted session** of core value-flows (asset lifecycle, harvest log +
quantity, log status transition, group membership) is run against a live farmOS
through the adapter. Every JSON:API request/response pair is recorded
(:class:`Observation`). Each flow is then **distilled** into a semantic fixture
whose ``then`` assertions carry the VALUES the live system actually delivered —
read back at the boundary, mapped to glossary terms, stripped of every id and
field name. That is the distillation discipline of ``decomposition-schema.md``
§5: the fixture keeps the value, discards the representation.

Self-verification (see :mod:`ctkr.oracle.runner`) re-runs these distilled
fixtures against the same farmOS: because the recorded value is exactly what the
source delivers, they must pass — a fixture that does not is a bad distillation.

The flows are declarative :class:`FlowSpec`s. The recorder executes ``given`` +
``when`` to reach the state, then observes each :class:`Probe` to fill the
expected value. No expected values are hand-authored — they are all observed.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from blake3 import blake3
from pydantic import BaseModel

from ctkr.oracle.adapter import AdapterError, Handle
from ctkr.oracle.farmos_adapter import FarmOSAdapter, FarmOSClient
from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    QuantitySpec,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
    order_sensitivity,
    probe_descriptor,
)
from ctkr.oracle.probes import PROBE_CONTRACT
from ctkr.oracle.steps import apply_given, apply_when, flow_now


#: A boundary request/response pair — transport-level provenance.
BOUNDARY_RECORD = "boundary"
#: A WITNESS: the recorder's note of the VALUE a probe read from the source.
#: Until this existed, an Observation's excerpt was ``{"type","id"}`` or
#: ``{"count":n}`` — the recorder never recorded the value a probe observed, so
#: the witness that would catch a forged expected value was in the pack and mute.
WITNESS_RECORD = "witness"


class Observation(BaseModel):
    """One recorded fact — a boundary exchange, or a witnessed probe value."""

    obs_id: str
    method: str
    path: str
    request: dict[str, Any] | None = None
    response_status: str = "ok"
    response_excerpt: dict[str, Any] | None = None
    #: :data:`BOUNDARY_RECORD` or :data:`WITNESS_RECORD`.
    record: str = BOUNDARY_RECORD
    #: WITNESS only: which probe was asked, in the assertion's own vocabulary.
    #: Compared field-for-field at load against the assertion that cites it, so a
    #: witness cannot be re-pointed at a different question than it answered.
    probe: dict[str, Any] | None = None
    #: WITNESS only: the value the SOURCE delivered. This is the fact a fixture's
    #: expected value is checked against.
    observed: Any = None


class RecordingClient(FarmOSClient):
    """A FarmOSClient that logs every request/response as an :class:`Observation`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.observations: list[Observation] = []
        self._seq = 0

    def request(
        self, method: str, path: str, doc: dict | None = None
    ) -> dict[str, Any]:
        try:
            resp = super().request(method, path, doc)
        except AdapterError as exc:
            # A REFUSED write is evidence, and it used to be the one thing the
            # recorder threw away: the exception propagated before any
            # observation was appended, so the source's own words ("Kid Fennel
            # already has a birth log") never reached the provenance file.
            self._seq += 1
            self.observations.append(
                Observation(
                    obs_id=blake3(f"{self._seq}:{method}:{path}".encode()).hexdigest()[:16],
                    method=method, path=path, request=doc,
                    response_status="refused",
                    response_excerpt={"refusal": str(exc)[:600]},
                )
            )
            raise
        self._seq += 1
        obs_id = blake3(f"{self._seq}:{method}:{path}".encode()).hexdigest()[:16]
        # keep a compact excerpt — ids/type of the primary resource only
        excerpt: dict[str, Any] | None = None
        data = resp.get("data") if isinstance(resp, dict) else None
        if isinstance(data, dict):
            excerpt = {"type": data.get("type"), "id": data.get("id")}
        elif isinstance(data, list):
            excerpt = {"count": len(data)}
        self.observations.append(
            Observation(
                obs_id=obs_id, method=method, path=path,
                request=doc, response_excerpt=excerpt,
            )
        )
        return resp


# --------------------------------------------------------------------------- #
# Flow specification                                                          #
# --------------------------------------------------------------------------- #
@dataclass
class Probe:
    """A `then` assertion whose expected value is filled from observation."""

    assert_: str
    subject: str
    measure: str = ""
    unit: str = ""
    kind: str = ""
    group: str = ""
    other: str = ""
    op: str = "=="


@dataclass
class FlowSpec:
    """One scripted value-flow to record and distill into a fixture."""

    key: str
    title: str
    feature: str
    glossary_terms: list[str]
    given: list[GivenStep]
    when: list[WhenStep]
    probes: list[Probe] = field(default_factory=list)
    #: This flow attempts something the source is expected to REFUSE, and the
    #: refusal is the semantic under test (MetaCoding-o8b). Recording used to die
    #: on the first AdapterError, so the sharpest signal a source can give —
    #: "you may not do that" — killed the run instead of becoming evidence. The
    #: wave-0 pilot lost farmOS's UniqueBirthLog 422 exactly this way.
    #:
    #: The expectation is NOT the observation: if the source ACCEPTS the write,
    #: that is recorded as a contradiction, never quietly turned into a fixture.
    expect_refusal: bool = False
    #: This flow's observed value is an artifact of how the SOURCE ordered things
    #: (e.g. several writes sharing one effective time), so it corroborates a
    #: decision but must never SCORE an implementation — a port ordering by its
    #: own rule will legitimately produce a different value (MetaCoding-bdy).
    corroboration_only: bool = False
    corroboration_reason: str = ""


def _q(measure: str, value: float, unit: str, label: str = "") -> QuantitySpec:
    return QuantitySpec(measure=measure, value=value, unit=unit, label=label)


def core_flows() -> list[FlowSpec]:
    """The scripted session — core farmOS value-flows (asset/log/quantity/group)."""
    return [
        FlowSpec(
            key="asset-lifecycle-active",
            title="A newly created land asset is active",
            feature="asset-lifecycle",
            glossary_terms=["land", "asset_active"],
            given=[GivenStep(entity="land", alias="A", name="North Field")],
            when=[],
            probes=[Probe(assert_="asset_active", subject="A")],
        ),
        FlowSpec(
            key="asset-lifecycle-archived",
            title="An archived land asset is no longer active",
            feature="asset-lifecycle",
            glossary_terms=["land", "asset_active", "archive_asset"],
            given=[GivenStep(entity="land", alias="A", name="South Field")],
            when=[WhenStep(action="archive_asset", ref="A")],
            probes=[Probe(assert_="asset_active", subject="A")],
        ),
        FlowSpec(
            key="harvest-yield-single",
            title="Recording a harvest of X against an asset gives that asset a yield total of X",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "yield_total", "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Tomato Bed")],
            when=[
                WhenStep(
                    action="record_log", alias="L", kind="harvest", status="done",
                    name="Tomato harvest", against=["A"],
                    quantities=[_q("weight", 5, "kilogram", "yield")],
                )
            ],
            probes=[
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                Probe(assert_="log_count", subject="A", kind="harvest"),
                Probe(assert_="quantity_recorded", subject="L", measure="weight",
                      unit="kilogram"),
            ],
        ),
        FlowSpec(
            key="harvest-yield-accumulates",
            title="Two harvests against an asset sum into its yield total",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "yield_total", "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Squash Patch")],
            when=[
                WhenStep(action="record_log", alias="L1", kind="harvest",
                         status="done", name="Harvest 1", against=["A"],
                         quantities=[_q("weight", 3, "kilogram", "yield")]),
                WhenStep(action="record_log", alias="L2", kind="harvest",
                         status="done", name="Harvest 2", against=["A"],
                         quantities=[_q("weight", 4, "kilogram", "yield")]),
            ],
            probes=[
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                Probe(assert_="log_count", subject="A", kind="harvest"),
            ],
        ),
        FlowSpec(
            key="log-status-pending",
            title="A harvest recorded as pending is delivered with pending status",
            feature="log-lifecycle",
            glossary_terms=["land", "harvest", "log_status", "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Pending Field")],
            when=[
                WhenStep(action="record_log", alias="L", kind="harvest",
                         status="pending", name="Planned harvest", against=["A"],
                         quantities=[_q("weight", 2, "kilogram", "yield")]),
            ],
            probes=[Probe(assert_="log_status", subject="L")],
        ),
        FlowSpec(
            key="log-status-transition",
            title="Marking a pending harvest done delivers it with done status",
            feature="log-lifecycle",
            glossary_terms=["land", "harvest", "log_status", "record_log",
                            "set_log_status"],
            given=[GivenStep(entity="land", alias="A", name="Transition Field")],
            when=[
                WhenStep(action="record_log", alias="L", kind="harvest",
                         status="pending", name="Harvest to complete", against=["A"],
                         quantities=[_q("weight", 6, "kilogram", "yield")]),
                WhenStep(action="set_log_status", ref="L", status="done"),
            ],
            probes=[Probe(assert_="log_status", subject="L")],
        ),
        FlowSpec(
            key="group-membership",
            title="Assigning an animal to a group makes it a member of that group",
            feature="group-membership",
            glossary_terms=["animal", "group", "group_member", "assign_to_group"],
            given=[
                GivenStep(entity="animal", alias="A", name="Bessie",
                          descriptor="Cattle"),
                GivenStep(entity="group", alias="G", name="Milking Herd"),
            ],
            when=[WhenStep(action="assign_to_group", ref="A", group="G")],
            probes=[Probe(assert_="group_member", subject="A", group="G")],
        ),
    ]


def hardening_flows() -> list[FlowSpec]:
    """Discriminating value-flows (bead MetaCoding-9h5.7).

    The canonical :func:`core_flows` pack tests only semantics recoverable from
    the adapter method names alone (ablation 9h5.4: both knockout cells passed
    7/7 blind). These flows assert values a builder **cannot** infer from a
    method name — they must be OBSERVED from the live source: pending logs count
    toward yield, measure/unit mismatch is excluded, a shared quantity attributes
    in full to every referenced asset, yield sums across *all* log kinds (not
    just harvest), archiving retires an asset without dropping its history,
    identical logs are not de-duplicated, and group membership is latest-wins.
    Every expected value is filled by observation in :func:`record_flow`; nothing
    here is hand-authored.
    """
    return [
        # 1. A pending harvest still contributes to yield total. The name
        #    "yield_total" does not tell you whether pending logs are included.
        FlowSpec(
            key="pending-contributes-to-yield",
            title="A pending harvest still contributes to the yield total",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "yield_total",
                            "log_status", "record_log", "pending"],
            given=[GivenStep(entity="land", alias="A", name="Pending Yield Field")],
            when=[
                WhenStep(action="record_log", alias="L", kind="harvest",
                         status="pending", name="Planned harvest", against=["A"],
                         quantities=[_q("weight", 5, "kilogram", "yield")]),
            ],
            probes=[
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                Probe(assert_="log_status", subject="L"),
            ],
        ),
        # 2. Yield total filters by BOTH measure and unit: a different measure or
        #    a different unit is excluded. Names cannot telegraph the filter.
        FlowSpec(
            key="measure-unit-mismatch-excluded",
            title="Yield total excludes quantities of a different measure or unit",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "volume", "yield_total",
                            "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Mismatch Field")],
            when=[
                WhenStep(action="record_log", alias="L", kind="harvest",
                         status="done", name="Weighed harvest", against=["A"],
                         quantities=[_q("weight", 5, "kilogram", "yield")]),
            ],
            probes=[
                # matching measure+unit — the control
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                # same measure, different unit — excluded
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="pound"),
                # different measure — excluded
                Probe(assert_="yield_total", subject="A", measure="volume",
                      unit="liter"),
            ],
        ),
        # 3. One log against two assets attributes the quantity IN FULL to each
        #    asset (it is not split between them).
        FlowSpec(
            key="multi-asset-full-attribution",
            title="A harvest against two assets attributes its full quantity to each",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "yield_total",
                            "log_count", "record_log"],
            given=[
                GivenStep(entity="land", alias="A", name="Shared Bed A"),
                GivenStep(entity="land", alias="B", name="Shared Bed B"),
            ],
            when=[
                WhenStep(action="record_log", alias="L", kind="harvest",
                         status="done", name="Shared harvest", against=["A", "B"],
                         quantities=[_q("weight", 5, "kilogram", "yield")]),
            ],
            probes=[
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                Probe(assert_="yield_total", subject="B", measure="weight",
                      unit="kilogram"),
                Probe(assert_="log_count", subject="A", kind="harvest"),
                Probe(assert_="log_count", subject="B", kind="harvest"),
            ],
        ),
        # 4. Log count and yield both include pending logs: neither filters by
        #    status. A builder might assume "count" means "completed count".
        FlowSpec(
            key="logcount-ignores-status",
            title="Log count and yield include both pending and done harvests",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "yield_total",
                            "log_count", "log_status", "record_log", "pending",
                            "done"],
            given=[GivenStep(entity="land", alias="A", name="Mixed Status Field")],
            when=[
                WhenStep(action="record_log", alias="L1", kind="harvest",
                         status="pending", name="Pending harvest", against=["A"],
                         quantities=[_q("weight", 2, "kilogram", "yield")]),
                WhenStep(action="record_log", alias="L2", kind="harvest",
                         status="done", name="Done harvest", against=["A"],
                         quantities=[_q("weight", 4, "kilogram", "yield")]),
            ],
            probes=[
                Probe(assert_="log_count", subject="A", kind="harvest"),
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
            ],
        ),
        # 5. Log count isolates by kind: a mixed set of kinds counts separately,
        #    and a kind with no logs is zero.
        FlowSpec(
            key="logcount-isolated-by-kind",
            title="Log count is isolated per kind across a mixed set of logs",
            feature="log-lifecycle",
            glossary_terms=["land", "harvest", "input", "observation", "seeding",
                            "log_count", "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Mixed Kinds Field")],
            when=[
                WhenStep(action="record_log", alias="L1", kind="harvest",
                         status="done", name="A harvest", against=["A"],
                         quantities=[_q("weight", 1, "kilogram", "yield")]),
                WhenStep(action="record_log", alias="L2", kind="observation",
                         status="done", name="An observation", against=["A"]),
                WhenStep(action="record_log", alias="L3", kind="input",
                         status="done", name="An input", against=["A"],
                         quantities=[_q("weight", 3, "kilogram", "")]),
            ],
            probes=[
                Probe(assert_="log_count", subject="A", kind="harvest"),
                Probe(assert_="log_count", subject="A", kind="observation"),
                Probe(assert_="log_count", subject="A", kind="input"),
                Probe(assert_="log_count", subject="A", kind="seeding"),
            ],
        ),
        # 6. Yield total sums a measure across ALL log kinds, not just harvest.
        #    The name "yield" strongly implies harvest-only; it is not.
        FlowSpec(
            key="yield-aggregates-across-kinds",
            title="Yield total sums a measure across all log kinds, not just harvest",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "input", "weight", "yield_total",
                            "log_count", "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Cross Kind Field")],
            when=[
                WhenStep(action="record_log", alias="L1", kind="harvest",
                         status="done", name="Harvest weight", against=["A"],
                         quantities=[_q("weight", 5, "kilogram", "yield")]),
                WhenStep(action="record_log", alias="L2", kind="input",
                         status="done", name="Input weight", against=["A"],
                         quantities=[_q("weight", 3, "kilogram", "")]),
            ],
            probes=[
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                Probe(assert_="log_count", subject="A", kind="harvest"),
                Probe(assert_="log_count", subject="A", kind="input"),
            ],
        ),
        # 7. Archiving an asset retires it from the active set but does NOT drop
        #    its recorded history — yield and log count survive.
        FlowSpec(
            key="archived-asset-retains-history",
            title="An archived asset is inactive but keeps its yield and log history",
            feature="asset-lifecycle",
            glossary_terms=["land", "harvest", "weight", "yield_total",
                            "log_count", "asset_active", "record_log",
                            "archive_asset"],
            given=[GivenStep(entity="land", alias="A", name="Retired Field")],
            when=[
                WhenStep(action="record_log", alias="L", kind="harvest",
                         status="done", name="Final harvest", against=["A"],
                         quantities=[_q("weight", 5, "kilogram", "yield")]),
                WhenStep(action="archive_asset", ref="A"),
            ],
            probes=[
                Probe(assert_="asset_active", subject="A"),
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                Probe(assert_="log_count", subject="A", kind="harvest"),
            ],
        ),
        # 8. Group membership is latest-wins: a second assignment revokes the
        #    first. Requires distinct assignment order to observe.
        FlowSpec(
            key="group-reassignment-latest-wins",
            title="Reassigning an animal to a new group revokes the prior membership",
            feature="group-membership",
            glossary_terms=["animal", "group", "group_member", "assign_to_group"],
            given=[
                GivenStep(entity="animal", alias="A", name="Roamer",
                          descriptor="Cattle"),
                GivenStep(entity="group", alias="G1", name="First Herd"),
                GivenStep(entity="group", alias="G2", name="Second Herd"),
            ],
            when=[
                WhenStep(action="assign_to_group", ref="A", group="G1"),
                WhenStep(action="assign_to_group", ref="A", group="G2"),
            ],
            probes=[
                Probe(assert_="group_member", subject="A", group="G2"),
                Probe(assert_="group_member", subject="A", group="G1"),
            ],
        ),
        # 8b. Group membership RECURSES. A in G1 and G1 in G2 makes A a member of
        #     G2 — farmOS's GroupMembership::getGroupMembers recurses BY DEFAULT
        #     ($recurse = TRUE). MetaCoding-ck2: no shipped pack discriminated
        #     the corrected transitive group_member from its regression, because
        #     core-pack's single direct assertion scores 1/1 for a port that
        #     recurses and for one that does not. This flow separates them: a
        #     non-recursive port answers group_member(A, G2) = False where farmOS
        #     answers True.
        FlowSpec(
            key="group-membership-recurses",
            title="An animal in a group that is itself in a group is a member of both",
            feature="group-membership",
            glossary_terms=["animal", "group", "group_member", "assign_to_group"],
            given=[
                GivenStep(entity="animal", alias="A", name="Ewe Yarrow",
                          descriptor="Sheep"),
                GivenStep(entity="group", alias="G1", name="Inner Flock"),
                GivenStep(entity="group", alias="G2", name="Outer Flock"),
                GivenStep(entity="group", alias="G3", name="Unrelated Flock"),
            ],
            when=[
                WhenStep(action="assign_to_group", ref="A", group="G1"),
                WhenStep(action="assign_to_group", ref="G1", group="G2"),
            ],
            probes=[
                # direct membership — the control every port gets right
                Probe(assert_="group_member", subject="A", group="G1"),
                # TRANSITIVE membership — the discriminating value
                Probe(assert_="group_member", subject="A", group="G2"),
                # the chain itself
                Probe(assert_="group_member", subject="G1", group="G2"),
                # and recursion does not leak into an unrelated group
                Probe(assert_="group_member", subject="A", group="G3"),
            ],
        ),
        # 9. Identical logs are NOT de-duplicated — an append-only history keeps
        #    both. (The birth-log uniqueness scenario, generalized: the live
        #    farmOS bare install has no farm_birth module, so the duplicate
        #    semantic is exercised on a harvest kind that IS present.)
        FlowSpec(
            key="duplicate-logs-not-deduplicated",
            title="Two identical harvests are both recorded, not de-duplicated",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "yield_total",
                            "log_count", "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Duplicate Field")],
            when=[
                WhenStep(action="record_log", alias="L1", kind="harvest",
                         status="done", name="Harvest", against=["A"],
                         quantities=[_q("weight", 5, "kilogram", "yield")]),
                WhenStep(action="record_log", alias="L2", kind="harvest",
                         status="done", name="Harvest", against=["A"],
                         quantities=[_q("weight", 5, "kilogram", "yield")]),
            ],
            probes=[
                Probe(assert_="log_count", subject="A", kind="harvest"),
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
            ],
        ),
        # 10. Two measures on ONE log are tracked independently; yield and the
        #     recorded-quantity read each resolve per (measure, unit).
        FlowSpec(
            key="multi-measure-on-one-log",
            title="Two measures on one harvest are tracked independently",
            feature="harvest-logging",
            glossary_terms=["land", "harvest", "weight", "count", "yield_total",
                            "quantity_recorded", "record_log"],
            given=[GivenStep(entity="land", alias="A", name="Two Measure Field")],
            when=[
                WhenStep(action="record_log", alias="L", kind="harvest",
                         status="done", name="Weighed and counted harvest",
                         against=["A"],
                         quantities=[_q("weight", 5, "kilogram", "yield"),
                                     _q("count", 12, "head", "yield")]),
            ],
            probes=[
                Probe(assert_="quantity_recorded", subject="L", measure="weight",
                      unit="kilogram"),
                Probe(assert_="quantity_recorded", subject="L", measure="count",
                      unit="head"),
                Probe(assert_="yield_total", subject="A", measure="weight",
                      unit="kilogram"),
                Probe(assert_="yield_total", subject="A", measure="count",
                      unit="head"),
            ],
        ),
    ]


# --------------------------------------------------------------------------- #
# Recording + distillation                                                    #
# --------------------------------------------------------------------------- #
def _observe_probe(
    adapter: FarmOSAdapter, probe: Probe, handles: dict[str, Handle]
) -> Any:
    """Read the value the live system delivers for a probe (the distilled fact)."""
    subject = handles[probe.subject]
    if probe.assert_ == "yield_total":
        return adapter.asset_yield_total(subject, probe.measure, probe.unit)
    if probe.assert_ == "log_status":
        return adapter.log_status(subject)
    if probe.assert_ == "log_count":
        return adapter.log_count(subject, probe.kind)
    if probe.assert_ == "asset_active":
        return adapter.asset_active(subject)
    if probe.assert_ == "group_member":
        return adapter.group_member(subject, handles[probe.group])
    if probe.assert_ == "quantity_recorded":
        return adapter.quantity_recorded(subject, probe.measure, probe.unit)
    if probe.assert_ == "stock_on_hand":
        return adapter.stock_on_hand(subject, probe.measure, probe.unit)
    if probe.assert_ == "stock_pair_count":
        return adapter.stock_pair_count(subject)
    if probe.assert_ == "adjustment_count":
        return adapter.adjustment_count(subject)
    if probe.assert_ == "animal_sex":
        return adapter.animal_sex(subject)
    if probe.assert_ == "nicknames":
        return adapter.nicknames(subject)
    if probe.assert_ == "birth_date":
        return adapter.birth_date(subject)
    if probe.assert_ == "parent_count":
        return adapter.parent_count(subject)
    if probe.assert_ == "has_parent":
        return adapter.has_parent(subject, handles[probe.other])
    if probe.assert_ == "birth_record_count":
        return adapter.birth_record_count(subject)
    # PROVISIONAL bundle-field assertions (MetaCoding-io6): the adapter delivers
    # each as a boundary readback of the subject log; wired here so a flow pack
    # can exercise them toward a sealed binding.
    if probe.assert_ == "lot_number":
        return adapter.lot_number(subject)
    if probe.assert_ == "material_quantity":
        return adapter.material_quantity(subject)
    # birth_mother is has_parent-shaped: it takes the expected dam as `other`
    # and delivers a boolean. Hand-wired at binding time, before MetaCoding-td9
    # taught `add-term` to generate this dispatch arm; later terms arrive here
    # generated.
    if probe.assert_ == "birth_mother":
        return adapter.birth_mother(subject, handles[probe.other])
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "equipment_used":
        return adapter.equipment_used(subject, handles[probe.other])
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "material_type_recorded":
        return adapter.material_type_recorded(subject)
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "lab_sample_type":
        return adapter.lab_sample_type(subject)
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "laboratory":
        return adapter.laboratory(subject)
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "lab_test_measurement":
        return adapter.lab_test_measurement(subject)
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "lab_processing_date":
        return adapter.lab_processing_date(subject)
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "sample_received_date":
        return adapter.sample_received_date(subject)
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    if probe.assert_ == "soil_texture":
        return adapter.soil_texture(subject)
    raise ValueError(f"unknown probe assertion {probe.assert_!r}")


def detect_order_sensitivity(flow: FlowSpec) -> str:
    """Why this flow's observed value depends on the SOURCE's ordering, if it does.

    Two or more writes sharing one effective time against the same subject leave
    the outcome to whatever the source uses to break the tie — for farmOS, entity
    insertion id. The value observed is then that tie-break's fingerprint, not a
    semantic a correct port must reproduce: w0a's three same-instant adjustments
    observed 3.0, and the same three events in the six possible orders yield four
    different values. Scoring a port against it is a false green under one
    ordering and a false failure under another.

    Detected rather than declared: the author of the w0a pack did not notice, the
    judges did — after the fixture had already been scored.

    The detection itself lives in :func:`ctkr.oracle.fixtures.order_sensitivity`,
    on the ``when`` clause, so that the party READING a pack re-derives the same
    answer instead of believing the pack's own label.
    """
    return order_sensitivity(flow.when)


def record_flow(
    adapter: FarmOSAdapter, flow: FlowSpec, source_version: str = "4.x"
) -> tuple[SemanticFixture, list[Observation]]:
    """Execute a flow against live farmOS and distill it into a semantic fixture.

    ``given`` + ``when`` reach the state; each :class:`Probe` is then observed to
    fill the expected value. The resulting fixture asserts exactly what the live
    boundary returned — the self-verification guarantee.
    """
    client = adapter.client
    obs_start = len(getattr(client, "observations", []))

    handles: dict[str, Handle] = {}
    now = flow_now()
    for g in flow.given:
        handles[g.alias] = apply_given(adapter, g)

    refusal: AdapterError | None = None
    for w in flow.when:
        try:
            apply_when(adapter, w, handles, now)
        except AdapterError as exc:
            if not flow.expect_refusal:
                raise
            # The refusal IS the observation. Stop here: everything after this
            # step was predicated on a write that did not happen.
            refusal = exc
            break

    if flow.expect_refusal and refusal is None:
        # Never fabricate the expected answer. The source accepted what the pack
        # said it would refuse — a real finding about the source, and the pack.
        raise RefusalNotObserved(
            f"flow {flow.key!r} expected the source to REFUSE, but it accepted "
            f"the write. That is a finding about the source, not a fixture: "
            f"either the invariant does not exist or the flow does not violate it."
        )

    # Every assertion below is issued together with the WITNESS that produced
    # its value. The two are minted in the same breath and cannot be separated:
    # the assertion carries the witness's obs_id inside the fixture's hashed
    # body, and the witness carries the value the source delivered.
    then: list[ThenAssertion] = []
    witnesses: list[Observation] = []

    def _witness(descriptor: dict[str, Any], observed: Any) -> str:
        obs = Observation(
            obs_id=blake3(
                json.dumps(
                    {"flow": flow.key, "n": len(witnesses), "probe": descriptor},
                    sort_keys=True, default=str,
                ).encode("utf-8")
            ).hexdigest()[:16],
            method="OBSERVE",
            path=f"probe/{descriptor['assert']}",
            record=WITNESS_RECORD,
            probe=descriptor,
            observed=observed,
        )
        witnesses.append(obs)
        return obs.obs_id

    if refusal is not None:
        a = ThenAssertion(
            assert_="refused", subject=flow.when[-1].ref or flow.when[-1].alias,
            op="==", value=True,
        )
        # A refusal is a value the source delivered in its own words, so it is
        # witnessed like any other — the source's refusal text is the excerpt.
        a.witness = _witness(probe_descriptor(a), True)
        then.append(a)
        witnesses[-1].response_status = "refused"
        witnesses[-1].response_excerpt = {"refusal": str(refusal)[:600]}
    for probe in flow.probes:
        if refusal is not None:
            # A probe after a refused write would read state the write never
            # produced. Refusal flows assert the refusal, nothing more.
            break
        observed = _observe_probe(adapter, probe, handles)
        a = ThenAssertion(
            assert_=probe.assert_, subject=probe.subject,
            measure=probe.measure, unit=probe.unit, kind=probe.kind,
            group=probe.group, other=probe.other, op=probe.op,
            value=observed,
        )
        a.witness = _witness(probe_descriptor(a), observed)
        then.append(a)

    # Evidence quality travels WITH the fixture. Declared by the flow, or
    # detected from what the flow does — a caller-supplied side file is not
    # enough, because the reader of a pack may never see one.
    detected = detect_order_sensitivity(flow)
    evidence_class = "scoring"
    evidence_note = ""
    if flow.corroboration_only and not detected:
        # A DECLARED exemption the reader cannot re-derive is exactly the pen the
        # flow author must not hold — the loader will refuse it (pack.py), so
        # refuse it HERE, where the author can still fix the flow, rather than
        # shipping a pack that turns into INVALID EVIDENCE at judging time.
        raise UnearnedExemption(
            f"flow {flow.key!r} declares corroboration_only "
            f"({flow.corroboration_reason or 'no reason given'}), but nothing in "
            f"its `when` clause makes the observed value order-dependent: no two "
            f"writes share an effective time against one subject. An exemption "
            f"from scoring must be re-derivable from the flow by whoever reads "
            f"the pack, not asserted by whoever wrote it."
        )
    if detected:
        evidence_class = "corroboration-only"
        evidence_note = flow.corroboration_reason or detected

    # INVARIANT 1. Every value the fixture carries is stamped with WHERE ITS
    # AUTHORITY COMES FROM, and — when it is one of ours — with the identity of
    # the computation that produced it. The recorder is the only party that can
    # honestly state this, because it is the party that made the reads.
    asserted = {a.assert_ for a in then}
    authority = {
        t: PROBE_CONTRACT[t].authority for t in sorted(asserted) if t in PROBE_CONTRACT
    }
    derivations = {
        t: PROBE_CONTRACT[t].derivation_id
        for t in sorted(asserted)
        if t in PROBE_CONTRACT and PROBE_CONTRACT[t].derivation_id
    }

    observations = list(getattr(client, "observations", []))[obs_start:] + witnesses
    fixture = SemanticFixture(
        title=flow.title,
        feature=flow.feature,
        glossary_terms=flow.glossary_terms,
        given=flow.given,
        when=flow.when,
        then=then,
        provenance=Provenance(
            source_system="farmOS",
            source_version=source_version,
            flow=flow.key,
            recorded_at=datetime.now(UTC).isoformat(),
            observation_refs=[o.obs_id for o in observations],
            evidence_class=evidence_class,
            evidence_note=evidence_note,
            derivations=derivations,
            authority=authority,
        ),
    ).with_id()
    return fixture, observations


class RefusalNotObserved(RuntimeError):
    """A flow declared ``expect_refusal`` but the source accepted the write."""


class UnearnedExemption(RuntimeError):
    """A flow declared corroboration-only and nothing in the flow earns it."""


@dataclass
class UnrecordedFlow:
    """A flow that produced no fixture, and why. Never silently dropped."""

    key: str
    title: str
    error: str


@dataclass
class SessionResult:
    """Everything a recording run produced, including what it could NOT record."""

    fixtures: list[SemanticFixture] = field(default_factory=list)
    observations: list[Observation] = field(default_factory=list)
    unrecorded: list[UnrecordedFlow] = field(default_factory=list)


def record_session_result(
    adapter: FarmOSAdapter,
    flows: list[FlowSpec] | None = None,
    source_version: str = "4.x",
) -> SessionResult:
    """Run the whole scripted session, surviving individual flow failures.

    The recorder used to abort the entire run on the first :class:`AdapterError`,
    so one unrecordable flow cost every flow after it (the wave-0 pilot lost a
    whole pack's tail that way). A failing flow is now recorded as
    :class:`UnrecordedFlow` and the session continues — but it is never treated
    as a pass: the caller must report the list, and the CLI exits non-zero.
    """
    flows = flows if flows is not None else core_flows()
    result = SessionResult()
    adapter.open()
    for flow in flows:
        obs_start = len(getattr(adapter.client, "observations", []))
        try:
            fx, obs = record_flow(adapter, flow, source_version)
        except (AdapterError, RefusalNotObserved, UnearnedExemption,
                KeyError, ValueError) as exc:
            # Keep whatever the boundary said before it failed — for a refusal
            # that excerpt IS the finding.
            result.observations.extend(
                list(getattr(adapter.client, "observations", []))[obs_start:]
            )
            result.unrecorded.append(
                UnrecordedFlow(key=flow.key, title=flow.title,
                               error=f"{type(exc).__name__}: {exc}")
            )
            continue
        result.fixtures.append(fx)
        result.observations.extend(obs)
    return result


def record_session(
    adapter: FarmOSAdapter,
    flows: list[FlowSpec] | None = None,
    source_version: str = "4.x",
) -> tuple[list[SemanticFixture], list[Observation]]:
    """Back-compatible shape: fixtures + observations only."""
    r = record_session_result(adapter, flows, source_version)
    return r.fixtures, r.observations


def write_observations(observations: list[Observation], path: Any) -> int:
    """Write raw recorded observations as JSONL (provenance ground truth)."""
    from pathlib import Path

    p = Path(path)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("w", encoding="utf-8") as fh:
        for o in observations:
            fh.write(json.dumps(o.model_dump(), default=str) + "\n")
    return len(observations)


def build_client(
    base_url: str, username: str, password: str, *, recording: bool = True,
    client_id: str = "farm", client_secret: str = "", timeout: float = 30.0,
) -> FarmOSClient:
    """Construct a (recording) farmOS client for the CLI + tests."""
    cls = RecordingClient if recording else FarmOSClient
    return cls(base_url, username, password, client_id=client_id,
              client_secret=client_secret, timeout=timeout)
