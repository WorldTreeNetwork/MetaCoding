"""Pydantic models for Layer-1 (mechanical) CTKR artifacts.

Every L1 technique writes its outputs under ``.metacoding/ctkr/`` against
the shapes defined here. Downstream code (L1 sibling techniques, L3
labelers, the CLI) imports from this module rather than redefining
shapes — this is the single source of truth.

Versioning rule: any field rename, type widen, or semantic change must
bump ``SCHEMA_VERSION`` and the per-artifact ``schema_version`` column.
Old artifacts can be re-validated against an older version of this
module by checking out the appropriate git revision.

The artifacts themselves live on disk as Parquet (columnar; fast for the
ML lane) plus a couple of opaque blob directories for index files that
aren't naturally tabular (FAISS / hnswlib).

Artifact directory layout::

    .metacoding/ctkr/
    ├── embeddings.parquet           # rows: EmbeddingRow
    ├── motifs.parquet               # rows: MotifRow
    ├── motif_instances.parquet      # rows: MotifInstanceRow
    ├── shape_pds.parquet            # rows: ShapePDRow (one per repo × dim)
    ├── wasserstein_h1.parquet       # rows: WassersteinH1Row (one per repo-pair)
    ├── centrality.parquet           # rows: CentralityRow
    ├── spectral_clusters.parquet    # rows: SpectralClusterRow
    ├── nn_index/
    │   ├── nn_index.bin             # FAISS/hnswlib serialized index
    │   └── nn_index.meta.json       # rows: NNIndexMeta (single object)
    └── manifest.json                # rows: ArtifactManifest (single object)

See ``docs/design/ctkr-artifacts.md`` for full prose; this docstring is the
short version.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, NonNegativeInt, PositiveInt

SCHEMA_VERSION: int = 1

# Edge kinds mirror MetaCoding's TypeScript EdgeKind union (src/store/types.ts).
# Kept as a Literal so static type checkers + pydantic catch typos.
EdgeKind = Literal[
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
]


# ----- Row-level models (one row per parquet record) -----


class EmbeddingRow(BaseModel):
    """One symbol's embedding vector.

    Produced by L1/C1 (node2vec / GraphSAGE). All vectors in a single
    ``embeddings.parquet`` MUST share a dimension; that dimension is
    recorded in ``ArtifactManifest.embedding_dim``.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    vec: list[float]  # float32 in parquet; pydantic carries float
    schema_version: int = SCHEMA_VERSION


class MotifRow(BaseModel):
    """One frequent typed subgraph discovered by L1/C2.

    ``signature`` is the canonical serialization of the motif's graph
    structure (a typed-edge-list string, deterministic across runs of
    the miner). It is the join key into ``motif_instances.parquet``.
    """

    motif_id: str
    signature: str
    size_nodes: PositiveInt
    size_edges: NonNegativeInt
    support: PositiveInt  # how many instances exist corpus-wide
    repo_coverage: list[str]  # repos in which the motif appears at least once
    edge_kinds: list[EdgeKind]  # distinct edge kinds present in the motif
    schema_version: int = SCHEMA_VERSION


class MotifInstanceRow(BaseModel):
    """One concrete occurrence of a motif in the corpus.

    Multiple rows per ``motif_id``; links back to the originating
    symbol(s) so an evidence-fetcher (L3/F3) can pull snippets.
    """

    motif_id: str
    symbol_id: str  # the "anchor" symbol — usually the first node by signature order
    repo: str
    file: str
    line: PositiveInt
    schema_version: int = SCHEMA_VERSION


class ShapePDRow(BaseModel):
    """Persistent-homology shape signature for one (repo, homology-dim) pair.

    Produced by L1/S1. ``persistence_pairs`` is encoded as flat parallel
    lists rather than a list-of-tuples because Parquet's list<list<...>>
    support varies across readers.
    """

    repo: str
    dim: NonNegativeInt  # H_0, H_1, H_2 typically
    birth: list[float]
    death: list[float]
    schema_version: int = SCHEMA_VERSION


