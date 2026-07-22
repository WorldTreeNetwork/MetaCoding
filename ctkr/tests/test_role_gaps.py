"""Tests for the family-scoped role-equivalence sweep + idiom filter (MetaCoding-034).

Hermetic: a small synthetic modules/log/* graph, no network, no sandbox
dependence. Pins scoping/feature extraction, the member-wise idiom filter, the
k-recurrence gate, the empty-mapping gap list, TERM-SPEC v1 candidate shape,
determinism, and the CLI wiring (JSONL out to tmp_path only).
"""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import polars as pl
import pytest

from ctkr.hom_profiles import compute_hom_profiles
from ctkr.role_gaps import (
    FAMILY_ROOT_FEATURE,
    class_record,
    feature_of,
    member_idiom_reason,
    role_gaps,
    scope_symbols,
    validate_mapping,
)


def _mk_graph() -> nx.MultiDiGraph:
    """Synthetic log family with two features (birth, harvest) plus scaffolding.

    Role structure (renaming-invariant by construction):
    * one DOMAIN role recurring in BOTH features: a validator method that
      CALLS a sibling and WRITES_FIELD twice (identical hom-profile shape);
    * one framework-idiom role recurring in both features: hook classes whose
      only edges EXTEND an external framework base;
    * one domain singleton (no recurrence) in birth only.
    """
    g = nx.MultiDiGraph()

    def add(nid, file, qn, kind="method", short=None):
        g.add_node(
            nid,
            repo="farm",
            qualified_name=qn,
            short_name=short or qn.split("::")[-1],
            file=file,
            kind=kind,
        )

    # external framework base (out of family scope: empty file)
    add("ext", "", "external::HookBase", kind="class")

    for feat, val, helper, hook in (
        ("birth", "v_birth", "h_birth", "hook_birth"),
        ("harvest", "v_harvest", "h_harvest", "hook_harvest"),
    ):
        f = f"modules/log/{feat}/src/X.php"
        add(val, f, f"{f}::Validate{feat.title()}")
        add(helper, f, f"{f}::Helper{feat.title()}")
        add(hook, f, f"{f}::{feat.title()}Hooks", kind="class")
        # domain role: validator CALLS helper + writes two fields
        g.add_edge(val, helper, key="CALLS", kind="CALLS")
        g.add_edge(val, helper, key="WRITES_FIELD", kind="WRITES_FIELD")
        # framework idiom: hook class only touches the external base
        g.add_edge(hook, "ext", key="EXTENDS", kind="EXTENDS")

    # a family-root symbol and an out-of-family symbol
    add("root", "modules/log/log.module", "modules/log/log.module::log_help")
    add("other", "modules/asset/animal/src/A.php", "modules/asset/animal/src/A.php::A")

    # domain singleton in birth only — different profile shape, references the
    # family-root symbol so the birth/harvest role symmetry stays intact
    add("solo", "modules/log/birth/src/Y.php", "modules/log/birth/src/Y.php::Solo")
    g.add_edge("solo", "root", key="REFERENCES", kind="REFERENCES")
    return g


def _profiles(g: nx.MultiDiGraph) -> pl.DataFrame:
    df, _ = compute_hom_profiles(g)
    return df


# ── scoping ──────────────────────────────────────────────────────────────────


def test_feature_of_paths() -> None:
    assert feature_of("modules/log/birth/src/X.php", "log") == "birth"
    assert feature_of("modules/log/log.module", "log") == FAMILY_ROOT_FEATURE
    assert feature_of("modules/asset/animal/src/A.php", "log") is None
    assert feature_of("", "log") is None


def test_scope_symbols_family_only() -> None:
    g = _mk_graph()
    scoped = scope_symbols(g, "log")
    assert "other" not in scoped
    assert "ext" not in scoped
    assert scoped["v_birth"] == "birth"
    assert scoped["v_harvest"] == "harvest"
    assert scoped["root"] == FAMILY_ROOT_FEATURE


# ── idiom filter ─────────────────────────────────────────────────────────────


def test_member_idiom_reason() -> None:
    g = _mk_graph()
    # hook classes: every non-CONTAINS edge lands on the external base
    assert member_idiom_reason(g, "hook_birth") == "framework-wiring"
    # domain validator: has a domain CALLS edge
    assert member_idiom_reason(g, "v_birth") is None
    # the external node itself
    assert member_idiom_reason(g, "ext") == "external"
    # drupal-base name pattern counts even in-repo
    g.add_node(
        "base",
        repo="farm",
        qualified_name="modules/log/birth/src/B.php::PluginBase",
        short_name="PluginBase",
        file="modules/log/birth/src/B.php",
        kind="class",
    )
    assert member_idiom_reason(g, "base") == "drupal-base"


# ── the sweep ────────────────────────────────────────────────────────────────


def test_role_gaps_recurring_domain_gap() -> None:
    g = _mk_graph()
    result = role_gaps(g, _profiles(g), family="log", k=2)

    by_tag = {}
    for rep in result.classes:
        by_tag.setdefault(rep.tag, []).append(rep)

    # the validator role recurs across birth+harvest and is domain
    domain_recurring = [
        r for r in by_tag.get("domain", []) if r.n_features >= 2
    ]
    assert domain_recurring, "expected a recurring domain class"
    gap = next(r for r in domain_recurring if "v_birth" in r.members)
    assert set(gap.members) == {"v_birth", "v_harvest"}
    assert gap.features == ("birth", "harvest")
    assert gap.glossary_terms == ()
    assert gap.candidate is not None

    # the hook role is framework-idiom (all members pure wiring)
    fw = by_tag.get("framework-idiom", [])
    assert any(set(r.members) == {"hook_birth", "hook_harvest"} for r in fw)
    fw_hook = next(r for r in fw if set(r.members) == {"hook_birth", "hook_harvest"})
    assert fw_hook.candidate is None
    assert fw_hook.idiom_reasons == {"framework-wiring": 2}

    assert result.n_gaps == len([r for r in result.classes if r.candidate])


