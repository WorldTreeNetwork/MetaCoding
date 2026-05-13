"""Load MetaCoding's exported graph into NetworkX.

The TypeScript side (``metacoding export <out-dir>``) writes
``nodes.jsonl`` + ``edges.jsonl`` so this loader can avoid linking
against ``@ladybugdb/core``. This is the **fallback path**; the
direct-Kùzu approach failed because ladybugdb 0.15.4 and mainline kuzu
0.11.3 use incompatible storage formats (verified 2026-05-11).

Single public entry: :func:`load_graph`. Returns a NetworkX
``MultiDiGraph`` with every Symbol as a node (id = ``Symbol.id``) and
every typed edge as an edge keyed by ``kind``. The graph is
intentionally NOT a ``DiGraph`` — typed-subgraph mining (gSpan and
friends) and most motif discovery techniques expect multiple
parallel edges between the same node pair when their ``kind`` differs.

For ML-heavy paths (PyG / DGL) we'll add a sibling ``to_pyg`` /
``to_dgl`` conversion in a later issue. The NetworkX representation is
the lingua franca.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Iterable, Iterator

import networkx as nx
import polars as pl

EDGE_KINDS: tuple[str, ...] = (
    "CALLS",
    "REFERENCES",
    "EXTENDS",
    "IMPLEMENTS",
    "OVERRIDES",
    "INJECTS",
    "CONTAINS",
    "IMPORTS",
    "ANNOTATES",
    "TYPE_OF",
)


@dataclass(slots=True, frozen=True)
class GraphPaths:
    """Resolved locations of the JSONL artifacts."""

    nodes: Path
    edges: Path
    manifest: Path | None


def resolve_paths(data_dir: str | Path) -> GraphPaths:
    """Locate ``nodes.jsonl`` + ``edges.jsonl`` given a MetaCoding data dir.

    Convention: the TS exporter writes to ``<data_dir>/ctkr/export/`` when
    given the project's ``.metacoding/`` as the data dir. If those don't
    exist there, fall back to treating ``data_dir`` itself as the export
    directory (this is what tests do).
    """
    p = Path(data_dir).expanduser().resolve()
    primary = p / "ctkr" / "export"
    candidates = [primary, p]
    for cand in candidates:
        n = cand / "nodes.jsonl"
        e = cand / "edges.jsonl"
        if n.exists() and e.exists():
            m = cand / "manifest.json"
            return GraphPaths(nodes=n, edges=e, manifest=m if m.exists() else None)
    raise FileNotFoundError(
        f"Could not find nodes.jsonl + edges.jsonl in {primary} or {p}. "
        f"Run `metacoding export <out-dir> --data-dir {p}` first."
    )


def load_graph(
    data_dir: str | Path,
    *,
    repo_filter: Iterable[str] | None = None,
    edge_kind_filter: Iterable[str] | None = None,
) -> nx.MultiDiGraph:
    """Load the exported MetaCoding graph into a NetworkX ``MultiDiGraph``.

    Parameters
    ----------
    data_dir
        Either the ``.metacoding/`` directory (in which case we look
        under ``ctkr/export/``) or a directory containing
        ``nodes.jsonl`` + ``edges.jsonl`` directly.
    repo_filter
        If given, drop any node whose ``repo`` is not in this set
        before adding edges. Edges to dropped nodes are also dropped.
    edge_kind_filter
        If given, only add edges whose ``kind`` is in this set.

    Returns
    -------
    nx.MultiDiGraph
        Nodes carry every column from ``Symbol`` as an attribute
        (``repo``, ``qualified_name``, ``file``, ``line``, ``kind``,
        ``language``, ``signature``, ``visibility``, ``branch``,
        ``source`` …). Edges carry ``kind`` and (where applicable)
        ``count``.
    """
    paths = resolve_paths(data_dir)
    repo_set: set[str] | None = set(repo_filter) if repo_filter else None
    edge_set: set[str] | None = set(edge_kind_filter) if edge_kind_filter else None

    g = nx.MultiDiGraph()

    # Nodes — polars handles 300k rows comfortably in <1s. We iterate to
    # NetworkX rather than building a DataFrame attribute map because the
    # downstream miners want native dict access.
    n_added = 0
    for rec in _iter_jsonl(paths.nodes):
        if repo_set is not None and rec.get("repo") not in repo_set:
            continue
        node_id = rec["id"]
        # `id` becomes the node key; keep the rest as attributes.
        attrs = {k: v for k, v in rec.items() if k != "id"}
        # Also keep `file_path` as an explicit alias for `file` — readability
        # in downstream code; the TS source's column is `file`.
        if "file" in attrs and "file_path" not in attrs:
            attrs["file_path"] = attrs["file"]
        g.add_node(node_id, **attrs)
        n_added += 1

    # Edges — drop any whose endpoints aren't in g (e.g. because of repo
    # filtering). Use kind as the edge key so parallel edges of different
    # kinds coexist.
    e_added = 0
    for rec in _iter_jsonl(paths.edges):
        if edge_set is not None and rec.get("kind") not in edge_set:
            continue
        src = rec["src_id"]
        dst = rec["dst_id"]
        if not (g.has_node(src) and g.has_node(dst)):
            continue
        kind = rec["kind"]
        attrs: dict[str, Any] = {"kind": kind}
        if "count" in rec and rec["count"] is not None:
            attrs["count"] = rec["count"]
        g.add_edge(src, dst, key=kind, **attrs)
        e_added += 1

    return g


def graph_stats(g: nx.MultiDiGraph) -> dict[str, Any]:
    """Summarize a loaded graph. Handy for smoke-testing and CLI output."""
    edge_kinds: dict[str, int] = {}
    for _, _, k in g.edges(keys=True):
        edge_kinds[k] = edge_kinds.get(k, 0) + 1
    repos: dict[str, int] = {}
    for _, d in g.nodes(data=True):
        r = d.get("repo")
        if r:
            repos[r] = repos.get(r, 0) + 1
    return {
        "n_nodes": g.number_of_nodes(),
        "n_edges": g.number_of_edges(),
        "edge_kinds": edge_kinds,
        "n_repos": len(repos),
        "repos": repos,
    }


def search_tokens(
    sqlite_path: str | Path,
    query: str,
    *,
    limit: int = 50,
    repo: str | None = None,
) -> pl.DataFrame:
    """Query MetaCoding's ``tokens.fts.sqlite`` directly.

    The FTS index is too large (~2.7 GB) to fold into NetworkX, so we
    expose it as a separate read-only call. Returns a polars DataFrame
    with the standard token columns; empty DataFrame if no rows match.
    """
    import sqlite3  # stdlib; no extra dep

    p = Path(sqlite_path).expanduser().resolve()
    if not p.exists():
        raise FileNotFoundError(f"FTS index not found: {p}")

    conn = sqlite3.connect(f"file:{p}?mode=ro", uri=True)
    try:
        if repo is not None:
            cur = conn.execute(
                "SELECT text, kind, repo, file, line, col, symbol_id "
                "FROM tokens WHERE tokens MATCH ? AND repo = ? LIMIT ?",
                (query, repo, limit),
            )
        else:
            cur = conn.execute(
                "SELECT text, kind, repo, file, line, col, symbol_id "
                "FROM tokens WHERE tokens MATCH ? LIMIT ?",
                (query, limit),
            )
        cols = [d[0] for d in cur.description]
        rows = cur.fetchall()
    finally:
        conn.close()

    if not rows:
        return pl.DataFrame(schema={c: pl.Utf8 for c in cols})
    return pl.DataFrame(rows, schema=cols, orient="row")


# ----- internals -----


def _iter_jsonl(path: Path) -> Iterator[dict[str, Any]]:
    """Yield decoded JSON objects line-by-line from a JSONL file."""
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            yield json.loads(line)


__all__ = [
    "EDGE_KINDS",
    "GraphPaths",
    "load_graph",
    "resolve_paths",
    "graph_stats",
    "search_tokens",
]
