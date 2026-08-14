#!/usr/bin/env python3
"""Regression evidence for ctkr/wave.py.

    uv run --group dev pytest ctkr/tests/test_wave.py

This decides when a wave may be sealed, so it is instrument tier: every check
exercises a REFUSING outcome AND its contrast. The contrasts matter more than
usual here, because the two ways this ritual dies are symmetric and both fatal —
a close that only succeeds when everything is perfect never succeeds, and a close
that succeeds regardless is a rubber stamp.
"""

from __future__ import annotations

import json

import ctkr.wave as W
from ctkr.wave import (AFFIRMATIONS, Check, append, close, load_waves, open_,
                       open_waves)

AT = "2026-08-12"
GOOD = {k: "Duke" for k in AFFIRMATIONS}


def ws(tmp_path, rows=()):
    d = tmp_path / "port_runs"
    d.mkdir(parents=True, exist_ok=True)
    if rows:
        (d / "WAVES.jsonl").write_text(
            "".join((r if isinstance(r, str) else json.dumps(r)) + "\n" for r in rows))
    return str(tmp_path)


def opened(name, at="2026-08-01"):
    return {"record": "open", "wave": name, "opened_at": at}


def closed(name, at="2026-08-02"):
    return {"record": "close", "wave": name, "closed_at": at}


def green(*_a, **_k):
    return [Check("committed:x", True, "clean", carryable=False),
            Check("verdicts", True, "all current")]


def one_red(*_a, **_k):
    return [Check("committed:x", True, "clean", carryable=False),
            Check("verdicts", False, "19 gating builds lack a verdict")]


def unsafe(*_a, **_k):
    return [Check("committed:x", False, "3 uncommitted changes", carryable=False)]


# ---------------------------------------------------------------------------
# open — the mechanism that makes closing unforgettable
# ---------------------------------------------------------------------------

def test_open_REFUSES_while_the_predecessor_is_open(tmp_path):
    """The whole design in one test. You cannot forget to close wave N if opening
    N+1 refuses while N is open — that converts the ritual from memory-dependent
    to path-dependent, the only kind enforceability.md found that works here."""
    ok, msg, row = open_(ws(tmp_path, [opened("wave2")]), "wave3", at=AT)
    assert not ok and row is None
    assert "wave2 is still open" in msg


def test_open_SUCCEEDS_once_the_predecessor_is_closed(tmp_path):
    """The contrast. A gate that refuses even the correct sequence protects
    nothing and gets removed."""
    ok, _, row = open_(ws(tmp_path, [opened("wave2"), closed("wave2")]), "wave3", at=AT)
    assert ok and row["record"] == "open" and row["predecessor"] == "wave2"


def test_force_PROCEEDS_and_writes_the_reason_as_a_first_class_row(tmp_path):
    """The override is not a weakening — it is WHERE THE RECORD COMES FROM. A gate
    with no escape hatch gets bypassed by editing the ledger by hand, at which
    point you have neither enforcement nor a record."""
    ok, msg, row = open_(ws(tmp_path, [opened("wave2")]), "wave3", at=AT,
                         force="wave2 cannot close until the kernel freeze lands")
    assert ok
    assert row["forced_over_open"] == ["wave2"]
    assert "kernel freeze" in row["force_reason"]
    assert "OVERRIDE RECORDED" in msg


def test_a_FORCE_WITHOUT_A_REAL_REASON_is_refused(tmp_path):
    ok, msg, _ = open_(ws(tmp_path, [opened("wave2")]), "wave3", at=AT, force="later")
    assert not ok and "is not a reason" in msg


# ---------------------------------------------------------------------------
# close — B affirmations
# ---------------------------------------------------------------------------

def test_close_REFUSES_without_the_human_affirmations(tmp_path, monkeypatch):
    """These are questions, not checks. Nothing here can verify them, and the
    moment one looks verified the ritual is a rubber stamp."""
    monkeypatch.setattr(W, "checks", green)
    ok, msg, _ = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm={})
    assert not ok
    assert "UNANSWERED" in msg
    for k in AFFIRMATIONS:
        assert k in msg


def test_an_affirmation_is_recorded_WITH_A_NAME(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "checks", green)
    ok, _, row = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm=GOOD)
    assert ok
    assert {a["what"] for a in row["affirmed"]} == set(AFFIRMATIONS)
    assert all(a["by"] == "Duke" for a in row["affirmed"])


