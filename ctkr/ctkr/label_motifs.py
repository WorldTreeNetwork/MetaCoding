"""L3 motif labeler — turn L1 motifs into labeled patterns.

Pipeline
--------

For each row of ``motifs.parquet``:

1. Look up its anchor symbol_ids from ``motif_instances.parquet``.
2. Assemble an :class:`EvidencePack` (snippets + 1-hop neighbors) via
   :func:`ctkr.evidence.build_evidence_pack`.
3. Render a prompt from the motif metadata + evidence pack.
4. Send the prompt to the LLM with a structured-output schema
   (:class:`MotifLabelOutput`).
5. Emit one :class:`PatternRow` (→ ``patterns.jsonl``) and one
   :class:`EvidenceRow` per instance (→ ``evidence.jsonl``), tagged with
   mandatory provenance (``llm_model``, ``llm_temperature``,
   ``prompt_version``, ``schema_version``).

Idempotency
-----------

``pattern_id`` is deterministic given
``(source_kind, source_ref, prompt_version, llm_model)``. Re-runs with
the same provenance produce the same ID — the same prompt and model on
the same motif map to the same row.

By default the loop **skips** motifs whose ``pattern_id`` is already
present in ``patterns.jsonl``; ``force=True`` re-labels and the caller is
responsible for rewriting the JSONL to dedupe (use a separate prune pass).

Owning bd issue: ``Orchestrators-zqt``.
"""

from __future__ import annotations

import hashlib
import json
import logging
from collections.abc import Iterable, Iterator
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import networkx as nx
import polars as pl
from pydantic import BaseModel, Field

from ctkr.evidence import EvidencePack, build_evidence_pack
from ctkr.llm import LLMClient
from ctkr.schema_l3 import EvidenceRow, LineRange, PatternRow

logger = logging.getLogger("ctkr.label_motifs")

DEFAULT_PROMPT_VERSION = "motif-labeler:v1"
DEFAULT_MODEL = "claude-haiku-4-5-20251001"
DEFAULT_TEMPERATURE = 0.0
DEFAULT_TOKEN_BUDGET = 8_000
DEFAULT_MAX_INSTANCES = 8

PATTERN_ID_PREFIX = "motif"


# ----- LLM response schema -----


class MotifLabelOutput(BaseModel):
    """What the LLM emits for one motif.

    Kept minimal — provenance fields (``llm_model``, ``prompt_version``,
    etc.) are filled in by the caller, not the LLM. The LLM only owns
    the natural-language judgement: a short name, a paragraph
    description, and a confidence score.
    """

    label: str = Field(
        description=(
            "Short canonical name for this pattern — 2-4 words. "
            "Reusable as a key in cross-instance synthesis."
        ),
    )
    description: str = Field(
        description=(
            "One paragraph (2-4 sentences) explaining what the pattern "
            "does and why it recurs in this corpus."
        ),
    )
    confidence: float = Field(
        ge=0.0,
        le=1.0,
        description=(
            "Self-reported confidence in [0, 1] that this label and "
            "description accurately characterize the structural pattern."
        ),
    )


# ----- pattern_id -----


def pattern_id_for_motif(
    motif_id: str,
    *,
    prompt_version: str,
    llm_model: str,
) -> str:
    """Deterministic ID for a labeled motif.

    Bumping ``prompt_version`` or ``llm_model`` yields a different ID
    — old and new labels coexist in ``patterns.jsonl`` until a prune
    pass garbage-collects.
    """
    canon = json.dumps(
        ["motif", motif_id, prompt_version, llm_model], sort_keys=True
    ).encode("utf-8")
    h = hashlib.blake2b(canon, digest_size=8).hexdigest()
    return f"{PATTERN_ID_PREFIX}:{motif_id}@{h}"


# ----- prompt -----


_SYSTEM = (
    "You are a software-architecture labeler. You see a recurring structural "
    "motif from a corpus of agent-orchestrator codebases and a handful of "
    "concrete instances. Your job is to give the motif a short canonical "
    "name and a one-paragraph description of what role this pattern plays "
    "and why it recurs. Stay grounded in the code shown — do not invent "
    "details that aren't visible in the evidence."
)


