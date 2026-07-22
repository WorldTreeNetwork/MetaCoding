"""``ctkr term-incidence`` — feature × glossary-term incidence graph (MetaCoding-01k).

The feature-kinds analogue for the oracle vocabulary: read the sealed packs
under one or more port-run roots, graph **features ↔ glossary terms** (assertion
terms exercised in ``then``, action terms used in ``when``), and classify every
term by cross-feature degree:

* **SPINE** — degree ≥ 80% of features (the shared backbone of the lexicon);
* **SHARED** — degree ≥ 2 below the spine threshold;
* **IDENTITY** — degree 1: the vocabulary only one feature needed.

With ``--role-classes`` (the role sweep's output, MetaCoding-034) it also
computes per-feature IDENTITY COVERAGE: distinguishing domain role classes
nameable by any exercised term / all such classes. Without the file the metric
degrades gracefully to ``n/a`` — incidence and degrees stand alone.

Deterministic and LM-free; reads packs only (never a source system).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Default port-run roots, resolved relative to the repo checkout that contains
# this package (<repo>/ctkr/ctkr/commands/term_incidence.py -> <repo>).
_REPO_ROOT = Path(__file__).resolve().parents[3]
DEFAULT_ROOTS = (
    _REPO_ROOT / "eval" / "ctkr" / "port_runs" / "wave1",
    _REPO_ROOT / "eval" / "ctkr" / "port_runs" / "wave0-pilot",
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "term-incidence",
        help="Build the feature × glossary-term incidence graph from sealed packs.",
        description=(
            "Read fixtures.jsonl (+ adapter_contract.json when present) under one or "
            "more port-run roots, assemble the bipartite feature↔term graph (assertion "
            "terms from 'then', action terms from 'when'), classify terms by degree "
            "(SPINE / SHARED / IDENTITY), and — given --role-classes — compute per-"
            "feature identity coverage. Deterministic, LM-free, pack-reading only."
        ),
    )
    p.add_argument(
        "roots",
        nargs="*",
        default=None,
        help="Port-run roots to scan for fixtures.jsonl (default: "
        "eval/ctkr/port_runs/wave1 + wave0-pilot of this checkout).",
    )
    p.add_argument(
        "--role-classes",
        default=None,
        help="role-classes.jsonl from the role sweep; enables the identity-coverage "
        "metric. Omit to degrade gracefully (coverage reported as n/a).",
    )
    p.add_argument(
        "--spine-threshold",
        type=float,
        default=0.8,
        help="Degree fraction at/above which a term is SPINE (default 0.8).",
    )
    p.add_argument(
        "--out",
        default=None,
        help="Write the edge list as term-incidence JSONL "
        "({feature, term, role, count} per line).",
    )
    p.add_argument(
        "--out-summary",
        default=None,
        help="Write the machine-readable summary JSON to a file.",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit the machine-readable summary JSON on stdout.",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.term_incidence import (
        build_incidence,
        classify_terms,
        edges_jsonl,
        identity_coverage,
        load_role_classes,
        summary_payload,
    )

    roots = [Path(r).expanduser() for r in args.roots] if args.roots else list(DEFAULT_ROOTS)
    missing = [r for r in roots if not r.exists()]
    if missing:
        for r in missing:
            sys.stderr.write(f"ERROR: root {r} does not exist.\n")
        return 2

    graph = build_incidence(roots)
    if not graph.features:
        sys.stderr.write(f"ERROR: no fixtures.jsonl found under {[str(r) for r in roots]}.\n")
        return 2

    degrees = classify_terms(graph, spine_threshold=args.spine_threshold)

    coverage = None
    if args.role_classes:
        rc_path = Path(args.role_classes).expanduser()
        if not rc_path.exists():
            sys.stderr.write(f"ERROR: --role-classes {rc_path} does not exist.\n")
            return 2
        coverage = identity_coverage(graph, load_role_classes(rc_path))

    if args.out:
        out = Path(args.out).expanduser()
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(edges_jsonl(graph), encoding="utf-8")
        sys.stderr.write(f"wrote {len(graph.edges)} edges → {out}\n")

    payload = summary_payload(
        graph, degrees, coverage, args.spine_threshold, relative_to=_REPO_ROOT
    )

    if args.out_summary:
        outs = Path(args.out_summary).expanduser()
        outs.parent.mkdir(parents=True, exist_ok=True)
        outs.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
        sys.stderr.write(f"wrote summary JSON → {outs}\n")

    if args.as_json:
        sys.stdout.write(json.dumps(payload) + "\n")
        return 0

    # Human summary.
    split = payload["classification_split"]
    print(f"\n  features     : {len(graph.features)}  ({', '.join(graph.features)})")
    print(f"  terms        : {len(degrees)}")
    print(f"  edges        : {len(graph.edges)}")
    print(
        f"  packs        : {len(graph.packs)} "
        f"({sum(1 for p in graph.packs if p.sealed)} sealed)"
    )
    print(
        f"\n  DEGREE SPLIT (spine ≥ {args.spine_threshold:.0%} of "
        f"{len(graph.features)} features): "
        f"SPINE={split['SPINE']}  SHARED={split['SHARED']}  IDENTITY={split['IDENTITY']}"
    )
    print(f"\n    {'term':<28}{'deg':>4}  class     roles      features")
    for d in degrees:
        mark = {"SPINE": "★", "IDENTITY": "◇", "SHARED": " "}[d.classification]
        print(
            f"  {mark} {d.term:<28}{d.degree:>4}  {d.classification:<9} "
            f"{'/'.join(d.roles):<10} {', '.join(d.features)}"
        )
    print("\n  PER FEATURE:")
    for feature in graph.features:
        pf = payload["per_feature"][feature]
        ident = pf["identity_terms"]
        cov = pf["identity_coverage"]
        if isinstance(cov, str):
            cov_str = cov
        elif cov["coverage"] is None:
            cov_str = "n/a (feature touches no distinguishing domain classes)"
        else:
            n_reach = len(cov["reachable_classes"])
            n_all = n_reach + len(cov["unreachable_classes"])
            cov_str = f"{cov['coverage']:.0%} ({n_reach}/{n_all} classes nameable)"
            if cov["unreachable_classes"]:
                cov_str += f"  gaps: {', '.join(cov['unreachable_classes'])}"
        print(
            f"    {feature:<18} fixtures={pf['n_fixtures']:<3} "
            f"assertion-terms={pf['n_assertion_terms']:<2} "
            f"action-terms={pf['n_action_terms']:<2} "
            f"identity={ident if ident else '—'}"
        )
        print(f"    {'':<18} identity-coverage: {cov_str}")
    return 0
