"""``ctkr motifs`` — 2-hop typed-edge chain frequency.

Layer-1 *fallback* until :issue:`Orchestrators-k97` (gSpan-style frequent
typed-subgraph mining) lands. Counts ordered pairs ``(kind1, kind2)`` for
every length-2 directed path ``a -kind1→ b -kind2→ c`` in the loaded
graph. Cross-repo coverage per pattern is also reported because
cross-repo support is the CTKR signal that matters most.

This is *not* a substitute for real motif mining — it doesn't discover
larger subgraphs, doesn't account for node typing, and treats every
2-hop chain as a single pattern regardless of context. But on the
Orchestrators corpus it surfaces a handy first cut at which typed
chains are actually common.
"""

from __future__ import annotations

import argparse
from collections import defaultdict

from ctkr.commands._common import add_common_flags, emit, resolve_data_dir
from ctkr.graph_loader import graph_stats, load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "motifs",
        help="Top-K most frequent typed-edge 2-hop chains in the corpus.",
        description=(
            "Layer-1 fallback motif report. Counts (kind_a, kind_b) chains "
            "across the loaded graph and reports cross-repo coverage."
        ),
    )
    add_common_flags(p)
    p.add_argument("--top", type=int, default=20)
    p.add_argument(
        "--repo",
        default=None,
        help="Optional repo filter — only count chains anchored in this repo.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    g = load_graph(data_dir)

    counts: dict[tuple[str, str], int] = defaultdict(int)
    coverage: dict[tuple[str, str], set[str]] = defaultdict(set)

    repo_filter = args.repo
    for a, b, k1 in g.out_edges(keys=True):
        a_repo = g.nodes[a].get("repo")
        if repo_filter is not None and a_repo != repo_filter:
            continue
        for _, c, k2 in g.out_edges(b, keys=True):
            key = (k1, k2)
            counts[key] += 1
            if a_repo is not None:
                coverage[key].add(a_repo)

    if not counts:
        print("no edge data — graph is empty or has no out-edges in the requested filter.")
        return 0

    ranked = sorted(counts.items(), key=lambda kv: kv[1], reverse=True)[: args.top]

    rows = [
        {
            "motif": f"{k1} → {k2}",
            "kind_a": k1,
            "kind_b": k2,
            "count": n,
            "repo_coverage": len(coverage[(k1, k2)]),
            "repos": sorted(coverage[(k1, k2)])[:5],  # top 5 alphabetically
        }
        for (k1, k2), n in ranked
    ]

    if not args.as_json:
        stats = graph_stats(g)
        print(
            f"# graph: {stats['n_nodes']} nodes, {stats['n_edges']} edges  "
            f"# distinct chains: {len(counts)}"
        )

    emit(
        rows,
        as_json=args.as_json,
        columns=("motif", "count", "repo_coverage", "repos"),
    )
    return 0
