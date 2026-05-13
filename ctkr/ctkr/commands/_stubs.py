"""Stub subcommand factory for commands whose implementation is owned
by a not-yet-closed bd issue.

Stubs satisfy the CLI surface (``--help``, registration) so users
discover the planned subcommands without needing to read the issue
tracker. Running them prints the owning issue ID and exits non-zero.
"""

from __future__ import annotations

import argparse
import sys


def make_stub(
    name: str,
    summary: str,
    description: str,
    owning_issue: str,
) -> tuple[
    callable[[argparse._SubParsersAction], None],  # type: ignore[type-arg]
    callable[[argparse.Namespace], int],  # type: ignore[type-arg]
]:
    """Build a (register, run) pair for an unimplemented subcommand."""

    def register(subparsers: argparse._SubParsersAction) -> None:
        p = subparsers.add_parser(
            name,
            help=summary,
            description=description,
        )
        p.set_defaults(func=_run, _name=name, _issue=owning_issue)

    def _run(args: argparse.Namespace) -> int:
        sys.stderr.write(
            f"`ctkr {args._name}` is not yet implemented.\n"
            f"  Owned by bd issue: {args._issue}\n"
            f"  Run `bd show {args._issue}` for details.\n"
        )
        return 2

    return register, _run
