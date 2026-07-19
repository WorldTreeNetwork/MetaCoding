"""``ctkr feature-kinds`` — build the feature × event-kind dependency graph (9h5.21).

Given per-feature build sources (a shared store + each feature's adapter view) and/or
prose contracts, extract the bipartite graph **features ↔ event kinds** (edges labelled
emit/fold + a status-gated flag), then report the two analyses the shared-kernel
prescription needs:

* **KERNEL SURFACE** — event kinds touched by ≥2 features (degree ≥2). Mechanically
  identified; these must be frozen centrally before the fan-out's wave 1.
* **WAVE SCHEDULING** — connected components of features sharing kinds. Features in one
  component serialize through one builder; distinct components parallelize. Re-run with
  the kernel frozen (``--freeze-kernel``) to see the domain clusters underneath.

Deterministic where a build source exists (name-blind TypeScript parse, LM-free). A
terra-structured fallback (``--prose NAME=path``) extracts a profile from a prose
contract (repair retry, cites the contract line). ``--project`` adds the farmOS
module-family kind GUESSES (labelled ``projected`` — never mixed with extracted edges).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "feature-kinds",
        help="Build the target-side feature × event-kind graph (kernel + wave analyses).",
        description=(
            "Extract, per feature, the event kinds its mutators EMIT and its projections "
            "FOLD (status-gated flag), assemble the bipartite feature↔kind graph, and "
            "report the KERNEL SURFACE (kinds with cross-feature degree ≥2) and WAVE "
            "SCHEDULE (feature clusters sharing kinds). Deterministic from build sources; "
            "terra fallback for prose contracts. LM-free unless --prose is used."
        ),
    )
    p.add_argument(
        "--store",
        default=None,
        help="Path to the shared store implementation (store.ts) for build-source extraction.",
    )
    p.add_argument(
        "--feature",
        action="append",
        default=[],
        metavar="NAME=ADAPTER_TS",
        help="A feature to extract deterministically: NAME=path/to/<feature>Adapter.ts "
        "(repeatable). Requires --store.",
    )
    p.add_argument(
        "--prose",
        action="append",
        default=[],
        metavar="NAME=CONTRACT_MD",
        help="A feature whose profile is extracted from a PROSE contract via terra "
        "(repeatable). NAME=path/to/contract.md.",
    )
    p.add_argument(
        "--project",
        action="store_true",
        help="Add the farmOS module-family kind GUESSES (projected profiles) to the graph "
        "to forecast the fan-out wave structure. Projected edges are labelled, never "
        "counted as extracted.",
    )
    p.add_argument(
        "--freeze-kernel",
        action="store_true",
        help="Also report the wave schedule with the kernel kinds frozen (decoupled), "
        "revealing the domain clusters that parallelize once the kernel ships.",
    )
    p.add_argument("--threshold", type=int, default=2, help="Kernel degree threshold (default 2).")
    p.add_argument("--out-json", default=None, help="Write the full graph + analyses as JSON.")
    p.add_argument("--out-mermaid", default=None, help="Write the bipartite mermaid diagram.")
    p.add_argument("--json", dest="as_json", action="store_true", help="Emit the summary as JSON.")
    # Prose-fallback LLM knobs (only used when --prose is given).
    p.add_argument("--provider", default=None, help="LLM provider for --prose (default openai).")
    p.add_argument("--model", default=None, help="Model for --prose (default gpt-5.6-terra).")
    p.set_defaults(func=run)


def _split_kv(spec: str) -> tuple[str, str]:
    if "=" not in spec:
        raise ValueError(f"expected NAME=PATH, got {spec!r}")
    name, path = spec.split("=", 1)
    return name.strip(), path.strip()


def run(args: argparse.Namespace) -> int:
    from ctkr.feature_kinds import (
        build_graph,
        extract_from_build,
        kernel_surface,
        projected_profiles,
        render_mermaid,
        taxonomy_tensions,
        wave_schedule,
    )

    profiles = []

    # 1. Deterministic build-source extraction.
    if args.feature:
        if not args.store:
            sys.stderr.write("ERROR: --feature requires --store.\n")
            return 2
        store_path = Path(args.store).expanduser()
        if not store_path.exists():
            sys.stderr.write(f"ERROR: --store {store_path} does not exist.\n")
            return 2
        store_ts = store_path.read_text(encoding="utf-8")
        for spec in args.feature:
            name, apath = _split_kv(spec)
            ap = Path(apath).expanduser()
            if not ap.exists():
                sys.stderr.write(f"ERROR: adapter source {ap} does not exist.\n")
                return 2
            profiles.append(
                extract_from_build(
                    feature=name, store_ts=store_ts, adapter_ts=ap.read_text(encoding="utf-8")
                )
            )
            sys.stderr.write(f"extracted (deterministic) feature {name!r} from {ap}\n")

    # 2. Prose fallback (terra-structured).
    if args.prose:
        from ctkr.commands._common import (
            DEFAULT_LLM_PROVIDER,
            GPT56_STRONG_MODEL,
            require_provider_key,
        )
        from ctkr.feature_kinds import extract_from_prose
        from ctkr.llm import LLMClient

        provider = args.provider or DEFAULT_LLM_PROVIDER
        model = args.model or GPT56_STRONG_MODEL
        rc = require_provider_key(provider, stage="feature-kinds --prose", default_hint=model)
        if rc is not None:
            return rc
        client = LLMClient(default_provider=provider, structured_repair=True)
        for spec in args.prose:
            name, cpath = _split_kv(spec)
            cp = Path(cpath).expanduser()
            if not cp.exists():
                sys.stderr.write(f"ERROR: prose contract {cp} does not exist.\n")
                return 2
            prof, cost = extract_from_prose(
                feature=name,
                contract_text=cp.read_text(encoding="utf-8"),
                client=client,
                model=model,
                provider=provider,
            )
            profiles.append(prof)
            sys.stderr.write(f"extracted (terra ${cost:.4f}) feature {name!r} from {cp}\n")

    # 3. Projected farmOS families.
    if args.project:
        profiles.extend(projected_profiles())
        sys.stderr.write("added projected farmOS module-family profiles (kind guesses)\n")

    if not profiles:
        sys.stderr.write("ERROR: no features to graph. Pass --feature, --prose, or --project.\n")
        return 2

    graph = build_graph(profiles)
    kinds = kernel_surface(graph, threshold=args.threshold)
    kernel_kinds = frozenset(k.kind for k in kinds if k.is_kernel)
    tensions = taxonomy_tensions(graph, profiles)
    waves = wave_schedule(graph)
    frozen_waves = wave_schedule(graph, freeze_kinds=kernel_kinds) if args.freeze_kernel else None

    if args.out_mermaid:
        Path(args.out_mermaid).expanduser().write_text(
            render_mermaid(graph, kernel_threshold=args.threshold), encoding="utf-8"
        )
        sys.stderr.write(f"wrote mermaid diagram → {args.out_mermaid}\n")

    payload = {
        "features": graph.features,
        "kinds": graph.kinds,
        "edges": [
            {
                "feature": e.feature,
                "kind": e.kind,
                "role": e.role,
                "status_gated": e.status_gated,
                "provenance": e.provenance,
                "via": list(e.via),
            }
            for e in graph.edges
        ],
        "kernel_surface": [
            {
                "kind": k.kind,
                "degree": k.degree,
                "is_kernel": k.is_kernel,
                "emit_features": list(k.emit_features),
                "fold_features": list(k.fold_features),
                "status_gated_features": list(k.status_gated_features),
            }
            for k in kinds
        ],
        "taxonomy_tensions": [
            {
                "kind_a": t.kind_a,
                "kind_b": t.kind_b,
                "feature_a": t.feature_a,
                "feature_b": t.feature_b,
                "kind_filtered_by": list(t.kind_filtered_by),
            }
            for t in tensions
        ],
        "waves": [
            {"features": list(c.features), "shared_kinds": list(c.shared_kinds)} for c in waves
        ],
    }
    if frozen_waves is not None:
        payload["waves_kernel_frozen"] = [
            {"features": list(c.features), "shared_kinds": list(c.shared_kinds)}
            for c in frozen_waves
        ]

    if args.out_json:
        Path(args.out_json).expanduser().write_text(
            json.dumps(payload, indent=2), encoding="utf-8"
        )
        sys.stderr.write(f"wrote graph JSON → {args.out_json}\n")

    if args.as_json:
        sys.stdout.write(json.dumps(payload) + "\n")
        return 0

    # Human summary.
    print(f"\n  features           : {len(graph.features)}  ({', '.join(graph.features)})")
    print(f"  event kinds        : {len(graph.kinds)}")
    print(f"  edges              : {len(graph.edges)}")
    print(f"\n  KERNEL SURFACE (degree ≥ {args.threshold}):")
    print(f"    {'kind':<22}{'deg':>4}  emit / fold features  (status-gated)")
    for k in kinds:
        mark = "★" if k.is_kernel else " "
        gated = (
            f"  gated:{','.join(f[:10] for f in k.status_gated_features)}"
            if k.status_gated_features
            else ""
        )
        print(
            f"  {mark} {k.kind:<22}{k.degree:>4}  emit={list(k.emit_features)} "
            f"fold={list(k.fold_features)}{gated}"
        )
    if tensions:
        print("\n  TAXONOMY TENSIONS (latent — distinct emit-kinds a fan-out might merge):")
        for t in tensions:
            print(
                f"    {t.kind_a} ({t.feature_a}) vs {t.kind_b} ({t.feature_b}) "
                f"— kind-filtered by {list(t.kind_filtered_by)}"
            )
    print("\n  WAVE SCHEDULE (features sharing ≥1 kind serialize):")
    for i, c in enumerate(waves, 1):
        verb = "SERIALIZE" if c.serializes else "parallel-ok"
        print(
            f"    cluster {i} [{verb}] size={c.size}: {list(c.features)} "
            f"shared={list(c.shared_kinds)}"
        )
    if frozen_waves is not None:
        print(f"\n  WAVE SCHEDULE — kernel frozen ({sorted(kernel_kinds)} decoupled):")
        for i, c in enumerate(frozen_waves, 1):
            verb = "SERIALIZE" if c.serializes else "parallel-ok"
            print(
                f"    cluster {i} [{verb}] size={c.size}: {list(c.features)} "
                f"shared={list(c.shared_kinds)}"
            )
    return 0
