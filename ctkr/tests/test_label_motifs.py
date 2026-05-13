"""Tests for the L3 motif labeler.

These tests use a mock LLM provider (no API key, no network) — the same
pattern as ``test_llm.py``. They exercise:

* Pattern-ID determinism + provenance-sensitivity.
* Prompt rendering — all evidence sections appear.
* The end-to-end ``label_motifs`` driver writes valid JSONL.
* Idempotency — re-running the driver skips already-labeled motifs.
* ``--force`` bypasses the skip.
* The MotifLabelOutput schema validates the structured response.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, ClassVar

import networkx as nx
import polars as pl
import pytest

from ctkr.label_motifs import (
    DEFAULT_PROMPT_VERSION,
    MotifLabelOutput,
    label_motif,
    label_motifs,
    pattern_id_for_motif,
    render_prompt,
)
from ctkr.llm import LLMClient, _ProviderResponse
from ctkr.schema_l3 import EvidenceRow, PatternRow


# ----- mock provider -----


@dataclass
class _MockProvider:
    name: ClassVar[str] = "anthropic"
    env_var: ClassVar[str] = "ANTHROPIC_API_KEY"

    responses: Iterable[dict[str, Any]] = field(default_factory=list)
    input_tokens: int = 100
    output_tokens: int = 50
    calls: list[dict[str, Any]] = field(default_factory=list)
    _it: Any = None

    def __post_init__(self) -> None:
        self._it = iter(self.responses)

    def complete(self, *a, **kw):  # pragma: no cover — not used here
        raise NotImplementedError

    def complete_structured(
        self,
        prompt: str,
        *,
        model: str,
        schema,
        temperature: float,
        max_tokens: int,
        system: str | None,
    ):
        self.calls.append(
            {"prompt": prompt, "model": model, "temperature": temperature, "schema": schema.__name__}
        )
        parsed = next(self._it)
        return (
            _ProviderResponse(
                text=json.dumps(parsed),
                input_tokens=self.input_tokens,
                output_tokens=self.output_tokens,
            ),
            parsed,
        )


# ----- corpus fixture -----


@pytest.fixture
def synth_corpus(tmp_path: Path) -> Path:
    """A tiny 3-repo corpus with one instantiable anchor each."""
    for i, repo in enumerate(("alpha", "beta", "gamma")):
        rd = tmp_path / repo / "src"
        rd.mkdir(parents=True)
        (rd / "tool.py").write_text(
            "# leading filler\n"
            "# leading filler\n"
            "# leading filler\n"
            f"def tool_{i}(name):\n"
            f'    """Register {repo} tool."""\n'
            f"    registry.set(name, lambda: {i})\n"
            "    return name\n"
        )
    return tmp_path


@pytest.fixture
def synth_graph(synth_corpus: Path) -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for i, repo in enumerate(("alpha", "beta", "gamma")):
        g.add_node(
            f"anchor_{repo}",
            repo=repo,
            file="src/tool.py",
            qualified_name=f"tool_{i}",
            kind="function",
            line=4,
            end_line=7,
            signature=f"def tool_{i}(name)",
            language="py",
        )
    return g


@pytest.fixture
def motifs_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "motif_id": ["m1"],
            "signature": ["function-CALLS->call"],
            "size_nodes": [2],
            "size_edges": [1],
            "support": [3],
            "repo_coverage": [["alpha", "beta", "gamma"]],
            "edge_kinds": [["CALLS"]],
            "schema_version": [1],
        }
    )


@pytest.fixture
def instances_df() -> pl.DataFrame:
    return pl.DataFrame(
        {
            "motif_id": ["m1", "m1", "m1"],
            "symbol_id": ["anchor_alpha", "anchor_beta", "anchor_gamma"],
            "repo": ["alpha", "beta", "gamma"],
            "file": ["src/tool.py", "src/tool.py", "src/tool.py"],
            "line": [4, 4, 4],
            "schema_version": [1, 1, 1],
        }
    )


# ----- pattern_id -----


def test_pattern_id_is_deterministic() -> None:
    a = pattern_id_for_motif("m1", prompt_version="p:v1", llm_model="claude-x")
    b = pattern_id_for_motif("m1", prompt_version="p:v1", llm_model="claude-x")
    assert a == b


def test_pattern_id_changes_with_prompt_version() -> None:
    a = pattern_id_for_motif("m1", prompt_version="p:v1", llm_model="claude-x")
    b = pattern_id_for_motif("m1", prompt_version="p:v2", llm_model="claude-x")
    assert a != b


def test_pattern_id_changes_with_model() -> None:
    a = pattern_id_for_motif("m1", prompt_version="p:v1", llm_model="claude-x")
    b = pattern_id_for_motif("m1", prompt_version="p:v1", llm_model="claude-y")
    assert a != b


# ----- render_prompt -----


def test_render_prompt_includes_signature_and_evidence(
    synth_corpus: Path, synth_graph: nx.MultiDiGraph
) -> None:
    from ctkr.evidence import build_evidence_pack

    pack = build_evidence_pack(
        synth_graph,
        ["anchor_alpha", "anchor_beta"],
        source_kind="motif",
        source_ref="m1",
        orchestrators_root=synth_corpus,
        token_budget=4000,
    )
    motif = {
        "motif_id": "m1",
        "signature": "function-CALLS->call",
        "size_nodes": 2,
        "size_edges": 1,
        "support": 3,
        "repo_coverage": ["alpha", "beta", "gamma"],
        "edge_kinds": ["CALLS"],
    }
    prompt = render_prompt(motif, pack)
    assert "m1" in prompt
    assert "function-CALLS->call" in prompt
    assert "tool_0" in prompt or "tool_1" in prompt
    assert "Instance 1" in prompt
    assert "MotifLabelOutput" in prompt


# ----- one motif -----


def test_label_motif_emits_well_formed_rows(
    synth_corpus: Path, synth_graph: nx.MultiDiGraph
) -> None:
    from ctkr.evidence import build_evidence_pack

    provider = _MockProvider(
        responses=[
            {
                "label": "Tool registry decorator",
                "description": (
                    "A function that registers itself into a shared tool "
                    "registry by name, then returns the name."
                ),
                "confidence": 0.85,
            }
        ]
    )
    client = LLMClient()
    client.register_provider(provider)

    pack = build_evidence_pack(
        synth_graph,
        ["anchor_alpha", "anchor_beta"],
        source_kind="motif",
        source_ref="m1",
        orchestrators_root=synth_corpus,
        token_budget=4000,
    )
    motif = {
        "motif_id": "m1",
        "signature": "function-CALLS->call",
        "size_nodes": 2,
        "size_edges": 1,
        "support": 3,
        "repo_coverage": ["alpha", "beta"],
        "edge_kinds": ["CALLS"],
    }
    out = label_motif(
        motif=motif,
        pack=pack,
        client=client,
        model="claude-haiku-4-5-20251001",
        prompt_version="motif-labeler:v1",
    )
    assert out.pattern.label == "Tool registry decorator"
    assert out.pattern.source_kind == "motif"
    assert out.pattern.source_ref == "m1"
    assert out.pattern.llm_model == "claude-haiku-4-5-20251001"
    assert out.pattern.prompt_version == "motif-labeler:v1"
    assert out.pattern.llm_temperature == 0.0
    assert 0.0 <= out.pattern.confidence <= 1.0
    assert len(out.evidence) == len(pack.instances)
    for ev in out.evidence:
        assert ev.pattern_id == out.pattern.pattern_id


def test_label_motif_invalid_confidence_fails(
    synth_corpus: Path, synth_graph: nx.MultiDiGraph
) -> None:
    from ctkr.evidence import build_evidence_pack
    from ctkr.llm import StructuredOutputError

    provider = _MockProvider(
        responses=[
            {"label": "x", "description": "y", "confidence": 1.5}
        ]
    )
    client = LLMClient()
    client.register_provider(provider)
    pack = build_evidence_pack(
        synth_graph,
        ["anchor_alpha"],
        source_kind="motif",
        source_ref="m1",
        orchestrators_root=synth_corpus,
        token_budget=4000,
    )
    with pytest.raises(StructuredOutputError):
        label_motif(motif={"motif_id": "m1"}, pack=pack, client=client)


# ----- driver -----


def test_label_motifs_writes_jsonl(
    tmp_path: Path,
    synth_corpus: Path,
    synth_graph: nx.MultiDiGraph,
    motifs_df: pl.DataFrame,
    instances_df: pl.DataFrame,
) -> None:
    provider = _MockProvider(
        responses=[
            {
                "label": "Tool registry decorator",
                "description": "Registers a tool into a shared registry.",
                "confidence": 0.9,
            }
        ]
    )
    client = LLMClient()
    client.register_provider(provider)

    out_p = tmp_path / "patterns.jsonl"
    out_e = tmp_path / "evidence.jsonl"
    stats = label_motifs(
        motifs_df=motifs_df,
        instances_df=instances_df,
        graph=synth_graph,
        orchestrators_root=synth_corpus,
        client=client,
        out_patterns=out_p,
        out_evidence=out_e,
        model="claude-haiku-4-5-20251001",
        prompt_version=DEFAULT_PROMPT_VERSION,
    )
    assert stats.n_labeled == 1
    assert stats.n_total == 1
    assert stats.n_failed == 0

    lines = out_p.read_text().splitlines()
    assert len(lines) == 1
    pr = PatternRow.model_validate_json(lines[0])
    assert pr.label == "Tool registry decorator"

    ev_lines = out_e.read_text().splitlines()
    assert len(ev_lines) >= 1
    for line in ev_lines:
        ev = EvidenceRow.model_validate_json(line)
        assert ev.pattern_id == pr.pattern_id


def test_label_motifs_is_idempotent(
    tmp_path: Path,
    synth_corpus: Path,
    synth_graph: nx.MultiDiGraph,
    motifs_df: pl.DataFrame,
    instances_df: pl.DataFrame,
) -> None:
    """Re-running with the same prompt+model skips already-labeled motifs."""
    provider = _MockProvider(
        responses=[
            {"label": "x", "description": "y", "confidence": 0.5},
            # No second response — if the second run called the LLM the
            # iterator would raise StopIteration and the test would fail.
        ]
    )
    client = LLMClient()
    client.register_provider(provider)

    out_p = tmp_path / "patterns.jsonl"
    out_e = tmp_path / "evidence.jsonl"

    kwargs = dict(
        motifs_df=motifs_df,
        instances_df=instances_df,
        graph=synth_graph,
        orchestrators_root=synth_corpus,
        client=client,
        out_patterns=out_p,
        out_evidence=out_e,
    )
    first = label_motifs(**kwargs)
    second = label_motifs(**kwargs)
    assert first.n_labeled == 1
    assert second.n_labeled == 0
    assert second.n_skipped == 1
    # Only one row on disk despite two runs.
    assert len(out_p.read_text().splitlines()) == 1


def test_label_motifs_force_relabels(
    tmp_path: Path,
    synth_corpus: Path,
    synth_graph: nx.MultiDiGraph,
    motifs_df: pl.DataFrame,
    instances_df: pl.DataFrame,
) -> None:
    """``force=True`` bypasses the skip-existing guard."""
    provider = _MockProvider(
        responses=[
            {"label": "v1", "description": "one", "confidence": 0.5},
            {"label": "v2", "description": "two", "confidence": 0.6},
        ]
    )
    client = LLMClient()
    client.register_provider(provider)
    out_p = tmp_path / "patterns.jsonl"
    out_e = tmp_path / "evidence.jsonl"
    base = dict(
        motifs_df=motifs_df,
        instances_df=instances_df,
        graph=synth_graph,
        orchestrators_root=synth_corpus,
        client=client,
        out_patterns=out_p,
        out_evidence=out_e,
    )
    label_motifs(**base)
    label_motifs(**base, force=True)
    # Two rows after force; same pattern_id (caller is responsible for prune).
    lines = out_p.read_text().splitlines()
    assert len(lines) == 2
    pids = [PatternRow.model_validate_json(l).pattern_id for l in lines]
    assert pids[0] == pids[1]


# ----- output schema -----


def test_motif_label_output_validates() -> None:
    ok = MotifLabelOutput(label="x", description="y", confidence=0.5)
    assert ok.label == "x"
    with pytest.raises(Exception):
        MotifLabelOutput(label="x", description="y", confidence=2.0)


def test_anchor_sampling_round_robins_by_repo() -> None:
    """When a motif's instances are dominated by one repo, the sampler
    must spread anchors across all represented repos."""
    from ctkr.label_motifs import _iter_motif_instance_anchors

    # 1 motif. 10 instances from repo alpha, 3 from beta, 2 from gamma.
    df = pl.DataFrame(
        {
            "motif_id": ["m1"] * 15,
            "symbol_id": [f"a{i}" for i in range(10)]
            + [f"b{i}" for i in range(3)]
            + [f"g{i}" for i in range(2)],
            "repo": ["alpha"] * 10 + ["beta"] * 3 + ["gamma"] * 2,
            "file": ["src/x.py"] * 15,
            "line": [1] * 15,
            "schema_version": [1] * 15,
        }
    )
    picks = _iter_motif_instance_anchors(df, "m1", max_instances=6)
    # First three picks should be one-per-repo (sorted: alpha, beta, gamma).
    repos_picked = []
    for sid in picks:
        row = df.filter(pl.col("symbol_id") == sid).row(0, named=True)
        repos_picked.append(row["repo"])
    assert set(repos_picked[:3]) == {"alpha", "beta", "gamma"}
    assert len(picks) == 6
