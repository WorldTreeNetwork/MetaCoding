"""Tests for the intent-CM (consistency-model-sensitivity) tag — port-loop Phase 3.

Hermetic: fixture source trees on disk + a mock LLM provider (no network). Pins the
machinery — detector-table hits on fixtures, deterministic seeding, adjudication
routing over the flagged subset, brief section renders ONLY with a profile, and
determinism of ids/rows. The real-corpus acceptance numbers (MetaCoding self-index,
farmOS) live in the task evidence, not here.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl

from ctkr.intent_cm import (
    INTENT_CM_COLUMNS,
    AdjudicatedCM,
    TargetProfile,
    adjudicate_cm,
    build_target_adaptation_notes,
    load_cm_detectors,
    read_adjudicated_jsonl,
    scan_cm,
    write_adjudicated_jsonl,
    write_intent_cm,
)
from ctkr.llm import LLMClient, _ProviderResponse

# ───────────────────────── fixtures ─────────────────────────

_PHP_ENTITY = """<?php
namespace Drupal\\farm_asset\\Entity;

class Asset {
  public function baseFieldDefinitions() {
    $fields['id'] = BaseFieldDefinition::create('integer')->setLabel('id');
    $fields['name']->addConstraint('UniqueField', []);
    $entity_type->setRevisionable(TRUE);
  }
  public function access($operation, $account) {
    return AccessResult::allowed();
  }
}

function farm_asset_entity_access($entity, $op, $account) {
  return $entity->access('view', $account);
}
"""

_PY_MODEL = """
class Widget:
    id = AutoField(primary_key=True)
    name = CharField(unique=True)

@login_required
def view_widget(request, pk):
    return Widget.objects.select_for_update().get(pk=pk)
"""

_CONFIG_SCHEMA = """farm_asset.settings:
  type: config_object
  mapping:
    code:
      type: string
      unique: true
