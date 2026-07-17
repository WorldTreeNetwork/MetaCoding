"""Tests for the Stage D+E spec-deck fuser (T5).

Uses a mock LLM provider (no network) + a synthetic data dir with the six
structural Parquet artifacts and a tiny exported graph, and asserts the T5
acceptance invariants: one card per subsystem, every nl-only symbol on exactly
one card, complete provenance, and deterministic card_ids that are stable across
re-runs and independent of generated_at.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ctkr.cards import card_id, read_cards, structural_digest
from ctkr.llm import LLMClient, _ProviderResponse
from ctkr.spec_cards import (
    _field_flow,
    _is_zero_centroid,
    build_deck,
    detect_role_dissonance,
    merge_patterns_jsonl,
    name_tokens,
    spec_pattern_id,
)


# ----- mock provider -----


class MockProvider:
    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"

    def __init__(self) -> None:
        self.calls = 0

    def complete(self, prompt, *, model, temperature, max_tokens, system):  # noqa: ANN001
        return _ProviderResponse(text="ok", input_tokens=1, output_tokens=1)

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        self.calls += 1
        # Superset dict: pydantic ignores fields a given schema doesn't declare;
        # required fields across all spec schemas are all present here.
        payload: dict[str, Any] = {
            "name": "Mock Subsystem",
            "intent": "Does a mock job for the rest of the system.",
            "responsibilities": ["do a", "do b"],
            "non_goals": [],
            "label": "Mock Role",
            "description": "A mock structural role.",
            "contract": "Callers may rely on the mock.",
            "meaning": "A mock data shape.",
            "dissonance_kind": None,
            "dissonance_evidence": None,
        }
        return _ProviderResponse(text=json.dumps(payload), input_tokens=5, output_tokens=5), payload


def _mock_client() -> LLMClient:
    c = LLMClient()
    c.register_provider(MockProvider())  # type: ignore[arg-type]
    return c


# ----- fixture builder -----


def _write_fixture(tmp: Path) -> tuple[Path, Path]:
    """Create <tmp>/data/.metacoding-like ctkr dir + a repo_root with sources.

    Returns (data_dir, repo_root)."""
    data_dir = tmp / "data"
    ctkr = data_dir / "ctkr"
    ctkr.mkdir(parents=True)
    export = ctkr / "export"
    export.mkdir()

    repo = "R"
    repo_root = tmp / "src_root"
    (repo_root / repo).mkdir(parents=True)
    src = "\n".join(f"# line {i}\ndef sym_{i}():\n    '''doc {i}'''\n    return {i}" for i in range(40))
    (repo_root / repo / "a.py").write_text(src, encoding="utf-8")

    # symbols: two subsystems. ss:1 has 3 profiled (role) + 2 nl-only; ss:2 has 2 nl-only only.
    def sym(i: int, qn: str, line: int) -> dict:
        return {
            "id": f"s{i}", "kind": "function", "language": "py", "repo": repo,
            "qualified_name": qn, "short_name": qn.split("/")[-1], "file": "a.py",
            "line": line, "col": 0, "end_line": line + 2, "end_col": 0,
            "signature": f"def {qn.split('/')[-1]}()", "visibility": "public",
            "is_abstract": False, "is_static": False, "ast_hash": f"h{i}",
            "branch": "main", "source": "tree-sitter",
        }

    nodes = [
        sym(1, "a.py/parseConfig", 2),
        sym(2, "a.py/validateSchema", 6),
        sym(3, "a.py/applyDefaults", 10),
        sym(4, "a.py/CONST_TABLE", 14),   # nl-only in ss:1
        sym(5, "a.py/README_BLURB", 18),  # nl-only in ss:1
        sym(6, "a.py/xylophone", 22),     # nl-only in ss:2 (incoherent names for dissonance role)
        sym(7, "a.py/qwerty", 26),        # nl-only in ss:2
        # a boundary export target + external symbol
        sym(8, "a.py/PublicApi", 30),
        sym(9, "a.py/ExternalCaller", 34),
    ]
    edges = [
        {"src_id": "s1", "dst_id": "s2", "kind": "CALLS", "count": 3},
        {"src_id": "s2", "dst_id": "s3", "kind": "CALLS", "count": 2},
        {"src_id": "s9", "dst_id": "s8", "kind": "CALLS", "count": 5},  # external -> provides
    ]
    with (export / "nodes.jsonl").open("w") as f:
        for n in nodes:
            f.write(json.dumps(n) + "\n")
    with (export / "edges.jsonl").open("w") as f:
        for e in edges:
            f.write(json.dumps(e) + "\n")

    sv = 1
    # subsystems
    pl.DataFrame([
        {"subsystem_id": "ss:1", "repo": repo, "n_members": 6, "resolution": 1.0,
         "persistence_score": 0.9, "config": json.dumps({"stage": "A", "resolution": 1.0}),
         "generated_at": "2026-01-01T00:00:00Z", "schema_version": sv},
        {"subsystem_id": "ss:2", "repo": repo, "n_members": 2, "resolution": 1.0,
         "persistence_score": 1.0, "config": json.dumps({"stage": "A", "resolution": 1.0}),
         "generated_at": "2026-01-01T00:00:00Z", "schema_version": sv},
    ]).write_parquet(ctkr / "subsystems.parquet")

    # members
    mem = [
        ("ss:1", "s1", "a.py/parseConfig", "structural"),
        ("ss:1", "s2", "a.py/validateSchema", "structural"),
        ("ss:1", "s3", "a.py/applyDefaults", "structural"),
        ("ss:1", "s8", "a.py/PublicApi", "structural"),
        ("ss:1", "s4", "a.py/CONST_TABLE", "locality"),
        ("ss:1", "s5", "a.py/README_BLURB", "locality"),
        ("ss:2", "s6", "a.py/xylophone", "locality"),
        ("ss:2", "s7", "a.py/qwerty", "locality"),
    ]
    pl.DataFrame([
        {"subsystem_id": a, "symbol_id": b, "repo": repo, "qualified_name": c,
         "boundary_confidence": 0.8, "placement": d, "schema_version": sv}
        for a, b, c, d in mem
    ]).write_parquet(ctkr / "subsystem_members.parquet")

    # presentations: ss:1 has one similarity role class over 3 members (s1,s2,s3) + s8 in its own class
    def prow(rid, view, members, exemplar, exqn, card, part):  # noqa: ANN001
        return {
            "subsystem_id": "ss:1", "repo": repo, "role_id": rid, "view": view,
            "granularity": "cos>=0.9" if view == "similarity" else "exact",
            "cardinality": card, "members": members, "exemplar_symbol_id": exemplar,
            "exemplar_qualified_name": exqn, "profile_centroid": [0.1, 0.2],
            "profile_depth": 1, "interface_participation": part, "persistence": 1.0,
            "config": json.dumps({"stage": "C"}), "generated_at": "2026-01-01T00:00:00Z",
            "schema_version": sv,
        }
    pl.DataFrame([
        prow("role:A", "similarity", ["s1", "s2", "s3"], "s1", "a.py/parseConfig", 3, []),
        prow("role:B", "similarity", ["s8"], "s8", "a.py/PublicApi", 1, ["provides"]),
        prow("role:A", "orbit", ["s1", "s2", "s3"], "s1", "a.py/parseConfig", 3, []),
        prow("role:B", "orbit", ["s8"], "s8", "a.py/PublicApi", 1, ["provides"]),
    ]).write_parquet(ctkr / "presentations.parquet")

    # interfaces: s8 provided to external s9; ss:1 consumes nothing external here
    pl.DataFrame([
        {"subsystem_id": "ss:1", "repo": repo, "direction": "provides", "edge_kind": "CALLS",
         "edge_count": 5, "internal_symbol_id": "s8", "internal_qualified_name": "a.py/PublicApi",
         "internal_export_symbol_id": "s8", "internal_export_qualified_name": "a.py/PublicApi",
         "external_symbol_id": "s9", "external_qualified_name": "a.py/ExternalCaller",
         "external_subsystem_id": None, "schema_version": sv},
    ]).write_parquet(ctkr / "interfaces.parquet")

    # data_shapes: one boundary type with two fields
    pl.DataFrame([
        {"subsystem_id": "ss:1", "repo": repo, "type_symbol_id": "s8",
         "type_qualified_name": "a.py/PublicApi", "boundary": True, "field_symbol_id": "s8f1",
         "field_name": "id", "field_type": "str", "read_by_internal": True, "read_by_external": True,
         "written_by_internal": True, "written_by_external": False, "constructed_by": [], "schema_version": sv},
        {"subsystem_id": "ss:1", "repo": repo, "type_symbol_id": "s8",
         "type_qualified_name": "a.py/PublicApi", "boundary": True, "field_symbol_id": "s8f2",
         "field_name": "value", "field_type": "int", "read_by_internal": False, "read_by_external": True,
         "written_by_internal": True, "written_by_external": False, "constructed_by": [], "schema_version": sv},
    ]).write_parquet(ctkr / "data_shapes.parquet")

    # operads: one path op over roles A -> B (boundary)
    pl.DataFrame([
        {"subsystem_id": "ss:1", "repo": repo, "operation_id": "op:1", "view": "similarity",
         "op_kind": "path", "arity": 1, "input_roles": ["role:A"], "output_role": "role:B",
         "edge_kinds": ["CALLS"], "support": 4, "is_boundary_op": True, "associative_observed": True,
         "law_violations": 0, "violation_kind": "", "exemplar_paths": ["a.py/parseConfig -> a.py/PublicApi"],
         "invariance_tier": "I", "config": json.dumps({"stage": "C"}),
         "generated_at": "2026-01-01T00:00:00Z", "schema_version": sv},
    ]).write_parquet(ctkr / "operads.parquet")

    (ctkr / "manifest.json").write_text(json.dumps({
        "generated_at": "2026-01-01T00:00:00Z",
        "alphabet_coverage": {"R": {"note": "alphabet ok", "scip_fraction": 0.5}},
    }), encoding="utf-8")

    return data_dir, repo_root


# ----- unit tests -----


def test_card_id_deterministic_and_gen_at_independent():
    d = structural_digest(member_ids=["b", "a"], role_ids=["r2", "r1"],
                          operation_ids=[], interface_keys=["x"], data_shape_keys=[])
    d2 = structural_digest(member_ids=["a", "b"], role_ids=["r1", "r2"],
                           operation_ids=[], interface_keys=["x"], data_shape_keys=[])
    assert d == d2  # order-independent
    a = card_id(subsystem_id="ss:1", struct_digest=d, prompt_version="v1", llm_model="m")
    b = card_id(subsystem_id="ss:1", struct_digest=d, prompt_version="v1", llm_model="m")
    assert a == b and a.startswith("card:")
    c = card_id(subsystem_id="ss:1", struct_digest=d, prompt_version="v2", llm_model="m")
    assert c != a  # prompt_version changes the id


def test_detect_role_dissonance_fires_on_incoherent_names():
    d = detect_role_dissonance(["p/xylophone", "p/qwerty", "p/plumbus"], cardinality=3)
    assert d is not None and d.kind == "name_incoherence" and d.source == "structural"
    coherent = detect_role_dissonance(["p/userLoad", "p/userSave", "p/userDelete"], cardinality=3)
    assert coherent is None
    assert detect_role_dissonance(["p/a", "p/b"], cardinality=2) is None  # too small


def test_is_zero_centroid_detects_the_floor():
    assert _is_zero_centroid([0.0, 0.0, 0.0]) is True
    assert _is_zero_centroid([]) is True
    assert _is_zero_centroid(None) is True
    assert _is_zero_centroid([0.0, 0.1]) is False


def test_field_flow():
    assert _field_flow({"written_by_external": True, "read_by_internal": True}) == "in"
    assert _field_flow({"written_by_internal": True, "read_by_external": True}) == "out"
    assert _field_flow({}) == "internal"


def test_name_tokens_drops_stopwords():
    assert "config" in name_tokens("a/parseConfig")
    assert "the" not in name_tokens("a/theThing")


def test_spec_pattern_id_stable():
    a = spec_pattern_id("role-class", "role:A", prompt_version="v1", llm_model="m")
    b = spec_pattern_id("role-class", "role:A", prompt_version="v1", llm_model="m")
    assert a == b and a.startswith("role-class:")


# ----- integration: full deck over the fixture -----


def test_build_deck_acceptance(tmp_path: Path):
    data_dir, repo_root = _write_fixture(tmp_path)
    client = _mock_client()

    cards, patterns, evidence, stats = build_deck(
        data_dir=data_dir, repo_root=repo_root, client=client,
        prompt_version="spec-labeler:test", generated_at="2026-02-02T00:00:00Z",
    )

    # one card per subsystem
    assert stats.n_cards == 2
    assert {c.subsystem_id for c in cards} == {"ss:1", "ss:2"}

    # every nl-only symbol appears on exactly one card
    nl_ids: list[str] = [n.symbol_id for c in cards for n in c.nl_only_symbols]
    assert sorted(nl_ids) == ["s4", "s5", "s6", "s7"]
    assert len(nl_ids) == len(set(nl_ids))  # no duplication

    # spec_basis_summary present + sums to 1 on every card
    for c in cards:
        s = c.spec_basis_summary
        assert abs(s.structural + s.nl_only - 1.0) < 1e-6
        # provenance complete
        p = c.provenance
        assert p.llm_model and p.prompt_version == "spec-labeler:test"
        assert p.generated_at == "2026-02-02T00:00:00Z"
        assert p.hom_profiles_generated_at == "2026-01-01T00:00:00Z"
        assert p.indexed_with_scip is True

    ss1 = next(c for c in cards if c.subsystem_id == "ss:1")
    assert ss1.spec_basis_summary.structural == pytest.approx(4 / 6, abs=1e-3)  # s1,s2,s3,s8 structural
    assert len(ss1.roles) >= 1
    assert len(ss1.composition_rules) == 1
    assert len(ss1.interface.provides) == 1
    assert ss1.interface.provides[0].symbol == "PublicApi"
    assert len(ss1.data_shapes) == 1
    assert ss1.data_shapes[0].boundary is True
    assert ss1.topology.internal_edge_histogram.get("CALLS") == 2

    # ss:2 is fully nl-only
    ss2 = next(c for c in cards if c.subsystem_id == "ss:2")
    assert ss2.spec_basis_summary.nl_only == 1.0
    assert {n.symbol_id for n in ss2.nl_only_symbols} == {"s6", "s7"}

    # patterns carry mandatory provenance + the new source_kinds
    kinds = {p.source_kind for p in patterns}
    assert "subsystem" in kinds and "role-class" in kinds
    for p in patterns:
        assert p.llm_model and p.prompt_version == "spec-labeler:test" and p.schema_version >= 1


def test_build_deck_reruns_identical_card_ids(tmp_path: Path):
    data_dir, repo_root = _write_fixture(tmp_path)

    def run(gen_at: str) -> list[str]:
        cards, *_ = build_deck(
            data_dir=data_dir, repo_root=repo_root, client=_mock_client(),
            prompt_version="spec-labeler:test", generated_at=gen_at,
        )
        return sorted(c.card_id for c in cards)

    ids1 = run("2026-02-02T00:00:00Z")
    ids2 = run("2027-09-09T09:09:09Z")  # different generated_at
    assert ids1 == ids2  # card_ids independent of generated_at + stable across re-runs


def test_merge_patterns_jsonl_is_idempotent_and_additive(tmp_path: Path):
    from ctkr.schema_l3 import PatternRow
    from datetime import UTC, datetime

    path = tmp_path / "patterns.jsonl"
    # a pre-existing motif label from another labeler must survive
    path.write_text(json.dumps({
        "pattern_id": "motif:xyz", "source_kind": "motif", "source_ref": "m1",
        "label": "L", "description": "D", "instances": [], "evidence_ids": [],
        "confidence": 1.0, "llm_model": "m", "llm_temperature": 0.0,
        "prompt_version": "motif:v1", "schema_version": 1,
        "generated_at": datetime.now(tz=UTC).isoformat(),
    }) + "\n", encoding="utf-8")

    def mkrow(pid: str) -> PatternRow:
        return PatternRow(
            pattern_id=pid, source_kind="subsystem", source_ref="ss:1", label="x",
            description="y", instances=[], confidence=1.0, llm_model="m",
            llm_temperature=0.0, prompt_version="spec:v1", generated_at=datetime.now(tz=UTC),
        )

    merge_patterns_jsonl(path, [mkrow("subsystem:aaa")])
    merge_patterns_jsonl(path, [mkrow("subsystem:aaa")])  # re-emit same id
    lines = [json.loads(x) for x in path.read_text().splitlines() if x.strip()]
    ids = [r["pattern_id"] for r in lines]
    assert ids.count("subsystem:aaa") == 1  # overwrite, not accumulate
    assert "motif:xyz" in ids  # other labeler's row preserved


def _patch_field_types_to_abs(ctkr: Path, abs_prefix: str) -> None:
    """Overwrite field_type in data_shapes.parquet with absolute worktree paths."""
    data = pl.read_parquet(ctkr / "data_shapes.parquet")
    patched = data.with_columns(
        pl.when(pl.col("field_type").is_not_null())
        .then(pl.lit(abs_prefix) + pl.col("field_type"))
        .otherwise(pl.col("field_type"))
        .alias("field_type")
    )
    patched.write_parquet(ctkr / "data_shapes.parquet")


def test_field_type_worktree_path_normalized(tmp_path: Path):
    """DataFieldCard.type must not contain absolute worktree-checkout paths.

    A deck built from a worktree may have field_type values like
    ``/abs/path/.../str``; after card assembly these must be normalized so
    worktree and main-checkout decks produce identical values (MetaCoding-j3y
    fix 2)."""
    data_dir, repo_root = _write_fixture(tmp_path)
    ctkr = data_dir / "ctkr"
    abs_prefix = "/Users/dukejones/.claude/worktrees/agent-abc123/R/"
    _patch_field_types_to_abs(ctkr, abs_prefix)

    cards, *_ = build_deck(
        data_dir=data_dir, repo_root=repo_root, client=_mock_client(),
        prompt_version="spec-labeler:test", generated_at="2026-02-02T00:00:00Z",
    )
    ss1 = next(c for c in cards if c.subsystem_id == "ss:1")
    assert ss1.data_shapes, "expected at least one data shape card"
    for shape in ss1.data_shapes:
        for f in shape.fields:
            if f.type is not None:
                assert not f.type.startswith("/"), (
                    f"absolute path leaked into DataFieldCard.type: {f.type!r}"
                )


def test_field_type_worktree_equals_main_checkout(tmp_path: Path):
    """A deck built with absolute worktree paths in field_type must produce
    the same DataFieldCard.type values as the unpatched (relative) deck."""
    data_dir, repo_root = _write_fixture(tmp_path)
    ctkr = data_dir / "ctkr"

    # Run 1: unpatched (relative paths as produced by normal main checkout).
    cards_main, *_ = build_deck(
        data_dir=data_dir, repo_root=repo_root, client=_mock_client(),
        prompt_version="spec-labeler:test", generated_at="2026-02-02T00:00:00Z",
    )

    # Patch: inject absolute worktree paths.
    abs_prefix = "/Users/dukejones/.claude/worktrees/agent-abc123/R/"
    _patch_field_types_to_abs(ctkr, abs_prefix)

    # Run 2: patched (absolute worktree paths in field_type).
    cards_wt, *_ = build_deck(
        data_dir=data_dir, repo_root=repo_root, client=_mock_client(),
        prompt_version="spec-labeler:test", generated_at="2026-02-02T00:00:00Z",
    )

    def _field_types(card_list: list) -> list[str]:
        return sorted(
            f.type
            for c in card_list
            for s in c.data_shapes
            for f in s.fields
            if f.type is not None
        )

    assert _field_types(cards_main) == _field_types(cards_wt), (
        "worktree and main-checkout decks produced different DataFieldCard.type values"
    )
