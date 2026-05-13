"""Tests for the evidence-retrieval module.

Covers the four acceptance criteria from issue Orchestrators-c0d:

* (a) 12 instances across 8 repos, ≤8K token budget, ≥1 snippet per repo
* (b) missing files don't crash the pack
* (c) duplicate neighbors are deduped across instances
* (d) docstrings/comments included when present
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import pytest

from ctkr.evidence import (
    DEFAULT_TOKEN_BUDGET,
    EvidencePack,
    InstanceEvidence,
    NeighborEvidence,
    build_evidence_pack,
)


# ----- fixtures -----


@pytest.fixture
def synth_corpus(tmp_path: Path) -> Path:
    """Create a fake orchestrators_root with 8 repos × N small files each.

    Each repo holds one labeled class with a docstring plus 2 small
    methods. Lines are deterministic so tests can pin them.
    """
    layouts = [
        ("py", "py", '"""', '"""'),
        ("ts", "ts", "/**", " */"),
        ("py", "py", '"""', '"""'),
        ("ts", "ts", "/**", " */"),
        ("py", "py", "#", None),  # generic-comment style
        ("ts", "ts", "//", None),
        ("py", "py", '"""', '"""'),
        ("ts", "ts", "/**", " */"),
    ]
    for i, (lang, ext, open_doc, close_doc) in enumerate(layouts):
        repo = tmp_path / f"repo{i}"
        (repo / "src").mkdir(parents=True)
        src_path = repo / "src" / f"thing.{ext}"
        if close_doc is None:
            doc_block = f"{open_doc} A {lang} thing in repo{i}."
        else:
            doc_block = f"{open_doc}\n A {lang} thing in repo{i}.\n{close_doc}"

        src_path.write_text(
            "// leading filler\n"
            "// leading filler\n"
            "// leading filler\n"
            f"class Thing{i} {{\n"
            f"  {doc_block}\n"
            f"  method_a() {{ return 1; }}\n"
            f"  method_b() {{ return 2; }}\n"
            f"}}\n"
        )
    return tmp_path


@pytest.fixture
def synth_graph(synth_corpus: Path) -> nx.MultiDiGraph:
    """Mirror the synthetic corpus into a NetworkX graph.

    12 instance anchor symbols are placed across 8 repos. Each anchor is
    a 'class' Thing<i>; each has two method neighbors via CONTAINS edges.
    Some neighbors are deliberately shared across anchors so the dedup
    test has something to chew on.
    """
    g = nx.MultiDiGraph()

    # 8 anchor symbols, one per repo, each on line 4 with end_line=8.
    for i in range(8):
        lang = "py" if i % 2 == 0 else "ts"
        ext = "py" if lang == "py" else "ts"
        g.add_node(
            f"a{i}",
            repo=f"repo{i}",
            file=f"src/thing.{ext}",
            qualified_name=f"Thing{i}",
            kind="class",
            line=4,
            end_line=8,
            signature=None,
            language=lang,
        )

    # 4 extra anchors so the pack candidate count is 12 total: re-use
    # 4 of the repos with second anchors pointing at the same file.
    for j, i in enumerate([0, 1, 2, 3]):
        lang = "py" if i % 2 == 0 else "ts"
        ext = "py" if lang == "py" else "ts"
        g.add_node(
            f"b{j}",
            repo=f"repo{i}",
            file=f"src/thing.{ext}",
            qualified_name=f"Thing{i}.method_a",
            kind="method",
            line=6,
            end_line=6,
            signature="() => number",
            language=lang,
        )

    # Shared neighbor that ALL anchors point at via CALLS — this forces
    # the dedup test to keep it on exactly one anchor.
    g.add_node(
        "shared",
        repo="repo-shared",
        file="util.py",
        qualified_name="util.shared_helper",
        kind="function",
        signature="(x: int) -> int",
    )
    for i in range(8):
        g.add_edge(f"a{i}", "shared", key="CALLS", kind="CALLS")
    # And per-anchor unique neighbors via CONTAINS.
    for i in range(8):
        nb = f"a{i}_method"
        lang = "py" if i % 2 == 0 else "ts"
        g.add_node(
            nb,
            repo=f"repo{i}",
            file=f"src/thing.{lang}",
            qualified_name=f"Thing{i}.method_b",
            kind="method",
            signature="() => number",
        )
        g.add_edge(f"a{i}", nb, key="CONTAINS", kind="CONTAINS")
    return g


# ----- acceptance criteria -----


def test_acceptance_a_eight_repos_within_budget(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    """(a) 12 instances across 8 repos → ≤8K tokens, ≥1 snippet per repo."""
    symbol_ids = [f"a{i}" for i in range(8)] + ["b0", "b1", "b2", "b3"]
    pack = build_evidence_pack(
        synth_graph,
        symbol_ids,
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
        token_budget=DEFAULT_TOKEN_BUDGET,
    )
    assert pack.estimated_tokens <= DEFAULT_TOKEN_BUDGET
    repos = {i.repo for i in pack.instances}
    assert repos == {f"repo{i}" for i in range(8)}, f"missing repos: {repos}"
    assert len(pack.instances) >= 8


def test_acceptance_b_missing_file_doesnt_crash(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    """(b) Missing files don't crash; recorded as notes."""
    # Add an anchor whose file was deleted post-index.
    synth_graph.add_node(
        "ghost",
        repo="repo0",
        file="src/nonexistent.py",
        qualified_name="Ghost",
        kind="class",
        line=1,
        end_line=2,
        language="py",
    )
    pack = build_evidence_pack(
        synth_graph,
        ["ghost", "a0"],
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
    )
    assert any("not found" in n for n in pack.notes)
    assert any(i.symbol_id == "a0" for i in pack.instances)


