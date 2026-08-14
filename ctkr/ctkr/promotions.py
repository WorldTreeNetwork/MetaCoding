#!/usr/bin/env python3
"""The questions builders ran into and could not answer — put to a person, in English.

    python3 ctkr/ctkr/wave.py elicit
    python3 ctkr/ctkr/wave.py decide "<the question>" --choice shared --why "..." --at DATE

WHY THIS EXISTS. `inflight.promotion_candidates` has computed this list since
2026-07-20 and nothing has ever shown it to anybody. `wave close` asked instead
for an affirmation — "the elicitation menu was answered and the decisions bound"
— which is a person promising they read something no command ever printed.

AND IT READ THE WRONG CHANNEL FOR ITS FIRST DAY (fixed 2026-08-13, same day it
shipped). The first version asked `inflight-decisions.jsonl` for topics that two
or more agents had collided on. Both halves were wrong against the real corpus:
that file has never been written, and across the 22 `punts.jsonl` ledgers that
builders DO fill, all 76 topics are distinct — builders write topics as free
prose, and free prose does not collide, so a threshold of 2 returns nothing
forever. Meanwhile 21 rows sat flagged `kernel_candidate: true`, unresolved,
11 of them since wave 1: the builders' own judgment that something wanted
deciding once, made while they had the problem in front of them, in a field
nothing read.

The menu was empty by MISREAD, not by absence — and a fresh judge, given the
whole corpus, concluded the signal did not exist because the threshold found
nothing. Both the builder and the auditor read a zero as an answer. The lesson is
the project's own and it keeps arriving in new clothes: when a mechanism reports
nothing, prove it looked in the place the data actually is.

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


class Raised:
    """One thing one builder could not settle, normalized across both channels.

    TWO CHANNELS, because a fresh judge found the first version reading the empty
    one (2026-08-13). `promotion_candidates` counted distinct agents colliding on
    a shared `topic` slug in `inflight-decisions.jsonl` — a file that has NEVER
    BEEN WRITTEN in the three weeks since it shipped. Meanwhile builders were
    filling `punts.jsonl` reliably (81 rows across 22 files) and flagging what
    needed deciding once, for everyone, in a field nothing read:
    `kernel_candidate: true`. 21 of those are unresolved, 11 since wave 1.

    So the menu was empty by MISREAD, not by absence — the classic shape here,
    and it survived a judge that concluded the signal did not exist because the
    threshold found nothing. Follow the data: the flag a builder actually sets is
    the signal, and the agent-collision count is kept as a second route in case
    the in-flight channel ever gets used.
    """

    def __init__(self, *, builder, feature, topic, statement="", assumption="",
                 reversal="", evidence="", flagged=False, event_kinds=()):
        self.builder = builder
        self.feature = feature
        self.topic = topic
        self.statement = statement
        self.assumption = assumption
        self.reversal = reversal
        self.evidence = evidence
        #: the builder itself said this needs deciding once, for everyone.
        self.flagged = flagged
        self.event_kinds = tuple(event_kinds)


def from_inflight(records):
    """In-flight reports -> Raised. Nothing has ever written this channel, but it
    is the one wired into every port brief, so it stays readable."""
    return [Raised(builder=r.agent, feature=r.feature, topic=r.topic,
                   statement=r.statement, assumption=r.assumption,
                   event_kinds=r.event_kinds)
            for r in records]


def read_punts(workspace):
    """Every `punts.jsonl` under the workspace -> Raised.

    A RESOLVED row is not raised any more; it was settled and says so.
    """
    out = []
    root = os.path.join(workspace, "port_runs")
    if not os.path.isdir(root):
        return out
    for base, _dirs, files in os.walk(root):
        if "punts.jsonl" not in files:
            continue
        path = os.path.join(base, "punts.jsonl")
        for line in open(path):
            line = line.strip()
            if not line or line.startswith("//"):
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue        # a malformed punt row is reported by `elicit`
            if str(r.get("status") or "").upper().startswith("RESOLVED"):
                continue
            topic = (r.get("topic") or r.get("id") or "").strip()
            if not topic:
                continue
            out.append(Raised(
                builder=(r.get("id") or os.path.basename(base)),
                feature=r.get("feature", ""),
                topic=topic,
                statement=r.get("why") or r.get("what") or "",
                # `decision_taken` IS the assumption: what shipped in the
                # meantime. Same field, the builders' name for it.
                assumption=r.get("decision_taken") or r.get("punt") or "",
                reversal=r.get("reversal_condition") or "",
                evidence=r.get("evidence") or "",
                flagged=bool(r.get("kernel_candidate")),
            ))
    return out


class Question:
    """One thing builders could not answer, in a shape a person reads."""

    def __init__(self, topic, records):
        self.topic = topic
        self.records = records

    @property
    def flagged(self):
        """A builder said out loud that this wants deciding once, for everyone."""
        return any(r.flagged for r in self.records)

    @property
    def builders(self):
        return sorted({r.builder for r in self.records})

    @property
    def reversals(self):
        """What would overturn the guess. The builders fill this 13/21 times and
        it is the single most decision-useful field in the corpus: it says what
        evidence would settle the question without anyone having to rule."""
        return sorted({r.reversal.strip() for r in self.records if r.reversal.strip()})

    @property
    def evidence(self):
        return sorted({r.evidence.strip() for r in self.records if r.evidence.strip()})

    @property
    def features(self):
        return sorted({r.feature.strip() for r in self.records if r.feature.strip()})

    @property
    def guesses(self):
        """(builder, what they assumed) for everyone who said what they did."""
        return sorted({(r.builder, r.assumption.strip())
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


def questions(raised, threshold=DEFAULT_THRESHOLD):
    """The questions worth putting to a person.

    TWO ROUTES ONTO THE MENU, and the union is deliberate:

      * **a builder flagged it** (`kernel_candidate`). One builder saying "this
        should be decided once, for everyone" is a signal on its own — it is a
        judgment about scope, not a tally.
      * **two or more builders hit the same question independently**, which is a
        pattern even when nobody flagged it.

    The first route is the one with data. Across 22 punt ledgers every one of 76
    topics is DISTINCT, so a threshold of 2 alone returns nothing forever: builders
    write topics as free prose and free prose does not collide. Requiring a
    collision was the bug.
    """
    groups = {}
    for r in raised:
        groups.setdefault(r.topic, []).append(r)
    out = []
    for topic, rs in sorted(groups.items()):
        q = Question(topic, rs)
        if q.flagged or len({r.builder for r in rs}) >= threshold:
            out.append(q)
    # Disagreements first — two builders who answered differently is damage, not
    # debt. Then questions more builders hit, then flagged ones.
    out.sort(key=lambda q: (not q.disagree, -len(q.builders), not q.flagged, q.topic))
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

def render(qs, answers, ledger_read, data_dir, workspace=None):
    lines = []
    open_qs = unanswered(qs, answers)

    if not qs:
        # ABSENCE OF A REPORT IS NOT A REPORT OF ABSENCE. The oracle taught this
        # project the same lesson with a 200 and an empty list (CLAUDE.md, 4ifi):
        # a reader who does not look at WHY it is empty concludes "no questions"
        # when the truth is "nobody was asked". Say which one this is.
        path = inflight.ledger_path(data_dir)
        n_punts = len(read_punts(workspace)) if workspace else None
        lines += ["# Decisions waiting for you — none", ""]
        lines += [
            "**Check that this is not the reader's fault before believing it.** "
            "This menu said 'none' for a day while 21 questions builders had "
            "flagged sat in their own records — it was counting collisions in a "
            "file nobody writes. Two places are read; here is what each held:",
            "",
            "  - build records (`punts.jsonl` under `port_runs/`): "
            + ("workspace not given, NOT READ" if n_punts is None
               else f"{n_punts} unsettled row(s), none flagged or repeated"),
            f"  - the in-flight log (`{path}`): "
            + (f"{len(ledger_read.records)} report(s)" if os.path.isfile(path)
               else "does not exist — nothing has ever written it"),
            "",
            "If both are genuinely empty, that says *nobody reported a question*, "
            "not *nobody had one*. Only one of those is good news, and nothing "
            "here can tell you which it is.",
        ]
        return "\n".join(lines) + "\n"

    disagreements = [q for q in open_qs if q.disagree]
    lines += [f"# Decisions waiting for you — {len(open_qs)}", ""]
    flagged = [q for q in open_qs if q.flagged]
    lines += [
        "These came up while the port was being built. In each one a builder "
        "needed an answer, did not have one, and shipped something anyway. "
        "**Whatever they picked is what the port does today** — deciding here "
        "either confirms that or changes it.",
        "",
    ]
    if flagged:
        lines += [
            f"**{len(flagged)} of them the builder explicitly flagged as needing to "
            f"be decided once, for everyone** rather than separately in each build. "
            f"That is the builder's own judgment about scope, made while it had the "
            f"problem in front of it.",
            "",
        ]
    lines += [
        "Many carry a **what would change this** line — the observation that would "
        "settle the question without anyone having to rule on it. Where one is "
        "present, going and looking is usually cheaper than deciding.",
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
        if q.flagged:
            lines += ["> The builder flagged this one as needing a single answer "
                      "everyone follows, not a per-build call.", ""]
        who_line = (f"**{len(q.builders)} builders** ran into it: "
                    if len(q.builders) > 1 else "**Raised by** ")
        lines += [who_line + ", ".join(f"`{b}`" for b in q.builders)
                  + (f"  ·  in {', '.join(q.features)}" if q.features else ""), ""]
        if q.guesses:
            label = ("**What each did instead:**" if len(q.guesses) > 1
                     else "**What it did instead, and what the port does today:**")
            lines += [label, ""]
            for who, guess in q.guesses:
                lines += [f"  - {guess}" if len(q.guesses) == 1
                          else f"  - `{who}` — {guess}"]
            lines += [""]
        else:
            lines += ["Nobody recorded what they did in the meantime, so what the "
                      "port currently does here is unknown.", ""]
        for rev in q.reversals:
            lines += [f"**What would change this:** {rev}", ""]
        for ev in q.evidence:
            lines += [f"**What was measured:** {ev}", ""]
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


def declarations(workspace, records, wave=None):
    """What each finished build said about the questions it hit.

    Three states, kept apart because they have different authority — the same
    split the wave close makes between a check, an affirmation, and a silence:

      * **declared** — `questions.raised` names them, or `none_because` says why
        nothing came up. Either is a claim with an author.
      * **silent** — no `questions` block at all. The build never said. Every
        manifest sealed before 2026-08-13 is here, and that is the honest record:
        retro-filling them would manufacture a claim nobody made.
      * **unreported** — the manifest names a question with NO in-flight record
        behind it. The builder knew, and said so only after the wave had already
        built on the guess. That is the failure `inflight.py` was written to
        prevent, and it is invisible without this cross-check.

    Returns (declared, silent, unreported) as lists of (build_label, detail),
    where the label is the path under `port_runs/`. NOT the containing directory
    name: half of these builds live in `<feature>/build/`, so a basename labels
    five different builds "build" and the reader cannot tell which to go fix.
    """
    root = os.path.join(workspace, "port_runs", wave) if wave else \
        os.path.join(workspace, "port_runs")
    reported = {r.topic for r in records}
    declared, silent, unreported = [], [], []
    if not os.path.isdir(root):
        return declared, silent, unreported
    for base, _dirs, files in os.walk(root):
        if "port.manifest.json" not in files:
            continue
        path = os.path.join(base, "port.manifest.json")
        label = os.path.relpath(base, os.path.join(workspace, "port_runs"))
        try:
            raw = json.load(open(path))
        except (OSError, ValueError) as exc:
            silent.append((label, f"unreadable ({exc})"))
            continue
        q = raw.get("questions")
        if q is None:
            silent.append((label, "no `questions` block — this build never said "
                                  "whether it had to guess at anything"))
            continue
        raised = [s for s in (q.get("raised") or []) if str(s).strip()]
        declared.append((label, f"{len(raised)} question(s)" if raised else
                                f"none: {q.get('none_because', '')}"))
        for topic in raised:
            if topic not in reported:
                unreported.append((label, topic))
    return declared, silent, unreported


def collect(data_dir, workspace, threshold=DEFAULT_THRESHOLD):
    """(questions, answers, raw read) — everything the menu and the check need.

    Reads BOTH channels. `punts.jsonl` is where the data actually is; the
    in-flight ledger is what every port brief tells builders to write and has
    never been written. Reading only the second is how this menu rendered "none"
    while 21 flagged questions sat unread, 11 of them since wave 1.
    """
    read = inflight.read(data_dir)
    raised = read_punts(workspace) + from_inflight(read.records)
    return questions(raised, threshold), read_answers(workspace), read
