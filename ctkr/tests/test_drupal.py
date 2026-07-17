"""Tests for the Drupal declarative-config intention lane (MetaCoding-77x).

Hermetic: a tiny synthetic Drupal module tree under ``tmp_path`` — an
``.info.yml`` manifest, a config-entity + config-schema pair, routing +
permissions + links YAML, a PHP 8 attribute plugin, and a ``hook_update_N`` with
a docblock — so the walker has real files to read. Pins the mechanism + schema;
the farmOS acceptance numbers live in the task evidence, not here.
"""

from __future__ import annotations

from pathlib import Path

import polars as pl

from ctkr.drupal import harvest_site, write_features
from ctkr.schema import (
    CONFIG_SHAPES_COLUMNS,
    FEATURES_COLUMNS,
    INTENTION_SIGNALS_COLUMNS,
    ConfigShapeRow,
    FeatureRow,
    IntentionSignalRow,
)

# ───────────────────────── synthetic Drupal site ─────────────────────────


def _site(tmp_path: Path) -> Path:
    """A two-module Drupal tree: ``farm_harvest`` (depends on ``farm_entity``)."""
    root = tmp_path / "site"
    # --- module farm_entity (a dependency) ---
    ent = root / "modules" / "core" / "entity"
    ent.mkdir(parents=True)
    (ent / "farm_entity.info.yml").write_text(
        "name: Farm entity\n"
        "description: Base entity behaviors.\n"
        "type: module\n"
        "package: farmOS Core\n"
        "core_version_requirement: ^11\n",
        encoding="utf-8",
    )

    # --- module farm_harvest ---
    mod = root / "modules" / "log" / "harvest"
    (mod / "config" / "install").mkdir(parents=True)
    (mod / "config" / "schema").mkdir(parents=True)
    (mod / "src" / "Entity").mkdir(parents=True)

    (mod / "farm_harvest.info.yml").write_text(
        "name: Harvest log\n"
        "description: Adds a Harvest log type.\n"
        "type: module\n"
        "package: farmOS Logs\n"
        "core_version_requirement: ^11\n"
        "dependencies:\n"
        "  - farm:farm_entity\n"
        "  - log:log\n",
        encoding="utf-8",
    )

    # config-entity instance: log.type.harvest → type "log.type", bundle "harvest"
    (mod / "config" / "install" / "log.type.harvest.yml").write_text(
        "langcode: en\n"
        "status: true\n"
        "id: harvest\n"
        "label: Harvest\n"
        "description: 'Records a harvest of a crop or product.'\n"
        "new_revision: true\n",
        encoding="utf-8",
    )

    # config schema: a config_entity type with a field mapping
    (mod / "config" / "schema" / "farm_harvest.schema.yml").write_text(
        "log.type.harvest:\n"
        "  type: config_entity\n"
        "  label: 'Harvest log type'\n"
        "  mapping:\n"
        "    id:\n"
        "      type: string\n"
        "      label: 'ID'\n"
        "    quantity_measures:\n"
        "      type: sequence\n"
        "      label: 'Quantity measures'\n",
        encoding="utf-8",
    )

    (mod / "farm_harvest.routing.yml").write_text(
        "farm_harvest.settings:\n"
        "  path: '/admin/config/farm/harvest'\n"
        "  defaults:\n"
        "    _title: 'Harvest settings'\n"
        "  requirements:\n"
        "    _permission: 'administer harvest'\n",
        encoding="utf-8",
    )

    (mod / "farm_harvest.permissions.yml").write_text(
        "administer harvest:\n"
        "  title: 'Administer harvest'\n"
        "  description: 'Manage harvest log settings.'\n",
        encoding="utf-8",
    )

    (mod / "farm_harvest.links.menu.yml").write_text(
        "farm_harvest.settings:\n"
        "  title: 'Harvest'\n"
        "  route_name: farm_harvest.settings\n",
        encoding="utf-8",
    )

    # PHP 8 attribute plugin (Drupal 11 style)
    (mod / "src" / "Entity" / "Harvest.php").write_text(
        "<?php\n\n"
        "namespace Drupal\\farm_harvest\\Entity;\n\n"
        "use Drupal\\log\\Entity\\Log;\n\n"
        "#[LogType(\n"
        "  id: 'harvest',\n"
        "  label: new TranslatableMarkup('Harvest'),\n"
        ")]\n"
        "class Harvest extends Log {}\n",
        encoding="utf-8",
    )

    # hook_update_N in a .install file, with a docblock
    (mod / "farm_harvest.install").write_text(
        "<?php\n\n"
        "/**\n"
        " * Grant the harvest permission to the manager role.\n"
        " */\n"
        "function farm_harvest_update_11401(&$sandbox) {\n"
        "  // ...\n"
        "}\n",
        encoding="utf-8",
    )
    return root


# ───────────────────────── schema + shape ─────────────────────────


def test_harvest_shapes_and_schema(tmp_path: Path) -> None:
    root = _site(tmp_path)
    signals, shapes, features, stats = harvest_site(root)
    assert list(signals.columns) == list(INTENTION_SIGNALS_COLUMNS)
    assert list(shapes.columns) == list(CONFIG_SHAPES_COLUMNS)
    assert list(features.columns) == list(FEATURES_COLUMNS)
    for d in signals.to_dicts():
        IntentionSignalRow.model_validate(d)
    for d in shapes.to_dicts():
        ConfigShapeRow.model_validate(d)
    for d in features.to_dicts():
        FeatureRow.model_validate(d)
    assert stats.n_modules == 2


