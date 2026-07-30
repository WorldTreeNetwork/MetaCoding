"""Where tests find the port workspace's ledger (MetaCoding-1gt).

The farmOS ledger — `port_runs/`, `results/`, the 43 sealed packs, PACKS.jsonl —
now lives in its own repo (github.com/WorldTreeNetwork/FarmOS2, cloned beside this
one as `farmos-port`). It used to sit at `eval/ctkr` inside this repo, and five
test modules hardcoded `parents[2] / "eval" / "ctkr" / "port_runs"`.

They resolve it through the workspace resolver instead, so the ledger's location
is stated once, here, and follows the same discovery every command uses.

WHAT THIS COSTS, stated plainly (Duke's call, 2026-07-30): the instrument's suite
now depends on a SIBLING CHECKOUT. A clone of MetaCoding alone will SKIP these
tests rather than fail, which means a green run on a fresh clone is a weaker claim
than a green run here. That is accepted as temporary: in-repo synthetic fixtures
replace this once the porting code stabilises, and until then
:data:`requires_ledger` says exactly what is missing rather than skipping quietly.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ctkr.oracle.port_contract import port_workspace
from ctkr.workspace import WORKSPACE_SEARCH_PATH

#: The instrument repo root.
REPO_ROOT: Path = Path(__file__).resolve().parents[2]

#: The resolved port workspace, and the ledger inside it.
WORKSPACE: Path = port_workspace(REPO_ROOT)
PORT_RUNS: Path = WORKSPACE / "port_runs"
RESULTS: Path = WORKSPACE / "results"
PACKS_LEDGER: Path = PORT_RUNS / "PACKS.jsonl"

#: Present means the ledger is really there, not merely that a path was spelled.
LEDGER_PRESENT: bool = PACKS_LEDGER.is_file()

requires_ledger = pytest.mark.skipif(
    not LEDGER_PRESENT,
    reason=(
        f"port-workspace ledger not found (looked for {PACKS_LEDGER}). The farmOS "
        f"ledger is a separate repo: clone github.com/WorldTreeNetwork/FarmOS2 to "
        f"one of {list(WORKSPACE_SEARCH_PATH)} relative to {REPO_ROOT}. These tests "
        f"read REAL sealed packs and cannot run without them — a green run without "
        f"the ledger is a weaker claim than a green run with it (MetaCoding-1gt)."
    ),
)
