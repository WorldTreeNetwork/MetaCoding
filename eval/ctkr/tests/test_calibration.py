"""Tests for the calibration pipeline.

Hermetic: all tests use tmp_path + synthetic data only.
Covers schema, ingest logic, miss_type derivation, and report functions.

Run: uv run pytest tests/  (from eval/ctkr/)
"""

from __future__ import annotations

import json
from pathlib import Path

import polars as pl
import pytest

from calibration_schema import (
    CALIBRATION_COLUMNS,
    CALIBRATION_SCHEMA_VERSION,
    append_calibration,
    make_calibration_row,
    read_calibration,
    write_calibration,
)
from calibration_ingest import _derive_miss_type, ingest
from calibration_report import dial_sweep, idiom_over_fire_rate, precision_recall


# ───────────────────────── synthetic fixtures ─────────────────────────

# A fixed recorded_at so row_ids are deterministic in tests.
_TS = "2026-07-17T00:00:00+00:00"


def _load_df() -> pl.DataFrame:
    """Three synthetic intention_load rows covering all three load classes."""
    return pl.DataFrame([
        {
            "element_id": "elem_sc",
            "element_kind": "interface-export",
            "structural_determinacy": 0.85,
            "intention_richness": 0.40,
            "load_class": "structure-clear",
            "port_critical_conflict": False,
            "drivers": ["high profile mass", "boundary export"],
            "schema_version": 1,
        },
        {
            "element_id": "elem_ic",
            "element_kind": "interface-export",
            "structural_determinacy": 0.30,
            "intention_richness": 0.75,
            "load_class": "intention-critical",
            "port_critical_conflict": False,
            "drivers": ["low discriminativeness", "6 tests pin behavior"],
            "schema_version": 1,
        },
        {
            "element_id": "elem_amb",
            "element_kind": "interface-export",
            "structural_determinacy": 0.20,
            "intention_richness": 0.15,
            "load_class": "ambiguous",
            "port_critical_conflict": False,
            "drivers": ["zero profile", "no test linkage"],
            "schema_version": 1,
        },
    ])


def _obs_jsonl(*obs: dict) -> str:
    return "\n".join(json.dumps(o) for o in obs)


def _write_load(tmp_path: Path) -> Path:
    p = tmp_path / "intention_load.parquet"
    _load_df().write_parquet(p)
    return p


def _ingest_obs(tmp_path: Path, obs: list[dict], run_id: str = "run-001") -> Path:
    """Write obs JSONL + ingest against synthetic load → return calibration path."""
    load_path = _write_load(tmp_path)
    obs_path = tmp_path / f"obs_{run_id}.jsonl"
    obs_path.write_text(_obs_jsonl(*obs), encoding="utf-8")
    out = tmp_path / "calibration.parquet"
    ingest(run_id, obs_path, load_path, out, recorded_at=_TS)
    return out


# ───────────────────────── schema tests ─────────────────────────


def test_make_calibration_row_has_all_columns() -> None:
    row = make_calibration_row(
        port_run_id="run-001",
        element_id="elem_sc",
        predicted_load_class="structure-clear",
        structural_determinacy=0.85,
        intention_richness=0.40,
        drivers=["high mass"],
        builder_consulted_evidence=False,
        miss_type="none",
        source="port-run",
        recorded_at=_TS,
    )
    for col in CALIBRATION_COLUMNS:
        assert col in row, f"missing column {col!r}"
    assert row["schema_version"] == CALIBRATION_SCHEMA_VERSION
    assert row["port_run_id"] == "run-001"
    assert row["drivers"] == ["high mass"]


def test_row_id_is_deterministic() -> None:
    kw: dict = dict(
        port_run_id="run-001",
        element_id="elem_sc",
        predicted_load_class="structure-clear",
        structural_determinacy=0.85,
        intention_richness=0.40,
        drivers=[],
        builder_consulted_evidence=None,
        miss_type=None,
        source="port-run",
        recorded_at=_TS,
    )
    assert make_calibration_row(**kw)["calibration_row_id"] == make_calibration_row(**kw)["calibration_row_id"]


def test_row_id_differs_by_element() -> None:
    def _row(eid: str) -> str:
        return make_calibration_row(
            port_run_id="run-001", element_id=eid,
            predicted_load_class="structure-clear",
            structural_determinacy=0.85, intention_richness=0.4,
            drivers=[], builder_consulted_evidence=None,
            miss_type=None, source="port-run", recorded_at=_TS,
        )["calibration_row_id"]
    assert _row("elem_a") != _row("elem_b")