# ---------------------------------------------------------------------------
# close — A checks, and the carry-forward that keeps it usable
# ---------------------------------------------------------------------------

def test_UNCOMMITTED_WORK_cannot_be_carried_forward(tmp_path, monkeypatch):
    """Refusal is reserved for UNSAFE, not UNFINISHED. Sealing a tree with
    uncommitted work in it is the unsafe one: the row would describe a state that
    is not in the history."""
    monkeypatch.setattr(W, "checks", unsafe)
    ok, msg, _ = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm=GOOD,
                       carry={"committed:x": "we will commit it right after this"})
    assert not ok and "UNSAFE" in msg


def test_a_failing_check_NOBODY_MENTIONED_refuses(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "checks", one_red)
    ok, msg, _ = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm=GOOD)
    assert not ok
    assert "NOT DONE and nobody said so" in msg and "verdicts" in msg


def test_a_wave_CAN_be_closed_with_debt_that_is_named(tmp_path, monkeypatch):
    """THE contrast, and the one this ritual lives or dies by. A ritual that only
    succeeds when everything is perfect never succeeds. 'Not done' is a legitimate
    close; 'not done and nobody said so' is not."""
    monkeypatch.setattr(W, "checks", one_red)
    ok, msg, row = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm=GOOD,
                         carry={"verdicts": "19 gating builds lack verdicts; the "
                                            "remedy is uncosted and tracked in hy6.49"})
    assert ok, msg
    assert row["carried"][0]["item"] == "verdicts"
    assert "hy6.49" in row["carried"][0]["reason"]


def test_a_THIN_reason_is_refused(tmp_path, monkeypatch):
    """Carrying everything forward with the reason 'known' is the documented way
    to fake this. The reason field cannot be validated for honesty, but it can be
    made to cost something."""
    monkeypatch.setattr(W, "checks", one_red)
    ok, msg, _ = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm=GOOD,
                       carry={"verdicts": "known"})
    assert not ok and "is not a reason" in msg.lower()


def test_SKIPPING_the_suites_is_not_a_pass(tmp_path, monkeypatch):
    """hy6.25, in the seat where it would do the most damage: a check that did not
    run must never contribute to a seal."""
    monkeypatch.undo()
    results = W.checks(ws(tmp_path), "wave2", elenchus=None, run_suites=False)
    skipped = [c for c in results if c.name.startswith(("suite:", "smoke"))]
    assert skipped and all(not c.ok for c in skipped)
    assert all("not an answer" in c.detail for c in skipped)


def test_an_elenchus_that_does_not_exist_refuses(tmp_path, monkeypatch):
    results = W.checks(ws(tmp_path), "wave2", elenchus="results/nope.md", run_suites=False)
    e = next(c for c in results if c.name == "elenchus")
    assert not e.ok and "no such file" in e.detail


# ---------------------------------------------------------------------------
# the ledger itself
# ---------------------------------------------------------------------------

def test_reopening_after_a_close_is_TWO_ROWS_not_an_edit(tmp_path):
    """Append-only. The history of what we accepted is the point — a wave closed
    with debt and later re-opened must remain visible as both events."""
    w = ws(tmp_path, [opened("wave2"), closed("wave2"), opened("wave2", "2026-08-20")])
    waves, _ = load_waves(w)
    assert waves["wave2"].is_open
    assert len(waves["wave2"].rows) == 3
    assert [r["record"] for r in waves["wave2"].rows] == ["open", "close", "open"]


def test_an_unreadable_row_RAISES_rather_than_being_skipped(tmp_path):
    """This ledger decides what is open. A row nobody can parse is not a row that
    can be quietly ignored — skipping it could make a wave look closed."""
    w = ws(tmp_path, ["{not json", json.dumps(opened("wave2"))])
    try:
        load_waves(w)
    except RuntimeError as exc:
        assert "unreadable" in str(exc)
    else:
        raise AssertionError("an unparseable row was silently skipped")


def test_no_ledger_means_no_wave_is_open_and_that_is_not_an_error(tmp_path):
    assert open_waves(ws(tmp_path)) == []


def test_append_writes_the_header_once(tmp_path):
    w = ws(tmp_path)
    append(w, opened("wave2"))
    append(w, closed("wave2"))
    text = open(W.ledger_path(w)).read()
    assert text.count("append-only") == 1
    assert len([l for l in text.splitlines() if not l.startswith("//")]) == 2


