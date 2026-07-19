"""Tests for the semantic-mining pass (bead MetaCoding-9h5.10).

Hermetic: an in-memory NetworkX graph for the graph lane + ranking + schema, and a
mock LLM provider for the source-read lane (no network, no Docker). Pins the
LM-free machinery — reach ranking, category classification, topic fusion, the
deterministic rank-score formula, and JSONL round-trip — plus the mock-provider
structured path and the CM-adjudication → candidate mapping. The live-corpus
numbers (does the miner surface latest-wins on logs+quantities) live in the task
evidence, not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from types import SimpleNamespace

import networkx as nx
import pytest

from ctkr.llm import LLMClient, _ProviderResponse
from ctkr.mine_fixtures import (
    LANE_CM,
    LANE_GRAPH,
    LANE_SOURCE_READ,
    FixtureCandidate,
    RankWeights,
    ScenarioSketch,
    classify_topic,
    cm_candidate_from_adjudicated,
    compute_reach,
    fuse_and_rank,
    load_candidates,
    mine_cm_lane,
    mine_field_flow_edges,
    mine_graph_lane,
    mine_source_read_lane,
    write_candidates,
)


# ───────────────────────── graph fixtures ─────────────────────────
def _node(g, nid, **attrs):
    g.add_node(nid, **attrs)


def _build_graph() -> nx.MultiDiGraph:
    """A tiny farmOS-shaped graph: a log validator (constraint), a group membership
    class (high reach), an out-of-scope asset class, plus referrers + one config file."""
    g = nx.MultiDiGraph()
    _node(g, "constraint", kind="class",
          file="modules/log/birth/src/Plugin/Validation/Constraint/UniqueBirthLogConstraintValidator.php",
          short_name="UniqueBirthLogConstraintValidator", line=20)
    _node(g, "membership", kind="class", file="modules/asset/group/src/GroupMembership.php",
          short_name="GroupMembership", line=15)
    _node(g, "hook", kind="class", file="modules/log/birth/src/Hook/FieldHooks.php",
          short_name="FieldHooks", line=10)
    _node(g, "views", kind="class", file="modules/quantity/src/QuantityViewsData.php",
          short_name="QuantityViewsData", line=8)
    _node(g, "testcls", kind="class", file="modules/log/birth/tests/src/Kernel/BirthTest.php",
          short_name="BirthTest", line=5)
    _node(g, "config", kind="file", file="modules/log/birth/config/install/log.type.birth.yml",
          short_name="log.type.birth.yml", line=0)
    # referrers (reach) — 3 point at membership, 1 at constraint
    for i, tgt in enumerate(["membership", "membership", "membership", "constraint"]):
        rid = f"ref{i}"
        _node(g, rid, kind="method", file="modules/asset/group/src/Hook/EntityHooks.php",
              short_name=f"ref{i}", line=i)
        g.add_edge(rid, tgt, key="CALLS", kind="CALLS")
    return g


def test_compute_reach_counts_distinct_referrers():
    g = _build_graph()
    reach = compute_reach(g, ["membership", "constraint", "hook"])
    assert reach["membership"] == 3
    assert reach["constraint"] == 1
    assert reach["hook"] == 0


def test_graph_lane_scopes_and_ranks_by_reach():
    g = _build_graph()
    # Scope to log+quantity only: group (membership) is OUT of scope.
    cands = mine_graph_lane(g, subsystem_prefixes=["/log/", "/quantity/"], min_reach=0)
    files = {c.source_citation.split(":")[0] for c in cands}
    assert not any("asset/group" in f for f in files), "group must be out of log+quantity scope"
    # Test scaffolding excluded.
    assert not any("BirthTest" in c.title for c in cands)
    # The constraint validator is surfaced and categorised.
    constraint = next(c for c in cands if "Constraint" in c.title)
    assert constraint.lane_detail["graph"]["category"] == "validation-constraint"


def test_graph_lane_surfaces_membership_when_group_in_scope():
    g = _build_graph()
    cands = mine_graph_lane(
        g, subsystem_prefixes=["/log/", "/quantity/", "asset/group"], min_reach=0)
    membership = next((c for c in cands if "GroupMembership" in c.title), None)
    assert membership is not None
    assert membership.lane_detail["graph"]["category"] == "membership-logic"
    assert membership.reach == 3
    assert membership.topic == "group-membership-latest-wins"
    # highest reach ⇒ sorted first among graph candidates
    assert cands[0].element_id == "membership"


def test_field_flow_edges_present_when_export_carries_them():
    g = nx.MultiDiGraph()
    _node(g, "a", kind="method", file="modules/log/birth/src/Hook/EntityHooks.php",
          short_name="syncBirthChildren", line=1)
    _node(g, "b", kind="field", file="modules/asset/src/Entity/Asset.php",
          short_name="birthdate", line=1)
    g.add_edge("a", "b", key="WRITES_FIELD", kind="WRITES_FIELD")
    edges = mine_field_flow_edges(g, ["/log/"])
    assert len(edges) == 1 and edges[0]["kind"] == "WRITES_FIELD"


def test_field_flow_absent_degrades_gracefully():
    g = _build_graph()  # only CALLS edges
    assert mine_field_flow_edges(g, ["/log/"]) == []


# ───────────────────────── topic classification ─────────────────────────
@pytest.mark.parametrize("text,expected", [
    ("group membership is latest-wins", "group-membership-latest-wins"),
    ("only one birth log per asset (uniqueness)", "uniqueness-constraint"),
    ("a pending harvest still contributes", "pending-contributes"),
    ("yield sums across all log kinds", "cross-kind-aggregation"),
    ("nothing semantic here", ""),
])
def test_classify_topic(text, expected):
    assert classify_topic(text) == expected


# ───────────────────────── CM lane ─────────────────────────
def _adj(**kw):
    base = dict(element_id="unique-constraint:X:log/birth/src/Hook/FieldHooks.php",
                element_kind="php-class", categories=["unique-constraint"],
                sensitivity="hard", rationale="one birth log per asset",
                citations=["log/birth/src/Hook/FieldHooks.php:31"])
    base.update(kw)
    return SimpleNamespace(**base)


def test_cm_lane_keeps_hard_soft_drops_none():
    rows = [_adj(sensitivity="hard"), _adj(sensitivity="soft"), _adj(sensitivity="none")]
    cands = mine_cm_lane(rows)
    assert len(cands) == 2
    assert all(LANE_CM in c.lanes for c in cands)


def test_cm_candidate_maps_uniqueness_topic_and_citation():
    c = cm_candidate_from_adjudicated(_adj())
    assert c.topic == "uniqueness-constraint"
    assert c.source_citation == "log/birth/src/Hook/FieldHooks.php:31"
    assert c.lane_detail["cm"]["sensitivity"] == "hard"


# ───────────────────────── source-read lane (mock provider) ─────────────────────────
class _MockProvider:
    name = "openai"
    env_var = "OPENAI_API_KEY"

    def __init__(self, payload: dict):
        self._payload = payload

    def complete(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens,
                            system, reasoning_effort=None):
        return _ProviderResponse(text=json.dumps(self._payload), input_tokens=100,
                                 output_tokens=50), self._payload


def _client_with(payload):
    c = LLMClient(default_provider="openai", default_model="gpt-5.6-terra")
    c.register_provider(_MockProvider(payload))
    return c


def test_source_read_lane_parses_rules_to_candidates():
    payload = {"rules": [
        {"rule": "group membership is the latest assignment, not additive",
         "why_non_obvious": "a natural port models membership additively",
         "citation": "GroupMembership.php:80", "given": ["asset A"], "when": ["reassign to G2"],
         "then": ["member of G2 only"], "confidence": 0.9},
        {"rule": "yield sums across all log kinds",
         "why_non_obvious": "the name implies harvest-only",
         "citation": "Quantity.php:12", "given": [], "when": [], "then": [], "confidence": 0.7},
    ]}
    client = _client_with(payload)
    cands, cost = mine_source_read_lane({"group": "src"}, client, model="gpt-5.6-terra")
    assert len(cands) == 2
    assert cands[0].topic == "group-membership-latest-wins"
    assert all(LANE_SOURCE_READ in c.lanes for c in cands)
    assert cost >= 0.0


def test_source_read_lane_degrades_on_provider_error():
    class _Boom(_MockProvider):
        def complete_structured(self, *a, **k):
            raise RuntimeError("provider down")
    client = LLMClient(default_provider="openai", default_model="gpt-5.6-terra")
    client.register_provider(_Boom({}))
    cands, cost = mine_source_read_lane({"m": "src"}, client, model="gpt-5.6-terra")
    assert cands == [] and cost == 0.0


# ───────────────────────── fusion + ranking ─────────────────────────
def _cand(lanes, topic, feature, **kw):
    d = dict(title=kw.pop("title", f"t-{topic}"), feature=feature, topic=topic, lanes=lanes)
    d.update(kw)
    return FixtureCandidate(**d).with_id()


def test_fusion_merges_cross_lane_same_topic():
    cm = _cand([LANE_CM], "group-membership-latest-wins", "asset/group",
               lane_detail={"cm": {"sensitivity": "hard"}})
    src = _cand([LANE_SOURCE_READ], "group-membership-latest-wins", "asset/group",
                lane_detail={"source_read": {"confidence": 0.9}})
    graph = _cand([LANE_GRAPH], "group-membership-latest-wins", "asset/group",
                  reach=12, lane_detail={"graph": {"category": "membership-logic"}})
    ranked = fuse_and_rank([[cm], [graph], [src]])
    assert len(ranked) == 1
    fused = ranked[0]
    assert set(fused.lanes) == {LANE_CM, LANE_GRAPH, LANE_SOURCE_READ}


def test_multi_lane_outranks_single_lane():
    cm = _cand([LANE_CM], "uniqueness-constraint", "log/birth",
               lane_detail={"cm": {"sensitivity": "hard"}})
    src = _cand([LANE_SOURCE_READ], "uniqueness-constraint", "log/birth",
                lane_detail={"source_read": {"confidence": 0.8}})
    lone = _cand([LANE_GRAPH], "yield-aggregation", "quantity", reach=20,
                 lane_detail={"graph": {"category": "domain-logic"}})
    ranked = fuse_and_rank([[cm, lone], [src]])
    # the fused (2-lane) uniqueness candidate must outrank the single-lane graph one
    assert ranked[0].topic == "uniqueness-constraint"
    assert len(ranked[0].lanes) == 2
    assert ranked[0].rank_score > ranked[1].rank_score


def test_distinct_topicless_candidates_stay_separate():
    a = _cand([LANE_SOURCE_READ], "", "m", title="rule A")
    b = _cand([LANE_SOURCE_READ], "", "m", title="rule B")
    ranked = fuse_and_rank([[a, b]])
    assert len(ranked) == 2


def test_rank_score_formula_is_deterministic():
    w = RankWeights()
    graph = _cand([LANE_GRAPH], "x-topic", "m", reach=10,
                  lane_detail={"graph": {"category": "domain-logic"}})
    ranked = fuse_and_rank([[graph]], weights=w)
    # base = 0.7 * (10/20) = 0.35 ; +reach_bonus 0.15*0.5=0.075 ; n_lanes-1=0
    assert ranked[0].rank_score == pytest.approx(0.35 + 0.075, abs=1e-6)


# ───────────────────────── IO round-trip ─────────────────────────
def test_write_load_roundtrip(tmp_path: Path):
    c = _cand([LANE_CM], "uniqueness-constraint", "log/birth",
              scenario=ScenarioSketch(given=["g"], when=["w"], then=["t"]),
              source_citation="f.php:1", lane_detail={"cm": {"sensitivity": "hard"}})
    p = tmp_path / "cands.jsonl"
    assert write_candidates([c], p) == 1
    back = load_candidates(p)
    assert len(back) == 1
    assert back[0].candidate_id == c.candidate_id
    assert back[0].scenario.given == ["g"]