def test_read_nonexistent_returns_empty(tmp_path: Path) -> None:
    df = read_calibration(tmp_path / "nonexistent.parquet")
    assert df.height == 0
    assert list(df.columns) == list(CALIBRATION_COLUMNS)


def test_write_read_roundtrip(tmp_path: Path) -> None:
    p = tmp_path / "cal.parquet"
    row = make_calibration_row(
        port_run_id="run-001", element_id="elem_sc",
        predicted_load_class="structure-clear",
        structural_determinacy=0.85, intention_richness=0.40,
        drivers=["high mass"],
        builder_consulted_evidence=False,
        miss_type="none", source="port-run", recorded_at=_TS,
    )
    write_calibration(pl.DataFrame([row]), p)
    df = read_calibration(p)
    assert df.height == 1
    assert df["element_id"][0] == "elem_sc"
    assert list(df["drivers"][0]) == ["high mass"]


def test_append_deduplicates_same_row(tmp_path: Path) -> None:
    p = tmp_path / "cal.parquet"
    row = make_calibration_row(
        port_run_id="run-001", element_id="elem_sc",
        predicted_load_class="structure-clear",
        structural_determinacy=0.85, intention_richness=0.40,
        drivers=[], builder_consulted_evidence=False,
        miss_type="none", source="port-run", recorded_at=_TS,
    )
    append_calibration([row], p)
    combined = append_calibration([row], p)  # same row again
    assert combined.height == 1  # deduplicated by calibration_row_id


def test_append_keeps_distinct_runs(tmp_path: Path) -> None:
    p = tmp_path / "cal.parquet"
    for run_id in ("run-001", "run-002"):
        row = make_calibration_row(
            port_run_id=run_id, element_id="elem_sc",
            predicted_load_class="structure-clear",
            structural_determinacy=0.85, intention_richness=0.40,
            drivers=[], builder_consulted_evidence=False,
            miss_type="none", source="port-run", recorded_at=_TS,
        )
        append_calibration([row], p)
    # Two different run_ids produce different calibration_row_ids → both kept.
    assert read_calibration(p).height == 2


# ───────────────────────── miss_type derivation ─────────────────────────


def test_derive_miss_type_correct_predictions() -> None:
    assert _derive_miss_type("structure-clear", False) == "none"
    assert _derive_miss_type("intention-critical", True) == "none"
    assert _derive_miss_type("ambiguous", True) == "none"


def test_derive_miss_type_mismatches() -> None:
    assert _derive_miss_type("structure-clear", True) == "needed-evidence-not-given"
    assert _derive_miss_type("intention-critical", False) == "evidence-given-not-needed"
    assert _derive_miss_type("ambiguous", False) == "evidence-given-not-needed"


def test_derive_miss_type_unknown() -> None:
    # consulted=None means observer did not record — result is null
    assert _derive_miss_type("structure-clear", None) is None
    assert _derive_miss_type("intention-critical", None) is None


# ───────────────────────── ingest tests ─────────────────────────


def test_ingest_basic(tmp_path: Path) -> None:
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": False},
        {"element_id": "elem_ic", "builder_consulted_evidence": True},
    ])
    cal = read_calibration(out)
    assert cal.height == 2
    assert cal.filter(pl.col("element_id") == "elem_sc")["miss_type"][0] == "none"
    assert cal.filter(pl.col("element_id") == "elem_ic")["miss_type"][0] == "none"


def test_ingest_flags_needed_evidence_not_given(tmp_path: Path) -> None:
    # structure-clear predicted, builder consulted evidence → mismatch
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": True},
    ])
    cal = read_calibration(out)
    assert cal["miss_type"][0] == "needed-evidence-not-given"


def test_ingest_flags_evidence_given_not_needed(tmp_path: Path) -> None:
    # intention-critical predicted, builder did not consult evidence → mismatch
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_ic", "builder_consulted_evidence": False},
    ])
    cal = read_calibration(out)
    assert cal["miss_type"][0] == "evidence-given-not-needed"


def test_ingest_explicit_miss_type_wins(tmp_path: Path) -> None:
    """Observer-provided miss_type takes precedence over derivation."""
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": False, "miss_type": "builder-error"},
    ])
    cal = read_calibration(out)
    assert cal["miss_type"][0] == "builder-error"


def test_ingest_skips_unknown_element(tmp_path: Path, capsys: pytest.CaptureFixture) -> None:
    out = _ingest_obs(tmp_path, [
        {"element_id": "no_such_element", "builder_consulted_evidence": True},
    ])
    cal = read_calibration(out)
    assert cal.height == 0


