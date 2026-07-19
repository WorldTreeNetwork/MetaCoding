"""Calibration report: per-class precision/recall + dial-sensitivity sweep.

Pure polars/pyarrow — no LLM calls. Used to tune d_hi / r_min dials and
track classifier quality across port runs.

Usage:
    python calibration_report.py \\
        --calibration eval/ctkr/calibration.parquet \\
        --load-parquet /path/to/intention_load.parquet

    python calibration_report.py \\
        --calibration eval/ctkr/calibration.parquet \\
        --load-parquet /path/to/intention_load.parquet \\
        --out-json report.json

Spec: docs/design/ct-intention-extraction.md §5.2–§5.3
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import polars as pl

from calibration_schema import read_calibration

# Default dial sweep grids (all dials per §5.2 / entropy-as-dial.md).
_D_HI_RANGE = [round(v * 0.1, 1) for v in range(3, 10)]  # 0.3, 0.4, … 0.9
_R_MIN_RANGE = [round(v * 0.1, 1) for v in range(2, 9)]   # 0.2, 0.3, … 0.8

_LOAD_CLASSES = ["structure-clear", "intention-critical", "ambiguous"]


def _classify(d: float, r: float, d_hi: float, r_min: float) -> str:
    """Re-apply the §5.2 classification rule at the given dial settings."""
    if d >= d_hi:
        return "structure-clear"
    if r >= r_min:
        return "intention-critical"
    return "ambiguous"


def precision_recall(cal: pl.DataFrame) -> pl.DataFrame:
    """Per-class precision from the calibration record.

    precision@class = fraction of predictions for that class where
    miss_type == "none" (i.e. the builder confirmed the prediction was correct).

    Recall requires a ground-truth observed class; that is not available from
    builder_consulted_evidence alone, so this function computes precision +
    evidence_consult_rate (a proxy for the load-class signal quality).

    Returns an empty DataFrame (correct schema) when cal is empty.
    """
    empty_schema = {
        "predicted_load_class": pl.Utf8,
        "n_predictions": pl.Int64,
        "n_correct": pl.Int64,
        "precision": pl.Float64,
        "n_evidence_consulted": pl.Int64,
        "evidence_consult_rate": pl.Float64,
    }
    if cal.height == 0:
        return pl.DataFrame(schema=empty_schema)

    rows = []
    for cls in _LOAD_CLASSES:
        subset = cal.filter(pl.col("predicted_load_class") == cls)
        n = subset.height
        if n == 0:
            continue
        n_correct = subset.filter(pl.col("miss_type") == "none").height
        n_consulted = (
            subset.filter(pl.col("builder_consulted_evidence") == True).height  # noqa: E712
        )
        rows.append({
            "predicted_load_class": cls,
            "n_predictions": n,
            "n_correct": n_correct,
            "precision": round(n_correct / n, 4),
            "n_evidence_consulted": n_consulted,
            "evidence_consult_rate": round(n_consulted / n, 4),
        })

    return pl.DataFrame(rows, schema=empty_schema) if rows else pl.DataFrame(schema=empty_schema)


# Flagged classes whose whole purpose is to signal "a port must consult evidence
# here". When one fires on a source-idiom element a value-equivalence port never
# implements, that is an OVER-FIRE (dial-rec #1: track it, do NOT silently filter).
_FLAGGED_CLASSES = ["intention-critical", "ambiguous"]


def idiom_over_fire_rate(cal: pl.DataFrame) -> dict:
    """Idiom-over-fire rate for the flagged load classes (dial-rec #1).

    An intention-critical / ambiguous prediction exists to tell a port "consult the
    harvested evidence here". It OVER-FIRES when it lands on a source-idiom element with
    no path to a value-line term — one the value-equivalence port never implements, so
    the builder never needed the evidence. The value-line proxy already recorded by the
    pipeline is ``builder_consulted_evidence``: a flagged class the builder did NOT
    consult (miss_type ``evidence-given-not-needed``) fired on a non-value element.

    Duke's goalpost rule (§open-question 3): keep scoring EVERY element — do not filter
    source-idiom elements out of calibration — but surface the over-fire as its own
    metric so the classifier's source-paradigm noise is explicit and tracked, not hidden.

    Returns a dict::

        {
          "n_flagged": int,          # intention-critical + ambiguous predictions
          "n_over_fire": int,        # of those, ones the builder never needed
          "idiom_over_fire_rate": float | None,   # n_over_fire / n_flagged (None if 0)
          "by_class": {cls: {"n_flagged", "n_over_fire", "rate"}},
        }

    Rows with ``builder_consulted_evidence`` null (evidence usage unobserved) are counted
    in ``n_flagged`` but never as over-fire (unknown != over-fire).
    """
    by_class: dict[str, dict] = {}
    n_flagged = 0
    n_over = 0
    for cls in _FLAGGED_CLASSES:
        subset = cal.filter(pl.col("predicted_load_class") == cls) if cal.height else cal
        n = subset.height
        # over-fire: builder explicitly did NOT consult (False, not null)
        n_of = (
            subset.filter(pl.col("builder_consulted_evidence") == False).height  # noqa: E712
            if n
            else 0
        )
        n_flagged += n
        n_over += n_of
        by_class[cls] = {
            "n_flagged": n,
            "n_over_fire": n_of,
            "rate": round(n_of / n, 4) if n else None,
        }
    return {
        "n_flagged": n_flagged,
        "n_over_fire": n_over,
        "idiom_over_fire_rate": round(n_over / n_flagged, 4) if n_flagged else None,
        "by_class": by_class,
    }


def dial_sweep(
    load_df: pl.DataFrame,
    cal: pl.DataFrame,
    *,
    d_hi_range: list[float] | None = None,
    r_min_range: list[float] | None = None,
) -> pl.DataFrame:
    """Re-classify all elements at each (d_hi, r_min) pair; report the frontier.

    For each grid point:
    - Computes class distribution across all elements in load_df.
    - Where calibration data exists (joined by element_id), computes precision
      at the new thresholds (fraction of calibrated elements with miss_type=="none"
      under the re-classification).

    Returns one row per (d_hi, r_min) configuration sorted by d_hi, r_min.
    """
    d_hi_vals = d_hi_range if d_hi_range is not None else _D_HI_RANGE
    r_min_vals = r_min_range if r_min_range is not None else _R_MIN_RANGE

    # Build calibration index: element_id → miss_type (last recorded)
    cal_miss: dict[str, str | None] = {}
    if cal.height > 0:
        for row in cal.sort("recorded_at").iter_rows(named=True):
            cal_miss[row["element_id"]] = row.get("miss_type")

    # Pre-extract load rows once
    load_rows = load_df.iter_rows(named=True)
    load_list = list(load_rows)

    results = []
    for d_hi in d_hi_vals:
        for r_min in r_min_vals:
            n_sc = n_ic = n_amb = 0
            n_cal = n_correct_cal = 0

            for row in load_list:
                d = float(row.get("structural_determinacy") or 0.0)
                r = float(row.get("intention_richness") or 0.0)
                cls = _classify(d, r, d_hi, r_min)

                if cls == "structure-clear":
                    n_sc += 1
                elif cls == "intention-critical":
                    n_ic += 1
                else:
                    n_amb += 1

                eid = row["element_id"]
                if eid in cal_miss:
                    n_cal += 1
                    if cal_miss[eid] == "none":
                        n_correct_cal += 1

            total = n_sc + n_ic + n_amb
            results.append({
                "d_hi": d_hi,
                "r_min": r_min,
                "n_structure_clear": n_sc,
                "n_intention_critical": n_ic,
                "n_ambiguous": n_amb,
                "frac_structure_clear": round(n_sc / total, 4) if total else 0.0,
                "frac_ambiguous": round(n_amb / total, 4) if total else 0.0,
                "n_calibrated": n_cal,
                "precision_at_calibrated": round(n_correct_cal / n_cal, 4) if n_cal else None,
            })

    return pl.DataFrame(results).sort(["d_hi", "r_min"])


def report(
    calibration_path: Path,
    load_parquet_path: Path,
    *,
    d_hi_range: list[float] | None = None,
    r_min_range: list[float] | None = None,
) -> dict[str, object]:
    """Run all report components; return
    {"precision_recall": df, "idiom_over_fire": dict, "dial_sweep": df}."""
    cal = read_calibration(calibration_path)
    load_df = pl.read_parquet(load_parquet_path)
    return {
        "precision_recall": precision_recall(cal),
        "idiom_over_fire": idiom_over_fire_rate(cal),
        "dial_sweep": dial_sweep(load_df, cal, d_hi_range=d_hi_range, r_min_range=r_min_range),
    }


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Calibration report: precision/recall + dial-sensitivity sweep"
    )
    ap.add_argument("--calibration", required=True, type=Path, help="calibration.parquet")
    ap.add_argument("--load-parquet", required=True, type=Path, help="intention_load.parquet")
    ap.add_argument(
        "--out-json", default=None, type=Path, help="Write report as JSON (optional)"
    )
    args = ap.parse_args()

    result = report(args.calibration, args.load_parquet)
    pr = result["precision_recall"]
    iof = result["idiom_over_fire"]
    sweep = result["dial_sweep"]

    print("\n=== Per-class precision/recall ===")
    if pr.height == 0:
        print("  (no calibration data yet)")
    else:
        print(pr)

    print("\n=== Idiom-over-fire (flagged classes firing on non-value elements) ===")
    rate = iof["idiom_over_fire_rate"]
    print(
        f"  {iof['n_over_fire']}/{iof['n_flagged']} flagged predictions over-fired"
        f"  (rate = {rate if rate is not None else 'n/a'})"
    )
    for cls, c in iof["by_class"].items():
        print(f"    {cls:20} {c['n_over_fire']}/{c['n_flagged']}  (rate {c['rate']})")

    print(f"\n=== Dial-sensitivity sweep ({sweep.height} grid points) ===")
    print(sweep.head(10))
    if sweep.height > 10:
        print(f"  … {sweep.height - 10} more rows (use --out-json for full output)")

    if args.out_json:
        out = {
            "precision_recall": pr.to_dicts(),
            "idiom_over_fire": iof,
            "dial_sweep": sweep.to_dicts(),
        }
        args.out_json.write_text(json.dumps(out, indent=2), encoding="utf-8")
        print(f"\nReport written to {args.out_json}")


if __name__ == "__main__":
    main()