class HomProfileRow(BaseModel):
    """One symbol's hom-profile — raw integer edge counts by (kind, direction).

    Produced by L1 (``ctkr hom-profiles``, MetaCoding-23q.1). The vector
    is stored at **maximal precision** as unsigned integer counts (no
    L1-normalisation, no quantisation, no kinds_filter baked into the
    numbers). Per ``docs/notes/entropy-as-dial.md`` granularity is a
    caller-tunable knob, so downstream tools re-normalise / discretize
    at query time rather than the writer baking a choice into the bytes.

    Vector dimension is ``2 * len(EDGE_KINDS)`` from
    ``ctkr.graph_loader.EDGE_KINDS`` (currently 28). Ordering convention:
    for each ``ek in EDGE_KINDS``, the ``(ek, "in")`` slot precedes the
    ``(ek, "out")`` slot. The canonical ``_DIMS`` list in
    ``ctkr.hom_profiles`` is the single source of truth for the order.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    profile_vec: list[NonNegativeInt]
    schema_version: int = SCHEMA_VERSION


class NNIndexMeta(BaseModel):
    """Metadata sidecar for the opaque ``nn_index/`` directory.

    The binary index itself (FAISS or hnswlib) is not a parquet table.
    This sidecar records what's inside so callers don't have to
    introspect the binary.
    """

    backend: Literal["faiss", "hnswlib"]
    metric: Literal["cosine", "l2", "ip"]
    embedding_dim: PositiveInt
    n_symbols: NonNegativeInt
    built_at: datetime
    embeddings_source: str = Field(
        description=(
            "Relative path to the embeddings.parquet this index was built from. "
            "Used to detect staleness when embeddings are regenerated."
        ),
    )
    schema_version: int = SCHEMA_VERSION


class CentralityRow(BaseModel):
    """Per-symbol centrality scores produced by L1/S2.

    All three measures are normalized to [0, 1] within the source graph.
    ``betweenness`` is approximate when computed with sampling
    (``k < |N|``) — recorded as the same column for consistency, with
    the sampling factor noted in :attr:`ArtifactManifest.notes`.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    pagerank: float = Field(ge=0.0)
    betweenness: float = Field(ge=0.0)
    eigenvector: float = Field(ge=0.0)
    schema_version: int = SCHEMA_VERSION


