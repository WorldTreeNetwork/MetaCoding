#!/usr/bin/env python3
"""Regression evidence for ctkr/elenchus.py — no git, no bd, no wave.

    python3 -m pytest ctkr/tests/test_elenchus.py

The flags are an INSTRUMENT — they decide when we examine the work — so they get
instrument-tier treatment: every check below exercises a REFUTING outcome AND its
contrast. A flag asserted only to fire is indistinguishable from one that fires
always, and a flag that fires always is the same as one that never fires.

The judgment is a pure function over gathered state (`evaluate`), so all of this
runs against synthetic waves. What is NOT covered here is the gathering: whether
`git log` and `bd list` are read correctly is established by running the thing
against the real repo, and that evidence lives in the commit.
"""

from __future__ import annotations

import io
import sys
from contextlib import redirect_stdout

from ctkr.elenchus import (INVERSION_RUN, STALE_AFTER_BUILDS, cluster_findings,
                           evaluate, main, render)


def _read(readings, name):
    return next(r for r in readings if r.flag.name == name)


def _state(**kw):
    base = {"workspace": "/nowhere", "errors": {},
            "elenchus_records": ["results/wave1-ritual.md"],
            "last_elenchus": "results/wave1-ritual.md",
            "builds_since_elenchus": 0,
            "regime": []}
    base.update(kw)
    return base


def _commit(instrument=0, builds=()):
    return {"sha": "abc1234", "instrument": instrument, "builds": list(builds)}


# ---------------------------------------------------------------------------
# THE PROPERTY THAT MATTERS MOST: this is not a gate
# ---------------------------------------------------------------------------

def test_main_exits_zero_even_with_every_computable_flag_lit(monkeypatch):
    """If this ever fails, the flags have become a gate and the ritual has become
    a counter to satisfy. The charter's warning is that a method exhausting to
    live inside gets gamed; an Elenchus convened to reset a threshold produces
    three tidy questions and examines nothing."""
    import ctkr.elenchus as E
    monkeypatch.setattr(E, "gather", lambda ws, window=10: _state(
        elenchus_records=[], last_elenchus=None, builds_since_elenchus=None,
        regime=[_commit(3, ["port_runs/wave2/one"])] * 4))
    monkeypatch.setattr(E, "open_findings", lambda epic: [
        {"id": f"X-{i}", "title": "ledger.py", "description": "preflight"}
        for i in range(4)])
    out = io.StringIO()
    with redirect_stdout(out):
        rc = main(["--epic", "X"])
    assert rc == 0, "the flags became a gate"
    assert "FLAG" in out.getvalue(), "nothing lit — this test proved nothing"


def test_require_current_IS_a_gate_and_refuses_when_stale(monkeypatch):
    """The one legitimate gate: on the irreversible act, not on the smell."""
    import ctkr.elenchus as E
    monkeypatch.setattr(E, "gather", lambda ws, window=10: _state(
        builds_since_elenchus=STALE_AFTER_BUILDS + 1))
    monkeypatch.setattr(E, "open_findings", lambda epic: [])
    with redirect_stdout(io.StringIO()):
        assert main(["--epic", "X", "--require-current"]) == 2


def test_require_current_passes_when_the_reading_is_fresh(monkeypatch):
    """The contrast: a gate that refuses everything protects nothing."""
    import ctkr.elenchus as E
    monkeypatch.setattr(E, "gather", lambda ws, window=10: _state(
        builds_since_elenchus=0))
    monkeypatch.setattr(E, "open_findings", lambda epic: [])
    with redirect_stdout(io.StringIO()):
        assert main(["--epic", "X", "--require-current"]) == 0


def test_require_current_refuses_when_it_CANNOT_TELL(monkeypatch):
    """Unavailable is not clear. A check that could not run must never contribute
    a pass — the hy6.25 lesson, applied to the check that decides when we look."""
    import ctkr.elenchus as E
    monkeypatch.setattr(E, "gather", lambda ws, window=10: _state(
        errors={"history": "not a git repository"}))
    monkeypatch.setattr(E, "open_findings", lambda epic: [])
    with redirect_stdout(io.StringIO()):
        assert main(["--epic", "X", "--require-current"]) == 2


# ---------------------------------------------------------------------------
# instrument-inversion — calibrated against the episode that produced it
# ---------------------------------------------------------------------------

def test_inversion_fires_on_its_OWN_FOUNDING_CASE():
    """2026-08-07, replayed: consecutive commits hardening tools/ while the
    measured side stays inside one build. The first threshold (3) did NOT catch
    this — by the third commit the correction had already reached a second build.
    This test is the reason the constant is 2."""
    r = _read(evaluate(_state(regime=[
        _commit(3, ["port_runs/wave2/identity-farm-org"]),
        _commit(4, ["port_runs/wave2/identity-farm-org"]),
        _commit(0, ["port_runs/wave2/identity-medical"]),
    ])), "instrument-inversion")
    assert r.lit, r.evidence
    assert "1 build(s)" in r.evidence


