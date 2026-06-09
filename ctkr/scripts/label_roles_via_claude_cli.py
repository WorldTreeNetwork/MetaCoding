"""Live LLM labeler for role clusters via the local ``claude -p`` CLI.

Bypasses ``ctkr.llm.LLMClient`` (which talks to the Anthropic API directly)
so labeling runs spend the user's Claude Code subscription rather than
direct API credits. Single-shot calls with structured output via
``--json-schema``. Idempotent — skips clusters whose ``pattern_id`` is
already in ``patterns.jsonl``.

Usage (run from the ctkr/ subdirectory under MetaCoding):
    uv run python scripts/label_roles_via_claude_cli.py \\
        --data-dir /tmp/metacoding-scip \\
        --orchestrators-root ~/projects/Orchestrators \\
        --granularity 4 \\
        --max-clusters 5

Owning bd issue: MetaCoding-23q.4 (deferred-live-labeling spike).
"""

from __future__ import annotations

import argparse
import json
import logging
import shutil
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

import polars as pl

from ctkr.evidence import build_evidence_pack
from ctkr.graph_loader import load_graph
from ctkr.label_roles import (
    DEFAULT_GRANULARITY,
    DEFAULT_MAX_INSTANCES,
    DEFAULT_MIN_CLUSTER_SIZE,
    DEFAULT_PROMPT_VERSION,
    DEFAULT_TOKEN_BUDGET,
    SOURCE_KIND,
    RoleClusterLabelOutput,
    _load_existing_pattern_ids,
    _pick_anchors_by_repo,
    compute_role_clusters,
    pattern_id_for_role_cluster,
    render_prompt,
)
from ctkr.schema_l3 import EvidenceRow, LineRange, PatternRow

logger = logging.getLogger("ctkr.label_roles_cli")


JSON_ONLY_SUFFIX = (
    "\n\nIMPORTANT: Output ONLY a single JSON object matching the "
    "RoleClusterLabelOutput schema (keys: label, description, confidence). "
    "No prose, no markdown fences, no commentary — just the JSON."
)


def _call_claude_cli(
    prompt: str,
    schema: dict,
    *,
    timeout_seconds: int = 180,
) -> tuple[RoleClusterLabelOutput, float]:
    """Run ``claude -p`` on the prompt; parse the result; return (model, cost).

    Uses ``--bare`` to skip CLAUDE.md auto-discovery, hooks, plugins —
    we want a pure one-shot call against the user's subscription.
    """
    cmd = [
        "claude",
        "-p",
        "--bare",
        "--output-format",
        "json",
        "--json-schema",
        json.dumps(schema),
    ]
    full_prompt = prompt + JSON_ONLY_SUFFIX
    completed = subprocess.run(
        cmd,
        input=full_prompt,
        capture_output=True,
        text=True,
        timeout=timeout_seconds,
        check=False,
    )
    if completed.returncode != 0:
        raise RuntimeError(
            f"claude -p exited {completed.returncode}: {completed.stderr[:500]}"
        )
    envelope = json.loads(completed.stdout)
    if envelope.get("is_error"):
        raise RuntimeError(
            f"claude -p reported error: {envelope.get('result', '?')[:500]}"
        )
    cost = float(envelope.get("total_cost_usd") or 0.0)
    raw = envelope.get("result", "")
    parsed_json = _extract_first_json_object(raw)
    return RoleClusterLabelOutput.model_validate(parsed_json), cost


