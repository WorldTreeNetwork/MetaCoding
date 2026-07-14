"""Source-code evidence retrieval for L3 labelers.

Given a structural element (a motif's instances, a role-cluster's
members, an analogy pair), assemble an :class:`EvidencePack` of
typed snippets that an L3 labeler can feed to an LLM.

Responsibilities
----------------

* Look up each instance's repo/file/line in the loaded NetworkX graph.
* Read the source file from ``<orchestrators_root>/<repo>/<file>`` and
  slice the relevant window.
* Pull 1-hop neighbor signatures so the labeler sees calling/called
  context, not just the symbol in isolation.
* Stay under a token budget, preferring *breadth* (more instances /
  more repos) over *depth* (deeper neighbor expansion).
* Guarantee at least one snippet per repo when ``balance_repos=True``
  and the budget allows.
* Deduplicate neighbors that appear across multiple instances.
* Handle missing files (file deleted post-index) by recording a note
  and skipping, rather than crashing the whole pack.

Output is :class:`EvidencePack`, a pydantic model that
:issue:`Orchestrators-zqt` (motif labeler) and :issue:`Orchestrators-0l9`
(role-cluster labeler) will consume directly.

Token estimation defaults to ``len(text) // 4`` — a rough but stable
heuristic. Pass a custom ``estimate_tokens`` callable for a more
accurate count (e.g. ``tiktoken`` or ``anthropic.tokenizer``).
"""

from __future__ import annotations

import logging
from collections.abc import Callable, Iterable, Sequence
from pathlib import Path
from typing import Literal

import networkx as nx
from pydantic import BaseModel, Field, NonNegativeInt, PositiveInt

from ctkr.schema_l3 import LineRange

logger = logging.getLogger("ctkr.evidence")

DEFAULT_TOKEN_BUDGET = 8_000
DEFAULT_CONTEXT_LINES = 3
MAX_NEIGHBOR_SIG_CHARS = 200
MAX_SNIPPET_LINES = 80


SourceKind = Literal[
    "motif",
    "role-cluster",
    "analogy",
    "subsystem",
    "role-class",
    "operad-op",
    "interface-export",
    "data-shape",
    "nl-only",
]
NeighborDir = Literal["incoming", "outgoing"]


# ----- pydantic models -----


class NeighborEvidence(BaseModel):
    """One 1-hop neighbor of an instance symbol.

    We carry only signature-level info — full snippets would blow the
    token budget. The labeler should mention these as "this symbol calls
    X / is called by Y" rather than as additional code blocks.
    """

    direction: NeighborDir
    edge_kind: str
    symbol_id: str
    qualified_name: str
    repo: str
    signature: str | None = None


class InstanceEvidence(BaseModel):
    """Evidence for one concrete instance of a pattern."""

    symbol_id: str
    repo: str
    file: str  # repo-relative
    qualified_name: str
    kind: str  # 'class' | 'method' | 'function' | ...
    line_range: LineRange
    snippet: str
    docstring: str | None = None
    neighbors: list[NeighborEvidence] = Field(default_factory=list)


class EvidencePack(BaseModel):
    """Complete evidence assembled for one labeler invocation."""

    source_kind: SourceKind
    source_ref: str
    instances: list[InstanceEvidence] = Field(default_factory=list)
    estimated_tokens: NonNegativeInt
    token_budget: PositiveInt
    truncated: bool = Field(
        default=False,
        description=(
            "True if more candidate instances were available than fit in the budget."
        ),
    )
    repos_covered: list[str] = Field(default_factory=list)
    notes: list[str] = Field(
        default_factory=list,
        description="Diagnostic strings (missing files, oversized snippets, etc.).",
    )


# ----- public entry point -----


