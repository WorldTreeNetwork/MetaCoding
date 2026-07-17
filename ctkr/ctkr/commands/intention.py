"""``ctkr intention`` — mechanical intention harvest (Stage T5a / §9.2).

The LM-free layer of the intention channel. Downstream of the frozen structural
stages, harvests every incidental indicator of intention the source carries
(names, docstrings, error strings, decorators, comments, tests), attaches each
to a structural element, scores where structure alone underdetermines the spec
(§5), and runs the mechanical conflict-detector table (§6.1 stage 1). Writes
``intention_signals.parquet`` + ``intention_load.parquet`` +
``intention_conflicts.parquet`` under ``<data_dir>/ctkr/`` and merges presence +
counts into ``manifest.json``.

Requires Stage A (``ctkr subsystems``) + Stage B (``ctkr interfaces``); role
classes (Stage C ``ctkr roles``) and data shapes are used when present. No LLM —
deterministic, byte-identical re-runs (the T5a acceptance criterion).

See :mod:`ctkr.intention` for the algorithm and
``docs/design/ct-intention-extraction.md`` §9.2 for the design.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import polars as pl

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "intention",
        help="Mechanical intention harvest (Stage T5a) — signals + load + conflicts.",
        description=(
            "Harvest the LM-free intention layer (ct-intention-extraction.md §9.2): "
            "intention_signals.parquet (one row per element/indicator with file:line "
            "provenance), intention_load.parquet (the §5 structural-determinacy D / "
            "intention-richness R scores + load class + drivers), and "
            "intention_conflicts.parquet (mechanical structure-vs-intention conflict "
            "candidates, §6.1). Deterministic — no LLM. Requires `ctkr subsystems` + "
            "`ctkr interfaces`; uses `ctkr roles` + data shapes when present."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--repo-root",
        default=None,
        help="Parent directory containing the indexed repo as a subdirectory "
        "(source slices read from <repo-root>/<repo>/<file>). Default: parent of cwd.",
    )
    p.add_argument(
        "--view",
        default="similarity",
        choices=["orbit", "similarity"],
        help="Role quotient view for A5 naming-pattern harvest (default: similarity).",
    )
    p.add_argument(
        "--exclude-prefix",
        action="append",
        default=None,
        metavar="PREFIX",
        help="Repo-relative path prefix to exclude from the harvest (repeatable). "
        "Default: .claude/ (git-worktree copies pollute a self-index).",
    )
    p.add_argument(
        "--generated-at",
        default=None,
        help="Fixed ISO-8601 timestamp for the manifest (byte-identical re-runs). "
        "Does not affect row content (rows carry no timestamp).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.intention import (
        compute_intention,
        write_intention_conflicts,
        write_intention_load,
        write_intention_signals,
        write_manifest,
    )

    data_dir = resolve_data_dir(args.data_dir)
    ctkr_dir = Path(data_dir) / "ctkr"
    members_path = ctkr_dir / "subsystem_members.parquet"
    interfaces_path = ctkr_dir / "interfaces.parquet"
    if not members_path.exists():
        sys.stderr.write(
            f"ERROR: {members_path} not found — run `ctkr subsystems` first (Stage A).\n"
        )
        return 2
    if not interfaces_path.exists():
        sys.stderr.write(
            f"ERROR: {interfaces_path} not found — run `ctkr interfaces` first (Stage B).\n"
        )
        return 2

    repo_root = (
        Path(args.repo_root).expanduser().resolve() if args.repo_root else Path.cwd().parent
    )
    fts_path = Path(data_dir) / "tokens.fts.sqlite"

    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    sys.stderr.write(f"  {g.number_of_nodes():,} nodes, {g.number_of_edges():,} edges\n")
    if g.number_of_nodes() == 0:
        sys.stderr.write("ERROR: empty graph — nothing to harvest.\n")
        return 1

    members_df = pl.read_parquet(members_path)
    interfaces_df = pl.read_parquet(interfaces_path)
    data_shapes_df = (
        pl.read_parquet(ctkr_dir / "data_shapes.parquet")
        if (ctkr_dir / "data_shapes.parquet").exists()
        else None
    )
    presentations_df = (
        pl.read_parquet(ctkr_dir / "presentations.parquet")
        if (ctkr_dir / "presentations.parquet").exists()
        else None
    )

    signals_df, load_df, conflicts_df, stats = compute_intention(
        g,
        members_df=members_df,
        interfaces_df=interfaces_df,
        data_shapes_df=data_shapes_df,
        presentations_df=presentations_df,
        repo_root=repo_root,
        view=args.view,
        exclude_prefixes=tuple(args.exclude_prefix) if args.exclude_prefix else (".claude/",),
        fts_path=fts_path if fts_path.exists() else None,
    )

    ctkr_dir.mkdir(parents=True, exist_ok=True)
    write_intention_signals(signals_df, ctkr_dir / "intention_signals.parquet")
    write_intention_load(load_df, ctkr_dir / "intention_load.parquet")
    write_intention_conflicts(conflicts_df, ctkr_dir / "intention_conflicts.parquet")
    manifest_path = write_manifest(
        data_dir,
        n_signals=signals_df.height,
        n_load=load_df.height,
        n_conflicts=conflicts_df.height,
        generated_at=args.generated_at,
    )

    sys.stderr.write(
        "\n"
        f"  intention signals   : {stats.n_signals:,} "
        f"(by indicator {stats.by_indicator})\n"
        f"  portability tiers   : {stats.by_portability}\n"
        f"  load rows           : {stats.n_load_rows:,} (classes {stats.load_classes})\n"
        f"  conflicts           : {stats.n_conflicts} "
        f"(port-critical {stats.n_port_critical})\n"
        f"  boundary exports    : {stats.n_boundary_exports} "
        f"(test-linked {stats.n_boundary_exports_tested} = "
        f"{stats.test_linkage_fraction:.1%})\n"
        f"  deferred indicators : {', '.join(sorted(stats.deferred))}\n"
        f"  manifest            : {manifest_path}\n"
        f"  elapsed             : {stats.total_seconds}s\n"
    )

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "n_signals": stats.n_signals,
                    "n_load_rows": stats.n_load_rows,
                    "n_conflicts": stats.n_conflicts,
                    "n_port_critical": stats.n_port_critical,
                    "n_boundary_exports": stats.n_boundary_exports,
                    "n_boundary_exports_tested": stats.n_boundary_exports_tested,
                    "test_linkage_fraction": stats.test_linkage_fraction,
                    "by_indicator": stats.by_indicator,
                    "by_portability": stats.by_portability,
                    "load_classes": stats.load_classes,
                    "deferred_indicators": stats.deferred,
                    "harvest_coverage": stats.coverage,
                    "elapsed_seconds": stats.total_seconds,
                },
                indent=2,
                default=str,
            )
            + "\n"
        )
    return 0
