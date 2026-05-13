"""``ctkr shape`` — per-repo persistent-homology shape signatures."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "shape",
        help="Compute per-repo persistent-homology shape signatures.",
        description=(
            "Build a degree-filtered flag complex for each repo, compute H_0 "
            "and H_1 persistence diagrams, write shape_pds.parquet, then "
            "compute the pairwise Wasserstein distance matrix between repos "
            "to wasserstein.parquet."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--max-nodes",
        type=int,
        default=3000,
        help="Per-repo node cap (degree-bias-sample if exceeded).",
    )
    p.add_argument(
        "--max-dim",
        type=int,
        default=1,
        help="Highest homology dimension to compute (0..max-dim).",
    )
    p.add_argument(
        "--min-repo-size",
        type=int,
        default=8,
        help="Skip repos with fewer than this many nodes.",
    )
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--skip-wasserstein",
        action="store_true",
        help="Only compute PDs; don't compute the distance matrix.",
    )
    p.add_argument(
        "--wasserstein-dim",
        type=int,
        default=1,
        help="Homology dim to use for the pairwise distance matrix.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    try:
        from ctkr.shape import (
            compute_shape_pds,
            wasserstein_distance_matrix,
            write_shape_pds,
            write_wasserstein,
        )
    except ImportError as e:
        sys.stderr.write(
            f"`ctkr shape` requires the 'topo' extra (gudhi).\n"
            f"  Install with: uv sync --extra topo\n"
            f"  ({e})\n"
        )
        return 2

    data_dir = resolve_data_dir(args.data_dir)
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(f"  {g.number_of_nodes()} nodes, {g.number_of_edges()} edges\n")

    sys.stderr.write(
        f"computing per-repo persistence diagrams (max_nodes={args.max_nodes}, "
        f"max_dim={args.max_dim})...\n"
    )
    df, pds, stats = compute_shape_pds(
        g,
        max_nodes_per_repo=args.max_nodes,
        max_dim=args.max_dim,
        seed=args.seed,
        min_repo_size=args.min_repo_size,
    )
    out_root = Path(data_dir) / "ctkr"
    write_shape_pds(df, out_root / "shape_pds.parquet")
    sys.stderr.write(
        f"  shape_pds.parquet: {df.height} rows across {stats.n_repos} repos, "
        f"{stats.n_points_total} persistence points ({stats.seconds}s)\n"
        f"  sampled repos (>{args.max_nodes} nodes): {len(stats.sampled_repos)}\n"
    )

    if not args.skip_wasserstein:
        sys.stderr.write(
            f"computing pairwise Wasserstein distances at dim={args.wasserstein_dim}...\n"
        )
        wdf, repos = wasserstein_distance_matrix(pds, dim=args.wasserstein_dim)
        write_wasserstein(wdf, out_root / f"wasserstein_h{args.wasserstein_dim}.parquet")
        sys.stderr.write(
            f"  wasserstein_h{args.wasserstein_dim}.parquet: "
            f"{wdf.height} pairwise distances over {len(repos)} repos\n"
        )

    return 0
