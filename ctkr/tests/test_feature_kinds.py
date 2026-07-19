"""Tests for the feature × event-kind dependency graph (bead MetaCoding-9h5.21).

Hermetic: synthetic TypeScript contracts for the deterministic extractor, pure-function
checks on the graph/kernel/wave analyses, and a mock LLM provider for the prose fallback.
The live-corpus finding (the 2 real features + the projection) lives in the task report,
not here.
"""

from __future__ import annotations

import json

from ctkr.feature_kinds import (
    FeatureKindProfile,
    FoldEdge,
    MutatorEmit,
    ProjectionFold,
    build_graph,
    build_terra_fallback_prompt,
    extract_from_build,
    extract_from_prose,
    kernel_surface,
    projected_profiles,
    render_mermaid,
    taxonomy_tensions,
    wave_schedule,
)
from ctkr.llm import _ProviderResponse

# A synthetic shared store: prettier-style 2-space class-member indentation. One mutator
# emits `thing_made`; `setState` emits `state_changed`; `countThings` folds `thing_made`
# ungated; `activeThings` folds `thing_made` gated on a status value, reaching
# `state_changed` transitively through the `thingStatus` helper.
_STORE = """
export class SharedStore {
  private append(e) {
    this.events.push(e);
    return e;
  }

  makeThing(name) {
    const seq = this.nextSeq();
    return this.append({ type: "thing_made", seq, name });
  }

  setState(id, status) {
    return this.append({ type: "state_changed", id, status });
  }

  private thingStatus(id) {
    let s = "";
    for (const e of this.events) {
      if (e.type === "state_changed" && e.id === id) s = e.status;
    }
    return s;
  }

  countThings() {
    return this.events.filter((e) => e.type === "thing_made").length;
  }

  activeThings() {
    return this.events.filter(
      (e) => e.type === "thing_made" && this.thingStatus(e.id) === "done",
    );
  }
}
"""

# Feature A (making) uses makeThing + countThings. Feature B (lifecycle) uses makeThing +
# setState + activeThings — sharing `thing_made` with A.
_ADAPTER_A = """
export function makeMakingAdapter(store) {
  return {
    create(name) { return store.makeThing(name); },
    count() { return store.countThings(); },
  };
}
"""
_ADAPTER_B = """
export function makeLifecycleAdapter(store) {
  return {
    create(name) { return store.makeThing(name); },
    setState(id, s) { return store.setState(id, s); },
    active() { return store.activeThings(); },
  };
}
"""


# ───────────────────────── deterministic extraction ─────────────────────────
def _profiles():
    a = extract_from_build(feature="making", store_ts=_STORE, adapter_ts=_ADAPTER_A)
    b = extract_from_build(feature="lifecycle", store_ts=_STORE, adapter_ts=_ADAPTER_B)
    return a, b


def test_extract_emits_and_folds():
    a, b = _profiles()
    assert a.provenance == "extracted"
    a_emits = {e for m in a.mutators for e in m.emits}
    assert a_emits == {"thing_made"}
    a_folds = {f.kind for p in a.projections for f in p.folds}
    assert a_folds == {"thing_made"}
    # feature B emits both kinds (makeThing + setState).
    b_emits = {e for m in b.mutators for e in m.emits}
    assert b_emits == {"thing_made", "state_changed"}


def test_status_gated_flag_and_transitive_fold():
    _, b = _profiles()
    active = next(p for p in b.projections if p.name == "activeThings")
    folds = {f.kind: f.status_gated for f in active.folds}
    # thing_made is folded directly under a status-value filter → gated.
    assert folds["thing_made"] is True
    # state_changed is reached transitively via thingStatus (no gate there) → not gated.
    assert folds.get("state_changed") is False


def test_only_delegated_store_methods_attributed():
    a, _ = _profiles()
    # Feature A never calls setState/activeThings, so it must not carry state_changed.
    names = {m.name for m in a.mutators} | {p.name for p in a.projections}
    assert "setState" not in names
    assert "activeThings" not in names


# ───────────────────────── bipartite graph + kernel ─────────────────────────
def test_build_graph_aggregates_edges_and_status_gate():
    a, b = _profiles()
    g = build_graph([a, b])
    assert set(g.features) == {"making", "lifecycle"}
    # thing_made touched by both features; the fold edge for lifecycle is status-gated.
    fold_gated = {
        (e.feature, e.status_gated)
        for e in g.edges
        if e.kind == "thing_made" and e.role == "fold"
    }
    assert ("lifecycle", True) in fold_gated
    assert ("making", False) in fold_gated


def test_kernel_surface_degree_and_threshold():
    a, b = _profiles()
    g = build_graph([a, b])
    ks = {k.kind: k for k in kernel_surface(g)}
    assert ks["thing_made"].degree == 2
    assert ks["thing_made"].is_kernel is True
    # state_changed only touched by lifecycle → degree 1, not kernel.
    assert ks["state_changed"].degree == 1
    assert ks["state_changed"].is_kernel is False
    # threshold raised to 3 → nothing is kernel with 2 features.
    assert all(not k.is_kernel for k in kernel_surface(g, threshold=3))


