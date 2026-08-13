#!/usr/bin/env python3
"""The questions builders ran into and could not answer — put to a person, in English.

    python3 ctkr/ctkr/wave.py elicit
    python3 ctkr/ctkr/wave.py decide "<the question>" --choice shared --why "..." --at DATE

WHY THIS EXISTS. `inflight.promotion_candidates` has computed this list since
2026-07-20 and nothing has ever shown it to anybody. `wave close` asked instead
for an affirmation — "the elicitation menu was answered and the decisions bound"
— which is a person promising they read something no command ever printed.

WHY IT IS WRITTEN IN PLAIN WORDS, which is the actual requirement. Duke,
2026-08-13: *"It should be really clear. To me, or the person running this
process, what is being elicited, what decisions are being asked without
referencing all our special terms."*

The vocabulary this project uses among its own parts — punt, promotion, kernel,
wave, blast radius, elicitation, binding, pith — is precise and it is load-bearing
in the code. It is also unreadable to the person whose judgment is the entire
point of asking, and a question nobody can read is a question nobody answers. So
the mapping is done HERE, once, at the boundary where a machine hands work to a
human:

    a punt                 -> a builder had no answer and guessed
    the topic              -> the question
    the kernel             -> the rules every builder follows
    promotion              -> decide it once, for everyone
    the assumption         -> what they did instead, in the meantime
    N distinct agents      -> how many builders hit it independently
    blast radius           -> how much of the port it touches

Nothing here invents information. Every line is a field of a record some builder
wrote, or a count of them. The one DERIVED fact is the one worth deriving: when
two builders guessed DIFFERENTLY at the same question, the port already contains
two different answers, and that is the fact most likely to change what a person
decides. It leads.
"""

from __future__ import annotations

import json
import os

from ctkr import inflight

#: Distinct builders who must have hit a question before it is put to a person.
#: Distinct BUILDERS, not distinct reports: one builder hitting the same wall
#: five times is one signal; two builders hitting it independently is a pattern.
DEFAULT_THRESHOLD = 2

#: The three answers, named so a reader knows what each one costs. These are the
#: user-facing words; nothing downstream should introduce a fourth.
CHOICES = {
    "shared": "decide it once, and every builder follows the same rule from here",
    "per-build": "leave it to each builder, accepting that their answers differ",
    "later": "not now; it comes back next round, with the reason recorded",
}

MIN_REASON_WORDS = 4


def ledger_file(workspace):
    """Where answers are recorded. Append-only, beside the other ledgers."""
    return os.path.join(workspace, "port_runs", "DECIDED.jsonl")


class Question:
    """One thing several builders could not answer, in a shape a person reads."""

    def __init__(self, topic, records):
        self.topic = topic
        self.records = records

    @property
    def builders(self):
        return sorted({r.agent for r in self.records})

    @property
    def guesses(self):
        """(builder, what they assumed) for everyone who said what they did."""
        return sorted({(r.agent, r.assumption.strip())
                       for r in self.records if r.assumption.strip()})

    @property
    def disagree(self):
        """Did builders guess DIFFERENTLY? The derived fact that leads the entry.

        If they did, the port does not contain an open question — it contains two
        answers, already shipped, in two places. That is a different and worse
        situation than nobody having decided yet, and a reader must not have to
        notice it by comparing rows.
        """
        return len({g for _, g in self.guesses}) > 1

    @property
    def statement(self):
        for r in self.records:
            if r.statement.strip():
                return r.statement.strip()
        return ""

    @property
    def touches(self):
        out = set()
        for r in self.records:
            out.update(r.event_kinds)
        return sorted(out)


def questions(records, threshold=DEFAULT_THRESHOLD):
    """The questions worth putting to a person, most-builders-first."""
    out = [Question(topic, rs)
           for topic, rs in inflight.promotion_candidates(records, threshold)]
    # Disagreements first, then by how many builders hit it. A question two
    # builders answered differently outranks one four builders all punted on the
    # same way: the first is damage, the second is only debt.
    out.sort(key=lambda q: (not q.disagree, -len(q.builders), q.topic))
    return out


