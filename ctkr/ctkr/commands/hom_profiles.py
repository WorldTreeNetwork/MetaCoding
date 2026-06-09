"""``ctkr hom-profiles`` — emit ``hom_profiles.parquet`` (MetaCoding-23q.1).

Computes per-symbol typed-edge profile vectors and writes them as a
parquet table at maximal precision (raw UInt32 counts, no quantisation).
See :mod:`ctkr.hom_profiles` for the algorithm; this module is a thin
CLI wrapper.

The ``--kinds-filter`` flag implements the resolution to MetaCoding-o7k
(closed 2026-06-02 → option A): exclude listed ``Symbol.kind`` values
from the output without rebalancing edge counts on the surviving
endpoints. Common usage: ``--kinds-filter file`` to drop file-node
rows whose hom-profiles are dominated by ``CONTAINS:in=1.0``.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph
from ctkr.hom_profiles import (
    NDIM,
    compute_hom_profiles,
    write_hom_profiles,
    write_manifest,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "hom-profiles",
        help="Compute per-symbol hom-profiles → hom_profiles.parquet (MetaCoding-23q.1).",
        description=(
            "Compute per-symbol typed-edge profile vectors and write them as "
            "<data_dir>/ctkr/hom_profiles.parquet at maximal precision (raw "
            "integer counts; no L1-normalisation, no quantisation). "
            "Implements MetaCoding-23q.1; see docs/notes/entropy-as-dial.md "
            "for the granularity-as-query-time-knob framing."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--kinds-filter",
        action="append",
        default=None,
        metavar="KIND",
        help=(
            "Symbol kind to EXCLUDE from the output (repeatable). Edges "
            "incident to excluded symbols still increment their surviving "
            "neighbors' counts. Common usage: --kinds-filter file."
        ),
    )
    p.add_argument(
        "--out",
        default=None,
        help="Output path. Default: <data_dir>/ctkr/hom_profiles.parquet.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    start = time.perf_counter()
    data_dir = resolve_data_dir(args.data_dir)
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(
        f"  {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges\n"
    )

    if g.number_of_nodes() == 0:
        sys.stderr.write("ERROR: empty graph — nothing to compute.\n")
        return 1

    kinds_filter = set(args.kinds_filter) if args.kinds_filter else None
    filter_label = sorted(kinds_filter) if kinds_filter else "(none)"
    sys.stderr.write(f"computing hom-profiles (kinds_filter={filter_label})...\n")
    df, stats = compute_hom_profiles(g, kinds_filter=kinds_filter)

    canonical_out = (data_dir / "ctkr" / "hom_profiles.parquet").resolve()
    out = Path(args.out).expanduser().resolve() if args.out else canonical_out
    sys.stderr.write(f"writing {df.height:,} rows to {out}...\n")
    write_hom_profiles(df, out)

    # Skip manifest update when --out points outside the canonical path;
    # the manifest's "artifact present" promise must match where it lives.
    if out == canonical_out:
        manifest_path: Path | None = write_manifest(
            data_dir,
            hom_profiles=True,
            n_hom_profiles=df.height,
            profile_vec_dim=NDIM,
        )
    else:
        manifest_path = None
        sys.stderr.write(
            f"  note: --out points outside {canonical_out.parent}; "
            "skipping manifest.json update to avoid desync.\n"
        )

    elapsed = round(time.perf_counter() - start, 3)
    filter_desc = (
        ",".join(sorted(kinds_filter)) if kinds_filter else "(none)"
    )
    manifest_desc = str(manifest_path) if manifest_path else "(skipped — non-canonical --out)"
    sys.stderr.write(
        "\n"
        f"  rows            : {df.height:,}\n"
        f"  profile_vec_dim : {NDIM}\n"
        f"  kinds_filter    : {filter_desc}\n"
        f"  output          : {out}\n"
        f"  manifest        : {manifest_desc}\n"
        f"  elapsed         : {elapsed}s (compute {stats.elapsed_seconds}s)\n"
    )

    if getattr(args, "as_json", False):
        import json

        sys.stdout.write(
            json.dumps(
                {
                    "rows": df.height,
                    "profile_vec_dim": NDIM,
                    "kinds_filter": sorted(kinds_filter) if kinds_filter else [],
                    "output": str(out),
                    "manifest": str(manifest_path) if manifest_path else None,
                    "elapsed_seconds": elapsed,
                }
            )
            + "\n"
        )
    return 0
