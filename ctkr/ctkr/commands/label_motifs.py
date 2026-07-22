"""``ctkr label-motifs`` — L3 motif labeler CLI (Orchestrators-zqt).

Reads ``motifs.parquet`` + ``motif_instances.parquet`` from the data
dir, walks each motif through the LLM labeler, and writes
``patterns.jsonl`` + ``evidence.jsonl`` alongside the L1 artifacts.

Idempotent across re-runs with the same prompt + model — already-labeled
motifs are skipped unless ``--force`` is passed.
"""

from __future__ import annotations

import argparse
import logging
import sys
from pathlib import Path

import polars as pl

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph
from ctkr.label_motifs import (
    DEFAULT_MAX_INSTANCES,
    DEFAULT_MODEL,
    DEFAULT_PROMPT_VERSION,
    DEFAULT_TEMPERATURE,
    DEFAULT_TOKEN_BUDGET,
    label_motifs,
    pattern_id_for_motif,
    render_prompt,
)
from ctkr.llm import LLMClient, sandbox_write_guard, scratch_dir


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "label-motifs",
        help="L3: label each motif with a name + description via an LLM.",
        description=(
            "Read motifs.parquet + motif_instances.parquet, assemble an "
            "EvidencePack per motif, send to the LLM with structured output, "
            "and stream PatternRow / EvidenceRow into patterns.jsonl + "
            "evidence.jsonl. Idempotent under the same prompt-version + "
            "model — re-runs skip already-labeled motifs."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--orchestrators-root",
        type=str,
        default=None,
        help=(
            "Parent dir containing each indexed repo as a subdirectory. "
            "Defaults to the parent of --data-dir (i.e. the project root "
            "where .metacoding/ lives)."
        ),
    )
    p.add_argument("--provider", choices=("anthropic", "openai"), default="anthropic")
    p.add_argument("--model", default=DEFAULT_MODEL)
    p.add_argument("--temperature", type=float, default=DEFAULT_TEMPERATURE)
    p.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    p.add_argument("--max-tokens", type=int, default=1024)
    p.add_argument(
        "--max-instances-per-motif", type=int, default=DEFAULT_MAX_INSTANCES
    )
    p.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    p.add_argument(
        "--max-motifs",
        type=int,
        default=None,
        help="Cap the number of motifs labeled (sorted by support desc).",
    )
    p.add_argument(
        "--force",
        action="store_true",
        help="Re-label motifs whose pattern_id already exists in patterns.jsonl.",
    )
    p.add_argument(
        "--dry-run",
        action="store_true",
        help=(
            "Don't call the LLM. Render the prompt for the first motif "
            "and print it, then exit. Useful for sanity-checking before "
            "spending money."
        ),
    )
    p.add_argument(
        "--cache-dir",
        default=None,
        help=(
            "LLM cache directory; defaults to ~/.cache/ctkr/label-motifs/llm_cache/ (scratch, never a sandbox). "
            "Caching makes re-runs free."
        ),
    )
    p.add_argument(
        "--cost-log",
        default=None,
        help=(
            "LLM cost log JSONL; defaults to ~/.cache/ctkr/label-motifs/llm_cost.jsonl (scratch, never a sandbox). "
            "Append-only."
        ),
    )
    p.add_argument(
        "--verbose", "-v", action="store_true", help="Log one line per motif."
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(name)s %(levelname)s %(message)s",
    )

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = data_dir / "ctkr"
    motifs_path = ctkr_dir / "motifs.parquet"
    instances_path = ctkr_dir / "motif_instances.parquet"
    for required in (motifs_path, instances_path):
        if not required.exists():
            sys.stderr.write(
                f"{required} not found. Run `ctkr mine-motifs` first.\n"
            )
            return 2

    orchestrators_root = (
        Path(args.orchestrators_root).expanduser().resolve()
        if args.orchestrators_root
        else data_dir.parent
    )
    if not orchestrators_root.exists():
        sys.stderr.write(
            f"--orchestrators-root {orchestrators_root} does not exist\n"
        )
        return 2

    sys.stderr.write(f"loading graph from {data_dir}...\n")
    graph = load_graph(data_dir)
    sys.stderr.write(
        f"  {graph.number_of_nodes()} nodes, {graph.number_of_edges()} edges\n"
    )
    motifs_df = pl.read_parquet(motifs_path)
    instances_df = pl.read_parquet(instances_path)
    sys.stderr.write(
        f"  {motifs_df.height} motifs, {instances_df.height} instances\n"
    )

    if args.dry_run:
        return _dry_run(
            motifs_df=motifs_df,
            instances_df=instances_df,
            graph=graph,
            orchestrators_root=orchestrators_root,
            max_instances_per_motif=args.max_instances_per_motif,
            token_budget=args.token_budget,
        )

    cache_dir = (
        Path(args.cache_dir).expanduser().resolve()
        if args.cache_dir
        else scratch_dir("label-motifs") / "llm_cache"
    )
    cost_log = (
        Path(args.cost_log).expanduser().resolve()
        if args.cost_log
        else scratch_dir("label-motifs") / "llm_cost.jsonl"
    )
    sandbox_write_guard(data_dir, cache_dir, cost_log)
    client = LLMClient(
        cache_dir=cache_dir,
        cost_log=cost_log,
        default_provider=args.provider,
        default_model=args.model,
        default_temperature=args.temperature,
        default_max_tokens=args.max_tokens,
    )

    out_patterns = ctkr_dir / "patterns.jsonl"
    out_evidence = ctkr_dir / "evidence.jsonl"
    sys.stderr.write(
        f"labeling — writing to {out_patterns} and {out_evidence}\n"
    )

    stats = label_motifs(
        motifs_df=motifs_df,
        instances_df=instances_df,
        graph=graph,
        orchestrators_root=orchestrators_root,
        client=client,
        out_patterns=out_patterns,
        out_evidence=out_evidence,
        model=args.model,
        temperature=args.temperature,
        prompt_version=args.prompt_version,
        max_instances_per_motif=args.max_instances_per_motif,
        token_budget=args.token_budget,
        force=args.force,
        max_motifs=args.max_motifs,
        progress=[""] if args.verbose else None,
    )

    sys.stderr.write(
        f"\ndone — labeled={stats.n_labeled} skipped={stats.n_skipped} "
        f"failed={stats.n_failed} (of {stats.n_total}) "
        f"cost=${stats.total_cost_usd:.4f} cache_hits={stats.cache_hits}\n"
    )
    return 0 if stats.n_failed == 0 else 1


