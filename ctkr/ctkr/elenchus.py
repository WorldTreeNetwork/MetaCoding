#!/usr/bin/env python3
"""Elenchus flags — when is it time to read the work WHOLE?

    python3 ctkr/ctkr/elenchus.py                 # print the flags, always exit 0
    python3 ctkr/ctkr/elenchus.py --require-current   # exit 2 if no current Elenchus

WHAT THIS IS
============
The Elenchus (`docs/design/epistemology-charter.md` §Dialectic,
`docs/design/fanout-wave-plan.md` §Coordination layer) is the antithesis phase:
one fresh interlocutor reads a wave WHOLE and returns the *pith* — the one to
three questions that say what the wave's scattered frictions were trying to say.
It fired once, at the wave-1 boundary (2026-07-22). Its only trigger was a wave
boundary a human declares, and eighteen days of wave 2 went by without one.

That is the shape MetaCoding-hy6.28 spent two days removing one level down: the
oracle preflight existed, was cheap, was correct, and ran in one build out of
five because nothing made it a precondition of anything. A step that depends on
memory is off by default.

FLAGS ARE NOT GATES, AND THIS FILE MUST NEVER BECOME ONE
========================================================
Everywhere else in this project, "advisory to a human, invisible to an automated
caller" IS the defect — it is exactly what made the module-drift check exit 0
while it had not run (hy6.25). Here the inversion is deliberate, and the reason
is worth stating so nobody "fixes" it:

    The flags say it may be time to examine. Whether it IS time, and what the
    examination finds, is judgment — and judgment auto-fired on a counter is
    judgment performed to reset the counter.

The charter's own warning: a method exhausting to live inside will be abandoned
or gamed. An Elenchus convened to satisfy a threshold produces three tidy
questions and examines nothing. So: `main()` exits 0 whatever it finds. The one
gate that IS legitimate is on the irreversible act — a kernel freeze, a wave
seal, a re-baseline — because those are the steps you cannot take back, and that
is what `--require-current` is for. Gate the act, flag the smell.

THREE OF THESE ARE COMPUTED. THE TWO STRONGEST ARE NOT.
=======================================================
Said out loud rather than papered over, because a flag set that only contains
what is easy to measure will quietly redefine "time to examine" as "time the
easy measurements noticed" — the same substitution `hy6.25` exists to prevent,
one level up. The two most valuable signals so far — readers converging on an
observation nobody asked them for, and "I cannot say in one sentence what this
wave established" — are noticed by a person. They are listed here as first-class
flags with `source="noticed"`, reported as *your call*, never as clear.

THE LIST IS DATA AND IT WILL CHURN
==================================
The general principle above is meant to last. The particular flags below are
provisional: each carries the observation that produced it (`because`) and the
condition under which it should be dropped (`retire_when`), in the spirit of
`eval/ctkr/metric_updates.jsonl` — no silent redefinition of when we look.
Adding or retiring one is a commit that says which observation moved it.
"""

from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field

#: A file is an Elenchus record if it CONTAINS one, not if it is named like one.
#: `wave1-ritual-2026-07-22.md` carries the only one that exists and does not say
#: "elenchus" in its filename; a naming convention would have missed it, and a
#: discovery rule that misses the single instance of the thing it looks for is a
#: checker that cannot fire.
ELENCHUS_HEADING = re.compile(r"^#{1,3}\s+the elenchus\b", re.I | re.M)

#: How many builds may land before the last reading of the whole is stale. Set
#: from wave 1: four features, one Elenchus. Wave 2 is past twenty.
STALE_AFTER_BUILDS = 6

