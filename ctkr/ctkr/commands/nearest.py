"""``ctkr nearest`` — find structurally similar symbols.

Prefers the **HNSW embedding index** when ``<data_dir>/ctkr/nn_index/``
is present (built by ``ctkr build-nn``). Falls back to typed-neighborhood
Jaccard on the raw graph when no index is available — useful for
ad-hoc exploration before the L1 embedding lane has been run.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import networkx as nx

from ctkr.commands._common import add_common_flags, emit, resolve_data_dir
from ctkr.graph_loader import graph_stats, load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "nearest",
        help="Find symbols similar to <symbol> (HNSW embeddings, or graph fallback).",
        description=(
            "Use the HNSW index at <data_dir>/ctkr/nn_index/ when present; "
            "fall back to typed-neighborhood Jaccard otherwise."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "symbol",
        help=(
            "Target symbol — match by qualified_name (default) or by id. "
            "Substring match against qualified_name is supported."
        ),
    )
    p.add_argument("--by", choices=("qualified_name", "id"), default="qualified_name")
    p.add_argument("--limit", "-k", type=int, default=20)
    p.add_argument(
        "--repo",
        default=None,
        help="Optional repo filter — only consider candidates in this repo.",
    )
    p.add_argument(
        "--cross-repo",
        action="store_true",
        help="Drop same-repo results (embedding mode only).",
    )
    p.add_argument(
        "--mode",
        choices=("auto", "embedding", "graph"),
        default="auto",
        help="Auto picks embedding when nn_index exists, else graph Jaccard.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)

    # Pick mode — embedding by default when the index exists.
    nn_dir = data_dir / "ctkr" / "nn_index"
    use_embedding = (args.mode == "embedding") or (
        args.mode == "auto" and (nn_dir / "nn_index.bin").exists()
    )
    if args.mode == "embedding" and not (nn_dir / "nn_index.bin").exists():
        sys.stderr.write(
            f"--mode=embedding requested but no index at {nn_dir}.\n"
            f"  Run `ctkr build-nn` first.\n"
        )
        return 2

    if use_embedding:
        return _run_embedding_mode(args, data_dir, nn_dir)
    return _run_graph_mode(args, data_dir)


def _run_embedding_mode(
    args: argparse.Namespace, data_dir: Path, nn_dir: Path
) -> int:
    from ctkr.nn_index import NNIndex

    index = NNIndex.load(nn_dir)
    # Resolve the target — for embedding mode, the symbol_id must be in
    # the index. Allow qualified_name lookup via the labels sidecar.
    target_label_row = _resolve_in_index(index, args.symbol, by=args.by)
    if target_label_row is None:
        sys.stderr.write(f"no indexed symbol matched {args.symbol!r} ({args.by})\n")
        return 1

    hits = index.query_by_id(
        target_label_row["symbol_id"],
        k=args.limit,
        cross_repo_only=args.cross_repo,
        repo_filter=[args.repo] if args.repo else None,
    )
    rows = [
        {
            "symbol_id": h.symbol_id,
            "repo": h.repo,
            "qualified_name": h.qualified_name,
            "similarity": h.similarity,
        }
        for h in hits
    ]
    if not args.as_json:
        sys.stdout.write(
            f"# target: {target_label_row['qualified_name']} ({target_label_row['repo']})  "
            f"# mode: embedding (HNSW, dim={index.meta.embedding_dim})\n"
        )
    emit(
        rows,
        as_json=args.as_json,
        columns=("symbol_id", "repo", "qualified_name", "similarity"),
    )
    return 0


def _resolve_in_index(index: "NNIndex", q: str, *, by: str) -> dict | None:  # type: ignore[name-defined]
    """Find a row in the index's labels sidecar."""
    df = index._labels  # noqa: SLF001 — internal but stable
    if by == "id":
        match = df.filter(df["symbol_id"] == q)
        return match.row(0, named=True) if match.height else None
    # Substring match on qualified_name, prefer exact.
    exact = df.filter(df["qualified_name"] == q)
    if exact.height:
        return exact.row(0, named=True)
    sub = df.filter(df["qualified_name"].str.contains(q, literal=True))
    return sub.row(0, named=True) if sub.height else None


def _run_graph_mode(args: argparse.Namespace, data_dir: Path) -> int:
    g = load_graph(data_dir)

    target_id = _resolve_target(g, args.symbol, by=args.by)
    if target_id is None:
        print(f"no symbol matched {args.symbol!r} ({args.by})")
        return 1

    target_node = g.nodes[target_id]
    target_nbrs = _typed_neighborhood(g, target_id)
    if not target_nbrs:
        print(f"symbol {target_id} has no typed neighbors; nothing to compare against.")
        return 0

    # 2-hop candidate set — symbols sharing at least one typed neighbor.
    candidates: set[str] = set()
    for _kind, nbr in target_nbrs:
        candidates.update(g.predecessors(nbr))
        candidates.update(g.successors(nbr))
    candidates.discard(target_id)

    if args.repo:
        candidates = {c for c in candidates if g.nodes[c].get("repo") == args.repo}

    scored: list[tuple[str, float]] = []
    for c in candidates:
        c_nbrs = _typed_neighborhood(g, c)
        if not c_nbrs:
            continue
        inter = len(target_nbrs & c_nbrs)
        union = len(target_nbrs | c_nbrs)
        if union == 0:
            continue
        scored.append((c, inter / union))

    scored.sort(key=lambda t: t[1], reverse=True)
    top = scored[: args.limit]

    rows = [
        {
            "symbol_id": s,
            "repo": g.nodes[s].get("repo", ""),
            "qualified_name": g.nodes[s].get("qualified_name", ""),
            "kind": g.nodes[s].get("kind", ""),
            "similarity": score,
        }
        for s, score in top
    ]

    if not args.as_json:
        stats = graph_stats(g)
        target_qn = target_node.get("qualified_name", target_id)
        target_repo = target_node.get("repo", "")
        print(
            f"# target: {target_qn} ({target_repo})  "
            f"# graph: {stats['n_nodes']} nodes, {stats['n_edges']} edges  "
            f"# candidates scored: {len(scored)}"
        )

    emit(
        rows,
        as_json=args.as_json,
        columns=("symbol_id", "repo", "qualified_name", "kind", "similarity"),
    )
    return 0


def _resolve_target(g: nx.MultiDiGraph, q: str, *, by: str) -> str | None:
    """Find a node by id or by (substring) qualified_name."""
    if by == "id":
        return q if g.has_node(q) else None
    # Prefer exact match, then substring.
    exact: str | None = None
    sub: str | None = None
    for nid, d in g.nodes(data=True):
        qn = d.get("qualified_name") or ""
        if qn == q:
            exact = nid
            break
        if sub is None and q in qn:
            sub = nid
    return exact or sub


def _typed_neighborhood(g: nx.MultiDiGraph, n: str) -> frozenset[tuple[str, str]]:
    """Set of (edge_kind, neighbor_id) tuples — symmetric over direction.

    Direction is *folded in* on the kind via a ``↑``/``↓`` prefix so
    in-edges and out-edges of the same kind count as distinct dimensions.
    """
    nb: set[tuple[str, str]] = set()
    for _, dst, k in g.out_edges(n, keys=True):
        nb.add((f"↓{k}", dst))
    for src, _, k in g.in_edges(n, keys=True):
        nb.add((f"↑{k}", src))
    return frozenset(nb)