def read_answers(workspace):
    """The latest answer per question. Append-only file, last row wins."""
    path = ledger_file(workspace)
    out = {}
    if not os.path.isfile(path):
        return out
    for n, line in enumerate(open(path), 1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise RuntimeError(
                f"DECIDED.jsonl:{n} is unreadable ({exc}). This file records what "
                f"was decided; a row nobody can parse is not a row to skip.") from None
        if row.get("question"):
            out[row["question"]] = row
    return out


def unanswered(qs, answers):
    """Questions with no recorded answer — including ones answered 'later' in a
    previous round, which is the point of 'later': it comes BACK."""
    return [q for q in qs
            if answers.get(q.topic, {}).get("choice") in (None, "later")]


def record_answer(workspace, question, choice, why, by, at):
    """Returns (ok, message, row). Writes nothing — the caller appends."""
    if choice not in CHOICES:
        return False, (f"{choice!r} is not one of: " +
                       ", ".join(f"{k} ({v})" for k, v in CHOICES.items())), None
    if len((why or "").split()) < MIN_REASON_WORDS:
        return False, (f"a reason under {MIN_REASON_WORDS} words is not a reason. "
                       f"This is the record of why the port works the way it does; "
                       f"say why in a sentence."), None
    if not (by or "").strip():
        return False, "--by is required: a decision has an author.", None
    return True, f"recorded: {question} -> {choice}", {
        "question": question, "choice": choice, "why": why.strip(),
        "by": by.strip(), "at": at,
    }


def append(workspace, row):
    path = ledger_file(workspace)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.isfile(path)
    with open(path, "a") as fh:
        if new:
            fh.write("// DECIDED.jsonl — append-only. What was decided about the "
                     "questions builders could not answer, and why. Re-deciding is "
                     "a new row, never an edit.\n")
        fh.write(json.dumps(row) + "\n")
    return path


# ---------------------------------------------------------------------------
# rendering — the whole point, and the only place project vocabulary is banned
# ---------------------------------------------------------------------------

def render(qs, answers, ledger_read, data_dir):
    lines = []
    open_qs = unanswered(qs, answers)

    if not qs:
        # ABSENCE OF A REPORT IS NOT A REPORT OF ABSENCE. The oracle taught this
        # project the same lesson with a 200 and an empty list (CLAUDE.md, 4ifi):
        # a reader who does not look at WHY it is empty concludes "no questions"
        # when the truth is "nobody was asked". Say which one this is.
        path = inflight.ledger_path(data_dir)
        found = os.path.isfile(path)
        lines += ["# Decisions waiting for you — none", ""]
        if not found:
            lines += [
                "**And that is not the same as 'nothing came up.'** No builder has "
                "ever written to the log this reads:",
                "",
                f"    {path}   (does not exist)",
                "",
                "So this says *nobody reported a question*, not *nobody had one*. "
                "Only one of those is good news, and nothing here can tell you "
                "which it is.",
            ]
        else:
            n = len(ledger_read.records)
            lines += [
                f"The builders' log exists and holds {n} report(s), but no question "
                f"was hit independently by {DEFAULT_THRESHOLD} or more builders. "
                f"One builder guessing alone is recorded there and is not raised "
                f"here.",
                "", f"    {path}",
            ]
        return "\n".join(lines) + "\n"

    disagreements = [q for q in open_qs if q.disagree]
    lines += [f"# Decisions waiting for you — {len(open_qs)}", ""]
    lines += [
        "These are questions that came up while the port was being built. In each "
        "one, a builder needed an answer, did not have one, and carried on with a "
        "guess. They are here because **more than one builder hit the same "
        "question independently** — which is the sign that it needs deciding once "
        "rather than over and over.",
        "",
    ]
    if disagreements:
        lines += [
            ("**One of them was guessed at DIFFERENTLY by different builders.**"
             if len(disagreements) == 1 else
             f"**{len(disagreements)} of them were guessed at DIFFERENTLY by "
             f"different builders.**")
            + " For those, the port does not hold an open question — it holds two "
              "different answers, already written, in different places. Those are "
              "listed first.",
            "",
        ]

    for i, q in enumerate(open_qs, 1):
        lines += ["---", "", f"## {i}. {q.topic}", ""]
        if q.statement:
            lines += [f"{q.statement}", ""]
        if q.disagree:
            lines += ["> **The builders disagreed.** They did not just skip this — "
                      "they answered it, differently, and both answers shipped.", ""]
        lines += [f"**{len(q.builders)} builders** ran into it: "
                  + ", ".join(q.builders), ""]
        if q.guesses:
            lines += ["**What each did instead, having no answer:**", ""]
            for who, guess in q.guesses:
                lines += [f"  - `{who}` — {guess}"]
            lines += [""]
        else:
            lines += ["None of them recorded what they did in the meantime, so "
                      "what the port currently does here is unknown.", ""]
        if q.touches:
            lines += [f"**Touches:** {', '.join(q.touches)}", ""]
        prior = answers.get(q.topic)
        if prior and prior.get("choice") == "later":
            lines += [f"**Deferred once already** ({prior.get('at','?')}, "
                      f"{prior.get('by','?')}): {prior.get('why','')}", ""]
        lines += ["**Your choice:**", ""]
        for name, meaning in CHOICES.items():
            lines += [f"  - **{name}** — {meaning}"]
        lines += [
            "",
            "```",
            f'python3 ctkr/ctkr/wave.py decide "{q.topic}" \\',
            '    --choice shared --by YOU --at DATE --why "..."',
            "```",
            "",
        ]

    answered = [q for q in qs if q not in open_qs]
    if answered:
        lines += ["---", "", f"## Already decided ({len(answered)})", ""]
        for q in answered:
            a = answers[q.topic]
            lines += [f"  - **{q.topic}** → `{a['choice']}` "
                      f"({a.get('by','?')}, {a.get('at','?')}) — {a.get('why','')}"]
        lines += [""]
    return "\n".join(lines) + "\n"


def collect(data_dir, workspace, threshold=DEFAULT_THRESHOLD):
    """(questions, answers, raw read) — everything the menu and the check need."""
    read = inflight.read(data_dir)
    return questions(read.records, threshold), read_answers(workspace), read
