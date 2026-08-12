#!/usr/bin/env python3
"""Regression evidence for ctkr/verdict_currency.py.

    python3 -m pytest ctkr/tests/test_verdict_currency.py

This gate is an INSTRUMENT — it decides whether a build counts as done — so every
check below exercises a REFUTING outcome AND its contrast. A gate asserted only to
refuse is indistinguishable from one that refuses everything, and a gate that
refuses everything gets switched off exactly as fast as one that refuses nothing.

Built against synthetic workspaces, so the rules are testable without the port
tree. What is NOT covered here is discovery against the real workspace; that
evidence is the run recorded in the commit.
"""

from __future__ import annotations

import json

from ctkr.verdict_currency import (SPINE, current_wave, discover, evaluate,
                                   load_verdicts, main, tier_of)


# ---------------------------------------------------------------------------
# a synthetic workspace
# ---------------------------------------------------------------------------

def workspace(tmp_path, builds, verdicts=(), wave="wave2"):
    """builds: {name: {"seal": str|None, "manifest": bool}}"""
    for name, spec in builds.items():
        b = tmp_path / "port_runs" / wave / name
        if spec.get("manifest", True):
            (b / "build").mkdir(parents=True, exist_ok=True)
            (b / "build" / "port.manifest.json").write_text('{"port":"%s"}' % name)
        if spec.get("seal") is not None:
            (b / "observe").mkdir(parents=True, exist_ok=True)
            (b / "observe" / "pack.seal.json").write_text(
                json.dumps({"seal": spec["seal"]}))
    vd = tmp_path / "results" / "port-verify"
    vd.mkdir(parents=True, exist_ok=True)
    for fn, doc in verdicts:
        (vd / fn).write_text(doc if isinstance(doc, str) else json.dumps(doc))
    return str(tmp_path)


def verdict(port, seal, clean=True):
    return {"port": port, "pack_seal": seal, "clean": clean, "score": {}}


def rows_for(tmp_path, builds, verdicts=(), wave="wave2"):
    ws = workspace(tmp_path, builds, verdicts, wave)
    v, _err = load_verdicts(ws)
    return {r.build.name: r for r in evaluate(discover(ws, wave), v)}


# ---------------------------------------------------------------------------
# the rules, each refuting + its contrast
# ---------------------------------------------------------------------------

def test_a_build_with_no_verdict_GATES(tmp_path):
    r = rows_for(tmp_path, {"identity-a": {"seal": "abc"}})["identity-a"]
    assert r.state == "missing" and r.gates


def test_a_build_WITH_a_current_clean_verdict_does_not(tmp_path):
    """The contrast. A gate that refuses a correctly-verified build is a gate
    someone deletes within the week."""
    r = rows_for(tmp_path, {"identity-a": {"seal": "abc"}},
                 [("a.json", verdict("w2-identity-a", "abc"))])["identity-a"]
    assert r.state == "ok" and not r.gates


def test_a_verdict_against_a_SUPERSEDED_pack_gates(tmp_path):
    """The subtle one, and the reason the seal is compared rather than the name:
    re-recording a pack silently invalidates every score taken on the old one, and
    the stale verdict keeps sitting there looking like evidence."""
    r = rows_for(tmp_path, {"identity-a": {"seal": "NEW"}},
                 [("a.json", verdict("w2-identity-a", "OLD"))])["identity-a"]
    assert r.state == "stale" and r.gates
    assert "no longer exists" in r.detail


def test_an_UNCLEAN_verdict_gates(tmp_path):
    r = rows_for(tmp_path, {"identity-a": {"seal": "abc"}},
                 [("a.json", verdict("w2-identity-a", "abc", clean=False))])["identity-a"]
    assert r.state == "unclean" and r.gates


def test_a_build_with_NO_SEALED_PACK_gates_and_is_not_called_ok(tmp_path):
    """Absence of an answer is never a yes. A build with no pack has not been
    driven at all — the strongest form of undriven, and the easiest to read as
    'nothing to check here'."""
    r = rows_for(tmp_path, {"identity-a": {"seal": None}})["identity-a"]
    assert r.state == "undeterminable" and r.gates


def test_an_UNREADABLE_verdict_counts_as_NO_verdict(tmp_path):
    """A corrupt report must never satisfy the gate it was supposed to satisfy."""
    ws = workspace(tmp_path, {"identity-a": {"seal": "abc"}},
                   [("a.json", "{not json")])
    v, errors = load_verdicts(ws)
    rows = {r.build.name: r for r in evaluate(discover(ws, "wave2"), v)}
    assert rows["identity-a"].gates
    assert any("never as one" in e for e in errors)


# ---------------------------------------------------------------------------
# the bound decision: spine is advisory
# ---------------------------------------------------------------------------

def test_SPINE_never_gates_even_with_no_verdict(tmp_path):
    """MetaCoding-hy6 (2)/(4), reaffirmed by Duke as hy6.51. Spine builds are
    REPORTED and never block. If this test starts failing, someone widened the
    gate without reopening the risk partition."""
    r = rows_for(tmp_path, {"spine-a": {"seal": None}})["spine-a"]
    assert r.build.tier == SPINE
    assert r.state == "undeterminable"
    assert not r.gates, "the gate reversed a bound decision"


def test_an_UNCLASSIFIABLE_build_gates(tmp_path):
    """Neither identity- nor spine-: nobody decided about it, so it is not
    exempt. The exemption is a decision, not a default."""
    r = rows_for(tmp_path, {"mystery": {"seal": None}})["mystery"]
    assert r.gates


def test_tier_comes_from_the_name():
    assert tier_of("identity-sensor") == "identity"
    assert tier_of("spine-asset") == "spine"
    assert tier_of("quick-folds") == "unknown"


# ---------------------------------------------------------------------------
# vacuity
# ---------------------------------------------------------------------------

def test_an_EMPTY_SWEEP_refuses_rather_than_passing(tmp_path, capsys):
    """The classic vacuous pass: find no builds, report everything verified. A
    wrong --workspace would otherwise be indistinguishable from a clean tree."""
    (tmp_path / "port_runs" / "wave2").mkdir(parents=True)
    assert main(["--workspace", str(tmp_path)]) == 2
    assert "REFUSING" in capsys.readouterr().err


def test_main_exits_2_when_a_gating_build_lacks_a_verdict(tmp_path):
    workspace(tmp_path, {"identity-a": {"seal": "abc"}})
    assert main(["--workspace", str(tmp_path)]) == 2


def test_main_exits_0_when_every_gating_build_is_current(tmp_path):
    """The contrast that makes the exit code worth reading."""
    workspace(tmp_path, {"identity-a": {"seal": "abc"}, "spine-b": {"seal": None}},
              [("a.json", verdict("w2-identity-a", "abc"))])
    assert main(["--workspace", str(tmp_path)]) == 0


def test_the_wave_scope_is_the_newest_wave(tmp_path):
    """Sweeping retired pilot waves would keep the gate permanently red, and a
    permanently-red gate is ignored as fast as a permanently-green one."""
    workspace(tmp_path, {"identity-old": {"seal": None}}, wave="wave0-pilot")
    workspace(tmp_path, {"identity-new": {"seal": "abc"}}, wave="wave2")
    assert current_wave(str(tmp_path)) == "wave2"
    names = {b.name for b in discover(str(tmp_path), "wave2")}
    assert names == {"identity-new"}, names