def render_prompt(motif: dict[str, Any], pack: EvidencePack) -> str:
    """Compose the user-side prompt from a motif row + its EvidencePack.

    Kept as plain Markdown rather than a chat-message list so it caches
    consistently and survives provider switches.
    """
    parts: list[str] = []
    parts.append(f"# Motif `{motif['motif_id']}`")
    parts.append("")
    parts.append("## Structural signature")
    parts.append(f"- signature: `{motif.get('signature', '?')}`")
    parts.append(f"- nodes: {motif.get('size_nodes', '?')}, edges: {motif.get('size_edges', '?')}")
    parts.append(f"- support (total occurrences): {motif.get('support', '?')}")
    coverage = motif.get("repo_coverage") or []
    parts.append(f"- repo_coverage ({len(coverage)} repos): {', '.join(coverage[:20])}")
    edge_kinds = motif.get("edge_kinds") or []
    parts.append(f"- edge_kinds: {', '.join(edge_kinds)}")
    parts.append("")
    parts.append(
        f"## Evidence ({len(pack.instances)} instances across {len(pack.repos_covered)} repos)"
    )
    if pack.truncated:
        parts.append(
            f"_Note: truncated to fit a {pack.token_budget}-token budget; more instances exist._"
        )
    parts.append("")

    for i, inst in enumerate(pack.instances, 1):
        parts.append(f"### Instance {i}: `{inst.qualified_name}` ({inst.repo})")
        parts.append(
            f"- file: `{inst.file}` lines {inst.line_range.start}-{inst.line_range.end}"
        )
        if inst.docstring:
            parts.append(f"- docstring: {inst.docstring}")
        parts.append("")
        parts.append("```")
        parts.append(inst.snippet)
        parts.append("```")
        if inst.neighbors:
            parts.append("")
            parts.append("**1-hop neighbors:**")
            for nb in inst.neighbors:
                arrow = "→" if nb.direction == "outgoing" else "←"
                sig = f" `{nb.signature}`" if nb.signature else ""
                parts.append(f"- {arrow} [{nb.edge_kind}] `{nb.qualified_name}` ({nb.repo}){sig}")
        parts.append("")

    parts.append("---")
    parts.append("")
    parts.append(
        "Emit a `MotifLabelOutput` describing the pattern. Be concrete — "
        "say what role the anchor symbol plays and how it composes with "
        "the neighbors shown. Avoid generic words like 'class' or 'helper'."
    )
    return "\n".join(parts)


# ----- one motif -----


@dataclass(slots=True)
class LabeledMotif:
    """One motif's full labeled output — pattern row + per-instance evidence."""

    pattern: PatternRow
    evidence: list[EvidenceRow]
    cost_usd: float
    cache_hit: bool


def label_motif(
    *,
    motif: dict[str, Any],
    pack: EvidencePack,
    client: LLMClient,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    max_tokens: int = 1024,
) -> LabeledMotif:
    """Label one motif. Caller drives the EvidencePack assembly."""
    prompt = render_prompt(motif, pack)
    result = client.complete_structured(
        prompt,
        schema=MotifLabelOutput,
        model=model,
        temperature=temperature,
        max_tokens=max_tokens,
        system=_SYSTEM,
    )
    parsed = result.parsed
    motif_id = str(motif["motif_id"])
    pid = pattern_id_for_motif(
        motif_id, prompt_version=prompt_version, llm_model=model
    )
    now = datetime.now(tz=timezone.utc)

    pattern = PatternRow(
        pattern_id=pid,
        source_kind="motif",
        source_ref=motif_id,
        label=parsed.label,
        description=parsed.description,
        instances=[i.symbol_id for i in pack.instances],
        confidence=parsed.confidence,
        llm_model=model,
        llm_temperature=temperature,
        prompt_version=prompt_version,
        generated_at=now,
    )
    evidence_rows = [
        EvidenceRow(
            pattern_id=pid,
            repo=inst.repo,
            file=inst.file,
            line_range=LineRange(start=inst.line_range.start, end=inst.line_range.end),
            snippet=inst.snippet,
            context=inst.qualified_name,
        )
        for inst in pack.instances
    ]
    return LabeledMotif(
        pattern=pattern,
        evidence=evidence_rows,
        cost_usd=result.cost_estimate_usd,
        cache_hit=result.cache_hit,
    )