def test_a_closed_wave_cannot_be_closed_again(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "checks", green)
    ok, msg, _ = close(ws(tmp_path, [opened("wave2"), closed("wave2")]), "wave2",
                       at=AT, affirm=GOOD)
    assert not ok and "already closed" in msg


def test_UNTRACKED_source_cannot_pass_unmentioned(tmp_path):
    """Found on this ritual's FIRST dry run: the close passed cleanly while
    `wave.py` — the file implementing the close — sat untracked in the tree,
    because the first version filtered `??` away entirely.

    Untracked SOURCE is uncommitted work. Untracked build noise is not, and no
    rule can tell them apart — so untracked is CARRYABLE (nameable, not blocking)
    while modified stays UNSAFE. This project has already paid for the other
    choice: a killed agent's uncommitted work cost 3h22m across five retries.
    """
    import subprocess
    repo = tmp_path / "repo"
    (repo / "port_runs").mkdir(parents=True)
    run = lambda *a: subprocess.run(["git", "-C", str(repo), *a], check=True,
                                    capture_output=True)
    run("init", "-q", "-b", "main")
    run("config", "user.email", "t@t"); run("config", "user.name", "t")
    (repo / "kept.txt").write_text("x")
    run("add", "kept.txt")
    run("commit", "-q", "-m", "c0")
    (repo / "brand_new_source.py").write_text("# nobody committed me")

    results = W.checks(str(repo), "wave2", elenchus=None,
                       instrument=str(repo), run_suites=False)
    untracked = [c for c in results if c.name.startswith("untracked:")]
    assert untracked, "untracked files are not reported at all"
    bad = [c for c in untracked if not c.ok]
    assert bad, "an untracked new source file passed silently"
    assert "brand_new_source.py" in bad[0].detail
    assert bad[0].carryable, "untracked must be nameable, not blocking"

    # The contrast: a genuinely clean tree must not be flagged, or the check is
    # permanently red and gets deleted.
    run("add", "brand_new_source.py")
    run("commit", "-q", "-m", "c1")
    clean = W.checks(str(repo), "wave2", elenchus=None,
                     instrument=str(repo), run_suites=False)
    assert all(c.ok for c in clean if c.name.startswith(("untracked:", "committed:")))


# ---------------------------------------------------------------------------
# brief — the same checks, fired without anyone asking
# ---------------------------------------------------------------------------

def test_brief_reports_a_RED_check_without_anyone_running_a_close(tmp_path, monkeypatch):
    """The whole point. Every one of these checks already existed and ran EXACTLY
    ONCE PER WAVE, inside a close a person had to remember. A kernel that drifted
    on day 2 was found on day 21."""
    monkeypatch.setattr(W, "checks", lambda *a, **k: [
        Check("verdicts", False, "19 gating builds lack a current, clean verdict"),
        Check("kernel", True, "v1.4.0 clean")])
    monkeypatch.setattr(W.promotions, "collect", lambda *a, **k: ([], {}, None))
    out = "\n".join(W.brief(ws(tmp_path, [opened("wave3")])))
    assert "RED  verdicts" in out and "19 gating" in out
    assert "kernel" not in out, "a green check must not spend a line"


def test_brief_is_QUIET_when_nothing_wants_attention(tmp_path, monkeypatch):
    """A digest that prints a wall of green on every session start is one people
    scroll past, at which point it is decoration that costs context."""
    monkeypatch.setattr(W, "checks", lambda *a, **k: [Check("verdicts", True, "all current")])
    monkeypatch.setattr(W.promotions, "collect", lambda *a, **k: ([], {}, None))
    out = W.brief(ws(tmp_path, [opened("wave3")]))
    assert len(out) == 1 and "wave3 is open" in out[0]


def test_brief_LEADS_with_what_is_waiting_on_a_person(tmp_path, monkeypatch):
    """The only item in the digest that a machine cannot clear by itself."""
    class Q:
        topic, reversals = "t", ["an observation that would settle it"]
    monkeypatch.setattr(W, "checks", lambda *a, **k: [Check("x", False, "red")])
    monkeypatch.setattr(W.promotions, "collect", lambda *a, **k: ([Q()], {}, None))
    monkeypatch.setattr(W.promotions, "unanswered", lambda qs, ans: qs)
    out = W.brief(ws(tmp_path, [opened("wave3")]))
    assert "1 decision(s) waiting on you" in out[1]
    assert "1 name the observation" in out[1]
    assert out.index([ln for ln in out if "waiting on you" in ln][0]) < \
        out.index([ln for ln in out if ln.startswith("RED")][0])


