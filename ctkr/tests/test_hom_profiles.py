"""Tests for ctkr.hom_profiles — per-symbol typed-edge profile vectors."""

from __future__ import annotations

import json
from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.graph_loader import EDGE_KINDS
from ctkr.hom_profiles import (
    DIM_IDX,
    DIMS,
    NDIM,
    compute_hom_profiles,
    write_hom_profiles,
    write_manifest,
)
from ctkr.schema import (
    HOM_PROFILES_COLUMNS,
    SCHEMA_VERSION,
    ArtifactManifest,
    HomProfileRow,
)


def _toy_graph() -> nx.MultiDiGraph:
    """A graph mixing CONTAINS, CALLS, and a file→method CONTAINS edge.

    Layout::

        file:f1 ──CONTAINS──▶ method:m_a
        method:m_a ──CALLS──▶ method:m_b
        method:m_a ──CONTAINS──▶ method:m_b   (extra parallel edge of a different kind)
        method:m_b ──CALLS──▶ method:m_a
    """
    g = nx.MultiDiGraph()
    g.add_node("f1", repo="r", qualified_name="r.f1", kind="file")
    g.add_node("m_a", repo="r", qualified_name="r.f1.m_a", kind="method")
    g.add_node("m_b", repo="r", qualified_name="r.f1.m_b", kind="method")

    g.add_edge("f1", "m_a", key="CONTAINS", kind="CONTAINS")
    g.add_edge("m_a", "m_b", key="CALLS", kind="CALLS")
    g.add_edge("m_a", "m_b", key="CONTAINS", kind="CONTAINS")
    g.add_edge("m_b", "m_a", key="CALLS", kind="CALLS")
    return g


def test_ndim_matches_edge_kinds() -> None:
    assert NDIM == 2 * len(EDGE_KINDS)
    # First two dims belong to the first edge kind, in/out order.
    assert DIMS[0] == (EDGE_KINDS[0], "in")
    assert DIMS[1] == (EDGE_KINDS[0], "out")


def test_raw_counts_on_known_graph() -> None:
    g = _toy_graph()
    df, stats = compute_hom_profiles(g)

    assert df.height == 3
    assert stats.n_nodes_emitted == 3
    assert stats.n_edges == 4
    assert stats.profile_vec_dim == NDIM
    assert stats.kinds_filter == ()

    rows = {r["symbol_id"]: r for r in df.iter_rows(named=True)}
    contains_in = DIM_IDX[("CONTAINS", "in")]
    contains_out = DIM_IDX[("CONTAINS", "out")]
    calls_in = DIM_IDX[("CALLS", "in")]
    calls_out = DIM_IDX[("CALLS", "out")]

    # f1 only has a CONTAINS:out → m_a edge.
    f1_vec = rows["f1"]["profile_vec"]
    assert f1_vec[contains_out] == 1
    assert f1_vec[contains_in] == 0
    assert f1_vec[calls_in] == 0
    assert f1_vec[calls_out] == 0

    # m_a: CONTAINS:in from f1, CONTAINS:out to m_b, CALLS:out to m_b, CALLS:in from m_b.
    m_a_vec = rows["m_a"]["profile_vec"]
    assert m_a_vec[contains_in] == 1
    assert m_a_vec[contains_out] == 1
    assert m_a_vec[calls_in] == 1
    assert m_a_vec[calls_out] == 1

    # m_b: CONTAINS:in from m_a, CALLS:in from m_a, CALLS:out to m_a.
    m_b_vec = rows["m_b"]["profile_vec"]
    assert m_b_vec[contains_in] == 1
    assert m_b_vec[contains_out] == 0
    assert m_b_vec[calls_in] == 1
    assert m_b_vec[calls_out] == 1


def test_kinds_filter_drops_rows_but_preserves_neighbor_counts() -> None:
    """Filtering 'file' must NOT zero out the file→method CONTAINS edge."""
    g = _toy_graph()
    df, stats = compute_hom_profiles(g, kinds_filter={"file"})

    assert df.height == 2
    assert stats.kinds_filter == ("file",)
    ids = set(df["symbol_id"].to_list())
    assert ids == {"m_a", "m_b"}

    contains_in = DIM_IDX[("CONTAINS", "in")]
    m_a_row = next(r for r in df.iter_rows(named=True) if r["symbol_id"] == "m_a")
    # The CONTAINS:in count on m_a must still reflect the file→m_a edge.
    assert m_a_row["profile_vec"][contains_in] == 1


def test_output_is_deterministic() -> None:
    g = _toy_graph()
    df1, _ = compute_hom_profiles(g)
    df2, _ = compute_hom_profiles(g)
    assert df1.equals(df2)
    # Lexicographic ordering — f1 < m_a < m_b.
    assert df1["symbol_id"].to_list() == ["f1", "m_a", "m_b"]


def test_empty_kinds_filter_keeps_all() -> None:
    g = _toy_graph()
    df_none, _ = compute_hom_profiles(g, kinds_filter=None)
    df_empty, _ = compute_hom_profiles(g, kinds_filter=set())
    assert df_none.equals(df_empty)