#: Consecutive instrument-touching commits before `instrument-inversion` lights.
#:
#: CALIBRATED AGAINST ITS OWN FOUNDING CASE, AND THE FIRST VALUE FAILED IT. Set
#: to 3 from the description "three consecutive commits hardening tools/", this
#: flag never fired across the episode it was written from: after the second such
#: commit the run was 2, and by the third the measured side had reached a second
#: build — because that third commit was the CORRECTION. A flag that lights only
#: once you have already fixed the thing is a flag that reports history.
#:
#: 2 is the moment the signal is actually available: two commits of mechanism
#: with the measured side still inside one build, which is when the judge had
#: said it twice and the work had not moved. Measured by replaying the window,
#: not reasoned about — see tests/test_elenchus.py.
INVERSION_RUN = 2


@dataclass(frozen=True)
class Flag:
    """One reason it might be time. `asks` is the question, not the metric —
    a flag whose name is a threshold invites satisfying the threshold."""
    name: str
    asks: str
    source: str            # "computed" | "noticed"
    since: str
    because: str           # the observation that produced this flag
    retire_when: str       # drop it when this holds — reversal condition


FLAGS = [
    Flag(name="cannot-say-what-it-established",
         asks="Can you say in one sentence what this wave established?",
         source="noticed", since="2026-08-09",
         because="Duke, naming his own tell. It is the strongest signal we have "
                 "and no artifact carries it.",
         retire_when="a synthesis artifact per wave makes the sentence a "
                     "deliverable rather than a test"),
    Flag(name="readers-converged",
         asks="Have two independent fresh readings volunteered the SAME closing "
              "observation, unprompted?",
         source="noticed", since="2026-08-09",
         because="The hy6.28 judge ended both of its reports with 'every repair "
                 "lands on tools/ledger.py, which one build uses' — a reader "
                 "noticing something a reader has no mandate to pursue. That is "
                 "pith material arriving through the wrong door.",
         retire_when="readings carry a structured 'what I could not pursue' "
                     "section, making convergence countable instead of noticed"),
    Flag(name="instrument-inversion",
         asks="Have the last commits been mechanism, with the measured side "
              "confined to a single build?",
         source="computed", since="2026-08-09",
         because="2026-08-07: three consecutive commits hardening tools/, after "
                 "seven that touched it not at all. FIRST DRAFT OF THIS FLAG "
                 "ASKED FOR `measured == 0` AND READ 0 — because those three "
                 "commits DID touch port_runs/, just all of it inside one build "
                 "(the harness they were hardening, plus its regenerated "
                 "artifact). The flag's own author had described them as "
                 "'instrument only' and the flag said otherwise. The signal is "
                 "not mechanism-without-measurement; it is mechanism whose "
                 "measured side never leaves one build — which is precisely "
                 "what the hy6.28 judge said twice.",
         retire_when="a wave routinely interleaves both and the signal stops "
                     "discriminating. ASSUMES A LAYOUT, and that assumption "
                     "already expired once: instrument = MetaCoding src/ ctkr/ "
                     "scripts/ + farmos-port tools/, measured = farmos-port "
                     "port_runs/ (ROLE_PREFIXES). Written as tools/-in-one-repo "
                     "on 2026-08-09, the flag went blind when the instrument "
                     "moved and reported CLEAR through a 100%-instrument week "
                     "(MetaCoding-vm8). RE-READ THIS ENTRY WHENEVER EITHER TREE "
                     "IS REORGANISED — a flag calibrated against where the work "
                     "happened to live expires silently when the work moves."),
    Flag(name="findings-cluster",
         asks="Are several open findings the same shape — patches accumulating "
              "where a better-posed question is hiding?",
         source="computed", since="2026-08-09",
         because="hy6.36 / hy6.39 / hy6.42 are one shape (the gate covers one "
                 "build; nothing reads its artifact; it checks one direction). "
                 "The synthesis signal is the inverse: findings collapsing into "
                 "one mechanism.",
         retire_when="clustering by shared token proves to fire on coincidence "
                     "more often than on shape"),
    Flag(name="stale-whole-reading",
         asks="How many builds have landed since anyone read the wave whole?",
         source="computed", since="2026-08-09",
         because="The dumb backstop. Wave 1 got an Elenchus at four features; "
                 "wave 2 passed twenty without one and nothing was overdue "
                 "because nothing was ever due.",
         retire_when="a boundary ritual fires reliably on its own"),
]


