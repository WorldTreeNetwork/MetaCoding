"""``ctkr glossary-gaps`` — deterministic vocabulary diff (glossary-as-topology).

Diffs a scoped farmOS module set's declarative config (workflow FSM states,
config-entity type lists, allowed-values maps, bundle fields declared in
attribute plugins) against the oracle glossary's closed sets
(:mod:`ctkr.oracle.glossary`). Writes ``gaps.jsonl`` (one row per gap, each
carrying a partial TERM-SPEC v1 candidate) and prints a human summary table.

Zero LLM, zero network, read-only over the scanned tree; the only write is
``--out``. See :mod:`ctkr.lexicon` for the scan itself.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

DEFAULT_SRCS = (
    "/private/tmp/farmos-cell3-2026-07-19/farm-src/modules/log",
    "/private/tmp/farmos-cell3-2026-07-19/farm-src/modules/asset/land",
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "glossary-gaps",
        help="Deterministic vocabulary diff: source declarative config vs the "
        "glossary's closed sets.",
        description=(
            "Walk a scoped farmOS module set's DECLARATIVE config (*.workflows.yml "
            "states, config/install + config/optional config entities, field "
            "storage/instance definitions with allowed_values, bundle fields in "
            "PHP attribute plugins) and diff every declared vocabulary item "
            "against the oracle glossary's closed sets (LOG_STATUSES, LOG_KINDS, "
            "MEASURES, ENTITY_TERMS, ASSERTION_TERMS). One gaps.jsonl row per "
            "gap, each with a partial TERM-SPEC v1 candidate (PROVISIONAL: "
            "first_pack_seal is null; this command proposes, never binds). "
            "Deterministic — no LLM, no network, no writes into the scanned tree."
        ),
    )
    p.add_argument(
        "--src",
        action="append",
        default=None,
        help="Module directory to scan (repeatable). Defaults to the wave-1 "
        f"sandbox scope: {', '.join(DEFAULT_SRCS)}.",
    )
    p.add_argument(
        "--rel-root",
        default=None,
        help="Root that source_ref paths are made relative to (default: each "
        "--src itself).",
    )
    p.add_argument(
        "--out",
        default="gaps.jsonl",
        help="Path for the gaps.jsonl output (default: ./gaps.jsonl). Point "
        "this at scratch or in-repo results — never at the scanned sandbox.",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the run summary as JSON on stdout (after the table).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.lexicon import scan_sources, summary_table, write_gaps_jsonl

    srcs = [Path(s).expanduser().resolve() for s in (args.src or DEFAULT_SRCS)]
    missing = [s for s in srcs if not s.is_dir()]
    if missing:
        for s in missing:
            sys.stderr.write(f"ERROR: --src {s} is not a directory.\n")
        return 2

    out_path = Path(args.out).expanduser().resolve()
    for s in srcs:
        if out_path.is_relative_to(s):
            sys.stderr.write(
                f"ERROR: --out {out_path} lies inside scanned source {s} — "
                "the scanned tree is read-only; point --out elsewhere.\n")
            return 2

    rel_root = Path(args.rel_root).expanduser().resolve() if args.rel_root else None
    gaps = scan_sources(srcs, rel_root=rel_root)
    write_gaps_jsonl(gaps, out_path)

    sys.stdout.write(summary_table(gaps) + "\n")
    sys.stderr.write(f"  gaps.jsonl : {out_path}\n")

    if args.as_json:
        by_kind: dict[str, int] = {}
        for g in gaps:
            by_kind[g.gap_kind] = by_kind.get(g.gap_kind, 0) + 1
        sys.stdout.write(json.dumps({
            "n_gaps": len(gaps),
            "by_kind": dict(sorted(by_kind.items())),
            "srcs": [str(s) for s in srcs],
            "out": str(out_path),
        }, indent=2) + "\n")
    return 0