def test_ingest_skips_missing_element_id(tmp_path: Path) -> None:
    out = _ingest_obs(tmp_path, [
        {"builder_consulted_evidence": True},  # no element_id
    ])
    assert read_calibration(out).height == 0


def test_ingest_appends_across_runs(tmp_path: Path) -> None:
    load_path = _write_load(tmp_path)
    out = tmp_path / "calibration.parquet"
    for run_id, elem_id in [("run-001", "elem_sc"), ("run-002", "elem_ic")]:
        obs_path = tmp_path / f"obs_{run_id}.jsonl"
        obs_path.write_text(_obs_jsonl({"element_id": elem_id, "builder_consulted_evidence": False}), encoding="utf-8")
        ingest(run_id, obs_path, load_path, out, recorded_at=_TS)
    cal = read_calibration(out)
    assert cal.height == 2
    assert set(cal["port_run_id"].to_list()) == {"run-001", "run-002"}


def test_ingest_human_review_source(tmp_path: Path) -> None:
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": False, "source": "human-review"},
    ])
    cal = read_calibration(out)
    assert cal["source"][0] == "human-review"


def test_ingest_null_consulted_produces_null_miss_type(tmp_path: Path) -> None:
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc"},  # no builder_consulted_evidence
    ])
    cal = read_calibration(out)
    assert cal.height == 1
    assert cal["builder_consulted_evidence"][0] is None
    assert cal["miss_type"][0] is None


# ───────────────────────── report tests ─────────────────────────


def test_precision_recall_empty() -> None:
    """precision_recall returns correct empty schema when no data."""
    pr = precision_recall(pl.DataFrame(
        schema={
            "predicted_load_class": pl.Utf8,
            "miss_type": pl.Utf8,
            "builder_consulted_evidence": pl.Boolean,
        }
    ))
    assert pr.height == 0
    assert "predicted_load_class" in pr.columns
    assert "precision" in pr.columns


def test_precision_recall_correct_classification(tmp_path: Path) -> None:
    """All correct → precision 1.0 for each class."""
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": False},
        {"element_id": "elem_ic", "builder_consulted_evidence": True},
    ])
    cal = read_calibration(out)
    pr = precision_recall(cal)

    sc = pr.filter(pl.col("predicted_load_class") == "structure-clear")
    assert sc.height == 1
    assert sc["precision"][0] == 1.0

    ic = pr.filter(pl.col("predicted_load_class") == "intention-critical")
    assert ic.height == 1
    assert ic["precision"][0] == 1.0


def test_precision_recall_mismatch_lowers_precision(tmp_path: Path) -> None:
    """One correct, one miss → precision 0.5 for that class."""
    load_path = _write_load(tmp_path)
    out = tmp_path / "calibration.parquet"

    for run_id, consulted, ts in [
        ("run-001", False, "2026-07-17T00:00:00+00:00"),   # correct
        ("run-002", True, "2026-07-17T00:00:01+00:00"),    # miss (needed evidence)
    ]:
        obs_path = tmp_path / f"obs_{run_id}.jsonl"
        obs_path.write_text(
            _obs_jsonl({"element_id": "elem_sc", "builder_consulted_evidence": consulted}),
            encoding="utf-8",
        )
        ingest(run_id, obs_path, load_path, out, recorded_at=ts)

    pr = precision_recall(read_calibration(out))
    sc = pr.filter(pl.col("predicted_load_class") == "structure-clear")
    assert sc["n_predictions"][0] == 2
    assert sc["n_correct"][0] == 1
    assert sc["precision"][0] == pytest.approx(0.5)


def test_dial_sweep_grid_size(tmp_path: Path) -> None:
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": False},
    ])
    cal = read_calibration(out)
    load_df = _load_df()
    d_hi_range = [0.4, 0.6, 0.8]
    r_min_range = [0.3, 0.5]
    sweep = dial_sweep(load_df, cal, d_hi_range=d_hi_range, r_min_range=r_min_range)
    assert sweep.height == len(d_hi_range) * len(r_min_range)
    assert "d_hi" in sweep.columns
    assert "r_min" in sweep.columns
    assert "n_structure_clear" in sweep.columns