@dataclass
class Reading:
    """What one flag found. `unavailable` is NOT `clear` — an unanswerable
    question is 'no answer', and reporting it as clear is how a check that could
    not run contributes a pass (hy6.25, the whole reason that lesson is written
    down)."""
    flag: Flag
    lit: bool = False
    unavailable: str = ""
    evidence: str = ""


# ---------------------------------------------------------------------------
# Gathering — every collector may fail, and says so rather than returning empty
# ---------------------------------------------------------------------------

def _git(repo, *args):
    out = subprocess.run(["git", "-C", repo, *args],
                         capture_output=True, text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[:200])
    return out.stdout


def port_workspace(explicit=None):
    """The ledger tree. Same resolution the rest of the instrument uses."""
    if explicit:
        return explicit
    env = os.environ.get("METACODING_PORT_WORKSPACE")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    root = os.path.normpath(os.path.join(here, "..", ".."))
    sibling = os.path.normpath(os.path.join(root, "..", "farmos-port"))
    return sibling if os.path.isdir(sibling) else os.path.join(root, "eval", "ctkr")


def instrument_repo(explicit=None):
    """The tree the INSTRUMENT lives in — MetaCoding, i.e. this file's own repo.

    Separate from `port_workspace()` on purpose. They were the same tree when
    these flags were calibrated on 2026-08-09 and they are not any more, which is
    the whole of `MetaCoding-vm8`.
    """
    if explicit:
        return explicit
    env = os.environ.get("METACODING_INSTRUMENT_REPO")
    if env:
        return env
    here = os.path.dirname(os.path.abspath(__file__))
    return os.path.normpath(os.path.join(here, "..", ".."))


#: WHICH PATHS PLAY WHICH ROLE, DECLARED RATHER THAN INFERRED — MetaCoding-vm8.
#:
#: The first version of this flag asked one question of one tree: "does the path
#: start with `tools/`?" That was true of the instrument on 2026-08-09 and false
#: five days later, because the instrument MOVED to MetaCoding while the flag kept
#: reading farmos-port. It reported CLEAR through a week in which ~120 file-touches
#: of mechanism hardening happened in a repo it never opened — the flag's own
#: founding shape, running dark, invisible to itself.
#:
#: So the roles are a DECLARATION with a repo attached, not a prefix test. When the
#: layout moves again this is the thing that must be edited, and a wrong entry here
#: is visible as a wrong entry rather than as silence. `retire_when` on the flag now
#: carries the assumption too, per the bead's larger lesson: a flag calibrated
#: against where the work happened to live expires silently when the work moves.
#:
#: `docs/` is deliberately NOT instrument. Design documents are the argument about
#: the mechanism, not the mechanism; counting them would let a week of writing about
#: a tool read as a week of hardening it — which is the inversion this flag exists
#: to catch, inverted.
ROLE_PREFIXES = {
    "instrument": {
        "instrument": ("src/", "ctkr/", "scripts/"),   # MetaCoding
        "workspace": ("tools/",),                       # farmos-port
    },
    "measured": {
        "instrument": (),
        "workspace": ("port_runs/",),
    },
}


def _commits(repo, role, window):
    """The `window` most recent commits of one repo, newest first, with an
    author timestamp so two histories can be merged onto one clock.

    Returns [] when the repo is missing rather than raising: one absent tree must
    degrade the reading, not abolish it. A caller that needs to know the difference
    reads `state["errors"]`.
    """
    if not os.path.isdir(os.path.join(repo, ".git")):
        return []
    out = []
    for line in _git(repo, "log", f"-{window}", "--format=%H %at").splitlines():
        if not line.strip():
            continue
        sha, _, ts = line.partition(" ")
        files = _git(repo, "show", "--name-only", "--format=", sha).split()
        out.append({"sha": sha, "at": int(ts or 0), "repo": repo,
                    "role": role, "files": files})
    return out


