"""MetaCoding-7xr lever 4 — LLM scratch discipline.

Wave-1 prep wrote ``llm_cache/`` + ``llm_cost.jsonl`` INTO the shared graph
data-dir the commands were reading: a sandbox declared read-only, mutated by
its own reader (wave1-ritual-2026-07-22.md, Elenchus question 3). Pins:

* the guard refuses cache/cost paths inside a data-dir, loudly, at argument
  resolution;
* scratch defaults live under the user cache root, per command;
* NO command module constructs an LLM cache/cost path from a data-dir-derived
  variable — the exact textual shape of the original mistake, pinned
  repo-wide so a new command cannot quietly reintroduce it.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ctkr.llm import SCRATCH_ROOT, sandbox_write_guard, scratch_dir


def test_scratch_dir_is_under_the_user_cache_root_never_a_data_dir() -> None:
    d = scratch_dir("mine-fixtures")
    assert d == SCRATCH_ROOT / "mine-fixtures"
    assert Path.home() in d.parents


def test_the_guard_refuses_paths_inside_the_data_dir(tmp_path: Path) -> None:
    data_dir = tmp_path / "farmos-data"
    data_dir.mkdir()
    with pytest.raises(ValueError, match="READ-ONLY"):
        sandbox_write_guard(data_dir, data_dir / "ctkr" / "llm_cache")
    with pytest.raises(ValueError, match="READ-ONLY"):
        sandbox_write_guard(data_dir, tmp_path / "elsewhere", data_dir)


def test_the_guard_admits_scratch_and_unrelated_paths(tmp_path: Path) -> None:
    data_dir = tmp_path / "farmos-data"
    data_dir.mkdir()
    sandbox_write_guard(data_dir, scratch_dir("label-roles") / "llm_cache")
    sandbox_write_guard(data_dir, tmp_path / "elsewhere" / "llm_cache")
    sandbox_write_guard(None, data_dir / "anything")  # no data-dir, no opinion


def test_no_command_builds_llm_artifacts_inside_a_data_dir() -> None:
    """The original mistake was `ctkr_dir / "llm_cache"` (ctkr_dir being
    <data_dir>/ctkr). Pin its absence textually across every command module:
    crude, but it is the exact shape that shipped, and a lint that exists
    beats a review note that fades."""
    commands = Path(__file__).resolve().parents[1] / "ctkr" / "commands"
    offenders: list[str] = []
    for py in sorted(commands.glob("*.py")):
        text = py.read_text(encoding="utf-8")
        for i, line in enumerate(text.splitlines(), 1):
            if ("llm_cache" in line or "llm_cost" in line) and (
                "ctkr_dir /" in line or "data_dir /" in line
            ):
                offenders.append(f"{py.name}:{i}: {line.strip()}")
    assert offenders == [], (
        "LLM cache/cost artifacts built from a data-dir path — a sandbox a "
        "command reads is READ-ONLY; use ctkr.llm.scratch_dir():\n  "
        + "\n  ".join(offenders)
    )