def test_inversion_goes_DARK_once_the_work_reaches_a_second_build():
    """The contrast, and it is the behaviour that makes the flag worth having:
    the corrective action clears it. Widening coverage is what the flag is
    asking for, so doing it must turn the flag off."""
    r = _read(evaluate(_state(regime=[
        _commit(3, ["port_runs/wave2/identity-farm-org",
                    "port_runs/wave2/identity-transplanting"]),
        _commit(4, ["port_runs/wave2/identity-farm-org"]),
    ])), "instrument-inversion")
    assert not r.lit, r.evidence


def test_inversion_dark_when_the_recent_work_is_measurement():
    """A wave doing what it is supposed to do must not be flagged."""
    r = _read(evaluate(_state(regime=[
        _commit(0, ["port_runs/wave2/a"]), _commit(0, ["port_runs/wave2/b"]),
        _commit(3, ["port_runs/wave2/a"]),
    ])), "instrument-inversion")
    assert not r.lit, r.evidence


def test_inversion_needs_a_RUN_not_a_single_commit():
    """One mechanism commit is ordinary work."""
    r = _read(evaluate(_state(regime=[
        _commit(2, ["port_runs/wave2/a"]), _commit(0, ["port_runs/wave2/b"]),
    ])), "instrument-inversion")
    assert not r.lit and INVERSION_RUN > 1


# ---------------------------------------------------------------------------
# stale-whole-reading
# ---------------------------------------------------------------------------

def test_no_elenchus_ANYWHERE_is_lit_not_clear():
    """Never having read the work whole is the strongest form of overdue, and an
    empty search result is the easiest thing in the world to read as fine."""
    r = _read(evaluate(_state(elenchus_records=[], last_elenchus=None,
                              builds_since_elenchus=None)), "stale-whole-reading")
    assert r.lit and "NO Elenchus record" in r.evidence


def test_stale_fires_past_the_threshold_and_not_before():
    over = _read(evaluate(_state(builds_since_elenchus=STALE_AFTER_BUILDS)),
                 "stale-whole-reading")
    under = _read(evaluate(_state(builds_since_elenchus=STALE_AFTER_BUILDS - 1)),
                  "stale-whole-reading")
    assert over.lit and not under.lit


def test_a_history_error_is_unavailable_and_therefore_not_clear():
    r = _read(evaluate(_state(errors={"history": "boom"})), "stale-whole-reading")
    assert not r.lit and r.unavailable == "boom"


# ---------------------------------------------------------------------------
# findings-cluster
# ---------------------------------------------------------------------------

def test_cluster_needs_three_to_be_a_shape():
    two = [{"id": "a", "title": "ledger.py", "description": ""},
           {"id": "b", "title": "", "description": "ledger.py"}]
    assert cluster_findings(two) == {}
    three = two + [{"id": "c", "title": "ledger.py", "description": ""}]
    assert cluster_findings(three) == {"ledger.py": ["a", "b", "c"]}


def test_cluster_unavailable_without_a_wave_SCOPE():
    """The first version clustered every open bead in the store and lit on eleven
    across four unrelated efforts. A flag that fires always is the same as one
    that never fires, so no scope means NO ANSWER rather than a cheap yes."""
    r = _read(evaluate(_state(), findings=None, findings_error="no wave scope"),
              "findings-cluster")
    assert not r.lit and "no wave scope" in r.unavailable


def test_cluster_dark_when_the_findings_are_unalike():
    findings = [{"id": "a", "title": "kernel freeze", "description": ""},
                {"id": "b", "title": "typecheck", "description": ""},
                {"id": "c", "title": "pagination", "description": ""}]
    r = _read(evaluate(_state(), findings=findings), "findings-cluster")
    assert not r.lit, r.evidence


# ---------------------------------------------------------------------------
# the noticed flags
# ---------------------------------------------------------------------------

def test_the_noticed_flags_are_never_reported_as_clear():
    """They are the two strongest signals and neither is computable. Reporting
    them as clear would let the flag set quietly redefine 'time to examine' as
    'time the easy measurements noticed'."""
    readings = evaluate(_state())
    for name in ("cannot-say-what-it-established", "readers-converged"):
        r = _read(readings, name)
        assert not r.lit and r.unavailable, name
        assert "your call" in r.unavailable, name


def test_the_rendering_says_it_decides_nothing():
    text = render(evaluate(_state()), _state())
    assert "NOT GATES" in text
    assert "QUESTION, never a findings list" in text
