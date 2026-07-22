"""Tests for the naming joint (bead MetaCoding-5c5).

Hermetic: vendored candidate-row fixtures written to tmp_path, a mock LLM
provider for the structured path (house pattern, cf. test_propose_adapter),
no network, no sandbox dependence. Validates schema enforcement (the flow
sketch may use ONLY existing flow-DSL vocabulary plus the proposed term),
the single house repair retry, cross-channel dedup, and — the posture — that
proposing NEVER touches glossary.py.
"""

from __future__ import annotations

import json
from argparse import Namespace
from pathlib import Path

import pytest
from pydantic import ValidationError

import ctkr.oracle.glossary as glossary_mod
from ctkr.commands import propose_terms as cmd
from ctkr.llm import LLMClient, StructuredOutputError, _ProviderResponse
from ctkr.oracle.glossary import all_terms
from ctkr.propose_terms import (
    SpendExceededError,
    TermProposal,
    build_term_prompt,
    load_candidate_rows,
    merge_channels,
    normalize_rows,
    project_spend,
    propose_all,
)

# ───────────────────────── vendored candidate fixtures ─────────────────────────

CONFIG_ROWS = [
    {
        "candidate": {
            "term": "lab_test_type",
            "kind": "entity",
            "description": "lab_test_type allowed-values list ['soil','tissue','water']",
            "probe_semantics": "read the descriptor delivered for the subject",
            "discriminating_flow": {"given": ["a lab_test_type"], "when": [],
                                    "then": ["asset_active == true"]},
            "provenance": {
                "role_class_id": None,
                "config_source": "modules/log/lab_test/config/install/x.yml:farm_lab_test.lab_test_type.*",
                "punts": ["kind='entity' guessed deterministically"],
                "first_pack_seal": None,
            },
        },
        "gap_kind": "allowed_values",
        "glossary_set": "ENTITY_TERMS",
        "source_ref": "modules/log/lab_test/config/install/x.yml:farm_lab_test.lab_test_type.*",
        "value": ["soil", "tissue", "water"],
    },
    {
        "candidate": {
            "term": "lab",
            "kind": "assertion",
            "description": "bundle field 'lab' on LogType 'lab_test'",
            "probe_semantics": "read the field's delivered value back",
            "discriminating_flow": {"given": ["a land asset"],
                                    "when": ["record_log with lab set"],
                                    "then": ["lab delivered == the recorded value"]},
            "provenance": {
                "role_class_id": None,
                "config_source": "modules/log/lab_test/src/Plugin/Log/LogType/LabTestLog.php:fields.lab",
                "punts": [],
                "first_pack_seal": None,
            },
        },
        "gap_kind": "bundle_field",
        "glossary_set": "ASSERTION_TERMS",
        "source_ref": "modules/log/lab_test/src/Plugin/Log/LogType/LabTestLog.php:fields.lab",
        "value": "lab",
    },
]

ROLE_ROWS = [
    {
        "record_type": "role_class",
        "class_id": "030c2e2414084347",
        "member_names": [
            "modules/log/lab_test/src/FarmLabTestHelper.php::FarmLabTestHelper::labTestTypeAllowedValues",
            "modules/log/birth/src/Hook/EntityHooks.php::EntityHooks",
        ],
        "features": ["birth", "lab_test"],
        "candidate": {
            "term": "",
            "kind": "entity",
            "description": "Unnamed domain role class recurring across features",
            "probe_semantics": "TBD",
            "discriminating_flow": {"given": [], "when": [], "then": []},
            "provenance": {"role_class_id": "030c2e2414084347",
                           "config_source": None,
                           "punts": ["term left blank"],
                           "first_pack_seal": None},
        },
    },
    {
        "record_type": "role_class",
        "class_id": "ffff000011112222",
        "member_names": [
            "modules/log/harvest/src/Hook/ThemeHooks.php::ThemeHooks",
        ],
        "features": ["harvest", "seeding"],
        "candidate": {
            "term": "",
            "kind": "entity",
            "description": "Another unnamed role class",
            "probe_semantics": "TBD",
            "discriminating_flow": {"given": [], "when": [], "then": []},
            "provenance": {"role_class_id": "ffff000011112222",
                           "config_source": None,
                           "punts": [],
                           "first_pack_seal": None},
        },
    },
    # a NON-gap role class (candidate null) must be skipped
    {"record_type": "role_class", "class_id": "aaaa", "member_names": [],
     "features": [], "candidate": None},
    # the trailing summary record must be skipped
    {"record_type": "summary", "family": "log", "n_gaps": 2},
]