# ───────────────────────── signals ─────────────────────────


def test_module_and_config_signals(tmp_path: Path) -> None:
    root = _site(tmp_path)
    signals, _, _, _ = harvest_site(root)

    mod = signals.filter(pl.col("element_id") == "module:farm_harvest")
    kinds = set(mod["indicator_kind"].to_list())
    # S4 description, A3 label, B1 package, B3 dependencies
    assert {"S4", "A3", "B1", "B3"} <= kinds
    contents = mod["content"].to_list()
    assert any("Adds a Harvest log type" in c for c in contents)  # S4 purpose
    # dependency machine names are colon-stripped (farm:farm_entity → farm_entity)
    deps = mod.filter(pl.col("indicator_kind") == "B3")["content"].to_list()
    assert "farm_entity" in deps and "log" in deps

    cfg = signals.filter(pl.col("element_id") == "config:log.type.harvest")
    cfg_contents = cfg["content"].to_list()
    assert any(c == "Harvest" for c in cfg_contents)  # A4 label
    assert any("Records a harvest" in c for c in cfg_contents)  # S4 description
    assert any(c == "log.type" for c in cfg_contents)  # A3 config type


def test_route_permission_plugin_and_hook_signals(tmp_path: Path) -> None:
    root = _site(tmp_path)
    signals, _, _, stats = harvest_site(root)

    # route path is an A2 contract-with-the-outside-world string
    route = signals.filter(pl.col("element_kind") == "route")
    assert "/admin/config/farm/harvest" in route["content"].to_list()
    path_rows = route.filter(pl.col("content").str.starts_with("/"))
    assert set(path_rows["indicator_kind"].to_list()) == {"A2"}

    perm = signals.filter(pl.col("element_kind") == "permission")
    assert "administer harvest" in perm["content"].to_list()

    # PHP 8 attribute plugin: #[LogType] name (A1) + id (A3) + label (A4)
    plugin = signals.filter(pl.col("element_kind") == "php-plugin")
    pcontents = plugin["content"].to_list()
    assert "#[LogType]" in pcontents
    assert "harvest" in pcontents  # id arg
    assert stats.n_php_plugins >= 1

    # hook_update_N docblock is an A6 rationale signal
    hook = signals.filter(pl.col("element_kind") == "update-hook")
    assert hook.height == 1
    assert hook["indicator_kind"][0] == "A6"
    assert "manager role" in hook["content"][0]
    assert "farm_harvest_update_11401" in hook["content"][0]


def test_portability_tiers_assigned(tmp_path: Path) -> None:
    root = _site(tmp_path)
    signals, _, _, _ = harvest_site(root)
    assert set(signals["portability_tier"].to_list()) <= {"I", "N", "A"}
    # config label (domain vocab) is intent-I; config type (Drupal idiom) is intent-N
    cfg = signals.filter(pl.col("element_id") == "config:log.type.harvest")
    label = cfg.filter(pl.col("content") == "Harvest")
    assert label["portability_tier"][0] == "I"
    ctype = cfg.filter(pl.col("content") == "log.type")
    assert ctype["portability_tier"][0] == "N"


# ───────────────────────── config shapes ─────────────────────────


def test_config_shapes_from_schema(tmp_path: Path) -> None:
    root = _site(tmp_path)
    _, shapes, _, _ = harvest_site(root)
    ht = shapes.filter(pl.col("config_type") == "log.type.harvest")
    # one type-summary row (field_name null) + one row per mapping field
    summary = ht.filter(pl.col("field_name").is_null())
    assert summary.height == 1
    assert summary["entity_kind"][0] == "config_entity"
    fields = ht.filter(pl.col("field_name").is_not_null())
    fnames = set(fields["field_name"].to_list())
    assert {"id", "quantity_measures"} <= fnames
    idrow = fields.filter(pl.col("field_name") == "id")
    assert idrow["field_type"][0] == "string"
    assert idrow["module"][0] == "farm_harvest"


# ───────────────────────── feature inventory ─────────────────────────


def test_feature_inventory(tmp_path: Path) -> None:
    root = _site(tmp_path)
    _, _, features, _ = harvest_site(root)
    names = set(features["name"].to_list())
    assert names == {"farm_entity", "farm_harvest"}

    fh = features.filter(pl.col("name") == "farm_harvest").to_dicts()[0]
    assert fh["source_basis"] == "declarative"
    assert fh["label"] == "Harvest log"
    assert fh["routes_count"] == 1
    assert fh["permissions_count"] == 1
    assert "log.type" in fh["config_entity_types"]
    assert any(g.endswith("harvest/**") for g in fh["member_globs"])

    # dependency edge: farm_harvest depends_on farm_entity's feature_id (in-corpus);
    # "log" is NOT in the corpus so it is dropped from depends_on.
    fe = features.filter(pl.col("name") == "farm_entity").to_dicts()[0]
    assert fe["feature_id"] in fh["depends_on"]
    assert len(fh["depends_on"]) == 1  # log:log not in corpus


# ───────────────────────── determinism ─────────────────────────


def test_harvest_deterministic_byte_identical(tmp_path: Path) -> None:
    root = _site(tmp_path)
    out = tmp_path / "out"
    for tag in ("run1", "run2"):
        _, _, features, _ = harvest_site(root)
        write_features(features, out / f"feat_{tag}.parquet")
    assert (out / "feat_run1.parquet").read_bytes() == (out / "feat_run2.parquet").read_bytes()