class SpectralClusterRow(BaseModel):
    """Per-symbol cluster assignment produced by L1/S2.

    Clusters are scoped to one repo at a time — ``cluster_id`` is only
    meaningful within ``repo``. The intent is "modules-as-emergent": a
    sub-system that the symbol's structural neighbors form, regardless
    of declared package boundaries.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    cluster_id: NonNegativeInt
    cluster_size: PositiveInt
    schema_version: int = SCHEMA_VERSION


class WassersteinH1Row(BaseModel):
    """One pairwise topological-distance entry between two repos.

    Produced by ``ctkr shape`` (L1/S1) alongside ``shape_pds.parquet``.
    Despite the file name, the underlying metric is the **bottleneck
    distance** (L∞-Wasserstein) between H₁ persistence diagrams —
    chosen over full p-Wasserstein because it ships with the lighter
    ``topo`` extra (gudhi, no ``pot`` dependency). The file name is
    retained for historical / external-caller compatibility.

    Stored upper-triangle only (``repo_a < repo_b`` lexicographically);
    the metric is symmetric, so the lower triangle is implied.
    """

    repo_a: str
    repo_b: str
    distance: float = Field(ge=0.0)
    schema_version: int = SCHEMA_VERSION


class ArtifactManifest(BaseModel):
    """Top-level pointer file for the ``.metacoding/ctkr/`` directory.

    Lives at ``.metacoding/ctkr/manifest.json``. Records which artifacts
    are present, when they were generated, and what version of this
    schema they were validated against. Cheap to read; tooling should
    consult it before assuming an artifact exists.
    """

    # ``extra="allow"`` so a manifest written by a future ctkr schema
    # version (with unknown fields) round-trips through an older writer
    # without those fields being silently dropped. Multiple writers
    # share this file, so forward-compat preservation matters even
    # within a single schema version.
    model_config = ConfigDict(extra="allow")

    schema_version: int = SCHEMA_VERSION
    generated_at: datetime
    metacoding_data_dir: str  # absolute path to the .metacoding/ that fed us
    embeddings: bool = False
    motifs: bool = False
    motif_instances: bool = False
    shape_pds: bool = False
    wasserstein_h1: bool = False
    centrality: bool = False
    spectral_clusters: bool = False
    nn_index: bool = False
    hom_profiles: bool = False
    embedding_dim: int | None = None
    profile_vec_dim: int | None = None
    # Per-edge-kind weights applied to hom-profile dimensions (MetaCoding-23q.1
    # weighting variant). None/absent means raw UInt32 counts (the maximal-
    # precision default). A non-empty mapping means the profile_vec was scaled
    # by these multipliers and is therefore a Float64 variant, NOT raw counts.
    kind_weights: dict[str, float] | None = None
    # Neighborhood depth of the hom-profile artifact. 1 (default) = raw
    # per-symbol typed-edge counts; 2 = one Weisfeiler-Leman refinement
    # round (self ++ per-(kind,dir)-block neighbor-mean). None on manifests
    # written before this field existed (treat as 1).
    profile_depth: int | None = None
    n_symbols: NonNegativeInt = 0
    n_motifs: NonNegativeInt = 0
    n_motif_instances: NonNegativeInt = 0
    n_hom_profiles: NonNegativeInt = 0
    notes: str | None = None


# ----- Parquet column orderings -----
# Parquet doesn't care about column order, but downstream tooling (e.g.
# `duckdb` ad-hoc queries) reads more nicely with a stable layout.
# Tests pin against these so accidental field reorderings fail loudly.

EMBEDDINGS_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "vec",
    "schema_version",
)

MOTIFS_COLUMNS: tuple[str, ...] = (
    "motif_id",
    "signature",
    "size_nodes",
    "size_edges",
    "support",
    "repo_coverage",
    "edge_kinds",
    "schema_version",
)

MOTIF_INSTANCES_COLUMNS: tuple[str, ...] = (
    "motif_id",
    "symbol_id",
    "repo",
    "file",
    "line",
    "schema_version",
)

SHAPE_PDS_COLUMNS: tuple[str, ...] = (
    "repo",
    "dim",
    "birth",
    "death",
    "schema_version",
)

CENTRALITY_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "pagerank",
    "betweenness",
    "eigenvector",
    "schema_version",
)

SPECTRAL_CLUSTERS_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "cluster_id",
    "cluster_size",
    "schema_version",
)

WASSERSTEIN_H1_COLUMNS: tuple[str, ...] = (
    "repo_a",
    "repo_b",
    "distance",
    "schema_version",
)

HOM_PROFILES_COLUMNS: tuple[str, ...] = (
    "symbol_id",
    "repo",
    "qualified_name",
    "profile_vec",
    "schema_version",
)


__all__ = [
    "SCHEMA_VERSION",
    "EdgeKind",
    "EmbeddingRow",
    "MotifRow",
    "MotifInstanceRow",
    "ShapePDRow",
    "WassersteinH1Row",
    "CentralityRow",
    "SpectralClusterRow",
    "HomProfileRow",
    "NNIndexMeta",
    "ArtifactManifest",
    "EMBEDDINGS_COLUMNS",
    "MOTIFS_COLUMNS",
    "MOTIF_INSTANCES_COLUMNS",
    "SHAPE_PDS_COLUMNS",
    "WASSERSTEIN_H1_COLUMNS",
    "CENTRALITY_COLUMNS",
    "SPECTRAL_CLUSTERS_COLUMNS",
    "HOM_PROFILES_COLUMNS",
]