def test_brief_EXCLUDES_the_slow_and_the_close_only(tmp_path, monkeypatch):
    """It runs on every session start, so `bun test` (130s, measured) would make
    starting a session cost two minutes — and 'no --elenchus given' is true and
    uninteresting on every day that is not a closing day."""
    monkeypatch.setattr(W.promotions, "collect", lambda *a, **k: ([], {}, None))
    seen = {}

    def spy(*a, **k):
        seen.update(k)
        return [Check("elenchus", False, "no --elenchus given"),
                Check("suite:workspace", False, "red")]
    monkeypatch.setattr(W, "checks", spy)
    out = "\n".join(W.brief(ws(tmp_path, [opened("wave3")])))
    assert seen.get("run_suites") is False, "brief must never run the suites"
    assert "elenchus" not in out and "suite:workspace" not in out


def test_brief_says_NO_WAVE_IS_OPEN_rather_than_staying_silent(tmp_path, monkeypatch):
    """Layer 2 refuses probes outside an open wave. Someone about to work needs to
    know that before the refusal, not from it."""
    monkeypatch.setattr(W, "checks", lambda *a, **k: [])
    monkeypatch.setattr(W.promotions, "collect", lambda *a, **k: ([], {}, None))
    out = W.brief(ws(tmp_path, [opened("wave2"), closed("wave2")]))
    assert "none open" in out[0] and "wave2" in out[0]


def test_a_broken_decision_menu_does_not_take_the_brief_down(tmp_path, monkeypatch):
    """It runs on every session start. A digest that can abort session startup is
    worse than no digest, and it must SAY it failed rather than print nothing."""
    monkeypatch.setattr(W, "checks", lambda *a, **k: [])
    def boom(*a, **k):
        raise RuntimeError("DECIDED.jsonl:3 is unreadable")
    monkeypatch.setattr(W.promotions, "collect", boom)
    out = "\n".join(W.brief(ws(tmp_path, [opened("wave3")])))
    assert "could not read the decision menu" in out and "unreadable" in out


def test_an_affirmation_can_be_DECLINED_honestly(tmp_path, monkeypatch):
    """Or the ritual is a rubber stamp.

    The first version accepted only a name, so the only way to close a wave was
    to assert every affirmation was TRUE — which turns a question into a sentence
    you type to get past a prompt. Wave 2's honest answer to `kernel-frozen` was
    NO (v1.4's freeze agenda from wave 1 never landed; the version was still
    1.3.0), and a ritual that cannot record that manufactures false yeses at
    exactly the moment it matters.

    `kernel-frozen` is no longer an affirmation at all — it was a FACT on the
    human list and is now the `kernel` A-check — so this exercises the same
    mechanism through `pith-read`, which nothing can ever check. The history is
    kept in the docstring because it is the reason the decline path exists.
    """
    monkeypatch.setattr(W, "checks", green)
    affirm = dict(GOOD)
    affirm["pith-read"] = "no: the wave-2 Elenchus was produced but never read end to end"
    ok, msg, row = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm=affirm)
    assert ok, msg
    assert [d["what"] for d in row["declined"]] == ["pith-read"]
    assert "never read" in row["declined"][0]["reason"]
    # It must NOT appear as affirmed — that would be the lie the split prevents.
    assert "pith-read" not in {a["what"] for a in row["affirmed"]}
    assert len(row["affirmed"]) == len(AFFIRMATIONS) - 1
    assert "DECLINED" in msg


def test_a_DECLINED_affirmation_still_needs_a_reason(tmp_path, monkeypatch):
    """Saying no is fine. Saying nothing is not — otherwise 'no:' becomes the
    cheapest way past every question."""
    monkeypatch.setattr(W, "checks", green)
    affirm = dict(GOOD)
    affirm["pith-read"] = "no: nope"
    ok, msg, _ = close(ws(tmp_path, [opened("wave2")]), "wave2", at=AT, affirm=affirm)
    assert not ok and "STILL NEEDS A REASON" in msg


# ---------------------------------------------------------------------------
# the kernel — a FACT, computed, that used to be a question put to a person
# ---------------------------------------------------------------------------

