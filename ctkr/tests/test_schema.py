"""Round-trip tests for L1 and L3 schemas.

These tests are intentionally narrow: they verify that pydantic models
serialize to parquet/JSONL and round-trip without drift. They do NOT
exercise any of the L1 algorithms — those tests live alongside the
algorithm modules when they land.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import polars as pl
import pytest

from ctkr.schema import (
    EMBEDDINGS_COLUMNS,
    HOM_PROFILES_COLUMNS,
    MOTIF_INSTANCES_COLUMNS,
    MOTIFS_COLUMNS,
    SCHEMA_VERSION,
    SHAPE_PDS_COLUMNS,
    WASSERSTEIN_H1_COLUMNS,
    ArtifactManifest,
    EmbeddingRow,
    HomProfileRow,
    MotifInstanceRow,
    MotifRow,
    NNIndexMeta,
    ShapePDRow,
    WassersteinH1Row,
)
from ctkr.schema_l3 import SCHEMA_VERSION as L3_SCHEMA_VERSION
from ctkr.schema_l3 import EvidenceRow, LineRange, PatternRow

# ----- L1 schema tests -----


def test_embedding_row_parquet_roundtrip(tmp_path: Path) -> None:
    rows = [
        EmbeddingRow(symbol_id="sym1", repo="r", qualified_name="foo.bar", vec=[0.1, 0.2, 0.3]),
        EmbeddingRow(symbol_id="sym2", repo="r", qualified_name="foo.baz", vec=[0.4, 0.5, 0.6]),
    ]
    out = tmp_path / "embeddings.parquet"
    df = pl.DataFrame([r.model_dump() for r in rows])
    df = df.select(EMBEDDINGS_COLUMNS)  # pin column order
    df.write_parquet(out)

    back = pl.read_parquet(out)
    assert back.columns == list(EMBEDDINGS_COLUMNS)
    assert back.height == 2

    # Validate every row re-parses through the pydantic model.
    for d in back.to_dicts():
        EmbeddingRow.model_validate(d)


def test_motif_and_instance_roundtrip(tmp_path: Path) -> None:
    motifs = [
        MotifRow(
            motif_id="m1",
            signature="A-CALLS->B-IMPLEMENTS->C",
            size_nodes=3,
            size_edges=2,
            support=42,
            repo_coverage=["cline", "crewAI"],
            edge_kinds=["CALLS", "IMPLEMENTS"],
        ),
    ]
    instances = [
        MotifInstanceRow(motif_id="m1", symbol_id="s1", repo="cline", file="src/a.ts", line=10),
        MotifInstanceRow(motif_id="m1", symbol_id="s2", repo="crewAI", file="src/b.py", line=20),
    ]
    mpath = tmp_path / "motifs.parquet"
    ipath = tmp_path / "motif_instances.parquet"

    pl.DataFrame([m.model_dump() for m in motifs]).select(MOTIFS_COLUMNS).write_parquet(mpath)
    pl.DataFrame([i.model_dump() for i in instances]).select(
        MOTIF_INSTANCES_COLUMNS
    ).write_parquet(ipath)

    mb = pl.read_parquet(mpath)
    ib = pl.read_parquet(ipath)
    assert mb.columns == list(MOTIFS_COLUMNS)
    assert ib.columns == list(MOTIF_INSTANCES_COLUMNS)

    for d in mb.to_dicts():
        MotifRow.model_validate(d)
    for d in ib.to_dicts():
        MotifInstanceRow.model_validate(d)


def test_shape_pds_roundtrip(tmp_path: Path) -> None:
    rows = [
        ShapePDRow(repo="cline", dim=0, birth=[0.0, 0.1], death=[0.3, 0.4]),
        ShapePDRow(repo="cline", dim=1, birth=[0.05], death=[0.5]),
    ]
    out = tmp_path / "shape_pds.parquet"
    pl.DataFrame([r.model_dump() for r in rows]).select(SHAPE_PDS_COLUMNS).write_parquet(out)
    back = pl.read_parquet(out)
    assert back.columns == list(SHAPE_PDS_COLUMNS)
    for d in back.to_dicts():
        ShapePDRow.model_validate(d)


def test_manifest_json_roundtrip(tmp_path: Path) -> None:
    m = ArtifactManifest(
        generated_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        metacoding_data_dir="/home/dorje/projects/Orchestrators/.metacoding",
        embeddings=True,
        motifs=True,
        motif_instances=True,
        embedding_dim=128,
        n_symbols=300_000,
        n_motifs=512,
        n_motif_instances=21_337,
    )
    out = tmp_path / "manifest.json"
    out.write_text(m.model_dump_json(indent=2))
    back = ArtifactManifest.model_validate_json(out.read_text())
    assert back == m
    assert back.schema_version == SCHEMA_VERSION


def test_manifest_extended_presence_flags(tmp_path: Path) -> None:
    """The wasserstein_h1 / centrality / spectral_clusters flags round-trip."""
    m = ArtifactManifest(
        generated_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        metacoding_data_dir="/tmp/x",
        wasserstein_h1=True,
        centrality=True,
        spectral_clusters=True,
    )
    back = ArtifactManifest.model_validate_json(m.model_dump_json())
    assert back.wasserstein_h1 is True
    assert back.centrality is True
    assert back.spectral_clusters is True


def test_wasserstein_h1_roundtrip(tmp_path: Path) -> None:
    rows = [
        WassersteinH1Row(repo_a="cline", repo_b="crewAI", distance=0.0),
        WassersteinH1Row(repo_a="cline", repo_b="mastra", distance=1.42),
        WassersteinH1Row(repo_a="crewAI", repo_b="mastra", distance=0.71),
    ]
    out = tmp_path / "wasserstein_h1.parquet"
    pl.DataFrame([r.model_dump() for r in rows]).select(
        WASSERSTEIN_H1_COLUMNS
    ).write_parquet(out)
    back = pl.read_parquet(out)
    assert back.columns == list(WASSERSTEIN_H1_COLUMNS)
    for d in back.to_dicts():
        WassersteinH1Row.model_validate(d)


def test_wasserstein_h1_back_compat_missing_schema_version() -> None:
    """The on-disk artifact predating this schema lacks schema_version;
    the model must default it on read."""
    raw = {"repo_a": "a", "repo_b": "b", "distance": 0.5}
    row = WassersteinH1Row.model_validate(raw)
    assert row.schema_version == SCHEMA_VERSION


def test_wasserstein_h1_distance_nonnegative() -> None:
    with pytest.raises(Exception):
        WassersteinH1Row(repo_a="a", repo_b="b", distance=-0.1)


def test_nn_index_meta_roundtrip(tmp_path: Path) -> None:
    meta = NNIndexMeta(
        backend="hnswlib",
        metric="cosine",
        embedding_dim=128,
        n_symbols=300_000,
        built_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        embeddings_source="../embeddings.parquet",
    )
    out = tmp_path / "nn_index.meta.json"
    out.write_text(meta.model_dump_json(indent=2))
    back = NNIndexMeta.model_validate_json(out.read_text())
    assert back == meta


def test_schema_version_is_int() -> None:
    assert isinstance(SCHEMA_VERSION, int)
    assert SCHEMA_VERSION >= 1


def test_hom_profile_row_parquet_roundtrip(tmp_path: Path) -> None:
    rows = [
        HomProfileRow(
            symbol_id="sym1",
            repo="r",
            qualified_name="foo.bar",
            profile_vec=[0, 1, 2, 0, 5],
        ),
        HomProfileRow(
            symbol_id="sym2",
            repo="r",
            qualified_name="foo.baz",
            profile_vec=[3, 0, 0, 0, 7],
        ),
    ]
    out = tmp_path / "hom_profiles.parquet"
    df = pl.DataFrame([r.model_dump() for r in rows]).select(HOM_PROFILES_COLUMNS)
    df.write_parquet(out)

    back = pl.read_parquet(out)
    assert back.columns == list(HOM_PROFILES_COLUMNS)
    assert back.height == 2
    for d in back.to_dicts():
        HomProfileRow.model_validate(d)


def test_hom_profile_row_rejects_negative_counts() -> None:
    from pydantic import ValidationError

    with pytest.raises(ValidationError):
        HomProfileRow(
            symbol_id="x",
            repo="r",
            qualified_name="q",
            profile_vec=[0, -1, 0],
        )


def test_manifest_hom_profiles_flag_roundtrip() -> None:
    m = ArtifactManifest(
        generated_at=datetime(2026, 6, 2, tzinfo=timezone.utc),
        metacoding_data_dir="/tmp/metacoding-scip",
        hom_profiles=True,
        n_hom_profiles=189_179,
        profile_vec_dim=28,
    )
    back = ArtifactManifest.model_validate_json(m.model_dump_json())
    assert back.hom_profiles is True
    assert back.n_hom_profiles == 189_179
    assert back.profile_vec_dim == 28
    # Default zeros / falses on unrelated fields survive the round trip.
    assert back.embeddings is False
    assert back.n_motifs == 0


# ----- L3 schema tests -----


def test_pattern_row_jsonl_roundtrip(tmp_path: Path) -> None:
    p = PatternRow(
        pattern_id="p:motif:m1@motif-labeler-v1@claude-opus-4-7",
        source_kind="motif",
        source_ref="m1",
        label="Tool registry decorator",
        description="A function decorator that registers callables into a shared tool registry.",
        instances=["s1", "s2", "s3"],
        confidence=0.87,
        llm_model="claude-opus-4-7",
        llm_temperature=0.0,
        prompt_version="motif-labeler:v1",
        generated_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
    )
    out = tmp_path / "patterns.jsonl"
    out.write_text(p.model_dump_json() + "\n")

    line = out.read_text().strip()
    back = PatternRow.model_validate_json(line)
    assert back == p
    assert back.schema_version == L3_SCHEMA_VERSION


def test_evidence_row_jsonl_roundtrip(tmp_path: Path) -> None:
    e = EvidenceRow(
        pattern_id="p:motif:m1@motif-labeler-v1@claude-opus-4-7",
        repo="cline",
        file="src/tools/registry.ts",
        line_range=LineRange(start=42, end=50),
        snippet="export function tool(name: string) {\n  return (target: any) => { registry.set(name, target); };\n}",
        context="ToolRegistry",
    )
    out = tmp_path / "evidence.jsonl"
    out.write_text(e.model_dump_json() + "\n")
    back = EvidenceRow.model_validate_json(out.read_text().strip())
    assert back == e


def test_provenance_fields_mandatory() -> None:
    """llm_model / llm_temperature / prompt_version must all be required."""
    base = {
        "pattern_id": "x",
        "source_kind": "motif",
        "source_ref": "m1",
        "label": "x",
        "description": "x",
        "instances": [],
        "confidence": 0.5,
        "generated_at": "2026-05-11T00:00:00Z",
    }
    for missing in ("llm_model", "llm_temperature", "prompt_version"):
        bad = {**base, "llm_model": "m", "llm_temperature": 0.0, "prompt_version": "p"}
        del bad[missing]
        with pytest.raises(Exception):
            PatternRow.model_validate(bad)


def test_pattern_confidence_bounded() -> None:
    """Confidence must be in [0, 1]."""
    base = dict(
        pattern_id="x",
        source_kind="motif",
        source_ref="m1",
        label="x",
        description="x",
        instances=[],
        llm_model="m",
        llm_temperature=0.0,
        prompt_version="p",
        generated_at=datetime.now(tz=timezone.utc),
    )
    with pytest.raises(Exception):
        PatternRow(**base, confidence=1.5)  # type: ignore[arg-type]
    with pytest.raises(Exception):
        PatternRow(**base, confidence=-0.1)  # type: ignore[arg-type]


def test_l3_pattern_jsonl_appendable(tmp_path: Path) -> None:
    """JSONL append model: many rows, line-by-line load."""
    rows = [
        PatternRow(
            pattern_id=f"p:{i}",
            source_kind="motif",
            source_ref=f"m{i}",
            label="l",
            description="d",
            instances=[],
            confidence=0.5,
            llm_model="m",
            llm_temperature=0.0,
            prompt_version="p:v1",
            generated_at=datetime(2026, 5, 11, tzinfo=timezone.utc),
        )
        for i in range(5)
    ]
    out = tmp_path / "patterns.jsonl"
    with out.open("w") as f:
        for r in rows:
            f.write(r.model_dump_json() + "\n")

    loaded = [PatternRow.model_validate_json(line) for line in out.read_text().splitlines() if line]
    assert len(loaded) == 5
    assert [r.pattern_id for r in loaded] == [f"p:{i}" for i in range(5)]
