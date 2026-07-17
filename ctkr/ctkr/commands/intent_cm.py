"""``ctkr intent-cm`` — consistency-model-sensitivity tag (port-loop Phase 3).

Mechanically seeds an intent-CM grade over a source tree (a versioned regex
detector table over transaction / unique-constraint / autoincrement-id /
access-check / revision-lock sites), then OPTIONALLY LM-adjudicates the flagged
subset {hard | soft | none} with the strong model. Writes:

* ``intent_cm.parquet`` — the deterministic mechanical seed (no LLM);
* ``intent_cm_adjudicated.jsonl`` — the strong-model verdicts (with ``--adjudicate``).

The CM grade describes the SOURCE's central-authority assumptions and stands
alone; a target profile (``--target-profile``) only conditions how a port brief
responds to them. See :mod:`ctkr.intent_cm` and ``port-loop-plan.md`` Phase 3.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import resolve_data_dir


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "intent-cm",
        help="Consistency-model-sensitivity tag (port-loop Phase 3) — mechanical "
        "seed + optional LM adjudication.",
        description=(
            "Tag every central-authority assumption in a source tree (ACID "
            "transactions, unique constraints, autoincrement ids, server-side access "
            "checks, revision/locks) with a consistency-model-sensitivity grade. "
            "Mechanical seed is deterministic + LLM-free (intent_cm.parquet); "
            "--adjudicate routes the flagged subset to a strong model for "
            "{hard|soft|none} classification (intent_cm_adjudicated.jsonl). The grade "
            "describes the SOURCE and conditions only a port brief's target-adaptation "
            "section — the system stands alone without a target profile."
        ),
    )
    p.add_argument(
        "--source-root",
        required=True,
        help="Path to the source tree to scan (a Drupal/PHP site, a TS/Python repo, …).",
    )
    p.add_argument(
        "--data-dir",
        default=None,
        help="Path to .metacoding/ where artifacts are written under ctkr/ "
        "(auto-detected by walking up from cwd if omitted).",
    )
    p.add_argument(
        "--id-prefix",
        default="",
        help="Prefix prepended to element_id (e.g. a repo name) so seeds from "
        "different corpora never collide.",
    )
    p.add_argument(
        "--adjudicate",
        action="store_true",
        help="Run the strong-model adjudication over the flagged (CM-hard/CM-soft) "
        "subset. Off by default (LLM spend).",
    )
    p.add_argument("--model", default=None, help="Strong adjudication model (sonnet default).")
    p.add_argument("--prompt-version", default=None, help="Override the adjudication prompt_version.")
    p.add_argument(
        "--max-elements",
        type=int,
        default=None,
        help="Cap the number of elements adjudicated (cost control).",
    )
    p.add_argument(
        "--target-profile",
        default=None,
        help="OPTIONAL target-profile YAML (docs/design/target-profile.md format). "
        "When given, prints a target-adaptation preview; never required.",
    )
    p.add_argument(
        "--json", dest="as_json", action="store_true", help="Emit the run summary as JSON on stdout."
    )
    p.add_argument(
        "--generated-at",
        default=None,
        help="Fixed ISO-8601 timestamp for the manifest (byte-identical re-runs).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.intent_cm import (
        DEFAULT_MODEL,
        DEFAULT_PROMPT_VERSION,
        INTENT_CM_ADJUDICATED_FILE,
        INTENT_CM_FILE,
        TargetProfile,
        adjudicate_cm,
        build_target_adaptation_notes,
        scan_cm,
        write_adjudicated_jsonl,
        write_intent_cm,
        write_manifest,
    )

    source_root = Path(args.source_root).expanduser().resolve()
    if not source_root.exists():
        sys.stderr.write(f"ERROR: --source-root {source_root} does not exist.\n")
        return 2

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    ctkr_dir.mkdir(parents=True, exist_ok=True)

    sys.stderr.write(f"scanning {source_root} for consistency-model-sensitive sites...\n")
    cm_df, scan_stats = scan_cm(source_root, id_prefix=args.id_prefix)
    write_intent_cm(cm_df, ctkr_dir / INTENT_CM_FILE)

    adjudicated = []
    adj_stats = None
    if args.adjudicate:
        from ctkr.llm import LLMClient

        client = LLMClient(cache_dir=ctkr_dir / "llm_cache", cost_log=ctkr_dir / "llm_cost.jsonl")
        sys.stderr.write("adjudicating flagged subset with the strong model...\n")
        adjudicated, adj_stats = adjudicate_cm(
            cm_df,
            client,
            model=args.model or DEFAULT_MODEL,
            prompt_version=args.prompt_version or DEFAULT_PROMPT_VERSION,
            max_elements=args.max_elements,
        )
        write_adjudicated_jsonl(adjudicated, ctkr_dir / INTENT_CM_ADJUDICATED_FILE)

    manifest_path = write_manifest(
        data_dir,
        n_seeds=cm_df.height,
        n_adjudicated=len(adjudicated),
        generated_at=args.generated_at,
    )

    sys.stderr.write(
        "\n"
        f"  files scanned      : {scan_stats.n_files_scanned:,}\n"
        f"  CM seeds           : {scan_stats.n_seeds:,} over {scan_stats.n_elements:,} element(s)\n"
        f"  by category        : {scan_stats.by_category}\n"
        f"  by seed prior      : {scan_stats.by_seed}\n"
        f"  by language        : {scan_stats.by_language}\n"
        f"  artifact           : {ctkr_dir / INTENT_CM_FILE}\n"
    )
    if adj_stats is not None:
        sys.stderr.write(
            f"  adjudicated        : {adj_stats.n_elements:,} element(s)\n"
            f"  by sensitivity     : {adj_stats.by_sensitivity}\n"
            f"  llm cost / cached  : ${adj_stats.total_cost_usd:.4f} / {adj_stats.cache_hits} hit(s)\n"
            f"  failed calls       : {adj_stats.n_failed_calls}\n"
            f"  artifact           : {ctkr_dir / INTENT_CM_ADJUDICATED_FILE}\n"
        )
    sys.stderr.write(f"  manifest           : {manifest_path}\n")

    if args.target_profile:
        profile = TargetProfile.load(args.target_profile)
        notes = build_target_adaptation_notes(adjudicated, profile)
        sys.stderr.write(
            f"\n  target profile     : {profile.id} ({profile.name})\n"
            f"  adaptation notes   : {'rendered ' + str(sum(1 for a in adjudicated if a.sensitivity in ('hard','soft'))) + ' element(s)' if notes else '(none — run --adjudicate first)'}\n"
        )

    if getattr(args, "as_json", False):
        payload = {
            "n_seeds": scan_stats.n_seeds,
            "n_elements": scan_stats.n_elements,
            "by_category": scan_stats.by_category,
            "by_seed": scan_stats.by_seed,
            "by_language": scan_stats.by_language,
            "by_detector": scan_stats.by_detector,
            "n_files_scanned": scan_stats.n_files_scanned,
            "data_dir": str(Path(data_dir).resolve()),
        }
        if adj_stats is not None:
            payload["adjudication"] = {
                "n_elements": adj_stats.n_elements,
                "by_sensitivity": adj_stats.by_sensitivity,
                "total_cost_usd": adj_stats.total_cost_usd,
                "cache_hits": adj_stats.cache_hits,
                "n_failed_calls": adj_stats.n_failed_calls,
            }
        sys.stdout.write(json.dumps(payload, indent=2, default=str) + "\n")
    return 0