# ----- driver -----


@dataclass(slots=True)
class LabelRunStats:
    n_total: int
    n_labeled: int
    n_skipped: int
    n_failed: int
    total_cost_usd: float
    cache_hits: int


def _load_existing_pattern_ids(path: Path) -> set[str]:
    """Return the set of ``pattern_id``s already on disk; empty if absent."""
    if not path.exists():
        return set()
    out: set[str] = set()
    with path.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                d = json.loads(line)
            except json.JSONDecodeError:
                logger.warning("skipping malformed line in %s", path)
                continue
            pid = d.get("pattern_id")
            if pid is not None:
                out.add(pid)
    return out


def _iter_motif_instance_anchors(
    instances_df: pl.DataFrame,
    motif_id: str,
    *,
    max_instances: int,
) -> list[str]:
    """Pull up to ``max_instances`` anchor symbol_ids for one motif.

    Round-robin by repo: take one anchor from each represented repo,
    then a second from each, until we hit ``max_instances`` or run out.
    Otherwise a motif with 38-repo coverage but a long instances table
    dominated by one repo would feed only that repo's snippets to the
    labeler — defeating the cross-repo signal the labeler is supposed to
    pick up on.
    """
    sub = instances_df.filter(pl.col("motif_id") == motif_id)
    if sub.height == 0:
        return []
    by_repo: dict[str, list[str]] = {}
    for row in sub.iter_rows(named=True):
        by_repo.setdefault(str(row["repo"]), []).append(str(row["symbol_id"]))
    # Deterministic order: repos sorted alphabetically.
    repo_iters = [iter(by_repo[r]) for r in sorted(by_repo)]
    out: list[str] = []
    while repo_iters and len(out) < max_instances:
        next_round: list[Any] = []
        for it in repo_iters:
            sym = next(it, None)
            if sym is None:
                continue
            out.append(sym)
            if len(out) >= max_instances:
                return out
            next_round.append(it)
        repo_iters = next_round
    return out


