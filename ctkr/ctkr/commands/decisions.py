"""``ctkr decisions`` — the design-decision elicitation layer (bead MetaCoding-9h5.13).

Surfaces the port's pending design decisions from the existing artifacts, ranks them
by uncertainty × blast-radius, and lets the developer resolve each (interview,
decide-for-me, recommend, or roll-forward). Every committing resolution appends a Port
Decision to the data-dir ledger so the builder receives it as a pre-registered
constraint.

Subcommands::

    ctkr decisions [collect]       # collect + persist decisions.jsonl (the registry)
    ctkr decisions list            # render the ranked menu
    ctkr decisions resolve <id> --interview | --decide <opt> | --decide-for-me
                                   | --recommend | --roll-forward

See :mod:`ctkr.decisions` for the machinery and ``docs/design/meta-structural-pass.md``
for how resolved decisions become pre-registered constraints.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr import inflight
from ctkr.commands._common import (
    DEFAULT_LLM_PROVIDER,
    GPT56_STRONG_MODEL,
    require_provider_key,
    resolve_data_dir,
)

# The strong (sonnet-class) model the elicitation/decide flows default to on OpenAI
# (gpt-5.6-terra — the adopted strong role, MetaCoding-9h5.9). Anthropic falls back to
# sonnet.
_ANTHROPIC_STRONG_MODEL = "claude-sonnet-4-6"


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "decisions",
        help="Design-decision elicitation — surface, rank, and resolve the port's "
        "pending design decisions before the build.",
        description=(
            "Collect the port's pending design decisions from the existing artifacts "
            "(intent-CM adjudications with decision menus, verifyPort paradigm-divergence "
            "declarations, and unresolved brief adaptation notes), rank them by "
            "uncertainty × blast-radius (graph reach, LM-free), and resolve each via "
            "interview / decide-for-me / recommend / roll-forward. Every committing "
            "resolution appends a Port Decision to the ledger."
        ),
    )
    sub = p.add_subparsers(dest="subcommand", metavar="SUBCOMMAND")

    # --- collect (also the bare `ctkr decisions` default) ---
    c = sub.add_parser(
        "collect",
        help="Collect pending decisions from the artifacts and persist decisions.jsonl.",
    )
    _add_collect_flags(c)
    c.set_defaults(func=run_collect)

    # --- list ---
    lst = sub.add_parser("list", help="Render the ranked decision menu.")
    lst.add_argument("--data-dir", default=None, help="Path to .metacoding/ (auto-detected).")
    lst.add_argument(
        "--status",
        default=None,
        help="Filter to one status: pending / decided-by-developer / decided-for-me / "
        "rolled-forward.",
    )
    lst.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON.")
    lst.set_defaults(func=run_list)

    # --- emit (an in-flight agent reporting a decision it needs) ---
    em = sub.add_parser(
        "emit",
        help="Append an in-flight decision signal (punt / invented / conflict / "
             "blocked) to the wave ledger, from a RUNNING agent.",
        description=(
            "A running agent reports the moment it defers, invents, or hits a "
            "conflict — rather than at the end, when the wave has already built "
            "on it. The ledger is append-only JSONL; an agent in any language may "
            "append a line directly instead of using this command."
        ),
    )
    em.add_argument("--data-dir", default=None, help="Path to .metacoding/ (auto-detected).")
    em.add_argument("--agent", required=True, help="Agent label or build id (an interrupt needs to find you).")
    em.add_argument("--feature", required=True, help="The feature being ported.")
    em.add_argument("--topic", required=True,
                    help="STABLE slug for what is being decided — prefer an existing "
                         "invariant name, since punt-promotion counts by this.")
    em.add_argument("--kind", required=True, choices=sorted(inflight.KINDS))
    em.add_argument("--statement", required=True, help="One sentence: what is at stake.")
    em.add_argument("--event-kinds", default="", help="Comma-separated event kinds touched (blast radius).")
    em.add_argument("--assumption", default="", help="What you did meanwhile. An honest punt says so.")
    em.add_argument("--kernel", default="", help="Kernel pin you are running against.")
    em.add_argument("--at", default="", help="ISO-8601 timestamp.")
    em.set_defaults(func=run_emit)

    # --- inflight (the orchestrator polling) ---
    inf = sub.add_parser(
        "inflight",
        help="Read the in-flight ledger: what running agents need, what to promote.",
    )
    inf.add_argument("--data-dir", default=None, help="Path to .metacoding/ (auto-detected).")
    inf.add_argument("--threshold", type=int, default=2,
                     help="Distinct agents on one topic before it is a kernel candidate.")
    inf.add_argument("--touching", default="",
                     help="Comma-separated event kinds: list the agents an interrupt "
                          "would target.")
    inf.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON.")
    inf.set_defaults(func=run_inflight)

    # --- resolve ---
    r = sub.add_parser(
        "resolve",
        help="Resolve one decision (interview / decide / decide-for-me / recommend / "
        "roll-forward).",
    )
    r.add_argument("decision_id", help="The decision id (dec:...) to resolve.")
    r.add_argument("--data-dir", default=None, help="Path to .metacoding/ (auto-detected).")
    mode = r.add_mutually_exclusive_group(required=True)
    mode.add_argument(
        "--interview",
        action="store_true",
        help="Emit a structured elicitation doc (LLM tradeoff analysis per option); "
        "stays pending until answered.",
    )
    mode.add_argument(
        "--decide",
        metavar="OPTION",
        default=None,
        help="Record the developer's answer (an option id). Appends a Port Decision. "
        "Use with --rationale.",
    )
    mode.add_argument(
        "--decide-for-me",
        action="store_true",
        help="Let the agent pick via LLM (records rationale, marks decided-for-me). "
        "Appends a Port Decision.",
    )
    mode.add_argument(
        "--recommend",
        action="store_true",
        help="Emit recommendations only (LLM); stays pending.",
    )
    mode.add_argument(
        "--roll-forward",
        action="store_true",
        help="Explicitly defer (logged, flagged reversible). Appends a Port Decision.",
    )
    r.add_argument(
        "--rationale", default="", help="Rationale to record (with --decide / --roll-forward)."
    )
    r.add_argument("--out", default=None, help="Write the interview/recommend doc to this path.")
    r.add_argument("--author", default=None, help="Author recorded on the Port Decision.")
    r.add_argument("--provider", default=None, help="LLM provider (openai default; anthropic).")
    r.add_argument(
        "--model", default=None, help="Strong elicitation model (gpt-5.6-terra default)."
    )
    r.add_argument(
        "--max-cost-usd",
        type=float,
        default=2.0,
        help="Abort a mode before an LLM call if the run's spend would exceed this cap "
        "(default $2).",
    )
    r.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON.")
    r.set_defaults(func=run_resolve)

    # bare `ctkr decisions` → collect
    _add_collect_flags(p)
    p.set_defaults(func=run_collect)


def _add_collect_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("--data-dir", default=None, help="Path to .metacoding/ (auto-detected).")
    p.add_argument(
        "--target-profile",
        default=None,
        help="OPTIONAL target-profile YAML — supplies the CM decision menus. Without it "
        "a conservative default menu is used.",
    )
    p.add_argument(
        "--port-verify-dir",
        default=None,
        help="OPTIONAL directory of verifyPort report JSONs (paradigm-divergence source). "
        "Defaults to <data-dir>/ctkr/port_verify/ if present.",
    )
    p.add_argument(
        "--no-brief-adaptation",
        action="store_true",
        help="Skip the brief-adaptation (role intent_dissonance) collector.",
    )
    p.add_argument(
        "--generated-at",
        default=None,
        help="Fixed ISO-8601 timestamp (byte-identical re-runs).",
    )
    p.add_argument("--json", dest="as_json", action="store_true", help="Emit JSON summary.")


# ───────────────────────── collect ─────────────────────────


def _load_graph_opt(data_dir: Path):
    """Load the exported graph if present, else None (blast radius degrades gracefully)."""
    try:
        from ctkr.graph_loader import load_graph

        return load_graph(data_dir)
    except FileNotFoundError:
        sys.stderr.write(
            "  note: no exported graph (nodes.jsonl/edges.jsonl) — blast radius will "
            "use subsystem membership only.\n"
        )
        return None


def _load_members_opt(ctkr_dir: Path):
    import polars as pl

    p = ctkr_dir / "subsystem_members.parquet"
    return pl.read_parquet(p) if p.exists() else None


def _load_cards(ctkr_dir: Path) -> list[dict]:
    p = ctkr_dir / "subsystem_cards.jsonl"
    if not p.exists():
        return []
    out: list[dict] = []
    with p.open("r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if line:
                out.append(json.loads(line))
    return out


def _load_port_verify_reports(data_dir: Path, ctkr_dir: Path, explicit: str | None) -> list[dict]:
    candidates: list[Path] = []
    if explicit:
        candidates.append(Path(explicit).expanduser())
    else:
        candidates.append(ctkr_dir / "port_verify")
    reports: list[dict] = []
    for d in candidates:
        if d.is_dir():
            for jf in sorted(d.glob("*.json")):
                try:
                    reports.append(json.loads(jf.read_text(encoding="utf-8")))
                except json.JSONDecodeError:
                    sys.stderr.write(f"  warning: {jf} is not valid JSON; skipped.\n")
        elif d.is_file():
            try:
                reports.append(json.loads(d.read_text(encoding="utf-8")))
            except json.JSONDecodeError:
                sys.stderr.write(f"  warning: {d} is not valid JSON; skipped.\n")
    return reports


def run_emit(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    record = inflight.InflightRecord(
        agent=args.agent, feature=args.feature, topic=args.topic,
        kind=args.kind, statement=args.statement,
        event_kinds=tuple(k.strip() for k in args.event_kinds.split(",") if k.strip()),
        assumption=args.assumption, kernel=args.kernel, at=args.at,
    )
    path = inflight.emit(record, data_dir)
    sys.stderr.write(f"  emitted {args.kind} on {args.topic!r} -> {path}\n")
    return 0


def run_inflight(args: argparse.Namespace) -> int:
    data_dir = resolve_data_dir(args.data_dir)
    read = inflight.read(data_dir)
    attention = inflight.needs_attention(read.records)
    promotions = inflight.promotion_candidates(read.records, args.threshold)
    targeted = (
        inflight.affected_agents(
            read.records,
            {k.strip() for k in args.touching.split(",") if k.strip()},
        )
        if args.touching
        else []
    )

    if args.as_json:
        sys.stdout.write(json.dumps({
            "records": [json.loads(r.to_json()) for r in read.records],
            "malformed": read.malformed,
            "needs_attention": [json.loads(r.to_json()) for r in attention],
            "promotion_candidates": [
                {"topic": t, "agents": sorted({r.agent for r in rs}),
                 "records": [json.loads(r.to_json()) for r in rs]}
                for t, rs in promotions
            ],
            "affected_agents": targeted,
        }, indent=2) + "\n")
        return 0

    w = sys.stderr.write
    w(f"\n  in-flight records : {len(read.records)}\n")
    if read.malformed:
        # Never silently dropped: a malformed report is still a report.
        w(f"  MALFORMED         : {len(read.malformed)} (an agent tried to tell us something)\n")
        for m in read.malformed:
            w(f"    ! {m}\n")
    if attention:
        w(f"\n  NEEDS ATTENTION NOW ({len(attention)}) — conflicts and blocked agents:\n")
        for r in attention:
            w(f"    [{r.kind}] {r.agent} · {r.topic}: {r.statement}\n")
    if promotions:
        w(f"\n  KERNEL CANDIDATES ({len(promotions)}) — >= {args.threshold} distinct agents deferred:\n")
        for topic, rs in promotions:
            agents = sorted({r.agent for r in rs})
            w(f"    {topic} — {len(agents)} agents: {', '.join(agents)}\n")
            for r in rs:
                w(f"      · {r.agent}: {r.statement}\n")
                if r.assumption:
                    w(f"        assumed meanwhile: {r.assumption}\n")
    if targeted:
        w(f"\n  AN INTERRUPT WOULD TARGET: {', '.join(targeted)}\n")
    if not (attention or promotions or read.malformed):
        w("  nothing needs a decision right now\n")
    w("\n")
    return 0


def run_collect(args: argparse.Namespace) -> int:
    from ctkr.decisions import (
        DECISIONS_FILE,
        collect_brief_adaptation_decisions,
        collect_cm_decisions,
        collect_paradigm_divergence_decisions,
        merge_registry,
        read_registry,
        write_registry,
    )
    from ctkr.intent_cm import INTENT_CM_ADJUDICATED_FILE, TargetProfile, read_adjudicated_jsonl

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    if not ctkr_dir.is_dir():
        sys.stderr.write(f"ERROR: {ctkr_dir} does not exist — run the pipeline first.\n")
        return 2

    profile = None
    if args.target_profile:
        profile = TargetProfile.load(args.target_profile)

    adjudicated = read_adjudicated_jsonl(ctkr_dir / INTENT_CM_ADJUDICATED_FILE)
    cards = [] if args.no_brief_adaptation else _load_cards(ctkr_dir)
    reports = _load_port_verify_reports(Path(data_dir), ctkr_dir, args.port_verify_dir)

    graph = _load_graph_opt(Path(data_dir))
    members_df = _load_members_opt(ctkr_dir)

    fresh = []
    fresh += collect_cm_decisions(
        adjudicated, profile, graph=graph, members_df=members_df, generated_at=args.generated_at
    )
    fresh += collect_brief_adaptation_decisions(
        cards, graph=graph, members_df=members_df, generated_at=args.generated_at
    )
    fresh += collect_paradigm_divergence_decisions(
        reports, members_df=members_df, generated_at=args.generated_at
    )

    registry_path = ctkr_dir / DECISIONS_FILE
    existing = read_registry(registry_path)
    merged = merge_registry(fresh, existing)
    write_registry(merged, registry_path)

    by_source: dict[str, int] = {}
    for d in merged:
        by_source[d.source] = by_source.get(d.source, 0) + 1
    n_pending = sum(1 for d in merged if d.status == "pending")

    sys.stderr.write(
        "\n"
        f"  decisions surfaced : {len(merged)} ({n_pending} pending)\n"
        f"  by source          : {by_source}\n"
        f"  registry           : {registry_path}\n"
    )
    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "n_decisions": len(merged),
                    "n_pending": n_pending,
                    "by_source": by_source,
                    "registry": str(registry_path),
                    "data_dir": str(Path(data_dir).resolve()),
                },
                indent=2,
            )
            + "\n"
        )
    return 0


# ───────────────────────── list ─────────────────────────


def run_list(args: argparse.Namespace) -> int:
    from ctkr.decisions import DECISIONS_FILE, read_registry, render_menu

    data_dir = resolve_data_dir(args.data_dir)
    registry_path = Path(data_dir) / "ctkr" / DECISIONS_FILE
    decisions = read_registry(registry_path)
    if args.status:
        decisions = [d for d in decisions if d.status == args.status]

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps([json.loads(d.model_dump_json()) for d in decisions], indent=2) + "\n"
        )
        return 0

    if not registry_path.exists():
        sys.stderr.write(
            f"No registry at {registry_path}. Run `ctkr decisions` (collect) first.\n"
        )
    sys.stdout.write(render_menu(decisions))
    return 0


# ───────────────────────── resolve ─────────────────────────


def _find_decision(decisions, decision_id: str):
    for d in decisions:
        if d.id == decision_id:
            return d
    # Allow a short suffix match for convenience.
    matches = [d for d in decisions if d.id.endswith(decision_id)]
    return matches[0] if len(matches) == 1 else None


def _strong_model(provider: str, model_arg: str | None) -> str:
    if model_arg:
        return model_arg
    return GPT56_STRONG_MODEL if provider == "openai" else _ANTHROPIC_STRONG_MODEL


def run_resolve(args: argparse.Namespace) -> int:  # noqa: C901 — mode dispatch
    from ctkr.decisions import (
        DECISIONS_FILE,
        append_pd_record,
        apply_resolution,
        decide_for_me,
        elicit_decision,
        read_registry,
        render_interview_doc,
        write_registry,
    )

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    registry_path = ctkr_dir / DECISIONS_FILE
    decisions = read_registry(registry_path)
    if not decisions:
        sys.stderr.write(f"No registry at {registry_path}. Run `ctkr decisions` first.\n")
        return 2

    d = _find_decision(decisions, args.decision_id)
    if d is None:
        sys.stderr.write(f"decision {args.decision_id!r} not found (or ambiguous).\n")
        return 2

    author = args.author or "ctkr decisions (agent)"
    provider = args.provider or DEFAULT_LLM_PROVIDER

    def _persist(updated) -> None:
        for i, cur in enumerate(decisions):
            if cur.id == updated.id:
                decisions[i] = updated
                break
        write_registry(decisions, registry_path)

    # ---- interview / recommend / decide-for-me need an LLM ----
    needs_llm = args.interview or args.recommend or args.decide_for_me
    client = None
    model = _strong_model(provider, args.model)
    if needs_llm:
        rc = require_provider_key(
            provider, stage="decisions resolve", default_hint=f"OpenAI {model}"
        )
        if rc is not None:
            return rc
        from ctkr.llm import LLMClient

        client = LLMClient(
            cache_dir=ctkr_dir / "llm_cache",
            cost_log=ctkr_dir / "llm_cost.jsonl",
            default_provider=provider,
        )

    # ---- --interview ----
    if args.interview:
        try:
            res = elicit_decision(d, client, model=model, provider=provider)
        except Exception as e:  # noqa: BLE001 — provider/validation errors vary
            sys.stderr.write(f"ERROR: elicitation LLM call failed: {e}\n")
            return 1
        doc = render_interview_doc(d, res.parsed)
        updated = apply_resolution(
            d, mode="interview", recommendation=res.parsed.recommendation,
            author=author, llm_model=res.model, llm_cost_usd=res.cost_estimate_usd,
        )
        _persist(updated)
        _emit_doc(args, doc)
        sys.stderr.write(
            f"\n  interview doc for {d.id} (cost ${res.cost_estimate_usd:.4f}, "
            f"cache_hit={res.cache_hit}); decision stays pending.\n"
        )
        return 0

    # ---- --recommend ----
    if args.recommend:
        try:
            res = elicit_decision(d, client, model=model, provider=provider)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"ERROR: recommendation LLM call failed: {e}\n")
            return 1
        doc = render_interview_doc(d, res.parsed)
        updated = apply_resolution(
            d, mode="recommend", recommendation=res.parsed.recommendation,
            author=author, llm_model=res.model, llm_cost_usd=res.cost_estimate_usd,
        )
        _persist(updated)
        _emit_doc(args, doc)
        sys.stderr.write(
            f"\n  recommendation for {d.id}: {res.parsed.recommendation or '(neutral)'} "
            f"(cost ${res.cost_estimate_usd:.4f}); decision stays pending.\n"
        )
        return 0

    # ---- --decide-for-me ----
    if args.decide_for_me:
        try:
            res = decide_for_me(d, client, model=model, provider=provider)
        except Exception as e:  # noqa: BLE001
            sys.stderr.write(f"ERROR: decide-for-me LLM call failed: {e}\n")
            return 1
        choice = res.parsed.chosen_option
        valid = {o.id for o in d.options}
        if choice not in valid:
            sys.stderr.write(
                f"ERROR: model picked {choice!r} which is not in the menu {sorted(valid)}.\n"
            )
            return 1
        record, ledger = append_pd_record(
            data_dir, decision=d, chosen_option=choice,
            rationale=res.parsed.rationale, author=author, reversible=False,
        )
        updated = apply_resolution(
            d, mode="decide-for-me", chosen_option=choice, rationale=res.parsed.rationale,
            author=author, pd_record_id=record["id"], pd_ledger_path=str(ledger),
            llm_model=res.model, llm_cost_usd=res.cost_estimate_usd,
        )
        _persist(updated)
        _emit_resolution(args, updated, record, ledger)
        return 0

    # ---- --decide <option> (developer's answer) ----
    if args.decide is not None:
        valid = {o.id for o in d.options}
        if args.decide not in valid:
            sys.stderr.write(
                f"ERROR: {args.decide!r} is not in the menu {sorted(valid)}.\n"
            )
            return 2
        record, ledger = append_pd_record(
            data_dir, decision=d, chosen_option=args.decide,
            rationale=args.rationale or "(developer decision)", author=args.author or "developer",
            reversible=False,
        )
        updated = apply_resolution(
            d, mode="decide", chosen_option=args.decide,
            rationale=args.rationale or "(developer decision)", author=args.author or "developer",
            pd_record_id=record["id"], pd_ledger_path=str(ledger),
        )
        _persist(updated)
        _emit_resolution(args, updated, record, ledger)
        return 0

    # ---- --roll-forward ----
    if args.roll_forward:
        rationale = args.rationale or "Explicitly rolled forward; revisit before/during build."
        # No option is chosen on a roll-forward; the record lands as preserve-with-note
        # (the source intention is kept, pending an explicit revisit) and is flagged
        # reversible so verifyPort reads it as debt, not a settled constraint.
        record, ledger = append_pd_record(
            data_dir, decision=d, chosen_option="",
            rationale="ROLL-FORWARD (reversible): " + rationale,
            author=args.author or author, reversible=True,
        )
        updated = apply_resolution(
            d, mode="roll-forward", chosen_option=None, rationale=rationale,
            author=args.author or author, reversible=True,
            pd_record_id=record["id"], pd_ledger_path=str(ledger),
        )
        _persist(updated)
        _emit_resolution(args, updated, record, ledger)
        return 0

    sys.stderr.write("no mode selected.\n")
    return 2


def _emit_doc(args: argparse.Namespace, doc: str) -> None:
    if args.out:
        Path(args.out).expanduser().write_text(doc, encoding="utf-8")
        sys.stderr.write(f"  wrote {args.out}\n")
    else:
        sys.stdout.write(doc)


def _emit_resolution(args: argparse.Namespace, updated, record: dict, ledger) -> None:
    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "decision": json.loads(updated.model_dump_json()),
                    "pd_record": record,
                    "ledger": str(ledger),
                },
                indent=2,
            )
            + "\n"
        )
        return
    r = updated.resolution
    sys.stderr.write(
        f"\n  resolved {updated.id} → {updated.status}"
        + (f" (chose {r.chosen_option})" if r and r.chosen_option else "")
        + f"\n  Port Decision {record['id']} appended → {ledger}\n"
    )
