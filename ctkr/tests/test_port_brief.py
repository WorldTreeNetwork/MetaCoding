"""Tests for T5c port-brief renderer (ct-intention-extraction.md §4).

Hermetic: a mock LLM fuser (no network) + synthetic cards + a synthetic
``intention_signals`` frame. Pins the machinery — evidence-budget allocation math
(§4.4), section ordering (§4.2), brief-digest determinism (§8), appendix
materialization, and fusion routing/degradation. The MetaCoding self-index
acceptance run (real model, cost, buildability judgement) lives in the task
evidence, not here.
"""

from __future__ import annotations

import json
from typing import Any

import polars as pl

from ctkr.cards import (
    ElementIntention,
    InterfaceCard,
    InterfaceExportCard,
    Provenance,
    RoleCard,
    SpecBasisSummary,
    SubsystemCard,
    TopologyCard,
)
from ctkr.intention_synth import (
    BehavioralScenario,
    ConflictRecord,
    GlossaryTerm,
    IntentTriple,
)
from ctkr.llm import LLMClient, _ProviderResponse
from ctkr.port_brief import (
    BudgetConfig,
    PortBriefConfig,
    _signals_by_element,
    allocate_evidence_budget,
    brief_digest,
    brief_filename,
    build_port_brief,
    render_brief,
)
from ctkr.schema import INTENTION_SIGNALS_COLUMNS

# ───────────────────────── mock fuser ─────────────────────────


class MockFuser:
    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"

    def __init__(self) -> None:
        self.calls = 0
        self.models: list[str] = []

    def complete(self, prompt, *, model, temperature, max_tokens, system):  # noqa: ANN001
        return _ProviderResponse(text="ok", input_tokens=1, output_tokens=1)

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        self.calls += 1
        self.models.append(model)
        payload: dict[str, Any] = {
            "orientation": "Implement the shapes; read evidence only on the flagged role.",
            "glossary": [
                {"term": "session", "meaning": "a cached auth context", "portability": "universal"},
                {"term": "Impl", "meaning": "irrelevant idiom", "portability": "idiom"},
            ],
            "warnings": [
                {
                    "severity": "port-critical",
                    "element": "get_session",
                    "message": "named as a read but writes across the boundary",
                    "instruction": "trust structure for what happens",
                },
                {
                    "severity": "ambiguous",
                    "element": "role:validator",
                    "message": "structure and intention both thin",
                    "instruction": "",
                },
            ],
        }
        return _ProviderResponse(text=json.dumps(payload), input_tokens=5, output_tokens=5), payload


def _mock_client() -> tuple[LLMClient, MockFuser]:
    prov = MockFuser()
    c = LLMClient()
    c.register_provider(prov)  # type: ignore[arg-type]
    return c, prov


# ───────────────────────── synthetic card + signals ─────────────────────────


def _card() -> SubsystemCard:
    return SubsystemCard(
        card_id="card:test",
        subsystem_id="ss:test",
        repo="R",
        name="Session service",
        intent="Manages cached auth sessions.",
        responsibilities=["cache sessions", "expire stale ones"],
        non_goals=["persistence"],
        spec_basis_summary=SpecBasisSummary(structural=0.8, nl_only=0.2),
        roles=[
            RoleCard(
                role_id="role:validator",
                view="similarity",
                label="Validator",
                description="validates rate policy",
                cardinality=2,
                members=["RateValidator"],
                exemplar_symbol=None,
                exemplar_qualified_name=None,
                profile_depth=1,
                granularity="0.8",
                interface_participation=[],
                invariance_tier="I",
            )
        ],
        interface=InterfaceCard(
            provides=[
                InterfaceExportCard(
                    symbol="get_session",
                    symbol_id="get_session",
                    role_id=None,
                    usage_modes=["CALLS"],
                    contract="returns the cached session",
                    n_external_callers=3,
                )
            ]
        ),
        topology=TopologyCard(n_members=3),
        n_members=3,
        provenance=Provenance(
            generated_at="t", llm_model="m", llm_temperature=0.0, prompt_version="v"
        ),
        intention=[
            ElementIntention(
                element_id="get_session",
                element_kind="interface-export",
                load_class="structure-clear",
                intent=[
                    IntentTriple(
                        statement="Fetch a session by key.", citations=["s1"], portability_tier="I"
                    )
                ],
                glossary=[GlossaryTerm(term="session", meaning="auth context", citations=["s1"])],
                behavioral_scenarios=[
                    BehavioralScenario(
                        behavior="raises on unknown key",
                        given="an unknown key",
                        when="get_session called",
                        then="raises ValueError",
                        citations=["s3"],
                    )
                ],
                conflicts=[
                    ConflictRecord(
                        conflict_id="c1", detector_id="read-name-writes", severity="port-critical",
                        claim="get returns cached session",
                        structural_fact="writes last_seen across boundary",
                        file="svc.py", line_range="10",
                    )
                ],
            ),
            ElementIntention(
                element_id="role:validator",
                element_kind="role-class",
                load_class="ambiguous",
                intent=[
                    IntentTriple(
                        statement="Validate rate policy.", citations=["r1"], portability_tier="N"
                    )
                ],
                glossary=[],
            ),
        ],
        intention_load_summary={
            "structure_clear": 0.5, "intention_critical": 0.0, "ambiguous": 0.5
        },
    )


