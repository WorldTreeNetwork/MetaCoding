"""Persistent homology shape signatures (Orchestrators-vbj).

For each repo, compute a persistence diagram (PD) of its call/typed
graph under a degree-based filtration. The PD is a compact "shape
signature" — H₀ captures connected components and how they merge,
H₁ captures loops / dispatch structure. The corpus-level
repo-vs-repo Wasserstein distance matrix then clusters repos by
architectural shape, ignoring domain vocabulary.

Filtration choice
-----------------

The graph has no native edge weights for CONTAINS / IMPLEMENTS — they're
all binary relationships. We need a filtration that ranges over the
graph and yields informative PDs.

We use **node filtration f(v) = (max_deg - deg(v)) / max_deg**, edge
filtration = ``max(f(u), f(v))``. Result:

- ``f = 0`` is the **highest-degree hub**; it enters first.
- ``f = 1`` is a **leaf**; it enters last.
- Loops between hubs are born early (small filtration) and die late
  (when low-degree connectors complete the cycle).

This is a standard graph-PH filtration (a sublevel-set filtration with
degree as the height function). H₀ reports component-merge timings;
H₁ reports loop lifespans.

Subsampling
-----------

The largest repo (hermes-agent) has ~100k nodes — too large for gudhi's
SimplexTree without sampling. We degree-bias sample to ``max_nodes``
per repo, keeping high-degree hubs deterministically and sampling
lower-degree nodes by a fixed seed. The induced subgraph preserves
the "spine" of the repo while bounding compute.
"""

from __future__ import annotations

import logging
import math
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import networkx as nx
import polars as pl

from ctkr.schema import SCHEMA_VERSION, SHAPE_PDS_COLUMNS

logger = logging.getLogger("ctkr.shape")


DEFAULT_MAX_NODES_PER_REPO = 3000
DEFAULT_MAX_DIM = 1  # H_0 and H_1
DEFAULT_SAMPLE_SEED = 42
INFINITY_REPLACEMENT = 1.0  # bound for the unbounded H_0 essential point


@dataclass(slots=True, frozen=True)
class ShapeStats:
    """Telemetry for a ``compute_shape_pds`` run."""

    n_repos: int
    n_points_total: int
    sampled_repos: list[str]
    seconds: float


def compute_shape_pds(
    g: nx.MultiDiGraph,
    *,
    max_nodes_per_repo: int = DEFAULT_MAX_NODES_PER_REPO,
    max_dim: int = DEFAULT_MAX_DIM,
    seed: int = DEFAULT_SAMPLE_SEED,
    min_repo_size: int = 8,
) -> tuple[pl.DataFrame, dict[tuple[str, int], list[tuple[float, float]]], ShapeStats]:
    """Per-repo persistence diagrams (H_0 .. H_max_dim).

    Returns
    -------
    df
        DataFrame conforming to :data:`SHAPE_PDS_COLUMNS` — one row per
        ``(repo, dim)`` with parallel ``birth`` / ``death`` lists.
    pds
        Same data keyed by ``(repo, dim)`` — convenient for the
        Wasserstein-distance step which wants raw tuple lists.
    stats
        Telemetry: timing, sampled-repos list, total persistence-point
        count.
    """
    import gudhi  # type: ignore[import-untyped]

    start = time.perf_counter()
    pds: dict[tuple[str, int], list[tuple[float, float]]] = {}
    rows: list[dict[str, Any]] = []
    sampled: list[str] = []

    # Bucket node IDs by repo.
    by_repo: dict[str, list[str]] = {}
    for n, d in g.nodes(data=True):
        repo = d.get("repo")
        if repo is None:
            continue
        by_repo.setdefault(repo, []).append(n)

    for repo, node_ids in by_repo.items():
        if len(node_ids) < min_repo_size:
            continue

        if len(node_ids) > max_nodes_per_repo:
            node_ids = _degree_bias_sample(
                g, node_ids, max_nodes_per_repo, seed=seed
            )
            sampled.append(repo)

        sub = g.subgraph(node_ids).to_undirected()
        if sub.number_of_edges() == 0:
            continue

        # gudhi wants integer vertex IDs — assign a per-repo contiguous
        # index. The mapping is local; we don't need to keep it because
        # PDs (birth, death) are vertex-id-agnostic.
        idx = {n: i for i, n in enumerate(sub.nodes())}
        f_node_s, f_edge_s = _degree_filtration(sub)
        f_node = {idx[n]: f for n, f in f_node_s.items()}
        # Re-canonicalize integer pairs — string-order doesn't imply
        # the same int-order under ``idx``.
        f_edge = {
            _canon_int(idx[u], idx[v]): f for (u, v), f in f_edge_s.items()
        }

        st = gudhi.SimplexTree()
        for n, f in f_node.items():
            st.insert([n], filtration=f)
        for (u, v), f in f_edge.items():
            st.insert([u, v], filtration=f)
        # Triangles for H_1 detection. Each triangle's filtration =
        # max of its three edge values (the rule for a flag complex).
        if max_dim >= 1:
            _insert_triangles_int(st, sub, f_edge, idx)

        # gudhi needs the complex's "ambient dimension" set to one
        # higher than the homology dim we want, otherwise the top-most
        # homology class is silently dropped. See the gudhi tutorial
        # on "Persistent homology of a 1-skeleton."
        st.set_dimension(max_dim + 1)
        # min_persistence=-1.0 keeps zero-persistence pairs. For a
        # regular graph (all degrees equal) the filtration is constant
        # and every H_0 pair would otherwise be silently dropped.
        st.compute_persistence(
            homology_coeff_field=2,
            min_persistence=-1.0,
            persistence_dim_max=True,
        )

        for dim in range(max_dim + 1):
            pairs = st.persistence_intervals_in_dimension(dim)
            births: list[float] = []
            deaths: list[float] = []
            for b, d in pairs:
                births.append(float(b))
                deaths.append(
                    INFINITY_REPLACEMENT if math.isinf(d) else float(d)
                )
            pds[(repo, dim)] = list(zip(births, deaths, strict=True))
            rows.append(
                {
                    "repo": repo,
                    "dim": dim,
                    "birth": births,
                    "death": deaths,
                    "schema_version": SCHEMA_VERSION,
                }
            )

    if rows:
        df = pl.DataFrame(rows).select(SHAPE_PDS_COLUMNS)
    else:
        # Build an empty DataFrame with the right schema so downstream
        # code can always .select(SHAPE_PDS_COLUMNS) without a guard.
        df = pl.DataFrame(
            schema={
                "repo": pl.Utf8,
                "dim": pl.Int64,
                "birth": pl.List(pl.Float64),
                "death": pl.List(pl.Float64),
                "schema_version": pl.Int64,
            }
        ).select(SHAPE_PDS_COLUMNS)
    stats = ShapeStats(
        n_repos=len({k[0] for k in pds}),
        n_points_total=sum(len(v) for v in pds.values()),
        sampled_repos=sampled,
        seconds=round(time.perf_counter() - start, 3),
    )
    return df, pds, stats


