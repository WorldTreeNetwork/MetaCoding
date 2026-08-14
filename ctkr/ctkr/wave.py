#!/usr/bin/env python3
"""The wave transition — a ritual that does not depend on remembering it.

    python3 ctkr/ctkr/wave.py status
    python3 ctkr/ctkr/wave.py elicit                      # what needs deciding, in English
    python3 ctkr/ctkr/wave.py decide "<question>" --choice shared --by X --at D --why "..."
    python3 ctkr/ctkr/wave.py close wave2 --elenchus <path> --affirm k=who --carry id="reason"
    python3 ctkr/ctkr/wave.py open  wave3 [--force "reason"]

WHY THIS EXISTS — docs/design/wave-transition.md
================================================
Three mechanisms were built to gate wave-close sealing — `elenchus
--require-current`, `verdict_currency`, and recipe step 8. **None of them ever
ran, because there was no wave-close step in code.** Sealing was a human act with
no call site, so every gate hung on it was hung on nothing. Duke, 2026-08-12:
*"Sealing is an action that relies on my fallible memory to perform."*

Adding a command creates the call site. It does not by itself solve the problem —
a command you must remember to type is exactly as reliable as the memory it
depends on. The move that does solve it is layer 2: **make the next thing you want
refuse until the last thing is closed.** You cannot forget to close wave N if
opening wave N+1 refuses while N is open, and `ledger.py` refuses to probe in a
wave that is not open. That converts the ritual from memory-dependent to
path-dependent, which `enforceability.md` measured as the only kind that has ever
worked here.

THREE KINDS OF CLOSING CONDITION, KEPT APART ON PURPOSE
=======================================================
Conflating them is how a ritual becomes a rubber stamp.

  A — MECHANICAL. This command checks, and can refuse. Below in `checks()`.
  B — HUMAN. It ASKS, records the answer, and CANNOT verify it. An affirmation
      that looks like a check is worse than an honest question
      (enforceability.md, disposition 3), so these are stored with a name
      against them and never rendered as if they were measured.
  C — CARRY-FORWARD. Recorded, never blocking, each with a reason. This list
      becomes the next wave's ratchet baseline, which is the unification worth
      having: debt accepted deliberately at a boundary, by a person, once —
      instead of accumulating silently and being found by a judge three weeks on.

TWO PROPERTIES OR IT WILL NOT BE USED
=====================================
**Closing must be cheap when nothing is wrong.** If a clean close is expensive it
gets skipped precisely when things are going well, which is most of the time.

**It must be possible to close a wave WITH DEBT.** A ritual that only succeeds
when everything is perfect never succeeds. Refusal is reserved for UNSAFE, not
UNFINISHED: sealing uncommitted work, or carrying an item with no reason. "Not
done" is a legitimate close with a recorded carry-forward; "not done and nobody
said so" is not.

HOW THIS CAN BE FAKED, said out loud
====================================
- **Edit WAVES.jsonl by hand.** Trivially possible. It is a ledger, not a lock —
  same status as PACKS.jsonl, same defence: it is reviewed history and a
  hand-edited row shows up in the diff.
- **Carry everything forward with the reason "known".** The reason field is only
  as good as the review of the commit that adds it. This is the real weakness and
  the command says so in its own output rather than pretending otherwise.
- **Never open a wave at all**, dodging layer 2 entirely.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctkr import inflight, promotions  # noqa: E402
from ctkr.elenchus import port_workspace  # noqa: E402

#: The B-list. Each must be affirmed BY NAME to close. These are questions, not
#: checks — nothing here can verify them, and the moment one looks verified it
#: has become a rubber stamp.
#:
#: `kernel-frozen` WAS HERE AND WAS MISFILED (removed 2026-08-13). It asked a
#: person to attest to something the kernel's own fingerprint has been able to
#: compute since `version.ts` was written — and the first time it was asked, the
#: honest answer was no. Disposition 3 of enforceability.md says an affirmation
#: that looks like a check is worse than an honest question; the converse was
#: never written down and cost the same: **a check parked on the human list is a
#: toll with no epistemic value.** It is now the `kernel` A-check below.
#:
#: What genuinely was Duke's in that question survives, and it is not a yes/no:
#: *should* the kernel now change — which punts recurred often enough to promote
#: into the shared substrate. That is an intention, it belongs on the elicitation
#: menu next to the candidates that motivate it (`inflight.by_topic` is the
#: punt-promotion input, `decisions.render_menu` renders it), and it reaches a
#: person as ranked candidates or not at all. Duke, 2026-08-13: *"I'm focusing on
#: guiding the intention. The mechanism should be something that is managed
#: automatically."*
AFFIRMATIONS = {
    "elicitation-answered": "the wave's elicitation menu was answered and the decisions bound",
    "pith-read": "the Elenchus's pith was READ, not merely produced",
}

#: A reason shorter than this is not a reason. The friction is the point: the cost
#: of carrying debt should be stating why, and that cost should land on the person
#: carrying it rather than on the next reader.
MIN_REASON_WORDS = 4


@dataclass
class Check:
    name: str
    ok: bool
    detail: str
    carryable: bool = True   # False = UNSAFE, cannot be carried, refuses outright


@dataclass
class Wave:
    name: str
    opened_at: str = ""
    closed_at: str = ""
    rows: list = field(default_factory=list)

    @property
    def is_open(self):
        return bool(self.opened_at) and not self.closed_at


def ledger_path(workspace):
    return os.path.join(workspace, "port_runs", "WAVES.jsonl")


def load_waves(workspace):
    """Every wave, folded from the append-only ledger, in first-seen order.

    Append-only matters: a wave closed with debt and later re-opened is TWO rows,
    not an edit. The history of what we accepted is the point.
    """
    waves, order = {}, []
    path = ledger_path(workspace)
    if not os.path.isfile(path):
        return waves, order
    for n, line in enumerate(open(path), 1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            raise RuntimeError(f"WAVES.jsonl:{n} is unreadable ({exc}). This ledger "
                               f"decides what is open; a row nobody can parse is not "
                               f"a row that can be ignored.") from None
        name = row.get("wave")
        if not name:
            continue
        if name not in waves:
            waves[name] = Wave(name=name)
            order.append(name)
        w = waves[name]
        w.rows.append(row)
        if row.get("record") == "open":
            w.opened_at = row.get("opened_at", "")
            w.closed_at = ""          # re-opening clears the close
        elif row.get("record") == "close":
            w.closed_at = row.get("closed_at", "")
    return waves, order


def open_waves(workspace):
    waves, order = load_waves(workspace)
    return [waves[n] for n in order if waves[n].is_open]


# ---------------------------------------------------------------------------
# A — the mechanical checks. Each may refuse.
# ---------------------------------------------------------------------------

def _git_dirty(repo):
    """(tracked-but-modified, untracked) — or None if git could not answer.

    THEY ARE SEPARATED, and the separation was earned. The first version filtered
    `??` away entirely, and on this ritual's very first dry run it sealed cleanly
    while `wave.py` — the file implementing the ritual — sat untracked in the tree.
    Untracked SOURCE is uncommitted work; untracked build noise (`index.*.scip`)
    is not, and no rule can tell them apart. So modified files are UNSAFE and
    refuse outright, while untracked files are CARRYABLE: they cannot block a
    close, but they cannot pass unmentioned either. This project has already paid
    for the other choice — a killed agent's uncommitted work cost 3h22m and ~1.77M
    tokens across five retries.
    """
    if not os.path.isdir(os.path.join(repo, ".git")):
        return None
    out = subprocess.run(["git", "-C", repo, "status", "--porcelain"],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        return None
    lines = [l for l in out.stdout.splitlines() if l.strip()]
    return ([l for l in lines if not l.startswith("??")],
            [l for l in lines if l.startswith("??")])


def kernel_state(instrument):
    """What kernel this tree is running, and whether it drifted. None if unknown.

    Read, never asked. The kernel publishes `{version, fingerprint, drift}` from
    its own answer-bearing surface (`src/kernel/cli.ts state`), so the wave close
    does not need a human to vouch for a number it can compute.
    """
    rc, txt = _run(["bun", "run", os.path.join("src", "kernel", "cli.ts"), "state"],
                   cwd=instrument, timeout=120)
    if rc is None:
        return None
    try:
        start = txt.index("{")
        return json.loads(txt[start:txt.rindex("}") + 1])
    except (ValueError, KeyError):
        return None


def _kernel_check(workspace, wave, instrument):
    """The A-check that replaced the `kernel-frozen` affirmation.

    Three outcomes, and the third is why this is mechanical:

      * **held** — the surface at close is the surface at open. Green, silent.
      * **bumped mid-wave** — the lock moved deliberately and the version says so.
        Green, but the row records BOTH versions: builders that pinned the old
        one were already refusing at construction, and a reader of the ledger a
        month from now must not have to guess which kernel the wave's builds
        answered against.
      * **drift** — a gate or partner was edited and nobody bumped. UNSAFE, and
        cannot be carried: the close would write a `kernel` field into
        WAVES.jsonl that does not describe the answers the wave's builds gave.
        The remedy is one command (`cli.ts bump --why ...`), so refusing costs
        nothing that fixing it would not.
    """
    st = kernel_state(instrument)
    if st is None:
        return Check("kernel", False,
                     "could not read the kernel state (`bun run src/kernel/cli.ts "
                     "state`). NOT a pass — a check that cannot run is no answer.")
    if st.get("drift") != "clean":
        return Check("kernel", False,
                     f"DRIFT: running fingerprint {st.get('fingerprint')} is not the "
                     f"locked {st.get('locked_fingerprint')} for v{st.get('version')}. "
                     f"A gate or partner was edited without a version move — the "
                     f"exact silent divergence the fingerprint exists to catch. Run: "
                     f"bun run src/kernel/cli.ts bump --at DATE --why \"...\"",
                     carryable=False)

    waves, _ = load_waves(workspace)
    w = waves.get(wave)
    at_open = {}
    for row in (w.rows if w else []):
        if row.get("record") == "open" and row.get("kernel"):
            at_open = row["kernel"]
    if not at_open:
        return Check("kernel", False,
                     f"running v{st.get('version')} ({st.get('fingerprint')}) and "
                     f"clean, but {wave}'s open row recorded no kernel, so whether it "
                     f"HELD across the wave cannot be told. Carry it by name.")

    if at_open.get("fingerprint") != st.get("fingerprint"):
        return Check("kernel", True,
                     f"re-decided mid-wave: v{at_open.get('version')} "
                     f"({at_open.get('fingerprint')}) -> v{st.get('version')} "
                     f"({st.get('fingerprint')}). Clean against the lock.")
    return Check("kernel", True,
                 f"held at v{st.get('version')} ({st.get('fingerprint')}) for the "
                 f"whole wave")


def _declarations_check(workspace, wave, data_dir):
    """Every build in this wave said whether it had to guess at anything.

    The end-of-build half of the in-flight channel, and it exists because the
    running half CANNOT be enforced: nothing can make a builder notice it is
    guessing. What can be enforced is that it answers the question — so a build
    that hit nothing says so with a reason, and a build that says nothing at all
    is its own reported state rather than being read as a no.

    Carryable. Every manifest sealed before 2026-08-13 is silent by construction,
    and refusing outright would make the first close after this change
    unperformable — which is how a gate becomes something people route around.
    """
    try:
        read = inflight.read(data_dir)
        declared, silent, unreported = promotions.declarations(
            workspace, read.records, wave)
    except Exception as exc:                          # noqa: BLE001
        return Check("declarations", False,
                     f"could not read the builds' declarations: {exc}. NOT a pass.")
    if not declared and not silent:
        return Check("declarations", True, f"no builds found under port_runs/{wave}")
    if unreported:
        # The worse of the two failures, so it leads: the builder KNEW, and said
        # so only after the wave had already built on the guess.
        return Check("declarations", False,
                     f"{len(unreported)} question(s) declared by a build with no "
                     f"in-flight report behind them — the builder knew while it was "
                     f"running and nobody could act on it: " +
                     "; ".join(f"{lbl}:{t}" for lbl, t in unreported[:4]))
    if silent:
        return Check("declarations", False,
                     f"{len(silent)} of {len(declared) + len(silent)} build(s) never "
                     f"said whether they had to guess at anything (no `questions` "
                     f"block in port.manifest.json): " +
                     ", ".join(lbl for lbl, _ in silent[:5]) +
                     (f", +{len(silent) - 5} more" if len(silent) > 5 else ""))
    return Check("declarations", True,
                 f"all {len(declared)} build(s) declared what they could not answer")


def _decisions_check(workspace, data_dir):
    """Every question several builders hit has a recorded answer.

    CARRYABLE, never unsafe — deciding is judgment, and a wave that cannot close
    until every open question is settled is a wave that never closes. What this
    refuses is the third state: unanswered AND unmentioned. Answering "later" is
    an answer for this wave and brings the question back for the next one, which
    is what `later` is for.
    """
    try:
        qs, answers, _read = promotions.collect(data_dir, workspace)
    except Exception as exc:                          # noqa: BLE001
        return Check("decisions", False,
                     f"could not read the builders' question log: {exc}. NOT a "
                     f"pass — a check that cannot run is no answer.")
    # A MISSING LOG IS NOT AN EMPTY LOG, and reading it as one is how this
    # project's worst failures happen: the oracle's 200-with-`data: []` read as
    # "no records" when it meant "I am anonymous" (4ifi). Zero questions because
    # nobody ever reported is not zero questions.
    log = inflight.ledger_path(data_dir)
    if not os.path.isfile(log):
        return Check("decisions", False,
                     f"the builders' question log does not exist ({log}). That is "
                     f"'nobody reported a question', NOT 'nobody had one' — this "
                     f"check cannot tell you which, and a wave may not seal on the "
                     f"assumption it was the good one.")

    open_qs = promotions.unanswered(qs, answers)
    if not open_qs:
        return Check("decisions", True,
                     f"{len(qs)} question(s) raised by builders, all answered"
                     if qs else
                     f"{len(_read.records)} builder report(s), none hit by two or "
                     f"more builders independently")
    disagreed = [q for q in open_qs if q.disagree]
    if not disagreed:
        clash = ""
    elif len(disagreed) == 1:
        clash = (", and one of them was answered DIFFERENTLY by different builders "
                 "(the port already holds every answer they gave)")
    else:
        clash = (f", and {len(disagreed)} of them were answered DIFFERENTLY by "
                 f"different builders (the port already holds every answer they gave)")
    return Check("decisions", False,
                 f"{len(open_qs)} question(s) that two or more builders hit have "
                 f"no recorded answer{clash}: "
                 f"{', '.join(q.topic for q in open_qs[:4])}. "
                 f"See `wave.py elicit`; answer with `wave.py decide`.")


def _run(cmd, cwd=None, timeout=600):
    try:
        p = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout)
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except Exception as exc:                      # noqa: BLE001
        return None, str(exc)


def checks(workspace, wave, *, elenchus=None, instrument=None, run_suites=True,
           data_dir=None):
    """Every A-check. Pure-ish: returns Checks, never refuses on its own."""
    instrument = _instrument_root(instrument)
    data_dir = data_dir or _data_dir(workspace)
    out = []

    # --- uncommitted work. UNSAFE: cannot be carried. -----------------------
    for repo in (workspace, instrument):
        state = _git_dirty(repo)
        label = os.path.basename(repo.rstrip("/"))
        if state is None:
            out.append(Check(f"committed:{label}", False,
                             "not a git repo, or git failed — cannot tell whether "
                             "uncommitted work is being sealed", carryable=False))
            continue
        modified, untracked = state
        out.append(Check(f"committed:{label}", not modified,
                         "clean" if not modified else
                         f"{len(modified)} uncommitted change(s): " +
                         ", ".join(d[3:] for d in modified[:6]),
                         carryable=False))
        out.append(Check(f"untracked:{label}", not untracked,
                         "none" if not untracked else
                         f"{len(untracked)} untracked file(s): " +
                         ", ".join(d[3:] for d in untracked[:6]) +
                         " — build noise can be carried; NEW SOURCE cannot pass "
                         "unmentioned"))

    # --- an Elenchus artifact for THIS wave. --------------------------------
    # Deliberately the file check only. Whether it was READ is `pith-read`, a
    # B-affirmation — because A is satisfiable by producing a document nobody
    # opened, and pretending otherwise is the rubber stamp.
    if elenchus:
        p = elenchus if os.path.isabs(elenchus) else os.path.join(workspace, elenchus)
        out.append(Check("elenchus", os.path.isfile(p),
                         p if os.path.isfile(p) else f"no such file: {p}"))
    else:
        out.append(Check("elenchus", False,
                         "no --elenchus given. A wave closes on a reading of the "
                         "whole, or it closes on nothing."))

    # --- the kernel. Computed, never affirmed. ------------------------------
    out.append(_kernel_check(workspace, wave, instrument))

    # --- what each finished build SAID about its guesses --------------------
    out.append(_declarations_check(workspace, wave, data_dir))

    # --- questions builders could not answer --------------------------------
    # The A-half of `elicitation-answered`. The affirmation stays, because
    # nothing can check that a person READ a menu — but whether every question
    # has a recorded answer is a fact, and it was being asked of a human as part
    # of a yes/no about a menu no command ever printed.
    out.append(_decisions_check(workspace, data_dir))

    # --- verdict currency ---------------------------------------------------
    rc, txt = _run([sys.executable,
                    os.path.join(instrument, "ctkr", "ctkr", "verdict_currency.py")])
    if rc is None:
        out.append(Check("verdicts", False, f"could not run verdict_currency: {txt[:200]}"))
    else:
        tail = [l for l in txt.splitlines() if "lack a current, clean verdict" in l]
        out.append(Check("verdicts", rc == 0,
                         tail[-1].strip() if tail else f"verdict_currency exited {rc}"))

    # --- readings ratchet ---------------------------------------------------
    rc, txt = _run([sys.executable,
                    os.path.join(instrument, "ctkr", "ctkr", "readings.py"), "--ratchet"])
    if rc is None:
        out.append(Check("readings", False, f"could not run readings: {txt[:200]}"))
    else:
        out.append(Check("readings", rc == 0, txt.strip().splitlines()[-1][:300]
                         if txt.strip() else f"exited {rc}"))

    # --- the suites ---------------------------------------------------------
    if run_suites:
        for label, cmd, cwd in (
            ("suite:workspace", ["bun", "test"], workspace),
            ("suite:instrument", ["bun", "test"], instrument),
            ("smoke", ["bun", "run", "smoke"], instrument),
        ):
            rc, txt = _run(cmd, cwd=cwd, timeout=900)
            if rc is None:
                out.append(Check(label, False, f"could not run: {txt[:160]}"))
                continue
            hit = [l for l in txt.splitlines() if " pass" in l or "fail" in l.lower()]
            out.append(Check(label, rc == 0, (hit[-1].strip() if hit else f"exited {rc}")[:200]))
    else:
        # NOT a pass. A check that did not run is no answer at all (hy6.25), so it
        # is recorded as a failing, carryable check and must be carried BY NAME.
        for label in ("suite:workspace", "suite:instrument", "smoke"):
            out.append(Check(label, False, "NOT RUN (--skip-suites). Not a pass — a "
                                           "check that did not run is not an answer."))
    return out


# ---------------------------------------------------------------------------
# close / open
# ---------------------------------------------------------------------------

def _bad_reason(reason):
    return len((reason or "").split()) < MIN_REASON_WORDS


def _is_declined(value):
    """`--affirm kernel-frozen="no: v1.4 never landed"` — an honest no."""
    return (value or "").strip().lower().startswith("no:")


def _decline_reason(value):
    return (value or "").strip()[3:].strip()


def _instrument_root(instrument=None):
    return instrument or os.path.normpath(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", ".."))


def _data_dir(workspace, explicit=None):
    """Where the builders' question log lives.

    Deliberately does NOT reuse `commands._common.resolve_data_dir`, which exits
    the process when it finds nothing. A check that kills its caller cannot
    report "I could not tell", and "could not tell" is the answer that matters
    here — see `_decisions_check`.
    """
    if explicit:
        return explicit
    env = os.environ.get("METACODING_DATA_DIR")
    if env:
        return env
    cur = os.path.abspath(workspace)
    while True:
        if os.path.isdir(os.path.join(cur, ".metacoding")):
            return os.path.join(cur, ".metacoding")
        parent = os.path.dirname(cur)
        if parent == cur:
            return workspace
        cur = parent


def close(workspace, wave, *, at, elenchus=None, affirm=None, carry=None,
          instrument=None, run_suites=True, data_dir=None):
    """Returns (ok, message, row). Writes nothing — the caller appends."""
    waves, _ = load_waves(workspace)
    w = waves.get(wave)
    if w is None:
        return False, (f"{wave} was never opened. A wave that was never opened cannot "
                       f"be closed — open it first (retroactively is fine, and the row "
                       f"will say so)."), None
    if not w.is_open:
        return False, f"{wave} is already closed (at {w.closed_at}).", None

    affirm = dict(affirm or {})
    carry = dict(carry or {})

    problems = []

    missing = [k for k in AFFIRMATIONS if not affirm.get(k)]
    if missing:
        problems.append("UNANSWERED — these are questions only a person can answer, "
                        "and nothing here can check them:\n" +
                        "\n".join(f"    {k}: {AFFIRMATIONS[k]}" for k in missing) +
                        "\n  Answer each with --affirm KEY=WHO, or decline it "
                        "honestly with --affirm KEY=\"no: the reason\".")

    # AN AFFIRMATION MUST BE DECLINABLE, or the ritual is a rubber stamp. The
    # first version accepted only a name, so the sole way to close a wave was to
    # assert all three were true — which turns "the kernel is frozen" into a
    # sentence you type to get past a prompt. Answering NO is a legitimate close;
    # it just has to be recorded as a no, with a reason, and it lands in the
    # carried list where the next wave inherits it.
    declined_thin = {k: v for k, v in affirm.items()
                     if _is_declined(v) and _bad_reason(_decline_reason(v))}
    if declined_thin:
        problems.append("A DECLINED AFFIRMATION STILL NEEDS A REASON — saying no is "
                        "fine, saying nothing is not:\n" +
                        "\n".join(f"    {k}: {v!r}" for k, v in declined_thin.items()))

    results = checks(workspace, wave, elenchus=elenchus, instrument=instrument,
                     run_suites=run_suites, data_dir=data_dir)
    unsafe = [c for c in results if not c.ok and not c.carryable]
    if unsafe:
        problems.append("UNSAFE — cannot be carried forward:\n" +
                        "\n".join(f"    {c.name}: {c.detail}" for c in unsafe))

    uncarried = [c for c in results if not c.ok and c.carryable and c.name not in carry]
    if uncarried:
        problems.append("NOT DONE and nobody said so. Either fix, or carry each "
                        "forward with a reason (--carry NAME=\"why\"):\n" +
                        "\n".join(f"    {c.name}: {c.detail}" for c in uncarried))

    thin = {k: v for k, v in carry.items() if _bad_reason(v)}
    if thin:
        problems.append(f"A REASON UNDER {MIN_REASON_WORDS} WORDS IS NOT A REASON. The "
                        "cost of carrying debt is stating why, and it should land on "
                        "you rather than on the next reader:\n" +
                        "\n".join(f"    {k}: {v!r}" for k, v in thin.items()))

    if problems:
        return False, "\n\n".join(problems), None

    # DERIVED, not typed. `--kernel "v1.4"` used to be free text on the command
    # line, which is a version claim nobody checked sitting in a ledger row.
    row = {
        "record": "close", "wave": wave, "closed_at": at,
        "elenchus": elenchus or "",
        "kernel": kernel_state(_instrument_root(instrument)) or {},
        "affirmed": [{"what": k, "by": affirm[k]} for k in sorted(affirm)
                     if not _is_declined(affirm[k])],
        "declined": [{"what": k, "reason": _decline_reason(affirm[k])}
                     for k in sorted(affirm) if _is_declined(affirm[k])],
        "carried": [{"item": k, "reason": carry[k]} for k in sorted(carry)],
        "checks": [{"name": c.name, "ok": c.ok, "detail": c.detail} for c in results],
    }
    passed = sum(1 for c in results if c.ok)
    declined = len(row["declined"])
    return True, (f"{wave} closed. {passed}/{len(results)} mechanical checks green; "
                  f"{len(carry)} item(s) carried forward with reasons; "
                  f"{len(row['affirmed'])} affirmation(s) recorded by name" +
                  (f"; {declined} DECLINED and recorded as such." if declined
                   else ".")), row


def open_(workspace, wave, *, at, force="", instrument=None):
    """Returns (ok, message, row). REFUSES while a predecessor is open.

    The open row RECORDS THE KERNEL, with no input from whoever opens the wave.
    Without it "did the kernel hold across this wave?" has no baseline to be
    asked against, which is why it used to be asked of a person instead.
    """
    waves, _ = load_waves(workspace)
    if wave in waves and waves[wave].is_open:
        return False, f"{wave} is already open.", None

    still_open = [w.name for w in open_waves(workspace) if w.name != wave]
    if still_open and not force:
        return False, (f"REFUSING: {', '.join(still_open)} is still open.\n"
                       "  You cannot forget to close a wave if opening the next one "
                       "refuses — that is the whole mechanism.\n"
                       f"  Close it, or override deliberately:\n"
                       f"      wave open {wave} --force \"the reason\"\n"
                       "  An override is not a silence: the reason is written into "
                       "WAVES.jsonl as a row of its own."), None
    if force and _bad_reason(force):
        return False, (f"a --force reason under {MIN_REASON_WORDS} words is not a "
                       f"reason. Say why, in a sentence."), None

    row = {"record": "open", "wave": wave, "opened_at": at,
           "kernel": kernel_state(_instrument_root(instrument)) or {},
           "predecessor": still_open[0] if still_open else
                          (max((w for w in waves.values() if w.closed_at),
                               key=lambda w: w.closed_at).name if any(
                               w.closed_at for w in waves.values()) else "")}
    if force:
        row["forced_over_open"] = still_open
        row["force_reason"] = force
    msg = f"{wave} opened."
    if force:
        msg += (f" OVERRIDE RECORDED over still-open {', '.join(still_open)}: {force}")
    return True, msg, row


def append(workspace, row):
    path = ledger_path(workspace)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    new = not os.path.isfile(path)
    with open(path, "a") as fh:
        if new:
            fh.write("// WAVES.jsonl — append-only wave transitions. A wave closed "
                     "with debt and later re-opened is TWO rows, not an edit: the "
                     "history of what we accepted is the point. See MetaCoding "
                     "docs/design/wave-transition.md.\n")
        fh.write(json.dumps(row) + "\n")
    return path


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("action", choices=("status", "open", "close", "elicit", "decide"))
    ap.add_argument("wave", nargs="?")
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--at", required=False, default="",
                    help="the transition timestamp, e.g. 2026-08-12. Passed in "
                         "rather than read from the clock so a close is reproducible.")
    ap.add_argument("--elenchus", default=None)
    ap.add_argument("--data-dir", default=None,
                    help="where the builders' question log lives. Auto-detected "
                         "from a .metacoding/ above the workspace when omitted.")
    ap.add_argument("--choice", default="", choices=("", *promotions.CHOICES),
                    help="decide: " + " | ".join(
                        f"{k} = {v}" for k, v in promotions.CHOICES.items()))
    ap.add_argument("--why", default="", help="decide: why. This is the record of "
                                              "why the port works the way it does.")
    ap.add_argument("--by", default="", help="decide: who decided. A decision has "
                                             "an author.")
    ap.add_argument("--affirm", action="append", default=[], metavar="KEY=WHO")
    ap.add_argument("--carry", action="append", default=[], metavar="NAME=REASON")
    ap.add_argument("--force", default="")
    ap.add_argument("--note", default="",
                    help="free text written into the row. Use it when the row is "
                         "not what it appears — a RETROACTIVE open, for instance.")
    ap.add_argument("--skip-suites", action="store_true",
                    help="do not run the suites. NOT a pass — each becomes a check "
                         "you must carry forward by name.")
    ap.add_argument("--dry-run", action="store_true")
    args = ap.parse_args(argv)

    workspace = port_workspace(args.workspace)

    if args.action == "status":
        waves, order = load_waves(workspace)
        if not order:
            print(f"no wave ledger at {ledger_path(workspace)} — no wave has ever "
                  f"been opened or closed.")
            return 0
        for n in order:
            w = waves[n]
            state = "OPEN" if w.is_open else f"closed {w.closed_at}"
            print(f"  {n:14} {state:24} ({len(w.rows)} row(s))")
        return 0

    data_dir = _data_dir(workspace, args.data_dir)

    if args.action == "elicit":
        qs, answers, read = promotions.collect(data_dir, workspace)
        print(promotions.render(qs, answers, read, data_dir, workspace), end="")
        if read.malformed:
            print(f"\n{len(read.malformed)} unreadable report(s) in the builders' "
                  f"log were SKIPPED — they are not counted above:", file=sys.stderr)
            for m in read.malformed:
                print(f"  {m}", file=sys.stderr)
        return 0

    if args.action == "decide":
        # `wave` positionally carries the question here — it is the thing being
        # named, and a second positional would be worse than reusing this one.
        if not args.wave:
            ap.error("decide needs the question, exactly as `elicit` printed it")
        if not args.at:
            ap.error("--at is required (the date of the decision)")
        ok, msg, row = promotions.record_answer(
            workspace, args.wave, args.choice or "", args.why, args.by, args.at)
        if not ok:
            print(f"REFUSING to record that decision:\n\n{msg}", file=sys.stderr)
            return 2
        if args.dry_run:
            print(f"[dry run] would append: {json.dumps(row)}")
            return 0
        print(f"{msg}\nrecorded in {promotions.append(workspace, row)}")
        return 0

    if not args.wave:
        ap.error(f"{args.action} needs a wave name")
    if not args.at:
        ap.error("--at is required (the transition date), so a close is reproducible")

    def kv(items, what):
        out = {}
        for item in items:
            k, sep, v = item.partition("=")
            if not sep:
                ap.error(f"--{what} wants KEY=VALUE, got {item!r}")
            out[k.strip()] = v.strip()
        return out

    if args.action == "close":
        ok, msg, row = close(workspace, args.wave, at=args.at, elenchus=args.elenchus,
                             affirm=kv(args.affirm, "affirm"),
                             carry=kv(args.carry, "carry"),
                             run_suites=not args.skip_suites, data_dir=data_dir)
    else:
        ok, msg, row = open_(workspace, args.wave, at=args.at, force=args.force,
                             instrument=None)

    if not ok:
        print(f"REFUSING to {args.action} {args.wave}:\n\n{msg}", file=sys.stderr)
        return 2
    if args.note:
        row["note"] = args.note
    if args.dry_run:
        print(f"[dry run] would append to {ledger_path(workspace)}:")
        print(json.dumps(row, indent=2))
        print(f"\n{msg}")
        return 0
    path = append(workspace, row)
    print(msg)
    print(f"recorded in {path}")
    if args.action == "close" and row.get("carried"):
        print("\nThe carried list is only as good as the review of the commit that "
              "adds it. That is this ritual's real weakness and it is said here on "
              "purpose.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
