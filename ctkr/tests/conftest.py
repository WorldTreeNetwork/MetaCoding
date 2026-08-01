"""Make this directory importable so tests can share helpers.

`_workspace.py` states the port workspace's location once (MetaCoding-1gt) instead
of five test modules hardcoding `parents[2] / "eval" / "ctkr" / "port_runs"`.
Importing it needs this directory on `sys.path`, which pytest does not guarantee
for a non-package test directory under every import mode.
"""

from __future__ import annotations

import sys
from pathlib import Path

_HERE = str(Path(__file__).resolve().parent)
if _HERE not in sys.path:
    sys.path.insert(0, _HERE)

# The synthetic port workspace (MetaCoding-1gt) is registered HERE rather than
# imported per module: a fixture imported by name shadows its own definition in
# every consumer, which lints as a redefinition and hides real shadowing bugs.
from _synthetic_ledger import synthetic_ledger  # noqa: E402,F401
