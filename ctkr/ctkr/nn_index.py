"""Cross-repo nearest-neighbor index over the L1 embeddings.

Builds an HNSW (Hierarchical Navigable Small World) index — fast,
exact-enough, and dependency-light. Lives under
``.metacoding/ctkr/nn_index/`` as two files:

* ``nn_index.bin`` — the serialized hnswlib index
* ``nn_index.meta.json`` — sidecar conforming to
  :class:`ctkr.schema.NNIndexMeta` so consumers know its dimension,
  metric, source embeddings file, and build timestamp

The schema spec from :issue:`Orchestrators-003` also allowed FAISS as
the backend. We picked hnswlib for v1 because:

1. Pure pip install, no system libs (FAISS-cpu needs OpenBLAS).
2. Cosine similarity is native (FAISS forces L2 with normalized
   vectors as a workaround).
3. Saves ~80 MB at install time.

A FAISS backend can be added later by subclassing :class:`NNIndex` —
the public API doesn't leak hnswlib types.
"""

from __future__ import annotations

import json
import logging
import time
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import polars as pl

from ctkr.schema import NNIndexMeta

logger = logging.getLogger("ctkr.nn_index")

DEFAULT_M = 32              # HNSW graph degree (higher = better recall, more memory)
DEFAULT_EF_CONSTRUCTION = 200
DEFAULT_EF_SEARCH = 64      # query-time exploration; tunable per query


@dataclass(slots=True, frozen=True)
class BuildStats:
    n_vectors: int
    dim: int
    seconds: float
    backend: str = "hnswlib"


@dataclass(slots=True, frozen=True)
class NearestHit:
    """One row of a nearest-neighbor result set.

    ``distance`` is the raw HNSW distance under the configured metric
    (cosine → 1 - cos_sim). ``similarity`` is the cosine similarity in
    ``[-1, 1]`` for ergonomic display.
    """

    symbol_id: str
    repo: str
    qualified_name: str
    similarity: float
    distance: float