def label_motifs(
    *,
    motifs_df: pl.DataFrame,
    instances_df: pl.DataFrame,
    graph: nx.MultiDiGraph,
    orchestrators_root: str | Path,
    client: LLMClient,
    out_patterns: Path,
    out_evidence: Path,
    model: str = DEFAULT_MODEL,
    temperature: float = DEFAULT_TEMPERATURE,
    prompt_version: str = DEFAULT_PROMPT_VERSION,
    max_instances_per_motif: int = DEFAULT_MAX_INSTANCES,
    token_budget: int = DEFAULT_TOKEN_BUDGET,
    force: bool = False,
    max_motifs: int | None = None,
    progress: Iterable[str] | None = None,
) -> LabelRunStats:
    """Label every motif in ``motifs_df``; stream rows to JSONL.

    Parameters
    ----------
    motifs_df / instances_df
        Loaded ``motifs.parquet`` and ``motif_instances.parquet``.
    graph
        Loaded NetworkX graph (from :func:`ctkr.graph_loader.load_graph`).
        Carries node attributes the evidence builder needs.
    orchestrators_root
        Parent directory containing each indexed repo as a subdirectory.
        Snippet text is read from ``<root>/<repo>/<file>``.
    client
        Pre-configured :class:`ctkr.llm.LLMClient` (caching, cost log,
        retry are owned by it).
    out_patterns / out_evidence
        Destination JSONL files. Created if missing; appended to
        otherwise.
    force
        If ``False`` (default), motifs whose ``pattern_id`` already
        appears in ``out_patterns`` are skipped — the run is resumable.
        If ``True``, re-label them anyway (the caller can later run a
        prune pass to dedupe by ``pattern_id``).
    max_motifs
        Optional cap, useful for smoke tests.
    progress
        If provided, log a line per motif using ``logger.info``;
        otherwise stay quiet. Callers wire this through tqdm if they
        want live feedback.
    """
    out_patterns.parent.mkdir(parents=True, exist_ok=True)
    out_evidence.parent.mkdir(parents=True, exist_ok=True)

    existing = _load_existing_pattern_ids(out_patterns) if not force else set()

    n_total = motifs_df.height if max_motifs is None else min(motifs_df.height, max_motifs)
    n_labeled = 0
    n_skipped = 0
    n_failed = 0
    total_cost = 0.0
    cache_hits = 0

    # Open both files in append mode so partial runs are durable.
    with out_patterns.open("a", encoding="utf-8") as pf, out_evidence.open(
        "a", encoding="utf-8"
    ) as ef:
        for i, motif_dict in enumerate(_iter_motifs(motifs_df, max_motifs)):
            motif_id = str(motif_dict["motif_id"])
            pid = pattern_id_for_motif(
                motif_id, prompt_version=prompt_version, llm_model=model
            )
            if pid in existing:
                n_skipped += 1
                logger.debug("skipping %s (already labeled)", motif_id)
                continue

            anchors = _iter_motif_instance_anchors(
                instances_df, motif_id, max_instances=max_instances_per_motif
            )
            if not anchors:
                n_skipped += 1
                logger.warning("motif %s has no instances; skipped", motif_id)
                continue

            pack = build_evidence_pack(
                graph,
                anchors,
                source_kind="motif",
                source_ref=motif_id,
                orchestrators_root=orchestrators_root,
                token_budget=token_budget,
            )
            if not pack.instances:
                n_skipped += 1
                logger.warning(
                    "motif %s — no instances had readable evidence; skipped", motif_id
                )
                continue

            # Cross-repo signal check. motif_instances.parquet is capped
            # by `ctkr mine-motifs --max-instances-per-motif` and the
            # current miner doesn't balance that sample across the
            # motif's full repo coverage (Orchestrators-k97 follow-up).
            # Surface the gap so callers know when a "38-repo motif"
            # actually feeds the labeler one repo's worth of evidence.
            declared_coverage = motif_dict.get("repo_coverage") or []
            if len(declared_coverage) > 1 and len(pack.repos_covered) == 1:
                logger.warning(
                    "motif %s — instances cover %d of %d declared repos "
                    "(miner sampling bug; Orchestrators-k97). Labeler will "
                    "still proceed but the label will reflect one repo.",
                    motif_id,
                    len(pack.repos_covered),
                    len(declared_coverage),
                )

            try:
                out = label_motif(
                    motif=motif_dict,
                    pack=pack,
                    client=client,
                    model=model,
                    temperature=temperature,
                    prompt_version=prompt_version,
                )
            except Exception as e:  # noqa: BLE001
                n_failed += 1
                logger.exception("motif %s failed: %s", motif_id, e)
                continue

            pf.write(out.pattern.model_dump_json() + "\n")
            pf.flush()
            for ev in out.evidence:
                ef.write(ev.model_dump_json() + "\n")
            ef.flush()
            n_labeled += 1
            total_cost += out.cost_usd
            cache_hits += 1 if out.cache_hit else 0
            existing.add(pid)
            logger.info(
                "labeled %s as %r (cost=$%.6f cache=%s)",
                motif_id,
                out.pattern.label,
                out.cost_usd,
                out.cache_hit,
            )
            if progress is not None:
                logger.info("progress: %d/%d", i + 1, n_total)

    return LabelRunStats(
        n_total=n_total,
        n_labeled=n_labeled,
        n_skipped=n_skipped,
        n_failed=n_failed,
        total_cost_usd=round(total_cost, 6),
        cache_hits=cache_hits,
    )


def _iter_motifs(df: pl.DataFrame, max_motifs: int | None) -> Iterator[dict[str, Any]]:
    """Iterate motifs as dicts, with an optional cap. Sorted by support desc
    so cheap smoke runs hit the highest-value motifs first."""
    ordered = df.sort("support", descending=True)
    if max_motifs is not None:
        ordered = ordered.head(max_motifs)
    for row in ordered.iter_rows(named=True):
        yield row


__all__ = [
    "DEFAULT_MAX_INSTANCES",
    "DEFAULT_MODEL",
    "DEFAULT_PROMPT_VERSION",
    "DEFAULT_TEMPERATURE",
    "DEFAULT_TOKEN_BUDGET",
    "LabelRunStats",
    "LabeledMotif",
    "MotifLabelOutput",
    "label_motif",
    "label_motifs",
    "pattern_id_for_motif",
    "render_prompt",
]
