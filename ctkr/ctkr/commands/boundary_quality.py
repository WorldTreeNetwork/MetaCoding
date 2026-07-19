"""``ctkr boundary-quality`` — evaluate island boundary quality (MetaCoding-9h5.12).

Runs (or reads) the subsystem partition, then reports per-island boundary
composition — how many crossing edges are framework idioms (Drupal/Symfony
scaffolding) vs genuine domain coupling — and a stability diff (does the
partition survive pruning framework-idiom edges? ARI + moved-node count).

Reads ``<data_dir>/ctkr/export/nodes.jsonl`` + ``edges.jsonl`` and
``subsystems.parquet`` / ``subsystem_members.parquet``. If the partition
artifacts are absent it recomputes them in-memory (no write). LM-free.
"""

from __future__ import annotations

import argparse
import json
import sys

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "boundary-quality",
        help="Evaluate subsystem boundary quality (framework wiring vs domain seams).",
        description=(
            "For each island, classify the crossing (boundary) edges as framework "
            "idioms (edges to Drupal/Symfony base classes resolved outside the "
            "repo) vs genuine domain coupling, and run a stability diff: prune all "
            "framework-idiom edges, re-partition, and report the adjusted Rand "
            "index against the baseline. A boundary that survives the prune is a "
            "domain seam; one that dissolves was a wiring artifact. LM-free."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--no-base-heuristic",
        action="store_true",
        help="Classify only ``external::`` endpoints as framework (drop the in-repo "
        "Drupal-base name heuristic) for a maximally-conservative split.",
    )
    p.add_argument(
        "--skip-stability",
        action="store_true",
        help="Skip the prune-and-re-partition stability diff (faster).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.boundary_quality import boundary_quality, stability_diff
    from ctkr.subsystems import compute_subsystems

    data_dir = resolve_data_dir(getattr(args, "data_dir", None))
    ctkr_dir = data_dir / "ctkr"
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(f"  {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges\n")
    if g.number_of_nodes() == 0:
        sys.stderr.write("ERROR: empty graph.\n")
        return 1

    import polars as pl

    sub_path = ctkr_dir / "subsystems.parquet"
    mem_path = ctkr_dir / "subsystem_members.parquet"
    if sub_path.exists() and mem_path.exists():
        sub_df = pl.read_parquet(sub_path)
        mem_df = pl.read_parquet(mem_path)
        sys.stderr.write(f"  read partition: {sub_df.height} islands\n")
    else:
        sys.stderr.write("  no partition artifacts — computing in-memory\n")
        sub_df, mem_df, _ = compute_subsystems(g, generated_at="2026-07-20T00:00:00Z")

    include_base = not getattr(args, "no_base_heuristic", False)
    report = boundary_quality(g, mem_df, sub_df, include_base_heuristic=include_base)

    stability = None
    if not getattr(args, "skip_stability", False):
        sys.stderr.write("  running stability diff (prune framework edges + re-partition)...\n")

        def partition(graph):
            _, m, _ = compute_subsystems(graph, generated_at="2026-07-20T00:00:00Z")
            return {r["symbol_id"]: r["subsystem_id"] for r in m.iter_rows(named=True)}

        stability = stability_diff(g, partition, include_base_heuristic=False)

    if getattr(args, "as_json", False):
        out = {
            "n_islands": report.n_islands,
            "n_crossing": report.n_crossing,
            "n_framework_idiom": report.n_framework_idiom,
            "n_domain_coupling": report.n_domain_coupling,
            "framework_idiom_fraction": report.framework_idiom_fraction,
            "crossing_kind_histogram": report.crossing_kind_histogram,
            "domain_kind_histogram": report.domain_kind_histogram,
            "island_sizes": report.island_sizes,
            "islands": [
                {
                    "island_id": i.island_id,
                    "n_members": i.n_members,
                    "persistence_score": i.persistence_score,
                    "n_crossing": i.n_crossing,
                    "n_framework_idiom": i.n_framework_idiom,
                    "n_domain_coupling": i.n_domain_coupling,
                    "framework_idiom_fraction": i.framework_idiom_fraction,
                    "domain_neighbors": i.domain_neighbors,
                    "domain_kind_histogram": i.domain_kind_histogram,
                }
                for i in report.islands
            ],
        }
        if stability is not None:
            out["stability"] = {
                "n_shared": stability.n_shared,
                "ari": stability.ari,
                "n_moved": stability.n_moved,
                "moved_fraction": stability.moved_fraction,
                "n_pruned_nodes": stability.n_pruned_nodes,
                "n_pruned_edges": stability.n_pruned_edges,
                "baseline_sizes": stability.baseline_sizes,
                "pruned_sizes": stability.pruned_sizes,
            }
        sys.stdout.write(json.dumps(out, default=str) + "\n")
        return 0

    print(f"\n  islands            : {report.n_islands}")
    print(f"  crossing edges     : {report.n_crossing} (non-CONTAINS)")
    print(
        f"  framework idioms   : {report.n_framework_idiom} "
        f"({report.framework_idiom_fraction:.1%})"
    )
    print(f"  domain coupling    : {report.n_domain_coupling}")
    print(f"  crossing by kind   : {report.crossing_kind_histogram}")
    print(f"  domain by kind     : {report.domain_kind_histogram}")
    print("\n  per-island boundary composition:")
    print(f"    {'island':<14}{'n':>6}{'persist':>9}{'cross':>7}{'fw%':>7}  domain-neighbors")
    for i in report.islands:
        nb = ", ".join(f"{s[:8]}:{c}" for s, c in i.domain_neighbors[:3])
        print(
            f"    {i.island_id[:12]:<14}{i.n_members:>6}{i.persistence_score:>9.3f}"
            f"{i.n_crossing:>7}{i.framework_idiom_fraction * 100:>6.0f}%  {nb}"
        )
    if stability is not None:
        print("\n  stability diff (framework-idiom prune → re-partition):")
        print(f"    shared nodes     : {stability.n_shared}")
        print(f"    ARI              : {stability.ari}")
        print(f"    moved nodes      : {stability.n_moved} ({stability.moved_fraction:.1%})")
        print(f"    baseline sizes   : {stability.baseline_sizes}")
        print(f"    pruned sizes     : {stability.pruned_sizes}")
        verdict = (
            "boundaries are DOMAIN SEAMS (survive framework prune)"
            if stability.ari >= 0.8
            else "boundaries are partly WIRING ARTIFACTS (shift on prune)"
        )
        print(f"    verdict          : {verdict}")
    return 0
