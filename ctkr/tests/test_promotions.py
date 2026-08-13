#!/usr/bin/env python3
"""Regression evidence for ctkr/promotions.py — the menu a person actually reads.

    uv run --group dev pytest ctkr/tests/test_promotions.py

Instrument tier: this decides what reaches a person's attention, so every check
exercises the refusing/raising outcome AND its contrast. The failure mode with
teeth here is not a crash — it is a menu that reads as "all clear" when the truth
is "nobody was asked", which is the shape of this project's worst bugs.
"""

from __future__ import annotations

import json

import ctkr.promotions as P
import ctkr.wave as W
from ctkr.inflight import InflightRecord


def rec(agent, topic, assumption="", kind="punt", statement="s", event_kinds=()):
    return InflightRecord(agent=agent, feature="f", topic=topic, kind=kind,
                          statement=statement, assumption=assumption,
                          event_kinds=tuple(event_kinds), at="2026-08-06")


def dd(tmp_path, records):
    d = tmp_path / "dd" / "ctkr"
    d.mkdir(parents=True, exist_ok=True)
    (d / "inflight-decisions.jsonl").write_text(
        "".join(r.to_json() + "\n" for r in records))
    return str(tmp_path / "dd")


def ws(tmp_path, rows=()):
    d = tmp_path / "ws" / "port_runs"
    d.mkdir(parents=True, exist_ok=True)
    if rows:
        (d / "DECIDED.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows))
    return str(tmp_path / "ws")


# ---------------------------------------------------------------------------
# which questions reach a person at all
# ---------------------------------------------------------------------------

def test_one_builder_alone_is_NOT_raised():
    """One builder hitting a wall is a report. Two hitting it independently is a
    pattern. Raising the first floods the menu, and a flooded menu is unread."""
    qs = P.questions([rec("solo", "t", "guessed"), rec("solo", "t", "guessed")])
    assert qs == []


def test_two_builders_independently_IS_raised():
    """The contrast — otherwise the test above passes for a function that
    returns nothing at all."""
    qs = P.questions([rec("a", "t", "guessed"), rec("b", "t", "guessed")])
    assert [q.topic for q in qs] == ["t"]
    assert qs[0].builders == ["a", "b"]


# ---------------------------------------------------------------------------
# the derived fact — the reason this is worth rendering rather than listing
# ---------------------------------------------------------------------------

def test_builders_who_guessed_DIFFERENTLY_are_flagged_and_lead():
    """The port then holds two answers, already written, in two places. That is
    damage, not debt, and a reader must not have to spot it by comparing rows."""
    records = [
        rec("a", "agreed", "same guess"), rec("b", "agreed", "same guess"),
        rec("c", "agreed", "same guess"), rec("d", "agreed", "same guess"),
        rec("x", "clashed", "one way"), rec("y", "clashed", "the other way"),
    ]
    qs = P.questions(records)
    assert [q.topic for q in qs] == ["clashed", "agreed"], \
        "a disagreement outranks a question more builders hit the same way"
    assert qs[0].disagree and not qs[1].disagree


def test_agreement_is_not_reported_as_disagreement():
    q = P.questions([rec("a", "t", "same"), rec("b", "t", "same")])[0]
    assert not q.disagree


def test_a_builder_that_recorded_no_assumption_cannot_manufacture_agreement():
    """Silence is not a matching guess. Two builders, one of whom said nothing,
    must not read as "they agreed" — what the port does there is unknown."""
    q = P.questions([rec("a", "t", "one way"), rec("b", "t", "")])[0]
    assert q.guesses == [("a", "one way")]
    assert not q.disagree          # one known guess is not a clash...
    assert len(q.builders) == 2    # ...but the second builder is still counted


# ---------------------------------------------------------------------------
# answers
# ---------------------------------------------------------------------------

def test_LATER_brings_the_question_BACK(tmp_path):
    """That is the whole difference between 'later' and the other two. A defer
    that silently sticks is how debt accumulates unnoticed."""
    qs = P.questions([rec("a", "t", "g"), rec("b", "t", "g")])
    answers = P.read_answers(ws(tmp_path, [
        {"question": "t", "choice": "later", "why": "needs the oracle first",
         "by": "Duke", "at": "2026-08-13"}]))
    assert [q.topic for q in P.unanswered(qs, answers)] == ["t"]


def test_shared_and_per_build_settle_it(tmp_path):
    qs = P.questions([rec("a", "t", "g"), rec("b", "t", "g")])
    for choice in ("shared", "per-build"):
        answers = P.read_answers(ws(tmp_path / choice, [
            {"question": "t", "choice": choice, "why": "a real recorded reason",
             "by": "Duke", "at": "2026-08-13"}]))
        assert P.unanswered(qs, answers) == []


def test_an_answer_needs_a_reason_an_author_and_a_real_choice(tmp_path):
    w = ws(tmp_path)
    ok, msg, _ = P.record_answer(w, "t", "shared", "because", "Duke", "2026-08-13")
    assert not ok and "not a reason" in msg
    ok, msg, _ = P.record_answer(w, "t", "shared", "a genuinely stated reason here",
                                 "", "2026-08-13")
    assert not ok and "author" in msg
    ok, msg, _ = P.record_answer(w, "t", "maybe", "a genuinely stated reason here",
                                 "Duke", "2026-08-13")
    assert not ok and "shared" in msg
    ok, _msg, row = P.record_answer(w, "t", "shared", "a genuinely stated reason here",
                                    "Duke", "2026-08-13")
    assert ok and row["choice"] == "shared" and row["by"] == "Duke"


def test_re_deciding_is_a_NEW_ROW_and_the_last_one_wins(tmp_path):
    w = ws(tmp_path)
    P.append(w, {"question": "t", "choice": "later", "why": "w", "by": "D", "at": "1"})
    P.append(w, {"question": "t", "choice": "shared", "why": "w", "by": "D", "at": "2"})
    assert P.read_answers(w)["t"]["choice"] == "shared"
    assert open(P.ledger_file(w)).read().count('"question"') == 2, \
        "the history of what we decided is the point; a re-decision is not an edit"


# ---------------------------------------------------------------------------
# the rendering — the requirement was that a person can read it
# ---------------------------------------------------------------------------

JARGON = ["punt", "promotion", "kernel", "blast radius", "elicitation",
          "elenchus", "pith", "ratchet", "carry-forward", "adjudicat"]


def test_the_menu_uses_NO_project_vocabulary(tmp_path):
    """The actual requirement. Duke, 2026-08-13: "what decisions are being asked
    without referencing all our special terms." A question phrased in words only
    the machine understands is one the person it is addressed to will not answer.
    """
    qs, answers, read = P.collect(
        dd(tmp_path, [rec("a", "how to tell two animals apart", "used a counter",
                          event_kinds=["animal_born"]),
                      rec("b", "how to tell two animals apart", "used a random id")]),
        ws(tmp_path))
    out = P.render(qs, answers, read, dd(tmp_path, [])).lower()
    # An empty menu contains no jargon either. Prove there is a menu to inspect.
    assert "## 1." in out and "your choice" in out
    for word in JARGON:
        assert word not in out, f"{word!r} leaked into the menu a person reads"


def test_the_menu_LEADS_with_the_disagreement(tmp_path):
    qs, answers, read = P.collect(
        dd(tmp_path, [rec("a", "t", "one way"), rec("b", "t", "the other way")]),
        ws(tmp_path))
    out = P.render(qs, answers, read, "")
    assert "disagreed" in out
    assert "one way" in out and "the other way" in out
    assert out.index("DIFFERENTLY") < out.index("## 1."), \
        "the fact most likely to change the decision must precede the list"


def test_an_EMPTY_menu_says_which_kind_of_empty_it_is(tmp_path):
    """The failure this project keeps paying for: absence of an answer read as an
    answer. The oracle's 200-with-`data: []` meant "you are anonymous", not "no
    records" (CLAUDE.md, 4ifi). A menu that renders "none" without saying the log
    was never written is the same bug wearing different clothes.
    """
    missing = str(tmp_path / "no-such-dir")
    qs, answers, read = P.collect(missing, ws(tmp_path))
    out = P.render(qs, answers, read, missing)
    assert "not the same as" in out and "does not exist" in out
    assert "nobody reported a question" in out

    # The contrast: a log that EXISTS and holds sub-threshold reports is a
    # different sentence, and must not claim nobody ever wrote to the channel.
    d = dd(tmp_path, [rec("solo", "t", "g")])
    qs2, answers2, read2 = P.collect(d, ws(tmp_path))
    out2 = P.render(qs2, answers2, read2, d)
    assert "does not exist" not in out2
    assert "1 report" in out2


def test_answered_questions_stay_visible_but_out_of_the_way(tmp_path):
    d = dd(tmp_path, [rec("a", "t", "g"), rec("b", "t", "g")])
    w = ws(tmp_path, [{"question": "t", "choice": "shared", "why": "the reason given",
                       "by": "Duke", "at": "2026-08-13"}])
    qs, answers, read = P.collect(d, w)
    out = P.render(qs, answers, read, d)
    assert "waiting for you — 0" in out or "Already decided (1)" in out
    assert "the reason given" in out and "Duke" in out


# ---------------------------------------------------------------------------
# the wave-close check
# ---------------------------------------------------------------------------

def test_unanswered_questions_BLOCK_a_close_but_can_be_carried(tmp_path):
    """Carryable, never unsafe: deciding is judgment, and a wave that cannot
    close until every question is settled never closes. What it refuses is the
    third state — unanswered AND unmentioned."""
    c = W._decisions_check(ws(tmp_path), dd(tmp_path, [rec("a", "t", "g"),
                                                       rec("b", "t", "g")]))
    assert not c.ok and c.carryable
    assert "t" in c.detail and "elicit" in c.detail


def test_a_MISSING_log_is_not_a_pass(tmp_path):
    c = W._decisions_check(ws(tmp_path), str(tmp_path / "nowhere"))
    assert not c.ok
    assert "NOT 'nobody had one'" in c.detail


def test_an_answered_wave_closes_clean(tmp_path):
    d = dd(tmp_path, [rec("a", "t", "g"), rec("b", "t", "g")])
    w = ws(tmp_path, [{"question": "t", "choice": "shared", "why": "a stated reason",
                       "by": "Duke", "at": "2026-08-13"}])
    c = W._decisions_check(w, d)
    assert c.ok and "all answered" in c.detail


def test_a_log_with_only_sub_threshold_reports_closes_clean_and_says_so(tmp_path):
    c = W._decisions_check(ws(tmp_path), dd(tmp_path, [rec("solo", "t", "g")]))
    assert c.ok
    assert "1 builder report" in c.detail, \
        "green because nothing qualified is not the same as green because the " \
        "channel was silent, and the detail must say which"
