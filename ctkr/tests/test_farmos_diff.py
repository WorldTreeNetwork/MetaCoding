"""Tests for the farmOS 1.x↔2.x differential diff engine (bead MetaCoding-k12).

Hermetic: tiny synthetic Drupal-7 tree + a synthetic farm_migrate YAML under
``tmp_path``, plus direct unit tests of the survival classifier. The real N=2
survival numbers (asset_type 100%, log_type `farm_` prefix drops, etc.) live in
``eval/ctkr/results/farmos-differential.md``, not here — these pin the mechanism.
"""

from __future__ import annotations

from pathlib import Path

from ctkr.farmos_diff import (
    MigrateMap,
    Sig,
    build_oracle,
    classify_rename,
    diff_signals,
    fields_from_migrate,
    harvest_d7,
    load_tables,
    parse_migrations,
    survival_table,
)

TABLES = load_tables()


# ─────────────────────────── D7 adapter ───────────────────────────


def _write(p: Path, text: str) -> None:
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")


def _make_d7_tree(root: Path) -> None:
    # a module manifest (.info INI)
    _write(
        root / "farm_livestock" / "farm_livestock.info",
        "name = Farm Livestock\n"
        "description = Manage animals.\n"
        "core = 7.x\n"
        "dependencies[] = farm_asset\n"
        "dependencies[] = ctools\n",
    )
    # a test module — must be excluded
    _write(root / "farm_water_test" / "farm_water_test.info", "name = Water Test\ncore = 7.x\n")
    # asset + log type feature exports
    _write(
        root / "farm_livestock" / "farm_livestock.features.inc",
        """<?php
function farm_livestock_default_farm_asset_type() {
  $items = array();
  $items['animal'] = entity_import('farm_asset_type', '{
    "type" : "animal",
    "label" : "Animal"
  }');
  return $items;
}
function farm_livestock_default_log_type() {
  $items = array();
  $items['farm_birth'] = entity_import('log_type', '{
    "type" : "farm_birth",
    "label" : "Birth"
  }');
  return $items;
}
""",
    )
    # hook_permission()
    _write(
        root / "farm_livestock" / "farm_livestock.module",
        """<?php
function farm_livestock_permission() {
  return array(
    'view farm animals' => array(
      'title' => t('View farm animals'),
      'description' => t('View all animals.'),
    ),
    'administer farm_asset types' => array(
      'title' => t('Administer asset types'),
    ),
  );
}
""",
    )


def test_harvest_d7_modules_types_permissions(tmp_path: Path) -> None:
    _make_d7_tree(tmp_path)
    sigs = harvest_d7(tmp_path)
    by_kind: dict[str, set[str]] = {}
    for s in sigs:
        by_kind.setdefault(s.kind, set()).add(s.name)

    assert by_kind["module"] == {"farm_livestock"}  # _test module excluded
    assert by_kind["asset_type"] == {"animal"}
    assert by_kind["log_type"] == {"farm_birth"}
    assert by_kind["permission"] == {"view farm animals", "administer farm_asset types"}
    # labels are carried through
    animal = next(s for s in sigs if s.kind == "asset_type")
    assert animal.label == "Animal"
    assert animal.version == "1.x"


def test_harvest_d7_deterministic(tmp_path: Path) -> None:
    _make_d7_tree(tmp_path)
    assert harvest_d7(tmp_path) == harvest_d7(tmp_path)


# ─────────────────────────── migrate parser ───────────────────────────

_MIGRATION_YML = """
id: farm_migrate_asset_animal
source:
  plugin: d7_animal_asset
  bundle: animal
destination:
  plugin: 'entity:asset'
process:
  type:
    plugin: default_value
    default_value: animal
  id:
    plugin: get
    source: id
  sex:
    plugin: get
    source: field_farm_animal_sex
  id_tag:
    plugin: sub_process
    source: animal_tags
    process:
      type:
        - plugin: static_map
          source: type
          map:
            'Ear tag': ear_tag
            Brand: brand
"""

_TAXONOMY_YML = """
id: farm_migrate_taxonomy_crop_family
source:
  plugin: d7_taxonomy_term
  bundle: farm_crop_families
destination:
  plugin: 'entity:taxonomy_term'
process:
  vid:
    plugin: default_value
    default_value: crop_family
  name:
    plugin: get
    source: name
"""