"""

_CLEAN_TS = """
export function add(a: number, b: number): number {
  return a + b;
}
"""


def _write_tree(root: Path) -> None:
    (root / "src").mkdir(parents=True, exist_ok=True)
    (root / "src" / "Asset.php").write_text(_PHP_ENTITY, encoding="utf-8")
    (root / "models.py").write_text(_PY_MODEL, encoding="utf-8")
    cfg = root / "config" / "schema"
    cfg.mkdir(parents=True, exist_ok=True)
    (cfg / "farm_asset.schema.yml").write_text(_CONFIG_SCHEMA, encoding="utf-8")
    (root / "src" / "math.ts").write_text(_CLEAN_TS, encoding="utf-8")
    # a vendored dir that MUST be skipped
    (root / "vendor").mkdir(exist_ok=True)
    (root / "vendor" / "dep.php").write_text(_PHP_ENTITY, encoding="utf-8")


# ───────────────────────── mock provider ─────────────────────────


class MockCMProvider:
    """Returns a superset CMAdjudicationOut: a verdict per common category. Records
    the models it was called with so routing can be asserted."""

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
            "verdicts": [
                {
                    "category": "autoincrement-id",
                    "sensitivity": "hard",
                    "rationale": "serial id has no monotonic authority offline.",
                    "citation": "src/Asset.php:6",
                },
                {
                    "category": "unique-constraint",
                    "sensitivity": "hard",
                    "rationale": "write-time uniqueness cannot hold across replicas.",
                    "citation": "src/Asset.php:7",
                },
                {
                    "category": "access-check",
                    "sensitivity": "soft",
                    "rationale": "access is a stale snapshot; move to disclosure.",
                    "citation": "src/Asset.php:10",
                },
                {
                    "category": "revision-lock",
                    "sensitivity": "soft",
                    "rationale": "revisions become an eventual merge-aware log.",
                    "citation": "src/Asset.php:8",
                },
                {
                    "category": "transaction",
                    "sensitivity": "none",
                    "rationale": "false positive.",
                    "citation": "",
                },
            ]
        }
        return _ProviderResponse(text=json.dumps(payload), input_tokens=8, output_tokens=8), payload


def _mock_client() -> tuple[LLMClient, MockCMProvider]:
    prov = MockCMProvider()
    c = LLMClient()
    c.register_provider(prov)  # type: ignore[arg-type]
    return c, prov


# ───────────────────────── detector-table + scan ─────────────────────────


def test_detector_table_loads() -> None:
    dets = load_cm_detectors()
    assert dets
    cats = {d.category for d in dets}
    assert cats == {
        "transaction",
        "unique-constraint",
        "autoincrement-id",
        "access-check",
        "revision-lock",
    }
    assert all(d.cm_seed in ("CM-hard", "CM-soft", "CM-none") for d in dets)


def test_scan_hits_expected_categories(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, stats = scan_cm(tmp_path)
    assert df.height > 0
    cats = set(df["category"].to_list())
    # PHP: autoincrement-id, unique-constraint, access-check, revision-lock
    assert {"autoincrement-id", "unique-constraint", "access-check", "revision-lock"} <= cats
    # config-schema unique key picked up
    assert any(
        r["detector_id"] == "config-schema-unique-key" for r in df.iter_rows(named=True)
    )
    # python generic autoincrement + unique + access + select_for_update
    langs = set(df["language"].to_list())
    assert "php" in langs and "python" in langs and "yaml" in langs
    assert df.columns == list(INTENT_CM_COLUMNS)


def test_scan_skips_vendored_dirs(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    files = set(df["file"].to_list())
    assert not any(f.startswith("vendor/") for f in files)


def test_clean_file_yields_no_hits(tmp_path: Path) -> None:
    (tmp_path / "math.ts").write_text(_CLEAN_TS, encoding="utf-8")
    df, _ = scan_cm(tmp_path)
    assert df.height == 0


def test_scan_is_deterministic(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    a, _ = scan_cm(tmp_path)
    b, _ = scan_cm(tmp_path)
    assert a.to_dicts() == b.to_dicts()  # byte-identical rows on re-run


def test_element_id_anchors_to_enclosing_symbol(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    # the access() method hit anchors to a php-function/php-class element, not "file"
    access_rows = df.filter(pl.col("category") == "access-check").to_dicts()
    assert access_rows
    assert any(r["element_kind"] in ("php-function", "php-class") for r in access_rows)
    assert all(":" in r["element_id"] for r in access_rows)


# ───────────────────────── adjudication routing + determinism ─────────────────────────


def test_adjudication_routes_flagged_subset_to_strong_model(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    client, prov = _mock_client()
    rows, stats = adjudicate_cm(df, client, model="strong-m")
    assert stats.n_elements >= 1
    assert prov.models and set(prov.models) == {"strong-m"}
    # only CM-hard/CM-soft seeds routed; every none-seed detector is excluded by default
    assert stats.n_calls == stats.n_elements


def test_adjudication_produces_sensitivity_and_rationale(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    client, _ = _mock_client()
    rows, stats = adjudicate_cm(df, client)
    assert rows
    assert all(r.sensitivity in ("hard", "soft", "none") for r in rows)
    assert any(r.sensitivity == "hard" for r in rows)  # the id/unique element
    assert all(r.adjudication_id.startswith("cm:") for r in rows)
    assert all(r.evidence_refs for r in rows)
    # per_category verdicts landed for at least one element
    assert any(r.per_category for r in rows)


def test_adjudication_ids_are_deterministic(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    ids = []
    for _ in range(2):
        client, _ = _mock_client()
        rows, _ = adjudicate_cm(df, client)
        ids.append(sorted(r.adjudication_id for r in rows))
    assert ids[0] == ids[1]  # id independent of run / LLM output


def test_adjudication_degrades_on_failure(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)

    class _Flaky(MockCMProvider):
        def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
            raise ValueError("boom")

    c = LLMClient()
    c.register_provider(_Flaky())  # type: ignore[arg-type]
    rows, stats = adjudicate_cm(df, c)
    assert stats.n_failed_calls == stats.n_elements
    # degraded elements still produced, falling back to the mechanical prior
    assert rows and all(r.per_category for r in rows)


def test_jsonl_roundtrip(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    client, _ = _mock_client()
    rows, _ = adjudicate_cm(df, client)
    out = tmp_path / "adj.jsonl"
    write_adjudicated_jsonl(rows, out)
    back = read_adjudicated_jsonl(out)
    assert len(back) == len(rows)
    assert all(isinstance(r, AdjudicatedCM) for r in back)
    assert {r.adjudication_id for r in back} == {r.adjudication_id for r in rows}


def test_write_intent_cm_parquet(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    out = tmp_path / "intent_cm.parquet"
    write_intent_cm(df, out)
    back = pl.read_parquet(out)
    assert back.columns == list(INTENT_CM_COLUMNS)
    assert back.height == df.height


# ───────────────────────── target profile + adaptation notes ─────────────────────────


def _profile() -> TargetProfile:
    return TargetProfile(
        id="farmos-local-first",
        name="farmOS local-first port",
        consistency_model="eventual",
        architecture=["event-log", "materialized-views"],
        sync="selective-disclosure",
        summary="offline-first",
        decision_menu=TargetProfile._default_menu(),
    )


def test_profile_loads_from_yaml() -> None:
    repo = Path(__file__).resolve().parents[2]
    p = repo / "docs" / "design" / "target-profiles" / "farmos-local-first.yaml"
    prof = TargetProfile.load(p)
    assert prof.id == "farmos-local-first"
    assert prof.consistency_model == "eventual"
    assert "event-log" in prof.architecture
    assert prof.decision_menu["hard"]  # menu present


def test_profile_load_minimal(tmp_path: Path) -> None:
    y = tmp_path / "p.yaml"
    y.write_text("target_profile:\n  id: bare-target\n", encoding="utf-8")
    prof = TargetProfile.load(y)
    assert prof.id == "bare-target"
    assert prof.decision_menu == TargetProfile._default_menu()  # defaults fill in


def test_adaptation_notes_render_hard_and_soft(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    client, _ = _mock_client()
    rows, _ = adjudicate_cm(df, client)
    notes = build_target_adaptation_notes(rows, _profile())
    assert notes
    text = "\n".join(notes)
    assert "## Target adaptation notes" in text
    assert "Target-conditioned judgment" in text  # clearly labeled, never INTENT
    assert "CM-hard" in text and "Decision menu" in text
    assert "preserve-via-convergence-rule" in text


def test_adaptation_notes_empty_without_sensitive_elements() -> None:
    # no adjudicated rows → no section (system stands alone without CM-sensitive hits)
    assert build_target_adaptation_notes([], _profile()) == []


def test_adaptation_notes_respect_element_filter(tmp_path: Path) -> None:
    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    client, _ = _mock_client()
    rows, _ = adjudicate_cm(df, client)
    one = {rows[0].element_id}
    notes = build_target_adaptation_notes(rows, _profile(), element_filter=one)
    text = "\n".join(notes)
    # only the filtered element's block renders
    assert rows[0].element_id in text
    others = [r for r in rows if r.element_id not in one and r.sensitivity in ("hard", "soft")]
    for r in others:
        assert f"`{r.element_id}`" not in text


# ───────────────────────── brief integration (renders only with profile) ─────────────────────────


def _minimal_card(subsystem_id: str):
    from ctkr.cards import (
        InterfaceCard,
        InterfaceExportCard,
        Provenance,
        SpecBasisSummary,
        SubsystemCard,
        TopologyCard,
    )

    return SubsystemCard(
        card_id=f"card:{subsystem_id}",
        subsystem_id=subsystem_id,
        repo="R",
        name="Assets",
        intent="Manage farm assets.",
        spec_basis_summary=SpecBasisSummary(structural=1.0, nl_only=0.0),
        interface=InterfaceCard(
            provides=[
                InterfaceExportCard(
                    symbol="save",
                    symbol_id="save",
                    role_id=None,
                    usage_modes=["CALLS"],
                    contract="persist an asset",
                    n_external_callers=1,
                )
            ]
        ),
        topology=TopologyCard(n_members=1),
        n_members=1,
        provenance=Provenance(
            generated_at="t", llm_model="m", llm_temperature=0.0, prompt_version="v"
        ),
    )


def _empty_signals() -> pl.DataFrame:
    from ctkr.schema import INTENTION_SIGNALS_COLUMNS

    return pl.DataFrame(schema={c: pl.Utf8 for c in INTENTION_SIGNALS_COLUMNS})


class _NoFusionProvider:
    """Fusion degrades to empty; the deterministic fallbacks fill the brief."""

    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"

    def complete(self, *a, **k):  # noqa: ANN001, ANN002, ANN003
        return _ProviderResponse(text="{}", input_tokens=1, output_tokens=1)

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        return _ProviderResponse(text="{}", input_tokens=1, output_tokens=1), {}


def test_brief_omits_section_without_profile() -> None:
    from ctkr.port_brief import build_port_brief

    c = LLMClient()
    c.register_provider(_NoFusionProvider())  # type: ignore[arg-type]
    md, stats = build_port_brief(_minimal_card("ss:assets"), _empty_signals(), c)
    assert "## Target adaptation notes" not in md  # no profile → no section
    assert stats.n_target_adaptation == 0


def test_brief_includes_section_with_profile(tmp_path: Path) -> None:
    from ctkr.port_brief import build_port_brief

    _write_tree(tmp_path)
    df, _ = scan_cm(tmp_path)
    mc, _ = _mock_client()
    adj, _ = adjudicate_cm(df, mc)
    notes = build_target_adaptation_notes(adj, _profile())
    assert notes  # precondition

    c = LLMClient()
    c.register_provider(_NoFusionProvider())  # type: ignore[arg-type]
    md, stats = build_port_brief(
        _minimal_card("ss:assets"), _empty_signals(), c, target_notes=notes
    )
    assert "## Target adaptation notes" in md
    assert "Target-conditioned judgment" in md
    assert stats.n_target_adaptation >= 1
    # the section sits before the appendix, after warnings
    assert md.index("## Target adaptation notes") < md.index("## Appendix — raw evidence")
    assert md.index("## Warnings") < md.index("## Target adaptation notes")