def test_kernel_frozen_is_NOT_an_affirmation_anymore(tmp_path, monkeypatch):
    """It was a check parked on the human list, which is a toll with no
    epistemic value — the converse of enforceability.md disposition 3, and it
    cost the same. The first time it was asked the honest answer was no."""
    assert "kernel-frozen" not in AFFIRMATIONS
    # ...and closing must not secretly still demand it.
    monkeypatch.setattr(W, "checks", green)
    ok, msg, _ = close(ws(tmp_path, [opened("wave3")]), "wave3", at=AT, affirm=dict(GOOD))
    assert ok, msg


def _kstate(**over):
    base = {"version": "1.4.0", "fingerprint": "aaaa1111",
            "locked_fingerprint": "aaaa1111", "drift": "clean"}
    base.update(over)
    return base


def test_kernel_DRIFT_is_unsafe_and_cannot_be_carried(tmp_path, monkeypatch):
    """A gate edited without a version move. Carrying it would write a `kernel`
    field into WAVES.jsonl that does not describe the answers the wave's builds
    gave — the ledger would record a version claim that is false."""
    monkeypatch.setattr(W, "kernel_state", lambda *_a, **_k: _kstate(
        drift="drift", fingerprint="bbbb2222"))
    c = W._kernel_check(ws(tmp_path, [opened("wave3")]), "wave3", instrument=".")
    assert not c.ok and not c.carryable
    assert "DRIFT" in c.detail and "bump" in c.detail


def test_kernel_that_HELD_passes_with_no_human_input(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "kernel_state", lambda *_a, **_k: _kstate())
    row = opened("wave3")
    row["kernel"] = _kstate()
    c = W._kernel_check(ws(tmp_path, [row]), "wave3", instrument=".")
    assert c.ok and "held at v1.4.0" in c.detail


def test_a_kernel_BUMPED_MID_WAVE_passes_but_says_so(tmp_path, monkeypatch):
    """Legitimate — a decision can be re-bound mid-wave. But a reader of the
    ledger must not have to guess which kernel the wave's builds answered
    against, so both versions land in the detail."""
    monkeypatch.setattr(W, "kernel_state", lambda *_a, **_k: _kstate())
    row = opened("wave3")
    row["kernel"] = _kstate(version="1.3.0", fingerprint="0335ef15",
                            locked_fingerprint="0335ef15")
    c = W._kernel_check(ws(tmp_path, [row]), "wave3", instrument=".")
    assert c.ok
    assert "1.3.0" in c.detail and "1.4.0" in c.detail and "re-decided" in c.detail


def test_a_wave_whose_open_row_has_NO_kernel_cannot_claim_it_held(tmp_path, monkeypatch):
    """Cannot-tell is not a pass (hy6.25). Every wave opened before the open row
    recorded a kernel lands here, and must be carried BY NAME rather than
    silently reading as green."""
    monkeypatch.setattr(W, "kernel_state", lambda *_a, **_k: _kstate())
    c = W._kernel_check(ws(tmp_path, [opened("wave2")]), "wave2", instrument=".")
    assert not c.ok and c.carryable
    assert "cannot be told" in c.detail


def test_an_unreadable_kernel_is_not_a_pass(tmp_path, monkeypatch):
    monkeypatch.setattr(W, "kernel_state", lambda *_a, **_k: None)
    c = W._kernel_check(ws(tmp_path, [opened("wave3")]), "wave3", instrument=".")
    assert not c.ok and "no answer" in c.detail


def test_open_RECORDS_the_kernel_without_being_asked(tmp_path, monkeypatch):
    """The baseline the close is measured against. Without it, "did the kernel
    hold?" has nothing to compare to — which is why it used to be asked of a
    person instead of computed."""
    monkeypatch.setattr(W, "kernel_state", lambda *_a, **_k: _kstate())
    ok, _msg, row = open_(ws(tmp_path), "wave3", at=AT)
    assert ok
    assert row["kernel"]["version"] == "1.4.0"
    assert row["kernel"]["fingerprint"] == "aaaa1111"


def test_close_DERIVES_the_kernel_row_rather_than_accepting_a_claim(tmp_path, monkeypatch):
    """`--kernel "v1.4"` used to be free text on the command line: a version
    claim nobody checked, sitting in a ledger row, in a project whose commit log
    is its best instrument."""
    monkeypatch.setattr(W, "checks", green)
    monkeypatch.setattr(W, "kernel_state", lambda *_a, **_k: _kstate())
    ok, _msg, row = close(ws(tmp_path, [opened("wave3")]), "wave3", at=AT,
                          affirm=dict(GOOD))
    assert ok
    assert row["kernel"] == _kstate()
