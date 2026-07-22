"""Hermetic tests for ``ctkr glossary-gaps`` / :mod:`ctkr.lexicon`.

Small vendored fixture configs (miniature copies of the farmOS declarative
shapes) are written into ``tmp_path`` — no network, no LLM, no dependence on
any sandbox path. The four wave-1 gap SHAPES are reproduced in miniature: a
workflow state, a PHP-attribute-plugin bundle field, the ``material`` default
quantity type, and the ``land_type`` allowed-values list.

Wave 2 (MetaCoding-io6) promoted ``abandoned`` (→ LOG_STATUSES) and
``lot_number`` (→ ASSERTION_TERMS) into the glossary, so those two are no longer
gaps; the fixture keeps them (they are real source config, now correctly
EXCLUDED) and carries still-unmodelled exemplars — the ``canceled`` state and
the ``application_method`` field — to keep the two gap SHAPES under test.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctkr.lexicon import Gap, scan_sources, summary_table, write_gaps_jsonl

# ---------------------------------------------------------------------------
# Vendored miniature fixture tree (mirrors the farmOS declarative shapes)
# ---------------------------------------------------------------------------

WORKFLOWS_YML = """\
farm_log_workflow:
  id: farm_log_workflow
  group: log
  label: 'farmOS Log Workflow'
  states:
    done:
      label: Done
    pending:
      label: Pending
    abandoned:
      label: Abandoned
    canceled:
      label: Canceled
  transitions:
    to_abandoned:
      label: 'Abandon'
      from: [done, pending]
      to: abandoned
"""

LOG_TYPE_INPUT_YML = """\
langcode: en
status: true
third_party_settings:
  farm_log_quantity:
    default_quantity_type: material
id: input
label: Input
workflow: farm_log_workflow
"""

LOG_TYPE_HARVEST_YML = """\
langcode: en
status: true
id: harvest
label: Harvest
workflow: farm_log_workflow
"""

LOG_TYPE_MAINTENANCE_YML = """\
langcode: en
status: true
id: maintenance
label: Maintenance
workflow: farm_log_workflow
"""

LAND_TYPE_TMPL = """\
langcode: en
status: true
id: {id}
label: {label}
"""

ASSET_TYPE_LAND_YML = """\
langcode: en
status: true
id: land
label: Land
"""

FIELD_STORAGE_ALLOWED_YML = """\
langcode: en
status: true
id: taxonomy_term.grade
field_name: grade
entity_type: taxonomy_term
type: list_string
settings:
  allowed_values:
    prime: Prime
    marginal: Marginal
"""

HARVEST_PLUGIN_PHP = """\
<?php

namespace Drupal\\farm_harvest\\Plugin\\Log\\LogType;

#[LogType(
  id: 'harvest',
  label: new TranslatableMarkup('Harvest'),
)]
class Harvest extends FarmLogType {

