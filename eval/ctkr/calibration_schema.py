"""Calibration parquet schema for the port-loop ML pipeline.

One row per (port_run, element) observation: the pipeline's load-class
prediction alongside what the builder actually consulted, enabling
empirical tuning of D/R dials and prompt versions.

Spec: docs/design/port-loop-plan.md §cross-cutting #3
      docs/design/ct-intention-extraction.md §5.2–§5.3
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

import polars as pl
from blake3 import blake3

CALIBRATION_SCHEMA_VERSION: int = 1

# ── enum aliases (strings in parquet; kept as Literal for type-checking) ──

LoadClass = Literal["structure-clear", "intention-critical", "ambiguous"]
MissType = Literal[
    "none",
    "needed-evidence-not-given",   # predicted structure-clear; builder needed evidence
    "evidence-given-not-needed",   # predicted intention-critical; builder didn't use it
    "wrong-class",                 # broader mismatch / reclassification
    "builder-error",               # builder made an error unrelated to classifier
]
CalibrationSource = Literal["port-run", "human-review"]

# ── column order (deterministic; new fields append at end) ──

CALIBRATION_COLUMNS: tuple[str, ...] = (
    "calibration_row_id",          # blake3 deterministic id
    "port_run_id",                 # identifies the port-run batch
    "element_id",                  # FK → intention_load.parquet element_id
    "predicted_load_class",        # structure-clear | intention-critical | ambiguous
    "structural_determinacy",      # D score from intention_load
    "intention_richness",          # R score from intention_load
    "drivers",                     # list of driver strings from intention_load
    "builder_consulted_evidence",  # bool | null — did the builder read the evidence?
    "miss_type",                   # MissType | null
    "source",                      # port-run | human-review
    "recorded_at",                 # ISO-8601 timestamp
    "schema_version",
)


def _calibration_schema() -> dict:
    return {
        "calibration_row_id": pl.Utf8,
        "port_run_id": pl.Utf8,
        "element_id": pl.Utf8,
        "predicted_load_class": pl.Utf8,
        "structural_determinacy": pl.Float64,
        "intention_richness": pl.Float64,
        "drivers": pl.List(pl.Utf8),
        "builder_consulted_evidence": pl.Boolean,
        "miss_type": pl.Utf8,
        "source": pl.Utf8,
        "recorded_at": pl.Utf8,
        "schema_version": pl.Int64,
    }


def _row_id(port_run_id: str, element_id: str, source: str, recorded_at: str) -> str:
    """Deterministic blake3 id (per ctkr-l3-artifacts.md provenance convention)."""
    h = blake3()
    for part in (port_run_id, element_id, source, recorded_at):
        h.update(part.encode("utf-8"))
        h.update(b"\x00")
    return h.hexdigest(length=12)


def make_calibration_row(
    *,
    port_run_id: str,
    element_id: str,
    predicted_load_class: str,
    structural_determinacy: float,
    intention_richness: float,
    drivers: list[str],
    builder_consulted_evidence: bool | None,
    miss_type: str | None,
    source: str,
    recorded_at: str | None = None,
) -> dict:
    """Build a calibration row dict with a deterministic id."""
    ts = recorded_at or datetime.now(tz=UTC).isoformat()
    return {
        "calibration_row_id": _row_id(port_run_id, element_id, source, ts),
        "port_run_id": port_run_id,
        "element_id": element_id,
        "predicted_load_class": predicted_load_class,
        "structural_determinacy": float(structural_determinacy),
        "intention_richness": float(intention_richness),
        "drivers": list(drivers),
        "builder_consulted_evidence": builder_consulted_evidence,
        "miss_type": miss_type,
        "source": source,
        "recorded_at": ts,
        "schema_version": CALIBRATION_SCHEMA_VERSION,
    }


def _rows_to_df(rows: list[dict]) -> pl.DataFrame:
    schema = _calibration_schema()
    if not rows:
        return pl.DataFrame(schema=schema).select(list(CALIBRATION_COLUMNS))
    return pl.DataFrame(rows, schema=schema).select(list(CALIBRATION_COLUMNS))


def read_calibration(path: str | Path) -> pl.DataFrame:
    """Read calibration.parquet; returns empty frame (correct schema) if absent."""
    p = Path(path).expanduser().resolve()
    if not p.exists():
        return _rows_to_df([])
    return pl.read_parquet(p).select(list(CALIBRATION_COLUMNS))


def write_calibration(df: pl.DataFrame, path: str | Path) -> None:
    p = Path(path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(list(CALIBRATION_COLUMNS)).write_parquet(p)


def append_calibration(rows: list[dict], path: str | Path) -> pl.DataFrame:
    """Append new rows to calibration.parquet, deduplicating by calibration_row_id.

    Dedup keeps the *last* seen row (allows updates via re-ingest with same
    port_run_id + element_id + source + recorded_at).
    """
    existing = read_calibration(path)
    new_df = _rows_to_df(rows)
    if existing.height == 0:
        combined = new_df
    else:
        combined = (
            pl.concat([existing, new_df])
            .unique(subset=["calibration_row_id"], keep="last")
        )
    combined = combined.sort(["port_run_id", "element_id"])
    write_calibration(combined, path)
    return combined


__all__ = [
    "CALIBRATION_SCHEMA_VERSION",
    "CALIBRATION_COLUMNS",
    "LoadClass",
    "MissType",
    "CalibrationSource",
    "make_calibration_row",
    "read_calibration",
    "write_calibration",
    "append_calibration",
]
