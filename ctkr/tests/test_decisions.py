"""Hermetic tests for the design-decision elicitation layer (MetaCoding-9h5.13).

No network, no real data-dir: synthetic adjudications, a synthetic NetworkX graph, a
synthetic subsystem-members frame, and a mock LLM provider. Pins registry collection,
blast-radius graph reach, uncertainty × blast ranking, the Port Decision ledger append
(+ portDecisions.ts compatibility), the resolution-mode state transitions, and the
interview / decide-for-me LLM flows.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import networkx as nx
import polars as pl

from ctkr.decisions import (
    Decision,
    append_pd_record,
    apply_resolution,
    collect_brief_adaptation_decisions,
    collect_cm_decisions,
    collect_paradigm_divergence_decisions,
    compute_blast_radius,
    decide_for_me,
    elicit_decision,
    map_cm_element_to_nodes,
    merge_registry,
    rank_decisions,
    read_registry,
    render_interview_doc,
    render_menu,
    uncertainty_weight,
    write_registry,
)
from ctkr.intent_cm import AdjudicatedCM, TargetProfile
from ctkr.llm import LLMClient, _ProviderResponse

# ───────────────────────── fixtures ─────────────────────────


def _birth_adjudication() -> AdjudicatedCM:
    """The canonical UniqueBirthLog CM-hard adjudication (shape of the real slice row)."""
    return AdjudicatedCM(
        adjudication_id="cm:birthfixture",
        element_id="farmosunique-constraint:entityBundleFieldInfo:log/birth/src/Hook/FieldHooks.php",
        element_kind="php-class",
        categories=["unique-constraint"],
        cm_seed="CM-hard",
        sensitivity="hard",
        per_category={"unique-constraint": "hard"},
        rationale="The 'UniqueBirthLog' constraint enforces one birth log per asset; cannot "
        "hold under eventual consistency without a convergence rule.",
        evidence_refs=["f27edcbb"],
        citations=["log/birth/src/Hook/FieldHooks.php:31"],
        evidence_digest="deadbeef",
        llm_model="claude-sonnet-4-6",
        prompt_version="intent-cm:v1",
        generated_at="2026-07-19T00:00:00+00:00",
    )


def _soft_adjudication() -> AdjudicatedCM:
    return AdjudicatedCM(
        adjudication_id="cm:softfixture",
        element_id="farmosaccess-check:access:modules/asset/src/Access.php",
        element_kind="php-class",
        categories=["access-check"],
        cm_seed="CM-soft",
        sensitivity="soft",
        per_category={"access-check": "soft"},
        rationale="Access is a stale snapshot; move to the disclosure boundary.",
        evidence_refs=["a1"],
        citations=["modules/asset/src/Access.php:12"],
        evidence_digest="cafe",
        llm_model="claude-sonnet-4-6",
        prompt_version="intent-cm:v1",
        generated_at="2026-07-19T00:00:00+00:00",
    )


def _none_adjudication() -> AdjudicatedCM:
    return AdjudicatedCM(
        adjudication_id="cm:nonefixture",
        element_id="farmostransaction:t:modules/x/src/X.php",
        element_kind="php-class",
        categories=["transaction"],
        cm_seed="CM-soft",
        sensitivity="none",
        per_category={"transaction": "none"},
        rationale="false positive.",
        evidence_refs=[],
        citations=[],
        evidence_digest="00",
        llm_model="claude-sonnet-4-6",
        prompt_version="intent-cm:v1",
        generated_at="2026-07-19T00:00:00+00:00",
    )


def _profile() -> TargetProfile:
    return TargetProfile(
        id="farmos-local-first",
        name="farmOS local-first port",
        consistency_model="eventual",
        architecture=["event-log", "materialized-views"],
        sync="selective-disclosure",
        summary="",
        decision_menu={
            "hard": [
                "preserve-via-convergence-rule",
                "weaken-to-eventual",
                "move-to-disclosure-layer",
            ],
            "soft": ["preserve-as-eventual-invariant", "move-to-disclosure-layer"],
            "none": ["port-verbatim"],
        },
        capabilities={"coordination_layer": False},
    )


def _graph() -> nx.MultiDiGraph:
    """A tiny graph: the birth FieldHooks class + method, plus two external referrers
    living in a different subsystem so cross-subsystem reach is exercised."""
    g = nx.MultiDiGraph()
    g.add_node(
        "cls_birth",
        kind="class",
        short_name="FieldHooks",
        qualified_name="modules/log/birth/src/Hook/FieldHooks.php::FieldHooks",
        file="modules/log/birth/src/Hook/FieldHooks.php",
    )
    g.add_node(
        "meth_birth",
        kind="method",
        short_name="entityBundleFieldInfo",
        qualified_name="modules/log/birth/src/Hook/FieldHooks.php::FieldHooks::entityBundleFieldInfo",
        file="modules/log/birth/src/Hook/FieldHooks.php",
    )
    g.add_node("referrer_a", kind="method", short_name="a", file="modules/other/A.php")
    g.add_node("referrer_b", kind="method", short_name="b", file="modules/other/B.php")
    g.add_edge("cls_birth", "meth_birth", key="CONTAINS", kind="CONTAINS")
    # referrers -> the birth method (they reference/call it) → ancestors of meth_birth
    g.add_edge("referrer_a", "meth_birth", key="CALLS", kind="CALLS")
    g.add_edge("referrer_b", "referrer_a", key="CALLS", kind="CALLS")
    return g


def _members() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "subsystem_id": ["ss:log", "ss:log", "ss:other", "ss:other"],
            "symbol_id": ["cls_birth", "meth_birth", "referrer_a", "referrer_b"],
            "repo": ["farmos"] * 4,
            "qualified_name": ["cls", "meth", "a", "b"],
        }
    )


# ───────────────────────── blast radius ─────────────────────────


def test_map_cm_element_prefers_anchor_node() -> None:
    g = _graph()
    from ctkr.decisions import _file_node_index

    idx = _file_node_index(g)
    nodes = map_cm_element_to_nodes(
        element_file="log/birth/src/Hook/FieldHooks.php",
        anchor="entityBundleFieldInfo",
        graph=g,
        file_index=idx,
    )
    assert nodes == ["meth_birth"]


def test_blast_radius_counts_transitive_predecessors_and_subsystems() -> None:
    g = _graph()
    members_idx = {r["symbol_id"]: r["subsystem_id"] for r in _members().iter_rows(named=True)}
    sizes = {"ss:log": 2, "ss:other": 2}
    br = compute_blast_radius(
        anchor_nodes=["meth_birth"], graph=g, members_idx=members_idx, subsystem_sizes=sizes
    )
    # meth_birth + its 3 transitive predecessors (cls_birth via CONTAINS, referrer_a,
    # referrer_b) are affected.
    assert br.affected_symbols == 4
    # spans ss:log (the method + class) + ss:other (both referrers).
    assert br.referencing_subsystems == 2
    assert br.containing_subsystems == ["ss:log"]
    # score = affected(4) + 4*(subsystems-1 = 1) = 8
    assert br.score == 8.0


def test_blast_radius_empty_graph_is_graceful() -> None:
    br = compute_blast_radius(
        anchor_nodes=["nope"], graph=None, members_idx={}, subsystem_sizes={}
    )
    assert br.affected_symbols == 0 and br.score == 0.0


# ───────────────────────── CM collector ─────────────────────────


def test_collect_cm_surfaces_birthlog_with_three_option_menu() -> None:
    decs = collect_cm_decisions(
        [_birth_adjudication()],
        _profile(),
        graph=_graph(),
        members_df=_members(),
        generated_at="2026-07-19T00:00:00+00:00",
    )
    assert len(decs) == 1
    d = decs[0]
    assert d.source == "intent-cm"
    assert d.uncertainty_grade == "cm-hard"
    assert [o.id for o in d.options] == [
        "preserve-via-convergence-rule",
        "weaken-to-eventual",
        "move-to-disclosure-layer",
    ]
    assert "UniqueBirthLog" in d.evidence or "birth" in d.question.lower()
    assert d.subsystem_id == "ss:log"
    # weaken-to-eventual is the one option that RELAXES the invariant.
    weaken = next(o for o in d.options if o.id == "weaken-to-eventual")
    assert weaken.pd_kind == "weaken"
    preserve = next(o for o in d.options if o.id == "preserve-via-convergence-rule")
    assert preserve.pd_kind == "preserve-with-note"
    # rank = uncertainty(1.0) * blast score(8) = 8.0
    assert d.rank_score == 8.0


def test_collect_cm_skips_none_and_includes_soft() -> None:
    decs = collect_cm_decisions(
        [_birth_adjudication(), _soft_adjudication(), _none_adjudication()],
        _profile(),
    )
    grades = sorted(d.uncertainty_grade for d in decs)
    assert grades == ["cm-hard", "cm-soft"]  # none dropped


def test_collect_cm_without_profile_uses_default_menu() -> None:
    decs = collect_cm_decisions([_birth_adjudication()], None)
    assert len(decs) == 1
    # default hard menu contains the coordination-layer option.
    assert "move-to-coordination-layer" in {o.id for o in decs[0].options}


def test_cm_decision_id_is_deterministic() -> None:
    a = collect_cm_decisions([_birth_adjudication()], _profile())[0]
    b = collect_cm_decisions([_birth_adjudication()], _profile())[0]
    assert a.id == b.id and a.id.startswith("dec:")


# ───────────────────────── brief-adaptation collector ─────────────────────────


def _card_with_dissonance() -> dict:
    return {
        "subsystem_id": "ss:log",
        "roles": [
            {
                "role_id": "role:mixed",
                "label": "Log type plugin",
                "members": ["cls_birth", "meth_birth", "referrer_a"],
                "intent_dissonance": {
                    "kind": "name_incoherence",
                    "evidence": "members cohere weakly",
                    "source": "structural",
                },
            },
            {
                "role_id": "role:clean",
                "label": "Clean role",
                "members": ["referrer_b"],
                "intent_dissonance": None,
            },
        ],
    }


def test_collect_brief_adaptation_from_role_dissonance() -> None:
    decs = collect_brief_adaptation_decisions(
        [_card_with_dissonance()], graph=_graph(), members_df=_members()
    )
    assert len(decs) == 1  # only the dissonant role
    d = decs[0]
    assert d.source == "brief-adaptation"
    assert d.uncertainty_grade == "role-name-incoherence"
    assert [o.id for o in d.options] == [
        "confirm-role-intent",
        "split-role",
        "defer-to-implementation",
    ]
    assert d.blast_radius.affected_symbols >= 3


def test_brief_adaptation_blast_falls_back_to_member_count_without_graph() -> None:
    decs = collect_brief_adaptation_decisions([_card_with_dissonance()], graph=None, members_df=None)
    assert decs[0].blast_radius.affected_symbols == 3


# ───────────────────────── paradigm-divergence collector ─────────────────────────


def _divergence_report() -> dict:
    return {
        "subsystem": "ss:log",
        "verdict": "advisory",
        "paradigmDivergence": {
            "diverges": True,
            "axes": ["consistency strong→eventual", "coordination-layer true→false"],
            "predictedNonInformative": ["role_coverage", "interface_preservation"],
            "summary": "Central-authority shape idioms expected to dissolve.",
        },
    }


def test_collect_paradigm_divergence() -> None:
    decs = collect_paradigm_divergence_decisions([_divergence_report()], members_df=_members())
    assert len(decs) == 1
    d = decs[0]
    assert d.source == "paradigm-divergence"
    assert d.uncertainty_grade == "divergence-material"
    assert d.blast_radius.affected_symbols == 2  # ss:log has 2 members
    assert {o.id for o in d.options} == {
        "accept-divergence-as-declared",
        "reclassify-gate-binding",
        "revise-target-profile",
    }


def test_non_diverging_report_is_skipped() -> None:
    rep = {"subsystem": "ss:x", "paradigmDivergence": {"diverges": False}}
    assert collect_paradigm_divergence_decisions([rep]) == []


# ───────────────────────── ranking ─────────────────────────


def test_ranking_orders_by_uncertainty_times_blast() -> None:
    cm = collect_cm_decisions([_birth_adjudication()], _profile(), graph=_graph(), members_df=_members())
    brief = collect_brief_adaptation_decisions([_card_with_dissonance()], graph=_graph(), members_df=_members())
    ranked = rank_decisions(cm + brief)
    # deterministic sort: highest rank_score first
    scores = [d.rank_score for d in ranked]
    assert scores == sorted(scores, reverse=True)


def test_uncertainty_weight_hard_is_max() -> None:
    assert uncertainty_weight("cm-hard") == 1.0
    assert uncertainty_weight("cm-soft") < uncertainty_weight("cm-hard")
    assert uncertainty_weight("unknown-grade") == 0.5


# ───────────────────────── registry IO + merge ─────────────────────────


def test_registry_roundtrip_and_rank_order(tmp_path: Path) -> None:
    decs = collect_cm_decisions([_birth_adjudication(), _soft_adjudication()], _profile())
    p = tmp_path / "decisions.jsonl"
    write_registry(decs, p)
    back = read_registry(p)
    assert len(back) == 2
    # written in ranked order
    assert back[0].rank_score >= back[1].rank_score


def test_merge_preserves_resolution_across_recollect(tmp_path: Path) -> None:
    decs = collect_cm_decisions([_birth_adjudication()], _profile())
    resolved = apply_resolution(
        decs[0], mode="decide", chosen_option="weaken-to-eventual", rationale="r", author="dev"
    )
    fresh = collect_cm_decisions([_birth_adjudication()], _profile())  # a re-collect
    merged = merge_registry(fresh, [resolved])
    assert merged[0].status == "decided-by-developer"
    assert merged[0].resolution.chosen_option == "weaken-to-eventual"


# ───────────────────────── ledger append + PD compatibility ─────────────────────────


def test_append_pd_record_writes_portdecisions_compatible_row(tmp_path: Path) -> None:
    d = collect_cm_decisions([_birth_adjudication()], _profile(), members_df=_members(), graph=_graph())[0]
    record, ledger = append_pd_record(
        tmp_path, decision=d, chosen_option="preserve-via-convergence-rule",
        rationale="UUID tiebreak on merge.", author="dev", date="2026-07-19",
    )
    # required portDecisions.ts fields present + correct kind
    for field in (
        "id", "date", "subsystem", "targetElement", "decision",
        "supersededSourceIntention", "rationale", "author",
    ):
        assert record[field], f"missing {field}"
    assert record["decision"] == "preserve-with-note"
    assert record["targetElement"].startswith("intent_cm[element_id=")
    assert record["chosen_option"] == "preserve-via-convergence-rule"
    # file written under port_decisions/<subsystem>.jsonl
    assert ledger.parent.name == "port_decisions"
    assert ledger.exists()
    row = json.loads(ledger.read_text().strip())
    assert row["id"] == record["id"]


def test_pd_ids_unique_on_repeated_append(tmp_path: Path) -> None:
    d = collect_cm_decisions([_birth_adjudication()], _profile(), members_df=_members())[0]
    r1, ledger = append_pd_record(tmp_path, decision=d, chosen_option="weaken-to-eventual", rationale="a", author="x")
    r2, _ = append_pd_record(tmp_path, decision=d, chosen_option="weaken-to-eventual", rationale="b", author="x")
    assert r1["id"] != r2["id"]
    assert ledger.read_text().count("\n") == 2


def test_roll_forward_pd_is_flagged_reversible(tmp_path: Path) -> None:
    d = collect_cm_decisions([_birth_adjudication()], _profile(), members_df=_members())[0]
    record, _ = append_pd_record(
        tmp_path, decision=d, chosen_option=d.options[0].id,
        rationale="ROLL-FORWARD (reversible): defer", author="x", reversible=True,
    )
    assert record["reversible"] is True


# ───────────────────────── resolution state machine ─────────────────────────


def _one() -> Decision:
    return collect_cm_decisions([_birth_adjudication()], _profile())[0]


def test_decide_transitions_to_decided_by_developer() -> None:
    d = apply_resolution(_one(), mode="decide", chosen_option="weaken-to-eventual", author="dev")
    assert d.status == "decided-by-developer"
    assert d.resolution.mode == "decide"


def test_decide_for_me_transitions() -> None:
    d = apply_resolution(_one(), mode="decide-for-me", chosen_option="preserve-via-convergence-rule")
    assert d.status == "decided-for-me"


def test_roll_forward_transitions_and_reversible() -> None:
    d = apply_resolution(_one(), mode="roll-forward", reversible=True)
    assert d.status == "rolled-forward"
    assert d.resolution.reversible is True


def test_interview_and_recommend_stay_pending() -> None:
    assert apply_resolution(_one(), mode="interview").status == "pending"
    assert apply_resolution(_one(), mode="recommend").status == "pending"


def test_apply_resolution_rejects_option_off_menu() -> None:
    try:
        apply_resolution(_one(), mode="decide", chosen_option="not-a-real-option")
    except ValueError as e:
        assert "not in menu" in str(e)
    else:  # pragma: no cover
        raise AssertionError("expected ValueError for off-menu option")


# ───────────────────────── mock LLM flows ─────────────────────────


class MockDecisionProvider:
    """Returns a valid payload for whichever decision schema it is called with."""

    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"

    def __init__(self) -> None:
        self.models: list[str] = []

    def complete(self, prompt, *, model, temperature, max_tokens, system):  # noqa: ANN001
        return _ProviderResponse(text="ok", input_tokens=1, output_tokens=1)

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        self.models.append(model)
        if schema.__name__ == "DecisionElicitationOut":
            payload: dict[str, Any] = {
                "tradeoffs": [
                    {
                        "option_id": "preserve-via-convergence-rule",
                        "pros": "keeps one birth fact via a UUID tiebreak",
                        "cons": "needs a convergence rule at projection time",
                        "when_appropriate": "a reader needs one birth fact today",
                        "citation": "log/birth/src/Hook/FieldHooks.php:31",
                    },
                    {
                        "option_id": "weaken-to-eventual",
                        "pros": "no coordination needed",
                        "cons": "transient duplicate birth logs across replicas",
                        "when_appropriate": "duplicates are tolerable until sync",
                        "citation": "log/birth/src/Hook/FieldHooks.php:31",
                    },
                    {
                        "option_id": "move-to-disclosure-layer",
                        "pros": "n/a for a uniqueness invariant",
                        "cons": "does not address write-time uniqueness",
                        "when_appropriate": "access-flavored constraints only",
                        "citation": "",
                    },
                ],
                "recommendation": "preserve-via-convergence-rule: a deterministic "
                "lowest-UUID tiebreak keeps a single birth fact.",
            }
        elif schema.__name__ == "DecisionPickOut":
            payload = {
                "chosen_option": "preserve-via-convergence-rule",
                "rationale": "Deterministic UUID tiebreak preserves the single-birth "
                "invariant without a coordination layer (FieldHooks.php:31).",
            }
        else:  # pragma: no cover
            payload = {}
        return _ProviderResponse(text=json.dumps(payload), input_tokens=10, output_tokens=10), payload


def _mock_client() -> tuple[LLMClient, MockDecisionProvider]:
    prov = MockDecisionProvider()
    c = LLMClient()
    c.register_provider(prov)  # type: ignore[arg-type]
    return c, prov


def test_elicit_decision_builds_interview_doc() -> None:
    d = collect_cm_decisions([_birth_adjudication()], _profile(), graph=_graph(), members_df=_members())[0]
    client, _ = _mock_client()
    res = elicit_decision(d, client, model="mock-strong", provider="anthropic")
    doc = render_interview_doc(d, res.parsed)
    assert "# Decision" in doc
    assert "preserve-via-convergence-rule" in doc
    assert "Pros" in doc and "Cons" in doc
    assert "UUID tiebreak" in doc  # recommendation rendered
    # every menu option appears with its tradeoff
    for opt in ("preserve-via-convergence-rule", "weaken-to-eventual", "move-to-disclosure-layer"):
        assert opt in doc


def test_decide_for_me_picks_menu_option() -> None:
    d = collect_cm_decisions([_birth_adjudication()], _profile(), members_df=_members())[0]
    client, _ = _mock_client()
    res = decide_for_me(d, client, model="mock-strong", provider="anthropic")
    assert res.parsed.chosen_option == "preserve-via-convergence-rule"
    assert "UUID" in res.parsed.rationale


# ───────────────────────── menu rendering ─────────────────────────


def test_render_menu_shows_rank_status_and_menu() -> None:
    decs = collect_cm_decisions([_birth_adjudication()], _profile(), graph=_graph(), members_df=_members())
    out = render_menu(decs)
    assert "ranked by uncertainty × blast-radius" in out
    assert "cm-hard" in out
    assert "pending" in out
    assert "preserve-via-convergence-rule" in out


def test_render_menu_empty_is_graceful() -> None:
    assert "no pending design decisions" in render_menu([])
