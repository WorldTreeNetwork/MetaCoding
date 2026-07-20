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
    CmConstraint,
    SubsystemMember,
    build_contract_prompt,
    check_cm_conformance,
    classify_mechanics,
    extract_subsystem_members,
    format_cm_constraints_block,
    load_cm_decisions,
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


# ─────────────── CM-decision conformance (F2 / MetaCoding-9h5.27) ───────────────
# The wave-0 pilot's highest-severity recipe gap: propose-adapter re-derived
# birth-uniqueness as min-UUID/handle-tiebreak, contradicting the bound
# earliest-HLC-wins kernel decision. The SURFACE stage must consume the bound registry
# as fixed constraints and fail loudly on any re-derived conflicting mechanic.

# The bound decision verbatim from eval/.../kernel-9h5.24/build/cm-decisions.jsonl.
_BIRTH_BOUND = CmConstraint(
    invariant="birth-uniqueness",
    sensitivity="hard",
    menuChoice="preserve-via-convergence-rule",
    convergenceKey="earliest-hlc-wins; later concurrent birth demoted to observation "
    "(never dropped)",
    status="provisional",
    rationale="A birth log is a hard 'at most one per asset' invariant.",
)


def _birth_contract(*, birth_semantics: str) -> AdapterContract:
    """A minimal adapter contract whose birth projection carries the given semantics."""
    return AdapterContract(
        adapter_name="AnimalLifecycleAdapter",
        factory_signature="makeAdapter(): AnimalLifecycleAdapter",
        mutators=[
            AdapterMethod(
                name="recordBirth", kind="mutator",
                params=[AdapterParam(name="spec", type="BirthSpec")],
                returns="Promise<Handle>", as_of_time=False,
                semantics="append a birth log referencing the child asset",
                derived_from="invented: birth is a done log",
            ),
        ],
        projections=[
            AdapterMethod(
                name="getAnimalLifecycle", kind="projection",
                params=[AdapterParam(name="asset", type="Handle"),
                        AdapterParam(name="at", type="number")],
                returns="Promise<Lifecycle>", as_of_time=True,
                semantics=birth_semantics,
                derived_from="AssetBirth::getBirth",
            ),
        ],
        rationale="Birth surface split from the birth-log model.",
    )


def _min_uuid_payload() -> dict:
    """A mock provider payload reproducing the F2 min-UUID re-derivation."""
    contract = _birth_contract(
        birth_semantics=(
            "the lexicographically smallest BirthHandle is the sole accepted canonical "
            "birth per asset; the UUID/handle-tiebreak winner survives and others are "
            "rejected"
        ),
    )
    return contract.model_dump()


def test_conformance_rejects_rederived_min_uuid_mechanic():
    """F2 regression: a surface that re-derives min-UUID for birth-uniqueness conflicts
    with the bound earliest-HLC-wins decision and MUST be rejected."""
    # Synthesize via the mock provider (the min-UUID re-derivation), then gate it.
    client = LLMClient(default_provider="openai", default_model="gpt-5.6-terra")
    client.register_provider(_MockProvider(_min_uuid_payload()))
    members = [SubsystemMember(kind="class", name="AssetBirth", file="f.php")]
    prompt = build_contract_prompt(
        feature_name="animal lifecycle", members=members, fixture_candidates=[],
        target_profile_text="p", cm_constraints=[_BIRTH_BOUND],
    )
    contract, _ = synthesize_contract(prompt, client, model="gpt-5.6-terra")

    conflicts = check_cm_conformance(contract, [_BIRTH_BOUND])
    assert len(conflicts) == 1
    cf = conflicts[0]
    assert cf.invariant == "birth-uniqueness"
    assert "uuid-tiebreak" in cf.conflicting_mechanics
    assert "hlc-order" in cf.bound_mechanics
    # the failure renders the diff (bound rule vs conflicting mechanic)
    rendered = cf.render()
    assert "earliest-hlc-wins" in rendered
    assert "uuid-tiebreak" in rendered


