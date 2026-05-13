"""Node embeddings for the MetaCoding code graph (Orchestrators-7u7).

v1 implementation = **DeepWalk-equivalent uniform random walks + gensim
Word2Vec**. Hyperparameters follow the issue spec (dim=128, walks=20,
walk_length=40). The walks are uniform-random over neighbors because
``p=1, q=1`` collapses node2vec into DeepWalk; a future iteration can
add edge-type-aware biased walks if v1 results look weak.

Why not the ``node2vec`` PyPI package
-------------------------------------

The standard ``node2vec`` library materializes an in-memory transition
matrix of size O(|N|²). For our ~552k-node corpus that's well over a
trillion entries — guaranteed OOM. Hand-rolling the walk generator
keeps memory at O(|N|), and the walks are produced as a generator so
``gensim.Word2Vec`` can stream them.

Determinism
-----------

Every random source seeds explicitly from ``seed``. ``numpy.random``
is *not* used; we rely on stdlib ``random.Random`` so the same seed
produces byte-identical walks across machines that share a CPython
version. gensim's Word2Vec gets the same ``seed`` and is run with
``workers=1`` in deterministic mode (multi-threaded Word2Vec is
nondeterministic regardless of seed). When determinism doesn't matter,
crank ``workers`` for speed.
"""

from __future__ import annotations

import logging
import random
import time
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING, Any

import networkx as nx
import polars as pl

from ctkr.schema import EMBEDDINGS_COLUMNS, SCHEMA_VERSION

if TYPE_CHECKING:  # pragma: no cover
    from gensim.models import Word2Vec  # type: ignore[import-untyped]

logger = logging.getLogger("ctkr.embed")


DEFAULT_DIM = 128
DEFAULT_WALKS = 20
DEFAULT_WALK_LENGTH = 40
DEFAULT_WINDOW = 5
DEFAULT_MIN_COUNT = 1
DEFAULT_EPOCHS = 5
DEFAULT_SEED = 42


@dataclass(slots=True, frozen=True)
class EmbedStats:
    """Telemetry for one ``compute_embeddings`` run."""

    n_nodes: int
    n_walks: int
    walk_length: int
    dim: int
    epochs: int
    workers: int
    deterministic: bool
    walk_seconds: float
    train_seconds: float
    total_seconds: float


def compute_embeddings(
    g: nx.MultiDiGraph,
    *,
    dim: int = DEFAULT_DIM,
    num_walks: int = DEFAULT_WALKS,
    walk_length: int = DEFAULT_WALK_LENGTH,
    window: int = DEFAULT_WINDOW,
    min_count: int = DEFAULT_MIN_COUNT,
    epochs: int = DEFAULT_EPOCHS,
    seed: int = DEFAULT_SEED,
    workers: int = 1,
    node_filter: Iterable[str] | None = None,
    name_bridges: bool = True,
    name_bridges_cap: int = 3,
) -> tuple[pl.DataFrame, EmbedStats]:
    """Run DeepWalk on the graph and return embeddings as a DataFrame.

    Parameters
    ----------
    g
        Loaded MultiDiGraph from ``ctkr.graph_loader.load_graph``.
    dim
        Embedding dimension. Default 128 per the issue spec.
    num_walks, walk_length, window, min_count, epochs
        Word2Vec / random-walk hyperparameters.
    seed
        Seed for both walk generation and Word2Vec training.
    workers
        Number of Word2Vec worker threads. Note: ``workers > 1`` makes
        training nondeterministic per gensim's docs.
    node_filter
        Optional iterable of node IDs — only these nodes seed walks and
        appear in the output. The full graph is still used for
        neighbor sampling so embeddings reflect global topology.
    name_bridges
        When True, augment the graph with synthetic ``NAME_SHARED`` edges
        between symbols in *different* repos that share a ``short_name``.
        This is what makes cross-repo similarity work — without it,
        each repo's call graph is an island and walks never bridge
        repos. Bridges are scoped to nodes in ``node_filter`` (or all
        nodes if no filter is set) so we don't bloat memory by linking
        millions of parameters that share `self` / `cls`.
    name_bridges_cap
        Per-(short_name, repo) cap on outgoing bridge edges. Keeps a
        common name like ``Tool`` (across 40 repos) from generating
        an O(N²) clique.
    """
    from gensim.models import Word2Vec  # imported lazily — heavy

    deterministic = workers == 1
    if not deterministic:
        logger.warning("workers=%d > 1; Word2Vec training is nondeterministic", workers)

    start = time.perf_counter()

    nodes_for_walks: list[str]
    if node_filter is None:
        nodes_for_walks = list(g.nodes())
    else:
        nodes_for_walks = [n for n in node_filter if g.has_node(n)]

    if name_bridges:
        n_bridges = _inject_name_bridges(
            g, nodes_for_walks, cap=name_bridges_cap, rng=random.Random(seed + 1)
        )
        logger.info("injected %d NAME_SHARED bridge edges", n_bridges)

    rng = random.Random(seed)
    walks = list(_generate_walks(g, nodes_for_walks, num_walks, walk_length, rng))
    walk_end = time.perf_counter()
    walk_seconds = walk_end - start

    model = Word2Vec(
        sentences=walks,
        vector_size=dim,
        window=window,
        min_count=min_count,
        sg=1,  # skip-gram (node2vec convention)
        workers=workers,
        seed=seed,
        epochs=epochs,
    )

    rows = _embeddings_to_rows(model, g, nodes_for_walks)
    df = pl.DataFrame(rows).select(EMBEDDINGS_COLUMNS)

    train_end = time.perf_counter()
    train_seconds = train_end - walk_end

    stats = EmbedStats(
        n_nodes=len(nodes_for_walks),
        n_walks=len(walks),
        walk_length=walk_length,
        dim=dim,
        epochs=epochs,
        workers=workers,
        deterministic=deterministic,
        walk_seconds=round(walk_seconds, 3),
        train_seconds=round(train_seconds, 3),
        total_seconds=round(train_end - start, 3),
    )
    return df, stats