  public function buildFieldDefinitions() {
    $fields = parent::buildFieldDefinitions();
    $options = [
      'type' => 'string',
      'label' => $this->t('Lot number'),
      'description' => $this->t('If this harvest is part of a batch or lot, enter the lot number here.'),
    ];
    $fields['lot_number'] = $this->farmFieldFactory->bundleFieldDefinition($options);
    $method_options = [
      'type' => 'string',
      'label' => $this->t('Application method'),
      'description' => $this->t('The method used to apply an input.'),
    ];
    $fields['application_method'] = $this->farmFieldFactory->bundleFieldDefinition($method_options);
    return $fields;
  }

}
"""


@pytest.fixture()
def fixture_tree(tmp_path: Path) -> Path:
    """A miniature module tree with all four wave-1 gap shapes vendored in."""
    root = tmp_path / "modules"
    core_log = root / "core" / "log"
    core_log.mkdir(parents=True)
    (core_log / "farm_log.workflows.yml").write_text(WORKFLOWS_YML)

    for name, text in (
        ("input", LOG_TYPE_INPUT_YML),
        ("harvest", LOG_TYPE_HARVEST_YML),
        ("maintenance", LOG_TYPE_MAINTENANCE_YML),
    ):
        d = root / "log" / name / "config" / "install"
        d.mkdir(parents=True)
        (d / f"log.type.{name}.yml").write_text(text)

    plugin_dir = root / "log" / "harvest" / "src" / "Plugin" / "Log" / "LogType"
    plugin_dir.mkdir(parents=True)
    (plugin_dir / "Harvest.php").write_text(HARVEST_PLUGIN_PHP)

    land_install = root / "asset" / "land" / "config" / "install"
    land_install.mkdir(parents=True)
    (land_install / "asset.type.land.yml").write_text(ASSET_TYPE_LAND_YML)
    for lt in ("bed", "field", "paddock"):
        (land_install / f"farm_land.land_type.{lt}.yml").write_text(
            LAND_TYPE_TMPL.format(id=lt, label=lt.title()))
    (land_install / "field.storage.taxonomy_term.grade.yml").write_text(
        FIELD_STORAGE_ALLOWED_YML)
    return root


def _by_kind(gaps: list[Gap], kind: str) -> list[Gap]:
    return [g for g in gaps if g.gap_kind == kind]


# ---------------------------------------------------------------------------
# The four wave-1 gaps, in miniature
# ---------------------------------------------------------------------------

def test_finds_workflow_state_gap(fixture_tree: Path) -> None:
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    states = _by_kind(gaps, "workflow_state")
    # ``abandoned`` was promoted into glossary.LOG_STATUSES by the wave-2
    # glossary-growth batch (MetaCoding-io6), so it is no longer a gap; the
    # still-unmodelled ``canceled`` state is what the miner now surfaces. A
    # filled gap disappearing is glossary-as-topology working as intended.
    assert [g.value for g in states] == ["canceled"]
    g = states[0]
    assert g.glossary_set == "LOG_STATUSES"
    assert g.source_ref == (
        "modules/core/log/farm_log.workflows.yml:"
        "farm_log_workflow.states.canceled")


def test_promoted_workflow_state_is_not_a_gap(fixture_tree: Path) -> None:
    """The wave-2 promotion is regression-proofed: ``abandoned`` is now
    glossary-known and must never resurface as a workflow-state gap."""
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    assert "abandoned" not in [g.value for g in _by_kind(gaps, "workflow_state")]


def test_finds_php_plugin_bundle_field(fixture_tree: Path) -> None:
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    fields = _by_kind(gaps, "bundle_field")
    # ``lot_number`` was promoted into glossary.ASSERTION_TERMS by wave 2, so the
    # still-unmodelled ``application_method`` PHP-attribute-plugin field is the
    # bundle-field gap the miner now surfaces.
    method = [g for g in fields if g.value == "application_method"]
    assert len(method) == 1
    assert method[0].glossary_set == "ASSERTION_TERMS"
    assert method[0].source_ref.endswith("Harvest.php:fields.application_method")
    # The declarative $options block is harvested into the description.
    assert "Application method" in method[0].candidate["description"]
    # And the promoted term must no longer surface as a gap.
    assert "lot_number" not in [g.value for g in fields]


def test_material_quantity_type_is_shadowed_by_the_homonym_term(
    fixture_tree: Path,
) -> None:
    """The miner checks NAME membership in all_terms(), one flat union across
    sets — so binding 'material' as an ENTITY term (MetaCoding-5ln) shadows the
    quantity_type gap of the same name. Pinned as the current design's honest
    behaviour; the per-set provenance channel that would distinguish homonyms
    is bead MetaCoding-852. The quantity_type gap SHAPE stays covered by
    test_finds_unknown_quantity_type_shape below."""
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    assert _by_kind(gaps, "quantity_type") == []


def test_finds_unknown_quantity_type_shape(tmp_path: Path) -> None:
    """A default_quantity_type OUTSIDE the glossary still surfaces as a gap —
    the shape the shadowed 'material' fixture used to pin."""
    root = tmp_path / "modules"
    mod = root / "log" / "pricing"
    (mod / "config" / "install").mkdir(parents=True)
    (mod / "config" / "install" / "log.type.pricing.yml").write_text(
        LOG_TYPE_INPUT_YML.replace("default_quantity_type: material",
                                   "default_quantity_type: pricing")
        .replace("id: input", "id: pricing")
    )
    gaps = scan_sources([root], rel_root=root.parent)
    qt = _by_kind(gaps, "quantity_type")
    assert [g.value for g in qt] == ["pricing"]
    assert qt[0].glossary_set == "MEASURES"
    assert qt[0].source_ref.endswith(
        "log.type.pricing.yml:third_party_settings."
        "farm_log_quantity.default_quantity_type")


def test_blessed_land_type_vocabulary_is_not_a_gap(fixture_tree: Path) -> None:
    # Wave 2 (MetaCoding-io6) blessed the land_type closed vocabulary as
    # glossary.LAND_TYPES (bed/field/landmark/other/paddock/property), which the
    # miner folds into all_terms(); the fixture's bed/field/paddock are all
    # members, so land_type is no longer an allowed_values gap. The still-open
    # ``grade`` list (test_field_storage_allowed_values_map) keeps the
    # allowed_values SHAPE under test.
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    lists = _by_kind(gaps, "allowed_values")
    land = [g for g in lists if g.candidate["term"] == "land_type"]
    assert land == []


def test_field_storage_allowed_values_map(fixture_tree: Path) -> None:
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    lists = _by_kind(gaps, "allowed_values")
    grade = [g for g in lists if g.candidate["term"] == "grade"]
    assert len(grade) == 1
    assert grade[0].value == ["marginal", "prime"]
    # The field name itself is also a bundle-field gap.
    assert "grade" in [g.value for g in _by_kind(gaps, "bundle_field")]


# ---------------------------------------------------------------------------
# Glossary-known vocabulary is NOT a gap
# ---------------------------------------------------------------------------

def test_known_terms_produce_no_gaps(fixture_tree: Path) -> None:
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    values = {str(g.value) for g in gaps if not isinstance(g.value, list)}
    # In LOG_STATUSES / LOG_KINDS / ENTITY_TERMS — must be absent.
    for known in ("pending", "done", "harvest", "input", "land"):
        assert known not in values
    # 'maintenance' is a real log type NOT in LOG_KINDS — must be present.
    assert "maintenance" in {g.value for g in _by_kind(gaps, "log_type")}


# ---------------------------------------------------------------------------
# Determinism + schema
# ---------------------------------------------------------------------------

def test_scan_is_deterministic(fixture_tree: Path, tmp_path: Path) -> None:
    a = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    b = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    assert [g.to_row() for g in a] == [g.to_row() for g in b]
    out1, out2 = tmp_path / "a.jsonl", tmp_path / "b.jsonl"
    write_gaps_jsonl(a, out1)
    write_gaps_jsonl(b, out2)
    assert out1.read_bytes() == out2.read_bytes()


def test_gap_rows_carry_partial_term_spec_v1(fixture_tree: Path,
                                             tmp_path: Path) -> None:
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    out = tmp_path / "gaps.jsonl"
    write_gaps_jsonl(gaps, out)
    rows = [json.loads(ln) for ln in out.read_text().splitlines()]
    assert len(rows) == len(gaps) > 0
    for row in rows:
        assert set(row) == {"gap_kind", "source_ref", "value",
                            "glossary_set", "candidate"}
        cand = row["candidate"]
        assert cand["kind"] in ("entity", "action", "assertion")
        assert cand["term"] and cand["description"] and cand["probe_semantics"]
        assert set(cand["discriminating_flow"]) == {"given", "when", "then"}
        prov = cand["provenance"]
        assert prov["config_source"] == row["source_ref"]
        assert prov["role_class_id"] is None
        # PROVISIONAL until a real sealed recording fills this — the scan
        # must never fabricate a seal.
        assert prov["first_pack_seal"] is None
        assert isinstance(prov["punts"], list) and prov["punts"]


def test_scan_writes_nothing_into_the_scanned_tree(fixture_tree: Path,
                                                   tmp_path: Path) -> None:
    before = sorted(p for p in fixture_tree.rglob("*"))
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    write_gaps_jsonl(gaps, tmp_path / "out" / "gaps.jsonl")
    after = sorted(p for p in fixture_tree.rglob("*"))
    assert before == after


def test_summary_table_mentions_counts(fixture_tree: Path) -> None:
    gaps = scan_sources([fixture_tree], rel_root=fixture_tree.parent)
    table = summary_table(gaps)
    assert f"{len(gaps)} gaps" in table
    assert "workflow_state" in table and "canceled" in table


# ---------------------------------------------------------------------------
# CLI wiring (in-process, hermetic)
# ---------------------------------------------------------------------------

def test_cli_glossary_gaps(fixture_tree: Path, tmp_path: Path,
                           capsys: pytest.CaptureFixture) -> None:
    from ctkr.cli import main

    out = tmp_path / "cli-gaps.jsonl"
    rc = main([
        "glossary-gaps",
        "--src", str(fixture_tree),
        "--rel-root", str(fixture_tree.parent),
        "--out", str(out),
        "--json",
    ])
    assert rc == 0
    assert out.exists()
    captured = capsys.readouterr()
    assert "canceled" in captured.out
    assert "application_method" in captured.out


def test_cli_refuses_out_inside_scanned_tree(fixture_tree: Path,
                                             capsys: pytest.CaptureFixture,
                                             ) -> None:
    from ctkr.cli import main

    rc = main([
        "glossary-gaps",
        "--src", str(fixture_tree),
        "--out", str(fixture_tree / "gaps.jsonl"),
    ])
    assert rc == 2
    assert "read-only" in capsys.readouterr().err