def test_conformance_passes_conforming_surface():
    """A surface that respects the bound earliest-HLC rule (or names no mechanic at all)
    passes the deterministic conformance gate."""
    conforming = _birth_contract(
        birth_semantics=(
            "at most one canonical birth per asset; on concurrent births the earliest by "
            "HLC wins and the later birth is demoted to an observation, never dropped"
        ),
    )
    assert check_cm_conformance(conforming, [_BIRTH_BOUND]) == []

    # A surface that simply states the invariant without a mechanic also conforms.
    silent = _birth_contract(birth_semantics="at most one birth log per asset")
    assert check_cm_conformance(silent, [_BIRTH_BOUND]) == []


def test_conformance_ignores_unresolved_and_mechanic_free_decisions():
    """Unresolved decisions do not constrain; bound decisions whose rule names no
    recognizable convergence mechanic are skipped (nothing deterministic to enforce)."""
    unresolved = CmConstraint(
        invariant="birth-uniqueness", sensitivity="hard",
        menuChoice="preserve-via-convergence-rule",
        convergenceKey="earliest-hlc-wins", status="unresolved",
    )
    min_uuid = _birth_contract(
        birth_semantics="the lexicographically smallest birth handle wins (min-uuid)",
    )
    assert check_cm_conformance(min_uuid, [unresolved]) == []

    # A binding decision with no detectable mechanic (e.g. an id-scheme note) is skipped.
    id_scheme = CmConstraint(
        invariant="id-scheme", sensitivity="hard",
        menuChoice="preserve-via-convergence-rule",
        convergenceKey="replica-scoped client id (prefix_replicaId~counter)",
        status="provisional",
    )
    assert check_cm_conformance(min_uuid, [id_scheme]) == []


def test_classify_mechanics_distinguishes_families():
    assert classify_mechanics("earliest-HLC-wins; demote loser") == {"hlc-order"}
    assert classify_mechanics("lexicographically smallest handle") == {"uuid-tiebreak"}
    assert classify_mechanics("min-uuid tiebreak") == {"uuid-tiebreak"}
    assert classify_mechanics("append mother iff no parent") == set()


def test_load_cm_decisions_skips_comments_and_blanks(tmp_path: Path):
    p = tmp_path / "cm-decisions.jsonl"
    p.write_text(
        "// header comment\n"
        '{"invariant":"birth-uniqueness","sensitivity":"hard",'
        '"menuChoice":"preserve-via-convergence-rule",'
        '"convergenceKey":"earliest-hlc-wins","status":"provisional"}\n'
        "\n"
        '{"invariant":"id-scheme","sensitivity":"hard",'
        '"menuChoice":"preserve-via-convergence-rule",'
        '"convergenceKey":"replica-scoped client id","status":"bound"}\n',
        encoding="utf-8",
    )
    decisions = load_cm_decisions(p)
    assert [d.invariant for d in decisions] == ["birth-uniqueness", "id-scheme"]
    assert decisions[0].convergence_key == "earliest-hlc-wins"
    assert decisions[0].is_binding
    assert decisions[1].status == "bound"


def test_prompt_injects_bound_decisions_as_fixed_constraints():
    members = [SubsystemMember(kind="class", name="AssetBirth", file="f.php")]
    prompt = build_contract_prompt(
        feature_name="animal lifecycle", members=members, fixture_candidates=[],
        target_profile_text="p", cm_constraints=[_BIRTH_BOUND],
    )
    assert "FIXED kernel-bound decisions" in prompt
    assert "birth-uniqueness" in prompt
    # the convergence rule appears VERBATIM
    assert "earliest-hlc-wins; later concurrent birth demoted to observation" in prompt
    # and the block instructs the model not to re-derive
    assert "DO NOT RE-DERIVE" in prompt


def test_format_cm_constraints_block_omits_unresolved():
    unresolved = CmConstraint(
        invariant="x", sensitivity="hard", menuChoice="m",
        convergenceKey="k", status="unresolved",
    )
    assert format_cm_constraints_block([unresolved]) == ""
    assert format_cm_constraints_block([_BIRTH_BOUND]) != ""
