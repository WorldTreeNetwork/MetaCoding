"""Port-run observation emitter (port-loop Phase 4, calibration lane).

The deferred half of the calibration pipeline: `calibration_ingest.py` consumes a
per-element observation JSONL, but *producing* that JSONL from a real port run was
left to the port-runner. This is that emitter.

A port run observes, per intention_load element, two things the classifier cannot
know a priori:

  * ``builder_consulted_evidence`` — did the blind builder actually need to read
    the element's harvested EVIDENCE (intent statements / test slices) to
    implement it, or did the SHAPE alone suffice?
  * ``observed_class``           — the load class the run *revealed* the element to
    have (what it actually took to port it), independent of the prediction.

Both are observer judgments distilled from the builder's report (its questions,
uncertainties, and what it did vs. skipped). This script records them against the
predicted ``intention_load.parquet`` and writes the observation JSONL that
``calibration_ingest.py`` ingests.

Observations come from a small YAML/JSON file — one entry per element_id:

    observations:
      "role:752cb704...":
        consulted: false          # builder did NOT read the evidence
        observed_class: none      # revealed to be irrelevant to the value port
        note: "source-idiom views filter; not part of the value slice"

Elements absent from the file default to ``consulted: false`` (built from shape),
which for a predicted ``structure-clear`` element is a *correct* prediction.

miss_type is derived so `calibration_report.py` can score precision:
  * observed_class given and != predicted            -> "wrong-class"
  * else fall back to (predicted, consulted) table    -> ingest's derivation
    (emitted explicitly here so the record is self-contained).

Usage:
    python port_run_emit.py \\
        --load-parquet <intention_load.parquet> \\
        --observations <observations.yaml|.json> \\
        --out <port_run_obs.jsonl>
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

# (predicted_class, builder_consulted_evidence) -> miss_type
# (mirror of calibration_ingest._MISS_DERIVE; kept local so the emitted record is
#  self-contained and ingest can pass it through verbatim.)
_MISS_DERIVE: dict[tuple[str, bool], str] = {
    ("structure-clear", False): "none",
    ("structure-clear", True): "needed-evidence-not-given",
    ("intention-critical", True): "none",
    ("intention-critical", False): "evidence-given-not-needed",
    ("ambiguous", True): "none",
    ("ambiguous", False): "evidence-given-not-needed",
}

_LOAD_CLASSES = {"structure-clear", "intention-critical", "ambiguous", "none"}


def _load_observations(path: Path) -> dict[str, dict]:
    text = path.read_text(encoding="utf-8")
    if path.suffix in (".yaml", ".yml"):
        try:
            import yaml  # type: ignore
        except ModuleNotFoundError:
            sys.exit("PyYAML not installed; use a .json observations file instead")
        doc = yaml.safe_load(text)
    else:
        doc = json.loads(text)
    obs = doc.get("observations", doc) if isinstance(doc, dict) else {}
    if not isinstance(obs, dict):
        sys.exit("observations file must map element_id -> {consulted, observed_class, note}")
    return obs


def _derive_miss(predicted: str, consulted: bool | None, observed: str | None) -> str | None:
    if observed is not None and observed != predicted:
        return "wrong-class"
    if consulted is None:
        return None
    return _MISS_DERIVE.get((predicted, consulted))


def emit(load_parquet: Path, observations: Path, out: Path) -> int:
    load_df = pl.read_parquet(load_parquet)
    predicted_by_id: dict[str, str] = {
        r["element_id"]: r["load_class"] for r in load_df.iter_rows(named=True)
    }
    obs = _load_observations(observations)

    # validate observed_class values up front
    for eid, o in obs.items():
        oc = (o or {}).get("observed_class")
        if oc is not None and oc not in _LOAD_CLASSES:
            sys.exit(f"element {eid!r}: observed_class {oc!r} not in {sorted(_LOAD_CLASSES)}")

    lines: list[str] = []
    for eid, predicted in predicted_by_id.items():
        o = obs.get(eid, {}) or {}
        consulted = bool(o.get("consulted", False))
        observed = o.get("observed_class")
        miss = _derive_miss(predicted, consulted, observed)
        rec = {
            "element_id": eid,
            "builder_consulted_evidence": consulted,
            "miss_type": miss,
            "observed_class": observed,  # informational; ingest ignores unknown keys
            "note": o.get("note", ""),
            "source": "port-run",
        }
        lines.append(json.dumps(rec))

    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text("\n".join(lines) + "\n", encoding="utf-8")
    n_obs = sum(1 for e in predicted_by_id if e in obs)
    print(
        f"emitted {len(lines)} observation(s) → {out} "
        f"({n_obs} explicitly observed, {len(predicted_by_id) - n_obs} defaulted to shape-only)"
    )
    return len(lines)


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Emit a port-run observation JSONL for calibration ingest"
    )
    ap.add_argument(
        "--load-parquet", required=True, type=Path,
        help="intention_load.parquet the run predicted against",
    )
    ap.add_argument(
        "--observations", required=True, type=Path, help="observer judgments (YAML/JSON)"
    )
    ap.add_argument("--out", required=True, type=Path, help="output observation JSONL")
    args = ap.parse_args()
    emit(args.load_parquet, args.observations, args.out)


if __name__ == "__main__":
    main()
