"""``ctkr propose-adapter`` — propose a port adapter CONTRACT for a scoped feature.

Second-opinion T1 (bead MetaCoding-9h5.15): can the pipeline PROPOSE the hand-authored
adapter signature surface every prior port experiment presupposed? Given a scoped
feature's pipeline artifacts (subsystem members/roles from the graph + mined fixture
candidates + target profile) and the scoped source, synthesize a typed mutator +
projection contract with a strong model (default gpt-5.6-terra), structured + repair.

Emits ``adapter_contract.json`` (the structured contract) and ``adapter_contract.md``
(an ADAPTER_SIGNATURES-style doc a blind builder can port against).

Blindness: this command reads pipeline artifacts + the scoped source only. Do NOT point
``--glossary`` (or any input) at a reference signature surface, a fixtures pack, or a
prior builder's output — that would defeat the experiment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import (
    DEFAULT_LLM_PROVIDER,
    GPT56_STRONG_MODEL,
    require_provider_key,
    resolve_data_dir,
)


def discover_cm_registry(start: Path | None = None) -> Path | None:
    """The repo's bound CM-decision registry, discovered from ``start`` upward.

    Mirrors :data:`ctkr.oracle.port_contract.DEFAULT_DECISION_SOURCES` — the
    same fixed, repo-rooted registry ``port-verify`` resolves sanctions from —
    so the surface generator and the reader consult ONE set of bound decisions.
    Walks parents until a match or a ``.git`` root; returns ``None`` if the
    tree has no registry (the caller must then warn, never proceed silently).
    """
    from ctkr.oracle.port_contract import DEFAULT_DECISION_SOURCES

    cur = (start or Path.cwd()).resolve()
    for parent in (cur, *cur.parents):
        for rel in DEFAULT_DECISION_SOURCES:
            cand = parent / rel
            if cand.exists():
                return cand
        if (parent / ".git").exists():
            break
    return None


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "propose-adapter",
        help="Propose a typed port adapter contract (mutators + projections) for a feature.",
        description=(
            "Signature-generation pass (MetaCoding-9h5.15): synthesize the adapter "
            "signature surface a port needs — mutators (log events) + projections (as-of "
            "reads) — from pipeline artifacts (graph subsystem members + mined fixture "
            "candidates) + the target profile, using a strong model. Structured output, "
            "one repair retry. Emits adapter_contract.{json,md}."
        ),
    )
    p.add_argument("--data-dir", default=None, help="Path to .metacoding/ (graph export).")
    p.add_argument(
        "--subsystem", action="append", default=None, metavar="PATH_SUBSTR", required=True,
        help="Graph scope: a file-path substring selecting the feature's members "
        "(repeatable). E.g. --subsystem /location/.",
    )
    p.add_argument("--feature-name", required=True, help="Human name of the feature to port.")
    p.add_argument(
        "--fixture-candidates", default=None,
        help="Path to a mine-fixtures fixture_candidates.jsonl (the mined non-obvious "
        "semantics). Default <data-dir>/ctkr/fixture_candidates.jsonl if present.",
    )
    p.add_argument(
        "--target-profile", required=True,
        help="Path to the target profile (YAML/markdown) describing the local-first target.",
    )
    p.add_argument(
        "--glossary", default=None,
        help="Optional glossary / intent text file (domain framing). Must NOT contain a "
        "reference adapter surface.",
    )
    p.add_argument(
        "--cm-decisions", default=None,
        help="Path to the kernel's bound CM-decision registry (cm-decisions.jsonl, "
        "src/kernel/decisions.ts format). Bound/provisional decisions are injected into "
        "the synthesis prompt as FIXED constraints and enforced by a post-generation "
        "conformance check that fails loudly if the surface re-derives a conflicting "
        "convergence mechanic (F2 / MetaCoding-9h5.27). When omitted, the repo's own "
        "bound registry is discovered and used; generating with zero constraints "
        "warns loudly (MetaCoding-sag).",
    )
    p.add_argument("--target-language", default="TypeScript")
    p.add_argument("--out-json", default=None, help="Output contract JSON path.")
    p.add_argument("--out-md", default=None, help="Output contract markdown path.")
    p.add_argument("--provider", default=None, help="LLM provider (default openai).")
    p.add_argument("--model", default=None, help="Synthesis model (default gpt-5.6-terra).")
    p.add_argument("--reasoning-effort", default=None, help="GPT-5.x reasoning effort.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Emit summary as JSON.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.graph_loader import load_graph
    from ctkr.llm import LLMClient, scratch_dir
    from ctkr.propose_adapter import (
        build_contract_prompt,
        check_cm_conformance,
        extract_subsystem_members,
        load_cm_decisions,
        load_fixture_candidates,
        render_contract_markdown,
        synthesize_contract,
    )

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    ctkr_dir.mkdir(parents=True, exist_ok=True)

    target_profile_path = Path(args.target_profile).expanduser().resolve()
    if not target_profile_path.exists():
        sys.stderr.write(f"ERROR: --target-profile {target_profile_path} does not exist.\n")
        return 2
    target_profile_text = target_profile_path.read_text(encoding="utf-8")

    glossary_text = ""
    if args.glossary:
        gp = Path(args.glossary).expanduser().resolve()
        if not gp.exists():
            sys.stderr.write(f"ERROR: --glossary {gp} does not exist.\n")
            return 2
        glossary_text = gp.read_text(encoding="utf-8")

    # Bound CM-decision registry (F2 / MetaCoding-9h5.27): fixed constraints the surface
    # must conform to. Injected verbatim into the prompt AND enforced post-generation.
    # The coupling used to be opt-in: a runner that forgot the flag silently
    # regenerated the exact contradiction 9h5.27 fixed (MetaCoding-sag). Omitting
    # the flag now discovers the repo's own bound registry, and generating with
    # ZERO constraints is loud, never silent.
    cm_constraints = []
    cm_arg = args.cm_decisions or discover_cm_registry()
    if args.cm_decisions is None and cm_arg is not None:
        sys.stderr.write(
            f"--cm-decisions not given; using the repo's bound registry {cm_arg}\n"
        )
    if cm_arg:
        cmp = Path(cm_arg).expanduser().resolve()
        if not cmp.exists():
            sys.stderr.write(f"ERROR: --cm-decisions {cmp} does not exist.\n")
            return 2
        cm_constraints = load_cm_decisions(cmp)
        n_binding = sum(1 for c in cm_constraints if c.is_binding)
        sys.stderr.write(
            f"loaded {len(cm_constraints)} CM decision(s) ({n_binding} binding) from {cmp}\n"
        )
    else:
        sys.stderr.write(
            "WARNING: generating with ZERO bound CM constraints — no --cm-decisions "
            "given and no repo registry discovered. A surface generated blind can "
            "contradict frozen kernel decisions (MetaCoding-sag / 9h5.27).\n"
        )

    # Fixture candidates (mine-fixtures output) — the mined non-obvious semantics.
    fc_path = (
        Path(args.fixture_candidates)
        if args.fixture_candidates
        else ctkr_dir / "fixture_candidates.jsonl"
    )
    fixture_candidates: list[dict] = []
    if fc_path.exists():
        fixture_candidates = load_fixture_candidates(fc_path)
        sys.stderr.write(f"loaded {len(fixture_candidates)} fixture candidate(s) from {fc_path}\n")
    else:
        sys.stderr.write(
            f"WARNING: no fixture_candidates at {fc_path}; proposing from members only.\n"
        )

    # Subsystem members / roles (deterministic, from the graph).
    sys.stderr.write(f"loading graph from {data_dir} …\n")
    g = load_graph(data_dir)
    members = extract_subsystem_members(g, scope_prefixes=args.subsystem)
    sys.stderr.write(
        f"extracted {len(members)} subsystem member(s) over scope {args.subsystem}\n"
    )
    if not members:
        sys.stderr.write("ERROR: no members in scope; check --subsystem prefixes.\n")
        return 2

    prompt = build_contract_prompt(
        feature_name=args.feature_name,
        members=members,
        fixture_candidates=fixture_candidates,
        target_profile_text=target_profile_text,
        glossary_text=glossary_text,
        cm_constraints=cm_constraints,
        target_language=args.target_language,
    )

    provider = args.provider or DEFAULT_LLM_PROVIDER
    model = args.model or GPT56_STRONG_MODEL
    rc = require_provider_key(provider, stage="propose-adapter synthesis",
                              default_hint=f"OpenAI {model}")
    if rc is not None:
        return rc

    client = LLMClient(
        cache_dir=scratch_dir("propose-adapter") / "llm_cache",
        cost_log=scratch_dir("propose-adapter") / "llm_cost.jsonl",
        default_provider=provider,
    )
    sys.stderr.write(f"synthesizing adapter contract with {model} …\n")
    contract, cost = synthesize_contract(
        prompt, client, model=model, provider=provider,
        reasoning_effort=args.reasoning_effort,
    )

    out_json = Path(args.out_json) if args.out_json else ctkr_dir / "adapter_contract.json"
    out_md = Path(args.out_md) if args.out_md else ctkr_dir / "adapter_contract.md"
    out_json.write_text(json.dumps(contract.model_dump(), indent=2) + "\n", encoding="utf-8")
    out_md.write_text(
        render_contract_markdown(contract, feature_name=args.feature_name), encoding="utf-8"
    )

    n_mut, n_proj = len(contract.mutators), len(contract.projections)
    n_inv = sum(
        1 for m in [*contract.mutators, *contract.projections]
        if m.derived_from.strip().lower().startswith("invented")
    )
    sys.stderr.write(
        f"\n  contract written : {out_json}\n"
        f"                     {out_md}\n"
        f"  mutators         : {n_mut}\n"
        f"  projections      : {n_proj}\n"
        f"  invented methods : {n_inv}\n"
        f"  synthesis spend  : ${cost:.4f}\n"
    )

    if args.as_json:
        sys.stdout.write(json.dumps({
            "out_json": str(out_json), "out_md": str(out_md),
            "adapter_name": contract.adapter_name,
            "mutators": n_mut, "projections": n_proj, "invented": n_inv,
            "cost_usd": round(cost, 6),
        }, indent=2) + "\n")
    else:
        sys.stdout.write(f"\n{contract.adapter_name}  ({n_mut} mutators, {n_proj} projections)\n")
        for m in [*contract.mutators, *contract.projections]:
            aot = " @t" if m.as_of_time else ""
            sys.stdout.write(f"  [{m.kind[:4]}] {m.name}{aot}  <- {m.derived_from[:50]}\n")

    # Post-generation CM-conformance gate (F2 / MetaCoding-9h5.27). Deterministic: the
    # surface must not re-derive a convergence mechanic that conflicts with a bound
    # decision. Fail loudly (nonzero exit) — never a silent warning. The artifacts above
    # are written first so the conflicting surface is inspectable.
    conflicts = check_cm_conformance(contract, cm_constraints)
    if conflicts:
        sys.stderr.write(
            f"\nCM-CONFORMANCE FAILED: {len(conflicts)} bound-decision conflict(s) in the "
            "generated surface.\n\n"
        )
        for cf in conflicts:
            sys.stderr.write(cf.render() + "\n\n")
        return 3

    return 0
