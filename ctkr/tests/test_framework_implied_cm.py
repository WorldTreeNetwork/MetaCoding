"""Tests for framework-implied CM pass + heuristic pre-screen (MetaCoding-vzr).

All hermetic: fixture source trees on disk, mock LLM provider. No network.

Coverage:
- load_framework_implied() reads the versioned table section.
- detect_frameworks() identifies Drupal/Django/Rails from filesystem signals.
- scan_framework_implied() emits correct rows (source='framework-implied',
  deterministic element_ids, correct cm_seed values).
- adjudicate_cm() handles framework-implied rows without LLM call, marks
  adjudication_source='framework-implied'.
- heuristic_prescreen_cm() filters single-seed shallow-detector elements.
- adjudicate_cm() integrates the heuristic filter (adjudication_source=
  'heuristic-prescreen', sensitivity='none').
- Delta proof: routing-YAML fixtures equivalent to the i57 farmOS 'none'
  class (config-route-permission single-seed) are pre-screened, reducing
  the count forwarded to the LM — proving the 43-none class is reduced.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import polars as pl
import pytest

from ctkr.intent_cm import (
    INTENT_CM_COLUMNS,
    AdjudicatedCM,
    FrameworkSpec,
    _DEFAULT_SHALLOW_DETECTORS,
    adjudicate_cm,
    detect_frameworks,
    heuristic_prescreen_cm,
    load_framework_implied,
    scan_cm,
    scan_framework_implied,
)
from ctkr.llm import LLMClient, _ProviderResponse


# ───────────────────────── mock provider (zero LLM cost) ─────────────────────────


class _TrackedProvider:
    """Records every structured call so tests can assert no unexpected LLM calls."""

    name = "anthropic"
    env_var = "ANTHROPIC_API_KEY"

    def __init__(self) -> None:
        self.calls: list[str] = []  # element_id hints from the prompt

    def complete(self, prompt, *, model, temperature, max_tokens, system):  # noqa: ANN001
        return _ProviderResponse(text="{}", input_tokens=1, output_tokens=1)

    def complete_structured(self, prompt, *, model, schema, temperature, max_tokens, system):  # noqa: ANN001
        self.calls.append(prompt[:80])
        payload: dict[str, Any] = {
            "verdicts": [
                {
                    "category": "access-check",
                    "sensitivity": "soft",
                    "rationale": "server-side access check.",
                    "citation": "src/X.php:1",
                },
            ]
        }
        return _ProviderResponse(text=json.dumps(payload), input_tokens=4, output_tokens=4), payload


def _mock_client() -> tuple[LLMClient, _TrackedProvider]:
    prov = _TrackedProvider()
    c = LLMClient()
    c.register_provider(prov)  # type: ignore[arg-type]
    return c, prov


# ───────────────────────── framework-implied table ───────────────────────────────


def test_load_framework_implied_returns_specs() -> None:
    specs = load_framework_implied()
    assert specs, "framework_implied section must have at least one framework"
    ids = {s.id for s in specs}
    assert "drupal" in ids, "Drupal spec must be present"
    assert "django" in ids, "Django spec must be present"
    assert "rails" in ids, "Rails spec must be present"


def test_framework_specs_have_required_cm_categories() -> None:
    specs = load_framework_implied()
    by_id = {s.id: s for s in specs}

    drupal = by_id["drupal"]
    drupal_cats = {f.category for f in drupal.implied_facts}
    assert "transaction" in drupal_cats, "Drupal must imply transaction"
    assert "autoincrement-id" in drupal_cats, "Drupal must imply autoincrement-id"
    assert "access-check" in drupal_cats, "Drupal must imply access-check"

    for fact in drupal.implied_facts:
        assert fact.cm_seed in ("CM-hard", "CM-soft"), f"invalid cm_seed on {fact.id}"
        assert fact.rationale, f"rationale must be non-empty on {fact.id}"


def test_all_framework_implied_cm_seeds_valid() -> None:
    specs = load_framework_implied()
    for spec in specs:
        for fact in spec.implied_facts:
            assert fact.cm_seed in ("CM-hard", "CM-soft"), (
                f"{spec.id}/{fact.id}: cm_seed must be CM-hard or CM-soft"
            )


# ───────────────────────── detect_frameworks ─────────────────────────────────────


def test_detect_drupal_via_info_yml(tmp_path: Path) -> None:
    (tmp_path / "farm_asset").mkdir()
    (tmp_path / "farm_asset" / "farm_asset.info.yml").write_text(
        "name: Farm Asset\ntype: module\ncore_version_requirement: ^9\n",
        encoding="utf-8",
    )
    result = detect_frameworks(tmp_path)
    assert "drupal" in result


def test_detect_django_via_manage_py(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("# django manage.py\n", encoding="utf-8")
    result = detect_frameworks(tmp_path)
    assert "django" in result


def test_detect_django_via_requirements(tmp_path: Path) -> None:
    (tmp_path / "requirements.txt").write_text("Django>=4.0\npsycopg2\n", encoding="utf-8")
    result = detect_frameworks(tmp_path)
    assert "django" in result


def test_detect_rails_via_gemfile(tmp_path: Path) -> None:
    (tmp_path / "Gemfile").write_text(
        "source 'https://rubygems.org'\ngem 'rails', '~> 7.0'\n", encoding="utf-8"
    )
    result = detect_frameworks(tmp_path)
    assert "rails" in result


def test_detect_rails_via_application_record(tmp_path: Path) -> None:
    (tmp_path / "app" / "models").mkdir(parents=True)
    (tmp_path / "app" / "models" / "application_record.rb").write_text(
        "class ApplicationRecord < ActiveRecord::Base\nend\n", encoding="utf-8"
    )
    result = detect_frameworks(tmp_path)
    assert "rails" in result


def test_detect_returns_empty_for_unknown_stack(tmp_path: Path) -> None:
    (tmp_path / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    result = detect_frameworks(tmp_path)
    assert result == []


def test_detect_returns_sorted(tmp_path: Path) -> None:
    (tmp_path / "manage.py").write_text("", encoding="utf-8")
    (tmp_path / "Gemfile").write_text("gem 'rails'\n", encoding="utf-8")
    result = detect_frameworks(tmp_path)
    assert result == sorted(result)


# ───────────────────────── scan_framework_implied ─────────────────────────────────


def _make_drupal_tree(root: Path) -> None:
    (root / "modules" / "farm_log").mkdir(parents=True)
    (root / "modules" / "farm_log" / "farm_log.info.yml").write_text(
        "name: Farm Log\ntype: module\n", encoding="utf-8"
    )


def test_scan_framework_implied_drupal(tmp_path: Path) -> None:
    _make_drupal_tree(tmp_path)
    df, detected = scan_framework_implied(tmp_path)
    assert "drupal" in detected
    assert df.height > 0
    # Must have the source column set to "framework-implied"
    assert (df["source"] == "framework-implied").all()
    # Must cover transaction and autoincrement-id (the categories absent in i57 pattern scan)
    cats = set(df["category"].to_list())
    assert "transaction" in cats, "Drupal must emit transaction-implied row"
    assert "autoincrement-id" in cats, "Drupal must emit autoincrement-id-implied row"


def test_scan_framework_implied_schema_matches_scan_cm(tmp_path: Path) -> None:
    _make_drupal_tree(tmp_path)
    df, _ = scan_framework_implied(tmp_path)
    assert df.columns == list(INTENT_CM_COLUMNS), (
        "scan_framework_implied must produce the same column order as scan_cm"
    )


def test_scan_framework_implied_element_ids_are_deterministic(tmp_path: Path) -> None:
    _make_drupal_tree(tmp_path)
    df1, _ = scan_framework_implied(tmp_path)
    df2, _ = scan_framework_implied(tmp_path)
    assert df1.to_dicts() == df2.to_dicts()


def test_scan_framework_implied_element_id_format(tmp_path: Path) -> None:
    _make_drupal_tree(tmp_path)
    df, _ = scan_framework_implied(tmp_path)
    for eid in df["element_id"].to_list():
        assert eid.startswith("framework-implied:drupal:"), (
            f"element_id must follow 'framework-implied:{{fw}}:{{category}}' pattern; got {eid!r}"
        )


def test_scan_framework_implied_id_prefix(tmp_path: Path) -> None:
    _make_drupal_tree(tmp_path)
    df, _ = scan_framework_implied(tmp_path, id_prefix="repo:")
    for eid in df["element_id"].to_list():
        assert eid.startswith("repo:framework-implied:")


def test_scan_framework_implied_empty_for_unknown_stack(tmp_path: Path) -> None:
    (tmp_path / "index.ts").write_text("export const x = 1;\n", encoding="utf-8")
    df, detected = scan_framework_implied(tmp_path)
    assert detected == []
    assert df.height == 0


def test_scan_framework_implied_no_llm_needed_for_drupal_transaction(tmp_path: Path) -> None:
    """The key delta: farmOS had 0 transaction seeds from pattern scan; framework-implied adds them."""
    _make_drupal_tree(tmp_path)
    # Simulate a "pattern only" scan that found zero transactions (like i57)
    pattern_df, _ = scan_cm(tmp_path)
    transaction_in_pattern = pattern_df.filter(pl.col("category") == "transaction").height
    assert transaction_in_pattern == 0, "fixture must have 0 pattern-level transaction hits"

    # Now add framework-implied
    fw_df, _ = scan_framework_implied(tmp_path)
    transaction_in_fw = fw_df.filter(pl.col("category") == "transaction").height
    assert transaction_in_fw > 0, "framework-implied must add transaction row(s)"


# ───────────────────────── adjudicate_cm handles framework-implied ───────────────


def _combined_df(tmp_path: Path) -> pl.DataFrame:
    """Return scan_cm ++ scan_framework_implied for a Drupal tree (PHP + YAML + framework)."""
    _make_drupal_tree(tmp_path)
    # Add a minimal PHP file with an access pattern so the LLM path is exercised too
    src = tmp_path / "modules" / "farm_log" / "src"
    src.mkdir(parents=True, exist_ok=True)
    (src / "LogAccess.php").write_text(
        "<?php\nclass LogAccess {\n  public function access($op, $account) {\n"
        "    return AccessResult::allowed();\n  }\n}\n",
        encoding="utf-8",
    )
    pattern_df, _ = scan_cm(tmp_path)
    fw_df, _ = scan_framework_implied(tmp_path)
    return pl.concat([pattern_df, fw_df])


def test_adjudicate_cm_framework_implied_bypasses_llm(tmp_path: Path) -> None:
    combined = _combined_df(tmp_path)
    client, prov = _mock_client()

    rows, stats = adjudicate_cm(combined, client)

    fw_rows = [r for r in rows if r.adjudication_source == "framework-implied"]
    assert fw_rows, "must produce framework-implied AdjudicatedCM records"

    # LLM calls must only be for non-framework-implied elements
    fw_eids = {r.element_id for r in fw_rows}
    for call_prompt in prov.calls:
        for eid in fw_eids:
            # Framework-implied element IDs must NOT appear in LLM prompts
            assert eid not in call_prompt


def test_adjudicate_cm_framework_implied_sensitivity_from_cm_seed(tmp_path: Path) -> None:
    _make_drupal_tree(tmp_path)
    fw_df, _ = scan_framework_implied(tmp_path)
    client, prov = _mock_client()

    rows, _ = adjudicate_cm(fw_df, client)
    fw_rows = [r for r in rows if r.adjudication_source == "framework-implied"]

    # transaction and autoincrement-id are CM-hard → sensitivity must be "hard"
    hard_rows = [r for r in fw_rows if "transaction" in r.categories or "autoincrement-id" in r.categories]
    assert hard_rows, "must have hard framework-implied rows for transaction/autoincrement-id"
    assert all(r.sensitivity == "hard" for r in hard_rows)
    # access-check is CM-soft → sensitivity must be "soft"
    soft_rows = [r for r in fw_rows if r.categories == ["access-check"]]
    assert soft_rows
    assert all(r.sensitivity == "soft" for r in soft_rows)
    # No LLM calls for framework-implied-only run
    assert prov.calls == []


def test_adjudicate_cm_framework_implied_adjudication_id_stable(tmp_path: Path) -> None:
    _make_drupal_tree(tmp_path)
    fw_df, _ = scan_framework_implied(tmp_path)
    client1, _ = _mock_client()
    client2, _ = _mock_client()
    rows1, _ = adjudicate_cm(fw_df, client1)
    rows2, _ = adjudicate_cm(fw_df, client2)
    ids1 = sorted(r.adjudication_id for r in rows1)
    ids2 = sorted(r.adjudication_id for r in rows2)
    assert ids1 == ids2


# ───────────────────────── heuristic_prescreen_cm ────────────────────────────────


# Routing YAML fixtures — these match the config-route-permission detector pattern
# and replicate the signal class that produced 43 'none' in i57.
# ONE _permission: line per file → one seed per element_id (file stem) → matches i57 pattern.
_ROUTING_YAML_L10N = """\
farm_l10n.settings:
  path: '/admin/config/farm/l10n'
  defaults:
    _form: 'Drupal\\farm_l10n\\Form\\FarmL10nSettingsForm'
  requirements:
    _permission: 'administer farm language'
