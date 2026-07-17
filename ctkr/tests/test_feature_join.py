"""Tests for the feature ↔ subsystem join (MetaCoding-7fs).

Hermetic: synthetic fixtures under ``tmp_path`` — no real graph, no farmOS.
The fixtures exercise the full join path including glob matching, disagreement
signal, and the FileNotFoundError guard when structural data is absent.
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from ctkr.feature_join import (
    DISAGREE_COLUMNS,
    FEATURE_DISAGREE_FILE,
    JoinStats,
    _matches_glob,
    join_features_to_subsystems,
)


# ───────────────────────── fixture helpers ─────────────────────────────────


def _write_nodes_jsonl(path: Path, nodes: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for n in nodes:
            fh.write(json.dumps(n) + "\n")


def _write_members_parquet(path: Path, members: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(
        members,
        schema={
            "subsystem_id": pl.Utf8,
            "symbol_id": pl.Utf8,
            "repo": pl.Utf8,
            "qualified_name": pl.Utf8,
            "boundary_confidence": pl.Float64,
            "placement": pl.Utf8,
            "schema_version": pl.Int64,
        },
    )
    df.write_parquet(path)


def _write_features_parquet(path: Path, features: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    df = pl.DataFrame(
        features,
        schema={
            "feature_id": pl.Utf8,
            "repo": pl.Utf8,
            "name": pl.Utf8,
            "label": pl.Utf8,
            "description": pl.Utf8,
            "source_basis": pl.Utf8,
            "declarative_ref": pl.Utf8,
            "package": pl.Utf8,
            "core_requirement": pl.Utf8,
            "depends_on": pl.List(pl.Utf8),
            "config_entity_types": pl.List(pl.Utf8),
            "routes_count": pl.Int64,
            "permissions_count": pl.Int64,
            "member_globs": pl.List(pl.Utf8),
            "schema_version": pl.Int64,
        },
    )
    df.write_parquet(path)


def _make_data_dir(tmp_path: Path) -> Path:
    """Construct a minimal data_dir with structural + feature fixtures.

    Layout:
        <data_dir>/ctkr/features.parquet
        <data_dir>/ctkr/subsystem_members.parquet
        <data_dir>/ctkr/export/nodes.jsonl

    Two modules:
        ``farm_asset`` → modules/core/asset/**  (maps to ss:A and ss:B → cross-cutting)
        ``farm_log``   → modules/log/**          (maps to ss:C only → clean slice)
        ``farm_ui``    → modules/core/ui/**      (no symbols → empty subsystem_ids)

    Symbols:
        sym-1: modules/core/asset/src/AssetInterface.php  → ss:A
        sym-2: modules/core/asset/src/AssetStorage.php    → ss:A
        sym-3: modules/core/asset/src/Plugin/AssetPlugin.php → ss:B  (cross-cut)
        sym-4: modules/log/src/Entity/Log.php             → ss:C
        sym-5: modules/log/src/Plugin/LogPlugin.php        → ss:C
        sym-6: modules/other/foo.php                       → ss:A  (not in any module)
    """
    data_dir = tmp_path / "data"
    ctkr = data_dir / "ctkr"

    nodes = [
        {"id": "sym-1", "file": "modules/core/asset/src/AssetInterface.php", "kind": "class", "repo": "test"},
        {"id": "sym-2", "file": "modules/core/asset/src/AssetStorage.php", "kind": "class", "repo": "test"},
        {"id": "sym-3", "file": "modules/core/asset/src/Plugin/AssetPlugin.php", "kind": "class", "repo": "test"},
        {"id": "sym-4", "file": "modules/log/src/Entity/Log.php", "kind": "class", "repo": "test"},
        {"id": "sym-5", "file": "modules/log/src/Plugin/LogPlugin.php", "kind": "class", "repo": "test"},
        {"id": "sym-6", "file": "modules/other/foo.php", "kind": "function", "repo": "test"},
        # node with no file (should be ignored)
        {"id": "sym-7", "file": "", "kind": "file", "repo": "test"},
    ]
    _write_nodes_jsonl(ctkr / "export" / "nodes.jsonl", nodes)

    members = [
        {"subsystem_id": "ss:A", "symbol_id": "sym-1", "repo": "test", "qualified_name": "AssetInterface", "boundary_confidence": 1.0, "placement": "structural", "schema_version": 1},
        {"subsystem_id": "ss:A", "symbol_id": "sym-2", "repo": "test", "qualified_name": "AssetStorage", "boundary_confidence": 1.0, "placement": "structural", "schema_version": 1},
        {"subsystem_id": "ss:B", "symbol_id": "sym-3", "repo": "test", "qualified_name": "AssetPlugin", "boundary_confidence": 0.7, "placement": "structural", "schema_version": 1},
        {"subsystem_id": "ss:C", "symbol_id": "sym-4", "repo": "test", "qualified_name": "Log", "boundary_confidence": 1.0, "placement": "structural", "schema_version": 1},
        {"subsystem_id": "ss:C", "symbol_id": "sym-5", "repo": "test", "qualified_name": "LogPlugin", "boundary_confidence": 1.0, "placement": "structural", "schema_version": 1},
        {"subsystem_id": "ss:A", "symbol_id": "sym-6", "repo": "test", "qualified_name": "foo", "boundary_confidence": 0.5, "placement": "locality", "schema_version": 1},
    ]
    _write_members_parquet(ctkr / "subsystem_members.parquet", members)

    features = [
        {
            "feature_id": "fid-asset",
            "repo": "test",
            "name": "farm_asset",
            "label": "Asset",
            "description": "Manages farm assets.",
            "source_basis": "declarative",
            "declarative_ref": "modules/core/asset/farm_asset.info.yml",
            "package": "farmOS Core",
            "core_requirement": "^11",
            "depends_on": [],
            "config_entity_types": ["asset.type"],
            "routes_count": 2,
            "permissions_count": 3,
            "member_globs": ["modules/core/asset/**"],
            "schema_version": 1,
        },
        {
            "feature_id": "fid-log",
            "repo": "test",
            "name": "farm_log",
            "label": "Log",
            "description": "Manages farm logs.",
            "source_basis": "declarative",
            "declarative_ref": "modules/log/farm_log.info.yml",
            "package": "farmOS Logs",
            "core_requirement": "^11",
            "depends_on": ["fid-asset"],
            "config_entity_types": ["log.type"],
            "routes_count": 1,
            "permissions_count": 2,
            "member_globs": ["modules/log/**"],
            "schema_version": 1,
        },
        {
            "feature_id": "fid-ui",
            "repo": "test",
            "name": "farm_ui",
            "label": "UI",
            "description": "UI helpers.",
            "source_basis": "declarative",
            "declarative_ref": "modules/core/ui/farm_ui.info.yml",
            "package": "farmOS Core",
            "core_requirement": "^11",
            "depends_on": [],
            "config_entity_types": [],
            "routes_count": 0,
            "permissions_count": 0,
            "member_globs": ["modules/core/ui/**"],
            "schema_version": 1,
        },
    ]
    _write_features_parquet(ctkr / "features.parquet", features)

    return data_dir


# ───────────────────────── _matches_glob ───────────────────────────────────


def test_matches_glob_subtree():
    assert _matches_glob("modules/core/asset/src/Foo.php", "modules/core/asset/**")
    assert _matches_glob("modules/core/asset", "modules/core/asset/**")


def test_matches_glob_no_partial_prefix():
    # "modules/core/asset/**" must NOT match "modules/core/asset_test/Foo.php"
    assert not _matches_glob("modules/core/asset_test/Foo.php", "modules/core/asset/**")


def test_matches_glob_wildcard_all():
    assert _matches_glob("anything/goes.php", "**")


def test_matches_glob_exact():
    assert _matches_glob("farm.install", "farm.install")
    assert not _matches_glob("farm.install.bak", "farm.install")


# ───────────────────────── join_features_to_subsystems ─────────────────────


def test_join_basic(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    stats = join_features_to_subsystems(data_dir)

    assert stats.n_features == 3
    assert stats.n_features_with_subsystems == 2  # farm_asset + farm_log; farm_ui has none
    assert stats.n_features_cross_cutting == 1    # farm_asset spans ss:A + ss:B

    # avg = (2 + 1 + 0) / 3 �� 1.0
    assert abs(stats.avg_subsystems_per_feature - 1.0) < 0.01


def test_join_subsystem_ids_content(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    join_features_to_subsystems(data_dir)

    feat = pl.read_parquet(data_dir / "ctkr" / "features.parquet")
    by_name = {row["name"]: row["subsystem_ids"] for row in feat.iter_rows(named=True)}

    assert sorted(by_name["farm_asset"]) == ["ss:A", "ss:B"]
    assert by_name["farm_log"] == ["ss:C"]
    assert by_name["farm_ui"] == []


def test_join_interface_refs_placeholder(tmp_path):
    """interface_refs column must exist (empty placeholder) after join."""
    data_dir = _make_data_dir(tmp_path)
    join_features_to_subsystems(data_dir)

    feat = pl.read_parquet(data_dir / "ctkr" / "features.parquet")
    assert "interface_refs" in feat.columns
    for val in feat["interface_refs"].to_list():
        assert val is None or val == []


def test_join_disagree_output(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    join_features_to_subsystems(data_dir)

    dp = data_dir / "ctkr" / FEATURE_DISAGREE_FILE
    assert dp.exists()

    df = pl.read_parquet(dp)
    assert list(df.columns) == list(DISAGREE_COLUMNS)

    # top row should be farm_asset (most cross-cutting)
    top = df.row(0, named=True)
    assert top["name"] == "farm_asset"
    assert top["n_subsystems"] == 2
    assert top["is_cross_cutting"] is True

    # farm_log: 1 subsystem, not cross-cutting
    log_row = df.filter(pl.col("name") == "farm_log").row(0, named=True)
    assert log_row["n_subsystems"] == 1
    assert log_row["is_cross_cutting"] is False

    # farm_ui: 0 subsystems
    ui_row = df.filter(pl.col("name") == "farm_ui").row(0, named=True)
    assert ui_row["n_subsystems"] == 0
    assert ui_row["is_cross_cutting"] is False


def test_join_missing_structural_data(tmp_path):
    """FileNotFoundError when structural data is missing."""
    data_dir = tmp_path / "empty"
    (data_dir / "ctkr").mkdir(parents=True)
    (data_dir / "ctkr" / "features.parquet").write_bytes(b"")  # placeholder

    with pytest.raises(FileNotFoundError, match="subsystem_members.parquet"):
        join_features_to_subsystems(data_dir)


def test_join_missing_features(tmp_path):
    """FileNotFoundError when features.parquet is missing."""
    data_dir = tmp_path / "no_features"
    (data_dir / "ctkr").mkdir(parents=True)

    with pytest.raises(FileNotFoundError, match="features.parquet"):
        join_features_to_subsystems(data_dir)


def test_join_idempotent(tmp_path):
    """Running the join twice gives byte-identical results."""
    data_dir = _make_data_dir(tmp_path)
    join_features_to_subsystems(data_dir)
    first = (data_dir / "ctkr" / "features.parquet").read_bytes()
    first_d = (data_dir / "ctkr" / FEATURE_DISAGREE_FILE).read_bytes()

    join_features_to_subsystems(data_dir)
    assert (data_dir / "ctkr" / "features.parquet").read_bytes() == first
    assert (data_dir / "ctkr" / FEATURE_DISAGREE_FILE).read_bytes() == first_d


def test_join_stats_returns_joinstat_type(tmp_path):
    data_dir = _make_data_dir(tmp_path)
    stats = join_features_to_subsystems(data_dir)
    assert isinstance(stats, JoinStats)
    assert stats.nodes_loaded == 7  # 7 nodes in fixture (including no-file node)
    assert stats.members_loaded == 6