def build_evidence_pack(
    g: nx.MultiDiGraph,
    symbol_ids: Sequence[str],
    *,
    source_kind: SourceKind,
    source_ref: str,
    orchestrators_root: str | Path,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    context_lines: int = DEFAULT_CONTEXT_LINES,
    max_neighbors_per_instance: int = 6,
    balance_repos: bool = True,
    estimate_tokens: Callable[[str], int] | None = None,
) -> EvidencePack:
    """Assemble an evidence pack for an L3 labeler.

    Parameters
    ----------
    g
        The NetworkX graph from :func:`ctkr.graph_loader.load_graph`.
    symbol_ids
        Candidate instance symbol IDs (e.g. anchors of a motif).
    source_kind / source_ref
        Provenance — copied through to the output so downstream code
        knows which L1 artifact this pack came from.
    orchestrators_root
        Parent directory containing each indexed repo as a
        subdirectory. Source files are read as
        ``<orchestrators_root>/<repo>/<file>``.
    token_budget
        Upper bound on total estimated tokens in the pack.
    context_lines
        Extra source lines included before/after the symbol's
        ``line``..``end_line`` range. Naturally captures docstrings and
        decorators.
    max_neighbors_per_instance
        Cap on 1-hop neighbors per instance, to bound depth.
    balance_repos
        When True, instances are scheduled round-robin by repo so each
        represented repo gets at least one instance (budget permitting).
    estimate_tokens
        Override the default token estimator.

    Returns
    -------
    EvidencePack
        Always well-formed; missing files become diagnostic notes.
    """
    est = estimate_tokens or _default_token_estimate
    root = Path(orchestrators_root).expanduser().resolve()

    notes: list[str] = []
    candidates = list(_iter_candidate_instances(g, symbol_ids, root, context_lines, notes))

    if balance_repos:
        candidates = _round_robin_by_repo(candidates)

    seen_neighbors: set[str] = set()
    instances: list[InstanceEvidence] = []
    total_tokens = 0
    truncated = False

    for inst, snippet_text in candidates:
        # Build neighbor list first (deduped against `seen_neighbors`),
        # then test the whole assembled InstanceEvidence against the
        # budget. Atomicity matters: don't half-add an instance.
        neighbors = _collect_neighbors(
            g,
            inst.symbol_id,
            seen=seen_neighbors,
            limit=max_neighbors_per_instance,
        )
        for nb in neighbors:
            seen_neighbors.add(nb.symbol_id)

        inst_with_neighbors = inst.model_copy(update={"neighbors": neighbors})
        inst_tokens = _instance_tokens(inst_with_neighbors, est)
        if total_tokens + inst_tokens > token_budget and instances:
            # Already have at least one instance; stop rather than overflow.
            truncated = True
            # Roll back the neighbor reservations for this rejected instance
            # so a smaller later instance can still claim them.
            for nb in neighbors:
                seen_neighbors.discard(nb.symbol_id)
            break

        instances.append(inst_with_neighbors)
        total_tokens += inst_tokens

    if len(instances) < len(candidates):
        truncated = True

    repos_covered = sorted({i.repo for i in instances})

    return EvidencePack(
        source_kind=source_kind,
        source_ref=source_ref,
        instances=instances,
        estimated_tokens=total_tokens,
        token_budget=token_budget,
        truncated=truncated,
        repos_covered=repos_covered,
        notes=notes,
    )


# ----- internals -----


def _iter_candidate_instances(
    g: nx.MultiDiGraph,
    symbol_ids: Iterable[str],
    orchestrators_root: Path,
    context_lines: int,
    notes: list[str],
) -> Iterable[tuple[InstanceEvidence, str]]:
    """Walk the input symbols, materialize snippets, skip missing files."""
    for sid in symbol_ids:
        if not g.has_node(sid):
            notes.append(f"symbol {sid} not in graph; skipped")
            continue
        node = g.nodes[sid]
        repo = node.get("repo")
        file = node.get("file") or node.get("file_path")
        line = node.get("line")
        end_line = node.get("end_line") or line
        if repo is None or file is None or line is None:
            notes.append(f"symbol {sid} missing repo/file/line; skipped")
            continue

        try:
            snippet, real_start, real_end = _read_snippet(
                orchestrators_root, repo, file, line, end_line, context_lines
            )
        except FileNotFoundError:
            notes.append(f"file not found: {repo}/{file} (symbol {sid})")
            continue
        except OSError as e:
            notes.append(f"read error: {repo}/{file}: {e}")
            continue

        snippet, was_truncated = _cap_snippet_lines(snippet)
        if was_truncated:
            notes.append(f"snippet truncated: {repo}/{file} (>{MAX_SNIPPET_LINES} lines)")

        docstring = _extract_docstring(snippet, node.get("language") or "")

        inst = InstanceEvidence(
            symbol_id=sid,
            repo=repo,
            file=file,
            qualified_name=node.get("qualified_name") or sid,
            kind=node.get("kind") or "",
            line_range=LineRange(start=real_start, end=real_end),
            snippet=snippet,
            docstring=docstring,
            neighbors=[],  # filled in by the caller
        )
        yield inst, snippet


