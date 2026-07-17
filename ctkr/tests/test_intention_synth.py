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

from ctkr.intention_synth import (
    IntentionRow,
    _coerce_int_tags,
    _order_signals,
    _resolve_citations,
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
