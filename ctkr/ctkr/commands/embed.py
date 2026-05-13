"""``ctkr embed`` — DeepWalk-equivalent node embeddings (Orchestrators-7u7).

v1 uses uniform random walks (node2vec with p=q=1) + gensim Word2Vec.
Writes ``.metacoding/ctkr/embeddings.parquet`` conforming to the
schema in :mod:`ctkr.schema`.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "embed",
        help="Build node embeddings via DeepWalk + Word2Vec.",
        description=(
            "Compute structural embeddings for every symbol in the loaded "
            "graph using uniform random walks + gensim Word2Vec. Writes "
            "embeddings.parquet under <data_dir>/ctkr/."
        ),
    )
    add_common_flags(p)
    p.add_argument("--dim", type=int, default=128)
    p.add_argument("--walks", type=int, default=20, help="Walks per node.")
    p.add_argument("--walk-length", type=int, default=40)
    p.add_argument("--window", type=int, default=5)
    p.add_argument("--epochs", type=int, default=5)
    p.add_argument("--seed", type=int, default=42)
    p.add_argument(
        "--workers",
        type=int,
        default=1,
        help="Word2Vec worker threads. >1 trades determinism for speed.",
    )
    p.add_argument(
        "--kind",
        action="append",
        default=None,
        help=(
            "Restrict the embedded subset to specific symbol kinds "
            "(repeatable, e.g. --kind class --kind method). "
            "All nodes still seed the walks — only output rows are filtered."
        ),
    )
    p.add_argument(
        "--max-nodes",
        type=int,
        default=None,
        help="Truncate to the first N nodes (deterministic order). Smoke-test escape hatch.",
    )
    p.add_argument(
        "--no-name-bridges",
        dest="name_bridges",
        action="store_false",
        default=True,
        help=(
            "Disable synthetic NAME_SHARED edges linking same-short-name "
            "symbols across repos. Bridges are essential for cross-repo "
            "similarity; disable only for ablation studies."
        ),
    )
    p.add_argument(
        "--name-bridges-cap",
        type=int,
        default=3,
        help="Per-(short_name, repo) cap on outgoing bridge edges.",
    )
    p.add_argument(
        "--out",
        default=None,
        help=(
            "Output path. Default: <data_dir>/ctkr/embeddings.parquet."
        ),
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    # Lazy imports so the rest of the CLI loads instantly even when the
    # `embed` extra (gensim) isn't installed.
    try:
        from ctkr.embed import compute_embeddings, write_embeddings
    except ImportError as e:
        sys.stderr.write(
            f"`ctkr embed` requires the 'embed' extra (gensim).\n"
            f"  Install with: uv sync --extra embed\n"
            f"  ({e})\n"
        )
        return 2

    data_dir = resolve_data_dir(args.data_dir)
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)

    node_filter = None
    if args.kind:
        wanted = set(args.kind)
        node_filter = [n for n, d in g.nodes(data=True) if d.get("kind") in wanted]
        sys.stderr.write(f"kind filter {sorted(wanted)}: {len(node_filter)} nodes match\n")

    if args.max_nodes is not None:
        nodes = node_filter if node_filter is not None else list(g.nodes())
        node_filter = nodes[: args.max_nodes]
        sys.stderr.write(f"max-nodes capped to {len(node_filter)}\n")

    sys.stderr.write(
        f"running embed: dim={args.dim} walks={args.walks} length={args.walk_length} "
        f"epochs={args.epochs} seed={args.seed} workers={args.workers}\n"
    )

    df, stats = compute_embeddings(
        g,
        dim=args.dim,
        num_walks=args.walks,
        walk_length=args.walk_length,
        window=args.window,
        epochs=args.epochs,
        seed=args.seed,
        workers=args.workers,
        node_filter=node_filter,
        name_bridges=args.name_bridges,
        name_bridges_cap=args.name_bridges_cap,
    )

    out = Path(args.out) if args.out else (data_dir / "ctkr" / "embeddings.parquet")
    write_embeddings(df, out)

    sys.stderr.write(
        f"wrote {df.height} embeddings ({stats.dim}-d) to {out}\n"
        f"  walks: {stats.n_walks} (gen {stats.walk_seconds}s)\n"
        f"  train: {stats.train_seconds}s (workers={stats.workers}, "
        f"deterministic={stats.deterministic})\n"
        f"  total: {stats.total_seconds}s\n"
    )
    return 0