def _write_fixture_files(tmp_path: Path) -> tuple[Path, Path]:
    cfg = tmp_path / "gaps.jsonl"
    rol = tmp_path / "roles.jsonl"
    cfg.write_text("".join(json.dumps(r) + "\n" for r in CONFIG_ROWS))
    rol.write_text("".join(json.dumps(r) + "\n" for r in ROLE_ROWS))
    return cfg, rol


# ───────────────────────── loading + dedup ─────────────────────────


def test_load_and_normalize_skips_summary_and_null_candidates(tmp_path):
    cfg, rol = _write_fixture_files(tmp_path)
    cands = normalize_rows(load_candidate_rows([cfg, rol]))
    # 2 config + 2 role gap classes; summary + null-candidate rows dropped
    assert len(cands) == 4
    assert {c.channels for c in cands} == {"config", "role"}


def test_merge_prefers_longest_token_match_and_orders_both_first(tmp_path):
    cfg, rol = _write_fixture_files(tmp_path)
    cands = merge_channels(normalize_rows(load_candidate_rows([cfg, rol])))
    # lab_test_type (3 tokens) claims the role class over 'lab' (1 token)
    both = [c for c in cands if c.channels == "config+role"]
    assert [c.term_hint for c in both] == ["lab_test_type"]
    assert both[0].role_class_id == "030c2e2414084347"
    assert both[0].config_source is not None
    # strongest first, then config-only, then role-only; merged class not re-emitted
    assert cands[0].channels == "config+role"
    assert [c.channels for c in cands] == ["config+role", "config", "role"]
    role_only = [c for c in cands if c.channels == "role"]
    assert role_only[0].role_class_id == "ffff000011112222"
    # provenance merge is recorded as a punt
    assert any("role-equivalence class 030c2e2414084347" in p for p in both[0].punts)


def test_config_channel_dedups_repeated_terms(tmp_path):
    dup = [CONFIG_ROWS[0], CONFIG_ROWS[0]]
    p = tmp_path / "dup.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in dup))
    cands = normalize_rows(load_candidate_rows([p]))
    assert len(cands) == 1
    assert any("also surfaced by config source" in x for x in cands[0].punts)


# ───────────────────────── schema enforcement ─────────────────────────


def _payload(term="lab_test_kind", **over) -> dict:
    d = {
        "term": term,
        "kind": "entity",
        "description": "the closed vocabulary classifying a lab test",
        "probe_semantics": "deliver the lab-test classification for a recorded lab test",
        "discriminating_flow": {
            "given": ["a land asset"],
            "when": [f"record_log with a {term}"],
            "then": ["log_count kind=lab_test == 1"],
        },
    }
    d.update(over)
    return d


def test_valid_proposal_parses():
    p = TermProposal.model_validate(_payload())
    assert p.term == "lab_test_kind"


def test_existing_glossary_term_rejected():
    with pytest.raises(ValidationError, match="ALREADY a bound glossary term"):
        TermProposal.model_validate(_payload(term="harvest"))


def test_non_snake_case_term_rejected():
    with pytest.raises(ValidationError, match="snake_case"):
        TermProposal.model_validate(_payload(term="LabTestKind"))


def test_unknown_when_action_rejected():
    bad = _payload()
    bad["discriminating_flow"]["when"] = ["perform_lab_test on the asset"]
    with pytest.raises(ValidationError, match="unknown action"):
        TermProposal.model_validate(bad)


