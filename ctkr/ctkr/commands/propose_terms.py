"""``ctkr propose-terms`` — the naming joint (bead MetaCoding-5c5).

For each surviving lexicon candidate (glossary-gaps config diff + role-gaps
role sweep) the configured LLM emits a full TERM-SPEC v1 naming brief:
term name, kind, description, probe semantics, and a discriminating flow
sketch restricted to existing flow-DSL vocabulary plus the proposed term.

Same posture as ``propose-adapter``: the LLM PROPOSES, never binds.
Provenance is carried over from the candidate; ``first_pack_seal`` stays
``null`` (PROVISIONAL until a real sealed recording fills it at the binding
gate, MetaCoding-b5r). This command never touches
:mod:`ctkr.oracle.glossary`.

LLM cache + cost log default to a per-user scratch location (never a graph
sandbox, never the scanned source tree): ``~/.cache/ctkr/propose-terms/``.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import (
    DEFAULT_LLM_PROVIDER,
    GPT56_STRONG_MODEL,
    emit,
    require_provider_key,
)

DEFAULT_SCRATCH = Path.home() / ".cache" / "ctkr" / "propose-terms"


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "propose-terms",
        help="LLM naming briefs (TERM-SPEC v1) for lexicon candidates — "
        "proposes, never binds.",
        description=(
            "The naming joint (MetaCoding-5c5): for each candidate from "
            "glossary-gaps and/or role-gaps, a schema-forced LLM call (with "
            "the house single repair retry) produces a full TERM-SPEC v1 "
            "proposal — term, kind, description, probe semantics, and a "
            "discriminating flow sketch using ONLY existing flow-DSL actions "
            "plus the proposed term. Candidates surfaced by BOTH channels are "
            "deduped into one proposal (config_source AND role_class_id set) "
            "and ordered first as the strongest. Output rows are PROVISIONAL: "
            "first_pack_seal stays null until the binding gate seals a real "
            "recording. The glossary itself is never written."
        ),
    )
    p.add_argument(
        "--candidates",
        action="append",
        required=True,
        metavar="JSONL",
        help="Candidate rows file (repeatable): glossary-gaps gaps.jsonl "
        "and/or role-gaps role-classes JSONL.",
    )
    p.add_argument(
        "--out",
        default="term-proposals.jsonl",
        help="Output JSONL path (default ./term-proposals.jsonl). Point at "
        "scratch or in-repo results — never at a read-only sandbox.",
    )
    p.add_argument(
        "--provider",
        default=None,
        help=f"LLM provider (default {DEFAULT_LLM_PROVIDER}).",
    )
    p.add_argument(
        "--model",
        default=None,
        help=f"Naming model (default {GPT56_STRONG_MODEL}).",
    )
    p.add_argument(
        "--reasoning-effort", default=None, help="GPT-5.x reasoning effort."
    )
    p.add_argument(
        "--max-spend",
        type=float,
        default=3.0,
        help="Abort if PROJECTED spend exceeds this many USD, and stop if "
        "accumulated real spend crosses it (default 3.0).",
    )
    p.add_argument(
        "--cache-dir",
        default=str(DEFAULT_SCRATCH / "llm_cache"),
        help="LLM prompt cache directory (default "
        f"{DEFAULT_SCRATCH / 'llm_cache'} — scratch, never a sandbox).",
    )
    p.add_argument(
        "--cost-log",
        default=str(DEFAULT_SCRATCH / "llm_cost.jsonl"),
        help="House cost-telemetry JSONL (default "
        f"{DEFAULT_SCRATCH / 'llm_cost.jsonl'}).",
    )
    p.add_argument(
        "--json", dest="as_json", action="store_true",
        help="Emit the run summary as JSON on stdout.",
    )
    p.set_defaults(func=run)


def _build_client(args: argparse.Namespace, provider: str):
    """Constructed here (not inline in run) so tests can monkeypatch."""
    from ctkr.llm import LLMClient

    return LLMClient(
        cache_dir=Path(args.cache_dir).expanduser(),
        cost_log=Path(args.cost_log).expanduser(),
        default_provider=provider,
    )


def run(args: argparse.Namespace) -> int:
    from ctkr.propose_terms import (
        SpendExceededError,
        build_term_prompt,
        load_candidate_rows,
        merge_channels,
        normalize_rows,
        project_spend,
        propose_all,
        write_proposals_jsonl,
    )

    cand_paths = [Path(c).expanduser().resolve() for c in args.candidates]
    missing = [p for p in cand_paths if not p.is_file()]
    if missing:
        for p in missing:
            sys.stderr.write(f"ERROR: --candidates {p} is not a file.\n")
        return 2

    rows = load_candidate_rows(cand_paths)
    candidates = merge_channels(normalize_rows(rows))
    n_both = sum(1 for c in candidates if c.channels == "config+role")
    sys.stderr.write(
        f"loaded {len(rows)} row(s) from {len(cand_paths)} file(s) -> "
        f"{len(candidates)} candidate(s) after dedup "
        f"({n_both} surfaced by BOTH channels — strongest, ordered first)\n"
    )
    if not candidates:
        sys.stderr.write("ERROR: no candidates to propose over.\n")
        return 2

    provider = args.provider or DEFAULT_LLM_PROVIDER
    model = args.model or GPT56_STRONG_MODEL
    rc = require_provider_key(
        provider, stage="propose-terms naming", default_hint=f"OpenAI {model}"
    )
    if rc is not None:
        return rc

    projected = project_spend([build_term_prompt(c) for c in candidates], model)
    sys.stderr.write(f"projected spend: ${projected:.4f} (budget ${args.max_spend:.2f})\n")
    if projected > args.max_spend:
        sys.stderr.write(
            f"ABORT: projected spend ${projected:.4f} exceeds --max-spend "
            f"${args.max_spend:.2f}; nothing was called. Raise --max-spend or "
            "trim --candidates.\n"
        )
        return 2

    client = _build_client(args, provider)
    out_path = Path(args.out).expanduser().resolve()
    try:
        proposals, total = propose_all(
            candidates,
            client,
            provider=provider,
            model=model,
            reasoning_effort=args.reasoning_effort,
            max_spend=float(args.max_spend),
        )
    except SpendExceededError as e:
        sys.stderr.write(f"ABORT mid-run: {e}\n(no partial output written)\n")
        return 3

    write_proposals_jsonl(proposals, out_path)

    table = [
        {
            "term": r["term"],
            "kind": r["kind"],
            "channels": c.channels,
            "source": r["provenance"]["config_source"]
            or r["provenance"]["role_class_id"],
        }
        for c, r in zip(candidates, proposals, strict=True)
    ]
    emit(table, as_json=False, columns=["term", "kind", "channels", "source"])
    sys.stderr.write(
        f"\n  proposals   : {len(proposals)} (all PROVISIONAL — "
        "first_pack_seal null; nothing bound)\n"
        f"  output      : {out_path}\n"
        f"  spend       : ${total:.4f} ({provider}:{model})\n"
        f"  cost log    : {Path(args.cost_log).expanduser()}\n"
    )

    if args.as_json:
        sys.stdout.write(
            json.dumps(
                {
                    "n_candidates": len(candidates),
                    "n_both_channels": n_both,
                    "n_proposals": len(proposals),
                    "out": str(out_path),
                    "provider": provider,
                    "model": model,
                    "projected_spend_usd": round(projected, 6),
                    "spend_usd": round(total, 6),
                },
                indent=2,
            )
            + "\n"
        )
    return 0