def test_dial_sweep_counts_sum_to_total(tmp_path: Path) -> None:
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": False},
    ])
    cal = read_calibration(out)
    load_df = _load_df()
    sweep = dial_sweep(load_df, cal, d_hi_range=[0.5, 0.8], r_min_range=[0.4])
    total = load_df.height
    for row in sweep.iter_rows(named=True):
        assert row["n_structure_clear"] + row["n_intention_critical"] + row["n_ambiguous"] == total


def test_dial_sweep_higher_d_hi_reduces_structure_clear() -> None:
    """Raising d_hi should classify fewer elements as structure-clear."""
    load_df = _load_df()
    empty_cal = pl.DataFrame(schema={
        "element_id": pl.Utf8, "miss_type": pl.Utf8, "recorded_at": pl.Utf8,
    })
    sweep = dial_sweep(load_df, empty_cal, d_hi_range=[0.3, 0.9], r_min_range=[0.5])
    low = sweep.filter(pl.col("d_hi") == 0.3)["n_structure_clear"][0]
    high = sweep.filter(pl.col("d_hi") == 0.9)["n_structure_clear"][0]
    # d_hi=0.3 lets more elements through → n_sc >= n_sc at d_hi=0.9
    assert low >= high


def test_dial_sweep_lower_r_min_reduces_ambiguous() -> None:
    """Lowering r_min should classify fewer elements as ambiguous (more intention-critical)."""
    load_df = _load_df()
    empty_cal = pl.DataFrame(schema={
        "element_id": pl.Utf8, "miss_type": pl.Utf8, "recorded_at": pl.Utf8,
    })
    sweep = dial_sweep(load_df, empty_cal, d_hi_range=[0.9], r_min_range=[0.1, 0.9])
    amb_low_r = sweep.filter(pl.col("r_min") == 0.1)["n_ambiguous"][0]
    amb_high_r = sweep.filter(pl.col("r_min") == 0.9)["n_ambiguous"][0]
    assert amb_low_r <= amb_high_r


# ───────────────────────── idiom-over-fire metric (dial-rec #1) ─────────────────────────


def test_idiom_over_fire_empty() -> None:
    """No calibration data → zero flags, rate None (never crashes)."""
    cal = read_calibration("/nonexistent/calibration.parquet")
    iof = idiom_over_fire_rate(cal)
    assert iof["n_flagged"] == 0
    assert iof["n_over_fire"] == 0
    assert iof["idiom_over_fire_rate"] is None


def test_idiom_over_fire_all_flags_land_on_non_value(tmp_path: Path) -> None:
    """intention-critical + ambiguous flags where the builder never consulted →
    100% over-fire (the observed first-port signal: source-idiom flags)."""
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_ic", "builder_consulted_evidence": False},   # over-fire
        {"element_id": "elem_amb", "builder_consulted_evidence": False},  # over-fire
        {"element_id": "elem_sc", "builder_consulted_evidence": False},   # structure-clear, ignored
    ])
    iof = idiom_over_fire_rate(read_calibration(out))
    assert iof["n_flagged"] == 2
    assert iof["n_over_fire"] == 2
    assert iof["idiom_over_fire_rate"] == 1.0
    assert iof["by_class"]["intention-critical"]["n_over_fire"] == 1
    assert iof["by_class"]["ambiguous"]["n_over_fire"] == 1


def test_idiom_over_fire_consulted_flag_is_not_over_fire(tmp_path: Path) -> None:
    """A flagged class the builder DID consult is a correct fire, not over-fire."""
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_ic", "builder_consulted_evidence": True},  # correct fire
    ])
    iof = idiom_over_fire_rate(read_calibration(out))
    assert iof["n_flagged"] == 1
    assert iof["n_over_fire"] == 0
    assert iof["idiom_over_fire_rate"] == 0.0


def test_idiom_over_fire_structure_clear_excluded(tmp_path: Path) -> None:
    """structure-clear predictions are never counted — only flagged classes over-fire."""
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_sc", "builder_consulted_evidence": False},
    ])
    iof = idiom_over_fire_rate(read_calibration(out))
    assert iof["n_flagged"] == 0
    assert iof["idiom_over_fire_rate"] is None


def test_idiom_over_fire_null_consulted_not_counted_as_over_fire(tmp_path: Path) -> None:
    """Unobserved evidence usage (null) counts toward flagged but never as over-fire."""
    out = _ingest_obs(tmp_path, [
        {"element_id": "elem_ic"},  # no builder_consulted_evidence → null
    ])
    iof = idiom_over_fire_rate(read_calibration(out))
    assert iof["n_flagged"] == 1
    assert iof["n_over_fire"] == 0
    assert iof["idiom_over_fire_rate"] == 0.0