def _extract_first_json_object(text: str) -> dict:
    """Pull the first balanced ``{...}`` JSON object from text.

    Claude usually returns clean JSON when instructed to, but
    occasionally wraps it in markdown fences or adds a sentence — strip
    the noise before validating.
    """
    text = text.strip()
    if text.startswith("```"):
        # markdown fence — drop the first fence and anything after a
        # trailing fence.
        first_newline = text.find("\n")
        if first_newline != -1:
            text = text[first_newline + 1 :]
        if text.endswith("```"):
            text = text[: -3].rstrip()
    # Find the first { ... matching }.
    start = text.find("{")
    if start == -1:
        raise ValueError(f"no JSON object found in claude output: {text[:300]}")
    depth = 0
    in_string = False
    escape = False
    for i in range(start, len(text)):
        ch = text[i]
        if escape:
            escape = False
            continue
        if ch == "\\":
            escape = True
            continue
        if ch == '"':
            in_string = not in_string
            continue
        if in_string:
            continue
        if ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth == 0:
                return json.loads(text[start : i + 1])
    raise ValueError(f"unterminated JSON object in claude output: {text[:300]}")


def main() -> int:
    p = argparse.ArgumentParser(
        description=(
            "Live role-cluster labeler via the local `claude -p` CLI "
            "(Claude Code subscription). MetaCoding-23q.4."
        ),
    )
    p.add_argument("--data-dir", required=True)
    p.add_argument("--orchestrators-root", required=True)
    p.add_argument("--granularity", type=int, default=DEFAULT_GRANULARITY)
    p.add_argument("--min-cluster-size", type=int, default=DEFAULT_MIN_CLUSTER_SIZE)
    p.add_argument("--max-clusters", type=int, default=5)
    p.add_argument(
        "--max-instances-per-cluster", type=int, default=DEFAULT_MAX_INSTANCES
    )
    p.add_argument("--token-budget", type=int, default=DEFAULT_TOKEN_BUDGET)
    p.add_argument("--prompt-version", default=DEFAULT_PROMPT_VERSION)
    p.add_argument(
        "--llm-model",
        default="claude-cli",
        help=(
            "Provenance tag stored in PatternRow.llm_model. The actual "
            "model is chosen by the `claude` CLI; this string just "
            "records that the labeling lane was the CLI, not the API."
        ),
    )
    p.add_argument(
        "--skip-larger-than",
        type=int,
        default=None,
        help=(
            "Skip clusters with more members than this — useful to focus "
            "on mid-size, specific clusters rather than the dominant "
            "trivial profiles."
        ),
    )
    p.add_argument("--force", action="store_true")
    p.add_argument("--verbose", "-v", action="store_true")
    args = p.parse_args()

    logging.basicConfig(
        level=logging.INFO if args.verbose else logging.WARNING,
        format="%(asctime)s %(levelname)s %(message)s",
    )

    if not shutil.which("claude"):
        sys.stderr.write(
            "ERROR: `claude` CLI not found on PATH. Install Claude Code first.\n"
        )
        return 2

    data_dir = Path(args.data_dir).expanduser().resolve()
    orchestrators_root = Path(args.orchestrators_root).expanduser().resolve()
    ctkr_dir = data_dir / "ctkr"
    profiles_path = ctkr_dir / "hom_profiles.parquet"
    if not profiles_path.exists():
        sys.stderr.write(f"{profiles_path} not found. Run `ctkr hom-profiles` first.\n")
        return 2

    sys.stderr.write(f"loading graph from {data_dir}...\n")
    graph = load_graph(data_dir)
    sys.stderr.write(
        f"  {graph.number_of_nodes():,} nodes, {graph.number_of_edges():,} edges\n"
    )
    profiles_df = pl.read_parquet(profiles_path)
    sys.stderr.write(f"  {profiles_df.height:,} profile rows\n")

    sys.stderr.write(
        f"clustering at k={args.granularity} (min_size={args.min_cluster_size})...\n"
    )
    clusters = compute_role_clusters(
        profiles_df,
        granularity_k=args.granularity,
        min_cluster_size=args.min_cluster_size,
        drop_isolates=True,
    )
    if args.skip_larger_than is not None:
        clusters = [c for c in clusters if c.size <= args.skip_larger_than]
    if not clusters:
        sys.stderr.write("no clusters match selection.\n")
        return 0
    sys.stderr.write(f"  {len(clusters)} clusters available; labeling up to {args.max_clusters}\n")

    out_patterns = ctkr_dir / "patterns.jsonl"
    out_evidence = ctkr_dir / "evidence.jsonl"
    existing = _load_existing_pattern_ids(out_patterns) if not args.force else set()

    schema = RoleClusterLabelOutput.model_json_schema()

    n_labeled = 0
    n_skipped = 0
    n_failed = 0
    total_cost = 0.0
    targets = clusters[: args.max_clusters]

    with out_patterns.open("a", encoding="utf-8") as pf, out_evidence.open(
        "a", encoding="utf-8"
    ) as ef:
        for i, cluster in enumerate(targets, 1):
            pid = pattern_id_for_role_cluster(
                cluster.cluster_id,
                prompt_version=args.prompt_version,
                llm_model=args.llm_model,
            )
            if pid in existing:
                n_skipped += 1
                sys.stderr.write(
                    f"[{i}/{len(targets)}] {cluster.cluster_id} size={cluster.size} "
                    "skip (already labeled)\n"
                )
                continue

            anchors = _pick_anchors_by_repo(
                graph, cluster.members, max_instances=args.max_instances_per_cluster
            )
            if not anchors:
                n_skipped += 1
                sys.stderr.write(
                    f"[{i}/{len(targets)}] {cluster.cluster_id} size={cluster.size} "
                    "skip (no resolvable graph nodes)\n"
                )
                continue

            pack = build_evidence_pack(
                graph,
                anchors,
                source_kind=SOURCE_KIND,
                source_ref=cluster.cluster_id,
                orchestrators_root=orchestrators_root,
                token_budget=args.token_budget,
            )
            if not pack.instances:
                n_skipped += 1
                sys.stderr.write(
                    f"[{i}/{len(targets)}] {cluster.cluster_id} size={cluster.size} "
                    "skip (no readable evidence)\n"
                )
                continue

            prompt = render_prompt(cluster, pack, granularity_k=args.granularity)
            sys.stderr.write(
                f"[{i}/{len(targets)}] {cluster.cluster_id} size={cluster.size} "
                f"calling claude -p ({len(pack.instances)} instances, "
                f"{len(pack.repos_covered)} repos)...\n"
            )

            try:
                label_out, call_cost = _call_claude_cli(prompt, schema=schema)
            except Exception as e:  # noqa: BLE001
                n_failed += 1
                sys.stderr.write(f"    FAILED: {e}\n")
                continue

            now = datetime.now(tz=UTC)
            pattern = PatternRow(
                pattern_id=pid,
                source_kind=SOURCE_KIND,
                source_ref=cluster.cluster_id,
                label=label_out.label,
                description=label_out.description,
                instances=[inst.symbol_id for inst in pack.instances],
                confidence=label_out.confidence,
                llm_model=args.llm_model,
                llm_temperature=0.0,
                prompt_version=args.prompt_version,
                generated_at=now,
            )
            evidence_rows = [
                EvidenceRow(
                    pattern_id=pid,
                    repo=inst.repo,
                    file=inst.file,
                    line_range=LineRange(
                        start=inst.line_range.start, end=inst.line_range.end
                    ),
                    snippet=inst.snippet,
                    context=inst.qualified_name,
                )
                for inst in pack.instances
            ]
            pf.write(pattern.model_dump_json() + "\n")
            pf.flush()
            for ev in evidence_rows:
                ef.write(ev.model_dump_json() + "\n")
            ef.flush()
            existing.add(pid)
            n_labeled += 1
            total_cost += call_cost
            sys.stderr.write(
                f"    LABELED: {label_out.label!r} "
                f"(confidence={label_out.confidence:.2f}, cost=${call_cost:.4f})\n"
            )

    sys.stderr.write(
        f"\ndone — labeled={n_labeled} skipped={n_skipped} failed={n_failed} "
        f"total_cost=${total_cost:.4f}\n"
    )
    return 0 if n_failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
