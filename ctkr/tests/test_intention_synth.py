"""Tests for T5b intention synthesis (ct-intention-extraction.md §8, §9.2).

Hermetic: a mock LLM provider (no network) + synthetic T5a parquet frames. Pins
the machinery — evidence-digest / intention_id determinism, tag-based citation
resolution, scenario distillation from S1 fixtures, adjudication routing on the
flagged subset. The MetaCoding self-index acceptance run (real model, cost,
contradiction review) lives in the task evidence, not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest
from pydantic import ValidationError

from ctkr.intention_synth import (
    IntentionRow,
    ScenarioDistillOut,
    _canonicalize_scenario,
    _coerce_int_tags,
    _order_signals,
    _resolve_citations,
    _ScenarioItemOut,
    evidence_digest,
    intention_id,
    intention_load_summary,
    read_intention_jsonl,
    render_intent_prompt,
    synthesize_intention,
    write_intention_jsonl,
)
from ctkr.llm import LLMClient, _ProviderResponse
from ctkr.schema import (
    INTENTION_CONFLICTS_COLUMNS,
    INTENTION_LOAD_COLUMNS,
    INTENTION_SIGNALS_COLUMNS,
)

# ───────────────────────── mock provider ─────────────────────────


class MockProvider:
    """Superset-payload mock. Cites tags [1,2] so citation-resolution exercises the
    real tag→signal_id path (the fixtures always order ≥2 signals)."""

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
            # ElementIntentOut
            "intent": [
                {
                    "statement": "Validates the rate policy for callers.",
                    "citations": [1, 2],
                    "portability": "universal",
                },
            ],
            "glossary": [
                {"term": "rate", "meaning": "the throttling policy", "citations": [1]},
            ],
            "confidence": 0.9,
            # ScenarioDistillOut
            "scenarios": [
                {
                    "behavior": "rejects unknown key",
                    "given": "an unknown key",
                    "when": "get_session is called",
                    "then": "it raises ValueError",
                    "citations": [1],
                },
            ],
            # AdjudicationOut
            "verdict": "consistent",
            "rationale": "The name and the observed edges agree.",
        }
        return _ProviderResponse(text=json.dumps(payload), input_tokens=5, output_tokens=5), payload


def _mock_client() -> tuple[LLMClient, MockProvider]:
    prov = MockProvider()
    c = LLMClient()
    c.register_provider(prov)  # type: ignore[arg-type]
    return c, prov


# ───────────────────────── synthetic T5a frames ─────────────────────────


def _sig(element_id, kind, ind, tier, content, port="I", file="svc.py", lr="1") -> dict:
    return {
        "signal_id": f"sig::{element_id}::{ind}::{content}",
        "element_id": element_id,
        "element_kind": kind,
        "indicator_kind": ind,
        "tier": tier,
        "content": content,
        "file": file,
        "line_range": lr,
        "portability_tier": port,
        "schema_version": 1,
    }


def _frames() -> tuple[pl.DataFrame, pl.DataFrame, pl.DataFrame]:
    sigs = [
        _sig("get_session", "interface-export", "S2", "S", "get_session", "N"),
        _sig("get_session", "interface-export", "S4", "S", "Return the cached session"),
        _sig(
            "get_session",
            "interface-export",
            "S1",
            "S",
            "test:test_get_session_raises",
            "I",
            "test_svc.py",
        ),
        _sig("get_session", "interface-export", "S3", "S", "raises:ValueError"),
        _sig("role:validator", "role-class", "A5", "A", "head *validator (2/2)", "N"),
        _sig("role:validator", "role-class", "S4", "S", "Validate the rate policy"),
    ]
    signals_df = pl.DataFrame(sigs).select(INTENTION_SIGNALS_COLUMNS)
    load_df = pl.DataFrame(
        [
            {
                "element_id": "get_session",
                "element_kind": "interface-export",
                "structural_determinacy": 0.8,
                "intention_richness": 0.7,
                "load_class": "structure-clear",
                "port_critical_conflict": False,
                "drivers": ["profile mass 5.0", "3 edge kinds"],
                "schema_version": 1,
            },
            {
                "element_id": "role:validator",
                "element_kind": "role-class",
                "structural_determinacy": 0.2,
                "intention_richness": 0.3,
                "load_class": "ambiguous",
                "port_critical_conflict": False,
                "drivers": ["persistence 0.20"],
                "schema_version": 1,
            },
        ]
    ).select(INTENTION_LOAD_COLUMNS)
    conflicts_df = pl.DataFrame(schema={c: pl.Utf8 for c in INTENTION_CONFLICTS_COLUMNS})
    return signals_df, load_df, conflicts_df


# ───────────────────────── tokenizer-adjacent units ─────────────────────────


def test_coerce_int_tags_tolerates_messy_shapes() -> None:
    assert _coerce_int_tags([1, 2, 3]) == [1, 2, 3]
    assert _coerce_int_tags("3") == [3]
    assert _coerce_int_tags("3, 4") == [3, 4]
    assert _coerce_int_tags(["3", 4, "[5]"]) == [3, 4, 5]
    assert _coerce_int_tags(None) == []
    assert _coerce_int_tags([True, "x"]) == []


def test_order_signals_is_deterministic_and_tier_ranked() -> None:
    signals_df, _, _ = _frames()
    rows = signals_df.filter(pl.col("element_id") == "get_session").to_dicts()
    a = _order_signals(rows)
    b = _order_signals(list(reversed(rows)))
    assert [t.signal_id for t in a] == [t.signal_id for t in b]  # order-independent
    assert [t.tag for t in a] == [1, 2, 3, 4]  # 1-based, contiguous
    assert a[0].tier == "S"  # S tier ranks first


def test_resolve_citations_drops_out_of_range_and_dedupes() -> None:
    signals_df, _, _ = _frames()
    rows = signals_df.filter(pl.col("element_id") == "get_session").to_dicts()
    tagged = _order_signals(rows)  # 4 tags
    resolved = _resolve_citations([1, 1, 2, 99, 0], tagged)
    assert resolved == [tagged[0].signal_id, tagged[1].signal_id]  # deduped, in-range only


# ───────────────────────── digest / id determinism (§8) ─────────────────────────


def test_evidence_digest_and_id_are_stable() -> None:
    signals_df, load_df, conf_df = _frames()
    rows = signals_df.filter(pl.col("element_id") == "get_session").to_dicts()
    tagged = _order_signals(rows)
    load = load_df.filter(pl.col("element_id") == "get_session").to_dicts()[0]
    d1 = evidence_digest("get_session", "interface-export", tagged, load, [])
    d2 = evidence_digest(
        "get_session", "interface-export", _order_signals(list(reversed(rows))), load, []
    )
    assert d1 == d2  # independent of input order
    id1 = intention_id("get_session", d1, prompt_version="v1", llm_model="m")
    assert id1.startswith("intent:")
    assert id1 == intention_id("get_session", d1, prompt_version="v1", llm_model="m")
    assert id1 != intention_id("get_session", d1, prompt_version="v2", llm_model="m")


def test_intent_prompt_is_pure_function_of_evidence() -> None:
    signals_df, load_df, _ = _frames()
    rows = signals_df.filter(pl.col("element_id") == "get_session").to_dicts()
    tagged = _order_signals(rows)
    load = load_df.filter(pl.col("element_id") == "get_session").to_dicts()[0]
    p1 = render_intent_prompt("get_session", "interface-export", tagged, load)
    p2 = render_intent_prompt("get_session", "interface-export", tagged, load)
    assert p1 == p2
    assert "[1]" in p1 and "get_session" in p1  # tags + fact sheet present


# ───────────────────────── full synthesis (mock LLM) ─────────────────────────


def test_synthesize_produces_cited_intent_and_scenarios() -> None:
    signals_df, load_df, conf_df = _frames()
    client, prov = _mock_client()
    rows, stats = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=client,
        adjudication_model=None,
    )
    assert stats.n_elements == 2
    by_id = {r.element_id: r for r in rows}

    # export: has S1 → scenario distilled; every citation resolves to a real signal.
    exp = by_id["get_session"]
    assert exp.intent and exp.intent[0].citations
    valid = set(signals_df.filter(pl.col("element_id") == "get_session")["signal_id"].to_list())
    for tr in exp.intent:
        assert set(tr.citations) <= valid  # citation resolution (§9.2 acceptance)
    assert exp.behavioral_scenarios and exp.behavioral_scenarios[0].citations
    assert exp.glossary

    # role: ambiguous load class → flagged for adjudication.
    role = by_id["role:validator"]
    assert role.agreement is not None
    assert role.agreement.verdict in {"consistent", "tension", "contradiction"}
    assert stats.n_adjudications >= 1
    assert stats.n_scenarios >= 1
    assert stats.n_citations_resolved > 0


def test_flagged_subset_only_gets_adjudication() -> None:
    """structure-clear export (no conflict, high confidence) is NOT adjudicated;
    the ambiguous role IS (§8 filtered adjudication)."""
    signals_df, load_df, conf_df = _frames()
    client, _ = _mock_client()
    rows, stats = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=client,
        adjudication_model=None,
    )
    by_id = {r.element_id: r for r in rows}
    assert by_id["get_session"].agreement is None  # structure-clear, high conf → skipped
    assert by_id["role:validator"].agreement is not None  # ambiguous → flagged
    assert stats.n_flagged == 1


def test_synthesis_deterministic_ids_across_runs() -> None:
    signals_df, load_df, conf_df = _frames()
    ids = []
    for _ in range(2):
        client, _ = _mock_client()
        rows, _ = synthesize_intention(
            signals_df=signals_df,
            load_df=load_df,
            conflicts_df=conf_df,
            members_df=None,
            client=client,
            adjudication_model=None,
        )
        ids.append([r.intention_id for r in rows])
    assert ids[0] == ids[1]  # intention_id independent of run / LLM output


def test_intention_jsonl_roundtrip(tmp_path: Path) -> None:
    signals_df, load_df, conf_df = _frames()
    client, _ = _mock_client()
    rows, _ = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=client,
        adjudication_model=None,
    )
    out = tmp_path / "intention.jsonl"
    write_intention_jsonl(rows, out)
    back = read_intention_jsonl(out)
    assert len(back) == len(rows)
    assert all(isinstance(r, IntentionRow) for r in back)
    assert {r.intention_id for r in back} == {r.intention_id for r in rows}


def test_load_summary_fractions_sum_to_one() -> None:
    _, load_df, _ = _frames()
    s = intention_load_summary(load_df)
    assert abs(s["structure_clear"] + s["intention_critical"] + s["ambiguous"] - 1.0) < 1e-6
    assert s["structure_clear"] == 0.5 and s["ambiguous"] == 0.5


def test_adjudication_routes_to_strong_model() -> None:
    """When adjudication_model is set, the flagged element's adjudication call uses
    it while the cheap passes use the base model."""
    signals_df, load_df, conf_df = _frames()
    client, prov = _mock_client()
    synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=client,
        model="cheap-m",
        adjudication_model="strong-m",
    )
    assert "strong-m" in prov.models  # adjudication routed to the strong model
    assert "cheap-m" in prov.models  # intent/scenario on the cheap model


# ───────────────────────── deck attach (§9.1 card extension) ─────────────────────────


def _minimal_card(subsystem_id: str):
    from ctkr.cards import (
        InterfaceCard,
        InterfaceExportCard,
        Provenance,
        RoleCard,
        SpecBasisSummary,
        SubsystemCard,
        TopologyCard,
    )

    return SubsystemCard(
        card_id=f"card:{subsystem_id}",
        subsystem_id=subsystem_id,
        repo="R",
        name="Svc",
        intent="Does a job.",
        spec_basis_summary=SpecBasisSummary(structural=1.0, nl_only=0.0),
        roles=[
            RoleCard(
                role_id="role:validator",
                view="similarity",
                label="Validator",
                description="d",
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
                    contract="c",
                    n_external_callers=1,
                )
            ]
        ),
        topology=TopologyCard(n_members=3),
        n_members=3,
        provenance=Provenance(
            generated_at="t", llm_model="m", llm_temperature=0.0, prompt_version="v"
        ),
    )


def test_attach_intention_to_deck_joins_by_element_id(tmp_path: Path) -> None:
    from ctkr.cards import attach_intention_to_deck

    signals_df, load_df, conf_df = _frames()
    client, _ = _mock_client()
    rows, _ = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=client,
        adjudication_model=None,
    )
    intention_path = tmp_path / "intention.jsonl"
    write_intention_jsonl(rows, intention_path)

    card = _minimal_card("ss:svc")
    (attached,) = attach_intention_to_deck([card], intention_path)
    # both the export and the role element attach to this card.
    attached_ids = {e.element_id for e in attached.intention}
    assert attached_ids == {"get_session", "role:validator"}
    exp = next(e for e in attached.intention if e.element_id == "get_session")
    assert exp.intent and exp.intent[0].citations  # cited intent landed
    assert exp.behavioral_scenarios  # scenarios landed
    # header summary (§5.4): one structure-clear export + one ambiguous role → 0.5/0.5
    assert attached.intention_load_summary is not None
    assert attached.intention_load_summary["structure_clear"] == 0.5
    assert attached.intention_load_summary["ambiguous"] == 0.5


# ───────────────────────── robustness (real-model failure modes) ─────────────────────────


class _StringyListProvider(MockProvider):
    """A cheap-model habit: returns the ``intent`` list field as a JSON *string*
    rather than a list (the observed self-index crash). The before-validator must
    parse it back into a list."""

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        _, payload = super().complete_structured(
            prompt,
            model=model,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
        )
        payload = dict(payload)
        payload["intent"] = json.dumps(payload["intent"])  # stringify the list field
        return _ProviderResponse(text=json.dumps(payload), input_tokens=5, output_tokens=5), payload


def test_stringified_list_field_is_coerced() -> None:
    signals_df, load_df, conf_df = _frames()
    c = LLMClient()
    c.register_provider(_StringyListProvider())  # type: ignore[arg-type]
    rows, stats = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=c,
        adjudication_model=None,
    )
    exp = next(r for r in rows if r.element_id == "get_session")
    assert exp.intent and exp.intent[0].statement  # stringified list parsed back
    assert stats.n_failed_calls == 0  # coerced, not failed


class _FlakyProvider(MockProvider):
    """Raises a non-transient error on the first structured call, then behaves —
    the driver must degrade that element, not abort the batch."""

    def __init__(self) -> None:
        super().__init__()
        self.raised = False

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        if not self.raised:
            self.raised = True
            raise ValueError("simulated malformed response")
        return super().complete_structured(
            prompt,
            model=model,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
        )


def test_one_bad_response_degrades_element_not_batch() -> None:
    signals_df, load_df, conf_df = _frames()
    c = LLMClient()  # no cache; ValueError is non-transient so no slow retries
    c.register_provider(_FlakyProvider())  # type: ignore[arg-type]
    rows, stats = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=c,
        adjudication_model=None,
    )
    assert len(rows) == 2  # both elements produced despite one failed call
    assert stats.n_failed_calls == 1
    # the degraded element still has a valid, deterministic id + empty intent.
    degraded = [r for r in rows if not r.intent]
    assert len(degraded) == 1 and degraded[0].intention_id.startswith("intent:")


class _EmptyThenStrongProvider(MockProvider):
    """Returns empty intent on the cheap model, a filled intent on the strong
    model — exercises the empty-intent fallback (retry once on the strong model)."""

    def __init__(self, cheap: str, strong: str) -> None:
        super().__init__()
        self.cheap = cheap
        self.strong = strong

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        _, payload = super().complete_structured(
            prompt,
            model=model,
            schema=schema,
            temperature=temperature,
            max_tokens=max_tokens,
            system=system,
        )
        payload = dict(payload)
        if model == self.cheap:
            payload["intent"] = []  # cheap model gives up
        return _ProviderResponse(text=json.dumps(payload), input_tokens=5, output_tokens=5), payload


def test_empty_intent_falls_back_to_strong_model() -> None:
    signals_df, load_df, conf_df = _frames()
    c = LLMClient()
    c.register_provider(_EmptyThenStrongProvider("cheap-m", "strong-m"))  # type: ignore[arg-type]
    rows, stats = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=c,
        model="cheap-m",
        adjudication_model="strong-m",
    )
    # both elements had empty cheap intent → both refilled by the strong model.
    assert stats.n_intent_fallbacks == 2
    assert all(r.intent for r in rows)  # no element left empty
    # ids still keyed on the cheap model, so they do not move under fallback.
    assert all(r.intention_id.startswith("intent:") for r in rows)


def test_no_fallback_when_single_model() -> None:
    """With adjudication_model == model there is no stronger tier to retry on, so
    an empty cheap intent stays empty (no infinite/again call)."""
    signals_df, load_df, conf_df = _frames()
    c = LLMClient()
    c.register_provider(_EmptyThenStrongProvider("m", "m"))  # type: ignore[arg-type]
    rows, stats = synthesize_intention(
        signals_df=signals_df,
        load_df=load_df,
        conflicts_df=conf_df,
        members_df=None,
        client=c,
        model="m",
        adjudication_model="m",
    )
    assert stats.n_intent_fallbacks == 0
    assert all(not r.intent for r in rows)


# ───────────────────── scenario schema hardening (9h5.9) ─────────────────────


def test_scenario_alias_outcome_maps_to_then() -> None:
    """An unambiguous synonym (`outcome`) for the missing `then` field is
    relabeled — the value the model produced, not an invented one."""
    item = _ScenarioItemOut.model_validate(
        {
            "behavior": "birth log uniqueness",
            "given": "an asset with a birth log",
            "when": "a second birth log is created",
            "outcome": "the constraint rejects it",
        }
    )
    assert item.then == "the constraint rejects it"
    assert item.behavior == "birth log uniqueness"


def test_scenario_alias_other_then_synonyms_map() -> None:
    for alias in ("result", "expected", "expected_result", "assertion", "ensure"):
        item = _ScenarioItemOut.model_validate(
            {"behavior": "b", "given": "g", "when": "w", alias: "the outcome"}
        )
        assert item.then == "the outcome", alias


def test_scenario_alias_given_when_synonyms_map() -> None:
    item = _ScenarioItemOut.model_validate(
        {
            "behavior": "b",
            "precondition": "a precondition",
            "action": "an action",
            "then": "an outcome",
        }
    )
    assert item.given == "a precondition"
    assert item.when == "an action"


def test_scenario_nested_behavior_object_is_lifted() -> None:
    """`{"behavior": {given, when, then}}` — the whole triple nested under the
    behavior key — is lifted to the top level without loss."""
    item = _ScenarioItemOut.model_validate(
        {
            "behavior": {
                "name": "uniqueness",
                "given": "an asset",
                "when": "a duplicate log",
                "then": "rejected",
                "citations": [1, 2],
            }
        }
    )
    assert item.behavior == "uniqueness"
    assert (item.given, item.when, item.then) == ("an asset", "a duplicate log", "rejected")
    assert item.citations == [1, 2]


def test_scenario_bare_behavior_prose_is_NOT_salvaged() -> None:
    """The exact GPT-5.6 failure shape — a lone `behavior` prose string with no
    given/when/then and no synonyms — must still fail validation. Salvaging it
    would require inventing content; that is the repair retry's job, not the
    alias mapper's."""
    with pytest.raises(ValidationError):
        _ScenarioItemOut.model_validate(
            {"behavior": "Log type test asserting the type plugin contract."}
        )


def test_canonicalize_does_not_overwrite_present_then() -> None:
    """A canonical field already present is never clobbered by a synonym."""
    d = _canonicalize_scenario(
        {"behavior": "b", "given": "g", "when": "w", "then": "real", "outcome": "decoy"}
    )
    assert d["then"] == "real"


def test_scenario_distill_out_tolerates_alias_within_list() -> None:
    """End to end: a ScenarioDistillOut whose one scenario uses `outcome` parses,
    where before the whole distillation degraded to zero scenarios."""
    out = ScenarioDistillOut.model_validate(
        {
            "scenarios": [
                {"behavior": "b", "given": "g", "when": "w", "outcome": "o", "citations": [1]}
            ]
        }
    )
    assert len(out.scenarios) == 1
    assert out.scenarios[0].then == "o"