def test_when_step_may_use_the_proposed_term_itself():
    ok = _payload(term="perform_lab_test", kind="action")
    ok["discriminating_flow"]["when"] = ["perform_lab_test on the asset"]
    TermProposal.model_validate(ok)


def test_unknown_then_assertion_rejected_and_empty_then_rejected():
    bad = _payload()
    bad["discriminating_flow"]["then"] = ["row_count == 1"]
    with pytest.raises(ValidationError, match="unknown assertion"):
        TermProposal.model_validate(bad)
    empty = _payload()
    empty["discriminating_flow"]["then"] = []
    with pytest.raises(ValidationError, match="asserts nothing"):
        TermProposal.model_validate(empty)


# ───────────────────────── mock provider (house pattern) ─────────────────────────


class _SeqProvider:
    """Returns queued payloads in order; records call count."""

    name = "openai"
    env_var = "OPENAI_API_KEY"

    def __init__(self, payloads):
        self.payloads = list(payloads)
        self.calls = 0

    def complete(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, prompt, *, model, schema, temperature,
                            max_tokens, system, reasoning_effort=None):
        self.calls += 1
        payload = self.payloads.pop(0)
        return _ProviderResponse(text=json.dumps(payload), input_tokens=500,
                                 output_tokens=200), payload


def _client(provider) -> LLMClient:
    c = LLMClient(default_provider="openai", default_model="gpt-5.6-terra")
    c.register_provider(provider)
    return c


def _one_candidate(tmp_path):
    cfg, rol = _write_fixture_files(tmp_path)
    return merge_channels(normalize_rows(load_candidate_rows([cfg])))[:1]


def test_propose_all_carries_provenance_and_stays_provisional(tmp_path):
    cands = _one_candidate(tmp_path)
    prov = _SeqProvider([_payload()])
    rows, total = propose_all(cands, _client(prov), provider="openai",
                              model="gpt-5.6-terra")
    assert len(rows) == 1 and prov.calls == 1
    row = rows[0]
    assert set(row) == {"term", "kind", "description", "probe_semantics",
                        "discriminating_flow", "provenance"}
    p = row["provenance"]
    assert p["first_pack_seal"] is None  # PROVISIONAL, always
    assert p["config_source"] == cands[0].config_source  # carried, not authored
    assert any("PROVISIONAL" in x for x in p["punts"])
    assert total > 0


def test_repair_retry_recovers_from_one_invalid_payload(tmp_path):
    cands = _one_candidate(tmp_path)
    bad = _payload()
    bad["discriminating_flow"]["when"] = ["frobnicate the asset"]
    prov = _SeqProvider([bad, _payload()])
    rows, _ = propose_all(cands, _client(prov), provider="openai",
                          model="gpt-5.6-terra")
    assert prov.calls == 2  # exactly one repair retry
    assert rows[0]["term"] == "lab_test_kind"


def test_repair_retry_fails_closed_after_second_invalid(tmp_path):
    cands = _one_candidate(tmp_path)
    bad = _payload()
    bad["discriminating_flow"]["when"] = ["frobnicate the asset"]
    prov = _SeqProvider([bad, dict(bad)])
    with pytest.raises(StructuredOutputError):
        propose_all(cands, _client(prov), provider="openai", model="gpt-5.6-terra")
    assert prov.calls == 2


def test_spend_budget_aborts_mid_run(tmp_path):
    cfg, rol = _write_fixture_files(tmp_path)
    cands = merge_channels(normalize_rows(load_candidate_rows([cfg, rol])))
    prov = _SeqProvider([_payload(term=f"term_{i}") for i in range(len(cands))])
    with pytest.raises(SpendExceededError):
        # 500 in + 200 out on gpt-5.6-terra ≈ $0.0043/call > $0.000001 budget
        propose_all(cands, _client(prov), provider="openai",
                    model="gpt-5.6-terra", max_spend=0.000001)
    assert prov.calls < len(cands) + 1


