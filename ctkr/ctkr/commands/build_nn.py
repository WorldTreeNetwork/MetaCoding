"""``ctkr build-nn`` — build the cross-repo HNSW nearest-neighbor index.

Reads ``embeddings.parquet`` and writes ``nn_index/`` (binary + sidecars)
under ``<data_dir>/ctkr/``.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "build-nn",
        help="Build the cross-repo nearest-neighbor index from embeddings.parquet.",
        description=(
            "HNSW (cosine) index over the embeddings produced by `ctkr embed`. "
            "Writes nn_index/ under <data_dir>/ctkr/."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--embeddings",
        default=None,
        help="Path to embeddings.parquet (default: <data_dir>/ctkr/embeddings.parquet).",
    )
    p.add_argument("--M", type=int, default=32, help="HNSW graph degree.")
    p.add_argument("--ef-construction", type=int, default=200)
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    import polars as pl

    from ctkr.nn_index import NNIndex

    data_dir = resolve_data_dir(args.data_dir)
    embeddings_path = (
        Path(args.embeddings).expanduser().resolve()
        if args.embeddings
        else data_dir / "ctkr" / "embeddings.parquet"
    )
    if not embeddings_path.exists():
        sys.stderr.write(
            f"embeddings.parquet not found at {embeddings_path}.\n"
            f"  Run `ctkr embed` first.\n"
        )
        return 2

    sys.stderr.write(f"loading embeddings from {embeddings_path}...\n")
    df = pl.read_parquet(embeddings_path)
    sys.stderr.write(f"  {df.height} vectors, dim={len(df['vec'][0])}\n")

    out_dir = data_dir / "ctkr" / "nn_index"
    sys.stderr.write(
        f"building HNSW index (M={args.M}, ef_construction={args.ef_construction})...\n"
    )
    try:
        # Pass the relative path so the sidecar stays portable when
        # .metacoding/ moves between machines.
        rel = embeddings_path.relative_to(out_dir.parent)
    except ValueError:
        rel = embeddings_path
    _, stats = NNIndex.build(
        df,
        out_dir=out_dir,
        M=args.M,
        ef_construction=args.ef_construction,
        embeddings_source_rel=str(rel),
    )
    sys.stderr.write(
        f"  wrote nn_index/ ({stats.backend}, dim={stats.dim}, "
        f"{stats.n_vectors} vectors, {stats.seconds}s)\n"
    )
    return 0
