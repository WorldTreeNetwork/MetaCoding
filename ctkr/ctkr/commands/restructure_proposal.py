"""``ctkr restructure-proposal`` — emit restructure-proposal.md (MetaCoding-9h5.12).

Given the graph + its subsystem islands + the declared feature inventory,
propose the module boundaries the structure implies, the element-level moves to
reach them, and the per-move graph justification. Writes
``<data_dir>/ctkr/restructure-proposal.md``.

For an already-modular codebase (farmOS) the interesting output is where the
declared module map disagrees with the islands — SPLIT (a module the graph
scatters), MERGE (an island consolidating many modules), and per-symbol realign
moves. Prerequisites: ``ctkr subsystems`` + ``ctkr drupal-harvest`` (features)
+ ``metacoding export``, all under the same ``<data_dir>/ctkr/``. LM-free.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from ctkr.commands._common import add_common_flags, resolve_data_dir
from ctkr.graph_loader import load_graph


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "restructure-proposal",
        help="Emit restructure-proposal.md (module boundaries + moves from the graph).",
        description=(
            "Propose module boundaries for a codebase from its subsystem islands: "
            "the proposed modules (islands), the declared modules the graph splits, "
            "the islands the graph merges, and per-element realign moves justified "
            "by graph edges (cohesion gained vs declared-home coupling). Writes "
            "restructure-proposal.md under <data_dir>/ctkr/."
        ),
    )
    add_common_flags(p)
    p.add_argument(
        "--out",
        default=None,
        metavar="PATH",
        help="Where to write restructure-proposal.md (default: <data_dir>/ctkr/).",
    )
    p.add_argument(
        "--generated-at",
        default=None,
        metavar="ISO8601",
        help="Fixed timestamp to stamp on the proposal (for byte-identical re-runs).",
    )
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    import polars as pl

    from ctkr.restructure import build_restructure_proposal, write_proposal
    from ctkr.subsystems import compute_subsystems

    data_dir = resolve_data_dir(getattr(args, "data_dir", None))
    ctkr_dir = data_dir / "ctkr"
    sys.stderr.write(f"loading graph from {data_dir}...\n")
    g = load_graph(data_dir)
    if g.number_of_nodes() == 0:
        sys.stderr.write("ERROR: empty graph.\n")
        return 1

    feat_path = ctkr_dir / "features.parquet"
    if not feat_path.exists():
        sys.stderr.write(
            f"restructure-proposal: features.parquet not found at {feat_path}\n"
            "Run `ctkr drupal-harvest` first to produce the feature inventory.\n"
        )
        return 1
    features_df = pl.read_parquet(feat_path)

    sub_path = ctkr_dir / "subsystems.parquet"
    mem_path = ctkr_dir / "subsystem_members.parquet"
    if sub_path.exists() and mem_path.exists():
        sub_df = pl.read_parquet(sub_path)
        mem_df = pl.read_parquet(mem_path)
    else:
        sys.stderr.write("  no partition artifacts — computing in-memory\n")
        sub_df, mem_df, _ = compute_subsystems(g, generated_at="2026-07-20T00:00:00Z")

    proposal = build_restructure_proposal(
        g,
        mem_df,
        sub_df,
        features_df,
        generated_at=getattr(args, "generated_at", None),
    )

    out_path = Path(getattr(args, "out", None) or (ctkr_dir / "restructure-proposal.md"))
    written = write_proposal(proposal, out_path)

    if getattr(args, "as_json", False):
        sys.stdout.write(
            json.dumps(
                {
                    "repo": proposal.repo,
                    "n_islands": proposal.n_islands,
                    "n_declared_modules": proposal.n_declared_modules,
                    "n_clean_slices": len(proposal.clean_slices),
                    "n_split": len(proposal.split_disagreements),
                    "n_merge": len(proposal.merge_disagreements),
                    "n_realign_moves": len(proposal.realign_moves),
                    "out": str(written),
                },
                default=str,
            )
            + "\n"
        )
        return 0

    print(f"\n  proposed modules   : {proposal.n_islands}")
    print(f"  declared modules   : {proposal.n_declared_modules}")
    print(f"  clean slices (1:1) : {len(proposal.clean_slices)}")
    print(f"  SPLIT disagreements: {len(proposal.split_disagreements)}")
    print(f"  MERGE disagreements: {len(proposal.merge_disagreements)}")
    print(f"  realign moves      : {len(proposal.realign_moves)}")
    print(f"  elapsed            : {proposal.total_seconds}s")
    if proposal.split_disagreements:
        print("\n  top SPLIT modules (declared unit scattered across islands):")
        for d in proposal.split_disagreements[:6]:
            print(f"    {d['module']:<30} → {d['n_islands']} islands")
    print(f"\n  restructure-proposal.md → {written}")
    return 0