def test_parse_migrations_bundle_field_value_maps(tmp_path: Path) -> None:
    cfg = tmp_path / "config" / "install"
    _write(cfg / "migrate_plus.migration.asset_animal.yml", _MIGRATION_YML)
    _write(cfg / "migrate_plus.migration.tax_crop_family.yml", _TAXONOMY_YML)
    mm = parse_migrations(tmp_path)

    assert mm.n_migrations == 2
    # bundle correspondence via `type` (asset) and `vid` (taxonomy)
    assert mm.bundle_map["animal"] == "animal"
    assert mm.bundle_map["farm_crop_families"] == "crop_family"
    # field correspondence (dest field ← source field), plumbing keys skipped
    assert "field_farm_animal_sex" in mm.field_map["sex"]
    assert "id" not in mm.field_map  # id plumbing skipped
    # static_map value renames
    assert mm.value_map["Ear tag"] == "ear_tag"
    assert mm.value_map["Brand"] == "brand"


# ─────────────────────────── rename classifier ───────────────────────────


def test_classify_rename_convention_namespace_prefix() -> None:
    # `farm_` project-namespace prefix drop → convention (intent-N), not semantic
    assert classify_rename("farm_activity", "activity", TABLES) == "convention"
    assert classify_rename("farm_harvest", "harvest", TABLES) == "convention"


def test_classify_rename_convention_midstring_namespace() -> None:
    # namespace token mid-identifier must also fold (position-agnostic)
    assert classify_rename("administer farm_asset types", "administer asset types", TABLES) == (
        "convention"
    )


def test_classify_rename_convention_plural() -> None:
    assert classify_rename("farm_animal_types", "animal_type", TABLES) == "convention"


def test_classify_rename_semantic_root_moved() -> None:
    # the domain root itself changed → semantic (idiom, or a real concept shift)
    assert classify_rename("planting", "plant", TABLES) == "semantic"
    assert classify_rename("farm_crops", "plant_type", TABLES) == "semantic"


# ─────────────────────────── diff / survival ───────────────────────────


def test_diff_signals_all_statuses() -> None:
    v1 = [
        Sig("log_type", "farm_harvest", "", "1.x", "f"),  # → renamed convention
        Sig("log_type", "animal", "", "1.x", "f"),  # → verbatim
        Sig("log_type", "farm_sale", "", "1.x", "f"),  # → dropped
    ]
    v2 = [
        Sig("log_type", "harvest", "", "2.x", "g"),
        Sig("log_type", "animal", "", "2.x", "g"),
        Sig("log_type", "lab_test", "", "2.x", "g"),  # → new
    ]
    oracle = build_oracle(MigrateMap(bundle_map={"farm_harvest": "harvest"}))
    recs = diff_signals(v1, v2, oracle, TABLES)
    status = {r.v1_name or r.v2_name: r.status for r in recs}

    assert status["farm_harvest"] == "survived_renamed"
    assert status["animal"] == "survived_verbatim"
    assert status["farm_sale"] == "dropped"
    assert status["lab_test"] == "new"

    table = survival_table(recs)["log_type"]
    assert table["v1_population"] == 3
    assert table["survived_verbatim"] == 1
    assert table["survived_renamed"] == 1
    assert table["renamed_convention"] == 1
    assert table["dropped"] == 1
    assert table["new_in_v2"] == 1
    assert table["survival_rate"] == round(2 / 3, 3)


def test_diff_signals_token_fallback_when_oracle_silent() -> None:
    # no migrate entry, but the affix-folded token key matches → survived_renamed
    v1 = [Sig("taxonomy_vocab", "farm_season", "", "1.x", "f")]
    v2 = [Sig("taxonomy_vocab", "season", "", "2.x", "g")]
    recs = diff_signals(v1, v2, {}, TABLES)
    assert recs[0].status == "survived_renamed"
    assert recs[0].via == "token"
    assert recs[0].rename_class == "convention"


def test_diff_signals_deterministic_order() -> None:
    v1 = [Sig("asset_type", n, "", "1.x", "f") for n in ("zebra", "animal", "compost")]
    v2 = [Sig("asset_type", n, "", "2.x", "g") for n in ("compost", "animal")]
    a = diff_signals(v1, v2, {}, TABLES)
    b = diff_signals(list(reversed(v1)), list(reversed(v2)), {}, TABLES)
    assert [(r.kind, r.v1_name, r.v2_name, r.status) for r in a] == [
        (r.kind, r.v1_name, r.v2_name, r.status) for r in b
    ]


def test_fields_from_migrate_roundtrip() -> None:
    mm = MigrateMap()
    mm.field_map["sex"].add("field_farm_animal_sex")
    mm.field_map["nickname"].add("field_farm_animal_nicknames")
    f1, f2 = fields_from_migrate(mm)
    assert {s.name for s in f1} == {"field_farm_animal_sex", "field_farm_animal_nicknames"}
    assert {s.name for s in f2} == {"sex", "nickname"}
    assert all(s.kind == "field" for s in f1 + f2)
