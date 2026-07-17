"""``ctkr feature-join`` — join features.parquet to the structural lane.

Reads the D1 Feature Inventory (``features.parquet``) produced by
``ctkr drupal-harvest``, the structural graph export (``nodes.jsonl``),
and the subsystem membership table (``subsystem_members.parquet``) to fill
in the ``subsystem_ids`` column on each feature row.

Also emits ``feature_subsystem_disagree.parquet`` — the feature/subsystem
disagreement signal (``decomposition-schema.md`` §2.1): features that span
many structural subsystems are cross-cutting concerns; features that map to
exactly one subsystem are clean vertical slices.

All inputs and outputs live under ``<data_dir>/ctkr/``.  Run after both
``ctkr drupal-harvest`` and ``ctkr subsystems`` (+ ``metacoding export``).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "feature-join",
        help="Join features.parquet to structural subsystems (MetaCoding-7fs).",
        description=(
            "Fill the subsystem_ids column in features.parquet by matching each "
            "feature's member_globs against the structural graph's subsystem "
            "membership table.  Also writes feature_subsystem_disagree.parquet "
            "with the disagreement signal (how many structural subsystems each "
            "feature spans, sorted by count descending).\n\n"
            "Prerequisites: run `ctkr drupal-harvest` to produce features.parquet, "
            "then `metacoding export` + `ctkr subsystems` to produce nodes.jsonl + "
            "subsystem_members.parquet — all under the same <data_dir>/ctkr/."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--features",
        default=None,
        metavar="PATH",
        help="Override path to features.parquet (default: <data_dir>/ctkr/features.parquet).",
    )
    p.add_argument(
        "--out-features",
        default=None,
        metavar="PATH",
        help="Where to write the enriched features.parquet (default: in-place).",
    )
    p.add_argument(
        "--out-disagree",
        default=None,
        metavar="PATH",
        help="Where to write feature_subsystem_disagree.parquet (default: <data_dir>/ctkr/).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.feature_join import join_features_to_subsystems

    data_dir = resolve_data_dir(getattr(args, "data_dir", None))

    try:
        stats = join_features_to_subsystems(
            data_dir,
            features_path=getattr(args, "features", None),
            out_features_path=getattr(args, "out_features", None),
            out_disagree_path=getattr(args, "out_disagree", None),
        )
    except FileNotFoundError as exc:
        sys.stderr.write(f"feature-join: {exc}\n")
        sys.stderr.write(
            "Run `metacoding export` + `ctkr subsystems` first to produce the "
            "structural data, then re-run `ctkr feature-join`.\n"
        )
        return 1

    if getattr(args, "as_json", False):
        import dataclasses
        sys.stdout.write(json.dumps(dataclasses.asdict(stats), default=str) + "\n")
        return 0

    ctkr_dir = data_dir / "ctkr"
    print(f"  features joined    : {stats.n_features}")
    print(f"  with subsystems    : {stats.n_features_with_subsystems}")
    print(f"  cross-cutting (>1) : {stats.n_features_cross_cutting}")
    print(f"  avg subsystems     : {stats.avg_subsystems_per_feature:.2f}")
    print(f"  nodes loaded       : {stats.nodes_loaded}")
    print(f"  members loaded     : {stats.members_loaded}")
    print(f"  elapsed            : {stats.elapsed_seconds}s")
    if stats.top_disagreements:
        print("\n  top cross-cutting features:")
        for d in stats.top_disagreements[:5]:
            print(f"    {d['name']:<40s} {d['n_subsystems']} subsystems")
    out_feat = getattr(args, "out_features", None) or (ctkr_dir / "features.parquet")
    out_dis = getattr(args, "out_disagree", None) or (ctkr_dir / "feature_subsystem_disagree.parquet")
    print(f"\n  features.parquet   → {out_feat}")
    print(f"  disagree.parquet   → {out_dis}")

    return 0
