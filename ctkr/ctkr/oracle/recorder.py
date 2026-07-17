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
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from blake3 import blake3
from pydantic import BaseModel, Field

from ctkr.oracle.adapter import Handle
from ctkr.oracle.farmos_adapter import FarmOSAdapter, FarmOSClient
from ctkr.oracle.fixtures import (
    GivenStep,
    Provenance,
    QuantitySpec,
    SemanticFixture,
    ThenAssertion,
    WhenStep,
)


class Observation(BaseModel):
    """One recorded request/response pair at the JSON:API boundary (provenance)."""

    obs_id: str
    method: str
    path: str
    request: dict[str, Any] | None = None
    response_status: str = "ok"
    response_excerpt: dict[str, Any] | None = None


class RecordingClient(FarmOSClient):
    """A FarmOSClient that logs every request/response as an :class:`Observation`."""

    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, **kwargs)
        self.observations: list[Observation] = []
        self._seq = 0

    def request(
        self, method: str, path: str, doc: dict | None = None
    ) -> dict[str, Any]:
        resp = super().request(method, path, doc)
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
    raise ValueError(f"unknown probe assertion {probe.assert_!r}")


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
    for g in flow.given:
        handles[g.alias] = adapter.create_asset(g.entity, g.name, g.descriptor)
    for w in flow.when:
        if w.action == "record_log":
            asset_handles = [handles[a] for a in w.against]
            handles[w.alias] = adapter.record_log(
                w.kind, w.name or f"{w.kind} log", w.status or "done",
                asset_handles, w.quantities,
            )
        elif w.action == "set_log_status":
            adapter.set_log_status(handles[w.ref], w.status)
        elif w.action == "assign_to_group":
            adapter.assign_to_group(handles[w.ref], handles[w.group])
        elif w.action == "archive_asset":
            adapter.archive_asset(handles[w.ref])

    then: list[ThenAssertion] = []
    for probe in flow.probes:
        observed = _observe_probe(adapter, probe, handles)
        then.append(
            ThenAssertion(
                assert_=probe.assert_, subject=probe.subject,
                measure=probe.measure, unit=probe.unit, kind=probe.kind,
                group=probe.group, op=probe.op, value=observed,
            )
        )

    observations = list(getattr(client, "observations", []))[obs_start:]
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
            recorded_at=datetime.now(timezone.utc).isoformat(),
            observation_refs=[o.obs_id for o in observations],
        ),
    ).with_id()
    return fixture, observations


def record_session(
    adapter: FarmOSAdapter,
    flows: list[FlowSpec] | None = None,
    source_version: str = "4.x",
) -> tuple[list[SemanticFixture], list[Observation]]:
    """Run the whole scripted session; return distilled fixtures + all observations."""
    flows = flows if flows is not None else core_flows()
    fixtures: list[SemanticFixture] = []
    all_obs: list[Observation] = []
    adapter.open()
    for flow in flows:
        fx, obs = record_flow(adapter, flow, source_version)
        fixtures.append(fx)
        all_obs.extend(obs)
    return fixtures, all_obs


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
    client_id: str = "farm", client_secret: str = "",
) -> FarmOSClient:
    """Construct a (recording) farmOS client for the CLI + tests."""
    cls = RecordingClient if recording else FarmOSClient
    return cls(base_url, username, password, client_id=client_id,
              client_secret=client_secret)