"""

_ROUTING_YAML_REPORT = """\
farm_report.index:
  path: '/farm/reports'
  defaults:
    _controller: '...'
  requirements:
    _permission: 'access farm report index'
"""

_ROUTING_YAML_ENTITY = """\
farm_asset.view:
  path: '/asset/{asset}'
  requirements:
    _entity_access: 'asset.view'
"""


def _write_routing_fixtures(root: Path) -> None:
    mods = root / "modules"
    mods.mkdir(exist_ok=True)
    # Each file has ONE _permission: line → 1 seed per element → qualifies for prescreen
    (mods / "farm_l10n.routing.yml").write_text(_ROUTING_YAML_L10N, encoding="utf-8")
    (mods / "farm_report.routing.yml").write_text(_ROUTING_YAML_REPORT, encoding="utf-8")
    # _entity_access also fires config-route-permission; single seed per file
    (mods / "farm_asset.routing.yml").write_text(_ROUTING_YAML_ENTITY, encoding="utf-8")


def test_heuristic_prescreen_catches_shallow_route_elements(tmp_path: Path) -> None:
    _write_routing_fixtures(tmp_path)
    df, _ = scan_cm(tmp_path)
    assert df.height > 0, "fixture must produce seeds"

    route_seeds = df.filter(pl.col("detector_id") == "config-route-permission")
    assert route_seeds.height > 0, "must have config-route-permission seeds"

    send_to_llm, presuppose_none = heuristic_prescreen_cm(df)
    assert presuppose_none.height > 0, "must pre-screen at least one element as none"
    # Presupposed-none elements must all come from config-route-permission
    assert (presuppose_none["detector_id"] == "config-route-permission").all()
    # send_to_llm must not contain those element_ids
    screened_eids = set(presuppose_none["element_id"].to_list())
    llm_eids = set(send_to_llm["element_id"].to_list())
    assert screened_eids.isdisjoint(llm_eids)


def test_heuristic_prescreen_disabled_sends_all_to_llm(tmp_path: Path) -> None:
    _write_routing_fixtures(tmp_path)
    df, _ = scan_cm(tmp_path)
    send_to_llm, presuppose_none = heuristic_prescreen_cm(df, enabled=False)
    assert presuppose_none.height == 0
    assert send_to_llm.height == df.height


def test_heuristic_prescreen_does_not_filter_multi_seed_elements(tmp_path: Path) -> None:
    """An element with >1 seed must never be pre-screened (might be a genuine CM concern)."""
    _write_routing_fixtures(tmp_path)
    df, _ = scan_cm(tmp_path)
    _, presuppose_none = heuristic_prescreen_cm(df)
    # Count seeds per presupposed-none element — must all be 1
    if presuppose_none.height > 0:
        counts = (
            presuppose_none.group_by("element_id")
            .agg(pl.len().alias("n_seeds"))["n_seeds"]
            .to_list()
        )
        assert all(n == 1 for n in counts), "only single-seed elements may be pre-screened"


def test_heuristic_prescreen_does_not_filter_hard_seeds(tmp_path: Path) -> None:
    """CM-hard seeds must never be pre-screened regardless of seed count."""
    import re as _re
    # Inject a CM-hard hit (unique constraint in YAML) — must not be pre-screened
    cfg = tmp_path / "config" / "schema"
    cfg.mkdir(parents=True)
    (cfg / "fake.schema.yml").write_text(
        "fake_entity:\n  type: config_object\n  mapping:\n    code:\n      unique: true\n",
        encoding="utf-8",
    )
    df, _ = scan_cm(tmp_path)
    hard_seeds = df.filter(pl.col("cm_seed") == "CM-hard")
    assert hard_seeds.height > 0, "fixture must produce CM-hard seeds"

    _, presuppose_none = heuristic_prescreen_cm(df)
    hard_screened = presuppose_none.filter(pl.col("cm_seed") == "CM-hard")
    assert hard_screened.height == 0, "CM-hard seeds must never be pre-screened"


def test_heuristic_prescreen_custom_shallow_detectors(tmp_path: Path) -> None:
    """Custom shallow_detectors set gates which detectors are eligible for pre-screening."""
    _write_routing_fixtures(tmp_path)
    df, _ = scan_cm(tmp_path)
    # Empty set → nothing pre-screened
    send_all, none_none = heuristic_prescreen_cm(df, shallow_detectors=frozenset())
    assert none_none.height == 0
    assert send_all.height == df.height


# ───────────────────────── adjudicate_cm integrates heuristic filter ─────────────


def test_adjudicate_cm_heuristic_produces_none_adjudication_source(tmp_path: Path) -> None:
    _write_routing_fixtures(tmp_path)
    df, _ = scan_cm(tmp_path)
    client, prov = _mock_client()

    rows, stats = adjudicate_cm(df, client, use_heuristic_filter=True)
    hn_rows = [r for r in rows if r.adjudication_source == "heuristic-prescreen"]
    assert hn_rows, "must produce heuristic-prescreen records"
    assert all(r.sensitivity == "none" for r in hn_rows)
    # Presupposed-none elements must not appear in LLM calls
    hn_eids = {r.element_id for r in hn_rows}
    for prompt_snippet in prov.calls:
        for eid in hn_eids:
            assert eid not in prompt_snippet


def test_adjudicate_cm_heuristic_disabled_sends_routing_to_llm(tmp_path: Path) -> None:
    _write_routing_fixtures(tmp_path)
    df, _ = scan_cm(tmp_path)
    client_on, prov_on = _mock_client()
    client_off, prov_off = _mock_client()

    adjudicate_cm(df, client_on, use_heuristic_filter=True)
    adjudicate_cm(df, client_off, use_heuristic_filter=False)

    # With filter ON, fewer LLM calls (pre-screened elements skip the model)
    assert prov_on.calls <= prov_off.calls, (
        "heuristic filter must reduce or equal the LLM call count"
    )


# ───────────────────────── delta-proof: i57-none reduction via fixtures ───────────


def test_heuristic_filter_reduces_elements_sent_to_llm(tmp_path: Path) -> None:
    """Delta proof (fixture-based, no paid re-run).

    Reproduces the signal class responsible for the 43-none adjudications in the i57
    farmOS run: single-seed config-route-permission hits on routing.yml files. With the
    heuristic filter ON these elements are pre-screened as 'none' and NOT forwarded to
    the strong model, demonstrating the cost-reduction mechanism.
    """
    # Build a tree with multiple routing YAML files (like farmOS has ~12 routing.yml nones)
    mods = tmp_path / "modules"
    mods.mkdir()
    for i in range(8):
        # Each file creates at least one config-route-permission hit → 8 elements
        (mods / f"farm_module{i}.routing.yml").write_text(
            f"farm_module{i}.index:\n"
            f"  path: '/farm/module{i}'\n"
            f"  requirements:\n"
            f"    _permission: 'administer farm module{i}'\n",
            encoding="utf-8",
        )

    df, _ = scan_cm(tmp_path)
    assert df.height >= 8, "must produce at least 8 seed rows (one per routing file)"

    send_to_llm, presuppose_none = heuristic_prescreen_cm(df)

    # Core assertion: the filter reduced the elements that would go to the LLM
    n_total_elements = df["element_id"].n_unique()
    n_llm_elements = send_to_llm["element_id"].n_unique() if send_to_llm.height > 0 else 0
    n_screened = presuppose_none["element_id"].n_unique() if presuppose_none.height > 0 else 0

    assert n_screened > 0, "filter must pre-screen at least some elements"
    assert n_llm_elements < n_total_elements, (
        f"filter must reduce LLM-bound elements: {n_llm_elements} < {n_total_elements}"
    )
    assert n_screened + n_llm_elements == n_total_elements, "partition must be complete"


def test_framework_implied_adds_zero_i57_categories(tmp_path: Path) -> None:
    """Confirms the farmOS scenario: pattern scan finds 0 transaction/autoincrement,
    framework-implied scan fills the gap for a Drupal-detected tree."""
    _make_drupal_tree(tmp_path)
    pattern_df, _ = scan_cm(tmp_path)
    fw_df, detected = scan_framework_implied(tmp_path)

    assert "drupal" in detected

    # Verify the gap was present
    pattern_tx = pattern_df.filter(pl.col("category") == "transaction").height
    pattern_ai = pattern_df.filter(pl.col("category") == "autoincrement-id").height
    assert pattern_tx == 0 and pattern_ai == 0, (
        "fixture must have zero pattern-level transaction/autoincrement (the i57 gap)"
    )

    # Verify the gap is filled by framework-implied
    fw_tx = fw_df.filter(pl.col("category") == "transaction").height
    fw_ai = fw_df.filter(pl.col("category") == "autoincrement-id").height
    assert fw_tx > 0, "framework-implied must fill the transaction gap"
    assert fw_ai > 0, "framework-implied must fill the autoincrement-id gap"
