"""Ingest a port-run observation JSONL into calibration.parquet.

Usage:
    python calibration_ingest.py \\
        --port-run-id run-2026-07-17-001 \\
        --observations port_run_obs.jsonl \\
        --load-parquet /path/to/intention_load.parquet \\
        --out eval/ctkr/calibration.parquet

Observation JSONL format — one JSON object per line:
    {
        "element_id": "...",
        "builder_consulted_evidence": true,        // bool, optional
        "miss_type": "needed-evidence-not-given",  // optional; derived if absent
        "source": "port-run"                       // optional; default "port-run"
    }

miss_type derivation from (predicted_load_class, builder_consulted_evidence):
    structure-clear   + consulted=True  → needed-evidence-not-given
    structure-clear   + consulted=False → none
    intention-critical + consulted=True  → none
    intention-critical + consulted=False → evidence-given-not-needed
    ambiguous         + consulted=True  → none
    ambiguous         + consulted=False → evidence-given-not-needed
    any class         + consulted=None  → null (unknown)
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from calibration_schema import append_calibration, make_calibration_row

# (predicted_class, builder_consulted_evidence) → miss_type
_MISS_DERIVE: dict[tuple[str, bool], str] = {
    ("structure-clear", False): "none",
    ("structure-clear", True): "needed-evidence-not-given",
    ("intention-critical", True): "none",
    ("intention-critical", False): "evidence-given-not-needed",
    ("ambiguous", True): "none",
    ("ambiguous", False): "evidence-given-not-needed",
}


def _derive_miss_type(predicted: str, consulted: bool | None) -> str | None:
    """Derive miss_type from (predicted_load_class, builder_consulted_evidence).

    Returns None when consulted is None (observer did not record evidence usage).
    """
    if consulted is None:
        return None
    return _MISS_DERIVE.get((predicted, consulted))


def ingest(
    port_run_id: str,
    observations_path: Path,
    load_parquet_path: Path,
    out_path: Path,
    recorded_at: str | None = None,
) -> int:
    """Ingest observations, join with intention_load, append to calibration.parquet.

    Returns the number of rows ingested.
    """
    ts = recorded_at or datetime.now(tz=UTC).isoformat()

    # Load intention_load predictions keyed by element_id.
    load_df = pl.read_parquet(load_parquet_path)
    load_index: dict[str, dict] = {
        row["element_id"]: row
        for row in load_df.iter_rows(named=True)
    }

    obs_lines = observations_path.read_text(encoding="utf-8").splitlines()
    rows: list[dict] = []
    skipped = 0

    for lineno, line in enumerate(obs_lines, 1):
        line = line.strip()
        if not line:
            continue
        try:
            obs = json.loads(line)
        except json.JSONDecodeError as exc:
            print(f"[warn] line {lineno}: JSON parse error: {exc}", file=sys.stderr)
            skipped += 1
            continue

        element_id = obs.get("element_id")
        if not element_id:
            print(f"[warn] line {lineno}: missing element_id", file=sys.stderr)
            skipped += 1
            continue

        load_row = load_index.get(element_id)
        if load_row is None:
            print(
                f"[warn] element {element_id!r} not in intention_load; skipping",
                file=sys.stderr,
            )
            skipped += 1
            continue

        predicted = load_row["load_class"]
        consulted: bool | None = obs.get("builder_consulted_evidence")
        # Explicit miss_type from observer takes precedence; otherwise derive.
        miss_type: str | None = obs.get("miss_type") or _derive_miss_type(predicted, consulted)
        source = obs.get("source", "port-run")

        # drivers may be a List[str] in parquet (polars returns Python list)
        drivers: list[str] = list(load_row.get("drivers") or [])

        rows.append(
            make_calibration_row(
                port_run_id=port_run_id,
                element_id=element_id,
                predicted_load_class=predicted,
                structural_determinacy=float(load_row.get("structural_determinacy") or 0.0),
                intention_richness=float(load_row.get("intention_richness") or 0.0),
                drivers=drivers,
                builder_consulted_evidence=consulted,
                miss_type=miss_type,
                source=source,
                recorded_at=ts,
            )
        )

    if not rows:
        print(f"[warn] no rows ingested (skipped {skipped})", file=sys.stderr)
        return 0

    combined = append_calibration(rows, out_path)
    print(
        f"ingested {len(rows)} row(s) ({skipped} skipped) "
        f"→ {out_path} ({combined.height} total rows)"
    )
    return len(rows)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Ingest port-run observations into calibration.parquet"
    )
    ap.add_argument("--port-run-id", required=True, help="Unique id for this port run")
    ap.add_argument(
        "--observations", required=True, type=Path, help="JSONL of per-element observations"
    )
    ap.add_argument(
        "--load-parquet", required=True, type=Path,
        help="intention_load.parquet the run predicted against",
    )
    ap.add_argument(
        "--out", required=True, type=Path,
        help="Output calibration.parquet (appended if already exists)",
    )
    ap.add_argument(
        "--recorded-at", default=None,
        help="ISO-8601 timestamp for recorded_at (default: now)",
    )
    args = ap.parse_args()
    ingest(args.port_run_id, args.observations, args.load_parquet, args.out, args.recorded_at)


if __name__ == "__main__":
    main()