def test_project_spend_scales_with_prompts():
    one = project_spend(["x" * 4000], "gpt-5.6-terra")
    two = project_spend(["x" * 4000] * 2, "gpt-5.6-terra")
    assert one > 0 and abs(two - 2 * one) < 1e-9


# ───────────────────────── posture: never touches glossary.py ─────────────────────────


def test_proposing_never_touches_glossary(tmp_path):
    glossary_path = Path(glossary_mod.__file__)
    before_bytes = glossary_path.read_bytes()
    before_terms = set(all_terms())

    cands = _one_candidate(tmp_path)
    prov = _SeqProvider([_payload()])
    rows, _ = propose_all(cands, _client(prov), provider="openai",
                          model="gpt-5.6-terra")

    assert glossary_path.read_bytes() == before_bytes
    assert set(all_terms()) == before_terms
    assert rows[0]["term"] not in all_terms()  # proposed, not bound


# ───────────────────────── CLI end-to-end (mocked client) ─────────────────────────


def test_cli_run_end_to_end(tmp_path, monkeypatch):
    cfg, rol = _write_fixture_files(tmp_path)
    out = tmp_path / "term-proposals.jsonl"
    # 3 deduped candidates -> 3 valid payloads
    prov = _SeqProvider([_payload(term=f"term_{i}") for i in range(3)])

    def _mock_build(args, provider):
        c = LLMClient(default_provider="openai", default_model="gpt-5.6-terra",
                      cost_log=Path(args.cost_log))
        c.register_provider(prov)
        return c

    monkeypatch.setattr(cmd, "_build_client", _mock_build)
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")

    args = Namespace(
        candidates=[str(cfg), str(rol)], out=str(out), provider="openai",
        model="gpt-5.6-terra", reasoning_effort=None, max_spend=3.0,
        cache_dir=str(tmp_path / "cache"), cost_log=str(tmp_path / "cost.jsonl"),
        as_json=False,
    )
    assert cmd.run(args) == 0
    rows = [json.loads(x) for x in out.read_text().splitlines()]
    assert len(rows) == 3
    # strongest (both-channel) candidate first: carries BOTH provenance fields
    assert rows[0]["provenance"]["config_source"] is not None
    assert rows[0]["provenance"]["role_class_id"] == "030c2e2414084347"
    assert all(r["provenance"]["first_pack_seal"] is None for r in rows)
    # house cost telemetry respected
    assert (tmp_path / "cost.jsonl").exists()


def test_cli_aborts_on_projected_overspend(tmp_path, monkeypatch):
    cfg, rol = _write_fixture_files(tmp_path)

    class _Explodes:  # the provider must never be called
        name = "openai"
        env_var = "OPENAI_API_KEY"

        def complete_structured(self, *a, **k):  # pragma: no cover
            raise AssertionError("LLM called despite projected overspend")

    monkeypatch.setattr(cmd, "_build_client",
                        lambda args, provider: _client(_Explodes()))
    monkeypatch.setenv("OPENAI_API_KEY", "test-key")
    args = Namespace(
        candidates=[str(cfg), str(rol)], out=str(tmp_path / "o.jsonl"),
        provider="openai", model="gpt-5.6-terra", reasoning_effort=None,
        max_spend=0.0000001, cache_dir=str(tmp_path / "cache"),
        cost_log=str(tmp_path / "cost.jsonl"), as_json=False,
    )
    assert cmd.run(args) == 2
    assert not (tmp_path / "o.jsonl").exists()


def test_prompt_is_deterministic_and_names_the_vocabulary(tmp_path):
    cands = _one_candidate(tmp_path)
    p1, p2 = build_term_prompt(cands[0]), build_term_prompt(cands[0])
    assert p1 == p2  # pure — stable LLM cache keys
    assert "record_log" in p1  # action vocabulary present
    assert "log_status" in p1  # assertion vocabulary present
    assert "lab_test_type" in p1  # candidate hint present
