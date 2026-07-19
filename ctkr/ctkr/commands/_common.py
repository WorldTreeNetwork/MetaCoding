"""Shared helpers for ``ctkr`` subcommands."""

from __future__ import annotations

import argparse
import json
import os
import sys
from collections.abc import Iterable, Mapping
from pathlib import Path
from typing import Any

# Per-stage adopted routing (MetaCoding-9h5.9, Duke-approved 2026-07-19). The
# gpt56-tier comparison (results/gpt56-tier-comparison-2026-07-19.md) chose
# gpt-5.6-luna for the cheap/high-stakes labeler roles and gpt-5.6-terra for the
# strong (sonnet-class) fusion/adjudication roles. These are DEFAULTS only — the
# --provider / --model / --*-model flags stay as full overrides, and passing
# --provider anthropic restores the prior haiku/sonnet mix.
DEFAULT_LLM_PROVIDER = "openai"
GPT56_CHEAP_MODEL = "gpt-5.6-luna"
GPT56_STRONG_MODEL = "gpt-5.6-terra"

_ENV_VAR_FOR_PROVIDER = {
    "openai": "OPENAI_API_KEY",
    "anthropic": "ANTHROPIC_API_KEY",
}


def require_provider_key(provider: str, *, stage: str, default_hint: str) -> int | None:
    """Fail closed with a clear one-line message (not a deep stack trace) when the
    stage's effective provider has no API key set. Returns an exit code (2) to
    return from ``run`` when the key is missing, or ``None`` when it is present.

    ``stage`` names the command for the message; ``default_hint`` describes the
    OpenAI default so the user knows what to pass to opt back out (e.g. a
    ``--provider anthropic`` fallback invocation).
    """
    env_var = _ENV_VAR_FOR_PROVIDER.get(provider)
    if env_var and not os.environ.get(env_var):
        sys.stderr.write(
            f"ERROR: {stage} now defaults to {default_hint}, but {env_var} is not "
            f"set. Export {env_var}, or pass `--provider anthropic` to use the "
            f"prior Claude default.\n"
        )
        return 2
    return None


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


def add_kind_weight_flag(p: argparse.ArgumentParser) -> None:
    """Add the repeatable ``--kind-weight KIND=W`` flag.

    Shared by ``hom-profiles`` (write-time weighting) and the diagnostics
    (``entropy-check`` / ``marginal-entropy``) so the profile a diagnostic
    scores matches what the writer would emit for the same weights.
    """
    p.add_argument(
        "--kind-weight",
        action="append",
        default=None,
        metavar="KIND=W",
        help=(
            "Scale an edge kind's profile dimensions by float W (repeatable). "
            "Unspecified kinds default to 1.0. Example: --kind-weight "
            "CONTAINS=0.25 to down-weight containment scaffolding."
        ),
    )


def parse_kind_weights(
    raw: list[str] | None, valid_kinds: Iterable[str]
) -> dict[str, float]:
    """Parse repeated ``KIND=W`` flags into a ``{kind: weight}`` dict.

    Raises ``ValueError`` on malformed entries, non-float weights, negative
    weights, or unknown edge kinds (typo protection — an unrecognised kind
    would silently no-op otherwise). Mirrors the writer's parser so the two
    lanes can never diverge on validation.
    """
    valid = set(valid_kinds)
    weights: dict[str, float] = {}
    for item in raw or []:
        if "=" not in item:
            raise ValueError(f"--kind-weight expects KIND=W, got {item!r} (no '=').")
        kind, _, val = item.partition("=")
        kind = kind.strip()
        try:
            weight = float(val.strip())
        except ValueError as exc:
            raise ValueError(
                f"--kind-weight weight for {kind!r} is not a float: {val!r}."
            ) from exc
        if weight < 0.0:
            raise ValueError(f"--kind-weight for {kind!r} must be >= 0, got {weight}.")
        if kind not in valid:
            raise ValueError(
                f"--kind-weight kind {kind!r} is not a known edge kind. "
                f"Valid kinds: {', '.join(sorted(valid))}."
            )
        weights[kind] = weight
    return weights


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