def test_write_hom_profiles_roundtrip(tmp_path: Path) -> None:
    g = _toy_graph()
    df, _ = compute_hom_profiles(g)
    out = tmp_path / "hom_profiles.parquet"
    write_hom_profiles(df, out)

    back = pl.read_parquet(out)
    assert back.columns == list(HOM_PROFILES_COLUMNS)
    assert back.height == 3
    # UInt32 list dtype survives the round trip.
    assert back.schema["profile_vec"] == pl.List(pl.UInt32)
    for d in back.to_dicts():
        HomProfileRow.model_validate(d)


def test_write_hom_profiles_forces_uint32_on_disk(tmp_path: Path) -> None:
    """Maximal-precision contract: profile_vec is integer on disk regardless
    of in-memory dtype. A caller who happens to hand us a Float column still
    gets UInt32 in the parquet — no silent float-leakage downstream."""
    df = pl.DataFrame(
        {
            "symbol_id": ["s"],
            "repo": ["r"],
            "qualified_name": ["q"],
            "profile_vec": pl.Series(
                "profile_vec", [[1.0, 2.0]], dtype=pl.List(pl.Float64)
            ),
            "schema_version": [SCHEMA_VERSION],
        }
    )
    out = tmp_path / "from_float.parquet"
    write_hom_profiles(df, out)

    back = pl.read_parquet(out)
    assert back.schema["profile_vec"] == pl.List(pl.UInt32)
    assert back["profile_vec"][0].to_list() == [1, 2]


def test_write_manifest_creates_fresh(tmp_path: Path) -> None:
    path = write_manifest(
        tmp_path,
        hom_profiles=True,
        n_hom_profiles=42,
        profile_vec_dim=NDIM,
    )
    assert path == (tmp_path / "ctkr" / "manifest.json").resolve()
    data = json.loads(path.read_text())
    assert data["hom_profiles"] is True
    assert data["n_hom_profiles"] == 42
    assert data["profile_vec_dim"] == NDIM
    m = ArtifactManifest.model_validate(data)
    assert m.hom_profiles is True


def test_write_manifest_merges_without_clobbering(tmp_path: Path) -> None:
    """An existing manifest's unrelated presence flags must survive a merge."""
    ctkr_dir = tmp_path / "ctkr"
    ctkr_dir.mkdir()
    existing = ArtifactManifest(
        generated_at="2026-05-11T00:00:00Z",
        metacoding_data_dir=str(tmp_path),
        embeddings=True,
        n_symbols=300_000,
        embedding_dim=128,
    )
    (ctkr_dir / "manifest.json").write_text(existing.model_dump_json(indent=2))

    write_manifest(
        tmp_path,
        hom_profiles=True,
        n_hom_profiles=7,
        profile_vec_dim=NDIM,
    )

    merged = ArtifactManifest.model_validate_json(
        (ctkr_dir / "manifest.json").read_text()
    )
    assert merged.embeddings is True
    assert merged.n_symbols == 300_000
    assert merged.embedding_dim == 128
    assert merged.hom_profiles is True
    assert merged.n_hom_profiles == 7
    assert merged.profile_vec_dim == NDIM


def test_write_manifest_preserves_unknown_fields(tmp_path: Path) -> None:
    """A manifest written by a future schema version must round-trip
    through this version's write_manifest without losing fields."""
    ctkr_dir = tmp_path / "ctkr"
    ctkr_dir.mkdir()
    future_manifest = {
        "schema_version": 1,
        "generated_at": "2027-01-01T00:00:00Z",
        "metacoding_data_dir": str(tmp_path),
        "embeddings": True,
        "future_artifact": True,
        "n_future": 42,
        "future_meta": {"x": 1, "y": [1, 2, 3]},
    }
    (ctkr_dir / "manifest.json").write_text(json.dumps(future_manifest))

    write_manifest(
        tmp_path,
        hom_profiles=True,
        n_hom_profiles=7,
        profile_vec_dim=NDIM,
    )

    on_disk = json.loads((ctkr_dir / "manifest.json").read_text())
    assert on_disk["future_artifact"] is True
    assert on_disk["n_future"] == 42
    assert on_disk["future_meta"] == {"x": 1, "y": [1, 2, 3]}
    assert on_disk["hom_profiles"] is True
    assert on_disk["n_hom_profiles"] == 7


def test_write_manifest_overwrites_malformed(tmp_path: Path) -> None:
    ctkr_dir = tmp_path / "ctkr"
    ctkr_dir.mkdir()
    (ctkr_dir / "manifest.json").write_text("{not json")

    write_manifest(
        tmp_path,
        hom_profiles=True,
        n_hom_profiles=1,
        profile_vec_dim=NDIM,
    )
    merged = ArtifactManifest.model_validate_json(
        (ctkr_dir / "manifest.json").read_text()
    )
    assert merged.hom_profiles is True