def _dry_run(
    *,
    motifs_df: pl.DataFrame,
    instances_df: pl.DataFrame,
    graph,
    orchestrators_root: Path,
    max_instances_per_motif: int,
    token_budget: int,
) -> int:
    """Render the prompt for the highest-support motif and print it."""
    from ctkr.evidence import build_evidence_pack
    from ctkr.label_motifs import _iter_motifs  # type: ignore[attr-defined]

    for motif_dict in _iter_motifs(motifs_df, max_motifs=1):
        motif_id = str(motif_dict["motif_id"])
        sub = instances_df.filter(pl.col("motif_id") == motif_id)
        anchors = sub.get_column("symbol_id").to_list()[:max_instances_per_motif]
        if not anchors:
            sys.stderr.write(f"motif {motif_id} has no instances\n")
            return 2
        pack = build_evidence_pack(
            graph,
            anchors,
            source_kind="motif",
            source_ref=motif_id,
            orchestrators_root=orchestrators_root,
            token_budget=token_budget,
        )
        prompt = render_prompt(motif_dict, pack)
        sys.stdout.write(prompt + "\n")
        sys.stderr.write(
            f"\n(dry run) motif {motif_id}: pattern_id would be "
            f"{pattern_id_for_motif(motif_id, prompt_version='motif-labeler:v1', llm_model='claude-haiku-4-5-20251001')}\n"
        )
        return 0
    sys.stderr.write("no motifs to dry-run\n")
    return 2
