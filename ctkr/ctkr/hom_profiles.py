"""Hom-profile computation for the MetaCoding code graph (MetaCoding-23q.1).

For every Symbol in the loaded graph, count incident edges grouped by
``(edge_kind, direction)`` — the typed-graph analogue of an in/out
degree vector, with one dimension per edge kind per direction. The
result is a per-symbol vector that downstream tooling clusters to
discover name-independent "same role" classes (Yoneda's lemma applied
to typed graphs — see ``docs/design/ct-pipeline.md`` §2a).

Maximal-precision contract
--------------------------

Counts are stored as raw unsigned integers, **never** L1-normalised
and **never** quantised at write time. Per
``docs/notes/entropy-as-dial.md`` granularity is a caller-tunable
parameter: the same artifact must serve coarse (k=4 bucket equality)
and fine (exact-count equality) consumers without regeneration. Any
discretisation belongs at query time, in the consumer.

Kinds filter
------------

``kinds_filter`` (per MetaCoding-o7k, closed in favour of "filter at
analysis time") drops symbols whose ``kind`` matches before profile
extraction. Edges incident to dropped symbols are still counted on
their surviving endpoint — dropping ``file`` does not blank the
``CONTAINS:in`` counts of the methods that ``file`` contained, because
those edges are real graph-structural facts about the methods.

Per-edge-kind weighting
------------------------

``kind_weights`` (MetaCoding-23q.1 weighting variant) multiplies every
dimension belonging to a given edge kind (both ``:in`` and ``:out``) by
a float before the vector is emitted. Unspecified kinds default to
``1.0``. This exists to *down-weight structural-scaffolding edges*
(especially ``CONTAINS``, which is dominated by directory/containment
tree structure rather than behaviour — see
``docs/notes/entropy-as-dial.md``) so role-discrimination reflects
behaviour rather than the folder tree.

**Precision caveat (honest accounting).** Weighting scales the integer
counts, so the profile vector is *no longer* the raw ``UInt32``
maximal-precision artifact — it becomes a distinct ``Float64`` variant.
The weights used are recorded in the manifest's ``kind_weights`` field
so the artifact is self-describing and never silently confused with raw
counts. When ``kind_weights`` is ``None``/empty the integer raw-count
path is preserved byte-for-byte (backward compatible).

Determinism
-----------

Output rows are ordered by ``symbol_id`` (lexicographic) so the same
input graph yields a byte-identical parquet across runs.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import networkx as nx
import polars as pl

from ctkr.graph_loader import EDGE_KINDS
from ctkr.schema import (
    HOM_PROFILES_COLUMNS,
    SCHEMA_VERSION,
    ArtifactManifest,
    HomProfileRow,
)

logger = logging.getLogger("ctkr.hom_profiles")


# ── canonical dimension ordering ─────────────────────────────────────────────
# Mirrors ``ctkr.commands.entropy_check._DIMS`` exactly so the two callers
# cannot drift. Order: for each edge kind, (kind, "in") precedes (kind, "out").
DIMS: tuple[tuple[str, str], ...] = tuple(
    (ek, direction) for ek in EDGE_KINDS for direction in ("in", "out")
)
DIM_IDX: dict[tuple[str, str], int] = {d: i for i, d in enumerate(DIMS)}
NDIM: int = len(DIMS)


@dataclass(slots=True, frozen=True)
class HomProfilesStats:
    """Telemetry for one ``compute_hom_profiles`` run."""

    n_nodes_input: int
    n_nodes_emitted: int
    n_edges: int
    profile_vec_dim: int
    kinds_filter: tuple[str, ...]
    # Empty when no weights applied (raw-count path). Otherwise the
    # (kind, weight) pairs the profile vectors were scaled by, sorted.
    kind_weights: tuple[tuple[str, float], ...]
    weighted: bool
    elapsed_seconds: float


def compute_hom_profiles(
    g: nx.MultiDiGraph,
    *,
    kinds_filter: Iterable[str] | None = None,
    kind_weights: Mapping[str, float] | None = None,
) -> tuple[pl.DataFrame, HomProfilesStats]:
    """Compute per-symbol hom-profiles over the graph.

    Parameters
    ----------
    g
        Loaded MultiDiGraph from ``ctkr.graph_loader.load_graph``.
    kinds_filter
        Symbol kinds to *exclude* from the output (set semantics). The
        full graph is still used for edge counting on the surviving
        symbols so a filtered-out ``file`` still contributes
        ``CONTAINS:in`` counts to the methods it contains. None or an
        empty iterable keeps every symbol.
    kind_weights
        Per-edge-kind float multipliers applied to that kind's ``:in``
        and ``:out`` dimensions before emit. Unspecified kinds default
        to ``1.0``. None or an empty mapping (or one whose every value
        is exactly ``1.0``) preserves the raw integer-count path exactly
        (backward compatible). When any weight differs from ``1.0`` the
        ``profile_vec`` becomes ``Float64`` — a distinct, non-raw
        artifact variant; the weights used are surfaced on the returned
        stats and should be recorded in the manifest.

    Returns
    -------
    (pl.DataFrame, HomProfilesStats)
        DataFrame columns in ``HOM_PROFILES_COLUMNS`` order; one row
        per surviving symbol. ``profile_vec`` is a length-``NDIM`` list
        of unsigned integer counts (raw) unless ``kind_weights`` scaled
        it, in which case it is a length-``NDIM`` list of floats.
    """
    start = time.perf_counter()
    n_nodes_input = g.number_of_nodes()
    n_edges = g.number_of_edges()
    excluded_kinds: frozenset[str] = (
        frozenset(kinds_filter) if kinds_filter else frozenset()
    )

    # Normalise weights: keep only entries that actually change a count
    # (weight != 1.0). If nothing changes, we stay on the integer path.
    effective_weights: dict[str, float] = {
        k: float(w) for k, w in (kind_weights or {}).items() if float(w) != 1.0
    }
    weighted = bool(effective_weights)

    # We count edges over the FULL graph then filter at emit, so excluded
    # kinds still contribute to their neighbors' counts (the o7k invariant).
    raw_counts: dict[str, list[int]] = {nid: [0] * NDIM for nid in g.nodes()}
    for src, dst, data in g.edges(data=True):
        kind = data.get("kind", "")
        in_dim = DIM_IDX.get((kind, "in"))
        out_dim = DIM_IDX.get((kind, "out"))
        if out_dim is not None:
            raw_counts[src][out_dim] += 1
        if in_dim is not None:
            raw_counts[dst][in_dim] += 1

    # Per-dimension weight vector (1.0 for unspecified kinds). Only built
    # when weighting is active so the default path is untouched.
    weight_vec: list[float] = (
        [effective_weights.get(kind, 1.0) for (kind, _dir) in DIMS]
        if weighted
        else []
    )

    def _profile_for(nid: str) -> list[int] | list[float]:
        counts = raw_counts[nid]
        if not weighted:
            return counts
        return [c * w for c, w in zip(counts, weight_vec, strict=True)]

    rows: list[dict[str, Any]] = []
    for nid in sorted(g.nodes()):
        node_attrs = g.nodes[nid]
        sym_kind = node_attrs.get("kind") or ""
        if sym_kind in excluded_kinds:
            continue
        rows.append(
            {
                "symbol_id": nid,
                "repo": node_attrs.get("repo", "") or "",
                "qualified_name": node_attrs.get("qualified_name", "") or "",
                "profile_vec": _profile_for(nid),
                "schema_version": SCHEMA_VERSION,
            }
        )

    df = pl.DataFrame(rows, schema=_polars_schema(weighted=weighted)).select(
        HOM_PROFILES_COLUMNS
    )
    elapsed = round(time.perf_counter() - start, 3)

    stats = HomProfilesStats(
        n_nodes_input=n_nodes_input,
        n_nodes_emitted=df.height,
        n_edges=n_edges,
        profile_vec_dim=NDIM,
        kinds_filter=tuple(sorted(excluded_kinds)),
        kind_weights=tuple(sorted(effective_weights.items())),
        weighted=weighted,
        elapsed_seconds=elapsed,
    )
    return df, stats


def write_hom_profiles(
    df: pl.DataFrame, out_path: str | Path, *, weighted: bool = False
) -> None:
    """Write the hom-profiles parquet.

    Default (``weighted=False``): the UInt32 cast is load-bearing — it
    enforces the maximal-precision contract from
    ``docs/notes/entropy-as-dial.md`` even when a caller hands us a Float
    column. Don't relax it.

    ``weighted=True``: the ``profile_vec`` was scaled by per-kind
    weights and is therefore a deliberate Float64 variant, NOT raw
    counts. We cast to ``Float64`` (never UInt32 — that would truncate
    fractional weights to garbage) and rely on the manifest's
    ``kind_weights`` field to mark the artifact as non-raw.
    """
    p = Path(out_path).expanduser().resolve()
    p.parent.mkdir(parents=True, exist_ok=True)
    dtype = pl.List(pl.Float64) if weighted else pl.List(pl.UInt32)
    df = df.select(HOM_PROFILES_COLUMNS).with_columns(
        pl.col("profile_vec").cast(dtype)
    )
    df.write_parquet(p)


def write_manifest(
    data_dir: str | Path,
    *,
    hom_profiles: bool = True,
    n_hom_profiles: int = 0,
    profile_vec_dim: int | None = None,
    kind_weights: Mapping[str, float] | None = None,
    notes: str | None = None,
) -> Path:
    """Merge hom-profile presence into ``<data_dir>/ctkr/manifest.json``.

    Reads any existing manifest and updates only the hom-profile fields;
    other presence flags and counters survive intact so multiple
    commands can share the same manifest file. Creates a fresh manifest
    if none exists. Returns the path written.
    """
    base = Path(data_dir).expanduser().resolve()
    manifest_path = base / "ctkr" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)

    existing: dict[str, Any] = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            logger.warning(
                "manifest.json at %s is malformed; overwriting", manifest_path
            )
            existing = {}

    merged = {
        **existing,
        "schema_version": SCHEMA_VERSION,
        "generated_at": datetime.now(tz=UTC).isoformat(),
        "metacoding_data_dir": str(base),
        "hom_profiles": hom_profiles,
        "n_hom_profiles": int(n_hom_profiles),
        "profile_vec_dim": profile_vec_dim,
        # None (raw UInt32 counts) unless a weighting variant was written.
        "kind_weights": dict(kind_weights) if kind_weights else None,
    }
    if notes is not None:
        merged["notes"] = notes

    model = ArtifactManifest.model_validate(merged)
    manifest_path.write_text(model.model_dump_json(indent=2), encoding="utf-8")
    return manifest_path


# ----- internals -----


def _polars_schema(*, weighted: bool = False) -> dict[str, pl.DataType]:
    """Polars schema mapping for the row dicts produced by compute_hom_profiles.

    Pinned so an empty rows list still yields a DataFrame with the right
    columns (rather than tripping polars' schema-inference path). When
    ``weighted`` the profile vector carries fractional weights and must
    be ``Float64``; otherwise it stays the raw ``UInt32`` count vector.
    """
    return {
        "symbol_id": pl.Utf8,
        "repo": pl.Utf8,
        "qualified_name": pl.Utf8,
        "profile_vec": pl.List(pl.Float64) if weighted else pl.List(pl.UInt32),
        "schema_version": pl.Int64,
    }


__all__ = [
    "DIMS",
    "DIM_IDX",
    "NDIM",
    "HomProfilesStats",
    "compute_hom_profiles",
    "write_hom_profiles",
    "write_manifest",
    "HomProfileRow",
]