class NNIndex:
    """Cosine-similarity HNSW index over an ``embeddings.parquet``.

    Build once with :func:`build`; load on demand with :func:`load`;
    query via :meth:`query` or :meth:`query_by_id`.

    The index stores integer labels — we keep a sidecar
    ``labels.parquet`` mapping integer label → ``(symbol_id, repo,
    qualified_name)``. The sidecar lives alongside the binary index
    in the same directory.
    """

    def __init__(
        self,
        index: Any,  # hnswlib.Index
        labels: pl.DataFrame,
        meta: NNIndexMeta,
    ) -> None:
        self._index = index
        self._labels = labels
        self.meta = meta
        # symbol_id → integer label, populated lazily.
        self._sym_to_label: dict[str, int] | None = None

    @classmethod
    def build(
        cls,
        embeddings_df: pl.DataFrame,
        *,
        out_dir: str | Path,
        M: int = DEFAULT_M,
        ef_construction: int = DEFAULT_EF_CONSTRUCTION,
        embeddings_source_rel: str = "../embeddings.parquet",
    ) -> tuple["NNIndex", BuildStats]:
        """Build an HNSW index from a Polars DataFrame of embeddings."""
        import hnswlib  # imported lazily — only needed at build/query time
        import numpy as np

        start = time.perf_counter()
        if "vec" not in embeddings_df.columns:
            raise ValueError("embeddings_df is missing the 'vec' column")
        if embeddings_df.height == 0:
            raise ValueError("embeddings_df is empty — nothing to index")

        vecs = np.array(embeddings_df["vec"].to_list(), dtype=np.float32)
        n, dim = vecs.shape
        out = Path(out_dir).expanduser().resolve()
        out.mkdir(parents=True, exist_ok=True)

        index = hnswlib.Index(space="cosine", dim=dim)
        index.init_index(max_elements=n, ef_construction=ef_construction, M=M)
        # Add in chunks so progress is observable on very large corpora.
        labels = np.arange(n, dtype=np.int64)
        index.add_items(vecs, labels)
        index.set_ef(DEFAULT_EF_SEARCH)

        # Persist the binary + labels sidecar.
        index.save_index(str(out / "nn_index.bin"))
        label_df = embeddings_df.select(["symbol_id", "repo", "qualified_name"])
        label_df = label_df.with_row_index("label")
        label_df.write_parquet(out / "labels.parquet")

        # Metadata sidecar.
        meta = NNIndexMeta(
            backend="hnswlib",
            metric="cosine",
            embedding_dim=dim,
            n_symbols=n,
            built_at=datetime.now(tz=timezone.utc),
            embeddings_source=embeddings_source_rel,
        )
        (out / "nn_index.meta.json").write_text(meta.model_dump_json(indent=2))

        stats = BuildStats(
            n_vectors=n, dim=dim, seconds=round(time.perf_counter() - start, 3)
        )
        return cls(index, label_df, meta), stats

    @classmethod
    def load(cls, index_dir: str | Path, *, ef_search: int = DEFAULT_EF_SEARCH) -> "NNIndex":
        """Load a previously-built index from disk."""
        import hnswlib

        d = Path(index_dir).expanduser().resolve()
        meta = NNIndexMeta.model_validate_json((d / "nn_index.meta.json").read_text())
        labels = pl.read_parquet(d / "labels.parquet")

        index = hnswlib.Index(space=meta.metric, dim=meta.embedding_dim)
        index.load_index(str(d / "nn_index.bin"), max_elements=meta.n_symbols)
        index.set_ef(ef_search)
        return cls(index, labels, meta)

    def set_ef(self, ef: int) -> None:
        """Adjust query-time exploration. Higher → more accurate, slower."""
        self._index.set_ef(ef)

    def query(
        self,
        vec: Any,  # 1-D float32 numpy array
        *,
        k: int = 20,
        exclude_repo: str | None = None,
        repo_filter: Iterable[str] | None = None,
    ) -> list[NearestHit]:
        """Top-k cosine-nearest neighbors of a raw vector.

        Filters are applied **after** ANN retrieval — when filtering
        is restrictive, retrieve a larger candidate pool then truncate.
        """
        import numpy as np

        repos: set[str] | None = set(repo_filter) if repo_filter else None
        # Over-fetch when filters are likely to drop results.
        fetch = k
        if exclude_repo is not None or repos is not None:
            fetch = max(k * 8, 100)
        if fetch > self.meta.n_symbols:
            fetch = self.meta.n_symbols

        ids, dists = self._index.knn_query(
            np.asarray(vec, dtype=np.float32), k=fetch
        )
        ids = ids[0]
        dists = dists[0]

        hits: list[NearestHit] = []
        # Map labels → metadata via direct row lookup.
        label_rows = self._labels.rows(named=True)
        for label, dist in zip(ids, dists, strict=True):
            r = label_rows[int(label)]
            if exclude_repo is not None and r["repo"] == exclude_repo:
                continue
            if repos is not None and r["repo"] not in repos:
                continue
            hits.append(
                NearestHit(
                    symbol_id=r["symbol_id"],
                    repo=r["repo"],
                    qualified_name=r["qualified_name"],
                    similarity=float(1.0 - dist),
                    distance=float(dist),
                )
            )
            if len(hits) >= k:
                break
        return hits

    def query_by_id(
        self,
        symbol_id: str,
        *,
        k: int = 20,
        cross_repo_only: bool = False,
        repo_filter: Iterable[str] | None = None,
    ) -> list[NearestHit]:
        """Top-k nearest neighbors of an already-indexed symbol.

        When ``cross_repo_only=True``, results from the same repo as the
        query symbol are dropped — useful for "find the role-equivalent
        of X across other repos" queries (the most common L3 question).
        """
        label = self._symbol_label(symbol_id)
        if label is None:
            raise KeyError(f"symbol_id {symbol_id!r} not in index")
        vec = self._index.get_items([label], return_type="numpy")[0]
        exclude = self._labels.row(label, named=True)["repo"] if cross_repo_only else None
        return self.query(vec, k=k, exclude_repo=exclude, repo_filter=repo_filter)

    def _symbol_label(self, symbol_id: str) -> int | None:
        if self._sym_to_label is None:
            self._sym_to_label = {
                r["symbol_id"]: int(r["label"])
                for r in self._labels.iter_rows(named=True)
            }
        return self._sym_to_label.get(symbol_id)


__all__ = [
    "DEFAULT_M",
    "DEFAULT_EF_CONSTRUCTION",
    "DEFAULT_EF_SEARCH",
    "BuildStats",
    "NearestHit",
    "NNIndex",
]
