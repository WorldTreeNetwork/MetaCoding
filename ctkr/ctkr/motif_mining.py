"""Frequent typed-subgraph mining (Orchestrators-k97).

v1 enumerates **3-node** typed motifs in three "skeletons":

* **path** — ``a –e1→ b –e2→ c`` (b is the central node)
* **V** — ``a –e1→ b``, ``a –e2→ c`` (out-fork from a)
* **W** — ``b –e1→ a``, ``c –e2→ a`` (in-fork into a; "wedge")

This is intentionally narrower than full gSpan — running real gSpan on
a 500k-node typed graph would blow up combinatorially without
significant engineering. Three-node motifs already exceed the
issue's acceptance bar (≥50 motifs with cross-repo coverage > 1) and
capture the structural patterns we care about: dispatch chains,
implementer fanouts, decorated definitions, etc. Larger motifs are
deferred to a follow-up issue.

Why not ``gspan-mining``
------------------------

The PyPI gspan-mining package only handles **untyped** vertex/edge
graphs and expects a fixed integer-labeled graph DB. Our graph has
12 node kinds × 10 edge kinds × directionality, all of which carry
signal — we'd lose most of the discriminative power by dropping it.

Canonical signature
-------------------

Each motif is keyed by a tuple ``(shape, kind_a, e1, kind_b, e2, kind_c)``
where ``shape ∈ {"path", "V", "W"}``. For V and W shapes, we
canonicalize so ``(e1, kind_b) ≤ (e2, kind_c)`` lexicographically —
otherwise the same V appears under two signatures depending on which
prong we visited first.

Anchor symbol
-------------

Each instance records exactly one anchor symbol — the **central node**
of the shape (b for paths, a for V/W). That's the symbol that the
evidence-retrieval module (``ctkr.evidence``) will pull a snippet
around when an L3 labeler is fed this motif.
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Literal

import networkx as nx
import polars as pl

from ctkr.schema import (
    MOTIF_INSTANCES_COLUMNS,
    MOTIFS_COLUMNS,
    SCHEMA_VERSION,
)

logger = logging.getLogger("ctkr.motif_mining")


Shape = Literal["path", "V", "W"]

DEFAULT_MIN_SUPPORT = 5
DEFAULT_MAX_INCIDENT_EDGES = 30
DEFAULT_MAX_INSTANCES_PER_MOTIF = 100
DEFAULT_INTERESTING_KINDS = frozenset(
    {"class", "interface", "method", "function", "type_alias", "namespace", "enum"}
)


@dataclass(slots=True, frozen=True)
class MineStats:
    """Telemetry for a ``mine_motifs`` run."""

    n_nodes_considered: int
    n_anchors_visited: int
    n_signatures_seen: int
    n_motifs_kept: int
    n_instances_kept: int
    capped_anchors: int
    seconds: float


def mine_motifs(
    g: nx.MultiDiGraph,
    *,
    min_support: int = DEFAULT_MIN_SUPPORT,
    max_incident_edges: int = DEFAULT_MAX_INCIDENT_EDGES,
    max_instances_per_motif: int = DEFAULT_MAX_INSTANCES_PER_MOTIF,
    interesting_kinds: Iterable[str] | None = DEFAULT_INTERESTING_KINDS,
) -> tuple[pl.DataFrame, pl.DataFrame, MineStats]:
    """Enumerate 3-node typed motifs over the loaded graph.

    Parameters
    ----------
    g
        MultiDiGraph from ``ctkr.graph_loader.load_graph``.
    min_support
        A motif must have ≥ this many corpus-wide instances to be kept.
    max_incident_edges
        Per-anchor cap on incident edges considered. Hub nodes get
        deterministically truncated to bound the per-node ``degree²``
        cost. Document in stats how many anchors were capped.
    max_instances_per_motif
        Cap on the number of anchor instances stored per motif —
        downstream evidence retrieval samples from this list anyway.
    interesting_kinds
        Restrict anchor (central) nodes to these symbol kinds. Defaults
        to the architecturally significant kinds; pass ``None`` to
        consider every node.

    Returns
    -------
    motifs_df
        Schema-compliant DataFrame for ``motifs.parquet``.
    instances_df
        Schema-compliant DataFrame for ``motif_instances.parquet``.
    stats
        Telemetry.
    """
    start = time.perf_counter()
    kinds_filter: set[str] | None = (
        set(interesting_kinds) if interesting_kinds is not None else None
    )

    # Aggregations
    sig_count: dict[tuple, int] = defaultdict(int)
    sig_repos: dict[tuple, set[str]] = defaultdict(set)
    sig_edge_kinds: dict[tuple, set[str]] = defaultdict(set)
    sig_anchors: dict[tuple, list[str]] = defaultdict(list)
    sig_anchors_seen: dict[tuple, set[str]] = defaultdict(set)

    def _record_anchor(sig: tuple, anchor: str) -> None:
        """Append an anchor exactly once per motif (anchor IDs are
        per-symbol, so the central node of multiple instances of the
        same shape only contributes one row downstream)."""
        seen = sig_anchors_seen[sig]
        if anchor in seen:
            return
        if len(sig_anchors[sig]) >= max_instances_per_motif:
            return
        seen.add(anchor)
        sig_anchors[sig].append(anchor)

    anchors_visited = 0
    capped = 0
    n_considered = 0

    for v in g.nodes():
        n_considered += 1
        node_data = g.nodes[v]
        if kinds_filter is not None and node_data.get("kind") not in kinds_filter:
            continue

        # Collect incident edges, tag direction so V vs W vs path is recoverable.
        # Each entry: (direction, neighbor_id, edge_kind)
        incident: list[tuple[str, str, str]] = []
        for _, dst, k in g.out_edges(v, keys=True):
            incident.append(("out", dst, k))
        for src, _, k in g.in_edges(v, keys=True):
            incident.append(("in", src, k))
        if len(incident) < 2:
            continue
        anchors_visited += 1
        if len(incident) > max_incident_edges:
            capped += 1
            # Deterministic truncation: sort by (kind, neighbor) so subsequent
            # runs on the same graph produce the same patterns.
            incident.sort(key=lambda t: (t[2], t[0], t[1]))
            incident = incident[:max_incident_edges]

        kv = node_data.get("kind", "") or ""
        repo_v = node_data.get("repo", "") or ""

        for i in range(len(incident)):
            d1, nb1, e1 = incident[i]
            k_nb1 = g.nodes[nb1].get("kind", "") or ""
            for j in range(i + 1, len(incident)):
                d2, nb2, e2 = incident[j]
                if nb1 == nb2:
                    continue  # same neighbor twice; ignore the multi-edge case
                k_nb2 = g.nodes[nb2].get("kind", "") or ""

                # Decide skeleton.
                if d1 == "out" and d2 == "out":
                    shape: Shape = "V"
                elif d1 == "in" and d2 == "in":
                    shape = "W"
                elif d1 == "out" and d2 == "in":
                    # in→v→out reversed: it's a path through v but
                    # we want canonical (a→b→c) form.
                    # Here: nb2 → v → nb1 reads as path with nb2 first.
                    sig = (
                        "path",
                        k_nb2,
                        e2,
                        kv,
                        e1,
                        k_nb1,
                    )
                    sig_count[sig] += 1
                    sig_repos[sig].add(repo_v)
                    sig_edge_kinds[sig].update((e1, e2))
                    _record_anchor(sig, v)
                    continue
                elif d1 == "in" and d2 == "out":
                    sig = (
                        "path",
                        k_nb1,
                        e1,
                        kv,
                        e2,
                        k_nb2,
                    )
                    sig_count[sig] += 1
                    sig_repos[sig].add(repo_v)
                    sig_edge_kinds[sig].update((e1, e2))
                    _record_anchor(sig, v)
                    continue
                else:  # pragma: no cover — exhaustive
                    continue

                # V or W: canonicalize so the smaller prong is "first."
                left = (e1, k_nb1)
                right = (e2, k_nb2)
                if left <= right:
                    sig = (shape, kv, e1, k_nb1, e2, k_nb2)
                else:
                    sig = (shape, kv, e2, k_nb2, e1, k_nb1)
                sig_count[sig] += 1
                sig_repos[sig].add(repo_v)
                sig_edge_kinds[sig].update((e1, e2))
                _record_anchor(sig, v)

    # Build the output DataFrames.
    motif_rows: list[dict[str, Any]] = []
    instance_rows: list[dict[str, Any]] = []
    n_kept = 0
    n_instances = 0
    for sig, support in sig_count.items():
        if support < min_support:
            continue
        repo_cov = sorted(sig_repos[sig])
        motif_id = _motif_id(sig)
        motif_rows.append(
            {
                "motif_id": motif_id,
                "signature": _signature_string(sig),
                "size_nodes": 3,
                "size_edges": 2,
                "support": support,
                "repo_coverage": repo_cov,
                "edge_kinds": sorted(sig_edge_kinds[sig]),
                "schema_version": SCHEMA_VERSION,
            }
        )
        n_kept += 1

        for anchor in sig_anchors[sig]:
            d = g.nodes[anchor]
            file = d.get("file") or d.get("file_path") or ""
            line = d.get("line") or 1
            if not file or not line:
                continue
            instance_rows.append(
                {
                    "motif_id": motif_id,
                    "symbol_id": anchor,
                    "repo": d.get("repo", "") or "",
                    "file": file,
                    "line": max(1, int(line)),
                    "schema_version": SCHEMA_VERSION,
                }
            )
            n_instances += 1

    if motif_rows:
        motifs_df = pl.DataFrame(motif_rows).select(MOTIFS_COLUMNS)
    else:
        motifs_df = _empty_motifs_df()
    if instance_rows:
        instances_df = pl.DataFrame(instance_rows).select(MOTIF_INSTANCES_COLUMNS)
    else:
        instances_df = _empty_instances_df()

    stats = MineStats(
        n_nodes_considered=n_considered,
        n_anchors_visited=anchors_visited,
        n_signatures_seen=len(sig_count),
        n_motifs_kept=n_kept,
        n_instances_kept=n_instances,
        capped_anchors=capped,
        seconds=round(time.perf_counter() - start, 3),
    )
    return motifs_df, instances_df, stats


def write_motifs(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(MOTIFS_COLUMNS).write_parquet(p)


def write_motif_instances(df: pl.DataFrame, out_path: str | Path) -> None:
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    df.select(MOTIF_INSTANCES_COLUMNS).write_parquet(p)


# ----- internals -----


def _motif_id(sig: tuple) -> str:
    """Stable short ID for a motif signature.

    Uses a deterministic hash so re-runs produce the same IDs (good
    for joinability across artifact regenerations).
    """
    import hashlib

    raw = "|".join(str(x) for x in sig).encode("utf-8")
    return "m:" + hashlib.blake2b(raw, digest_size=6).hexdigest()


def _signature_string(sig: tuple) -> str:
    """Render a signature as a human-readable string.

    - path: ``path  kind_a -e1-> kind_b -e2-> kind_c``
    - V:    ``V     kind_a -e1-> kind_b ; kind_a -e2-> kind_c``
    - W:    ``W     kind_b -e1-> kind_a ; kind_c -e2-> kind_a``
    """
    shape = sig[0]
    if shape == "path":
        _, ka, e1, kb, e2, kc = sig
        return f"path  {ka} -{e1}-> {kb} -{e2}-> {kc}"
    if shape == "V":
        _, ka, e1, kb, e2, kc = sig
        return f"V     {ka} -{e1}-> {kb} ; {ka} -{e2}-> {kc}"
    if shape == "W":
        _, ka, e1, kb, e2, kc = sig
        return f"W     {kb} -{e1}-> {ka} ; {kc} -{e2}-> {ka}"
    return repr(sig)


def _empty_motifs_df() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "motif_id": pl.Utf8,
            "signature": pl.Utf8,
            "size_nodes": pl.Int64,
            "size_edges": pl.Int64,
            "support": pl.Int64,
            "repo_coverage": pl.List(pl.Utf8),
            "edge_kinds": pl.List(pl.Utf8),
            "schema_version": pl.Int64,
        }
    ).select(MOTIFS_COLUMNS)


def _empty_instances_df() -> pl.DataFrame:
    return pl.DataFrame(
        schema={
            "motif_id": pl.Utf8,
            "symbol_id": pl.Utf8,
            "repo": pl.Utf8,
            "file": pl.Utf8,
            "line": pl.Int64,
            "schema_version": pl.Int64,
        }
    ).select(MOTIF_INSTANCES_COLUMNS)


__all__ = [
    "DEFAULT_MIN_SUPPORT",
    "DEFAULT_MAX_INCIDENT_EDGES",
    "MineStats",
    "Shape",
    "mine_motifs",
    "write_motifs",
    "write_motif_instances",
]