def test_role_gaps_k_gate_excludes_single_feature_classes() -> None:
    g = _mk_graph()
    result = role_gaps(g, _profiles(g), family="log", k=3)
    # no class spans 3 features -> no recurring domain classes, no gaps
    assert result.n_recurring_domain == 0
    assert result.n_gaps == 0
    assert all(r.candidate is None for r in result.classes)


def test_role_gaps_explicit_mapping_closes_gap() -> None:
    g = _mk_graph()
    profiles = _profiles(g)
    base = role_gaps(g, profiles, family="log", k=2)
    gap = next(r for r in base.classes if r.candidate is not None)

    mapped = role_gaps(
        g, profiles, family="log", k=2, mapping={"record_log": gap.class_id}
    )
    rep = next(r for r in mapped.classes if r.class_id == gap.class_id)
    assert rep.glossary_terms == ("record_log",)
    assert rep.candidate is None
    assert mapped.n_gaps == base.n_gaps - 1


def test_validate_mapping_rejects_non_glossary_terms() -> None:
    with pytest.raises(ValueError, match="not_a_term"):
        validate_mapping({"not_a_term": "abc"})
    g = _mk_graph()
    with pytest.raises(ValueError, match="not_a_term"):
        role_gaps(g, _profiles(g), family="log", mapping={"not_a_term": "x"})


def test_candidate_is_partial_term_spec_v1() -> None:
    g = _mk_graph()
    result = role_gaps(g, _profiles(g), family="log", k=2)
    cand = next(r.candidate for r in result.classes if r.candidate is not None)
    assert set(cand) == {
        "term",
        "kind",
        "description",
        "probe_semantics",
        "discriminating_flow",
        "provenance",
    }
    assert cand["term"] == ""  # unnamed: naming is propose-terms' job
    assert cand["kind"] in ("entity", "action", "assertion")
    assert cand["kind"] == "action"  # members are methods
    prov = cand["provenance"]
    assert prov["first_pack_seal"] is None  # PROVISIONAL until sealed
    assert prov["config_source"] is None
    assert prov["role_class_id"]
    assert prov["punts"]  # honesty: the unfilled parts are declared
    flow = cand["discriminating_flow"]
    assert set(flow) >= {"given", "when", "then"}


def test_role_gaps_deterministic() -> None:
    g = _mk_graph()
    profiles = _profiles(g)
    a = role_gaps(g, profiles, family="log", k=2)
    b = role_gaps(g, profiles, family="log", k=2)
    assert [class_record(r) for r in a.classes] == [
        class_record(r) for r in b.classes
    ]
    assert a.summary() == b.summary()


def test_role_gaps_k_validation() -> None:
    g = _mk_graph()
    with pytest.raises(ValueError, match="k must be >= 1"):
        role_gaps(g, _profiles(g), family="log", k=0)


# ── CLI ──────────────────────────────────────────────────────────────────────


def _write_export(g: nx.MultiDiGraph, out_dir: Path) -> None:
    out_dir.mkdir(parents=True, exist_ok=True)
    with (out_dir / "nodes.jsonl").open("w") as f:
        for nid, attrs in g.nodes(data=True):
            f.write(json.dumps({"id": nid, **attrs}) + "\n")
    with (out_dir / "edges.jsonl").open("w") as f:
        for u, v, kind in g.edges(keys=True):
            f.write(json.dumps({"src_id": u, "dst_id": v, "kind": kind}) + "\n")


def test_cli_role_gaps_writes_jsonl(tmp_path: Path, capsys) -> None:
    from ctkr.cli import main

    _write_export(_mk_graph(), tmp_path / "data")
    out = tmp_path / "role-gaps.jsonl"
    rc = main(
        [
            "role-gaps",
            "--data-dir",
            str(tmp_path / "data"),
            "--family",
            "log",
            "-k",
            "2",
            "--out",
            str(out),
            "--json",
        ]
    )
    assert rc == 0
    lines = [json.loads(l) for l in out.read_text().splitlines()]
    assert lines, "expected JSONL output"
    summary = lines[-1]
    assert summary["record_type"] == "summary"
    assert summary["family"] == "log"
    assert summary["n_gaps"] >= 1
    classes = [l for l in lines if l["record_type"] == "role_class"]
    assert all(
        set(c)
        >= {
            "class_id",
            "members",
            "features",
            "tag",
            "glossary_terms",
            "candidate",
        }
        for c in classes
    )
    # stdout --json summary matches the trailing record's counts
    stdout_summary = json.loads(capsys.readouterr().out)
    assert stdout_summary["n_gaps"] == summary["n_gaps"]
    # nothing was written into the data-dir (read-only sandbox discipline)
    assert sorted(p.name for p in (tmp_path / "data").iterdir()) == [
        "edges.jsonl",
        "nodes.jsonl",
    ]


def test_cli_profiles_out_scratch(tmp_path: Path) -> None:
    from ctkr.cli import main

    _write_export(_mk_graph(), tmp_path / "data")
    scratch = tmp_path / "scratch" / "hom_profiles.parquet"
    out = tmp_path / "out.jsonl"
    rc = main(
        [
            "role-gaps",
            "--data-dir",
            str(tmp_path / "data"),
            "--family",
            "log",
            "--out",
            str(out),
            "--profiles-out",
            str(scratch),
        ]
    )
    assert rc == 0
    assert scratch.exists()
    df = pl.read_parquet(scratch)
    assert "profile_vec" in df.columns
