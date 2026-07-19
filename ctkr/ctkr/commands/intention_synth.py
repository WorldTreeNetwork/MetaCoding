"""``ctkr intention-synthesis`` — LM intention synthesis (Stage T5b / §9.2).

The LM layer of the intention channel, downstream of the T5a mechanical harvest
(``ctkr intention``). Reads ``intention_signals.parquet`` /
``intention_load.parquet`` / ``intention_conflicts.parquet`` under
``<data_dir>/ctkr/`` and, per element:

* synthesizes cited INTENT statements + a domain glossary (cheap model),
* distills S1 tests into given/when/then behavioral scenarios (cheap model),
* adjudicates structure↔intention agreement on a flagged subset (strong model).

Writes ``intention.jsonl`` (§9.1) and merges an ``intention_load_summary`` +
presence flags into ``manifest.json``. Rides the shared :class:`LLMClient` cache +
cost log (``<data_dir>/ctkr/llm_cache/`` + ``llm_cost.jsonl``) — temperature 0,
blake3 prompt-hash cache, so an unchanged harvest re-runs free and byte-identical
(§8). Requires ``ctkr intention`` (T5a) to have run.

See :mod:`ctkr.intention_synth` for the algorithm and
``docs/design/ct-intention-extraction.md`` §8 for models/caching/determinism.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

from ctkr.commands._common import add_common_flags, resolve_data_dir


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "intention-synthesis",
        help="LM intention synthesis (Stage T5b) — intent + scenarios + adjudication.",
        description=(
            "Fuse the T5a mechanical harvest into synthesized intention "
            "(ct-intention-extraction.md §8): per-element cited intent statements + "
            "glossary (cheap model), S1→given/when/then behavioral scenarios (cheap "
            "model), and structure-vs-intention adjudication on a flagged subset "
            "(strong model). Writes intention.jsonl. Deterministic given the same "
            "harvest + prompt-version + model (structured-evidence digest + LLM "
            "cache). Requires `ctkr intention` (T5a)."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--provider",
        default=None,
        help="LLM provider for every call: 'anthropic' (default) or 'openai' "
        "(GPT-5.x tiers — pass the tier via --model/--adjudication-model).",
    )
    p.add_argument(
        "--model",
        default=None,
        help="Cheap model for per-element intent + scenarios (default: haiku-class).",
    )
    p.add_argument(
        "--adjudication-model",
        default=None,
        help="Strong model for structure-vs-intention adjudication on the flagged "
        "subset (default: a sonnet-class model). Pass the same value as --model to "
        "force a single model / stay on the offline path.",
    )
    p.add_argument("--prompt-version", default=None, help="Override prompt_version.")
    p.add_argument(
        "--low-confidence",
        type=float,
        default=None,
        help="Cheap-labeler confidence below which an element is routed to strong "
        "adjudication (default 0.5).",
    )
    p.add_argument(
        "--max-elements",
        type=int,
        default=None,
        help="Cap the number of elements synthesized (stable order; for smoke runs).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.intention_synth import (
        DEFAULT_MODEL,
        DEFAULT_PROMPT_VERSION,
        intention_load_summary,
        synthesize_intention,
        write_intention_jsonl,
    )
    from ctkr.llm import LLMClient

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    signals_path = ctkr_dir / "intention_signals.parquet"
    load_path = ctkr_dir / "intention_load.parquet"
    conflicts_path = ctkr_dir / "intention_conflicts.parquet"
    if not signals_path.exists() or not load_path.exists():
        sys.stderr.write(
            f"ERROR: {signals_path.name} / {load_path.name} not found under "
            f"{ctkr_dir} — run `ctkr intention` (T5a) first.\n"
        )
        return 2

    signals_df = pl.read_parquet(signals_path)
    load_df = pl.read_parquet(load_path)
    conflicts_df = (
        pl.read_parquet(conflicts_path)
        if conflicts_path.exists()
        else pl.DataFrame(schema={"element_id": pl.Utf8})
    )
    members_path = ctkr_dir / "subsystem_members.parquet"
    members_df = pl.read_parquet(members_path) if members_path.exists() else None

    client = LLMClient(
        cache_dir=ctkr_dir / "llm_cache",
        cost_log=ctkr_dir / "llm_cost.jsonl",
        default_provider=args.provider or "anthropic",
    )

    kwargs: dict = {
        "signals_df": signals_df,
        "load_df": load_df,
        "conflicts_df": conflicts_df,
        "members_df": members_df,
        "client": client,
        "max_elements": args.max_elements,
    }
    if args.model:
        kwargs["model"] = args.model
    if args.adjudication_model:
        kwargs["adjudication_model"] = args.adjudication_model
    if args.prompt_version:
        kwargs["prompt_version"] = args.prompt_version
    if args.low_confidence is not None:
        kwargs["low_confidence"] = args.low_confidence

    sys.stderr.write(
        f"synthesizing intention over {load_df.height} load rows / {signals_df.height} signals …\n"
    )
    rows, stats = synthesize_intention(**kwargs)

    out_path = ctkr_dir / "intention.jsonl"
    write_intention_jsonl(rows, out_path)
    summary = intention_load_summary(load_df)
    manifest_path = _merge_manifest(data_dir, n_intention=len(rows), summary=summary)

    model = args.model or DEFAULT_MODEL
    pv = args.prompt_version or DEFAULT_PROMPT_VERSION
    sys.stderr.write(
        "\n"
        f"  elements synthesized: {stats.n_elements} (by kind {stats.by_element_kind})\n"
        f"  intent statements   : {stats.n_intent_statements} "
        f"(glossary terms {stats.n_glossary_terms})\n"
        f"  behavioral scenarios: {stats.n_scenarios} "
        f"(from {stats.n_scenario_calls} S1-linked elements)\n"
        f"  citations           : {stats.n_citations_resolved} resolved, "
        f"{stats.n_citations_dropped} dropped (out-of-range tags)\n"
        f"  adjudications        : {stats.n_adjudications} on {stats.n_flagged} flagged "
        f"(verdicts {stats.agreement_counts}, "
        f"confirmed contradictions {stats.n_confirmed_contradictions})\n"
        f"  load summary        : {summary}\n"
        f"  LLM calls           : intent {stats.n_intent_calls} + scenario "
        f"{stats.n_scenario_calls} + adjudication {stats.n_adjudications} "
        f"(cache hits {stats.cache_hits}, failed/degraded {stats.n_failed_calls})\n"
        f"  empty-intent fallbacks: {stats.n_intent_fallbacks} (refilled by strong model)\n"
        f"  cost                : ${stats.total_cost_usd:.4f}\n"
        f"  model / prompt      : {model} / {pv}\n"
        f"  intention.jsonl     : {out_path}\n"
        f"  manifest            : {manifest_path}\n"
        f"  elapsed             : {stats.total_seconds}s\n"
    )

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "n_elements": stats.n_elements,
                    "n_intent_statements": stats.n_intent_statements,
                    "n_glossary_terms": stats.n_glossary_terms,
                    "n_scenarios": stats.n_scenarios,
                    "n_intent_calls": stats.n_intent_calls,
                    "n_scenario_calls": stats.n_scenario_calls,
                    "n_adjudications": stats.n_adjudications,
                    "n_flagged": stats.n_flagged,
                    "agreement_counts": stats.agreement_counts,
                    "n_confirmed_contradictions": stats.n_confirmed_contradictions,
                    "n_citations_resolved": stats.n_citations_resolved,
                    "n_citations_dropped": stats.n_citations_dropped,
                    "n_failed_calls": stats.n_failed_calls,
                    "n_intent_fallbacks": stats.n_intent_fallbacks,
                    "intention_load_summary": summary,
                    "total_cost_usd": stats.total_cost_usd,
                    "cache_hits": stats.cache_hits,
                    "by_element_kind": stats.by_element_kind,
                    "model": model,
                    "prompt_version": pv,
                    "elapsed_seconds": stats.total_seconds,
                },
                indent=2,
            )
            + "\n"
        )
    return 0


def _merge_manifest(data_dir: str | Path, *, n_intention: int, summary: dict) -> Path:
    from datetime import UTC, datetime

    base = Path(data_dir).expanduser().resolve()
    manifest_path = base / "ctkr" / "manifest.json"
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    existing: dict = {}
    if manifest_path.exists():
        try:
            existing = json.loads(manifest_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing = {}
    merged = {
        **existing,
        "intention_synthesis": True,
        "n_intention_rows": int(n_intention),
        "intention_load_summary": summary,
        "intention_synthesis_generated_at": datetime.now(tz=UTC).isoformat(),
    }
    manifest_path.write_text(json.dumps(merged, indent=2), encoding="utf-8")
    return manifest_path