# ───────────────────────── taxonomy tension ─────────────────────────
def test_taxonomy_tension_flags_cross_feature_suffix_kinds():
    # Two features each emit a distinct `*_recorded` kind; one has a count-by-kind fold.
    p1 = FeatureKindProfile(
        feature="logs",
        mutators=[MutatorEmit(name="recordLog", emits=["log_recorded"])],
        projections=[ProjectionFold(name="logCount", folds=[FoldEdge(kind="log_recorded")])],
    )
    p2 = FeatureKindProfile(
        feature="loc",
        mutators=[MutatorEmit(name="recordMovement", emits=["movement_recorded"])],
    )
    g = build_graph([p1, p2])
    tensions = taxonomy_tensions(g, [p1, p2])
    assert len(tensions) == 1
    t = tensions[0]
    assert {t.kind_a, t.kind_b} == {"log_recorded", "movement_recorded"}
    assert t.kind_filtered_by == ("logs",)


# ───────────────────────── wave scheduling ─────────────────────────
def test_wave_schedule_serializes_and_freeze_decouples():
    a, b = _profiles()
    g = build_graph([a, b])
    waves = wave_schedule(g)
    # thing_made couples both features → one serialized cluster.
    assert len(waves) == 1
    assert waves[0].size == 2
    assert waves[0].serializes is True
    # Freeze thing_made → the two features decouple into parallel singletons.
    frozen = wave_schedule(g, freeze_kinds=frozenset({"thing_made"}))
    assert len(frozen) == 2
    assert all(c.size == 1 for c in frozen)


def test_disjoint_features_parallelize():
    p1 = FeatureKindProfile(
        feature="x", mutators=[MutatorEmit(name="mx", emits=["kx"])]
    )
    p2 = FeatureKindProfile(
        feature="y", mutators=[MutatorEmit(name="my", emits=["ky"])]
    )
    g = build_graph([p1, p2])
    waves = wave_schedule(g)
    assert len(waves) == 2
    assert all(not c.serializes for c in waves)


# ───────────────────────── projection labelling ─────────────────────────
def test_projected_profiles_are_labelled():
    profs = projected_profiles()
    assert profs
    assert all(p.provenance == "projected" for p in profs)
    assert all(p.citation for p in profs)


def test_projected_edges_carry_projected_provenance():
    a, _ = _profiles()
    g = build_graph([a, *projected_profiles()])
    provs = {e.provenance for e in g.edges}
    assert "extracted" in provs
    assert "projected" in provs


# ───────────────────────── mermaid render ─────────────────────────
def test_render_mermaid_marks_kernel_and_edges():
    a, b = _profiles()
    g = build_graph([a, b])
    mmd = render_mermaid(g)
    assert mmd.startswith("graph LR")
    assert "-->" in mmd  # emit edge
    assert "-.->" in mmd  # fold edge
    assert "|gated|" in mmd  # status-gated fold
    assert "class K_thing_made kernel" in mmd  # thing_made is the degree-2 kernel kind


# ───────────────────────── prose fallback (mock provider) ─────────────────────────
def test_prompt_includes_feature_and_contract():
    prompt = build_terra_fallback_prompt(feature="widgets", contract_text="a widget is made")
    assert "widgets" in prompt
    assert "a widget is made" in prompt


class _MockProvider:
    name = "openai"
    env_var = "OPENAI_API_KEY"

    def __init__(self, payload: dict):
        self._payload = payload

    def complete(self, *a, **k):  # pragma: no cover
        raise NotImplementedError

    def complete_structured(
        self, prompt, *, model, schema, temperature, max_tokens, system, reasoning_effort=None
    ):
        return (
            _ProviderResponse(text=json.dumps(self._payload), input_tokens=100, output_tokens=60),
            self._payload,
        )


def test_prose_fallback_parses_and_labels_terra():
    from ctkr.llm import LLMClient

    payload = {
        "feature": "ignored — overwritten by caller",
        "mutators": [{"name": "recordLog", "emits": ["log_recorded"]}],
        "projections": [
            {"name": "logCount", "folds": [{"kind": "log_recorded", "status_gated": False}]}
        ],
        "provenance": "extracted",
        "citation": "contract line 3: 'a log records a quantity'",
    }
    client = LLMClient(default_provider="openai", default_model="gpt-5.6-terra",
                       structured_repair=True)
    client.register_provider(_MockProvider(payload))  # inject mock
    profile, cost = extract_from_prose(
        feature="logs+quantities",
        contract_text="a log records a quantity",
        client=client,
        model="gpt-5.6-terra",
        provider="openai",
    )
    assert profile.feature == "logs+quantities"  # caller name wins
    assert profile.provenance == "terra"  # forced regardless of model output
    assert cost >= 0.0
    assert profile.mutators[0].emits == ["log_recorded"]