def _round_robin_by_repo(
    items: Iterable[tuple[InstanceEvidence, str]],
) -> list[tuple[InstanceEvidence, str]]:
    """Reorder so each repo gets a slot before any repo gets a second."""
    items_list = list(items)
    by_repo: dict[str, list[tuple[InstanceEvidence, str]]] = {}
    for inst, snippet in items_list:
        by_repo.setdefault(inst.repo, []).append((inst, snippet))
    rotated: list[tuple[InstanceEvidence, str]] = []
    while any(by_repo.values()):
        for repo in list(by_repo.keys()):
            bucket = by_repo[repo]
            if not bucket:
                continue
            rotated.append(bucket.pop(0))
    return rotated


def _collect_neighbors(
    g: nx.MultiDiGraph,
    symbol_id: str,
    *,
    seen: set[str],
    limit: int,
) -> list[NeighborEvidence]:
    out: list[NeighborEvidence] = []
    # Outgoing first (typically calls/references) — gives the labeler
    # "this symbol uses X" context which is usually more informative.
    for _, dst, k in g.out_edges(symbol_id, keys=True):
        if dst in seen or dst == symbol_id:
            continue
        d = g.nodes[dst]
        out.append(
            NeighborEvidence(
                direction="outgoing",
                edge_kind=k,
                symbol_id=dst,
                qualified_name=d.get("qualified_name") or dst,
                repo=d.get("repo") or "",
                signature=_trim_signature(d.get("signature")),
            )
        )
        if len(out) >= limit:
            return out
    for src, _, k in g.in_edges(symbol_id, keys=True):
        if src in seen or src == symbol_id:
            continue
        d = g.nodes[src]
        out.append(
            NeighborEvidence(
                direction="incoming",
                edge_kind=k,
                symbol_id=src,
                qualified_name=d.get("qualified_name") or src,
                repo=d.get("repo") or "",
                signature=_trim_signature(d.get("signature")),
            )
        )
        if len(out) >= limit:
            return out
    return out


def _read_snippet(
    orchestrators_root: Path,
    repo: str,
    file: str,
    line: int,
    end_line: int,
    context_lines: int,
) -> tuple[str, int, int]:
    """Read inclusive lines [line-context_lines, end_line+context_lines]."""
    path = orchestrators_root / repo / file
    text = path.read_text(encoding="utf-8", errors="replace")
    lines = text.splitlines()
    start = max(1, line - context_lines)
    end = min(len(lines), end_line + context_lines)
    # `lines` is 0-indexed; conventional source numbering is 1-indexed.
    sliced = lines[start - 1 : end]
    return ("\n".join(sliced), start, end)


def _cap_snippet_lines(snippet: str) -> tuple[str, bool]:
    """Truncate snippets that are longer than MAX_SNIPPET_LINES."""
    lines = snippet.splitlines()
    if len(lines) <= MAX_SNIPPET_LINES:
        return snippet, False
    head = lines[: MAX_SNIPPET_LINES - 2]
    return ("\n".join(head) + "\n  …  (truncated)\n"), True


def _trim_signature(sig: str | None) -> str | None:
    if not sig:
        return None
    if len(sig) <= MAX_NEIGHBOR_SIG_CHARS:
        return sig
    return sig[: MAX_NEIGHBOR_SIG_CHARS - 3] + "..."