def find_elenchus_records(workspace):
    """Every file under the workspace that CARRIES an Elenchus."""
    found = []
    for base, _dirs, files in os.walk(os.path.join(workspace, "results")):
        for fn in files:
            if not fn.endswith(".md"):
                continue
            path = os.path.join(base, fn)
            try:
                with open(path, encoding="utf-8", errors="replace") as fh:
                    if ELENCHUS_HEADING.search(fh.read()):
                        found.append(path)
            except OSError:
                continue
    return sorted(found)


def gather(workspace, *, instrument=None, window=10):
    """Everything the computed flags read. Pure data, so `evaluate()` is testable
    without a git tree, a bead store or a wave.

    TWO TREES. `workspace` holds the measured side (farmos-port/port_runs) and the
    Elenchus records; `instrument` holds the mechanism (MetaCoding). They were one
    tree when these flags were written — see ROLE_PREFIXES for what that cost.
    """
    instrument = instrument or instrument_repo()
    state = {"workspace": workspace, "instrument": instrument, "errors": {}}

    records = find_elenchus_records(workspace)
    state["elenchus_records"] = records
    try:
        if records:
            newest = max(records, key=lambda p: _git(
                workspace, "log", "-1", "--format=%at", "--", p).strip() or "0")
            state["last_elenchus"] = newest
            since = _git(workspace, "log", "-1", "--format=%H", "--", newest).strip()
            builds = _git(workspace, "log", "--format=%H", f"{since}..HEAD",
                          "--", "port_runs")
            state["builds_since_elenchus"] = len([l for l in builds.splitlines() if l])
        else:
            state["last_elenchus"] = None
            state["builds_since_elenchus"] = None
    except (RuntimeError, OSError) as exc:
        state["errors"]["history"] = str(exc)

    # Instrument vs measured, per commit, over the recent window — ACROSS BOTH
    # REPOS, merged onto one clock. See ROLE_PREFIXES and MetaCoding-vm8: reading
    # only the workspace made this flag blind to the tree the instrument moved to.
    try:
        merged = (_commits(instrument, "instrument", window)
                  + _commits(workspace, "workspace", window))
        merged.sort(key=lambda c: c["at"], reverse=True)
        regime = []
        for c in merged[:window]:
            inst_pfx = ROLE_PREFIXES["instrument"][c["role"]]
            meas_pfx = ROLE_PREFIXES["measured"][c["role"]]
            # A BUILD, not a file: `port_runs/wave2/identity-farm-org/...` is one
            # build however many of its files a commit rewrites. Counting files
            # would let regenerating one artifact read as broad measurement.
            builds = {"/".join(f.split("/")[:3]) for f in c["files"]
                      if f.startswith(meas_pfx) and len(f.split("/")) > 3}
            regime.append({
                "sha": c["sha"][:7],
                "repo": os.path.basename(c["repo"].rstrip("/")),
                "instrument": sum(1 for f in c["files"] if f.startswith(inst_pfx)),
                "builds": sorted(builds),
            })
        state["regime"] = regime
        if not merged:
            state["errors"]["regime"] = ("neither tree is a git repo — "
                                         f"{instrument!r}, {workspace!r}")
    except (RuntimeError, OSError) as exc:
        state["errors"]["regime"] = str(exc)

    return state


def open_findings(epic):
    """Open findings WITHIN ONE WAVE, via `bd`. Absence of bd is unavailable,
    never 'no findings'.

    Scoped, and it has to be. The first version clustered every open bead in the
    store and lit on eleven across four unrelated efforts — a flag that fires
    always is the same as a flag that never fires, which this module's own
    docstring says about the token list two paragraphs down. An Elenchus reads
    A WAVE whole; its flags read that wave's findings.
    """
    out = subprocess.run(["bd", "list", "--json"], capture_output=True,
                         text=True, timeout=60)
    if out.returncode != 0:
        raise RuntimeError((out.stderr or out.stdout).strip()[:200])
    import json
    rows = json.loads(out.stdout)
    return [r for r in rows
            if r.get("status") in ("open", "in_progress")
            and (r.get("parent") == epic or r["id"].startswith(epic + "."))]


