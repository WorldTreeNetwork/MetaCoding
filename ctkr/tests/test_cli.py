from __future__ import annotations

import io
import re
from contextlib import redirect_stdout

import pytest

from ctkr import __version__
from ctkr.cli import main


def test_help_runs_and_lists_info_subcommand() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf), pytest.raises(SystemExit) as exc:
        main(["--help"])
    out = buf.getvalue()
    assert exc.value.code == 0
    assert "ctkr" in out
    assert "info" in out  # the seed subcommand registers


def test_version_flag() -> None:
    with pytest.raises(SystemExit) as exc:
        main(["--version"])
    assert exc.value.code == 0


def test_no_args_prints_help_and_returns_zero() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main([])
    assert code == 0
    assert "usage" in buf.getvalue().lower()


def test_info_subcommand_runs() -> None:
    buf = io.StringIO()
    with redirect_stdout(buf):
        code = main(["info"])
    out = buf.getvalue()
    assert code == 0
    assert re.search(rf"^ctkr\s+{re.escape(__version__)}", out, re.MULTILINE)
