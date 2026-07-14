"""``ctkr interfaces`` — interface + data-shape extraction (Stage B / §3, T2).

Extracts each subsystem's boundary morphisms (provides/consumes contract) and
its data-shape vocabulary (boundary vs internal types, per-field flow) from the
typed graph + the T1 partition. Writes ``interfaces.parquet`` +
``data_shapes.parquet`` under ``<data_dir>/ctkr/`` and merges presence flags +
the per-lane ``alphabet_coverage`` note into ``manifest.json``.

Requires the Stage A artifacts (``ctkr subsystems``) to exist first.

See :mod:`ctkr.interfaces` for the algorithm and
``docs/design/ct-subsystem-extraction.md`` §3 for the design.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "interfaces",
        help="Extract subsystem boundary morphisms + data shapes (Stage B).",
        description=(
            "Extract each subsystem's interface contract (provides = external->"
            "internal crossing morphisms; consumes = internal->external) and its "
            "data-shape vocabulary (boundary vs internal types, per-field "
            "read/write flow) from the typed graph and the T1 subsystem "
            "partition. Emits interfaces.parquet + data_shapes.parquet under "
            "<data_dir>/ctkr/ and a per-lane alphabet_coverage note in "
            "manifest.json. Requires `ctkr subsystems` to have run first."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--generated-at",
        type=str,
        default=None,
        help="Fixed ISO-8601 timestamp to stamp on the manifest (for "
        "byte-identical re-runs). Default: now(). Does not affect row content.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.interfaces import (
        compute_interfaces,
        write_data_shapes,
        write_interfaces,
        write_manifest,
    )

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    members_path = ctkr_dir / "subsystem_members.parquet"
    if not members_path.exists():
        sys.stderr.write(
            f"ERROR: {members_path} not found — run `ctkr subsystems` first "
            "(Stage A / T1 is a prerequisite of interface extraction).\n"
        )
        return 2

    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(
        f"  {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges\n"
    )
    if g.number_of_nodes() == 0:
        sys.stderr.write("ERROR: empty graph — nothing to extract.\n")
        return 1

    members_df = pl.read_parquet(members_path)

    iface_df, data_df, stats = compute_interfaces(
        g, members_df, generated_at=args.generated_at
    )

    ctkr_dir.mkdir(parents=True, exist_ok=True)
    write_interfaces(iface_df, ctkr_dir / "interfaces.parquet")
    write_data_shapes(data_df, ctkr_dir / "data_shapes.parquet")
    manifest_path = write_manifest(
        data_dir,
        n_interfaces=iface_df.height,
        n_data_shapes=data_df.height,
        alphabet_coverage=stats.alphabet_coverage,
        generated_at=args.generated_at,
    )

    sys.stderr.write(
        "\n"
        f"  interfaces       : {stats.n_interfaces:,} "
        f"(provides {stats.n_provides:,} / consumes {stats.n_consumes:,})\n"
        f"  data shapes      : {stats.n_data_shapes:,} rows "
        f"(boundary types {stats.n_boundary_types} / internal {stats.n_internal_types})\n"
        f"  subsystems       : {stats.n_subsystems}\n"
        f"  manifest         : {manifest_path}\n"
        f"  elapsed          : {stats.total_seconds}s\n"
    )
    for repo, cov in sorted(stats.alphabet_coverage.items()):
        sys.stderr.write(f"  alphabet[{repo}]  : {cov['note']}\n")

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "n_interfaces": stats.n_interfaces,
                    "n_provides": stats.n_provides,
                    "n_consumes": stats.n_consumes,
                    "n_data_shapes": stats.n_data_shapes,
                    "n_boundary_types": stats.n_boundary_types,
                    "n_internal_types": stats.n_internal_types,
                    "n_subsystems": stats.n_subsystems,
                    "per_subsystem": stats.per_subsystem,
                    "alphabet_coverage": stats.alphabet_coverage,
                    "elapsed_seconds": stats.total_seconds,
                },
                default=str,
            )
            + "\n"
        )
    return 0
