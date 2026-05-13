"""``ctkr info`` — print environment + artifact paths.

Sanity-check subcommand. Useful as a template for new commands and as a
smoke check that the CLI plumbing is wired up.
"""

from __future__ import annotations

import argparse
import platform
import sys
from pathlib import Path

from ctkr import __version__


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser("info", help="Print ctkr version and environment info.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    del args
    print(f"ctkr             {__version__}")
    print(f"python           {sys.version.split()[0]} ({platform.platform()})")
    metacoding_root = _detect_metacoding_root()
    print(f"metacoding_root  {metacoding_root or '(not found)'}")
    if metacoding_root is not None:
        graph = metacoding_root / ".metacoding" / "graph.lbug"
        fts = metacoding_root / ".metacoding" / "tokens.fts.sqlite"
        print(f"  graph.lbug     {graph} ({'exists' if graph.exists() else 'missing'})")
        print(f"  tokens.fts     {fts} ({'exists' if fts.exists() else 'missing'})")
    return 0


def _detect_metacoding_root() -> Path | None:
    """Walk up from CWD until a `.metacoding/` directory is found."""
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".metacoding").is_dir():
            return candidate
    return None
