"""``ctkr mine-fixtures`` — the semantic-mining pass (bead MetaCoding-9h5.10).

Given a data-dir (code graph) + a scoped subsystem source root, proposes ranked
fixture CANDIDATES: the non-obvious semantics a port must get right that method
names cannot telegraph. Three lanes, fused (see :mod:`ctkr.mine_fixtures`):

* **CM lane** — intent-CM seed + gpt-5.6-luna adjudication over ``--source-root``
  (prescreen OFF, the adopted default);
* **graph lane** (LM-free) — scoped graph structures ranked by reach;
* **source-read lane** — gpt-5.6-terra reads each module's source for behavioral
  rules a re-implementer could get wrong (structured, ``repair=`` retry).

Emits ``fixture_candidates.jsonl``. No candidate is a fixture until it is OBSERVED
against the live oracle (a separate step) — this pass only proposes.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import (
    DEFAULT_LLM_PROVIDER,
    GPT56_CHEAP_MODEL,
    GPT56_STRONG_MODEL,
    require_provider_key,
    resolve_data_dir,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "mine-fixtures",
        help="Propose ranked fixture candidates (CM + graph + source-read lanes).",
        description=(
            "Semantic-mining pass (MetaCoding-9h5.10): mine the CM adjudications, the "
            "scoped code graph, and the module source for the non-obvious semantics a "
            "port must get right, and emit a ranked fixture_candidates.jsonl. No "
            "candidate becomes a fixture without live-oracle observation."
        ),
    )
    p.add_argument("--data-dir", default=None, help="Path to .metacoding/ (graph export).")
    p.add_argument(
        "--source-root", required=True,
        help="Scoped subsystem source tree (CM + source-read lanes scan this).",
    )
    p.add_argument(
        "--subsystem", action="append", default=None, metavar="PATH_SUBSTR",
        help="Graph-lane scope: a file-path substring (repeatable). E.g. --subsystem "
        "/log/ --subsystem /quantity/. Default: derived from --source-root leaf names.",
    )
    p.add_argument(
        "--module", action="append", default=None, metavar="NAME=PATH",
        help="Source-read module chunk NAME=PATH (repeatable). Default: auto-discover "
        "leaf modules (dirs with a *.info.yml or src/) under --source-root.",
    )
    p.add_argument("--out", default=None,
                   help="Output JSONL (default <data-dir>/ctkr/fixture_candidates.jsonl).")
    p.add_argument("--provider", default=None, help="LLM provider (default openai).")
    p.add_argument("--cm-model", default=None,
                   help="CM adjudication model (default gpt-5.6-luna).")
    p.add_argument("--source-model", default=None,
                   help="Source-read model (default gpt-5.6-terra).")
    p.add_argument("--skip-cm", action="store_true", help="Skip the CM lane (no LLM).")
    p.add_argument("--skip-source-read", action="store_true",
                   help="Skip the source-read lane (no LLM).")
    p.add_argument("--reuse-adjudicated", default=None,
                   help="Reuse an existing intent_cm_adjudicated.jsonl instead of re-adjudicating.")
    p.add_argument("--max-graph-candidates", type=int, default=40)
    p.add_argument("--min-reach", type=int, default=1)
    p.add_argument("--top", type=int, default=None, help="Print only the top-N ranked candidates.")
    p.add_argument("--budget-cap-usd", type=float, default=3.0,
                   help="Abort before an LLM lane if spend would exceed this.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Emit the summary as JSON.")
    p.set_defaults(func=run)


def _discover_modules(source_root: Path) -> dict[str, str]:
    """Discover source-read module chunks under ``source_root``.

    A module is a directory carrying a Drupal ``*.info.yml`` marker (the real
    module boundary), or — for non-Drupal trees — one with a ``src/`` child.
    Test directories are excluded (they carry no port behavior and would drop a
    real module if treated as a nested child)."""
    modules: dict[str, str] = {}
    for d in sorted(source_root.rglob("*")):
        if not d.is_dir():
            continue
        low = str(d).lower()
        if "/tests" in low or "/test" in low:
            continue
        has_info = any(d.glob("*.info.yml"))
        has_src = (d / "src").is_dir()
        if has_info or has_src:
            rel = d.relative_to(source_root)
            name = str(rel).replace("/", ".")
            modules[name] = str(d)
    # Keep leaves: drop a parent when a nested (non-test) module lives under it.
    leaves = {
        n: p for n, p in modules.items()
        if not any(other != p and other.startswith(p + "/") for other in modules.values())
    }
    return leaves or modules


def run(args: argparse.Namespace) -> int:
    from ctkr.graph_loader import load_graph
    from ctkr.mine_fixtures import fuse_and_rank as _fuse
    from ctkr.mine_fixtures import (
        mine_cm_lane,
        mine_graph_lane,
        mine_source_read_lane,
        read_module_source,
        write_candidates,
    )

    source_root = Path(args.source_root).expanduser().resolve()
    if not source_root.exists():
        sys.stderr.write(f"ERROR: --source-root {source_root} does not exist.\n")
        return 2
    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    ctkr_dir.mkdir(parents=True, exist_ok=True)
    out_path = Path(args.out) if args.out else ctkr_dir / "fixture_candidates.jsonl"

    provider = args.provider or DEFAULT_LLM_PROVIDER

    # ── Graph lane (LM-free) ────────────────────────────────────────────────
    prefixes = args.subsystem
    if not prefixes:
        prefixes = [f"/{p.name}/" for p in source_root.iterdir() if p.is_dir()]
        if not prefixes:
            prefixes = [f"/{source_root.name}/"]
    sys.stderr.write(f"graph lane: loading graph from {data_dir} …\n")
    g = load_graph(data_dir)
    graph_cands = mine_graph_lane(
        g, subsystem_prefixes=prefixes, min_reach=args.min_reach,
        max_candidates=args.max_graph_candidates,
    )
    sys.stderr.write(
        f"  graph lane: {len(graph_cands)} candidate(s) over scope {prefixes}\n"
    )

    total_cost = 0.0

    # ── CM lane ─────────────────────────────────────────────────────────────
    cm_cands = []
    if not args.skip_cm:
        from ctkr.intent_cm import (
            DEFAULT_PROMPT_VERSION,
            adjudicate_cm,
            read_adjudicated_jsonl,
            scan_cm,
        )

        if args.reuse_adjudicated:
            adjudicated = read_adjudicated_jsonl(args.reuse_adjudicated)
            sys.stderr.write(f"  cm lane: reusing {len(adjudicated)} adjudicated row(s)\n")
        else:
            from ctkr.llm import LLMClient

            cm_model = args.cm_model or GPT56_CHEAP_MODEL
            rc = require_provider_key(provider, stage="mine-fixtures CM lane",
                                      default_hint=f"OpenAI {cm_model}")
            if rc is not None:
                return rc
            client = LLMClient(
                cache_dir=ctkr_dir / "llm_cache", cost_log=ctkr_dir / "llm_cost.jsonl",
                default_provider=provider,
            )
            cm_df, _ = scan_cm(source_root, id_prefix="farmos")
            sys.stderr.write(f"  cm lane: {cm_df.height} seed(s); adjudicating with {cm_model} …\n")
            # prescreen OFF (use_heuristic_filter default False)
            adjudicated, adj_stats = adjudicate_cm(
                cm_df, client, model=cm_model, prompt_version=DEFAULT_PROMPT_VERSION,
            )
            total_cost += adj_stats.total_cost_usd
        cm_cands = mine_cm_lane(adjudicated)
        sys.stderr.write(
            f"  cm lane: {len(cm_cands)} hard/soft candidate(s); spend so far ${total_cost:.4f}\n"
        )

    # ── Source-read lane ────────────────────────────────────────────────────
    source_cands = []
    if not args.skip_source_read:
        from ctkr.llm import LLMClient

        source_model = args.source_model or GPT56_STRONG_MODEL
        rc = require_provider_key(provider, stage="mine-fixtures source-read lane",
                                  default_hint=f"OpenAI {source_model}")
        if rc is not None:
            return rc
        if args.module:
            module_paths = {}
            for m in args.module:
                name, _, path = m.partition("=")
                module_paths[name] = path
        else:
            module_paths = _discover_modules(source_root)
        module_sources = {
            name: read_module_source(path) for name, path in module_paths.items()
        }
        module_sources = {k: v for k, v in module_sources.items() if v.strip()}
        if total_cost >= args.budget_cap_usd:
            sys.stderr.write(f"  source-read lane: SKIPPED — spend ${total_cost:.4f} at cap.\n")
        else:
            sys.stderr.write(
                f"  source-read lane: {len(module_sources)} module(s) → {source_model} …\n"
            )
            client = LLMClient(
                cache_dir=ctkr_dir / "llm_cache", cost_log=ctkr_dir / "llm_cost.jsonl",
                default_provider=provider,
            )
            source_cands, src_cost = mine_source_read_lane(
                module_sources, client, model=source_model, provider=provider,
            )
            total_cost += src_cost
            sys.stderr.write(
                f"  source-read lane: {len(source_cands)} candidate(s); "
                f"spend so far ${total_cost:.4f}\n"
            )

    # ── Fuse + rank ─────────────────────────────────────────────────────────
    ranked = _fuse([cm_cands, graph_cands, source_cands])
    n = write_candidates(ranked, out_path)

    sys.stderr.write(
        f"\n  candidates written : {n} → {out_path}\n"
        f"  lanes              : cm={len(cm_cands)} graph={len(graph_cands)} "
        f"source-read={len(source_cands)}\n"
        f"  total LLM spend    : ${total_cost:.4f}\n"
    )

    top = ranked[: args.top] if args.top else ranked
    if args.as_json:
        sys.stdout.write(json.dumps(
            {
                "out": str(out_path), "n_candidates": n,
                "total_cost_usd": round(total_cost, 6),
                "lanes": {"cm": len(cm_cands), "graph": len(graph_cands),
                          "source_read": len(source_cands)},
                "ranked": [c.model_dump() for c in top],
            }, default=str, indent=2) + "\n")
    else:
        sys.stdout.write("\nrank  score  lanes                 topic / title\n")
        sys.stdout.write("----  -----  --------------------  " + "-" * 40 + "\n")
        for i, c in enumerate(top, 1):
            sys.stdout.write(
                f"{i:>4}  {c.rank_score:>5.2f}  {'+'.join(c.lanes):<20}  "
                f"{c.topic} :: {c.title[:60]}\n"
            )
    return 0
