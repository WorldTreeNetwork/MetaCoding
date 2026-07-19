"""Tests for the signature-generation pass (bead MetaCoding-9h5.15).

Hermetic: an in-memory NetworkX graph for the deterministic member extractor, a mock
LLM provider for the structured synthesis path, and pure-function checks on the prompt
builder + markdown renderer. The live-corpus finding (does the surface pass the
functional judge) lives in the task evidence, not here.
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx

from ctkr.llm import LLMClient, _ProviderResponse
from ctkr.propose_adapter import (
    AdapterContract,
    AdapterMethod,
    AdapterParam,
    SubsystemMember,
    build_contract_prompt,
    extract_subsystem_members,
    load_fixture_candidates,
    render_contract_markdown,
    synthesize_contract,
)


# ───────────────────────── member extraction ─────────────────────────
def _g_with_duplicated_location() -> nx.MultiDiGraph:
    """A tiny scoped graph carrying farmOS's compiled/source path duplication:
    the same interface + class exist under both ``core/location/`` and
    ``modules/core/location/`` and must collapse to one member each."""
    g = nx.MultiDiGraph()
    for base in ("core/location/src", "web/profiles/farm/modules/core/location/src"):
        g.add_node(f"{base}:iface", kind="interface", short_name="AssetLocationInterface",
                   file=f"{base}/AssetLocationInterface.php", line=12)
        g.add_node(f"{base}:cls", kind="class", short_name="AssetLocation",
                   file=f"{base}/AssetLocation.php", line=16)
        g.add_node(f"{base}:m_getloc", kind="method", short_name="getLocation",
                   file=f"{base}/AssetLocation.php", visibility="public",
                   signature="public function getLocation(AssetInterface $asset, $t = NULL): array")
        g.add_node(f"{base}:m_priv", kind="method", short_name="helper",
                   file=f"{base}/AssetLocation.php", visibility="private",
                   signature="private function helper(): void")
    # an out-of-scope class must not leak in
    g.add_node("other", kind="class", short_name="Quantity",
               file="modules/quantity/src/Quantity.php", line=1)
    # a test class in scope must be excluded
    g.add_node("t", kind="class", short_name="AssetLocationTest",
               file="core/location/tests/src/Kernel/AssetLocationTest.php", line=1)
    return g


def test_extract_members_dedupes_duplicated_paths_and_scopes():
    g = _g_with_duplicated_location()
    members = extract_subsystem_members(g, scope_prefixes=["/location/"])
    names = [m.name for m in members]
    # exactly one of each despite the two shipped copies
    assert names.count("AssetLocation") == 1
    assert names.count("AssetLocationInterface") == 1
    assert "Quantity" not in names  # out of scope
    assert "AssetLocationTest" not in names  # test excluded


def test_extract_members_interface_first_and_public_methods_only():
    g = _g_with_duplicated_location()
    members = extract_subsystem_members(g, scope_prefixes=["/location/"])
    assert members[0].is_interface  # interfaces named first
    cls = next(m for m in members if m.name == "AssetLocation")
    meth_names = {m.name for m in cls.methods}
    assert "getLocation" in meth_names
    assert "helper" not in meth_names  # private dropped by public_only default
    getloc = next(m for m in cls.methods if m.name == "getLocation")
    assert "getLocation" in getloc.signature


# ───────────────────────── prompt builder (pure) ─────────────────────────
def test_prompt_includes_members_candidates_and_profile():
    members = [
        SubsystemMember(kind="interface", name="AssetLocationInterface",
                        file="core/location/src/AssetLocationInterface.php", is_interface=True),
    ]
    cands = [{"title": "fixed asset uses intrinsic geometry", "rank_score": 0.9,
              "why_non_obvious": "a general projection would use the movement log",
              "scenario": {"then": ["intrinsic geometry returned"]}}]
    prompt = build_contract_prompt(
        feature_name="asset location & movement", members=members,
        fixture_candidates=cands, target_profile_text="consistency_model: eventual",
        glossary_text="assets can be located",
    )
    assert "asset location & movement" in prompt
    assert "AssetLocationInterface" in prompt
    assert "fixed asset uses intrinsic geometry" in prompt
    assert "consistency_model: eventual" in prompt
    assert "assets can be located" in prompt


def test_prompt_ranks_candidates_by_score():
    members = [SubsystemMember(kind="class", name="X", file="f.php")]
    cands = [
        {"title": "low", "rank_score": 0.1, "scenario": {}},
        {"title": "high", "rank_score": 0.99, "scenario": {}},
    ]
    prompt = build_contract_prompt(
        feature_name="f", members=members, fixture_candidates=cands,
        target_profile_text="p",
    )
    assert prompt.index("high") < prompt.index("low")


# ───────────────────────── synthesis (mock provider) ─────────────────────────
class _MockProvider:
    name = "openai"
    env_var = "OPENAI_API_KEY"

    def __init__(self, payload: dict):
        self._payload = payload

    def complete(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens,
                            system, reasoning_effort=None):
        return _ProviderResponse(text=json.dumps(self._payload), input_tokens=200,
                                 output_tokens=120), self._payload


def _contract_payload() -> dict:
    return {
        "adapter_name": "LocationAdapter",
        "factory_signature": "makeAdapter(): LocationAdapter",
        "mutators": [
            {"name": "recordMovement", "kind": "mutator",
             "params": [{"name": "spec", "type": "MovementSpec", "optional": False}],
             "returns": "Promise<Handle>", "as_of_time": False,
             "semantics": "append a movement event",
             "derived_from": "invented: movements are done logs referencing assets+locations"},
        ],
        "projections": [
            {"name": "currentLocations", "kind": "projection",
             "params": [{"name": "asset", "type": "Handle", "optional": False},
                        {"name": "at", "type": "number", "optional": False}],
             "returns": "Promise<Handle[]>", "as_of_time": True,
             "semantics": "latest done movement at-or-before t; empty if fixed",
             "derived_from": "AssetLocation::getLocation"},
        ],
        "rationale": "events vs reads split from the movement-log model",
    }


def test_synthesize_contract_parses_structured_output():
    client = LLMClient(default_provider="openai", default_model="gpt-5.6-terra")
    client.register_provider(_MockProvider(_contract_payload()))
    members = [SubsystemMember(kind="class", name="AssetLocation", file="f.php")]
    prompt = build_contract_prompt(
        feature_name="loc", members=members, fixture_candidates=[],
        target_profile_text="p",
    )
    contract, cost = synthesize_contract(prompt, client, model="gpt-5.6-terra")
    assert isinstance(contract, AdapterContract)
    assert contract.adapter_name == "LocationAdapter"
    assert len(contract.mutators) == 1 and len(contract.projections) == 1
    assert contract.projections[0].as_of_time is True
    assert cost >= 0.0


# ───────────────────────── markdown renderer ─────────────────────────
def test_render_markdown_emits_interface_and_table():
    contract = AdapterContract.model_validate(_contract_payload())
    md = render_contract_markdown(contract, feature_name="asset location")
    assert "export interface LocationAdapter" in md
    assert "recordMovement(spec: MovementSpec): Promise<Handle>;" in md
    assert "currentLocations(asset: Handle, at: number): Promise<Handle[]>;" in md
    assert "| `currentLocations` | projection | yes |" in md
    # invented mutator surfaced in the derived_from column
    assert "invented:" in md


def test_render_markdown_escapes_pipes():
    contract = AdapterContract(
        adapter_name="A", factory_signature="makeAdapter(): A",
        projections=[AdapterMethod(name="p", kind="projection", params=[AdapterParam(
            name="x", type="number")], returns="number", as_of_time=False,
            semantics="a | b", derived_from="c | d")],
    )
    md = render_contract_markdown(contract)
    assert "a \\| b" in md


# ───────────────────────── io ─────────────────────────
def test_load_fixture_candidates_tolerates_blank_lines(tmp_path: Path):
    p = tmp_path / "fc.jsonl"
    p.write_text('{"title": "a"}\n\n{"title": "b"}\n', encoding="utf-8")
    cands = load_fixture_candidates(p)
    assert [c["title"] for c in cands] == ["a", "b"]
