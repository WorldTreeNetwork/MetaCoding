"""Shared helpers for ``ctkr`` subcommands."""

from __future__ import annotations

import argparse
import json
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any


def detect_metacoding_root() -> Path | None:
    """Walk up from CWD until a ``.metacoding/`` directory is found."""
    cur = Path.cwd().resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".metacoding").is_dir():
            return candidate
    return None


def resolve_data_dir(arg_value: str | None) -> Path:
    """Resolve the user-supplied --data-dir, or auto-detect.

    Raises a friendly ``SystemExit`` when nothing is found so subcommands
    don't have to repeat the same error-handling boilerplate.
    """
    if arg_value:
        p = Path(arg_value).expanduser().resolve()
        if not p.exists():
            sys.stderr.write(f"--data-dir {p} does not exist\n")
            raise SystemExit(2)
        return p
    root = detect_metacoding_root()
    if root is None:
        sys.stderr.write(
            "No .metacoding/ found by walking up from cwd. "
            "Pass --data-dir <path-to-.metacoding/>.\n"
        )
        raise SystemExit(2)
    return root / ".metacoding"


def add_common_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument(
        "--data-dir",
        default=None,
        help="Path to .metacoding/ (auto-detected by walking up from cwd).",
    )
    p.add_argument(
        "--json",
        dest="as_json",
        action="store_true",
        help="Emit JSON instead of a tabular view.",
    )


def emit(rows: list[Mapping[str, Any]], *, as_json: bool, columns: Iterable[str]) -> None:
    """Emit a list of rows as either JSON or a fixed-width table."""
    if as_json:
        sys.stdout.write(json.dumps(list(rows), default=str) + "\n")
        return

    cols = list(columns)
    if not rows:
        sys.stdout.write("(no rows)\n")
        return

    widths: dict[str, int] = {c: len(c) for c in cols}
    str_rows: list[dict[str, str]] = []
    for r in rows:
        sr = {c: _fmt(r.get(c)) for c in cols}
        for c in cols:
            widths[c] = max(widths[c], len(sr[c]))
        str_rows.append(sr)

    def fmt_row(d: Mapping[str, str]) -> str:
        return "  ".join(d[c].ljust(widths[c]) for c in cols)

    sys.stdout.write(fmt_row({c: c for c in cols}) + "\n")
    sys.stdout.write(fmt_row({c: "-" * widths[c] for c in cols}) + "\n")
    for sr in str_rows:
        sys.stdout.write(fmt_row(sr) + "\n")


def _fmt(v: Any) -> str:
    if v is None:
        return ""
    if isinstance(v, float):
        return f"{v:.4f}"
    if isinstance(v, (list, tuple)):
        return ",".join(str(x) for x in v)
    return str(v)
