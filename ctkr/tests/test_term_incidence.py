"""Tests for the feature × glossary-term incidence graph (bead MetaCoding-01k).

Hermetic: tiny synthetic packs written into tmp_path (no network, no sandbox,
no real port-run dependence). The live-corpus finding (the wave-1 spine split)
lives in the committed artifact under eval/ctkr/results/lexicon/, not here.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pytest

from ctkr.term_incidence import (
    RoleClass,
    build_incidence,
    classify_terms,
    edges_jsonl,
    identity_coverage,
    load_role_classes,
    summary_payload,
)


def _fixture(
    fixture_id: str,
    feature: str,
    asserts: list[str],
    actions: list[str],
    decoy_glossary_terms: list[str] | None = None,
) -> dict:
    """A minimal semantic fixture with the fields the incidence reader uses.

    ``decoy_glossary_terms`` populates the pack-level ``glossary_terms`` list
    with terms NOT exercised in then/when — the incidence must never count them.
    """
    return {
        "fixture_id": fixture_id,
        "feature": feature,
        "glossary_terms": asserts + actions + (decoy_glossary_terms or []),
        "given": [{"entity": "planting", "alias": "bed"}],
        "when": [{"action": a, "alias": f"w{i}"} for i, a in enumerate(actions)],
        "then": [{"assert": a, "subject": "bed", "op": "==", "value": 1} for a in asserts],
    }


def _write_pack(
    pack_dir: Path,
    fixtures: list[dict],
    sealed: bool = True,
    contract: dict | None = None,
) -> Path:
    pack_dir.mkdir(parents=True, exist_ok=True)
    (pack_dir / "fixtures.jsonl").write_text(
        "".join(json.dumps(f) + "\n" for f in fixtures), encoding="utf-8"
    )
    if sealed:
        (pack_dir / "pack.seal.json").write_text("{}", encoding="utf-8")
    if contract is not None:
        (pack_dir / "adapter_contract.json").write_text(
            json.dumps(contract), encoding="utf-8"
        )
    return pack_dir


@pytest.fixture()
def two_feature_root(tmp_path: Path) -> Path:
    """Two features: a shared assertion+action spine, plus one identity term each."""
    root = tmp_path / "runs"
    _write_pack(
        root / "alpha" / "observe",
        [
            _fixture("a1", "alpha", ["log_count", "yield_total"], ["record_log"]),
            _fixture(
                "a2",
                "alpha",
                ["log_count", "stock_on_hand"],
                ["record_log"],
                decoy_glossary_terms=["refused"],  # never exercised → never an edge
            ),
        ],
        contract={"adapter_name": "AlphaAdapter"},
    )
    _write_pack(
        root / "beta" / "observe",
        [
            _fixture("b1", "beta", ["log_count"], ["record_log", "set_parents"]),
            _fixture("b2", "beta", ["yield_total"], ["record_log"]),
        ],
        contract={"adapter_name": "BetaAdapter"},
    )
    return root


def test_edges_come_from_then_and_when_not_glossary_terms(two_feature_root: Path):
    graph = build_incidence([two_feature_root])
    assert graph.features == ["alpha", "beta"]
    terms = {e.term for e in graph.edges}
    # "refused" appears only in the decoy glossary_terms list — must not be counted.
    assert "refused" not in terms
    assert terms == {"log_count", "yield_total", "stock_on_hand", "record_log", "set_parents"}


def test_edge_roles_and_counts(two_feature_root: Path):
    graph = build_incidence([two_feature_root])
    by_key = {(e.feature, e.term, e.role): e.count for e in graph.edges}
    assert by_key[("alpha", "log_count", "assertion")] == 2
    assert by_key[("alpha", "record_log", "action")] == 2
    assert by_key[("beta", "record_log", "action")] == 2
    assert by_key[("beta", "set_parents", "action")] == 1
    # A term never appears under the wrong role.
    assert ("alpha", "record_log", "assertion") not in by_key
    assert ("beta", "log_count", "action") not in by_key


def test_fixture_dedup_across_partial_run_packs(tmp_path: Path):
    """A partial re-recording (same fixture_ids) must not double-count."""
    root = tmp_path / "runs"
    full = [
        _fixture("f1", "gamma", ["log_count"], ["record_log"]),
        _fixture("f2", "gamma", ["yield_total"], ["record_log"]),
    ]
    _write_pack(root / "gamma" / "observe", full)
    _write_pack(root / "gamma" / "observe-partial-run1", full[:1])
    graph = build_incidence([root])
    assert graph.profiles["gamma"].n_fixtures == 2
    by_key = {(e.term, e.role): e.count for e in graph.edges}
    assert by_key[("record_log", "action")] == 2  # not 3
    partial = [p for p in graph.packs if "partial" in p.path.parent.name]
    assert partial[0].n_fixtures == 1 and partial[0].n_new_fixtures == 0


def test_adapter_contract_discovery_wave0_layout(tmp_path: Path):
    """w0-style: <prefix>-observe/fixtures.jsonl + sibling <prefix>-adapter_contract.json."""
    root = tmp_path / "runs"
    _write_pack(root / "w0a-observe", [_fixture("x1", "stock", ["stock_on_hand"], [])])
    (root / "w0a-adapter_contract.json").write_text(
        json.dumps({"adapter_name": "AssetInventoryAdapter"}), encoding="utf-8"
    )
    graph = build_incidence([root])
    assert graph.packs[0].adapter_name == "AssetInventoryAdapter"
    assert graph.profiles["stock"].adapter_names == {"AssetInventoryAdapter"}


def test_seal_presence_is_recorded_not_required(tmp_path: Path):
    root = tmp_path / "runs"
    _write_pack(root / "loose", [_fixture("l1", "delta", ["log_count"], [])], sealed=False)
    graph = build_incidence([root])
    assert graph.packs[0].sealed is False
    assert graph.features == ["delta"]


def test_classification_spine_shared_identity(two_feature_root: Path):
    graph = build_incidence([two_feature_root])
    degrees = {d.term: d for d in classify_terms(graph, spine_threshold=0.8)}
    # degree 2 of 2 features ≥ 80% → SPINE.
    assert degrees["log_count"].classification == "SPINE"
    assert degrees["record_log"].classification == "SPINE"
    assert degrees["yield_total"].classification == "SPINE"
    # degree 1 → IDENTITY.
    assert degrees["stock_on_hand"].classification == "IDENTITY"
    assert degrees["set_parents"].classification == "IDENTITY"


def test_classification_shared_band(tmp_path: Path):
    """With 3 features and threshold 0.8, degree 2 is SHARED (2 < 2.4)."""
    root = tmp_path / "runs"
    for feat, asserts in [("a", ["t_all", "t_two"]), ("b", ["t_all", "t_two"]), ("c", ["t_all"])]:
        _write_pack(root / feat, [_fixture(f"{feat}1", feat, asserts, [])])
    degrees = {d.term: d for d in classify_terms(build_incidence([root]))}
    assert degrees["t_all"].classification == "SPINE"
    assert degrees["t_two"].classification == "SHARED"


def test_single_feature_run_is_all_shared(tmp_path: Path):
    """One feature: degree-1 terms are neither IDENTITY nor SPINE — no split exists."""
    root = tmp_path / "runs"
    _write_pack(root / "solo", [_fixture("s1", "solo", ["log_count"], ["record_log"])])
    degrees = classify_terms(build_incidence([root]))
    assert {d.classification for d in degrees} == {"SHARED"}


def test_identity_coverage_filters_and_ratio(two_feature_root: Path):
    graph = build_incidence([two_feature_root])
    classes = [
        # Nameable by a term alpha exercises → reachable.
        RoleClass("cls-stock", "domain", ("alpha",), ("stock_on_hand",), True),
        # Unnamed (no terms) → unreachable: the lexicon gap.
        RoleClass("cls-gap", "domain", ("alpha",), (), True),
        # Framework kind → excluded from both sides.
        RoleClass("cls-fw", "framework", ("alpha",), ("log_count",), True),
        # Non-distinguishing → excluded from both sides.
        RoleClass("cls-nd", "domain", ("alpha",), ("log_count",), False),
        # Touches only beta → excluded for alpha.
        RoleClass("cls-beta", "domain", ("beta",), ("set_parents",), True),
    ]
    cov = identity_coverage(graph, classes)
    alpha = cov["alpha"]
    assert alpha.reachable == ("cls-stock",)
    assert alpha.unreachable == ("cls-gap",)
    assert alpha.coverage == 0.5
    beta = cov["beta"]
    assert beta.reachable == ("cls-beta",)
    assert beta.coverage == 1.0


def test_identity_coverage_none_when_no_relevant_classes(two_feature_root: Path):
    graph = build_incidence([two_feature_root])
    cov = identity_coverage(graph, [])
    assert cov["alpha"].coverage is None


def test_load_role_classes_defaults_and_missing_id(tmp_path: Path):
    p = tmp_path / "role-classes.jsonl"
    p.write_text(
        json.dumps({"class_id": "c1", "features": ["a"], "terms": ["t"]}) + "\n",
        encoding="utf-8",
    )
    (c1,) = load_role_classes(p)
    assert c1.kind == "domain" and c1.distinguishing is True
    p.write_text(json.dumps({"features": ["a"]}) + "\n", encoding="utf-8")
    with pytest.raises(ValueError, match="class_id"):
        load_role_classes(p)


def test_load_role_classes_accepts_role_gaps_dialect(tmp_path: Path):
    """The actual role-gaps producer dialect loads: summary row skipped,
    tag→kind and glossary_terms→terms aliases honored."""
    p = tmp_path / "role-gaps.jsonl"
    rows = [
        {
            "record_type": "role_class",
            "class_id": "dom1",
            "tag": "domain",
            "features": ["input"],
            "glossary_terms": ["stock_on_hand"],
        },
        {
            "record_type": "role_class",
            "class_id": "fw1",
            "tag": "framework-idiom",
            "features": ["input"],
            "glossary_terms": [],
        },
        {"record_type": "summary", "family": "log", "n_gaps": 7},
    ]
    p.write_text("\n".join(json.dumps(r) for r in rows) + "\n", encoding="utf-8")
    classes = load_role_classes(p)
    assert [c.class_id for c in classes] == ["dom1", "fw1"]
    dom1, fw1 = classes
    assert dom1.kind == "domain" and dom1.terms == ("stock_on_hand",)
    assert fw1.kind == "framework"
    # Explicit kind/terms still win over the aliases.
    p.write_text(
        json.dumps(
            {
                "record_type": "role_class",
                "class_id": "c",
                "kind": "domain",
                "tag": "framework-idiom",
                "terms": ["a"],
                "glossary_terms": ["b"],
            }
        )
        + "\n",
        encoding="utf-8",
    )
    (c,) = load_role_classes(p)
    assert c.kind == "domain" and c.terms == ("a",)


def test_identity_coverage_matches_family_qualified_features(two_feature_root: Path):
    """A pack feature 'alpha' is NOT matched by unrelated names, but a
    qualified pack feature matches its unqualified role-sweep name."""
    root = two_feature_root
    _write_pack(
        root / "qualified",
        [_fixture("q1", "log.alpha", ["stock_on_hand"], ["record_log"])],
    )
    graph = build_incidence([root])
    classes = [
        # Unqualified sweep name touches the qualified pack feature.
        RoleClass("cls-q", "domain", ("alpha",), ("stock_on_hand",), True),
        # No cross-matching on mere suffix text without the dot boundary.
        RoleClass("cls-no", "domain", ("pha",), ("stock_on_hand",), True),
    ]
    cov = identity_coverage(graph, classes)
    assert cov["log.alpha"].reachable == ("cls-q",)
    assert "cls-no" not in cov["log.alpha"].reachable + cov["log.alpha"].unreachable
    # Exact-name matching is unchanged.
    assert cov["alpha"].reachable == ("cls-q",)


def test_edges_jsonl_round_trip(two_feature_root: Path):
    graph = build_incidence([two_feature_root])
    lines = [json.loads(x) for x in edges_jsonl(graph).strip().splitlines()]
    assert len(lines) == len(graph.edges)
    assert set(lines[0]) == {"feature", "term", "role", "count"}


def test_summary_payload_shape_and_relative_paths(two_feature_root: Path, tmp_path: Path):
    graph = build_incidence([two_feature_root])
    degrees = classify_terms(graph)
    payload = summary_payload(graph, degrees, None, 0.8, relative_to=tmp_path)
    assert payload["n_features"] == 2
    split = payload["classification_split"]
    assert split == {"SPINE": 3, "SHARED": 0, "IDENTITY": 2}
    alpha = payload["per_feature"]["alpha"]
    assert alpha["identity_terms"] == ["stock_on_hand"]
    assert alpha["identity_coverage"] == "n/a (no role classes supplied)"
    assert alpha["adapters"] == ["AlphaAdapter"]
    # Paths inside the payload are relative to the requested base, not absolute.
    for pack in payload["packs"]:
        assert not Path(pack["path"]).is_absolute()
    # With coverage supplied, the per-feature block is structured, not the n/a string.
    cov = identity_coverage(graph, [RoleClass("c", "domain", ("alpha",), ("log_count",), True)])
    payload2 = summary_payload(graph, degrees, cov, 0.8)
    assert payload2["per_feature"]["alpha"]["identity_coverage"]["coverage"] == 1.0


def test_cli_command_registered_and_runs(two_feature_root: Path, capsys):
    """The subcommand registers via ctkr.commands auto-discovery and emits --json."""
    from ctkr.cli import main

    rc = main(["term-incidence", str(two_feature_root), "--json"])
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["n_features"] == 2
    assert payload["classification_split"]["IDENTITY"] == 2


def test_cli_missing_root_errors(tmp_path: Path):
    from ctkr.cli import main

    rc = main(["term-incidence", str(tmp_path / "nope")])
    assert rc == 2


def test_cli_role_classes_end_to_end(two_feature_root: Path, tmp_path: Path, capsys):
    rc_path = tmp_path / "role-classes.jsonl"
    rc_path.write_text(
        json.dumps(
            {"class_id": "c-gap", "kind": "domain", "features": ["alpha"], "terms": []}
        )
        + "\n",
        encoding="utf-8",
    )
    from ctkr.cli import main

    out_edges = tmp_path / "out" / "edges.jsonl"
    rc = main(
        [
            "term-incidence",
            str(two_feature_root),
            "--role-classes",
            str(rc_path),
            "--out",
            str(out_edges),
            "--json",
        ]
    )
    assert rc == 0
    payload = json.loads(capsys.readouterr().out)
    alpha_cov = payload["per_feature"]["alpha"]["identity_coverage"]
    assert alpha_cov["coverage"] == 0.0
    assert alpha_cov["unreachable_classes"] == ["c-gap"]
    assert out_edges.exists()