#: Tokens worth clustering on: a shape shows up as the same mechanism named in
#: several findings. Deliberately a SMALL closed list — an open one turns every
#: common English word into a cluster and the flag fires always, which is the
#: same as never.
CLUSTER_TOKENS = re.compile(
    r"\b(ledger\.py|oracle_preflight|preflight|PREFLIGHT row|bring-up\.sh|"
    r"same-oracle|kernel|glossary|port-verify|absence check)\b", re.I)


def cluster_findings(findings, *, threshold=3):
    """Group open findings by the mechanism they name. Returns {token: [ids]}."""
    groups = {}
    for f in findings:
        text = f"{f.get('title','')} {f.get('description','')}"
        for tok in {m.group(0).lower() for m in CLUSTER_TOKENS.finditer(text)}:
            groups.setdefault(tok, []).append(f["id"])
    return {k: v for k, v in groups.items() if len(v) >= threshold}


# ---------------------------------------------------------------------------
# Judging — pure functions over gathered state
# ---------------------------------------------------------------------------

def evaluate(state, findings=None, findings_error=""):
    """One Reading per flag. Never raises: an unanswerable flag is unavailable."""
    by_name = {f.name: f for f in FLAGS}
    out = []

    for f in FLAGS:
        if f.source == "noticed":
            out.append(Reading(flag=f, unavailable="not computable — your call",
                               evidence=f.asks))

    # -- stale-whole-reading ------------------------------------------------
    r = Reading(flag=by_name["stale-whole-reading"])
    if "history" in state.get("errors", {}):
        r.unavailable = state["errors"]["history"]
    elif not state.get("elenchus_records"):
        r.lit = True
        r.evidence = ("NO Elenchus record exists anywhere under results/ — "
                      "nothing has ever read this work whole")
    else:
        n = state.get("builds_since_elenchus")
        last = os.path.basename(state.get("last_elenchus") or "?")
        if n is None:
            r.unavailable = "could not count builds since the last Elenchus"
        else:
            r.lit = n >= STALE_AFTER_BUILDS
            r.evidence = (f"{n} commit(s) touching port_runs/ since {last} "
                          f"(stale at {STALE_AFTER_BUILDS})")
    out.append(r)

    # -- instrument-inversion ----------------------------------------------
    r = Reading(flag=by_name["instrument-inversion"])
    regime = state.get("regime")
    if "regime" in state.get("errors", {}) or regime is None:
        r.unavailable = state.get("errors", {}).get("regime", "no history read")
    else:
        run, touched = 0, set()
        for c in regime:                      # newest first
            if c["instrument"] == 0:
                # MEASUREMENT ends an inversion. Anything that is NEITHER
                # mechanism nor measurement — a design doc, a results/ write-up,
                # a bead export — is not evidence about the regime, so it is
                # SKIPPED rather than treated as the end of the run.
                #
                # The first version broke here unconditionally, which was
                # survivable while one repo held everything and became wrong the
                # moment two histories were merged: any prose commit in either
                # tree would end the run. Found while fixing MetaCoding-vm8 and
                # it is the same blindness one layer down — on 2026-08-12 this
                # flag read "0 commits touched the instrument" purely because the
                # three most recent commits were a synthesis and a design doc.
                # A flag that a design document can switch off is reporting who
                # wrote prose last, not what the regime is.
                if c["builds"]:
                    break
                continue
            run += 1
            touched.update(c["builds"])
        r.lit = run >= INVERSION_RUN and len(touched) <= 1
        where = ", ".join(sorted(touched)) or "no build at all"
        repos = sorted({c.get("repo", "?") for c in regime})
        r.evidence = (f"{run} most-recent commit(s) touched the instrument; their "
                      f"measured side reached {len(touched)} build(s): {where} "
                      f"(of {len(regime)} commits examined across {'+'.join(repos)})")
    out.append(r)

    # -- findings-cluster ---------------------------------------------------
    r = Reading(flag=by_name["findings-cluster"])
    if findings is None:
        r.unavailable = findings_error or "no findings source"
    else:
        groups = cluster_findings(findings)
        r.lit = bool(groups)
        r.evidence = ("; ".join(f"{k}: {', '.join(v)}" for k, v in sorted(groups.items()))
                      or f"no shape shared by 3+ of {len(findings)} open findings")
    out.append(r)

    order = {f.name: i for i, f in enumerate(FLAGS)}
    return sorted(out, key=lambda x: order[x.flag.name])


