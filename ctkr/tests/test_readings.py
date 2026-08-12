#!/usr/bin/env python3
"""Regression evidence for ctkr/readings.py.

    uv run pytest ctkr/tests/test_readings.py

This decides what counts as "read", so it is instrument tier: every check below
exercises a REFUTING outcome AND its contrast. A coverage number is the easiest
thing in this project to inflate — count the wrong denominator, or accept a row
that says nothing — and both directions are tested here.
"""

from __future__ import annotations

import json

from ctkr.readings import (KINDS, coverage, load_readings, ratchet,
                           readable_targets)


def workspace(tmp_path, builds=(), readings=(), baseline=None):
    """builds: [(wave, name, [entries])] — entries decide whether it is a BUILD."""
    for wave, name, entries in builds:
        for e in entries:
            d = tmp_path / "port_runs" / wave / name / e
            if e.endswith(".json"):
                d.parent.mkdir(parents=True, exist_ok=True)
                d.write_text("{}")
            else:
                d.mkdir(parents=True, exist_ok=True)
        (tmp_path / "port_runs" / wave / name).mkdir(parents=True, exist_ok=True)
    pr = tmp_path / "port_runs"
    pr.mkdir(parents=True, exist_ok=True)
    if readings:
        (pr / "READINGS.jsonl").write_text(
            "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in readings))
    if baseline is not None:
        (pr / "READINGS.baseline.json").write_text(json.dumps({"unread": baseline}))
    return str(tmp_path)


def row(target, **kw):
    base = {"record": "reading", "target": target, "kind": "judge", "at": "2026-08-01",
            "reader": "fresh-agent", "artifact": "results/x.md",
            "not_read": "the build's own src"}
    base.update(kw)
    return base


# ---------------------------------------------------------------------------
# what counts as a readable target — the denominator
# ---------------------------------------------------------------------------

def test_a_BUILD_is_a_target_and_a_bare_directory_is_NOT(tmp_path):
    """The first version counted every subdirectory and reported 36 readable
    targets including `wave0-pilot/w0a-observe`. An inflated denominator is the
    cheapest way to make coverage look worse than it is, and it is the same class
    of error as counting manifests while calling them builds (hy6.57)."""
    ws = workspace(tmp_path, builds=[
        ("wave2", "identity-real", ["build", "observe"]),
        ("wave2", "just-a-folder", ["notes"]),
        ("wave1-c1", "portA", ["port.manifest.json"]),
    ])
    assert readable_targets(ws) == ["wave1-c1/portA", "wave2/identity-real"]


def test_a_non_wave_directory_is_not_swept(tmp_path):
    ws = workspace(tmp_path, builds=[("lexicon-bind", "thing", ["build"])])
    assert readable_targets(ws) == []


# ---------------------------------------------------------------------------
# what counts as a reading — the numerator
# ---------------------------------------------------------------------------

def test_a_row_with_NO_not_read_is_REFUSED(tmp_path):
    """`not_read` is the field that costs something. Every judge report this
    project trusted carried one; the judge that died before writing it left a gap
    nobody could size. A reading that will not say what it skipped is a claim."""
    ws = workspace(tmp_path, builds=[("wave2", "b", ["build"])],
                   readings=[row("wave2/b", not_read="")])
    out, errors = load_readings(ws)
    assert out == []
    assert any("not_read" in e or "skipped" in e for e in errors), errors
    assert coverage(ws)["unread"] == ["wave2/b"], "an uncounted row still marked it read"


def test_a_COMPLETE_row_counts(tmp_path):
    """The contrast. Without it, a loader that rejected everything would pass the
    test above and report perfect ignorance forever."""
    ws = workspace(tmp_path, builds=[("wave2", "b", ["build"])], readings=[row("wave2/b")])
    assert coverage(ws)["unread"] == []


def test_an_UNREADABLE_row_is_an_error_not_a_skip(tmp_path):
    ws = workspace(tmp_path, builds=[("wave2", "b", ["build"])],
                   readings=["{not json", json.dumps(row("wave2/b"))])
    out, errors = load_readings(ws)
    assert len(out) == 1
    assert any("unreadable" in e for e in errors)


def test_a_kind_OUTSIDE_the_vocabulary_is_refused(tmp_path):
    """A closed vocabulary with no escape member — an unnamed kind is how
    'I glanced at it' becomes 'it was read'."""
    ws = workspace(tmp_path, builds=[("wave2", "b", ["build"])],
                   readings=[row("wave2/b", kind="glance")])
    out, errors = load_readings(ws)
    assert out == [] and any("outside" in e for e in errors)
    assert "glance" not in KINDS


# ---------------------------------------------------------------------------
# the ratchet
# ---------------------------------------------------------------------------

def test_the_ratchet_REFUSES_a_new_build_joining_the_unread_set(tmp_path):
    ws = workspace(tmp_path, builds=[("wave2", "old", ["build"]), ("wave2", "new", ["build"])],
                   baseline=["wave2/old"])
    ok, msg = ratchet(ws)
    assert not ok
    assert "wave2/new" in msg and "GREW" in msg


def test_the_ratchet_PASSES_when_the_unread_set_is_unchanged(tmp_path):
    """The contrast that makes the refusal worth reading. A ratchet that refused
    a steady state would be deleted within the week — which is the whole reason
    this is a ratchet and not 'everything must be read'."""
    ws = workspace(tmp_path, builds=[("wave2", "old", ["build"])], baseline=["wave2/old"])
    ok, _ = ratchet(ws)
    assert ok


def test_the_ratchet_PASSES_when_the_set_SHRINKS_and_says_to_re_cut(tmp_path):
    """Reading something must never be refused. It should say the baseline is now
    stale, because a baseline that is never re-cut silently permits regression
    back up to it."""
    ws = workspace(tmp_path, builds=[("wave2", "a", ["build"]), ("wave2", "b", ["build"])],
                   readings=[row("wave2/a")], baseline=["wave2/a", "wave2/b"])
    ok, msg = ratchet(ws)
    assert ok and "re-cut" in msg


def test_NO_baseline_is_a_REFUSAL_not_a_pass(tmp_path):
    """Absence of an answer is never a yes. Nothing being held is not the same as
    nothing being wrong."""
    ws = workspace(tmp_path, builds=[("wave2", "a", ["build"])])
    ok, msg = ratchet(ws)
    assert not ok and "no ratchet baseline" in msg


def test_an_unread_build_the_baseline_EXCUSES_does_not_gate(tmp_path):
    """The accepted-debt half: a build in the baseline is known-unread and does
    not refuse. If this ever fails, the ratchet has become a gate and will be
    deleted."""
    ws = workspace(tmp_path, builds=[("wave2", "known", ["build"])], baseline=["wave2/known"])
    ok, _ = ratchet(ws)
    assert ok
