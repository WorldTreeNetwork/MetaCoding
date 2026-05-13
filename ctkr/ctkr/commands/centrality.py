"""``ctkr centrality`` — global centrality + per-repo community clusters."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "centrality",
        help="Compute pagerank + betweenness + eigenvector + per-repo communities.",
        description=(
            "Runs three centrality measures on the global corpus graph "
            "and Louvain community detection per repo. Writes "
            "centrality.parquet + spectral_clusters.parquet under "
            "<data_dir>/ctkr/."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--betweenness-k",
        type=int,
        default=1000,
        help="Sample size for approximate betweenness centrality.",
    )
    p.add_argument("--eigenvector-max-iter", type=int, default=500)
    p.add_argument("--eigenvector-tol", type=float, default=1e-4)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--min-repo-size",
        type=int,
        default=4,
        help="Skip repos with fewer than this many nodes for clustering.",
    )
    p.add_argument(
        "--skip-centrality",
        action="store_true",
        help="Only run per-repo clustering, skip global centrality.",
    )
    p.add_argument(
        "--skip-clusters",
        action="store_true",
        help="Only run global centrality, skip per-repo clustering.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.centrality import (
        compute_centrality,
        compute_clusters,
        write_centrality,
        write_clusters,
    )

    data_dir = resolve_data_dir(args.data_dir)
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(f"  {g.number_of_nodes()} nodes, {g.number_of_edges()} edges\n")

    out_root = Path(data_dir) / "ctkr"
    out_root.mkdir(parents=True, exist_ok=True)

    if not args.skip_centrality:
        sys.stderr.write("computing centrality (pagerank → betweenness → eigenvector)...\n")
        cdf, cstats = compute_centrality(
            g,
            betweenness_k=args.betweenness_k,
            eigenvector_max_iter=args.eigenvector_max_iter,
            eigenvector_tol=args.eigenvector_tol,
            seed=args.seed,
        )
        write_centrality(cdf, out_root / "centrality.parquet")
        sys.stderr.write(
            f"  centrality.parquet: {cdf.height} rows "
            f"(pr={cstats.pagerank_seconds}s, "
            f"bc≈k={cstats.betweenness_k} {cstats.betweenness_seconds}s, "
            f"ec={cstats.eigenvector_seconds}s converged={cstats.eigenvector_converged})\n"
        )

    if not args.skip_clusters:
        sys.stderr.write("computing per-repo Louvain communities...\n")
        kdf, kstats = compute_clusters(g, seed=args.seed, min_repo_size=args.min_repo_size)
        write_clusters(kdf, out_root / "spectral_clusters.parquet")
        sys.stderr.write(
            f"  spectral_clusters.parquet: {kdf.height} rows, "
            f"{kstats.n_repos} repos, {kstats.n_clusters_total} clusters "
            f"({kstats.total_seconds}s)\n"
            f"  largest repo: {kstats.largest_repo} "
            f"({kstats.largest_repo_nodes} nodes → {kstats.largest_repo_clusters} clusters)\n"
        )

    return 0