def render(readings, state):
    lines = ["ELENCHUS FLAGS — reasons it may be time to read the work whole.",
             "These are FLAGS, NOT GATES: nothing here decides, and this command",
             "exits 0 whatever it finds. See the module docstring for why.", ""]
    for r in readings:
        mark = "FLAG " if r.lit else ("  ?  " if r.unavailable else "  .  ")
        lines.append(f"{mark} {r.flag.name}  [{r.flag.source}]")
        lines.append(f"       {r.flag.asks}")
        detail = r.unavailable or r.evidence
        if detail:
            lines.append(f"       -> {detail}")
    lit = [r for r in readings if r.lit]
    noticed = [r for r in readings if r.flag.source == "noticed"]
    lines += ["",
              f"{len(lit)} computed flag(s) lit; {len(noticed)} are yours to answer.",
              "A flag is a reason to consider convening, not a verdict that it is time.",
              "The output of an Elenchus is a QUESTION, never a findings list — if it",
              "reads like a checklist item, it was one."]
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--instrument", default=None,
                    help="the tree the INSTRUMENT lives in (default: this file's "
                         "own repo). Separate from --workspace since 2026-08-12: "
                         "they were one tree when these flags were calibrated and "
                         "reading only the workspace made the regime flag blind "
                         "(MetaCoding-vm8).")
    ap.add_argument("--epic", default=os.environ.get("ELENCHUS_EPIC"),
                    help="the wave whose findings to cluster, e.g. MetaCoding-hy6. "
                         "Without it the cluster flag reports UNAVAILABLE rather "
                         "than clustering the whole store — see open_findings().")
    ap.add_argument("--window", type=int, default=10,
                    help="how many recent commits to read for the regime flag")
    ap.add_argument("--require-current", action="store_true",
                    help="THE ONE GATE: exit 2 unless a current Elenchus exists. For "
                         "the irreversible steps only — kernel freeze, wave seal, "
                         "re-baseline, elicitation menu.")
    args = ap.parse_args(argv)

    workspace = port_workspace(args.workspace)
    state = gather(workspace, instrument=instrument_repo(args.instrument),
                   window=args.window)
    if not args.epic:
        findings, err = None, ("no wave scope: pass --epic (or set ELENCHUS_EPIC). "
                               "Clustering every open finding in the store lights "
                               "always, which is the same as never")
    else:
        try:
            findings, err = open_findings(args.epic), ""
        except Exception as exc:              # noqa: BLE001 — bd absent is no answer
            findings, err = None, f"bd unavailable: {exc}"

    readings = evaluate(state, findings, err)
    print(render(readings, state))

    if args.require_current:
        stale = next(r for r in readings if r.flag.name == "stale-whole-reading")
        if stale.unavailable:
            print("\nREFUSING: cannot establish whether an Elenchus is current "
                  f"({stale.unavailable}). Absence of an answer is not a yes.",
                  file=sys.stderr)
            return 2
        if stale.lit:
            print("\nREFUSING: this step makes something permanent or expensive to "
                  "undo, and no current Elenchus stands behind it.\n"
                  f"  {stale.evidence}\n"
                  "  Convene one, or take the step deliberately with the reason "
                  "recorded.", file=sys.stderr)
            return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
