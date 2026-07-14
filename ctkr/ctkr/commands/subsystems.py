"""``ctkr subsystems`` — subsystem partition (Stage A / DECOMPOSE, T1).

Consensus Louvain partition over a resolution sweep with persistence metadata.
Writes ``subsystems.parquet`` + ``subsystem_members.parquet`` under
``<data_dir>/ctkr/`` and merges the presence flags into ``manifest.json``.

See :mod:`ctkr.subsystems` for the algorithm and
``docs/design/ct-subsystem-extraction.md`` §2 for the design.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "subsystems",
        help="Partition each repo into subsystems (consensus Louvain + persistence).",
        description=(
            "Partition the object set of each indexed repo into subsystems at a "
            "team-would-own-this granularity, using a consensus Louvain partition "
            "over a resolution sweep with a low-weight directory prior. Emits "
            "subsystems.parquet + subsystem_members.parquet under <data_dir>/ctkr/ "
            "with per-member boundary_confidence and per-subsystem persistence. "
            "Zero-profile (structurally isolated) symbols are placed by directory "
            "locality and flagged placement='locality'. Deterministic: byte-"
            "identical re-runs for a fixed --generated-at."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--resolution",
        type=float,
        default=None,
        help="Default Louvain resolution the emitted partition is cut at "
        "(default 0.5; higher = more, smaller subsystems).",
    )
    p.add_argument(
        "--sweep",
        type=str,
        default=None,
        help="Comma-separated resolution sweep for persistence "
        "(default '0.3,0.5,0.7,1.0,1.3,1.6,2.0'). The default resolution is "
        "always unioned in.",
    )
    p.add_argument("--seed", type=int, default=None, help="Louvain seed (default 42).")
    p.add_argument(
        "--contains-weight",
        type=float,
        default=None,
        help="Weight for CONTAINS edges (containment backbone; default 1.0).",
    )
    p.add_argument(
        "--references-weight",
        type=float,
        default=None,
        help="Weight for REFERENCES edges (cross-cutting; default 0.5).",
    )
    p.add_argument(
        "--dir-prior",
        type=float,
        default=None,
        help="Weight of the per-directory locality prior edge each symbol gets "
        "(default 1.0; 0 disables the prior — then isolated symbols drop out).",
    )
    p.add_argument(
        "--dir-level",
        type=int,
        default=None,
        help="Path depth for the directory-prior hub key (default 2, e.g. src/mcp).",
    )
    p.add_argument(
        "--min-repo-size",
        type=int,
        default=None,
        help="Skip repos with fewer than this many symbols (default 4).",
    )
    p.add_argument(
        "--generated-at",
        type=str,
        default=None,
        help="Fixed ISO-8601 timestamp to stamp on rows (for byte-identical "
        "re-runs). Default: now(). Does not affect subsystem_ids.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.subsystems import (
        DEFAULT_CONTAINS_WEIGHT,
        DEFAULT_DIR_LEVEL,
        DEFAULT_DIR_PRIOR,
        DEFAULT_MIN_REPO_SIZE,
        DEFAULT_REFERENCES_WEIGHT,
        DEFAULT_RESOLUTION,
        DEFAULT_SEED,
        DEFAULT_SWEEP,
        compute_subsystems,
        write_manifest,
        write_subsystem_members,
        write_subsystems,
    )

    data_dir = resolve_data_dir(args.data_dir)
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(f"  {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges\n")
    if g.number_of_nodes() == 0:
        sys.stderr.write("ERROR: empty graph — nothing to partition.\n")
        return 1

    resolution = args.resolution if args.resolution is not None else DEFAULT_RESOLUTION
    seed = args.seed if args.seed is not None else DEFAULT_SEED
    if args.sweep:
        try:
            sweep = [float(x) for x in args.sweep.split(",") if x.strip()]
        except ValueError:
            sys.stderr.write(f"ERROR: --sweep must be comma-separated floats, got {args.sweep!r}\n")
            return 2
        if not sweep:
            sys.stderr.write("ERROR: --sweep is empty.\n")
            return 2
    else:
        sweep = list(DEFAULT_SWEEP)

    sub_df, mem_df, stats = compute_subsystems(
        g,
        default_resolution=resolution,
        sweep=sweep,
        seed=seed,
        contains_weight=(
            args.contains_weight if args.contains_weight is not None else DEFAULT_CONTAINS_WEIGHT
        ),
        references_weight=(
            args.references_weight
            if args.references_weight is not None
            else DEFAULT_REFERENCES_WEIGHT
        ),
        dir_prior=(args.dir_prior if args.dir_prior is not None else DEFAULT_DIR_PRIOR),
        dir_level=(args.dir_level if args.dir_level is not None else DEFAULT_DIR_LEVEL),
        min_repo_size=(
            args.min_repo_size if args.min_repo_size is not None else DEFAULT_MIN_REPO_SIZE
        ),
        generated_at=args.generated_at,
    )

    out_root = Path(data_dir) / "ctkr"
    out_root.mkdir(parents=True, exist_ok=True)
    write_subsystems(sub_df, out_root / "subsystems.parquet")
    write_subsystem_members(mem_df, out_root / "subsystem_members.parquet")
    manifest_path = write_manifest(
        data_dir, n_subsystems=sub_df.height, generated_at=args.generated_at
    )

    sys.stderr.write(
        "\n"
        f"  subsystems       : {sub_df.height}\n"
        f"  members          : {stats.n_members:,}\n"
        f"  locality-placed  : {stats.n_locality:,} "
        f"({(stats.n_locality / stats.n_members if stats.n_members else 0):.1%})\n"
        f"  persistent       : {stats.pct_persistent:.1%} "
        f"(boundary_confidence >= threshold)\n"
        f"  repos            : {stats.n_repos}\n"
        f"  manifest         : {manifest_path}\n"
        f"  elapsed          : {stats.total_seconds}s\n"
    )

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "n_subsystems": sub_df.height,
                    "n_members": stats.n_members,
                    "n_locality": stats.n_locality,
                    "pct_persistent": stats.pct_persistent,
                    "n_repos": stats.n_repos,
                    "per_repo": stats.per_repo,
                    "elapsed_seconds": stats.total_seconds,
                }
            )
            + "\n"
        )
    return 0
