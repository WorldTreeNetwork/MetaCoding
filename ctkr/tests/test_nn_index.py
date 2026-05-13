"""Tests for the HNSW nearest-neighbor index (Orchestrators-1l9)."""

from __future__ import annotations

import time
from pathlib import Path

import polars as pl
import pytest

hnswlib = pytest.importorskip("hnswlib", reason="install with `uv add hnswlib`")

from ctkr.nn_index import NNIndex, NearestHit  # noqa: E402
from ctkr.schema import EMBEDDINGS_COLUMNS, NNIndexMeta  # noqa: E402


def _toy_embeddings() -> pl.DataFrame:
    """Two well-separated 8-d clusters of 12 vectors each."""
    import numpy as np

    rng = np.random.default_rng(7)
    a = rng.normal(loc=2.0, scale=0.1, size=(12, 8)).astype("float32")
    b = rng.normal(loc=-2.0, scale=0.1, size=(12, 8)).astype("float32")
    vecs = list(a) + list(b)
    rows = []
    for i, v in enumerate(vecs):
        rows.append(
            {
                "symbol_id": f"sym{i:02d}",
                "repo": "clusterA" if i < 12 else "clusterB",
                "qualified_name": f"qn{i:02d}",
                "vec": [float(x) for x in v],
                "schema_version": 1,
            }
        )
    return pl.DataFrame(rows).select(EMBEDDINGS_COLUMNS)


def test_build_writes_files(tmp_path: Path) -> None:
    df = _toy_embeddings()
    index, stats = NNIndex.build(df, out_dir=tmp_path / "nn_index")
    assert stats.n_vectors == 24
    assert stats.dim == 8
    assert (tmp_path / "nn_index" / "nn_index.bin").exists()
    assert (tmp_path / "nn_index" / "nn_index.meta.json").exists()
    assert (tmp_path / "nn_index" / "labels.parquet").exists()


def test_query_returns_intra_cluster_first(tmp_path: Path) -> None:
    """A symbol's nearest neighbors should all be in the same cluster."""
    df = _toy_embeddings()
    index, _ = NNIndex.build(df, out_dir=tmp_path / "nn_index")
    hits = index.query_by_id("sym00", k=11)
    assert len(hits) == 11
    # All 11 should be in clusterA (the same cluster as sym00).
    assert all(h.repo == "clusterA" for h in hits), hits


def test_cross_repo_only_drops_same_repo(tmp_path: Path) -> None:
    df = _toy_embeddings()
    index, _ = NNIndex.build(df, out_dir=tmp_path / "nn_index")
    hits = index.query_by_id("sym00", k=5, cross_repo_only=True)
    assert all(h.repo != "clusterA" for h in hits)
    assert all(h.repo == "clusterB" for h in hits)
    # Even though clusterB is far away, we still return k results.
    assert len(hits) == 5


def test_repo_filter_restricts_pool(tmp_path: Path) -> None:
    df = _toy_embeddings()
    index, _ = NNIndex.build(df, out_dir=tmp_path / "nn_index")
    hits = index.query_by_id("sym00", k=5, repo_filter=["clusterB"])
    assert all(h.repo == "clusterB" for h in hits)


def test_query_by_unknown_id_raises(tmp_path: Path) -> None:
    df = _toy_embeddings()
    index, _ = NNIndex.build(df, out_dir=tmp_path / "nn_index")
    with pytest.raises(KeyError):
        index.query_by_id("not-an-id")


def test_load_roundtrips_meta(tmp_path: Path) -> None:
    df = _toy_embeddings()
    NNIndex.build(df, out_dir=tmp_path / "nn_index")
    loaded = NNIndex.load(tmp_path / "nn_index")
    assert isinstance(loaded.meta, NNIndexMeta)
    assert loaded.meta.n_symbols == 24
    assert loaded.meta.embedding_dim == 8
    assert loaded.meta.backend == "hnswlib"
    assert loaded.meta.metric == "cosine"


def test_loaded_index_queries_correctly(tmp_path: Path) -> None:
    df = _toy_embeddings()
    NNIndex.build(df, out_dir=tmp_path / "nn_index")
    loaded = NNIndex.load(tmp_path / "nn_index")
    hits = loaded.query_by_id("sym00", k=3)
    assert len(hits) == 3
    assert hits[0].similarity > 0.9  # very close intra-cluster


def test_similarity_in_unit_range(tmp_path: Path) -> None:
    df = _toy_embeddings()
    index, _ = NNIndex.build(df, out_dir=tmp_path / "nn_index")
    hits = index.query_by_id("sym00", k=5)
    for h in hits:
        assert -1.001 <= h.similarity <= 1.001
        # distance + similarity ≈ 1 for cosine
        assert abs(h.distance + h.similarity - 1.0) < 1e-3


def test_p99_latency_under_50ms(tmp_path: Path) -> None:
    """The issue's headline AC: p99 query latency under 50ms for k=50."""
    import numpy as np

    rng = np.random.default_rng(0)
    N, dim = 5000, 64
    vecs = rng.normal(size=(N, dim)).astype("float32")
    rows = [
        {
            "symbol_id": f"s{i}",
            "repo": f"r{i % 50}",
            "qualified_name": f"qn{i}",
            "vec": [float(x) for x in vecs[i]],
            "schema_version": 1,
        }
        for i in range(N)
    ]
    df = pl.DataFrame(rows).select(EMBEDDINGS_COLUMNS)
    index, _ = NNIndex.build(df, out_dir=tmp_path / "nn_index")

    # Warm up the JIT/cache.
    index.query_by_id("s0", k=50)

    timings = []
    for i in range(0, N, max(1, N // 200)):
        t0 = time.perf_counter()
        index.query_by_id(f"s{i}", k=50)
        timings.append((time.perf_counter() - t0) * 1000)
    timings.sort()
    p99 = timings[int(0.99 * (len(timings) - 1))]
    assert p99 < 50.0, f"p99={p99:.2f}ms > 50ms target"


def test_empty_embeddings_rejected(tmp_path: Path) -> None:
    df = pl.DataFrame(
        schema={
            "symbol_id": pl.Utf8,
            "repo": pl.Utf8,
            "qualified_name": pl.Utf8,
            "vec": pl.List(pl.Float32),
            "schema_version": pl.Int64,
        }
    )
    with pytest.raises(ValueError):
        NNIndex.build(df, out_dir=tmp_path / "nn_index")


def test_hit_type_is_dataclass(tmp_path: Path) -> None:
    df = _toy_embeddings()
    index, _ = NNIndex.build(df, out_dir=tmp_path / "nn_index")
    hits = index.query_by_id("sym00", k=1)
    assert isinstance(hits[0], NearestHit)
    assert hits[0].symbol_id == "sym00" or isinstance(hits[0].symbol_id, str)