def _sig(eid, kind, ind, tier, content, port="I", file="svc.py", lr="1") -> dict:
    return {
        "signal_id": f"sig::{eid}::{ind}::{content}",
        "element_id": eid,
        "element_kind": kind,
        "indicator_kind": ind,
        "tier": tier,
        "content": content,
        "file": file,
        "line_range": lr,
        "portability_tier": port,
        "schema_version": 1,
    }


def _signals_df() -> pl.DataFrame:
    rows = [
        _sig("get_session", "interface-export", "S2", "S", "get_session"),
        _sig("get_session", "interface-export", "S4", "S", "Return the cached session"),
        _sig(
            "get_session", "interface-export", "S1", "S",
            "test:test_get_session_raises", file="t.py",
        ),
        # ambiguous role: several signals, all should materialize (uncapped)
        _sig("role:validator", "role-class", "A5", "A", "head *validator (2/2)"),
        _sig("role:validator", "role-class", "S4", "S", "Validate the rate policy"),
        _sig("role:validator", "role-class", "A6", "A", "TODO: tighten the rate window"),
    ]
    return pl.DataFrame(rows).select(INTENTION_SIGNALS_COLUMNS)


# ───────────────────────── budget allocation (§4.4) ─────────────────────────


def test_allocation_is_load_proportional_and_deterministic() -> None:
    sigs = _signals_by_element(_signals_df())
    load = {"get_session": "structure-clear", "role:validator": "ambiguous"}
    ids = ["get_session", "role:validator"]
    cfg = BudgetConfig()
    r1 = allocate_evidence_budget(ids, load, sigs, cfg)
    r2 = allocate_evidence_budget(list(reversed(ids)), load, sigs, cfg)

    # structure-clear → near-zero raw evidence (weight 0 default).
    assert r1.allocations["get_session"].chosen == []
    # ambiguous → all its signals materialized + human flag (§4.4 "everything + flag").
    amb = r1.allocations["role:validator"]
    assert amb.human_flag is True
    assert len(amb.chosen) == 3
    # deterministic: identical outcome regardless of input order.
    assert {k: [s.signal_id for s in v.chosen] for k, v in r1.allocations.items()} == {
        k: [s.signal_id for s in v.chosen] for k, v in r2.allocations.items()
    }


def test_intention_critical_gets_budget_structure_clear_gets_none() -> None:
    sigs = _signals_by_element(_signals_df())
    load = {"get_session": "structure-clear", "role:validator": "intention-critical"}
    r = allocate_evidence_budget(["get_session", "role:validator"], load, sigs, BudgetConfig())
    assert r.allocations["get_session"].chosen == []  # structure-clear ≈ 0
    assert len(r.allocations["role:validator"].chosen) >= 1  # intention-critical carries evidence
    # budget math: appendix = multiple × (n × per-element).
    assert r.total_distilled_budget == 2 * BudgetConfig().distilled_tokens_per_element
    assert r.appendix_budget == int(round(6.0 * r.total_distilled_budget))


def test_appendix_multiple_dial_changes_budget() -> None:
    sigs = _signals_by_element(_signals_df())
    load = {"role:validator": "intention-critical"}
    ids = ["role:validator"]
    small = allocate_evidence_budget(ids, load, sigs, BudgetConfig(appendix_multiple=0.0))
    big = allocate_evidence_budget(ids, load, sigs, BudgetConfig(appendix_multiple=6.0))
    assert small.appendix_budget == 0
    assert big.appendix_budget > small.appendix_budget


# ───────────────────────── digest determinism (§8) ─────────────────────────


def test_brief_digest_stable_and_config_sensitive() -> None:
    card = _card()
    cfg = PortBriefConfig()
    d1 = brief_digest(card, "fdigest", cfg)
    d2 = brief_digest(card, "fdigest", cfg)
    assert d1 == d2 and d1.startswith("brief:")
    # a prompt-version change (a config change) invalidates the digest.
    cfg2 = PortBriefConfig(prompt_version="port-brief:v2")
    assert brief_digest(card, "fdigest", cfg2) != d1
    # a fusion-evidence change invalidates it.
    assert brief_digest(card, "other", cfg) != d1


def test_filename_is_fs_safe() -> None:
    assert brief_filename("ss:abc/def::ghi") == "ss__abc__def____ghi.md"