def test_acceptance_c_neighbor_dedup(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    """(c) The 'shared' neighbor appears at most once across instances."""
    symbol_ids = [f"a{i}" for i in range(8)]
    pack = build_evidence_pack(
        synth_graph,
        symbol_ids,
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
    )
    shared_count = sum(
        1 for inst in pack.instances for nb in inst.neighbors if nb.symbol_id == "shared"
    )
    assert shared_count == 1, f"'shared' appeared {shared_count} times across instances"


def test_acceptance_d_docstrings_included(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    """(d) When a docstring/comment is present, it's surfaced on the instance."""
    pack = build_evidence_pack(
        synth_graph,
        [f"a{i}" for i in range(8)],
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
    )
    docstring_count = sum(1 for i in pack.instances if i.docstring)
    assert docstring_count >= 6, "expected most synthetic instances to surface a docstring"


# ----- behavior tests -----


def test_repo_balance_round_robin(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    """First N instances should hit N distinct repos when balance_repos=True."""
    # All from a single repo (with multiple anchors) plus one from each
    # other repo. Round-robin must surface non-repo0 before a second repo0.
    symbol_ids = ["a0", "b0", "a1", "b1", "a2"]
    pack = build_evidence_pack(
        synth_graph,
        symbol_ids,
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
        balance_repos=True,
        token_budget=2_000_000,  # don't truncate
    )
    seen_repos: list[str] = []
    for inst in pack.instances:
        seen_repos.append(inst.repo)
    # Expect: repo0, repo1, repo2 first, then any extras.
    assert seen_repos[:3] == ["repo0", "repo1", "repo2"]


def test_budget_truncates_breadth_first(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    """Tiny budget — pack drops instances rather than expanding fewer."""
    pack = build_evidence_pack(
        synth_graph,
        [f"a{i}" for i in range(8)],
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
        token_budget=200,  # forces truncation
        max_neighbors_per_instance=6,
    )
    assert pack.truncated is True
    assert len(pack.instances) < 8


def test_returns_evidence_pack_type(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    pack = build_evidence_pack(
        synth_graph,
        ["a0"],
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
    )
    assert isinstance(pack, EvidencePack)
    assert pack.source_kind == "motif"
    assert pack.source_ref == "m-test"
    for inst in pack.instances:
        assert isinstance(inst, InstanceEvidence)
        for nb in inst.neighbors:
            assert isinstance(nb, NeighborEvidence)


def test_unknown_symbol_recorded_as_note(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    pack = build_evidence_pack(
        synth_graph,
        ["does-not-exist", "a0"],
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
    )
    assert any("not in graph" in n for n in pack.notes)
    assert any(i.symbol_id == "a0" for i in pack.instances)


def test_repos_covered_field_matches_instances(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    pack = build_evidence_pack(
        synth_graph,
        ["a0", "a1", "a2"],
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
    )
    assert set(pack.repos_covered) == {"repo0", "repo1", "repo2"}


def test_token_estimator_override(
    synth_graph: nx.MultiDiGraph, synth_corpus: Path
) -> None:
    """A custom estimator gets called instead of the default."""
    called: list[str] = []

    def fake_estimate(s: str) -> int:
        called.append(s)
        return len(s)  # 1 token per char — extremely conservative

    pack = build_evidence_pack(
        synth_graph,
        ["a0"],
        source_kind="motif",
        source_ref="m-test",
        orchestrators_root=synth_corpus,
        token_budget=10_000_000,
        estimate_tokens=fake_estimate,
    )
    assert called  # estimator was invoked
    assert pack.estimated_tokens > 0


def test_zero_neighbors_when_isolated(synth_corpus: Path) -> None:
    """An isolated symbol gives an InstanceEvidence with neighbors=[]."""
    g = nx.MultiDiGraph()
    g.add_node(
        "iso",
        repo="repo0",
        file="src/thing.py",
        qualified_name="Iso",
        kind="class",
        line=4,
        end_line=8,
        language="py",
    )
    pack = build_evidence_pack(
        g,
        ["iso"],
        source_kind="motif",
        source_ref="m-iso",
        orchestrators_root=synth_corpus,
    )
    assert len(pack.instances) == 1
    assert pack.instances[0].neighbors == []
