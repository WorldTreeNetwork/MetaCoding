"""Centrality + per-repo community decomposition (Orchestrators-2an).

Pure-NetworkX. Produces two artifacts under ``.metacoding/ctkr/``:

* ``centrality.parquet`` — pagerank + (sampled) betweenness + eigenvector
  centrality per symbol, computed on the **global** corpus graph.
* ``spectral_clusters.parquet`` — per-repo community assignments via
  Louvain modularity optimization, treating each repo's induced
  subgraph as undirected.

A note on naming
----------------

The issue title says "spectral and centrality." We use Louvain
modularity (``networkx.community.louvain_communities``) rather than
literal spectral clustering for the per-repo decomposition because:

* sklearn's ``SpectralClustering`` would add a heavy dependency for a
  P3 issue.
* Louvain is the standard modularity-based community detector — it
  recovers "modules-as-emergent" cleanly and runs in O(M log N).
* The two methods correlate strongly on connected, real-world graphs;
  swapping the algorithm later is one ``import`` change.

If a future iteration needs literal eigenvector-of-the-Laplacian
spectral clustering, ``nx.algebraic_connectivity`` and
``nx.fiedler_vector`` are the entry points.
"""

from __future__ import annotations

import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.schema import (
    CENTRALITY_COLUMNS,
    SCHEMA_VERSION,
    SPECTRAL_CLUSTERS_COLUMNS,
)

logger = logging.getLogger("ctkr.centrality")


DEFAULT_BETWEENNESS_K = 1000  # sample size for approximate betweenness
DEFAULT_EIGENVECTOR_MAX_ITER = 500
DEFAULT_EIGENVECTOR_TOL = 1e-4
DEFAULT_LOUVAIN_SEED = 42


@dataclass(slots=True, frozen=True)
class CentralityStats:
    n_nodes: int
    pagerank_seconds: float
    betweenness_seconds: float
    betweenness_k: int
    eigenvector_seconds: float
    eigenvector_converged: bool
    n_articulation: int = 0
    articulation_seconds: float = 0.0


@dataclass(slots=True, frozen=True)
class ClusterStats:
    n_repos: int
    n_clusters_total: int
    largest_repo: str
    largest_repo_nodes: int
    largest_repo_clusters: int
    total_seconds: float


# ----- centrality -----


def compute_centrality(
    g: nx.MultiDiGraph,
    *,
    betweenness_k: int = DEFAULT_BETWEENNESS_K,
    eigenvector_max_iter: int = DEFAULT_EIGENVECTOR_MAX_ITER,
    eigenvector_tol: float = DEFAULT_EIGENVECTOR_TOL,
    seed: int = DEFAULT_LOUVAIN_SEED,
) -> tuple[pl.DataFrame, CentralityStats]:
    """Compute pagerank + betweenness + eigenvector centrality globally.

    Returns one row per node, sorted by ``symbol_id`` for stability.
    Scores are normalized within the input graph (NetworkX's defaults
    already produce normalized output for these three measures).
    """
    # NetworkX centrality wants a simple graph or DiGraph — convert.
    # We collapse parallel typed edges to a single weighted edge,
    # weight = number of underlying typed edges. This preserves the
    # intuitive "more types of relationship = stronger tie" notion.
    h = _collapse_multidigraph(g)

    # PageRank — fast, scales to millions of edges. Always converges.
    t0 = time.perf_counter()
    pr = nx.pagerank(h, weight="weight")
    t1 = time.perf_counter()

    # Betweenness — exact is O(NM); we sample. NetworkX returns
    # normalized values in [0, 1] when normalized=True (the default).
    k = min(betweenness_k, h.number_of_nodes())
    bc = nx.betweenness_centrality(h, k=k, seed=seed, normalized=True)
    t2 = time.perf_counter()

    # Eigenvector — power iteration. May fail on disconnected graphs;
    # we catch and fall back to zeros so the artifact stays well-formed.
    converged = True
    try:
        ec = nx.eigenvector_centrality(
            h, max_iter=eigenvector_max_iter, tol=eigenvector_tol, weight="weight"
        )
    except nx.PowerIterationFailedConvergence:
        logger.warning(
            "eigenvector_centrality did not converge in %d iters; emitting zeros",
            eigenvector_max_iter,
        )
        ec = {n: 0.0 for n in h.nodes()}
        converged = False
    t3 = time.perf_counter()

    # Articulation points (cut vertices) — the "real seam" signal from ctkr.md
    # L1 §4, closing the subsystem-extraction §2.1 gap. Defined on the
    # UNDIRECTED collapse: a node whose removal increases the component count of
    # its connected component. NetworkX computes this per component in one pass.
    # Deterministic (no sampling), so it never perturbs byte-identical re-runs.
    u = h.to_undirected(as_view=False)
    articulation: set[str] = set(nx.articulation_points(u)) if u.number_of_edges() else set()
    t4 = time.perf_counter()

    rows: list[dict[str, object]] = []
    for n in sorted(h.nodes()):
        d = g.nodes[n]
        rows.append(
            {
                "symbol_id": n,
                "repo": d.get("repo", "") or "",
                "qualified_name": d.get("qualified_name", "") or "",
                "pagerank": float(pr.get(n, 0.0)),
                "betweenness": float(bc.get(n, 0.0)),
                "eigenvector": float(ec.get(n, 0.0)),
                "articulation": n in articulation,
                "schema_version": SCHEMA_VERSION,
            }
        )

    df = pl.DataFrame(rows).select(CENTRALITY_COLUMNS)
    stats = CentralityStats(
        n_nodes=h.number_of_nodes(),
        pagerank_seconds=round(t1 - t0, 3),
        betweenness_seconds=round(t2 - t1, 3),
        betweenness_k=k,
        eigenvector_seconds=round(t3 - t2, 3),
        eigenvector_converged=converged,
        n_articulation=len(articulation),
        articulation_seconds=round(t4 - t3, 3),
    )
    return df, stats