# ───────────────────────── section ordering (§4.2) ─────────────────────────


def test_section_order_matches_spec() -> None:
    card = _card()
    client, _ = _mock_client()
    md, _ = build_port_brief(card, _signals_df(), client, PortBriefConfig(fusion_model="m"))
    heads = [ln for ln in md.splitlines() if ln.startswith("## ")]
    assert heads == [
        "## Domain glossary",
        "## Interface contract",
        "## Roles",
        "## Composition laws & protocol",
        "## Data shapes",
        "## Behavioral spec (acceptance list)",
        "## Warnings",
        "## Appendix — raw evidence",
    ]
    # header precedes everything (orientation → vocabulary → …).
    assert md.index("# Port brief") < md.index("## Domain glossary")


def test_triples_and_epistemic_labels_present() -> None:
    card = _card()
    client, _ = _mock_client()
    md, stats = build_port_brief(card, _signals_df(), client, PortBriefConfig(fusion_model="m"))
    # every lane label appears; the export block carries all three.
    assert "**SHAPE**" in md and "**INTENT**" in md and "**EVIDENCE**" in md
    # SHAPE structural facts surfaced.
    assert "3 external caller(s)" in md
    # INTENT prose from the synthesized triple.
    assert "Fetch a session by key." in md
    # convention-tier intent is restated-marked (role validator is portability N).
    assert "convention — restated" in md
    # scenarios rendered as the acceptance list.
    assert "raises on unknown key" in md
    assert stats.n_scenarios == 1


def test_glossary_drops_idiom_terms() -> None:
    card = _card()
    client, _ = _mock_client()
    md, _ = build_port_brief(card, _signals_df(), client, PortBriefConfig(fusion_model="m"))
    assert "**session**" in md  # universal term kept
    assert "irrelevant idiom" not in md  # idiom-tier term dropped (§7.2)


# ───────────────────────── appendix materialization ─────────────────────────


def test_ambiguous_evidence_materialized_structure_clear_elided() -> None:
    card = _card()
    client, _ = _mock_client()
    md, _ = build_port_brief(card, _signals_df(), client, PortBriefConfig(fusion_model="m"))
    appendix = md[md.index("## Appendix"):]
    # the ambiguous role's harvested signals appear verbatim in the appendix.
    assert "Validate the rate policy" in appendix
    assert "head *validator" in appendix
    assert "human review flagged" in appendix
    # structure-clear export's raw docstring is NOT dumped into the appendix.
    assert "Return the cached session" not in appendix


def test_warnings_ordered_port_critical_first() -> None:
    card = _card()
    client, _ = _mock_client()
    md, _ = build_port_brief(card, _signals_df(), client, PortBriefConfig(fusion_model="m"))
    warn = md[md.index("## Warnings"):md.index("## Appendix")]
    assert warn.index("port-critical") < warn.index("ambiguous")


# ───────────────────────── fusion routing + degradation ─────────────────────────


def test_fusion_uses_configured_strong_model() -> None:
    card = _card()
    client, prov = _mock_client()
    build_port_brief(card, _signals_df(), client, PortBriefConfig(fusion_model="strong-m"))
    assert prov.models == ["strong-m"]  # exactly one fusion call, on the strong model


class _BrokenFuser(MockFuser):
    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        raise ValueError("simulated fusion failure")


def test_fusion_failure_degrades_to_deterministic_fallback() -> None:
    """A failed fusion call must not abort the brief — it falls back to the
    deterministic per-element glossary + warnings derived from the card."""
    card = _card()
    c = LLMClient()
    c.register_provider(_BrokenFuser())  # type: ignore[arg-type]
    md, stats = build_port_brief(card, _signals_df(), c, PortBriefConfig(fusion_model="m"))
    # fallback glossary still rendered from per-element terms.
    assert "**session**" in md
    # fallback warnings still surface the port-critical conflict + ambiguous element.
    assert "port-critical" in md and "ambiguous" in md
    assert stats.brief_digest.startswith("brief:")


def test_render_is_pure_given_fixed_inputs() -> None:
    """Two renders of the same card + fusion + budget produce identical markdown
    (modulo the footer timestamp, which we pin)."""
    from ctkr.port_brief import BriefFusionOut, allocate_evidence_budget

    card = _card()
    sigs = _signals_by_element(_signals_df())
    ids = [e.element_id for e in card.intention]
    load = {e.element_id: e.load_class for e in card.intention}
    budget = allocate_evidence_budget(ids, load, sigs, BudgetConfig())
    fusion = BriefFusionOut(orientation="read carefully")
    cfg = PortBriefConfig()
    kw = dict(fusion_dig="fd", cfg=cfg, generated_at="2026-01-01")
    md1 = render_brief(card, fusion, budget, sigs, **kw)
    md2 = render_brief(card, fusion, budget, sigs, **kw)
    assert md1 == md2
