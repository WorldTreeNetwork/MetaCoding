"""``ctkr mine-motifs`` — frequent typed-subgraph mining (Orchestrators-k97)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "mine-motifs",
        help="Mine frequent typed 3-node motifs over the corpus graph.",
        description=(
            "Enumerate paths, V-shapes, and wedges over the loaded typed "
            "graph. Writes motifs.parquet + motif_instances.parquet under "
            "<data_dir>/ctkr/."
        ),
    )
    add_common_flags(p)
    p.add_argument("--min-support", type=int, default=5)
    p.add_argument("--max-incident-edges", type=int, default=30)
    p.add_argument("--max-instances-per-motif", type=int, default=100)
    p.add_argument(
        "--include-all-kinds",
        action="store_true",
        help=(
            "Consider every symbol kind as anchor (default: only "
            "class/interface/method/function/type_alias/namespace/enum)."
        ),
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.motif_mining import (
        DEFAULT_INTERESTING_KINDS,
        mine_motifs,
        write_motif_instances,
        write_motifs,
    )

    data_dir = resolve_data_dir(args.data_dir)
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(f"  {g.number_of_nodes()} nodes, {g.number_of_edges()} edges\n")

    sys.stderr.write(
        f"mining 3-node motifs: min_support={args.min_support}, "
        f"max_incident_edges={args.max_incident_edges}, "
        f"max_instances_per_motif={args.max_instances_per_motif}\n"
    )
    kinds_filter = None if args.include_all_kinds else DEFAULT_INTERESTING_KINDS
    motifs_df, instances_df, stats = mine_motifs(
        g,
        min_support=args.min_support,
        max_incident_edges=args.max_incident_edges,
        max_instances_per_motif=args.max_instances_per_motif,
        interesting_kinds=kinds_filter,
    )

    out_root = Path(data_dir) / "ctkr"
    write_motifs(motifs_df, out_root / "motifs.parquet")
    write_motif_instances(instances_df, out_root / "motif_instances.parquet")

    sys.stderr.write(
        f"  considered {stats.n_nodes_considered} nodes / visited {stats.n_anchors_visited} anchors "
        f"({stats.capped_anchors} capped)\n"
        f"  signatures observed: {stats.n_signatures_seen}\n"
        f"  motifs ≥ support {args.min_support}: {stats.n_motifs_kept}\n"
        f"  instance rows: {stats.n_instances_kept}\n"
        f"  total: {stats.seconds}s\n"
    )
    return 0