# ----- clustering -----


def compute_clusters(
    g: nx.MultiDiGraph,
    *,
    seed: int = DEFAULT_LOUVAIN_SEED,
    min_repo_size: int = 4,
    repos: Iterable[str] | None = None,
) -> tuple[pl.DataFrame, ClusterStats]:
    """Run Louvain modularity per repo.

    Parameters
    ----------
    g
        Loaded MultiDiGraph.
    seed
        Forwarded to Louvain for determinism.
    min_repo_size
        Skip repos with fewer than this many nodes — modularity isn't
        meaningful on near-empty subgraphs.
    repos
        Restrict to a specific set of repos. ``None`` runs everywhere.
    """
    start = time.perf_counter()
    rows: list[dict[str, object]] = []
    largest_repo = ""
    largest_repo_nodes = 0
    largest_repo_clusters = 0
    n_clusters_total = 0

    # Bucket node IDs by repo.
    by_repo: dict[str, list[str]] = {}
    for n, d in g.nodes(data=True):
        repo = d.get("repo")
        if repo is None:
            continue
        by_repo.setdefault(repo, []).append(n)

    if repos is not None:
        wanted = set(repos)
        by_repo = {k: v for k, v in by_repo.items() if k in wanted}

    repos_with_clusters = 0
    for repo, node_ids in by_repo.items():
        if len(node_ids) < min_repo_size:
            continue
        sub = g.subgraph(node_ids).copy()
        u = _collapse_multidigraph(sub).to_undirected()
        if u.number_of_edges() == 0:
            continue
        # Louvain returns a list of sets.
        communities = nx.community.louvain_communities(u, seed=seed)
        # Sort communities by size (descending) so cluster_id=0 is largest.
        communities = sorted(communities, key=len, reverse=True)
        repo_cluster_count = len(communities)
        n_clusters_total += repo_cluster_count
        repos_with_clusters += 1
        if len(node_ids) > largest_repo_nodes:
            largest_repo = repo
            largest_repo_nodes = len(node_ids)
            largest_repo_clusters = repo_cluster_count
        for cid, comm in enumerate(communities):
            csize = len(comm)
            for n in comm:
                d = g.nodes[n]
                rows.append(
                    {
                        "symbol_id": n,
                        "repo": repo,
                        "qualified_name": d.get("qualified_name", "") or "",
                        "cluster_id": cid,
                        "cluster_size": csize,
                        "schema_version": SCHEMA_VERSION,
                    }
                )

    df = pl.DataFrame(rows).select(SPECTRAL_CLUSTERS_COLUMNS)
    stats = ClusterStats(
        n_repos=repos_with_clusters,
        n_clusters_total=n_clusters_total,
        largest_repo=largest_repo,
        largest_repo_nodes=largest_repo_nodes,
        largest_repo_clusters=largest_repo_clusters,
        total_seconds=round(time.perf_counter() - start, 3),
    )
    return df, stats


def write_centrality(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(CENTRALITY_COLUMNS).write_parquet(p)


def write_clusters(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(SPECTRAL_CLUSTERS_COLUMNS).write_parquet(p)


# ----- internals -----


def _collapse_multidigraph(g: nx.MultiDiGraph) -> nx.DiGraph:
    """Collapse parallel typed edges into a single weighted DiGraph.

    Weight = number of underlying typed edges + sum of any explicit
    ``count`` attributes (e.g. CALLS edges carry counts from SCIP).
    """
    h: nx.DiGraph = nx.DiGraph()
    h.add_nodes_from(g.nodes(data=True))
    edge_weights: dict[tuple[str, str], float] = {}
    for u, v, data in g.edges(data=True):
        c = data.get("count")
        delta = 1.0 + (float(c) if isinstance(c, (int, float)) else 0.0)
        edge_weights[(u, v)] = edge_weights.get((u, v), 0.0) + delta
    for (u, v), w in edge_weights.items():
        h.add_edge(u, v, weight=w)
    return h


__all__ = [
    "DEFAULT_BETWEENNESS_K",
    "CentralityStats",
    "ClusterStats",
    "compute_centrality",
    "compute_clusters",
    "write_centrality",
    "write_clusters",
]