def _extract_docstring(snippet: str, language: str) -> str | None:
    """Best-effort: find a docstring-ish block in the first few lines.

    Conservative — no AST parsing, just pattern recognition. Returns
    ``None`` when no obvious docstring/comment is present, so labelers
    can decide whether to mention it.

    Per-language extractors are tried first; if they don't match, we
    fall through to a generic ``#`` / ``//`` comment-run detector so
    files with line comments (rather than triple-quoted Python or JSDoc)
    still surface their leading prose.
    """
    lines = snippet.splitlines()
    if not lines:
        return None

    # Python — first """...""" block.
    if language == "py":
        py = _extract_py_docstring(lines)
        if py is not None:
            return py
        # fall through

    # TS / JS — first JSDoc-style /** ... */ block.
    if language in {"ts", "tsx", "js"}:
        js = _extract_jsdoc(lines)
        if js is not None:
            return js
        # fall through

    # Generic fallback — first non-trivial run of `#` or `//` comments,
    # skipping past filler comments and the symbol's own header line
    # (which may itself be `class ...` / `def ...` etc.).
    return _extract_line_comments(lines)


def _extract_py_docstring(lines: list[str]) -> str | None:
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not (stripped.startswith('"""') or stripped.startswith("'''")):
            continue
        quote = stripped[:3]
        rest = stripped[3:]
        # Same-line one-liner: `"""foo"""`
        if rest.endswith(quote) and len(rest) >= 3:
            return rest[: -len(quote)].strip() or None
        collected: list[str] = [rest]
        for j in range(i + 1, len(lines)):
            if quote in lines[j]:
                collected.append(lines[j].split(quote, 1)[0])
                joined = "\n".join(s for s in collected if s).strip()
                return joined or None
            collected.append(lines[j])
        return None
    return None


def _extract_jsdoc(lines: list[str]) -> str | None:
    for i, line in enumerate(lines):
        stripped = line.strip()
        if not stripped.startswith("/**"):
            continue
        # Single-line `/** ... */`
        rest = stripped[3:]
        if "*/" in rest:
            return rest.split("*/", 1)[0].strip() or None
        collected: list[str] = []
        for j in range(i + 1, len(lines)):
            raw = lines[j].strip()
            if "*/" in raw:
                before = raw.split("*/", 1)[0].lstrip("*").strip()
                if before:
                    collected.append(before)
                joined = "\n".join(s for s in collected if s).strip()
                return joined or None
            collected.append(raw.lstrip("*").strip())
        return None
    return None


def _extract_line_comments(lines: list[str]) -> str | None:
    """Find the longest contiguous comment-run; ignore short repeated
    filler lines so we don't surface "leading filler" as a docstring.
    """
    best: list[str] | None = None
    cur: list[str] = []
    for line in lines:
        stripped = line.strip()
        if stripped.startswith("#") or stripped.startswith("//"):
            content = stripped.lstrip("/#").strip()
            cur.append(content)
            continue
        if cur:
            if best is None or len(cur) > len(best) or _is_more_informative(cur, best):
                best = cur
            cur = []
    if cur and (best is None or len(cur) > len(best)):
        best = cur
    if best is None:
        return None
    # Drop runs that look like filler — repeated identical lines.
    if len(set(best)) == 1 and len(best[0]) < 40:
        return None
    return "\n".join(best).strip() or None


def _is_more_informative(a: list[str], b: list[str]) -> bool:
    """Prefer a run with more unique content."""
    return len(set(a)) > len(set(b))


def _instance_tokens(inst: InstanceEvidence, est: Callable[[str], int]) -> int:
    total = est(inst.snippet)
    total += est(inst.qualified_name)
    if inst.docstring:
        total += est(inst.docstring)
    for nb in inst.neighbors:
        total += est(nb.qualified_name)
        if nb.signature:
            total += est(nb.signature)
    return total


def _default_token_estimate(s: str) -> int:
    return max(1, len(s) // 4)


__all__ = [
    "DEFAULT_TOKEN_BUDGET",
    "DEFAULT_CONTEXT_LINES",
    "EvidencePack",
    "InstanceEvidence",
    "NeighborEvidence",
    "build_evidence_pack",
]