def write_embeddings(df: pl.DataFrame, out_path: str | Path) -> None:
    """Pin column order, ensure float32 vectors, and write to parquet."""
    out_path = Path(out_path).expanduser().resolve()
    out_path.parent.mkdir(parents=True, exist_ok=True)
    df = df.select(EMBEDDINGS_COLUMNS)
    df = df.with_columns(pl.col("vec").cast(pl.List(pl.Float32)))
    df.write_parquet(out_path)


# ----- internals -----


def _inject_name_bridges(
    g: nx.MultiDiGraph,
    scope: list[str],
    *,
    cap: int,
    rng: random.Random,
    edge_key: str = "NAME_SHARED",
) -> int:
    """Add synthetic edges between cross-repo nodes sharing a ``short_name``.

    Strategy: bucket ``scope`` by short_name; for each bucket spanning ≥2
    repos, link each (short_name, repo) cluster to ``cap`` representatives
    in each other repo. Bidirectional so walks can traverse either way.

    Returns the number of edges added.
    """
    # Bucket by short_name → repo → [node ids]
    buckets: dict[str, dict[str, list[str]]] = {}
    for n in scope:
        d = g.nodes[n]
        sn = d.get("short_name") or ""
        repo = d.get("repo") or ""
        if not sn or not repo:
            continue
        # Skip overly generic identifiers — they don't carry signal.
        if len(sn) <= 2 or sn.lower() in _GENERIC_NAMES:
            continue
        buckets.setdefault(sn, {}).setdefault(repo, []).append(n)

    added = 0
    for sn, by_repo in buckets.items():
        if len(by_repo) < 2:
            continue
        repos = list(by_repo.keys())
        for src_repo in repos:
            src_nodes = by_repo[src_repo]
            # Pick one representative per source repo, deterministically.
            src = rng.choice(src_nodes)
            for dst_repo in repos:
                if dst_repo == src_repo:
                    continue
                dst_pool = by_repo[dst_repo]
                sample = rng.sample(dst_pool, k=min(cap, len(dst_pool)))
                for dst in sample:
                    # MultiDiGraph allows parallel edges with different keys.
                    g.add_edge(src, dst, key=edge_key, kind=edge_key, short_name=sn)
                    added += 1
    return added


_GENERIC_NAMES: frozenset[str] = frozenset(
    {
        "self",
        "cls",
        "this",
        "args",
        "kwargs",
        "_",
        "__init__",
        "__call__",
        "__str__",
        "__repr__",
        "__init__.py",
        "main",
        "run",
        "init",
        "constructor",
        "render",
        "default",
        "value",
        "data",
        "item",
        "name",
        "id",
        "type",
        "kind",
        "key",
        "config",
        "options",
        "params",
        "result",
        "ok",
        "true",
        "false",
        "null",
        "none",
    }
)


def _generate_walks(
    g: nx.MultiDiGraph,
    seed_nodes: list[str],
    num_walks: int,
    walk_length: int,
    rng: random.Random,
) -> Iterator[list[str]]:
    """Yield ``num_walks`` uniform-random walks of length ``walk_length``
    from each node in ``seed_nodes``.

    Walks are undirected — we sample from in-edges *and* out-edges
    pooled together. This matches how DeepWalk treats the graph for
    representation learning, and it lets containing-symbols and
    contained-symbols both appear as context for each other.
    """
    # Cache a list of neighbors per node so we don't rebuild it on every
    # walk step. NetworkX neighbor lookup is fast but still measurable
    # at ~10⁸ touches.
    neighbor_cache: dict[str, list[str]] = {}

    def neighbors(n: str) -> list[str]:
        cached = neighbor_cache.get(n)
        if cached is not None:
            return cached
        # Use a dict to dedupe — a node might have both an in and out edge
        # to the same partner; we don't want it twice.
        s: dict[str, None] = {}
        for _, dst in g.out_edges(n):
            s[dst] = None
        for src, _ in g.in_edges(n):
            s[src] = None
        out = list(s.keys())
        neighbor_cache[n] = out
        return out

    for start in seed_nodes:
        for _ in range(num_walks):
            walk = [start]
            cur = start
            for _ in range(walk_length - 1):
                nb = neighbors(cur)
                if not nb:
                    break
                cur = rng.choice(nb)
                walk.append(cur)
            yield walk


def _embeddings_to_rows(
    model: Word2Vec,
    g: nx.MultiDiGraph,
    seed_nodes: list[str],
) -> list[dict[str, Any]]:
    """Convert the trained model's vectors into schema-compliant rows."""
    rows: list[dict[str, Any]] = []
    vocab = model.wv.key_to_index
    for n in seed_nodes:
        if n not in vocab:
            # Some nodes may not appear in any walk (isolates with empty
            # neighbor set and no incoming edges). Skip them; downstream
            # code already tolerates missing rows via outer joins.
            continue
        d = g.nodes[n]
        vec = model.wv[n].tolist()
        rows.append(
            {
                "symbol_id": n,
                "repo": d.get("repo", "") or "",
                "qualified_name": d.get("qualified_name", "") or "",
                "vec": vec,
                "schema_version": SCHEMA_VERSION,
            }
        )
    return rows


__all__ = [
    "DEFAULT_DIM",
    "DEFAULT_WALKS",
    "DEFAULT_WALK_LENGTH",
    "DEFAULT_SEED",
    "EmbedStats",
    "compute_embeddings",
    "write_embeddings",
]