def wasserstein_distance_matrix(
    pds: dict[tuple[str, int], list[tuple[float, float]]],
    dim: int = 1,
) -> tuple[pl.DataFrame, list[str]]:
    """Pairwise *bottleneck* distances between PDs of the given dimension.

    Despite the function name (kept for historical reasons / external
    callers), this uses the **bottleneck distance** rather than full
    p-Wasserstein. The bottleneck distance is the L∞-Wasserstein
    distance and doesn't require ``pot`` (Python Optimal Transport),
    so it ships with the lighter topo extra. Bottleneck satisfies the
    spec's "Wasserstein or bottleneck" allowance.

    Returns
    -------
    df
        Long-format DataFrame: ``repo_a, repo_b, distance``. Upper
        triangle only (``a < b`` lexicographically), since the metric
        is symmetric.
    repos
        Sorted repo list — axis labels for a square distance matrix.
    """
    import gudhi  # type: ignore[import-untyped]

    repos = sorted({k[0] for k in pds if k[1] == dim})

    rows: list[dict[str, Any]] = []
    for i, a in enumerate(repos):
        for b in repos[i + 1 :]:
            da = pds.get((a, dim)) or []
            db = pds.get((b, dim)) or []
            if not da and not db:
                dist = 0.0
            else:
                # gudhi.bottleneck_distance wants list[(birth, death)].
                dist = float(gudhi.bottleneck_distance(da, db))
            rows.append({"repo_a": a, "repo_b": b, "distance": dist})

    return pl.DataFrame(rows), repos


def write_shape_pds(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(SHAPE_PDS_COLUMNS).write_parquet(p)


def write_wasserstein(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.write_parquet(p)


# ----- internals -----


def _degree_bias_sample(
    g: nx.MultiDiGraph,
    node_ids: list[str],
    k: int,
    *,
    seed: int,
) -> list[str]:
    """Keep the top-``k/2`` by degree deterministically; sample the rest."""
    degs = [(n, g.degree(n)) for n in node_ids]
    degs.sort(key=lambda t: t[1], reverse=True)
    top_n = k // 2
    top = [n for n, _ in degs[:top_n]]
    rest = [n for n, _ in degs[top_n:]]
    rng = random.Random(seed)
    rng.shuffle(rest)
    return top + rest[: k - top_n]


def _degree_filtration(
    sub: nx.Graph,
) -> tuple[dict[str, float], dict[tuple[str, str], float]]:
    """Compute node and edge filtration values from the degree height.

    Keys are string node IDs; the caller remaps to integers for gudhi.
    """
    degs = dict(sub.degree())
    if not degs:
        return {}, {}
    max_d = max(degs.values()) or 1
    f_node: dict[str, float] = {n: (max_d - d) / max_d for n, d in degs.items()}
    f_edge: dict[tuple[str, str], float] = {}
    for u, v in sub.edges():
        a, b = (u, v) if u < v else (v, u)
        f_edge[(a, b)] = max(f_node[u], f_node[v])
    return f_node, f_edge


def _insert_triangles_int(
    st: Any,  # gudhi.SimplexTree
    sub: nx.Graph,
    f_edge: dict[tuple[int, int], float],
    idx: dict[str, int],
) -> None:
    """Add every triangle (u, v, w) — using integer vertex IDs (gudhi
    requires int vertices)."""
    nbrs = {n: set(sub.neighbors(n)) for n in sub.nodes()}
    for u in sub.nodes():
        u_nbrs = nbrs[u]
        for v in u_nbrs:
            if v <= u:
                continue
            common = u_nbrs & nbrs[v]
            for w in common:
                if w <= v:
                    continue
                iu, iv, iw = idx[u], idx[v], idx[w]
                fmax = max(
                    f_edge[_canon_int(iu, iv)],
                    f_edge[_canon_int(iu, iw)],
                    f_edge[_canon_int(iv, iw)],
                )
                st.insert([iu, iv, iw], filtration=fmax)


def _canon_int(u: int, v: int) -> tuple[int, int]:
    return (u, v) if u < v else (v, u)


__all__ = [
    "DEFAULT_MAX_NODES_PER_REPO",
    "DEFAULT_MAX_DIM",
    "ShapeStats",
    "compute_shape_pds",
    "wasserstein_distance_matrix",
    "write_shape_pds",
    "write_wasserstein",
]
