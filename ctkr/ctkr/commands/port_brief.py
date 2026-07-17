"""``ctkr port-brief`` — render port_briefs/<subsystem>.md (Stage T5c / §4).

The re-implementation payload: the subsystem card rendered *for a builder*, with
shape and intention fused (SHAPE/INTENT/EVIDENCE triples), evidence budgeted by
intention load (§4.4), and a one-per-subsystem strong-model fusion writing the
distilled orientation + glossary + warnings (§8).

Reads ``subsystem_cards.jsonl`` (Stage E / ``ctkr extract-spec``) and
``intention.jsonl`` (Stage T5b / ``ctkr intention-synthesis``), attaches the
intention onto the deck, and renders one brief per selected subsystem to
``<data_dir>/ctkr/port_briefs/``. Each brief's regenerable digest is recorded in
``port_briefs/manifest.json`` and embedded in the brief header. Rides the shared
:class:`LLMClient` cache + cost log — temperature 0, so an unchanged card + harvest
re-runs free and byte-identical.

See :mod:`ctkr.port_brief` for the renderer/allocator/fusion and
``docs/design/ct-intention-extraction.md`` §4 for the spec.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "port-brief",
        help="Render port_briefs/<subsystem>.md — the re-implementation payload (T5c).",
        description=(
            "Render the port brief(s) for one or more subsystems (ct-intention-"
            "extraction.md §4): SHAPE/INTENT/EVIDENCE triples per element, evidence "
            "budgeted by intention load (§4.4), and a one-per-subsystem strong-model "
            "fusion for the distilled orientation + glossary + warnings (§8). Reads "
            "subsystem_cards.jsonl (extract-spec) + intention.jsonl "
            "(intention-synthesis). Deterministic brief digest for fixed inputs + "
            "prompt-version + model."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--subsystem",
        default=None,
        help="Render only this subsystem_id (default: all cards in the deck).",
    )
    p.add_argument(
        "--max-briefs",
        type=int,
        default=None,
        help="Cap the number of briefs rendered, richest-intention first "
        "(most load-scored + conflict-bearing elements).",
    )
    p.add_argument(
        "--fusion-model", default=None, help="Strong model for brief fusion (sonnet default)."
    )
    p.add_argument("--prompt-version", default=None, help="Override prompt_version.")
    p.add_argument(
        "--distilled-tokens",
        type=int,
        default=None,
        help="Target tokens per element for the distilled sections (dial, default 300).",
    )
    p.add_argument(
        "--appendix-multiple",
        type=float,
        default=None,
        help="Appendix budget as a multiple of the distilled budget (dial, default 6).",
    )
    p.add_argument(
        "--generated-at",
        default=None,
        help="Fixed ISO-8601 timestamp for the brief footer (does not affect the digest).",
    )
    p.set_defaults(func=run)


def _richness(card) -> tuple[int, int]:  # noqa: ANN001
    """Sort key: elements carrying a load class, then conflict-bearing elements."""
    loaded = sum(1 for e in card.intention if e.load_class)
    conflicts = sum(len(e.conflicts) for e in card.intention)
    return (loaded, conflicts)


def run(args: argparse.Namespace) -> int:
    import polars as pl

    from ctkr.cards import attach_intention_to_deck, read_cards
    from ctkr.llm import LLMClient
    from ctkr.port_brief import (
        DEFAULT_FUSION_MODEL,
        DEFAULT_PROMPT_VERSION,
        BudgetConfig,
        PortBriefConfig,
        brief_filename,
        build_port_brief,
        write_brief,
    )

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    cards_path = ctkr_dir / "subsystem_cards.jsonl"
    intention_path = ctkr_dir / "intention.jsonl"
    signals_path = ctkr_dir / "intention_signals.parquet"

    if not cards_path.exists():
        sys.stderr.write(
            f"ERROR: {cards_path.name} not found under {ctkr_dir} — run "
            f"`ctkr extract-spec` first.\n"
        )
        return 2
    if not signals_path.exists():
        sys.stderr.write(
            f"ERROR: {signals_path.name} not found — run `ctkr intention` (T5a) first.\n"
        )
        return 2

    cards = read_cards(cards_path)
    if intention_path.exists():
        cards = attach_intention_to_deck(cards, intention_path)
    else:
        sys.stderr.write(
            f"WARNING: {intention_path.name} not found — briefs will render SHAPE only "
            f"(run `ctkr intention-synthesis` for the INTENT/EVIDENCE lanes).\n"
        )
    signals_df = pl.read_parquet(signals_path)

    selected = cards
    if args.subsystem:
        selected = [c for c in cards if c.subsystem_id == args.subsystem]
        if not selected:
            sys.stderr.write(f"ERROR: subsystem {args.subsystem!r} not in the deck.\n")
            return 2
    else:
        selected = sorted(cards, key=_richness, reverse=True)
        if args.max_briefs is not None:
            selected = selected[: args.max_briefs]

    budget = BudgetConfig()
    if args.distilled_tokens is not None:
        budget = BudgetConfig(
            **{**budget.__dict__, "distilled_tokens_per_element": args.distilled_tokens}
        )
    if args.appendix_multiple is not None:
        budget = BudgetConfig(**{**budget.__dict__, "appendix_multiple": args.appendix_multiple})
    cfg = PortBriefConfig(
        budget=budget,
        fusion_model=args.fusion_model or DEFAULT_FUSION_MODEL,
        prompt_version=args.prompt_version or DEFAULT_PROMPT_VERSION,
    )

    client = LLMClient(cache_dir=ctkr_dir / "llm_cache", cost_log=ctkr_dir / "llm_cost.jsonl")
    out_dir = ctkr_dir / "port_briefs"

    manifest_entries: dict[str, dict] = {}
    total_cost = 0.0
    written: list[Path] = []
    for card in selected:
        md, stats = build_port_brief(
            card, signals_df, client, cfg, generated_at=args.generated_at
        )
        path = write_brief(md, out_dir, card.subsystem_id)
        written.append(path)
        total_cost += stats.fusion_cost_usd
        manifest_entries[card.subsystem_id] = {
            "brief_digest": stats.brief_digest,
            "fusion_digest": stats.fusion_digest,
            "file": brief_filename(card.subsystem_id),
            "card_id": card.card_id,
            "n_roles": stats.n_roles,
            "n_exports": stats.n_exports,
            "n_ops": stats.n_ops,
            "n_shapes": stats.n_shapes,
            "n_scenarios": stats.n_scenarios,
            "n_warnings": stats.n_warnings,
            "n_glossary_terms": stats.n_glossary_terms,
            "n_signals_materialized": stats.n_signals_materialized,
            "n_signals_elided": stats.n_signals_elided,
            "load": {
                "structure_clear": stats.n_structure_clear,
                "intention_critical": stats.n_intention_critical,
                "ambiguous": stats.n_ambiguous,
            },
            "fusion_cost_usd": stats.fusion_cost_usd,
            "fusion_cache_hit": stats.fusion_cache_hit,
        }
        sys.stderr.write(
            f"  ✓ {card.subsystem_id}  →  {path.name}  "
            f"[{stats.n_exports} exports, {stats.n_roles} roles, {stats.n_ops} ops, "
            f"{stats.n_scenarios} scenarios, {stats.n_warnings} warnings; "
            f"digest {stats.brief_digest}; ${stats.fusion_cost_usd:.4f}"
            f"{' cached' if stats.fusion_cache_hit else ''}]\n"
        )

    manifest_path = out_dir / "manifest.json"
    manifest_path.write_text(
        json.dumps(
            {
                "prompt_version": cfg.prompt_version,
                "fusion_model": cfg.fusion_model,
                "n_briefs": len(written),
                "briefs": manifest_entries,
            },
            indent=2,
        ),
        encoding="utf-8",
    )

    sys.stderr.write(
        f"\n  briefs written : {len(written)} → {out_dir}\n"
        f"  fusion cost    : ${total_cost:.4f}\n"
        f"  manifest       : {manifest_path}\n"
    )

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "n_briefs": len(written),
                    "out_dir": str(out_dir),
                    "total_fusion_cost_usd": round(total_cost, 6),
                    "briefs": manifest_entries,
                },
                indent=2,
            )
            + "\n"
        )
    return 0
