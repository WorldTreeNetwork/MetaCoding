#!/usr/bin/env python3
"""Readings — who has read what, how stale it is, and what nobody has read.

    python3 ctkr/ctkr/readings.py                  # coverage report, always exit 0
    python3 ctkr/ctkr/readings.py --unread         # just the names, for piping
    python3 ctkr/ctkr/readings.py --ratchet        # exit 2 if the UNREAD SET GREW

WHY THIS EXISTS
===============
A judge ruled on 2026-08-12 that a mechanically-replayed pack, satisfied perfectly
across all 21 wave-2 builds, would have caught approximately NONE of wave 2's
actual defects — they live in the complement, the inputs nobody thought to send.
The fresh reader caught every one of them, 8 for 8, and reached 8 of 21 builds.
Its own conclusion, argued against its own ruling: *if only one is funded this
month, fund the readings.*

But the wave-2 Elenchus found all three of wave 1's pith questions RECURRING, and
diagnosed why: wave 1 proposed an answer addressing REACHABILITY while the question
was about READERSHIP. A reading's finding currently decays into a bead. Sixty-one
beads were opened in five days against twenty closed. **More readings without
persistence is more recurrence, faster.**

So this file does the smallest thing that makes readings durable:

  1. ONE APPEND PER READING to `port_runs/READINGS.jsonl`, matching the PACKS.jsonl
     convention exactly — the ledger's records live with the ledger.
  2. A COVERAGE READ: which builds have never been read, and how stale the rest are.
  3. A RATCHET: the unread set may not GROW. Not "everything must be read" — that
     is permanently red today at 13 unread, and a permanently red gate is deleted
     within the week and is exactly as useful as one that never fires.

WHAT IT DELIBERATELY DOES NOT DO
================================
It does not check that a reading was any GOOD. It cannot. Whether an interlocutor
asked the right question is judgment, and `docs/design/enforceability.md`
disposition 3 says an executable pretence there decays into a counter to satisfy.
A row here means SOMEONE FRESH LOOKED AND SAID WHAT THEY DID NOT LOOK AT. That is
all, and claiming more would be the defect this project keeps finding.

Nor does it schedule readings. It makes the absence of one VISIBLE and makes the
set of unread builds unable to grow silently. Whether to read is Duke's call —
which is the same shape as `elenchus.py`: the mechanism reports, the human decides,
and the deciding is recorded.

THE RECORD, and it is one line
==============================
    {"record":"reading", "target":"wave2/identity-medical", "kind":"judge",
     "at":"2026-08-12", "rev_ledger":"bbdecf8", "rev_instrument":"c956a5e",
     "reader":"fresh-agent", "artifact":"results/wave2/judge-batch2-2026-08-03.md",
     "findings":["MetaCoding-hy6.31"], "not_read":"the build's own src/; packs"}

`not_read` is required and is the field that costs something. Every judge report
this project has trusted carried one, and the one judge that died before writing
it left a gap nobody could size. A reading that will not say what it skipped is
not a reading, it is a claim.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctkr.elenchus import port_workspace  # noqa: E402

#: Required on every row. `not_read` is here on purpose — see the docstring.
REQUIRED = ("record", "target", "kind", "at", "reader", "artifact", "not_read")

#: What a reading can be. A closed vocabulary with no escape member, because an
#: unnamed kind is how "I glanced at it" becomes "it was read".
KINDS = ("judge", "elenchus", "observation", "verifier")


@dataclass
class Reading:
    target: str
    kind: str
    at: str
    artifact: str
    reader: str = ""
    findings: list = field(default_factory=list)
    not_read: str = ""
    rev_ledger: str = ""


def load_readings(workspace):
    """Every recorded reading, plus the rows that are malformed and why.

    A malformed row is an ERROR, never silently skipped: a row that fails to
    parse is a reading nobody can check, and counting it would let the coverage
    number rise on unreadable evidence.
    """
    out, errors = [], []
    path = os.path.join(workspace, "port_runs", "READINGS.jsonl")
    if not os.path.isfile(path):
        return out, errors
    for n, line in enumerate(open(path), 1):
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            errors.append(f"READINGS.jsonl:{n}: unreadable ({exc}) — not counted as a reading")
            continue
        if str(row.get("record") or "") != "reading":
            continue
        missing = [k for k in REQUIRED if not str(row.get(k) or "").strip()]
        if missing:
            errors.append(f"READINGS.jsonl:{n}: missing {', '.join(missing)} — not counted. "
                          f"`not_read` is required: a reading that will not say what it "
                          f"skipped is a claim, not a reading.")
            continue
        if row["kind"] not in KINDS:
            errors.append(f"READINGS.jsonl:{n}: kind {row['kind']!r} is outside "
                          f"{KINDS} — not counted")
            continue
        out.append(Reading(target=row["target"], kind=row["kind"], at=row["at"],
                           artifact=row["artifact"], reader=row.get("reader", ""),
                           findings=row.get("findings") or [],
                           not_read=row["not_read"],
                           rev_ledger=row.get("rev_ledger", "")))
    return out, errors


def readable_targets(workspace):
    """Everything that CAN be read: one entry per build directory in every wave.

    A build, not a manifest — a reading is of a build, and `spine-asset`'s seven
    packages are one thing to read. That is the opposite of what verdict_currency
    counts, deliberately: a verdict is per-artifact, a reading is per-mind.
    """
    runs = os.path.join(workspace, "port_runs")
    targets = []
    if not os.path.isdir(runs):
        return targets
    for wave in sorted(os.listdir(runs)):
        wdir = os.path.join(runs, wave)
        if not wave.startswith("wave") or not os.path.isdir(wdir):
            continue
        for build in sorted(os.listdir(wdir)):
            bdir = os.path.join(wdir, build)
            if not os.path.isdir(bdir):
                continue
            # A BUILD, not any directory. The first version counted every
            # subdirectory and reported 36 readable targets including
            # `wave0-pilot/w0a-observe` — inflating the denominator, which is the
            # cheapest way to make a coverage number look worse than it is and
            # the same class of error as counting manifests while calling them
            # builds (MetaCoding-hy6.57). A build has a `build/` or an `observe/`
            # lane, or declares a manifest of its own.
            entries = set(os.listdir(bdir))
            if {"build", "observe"} & entries or "port.manifest.json" in entries:
                targets.append(f"{wave}/{build}")
    return targets


def coverage(workspace):
    readings, errors = load_readings(workspace)
    targets = readable_targets(workspace)
    by_target = {}
    for r in readings:
        by_target.setdefault(r.target, []).append(r)
    unread = [t for t in targets if t not in by_target]
    return {"targets": targets, "by_target": by_target, "unread": sorted(unread),
            "errors": errors, "readings": readings}


# ---------------------------------------------------------------------------
# The ratchet
# ---------------------------------------------------------------------------

def baseline_path(workspace):
    return os.path.join(workspace, "port_runs", "READINGS.baseline.json")


def load_baseline(workspace):
    try:
        with open(baseline_path(workspace)) as fh:
            doc = json.load(fh)
        return set(doc.get("unread") or []), doc.get("recorded_at", "")
    except FileNotFoundError:
        return None, ""
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"cannot read the ratchet baseline: {exc}") from exc


def ratchet(workspace):
    """The unread set may not GROW. Returns (ok, message).

    NOT "everything must be read" — that is red today at 13 of 21 and would be
    deleted within the week. What this refuses is the actual failure mode: a NEW
    build joining the unread set without anyone saying so. Shrinking is always
    fine and the baseline is meant to be re-cut when it shrinks.
    """
    cov = coverage(workspace)
    now = set(cov["unread"])
    base, when = load_baseline(workspace)
    if base is None:
        return False, ("no ratchet baseline exists. Nothing is being held, which is not "
                       "the same as nothing being wrong — write "
                       f"{baseline_path(workspace)} with the current unread set and a "
                       "reason per entry, deliberately, once.")
    grew = sorted(now - base)
    if grew:
        return False, ("THE UNREAD SET GREW. These are readable and nobody has read them, "
                       "and they were not in the baseline:\n  " + "\n  ".join(grew) +
                       f"\n(baseline recorded {when}). Either read them, or re-cut the "
                       "baseline deliberately with a reason — but not silently.")
    shrank = sorted(base - now)
    msg = f"unread set held at {len(now)} (baseline {len(base)})"
    if shrank:
        msg += f"; {len(shrank)} newly read: {', '.join(shrank)} — re-cut the baseline"
    return True, msg


def render(cov):
    lines = [f"readable targets: {len(cov['targets'])}   "
             f"read: {len(cov['by_target'])}   UNREAD: {len(cov['unread'])}"]
    if cov["unread"]:
        lines.append("\nnever read by anyone but their builder:")
        lines += [f"  {t}" for t in cov["unread"]]
    if cov["by_target"]:
        lines.append("\nread:")
        for t in sorted(cov["by_target"]):
            rs = cov["by_target"][t]
            newest = max(rs, key=lambda r: r.at)
            kinds = ",".join(sorted({r.kind for r in rs}))
            lines.append(f"  {t:38} {newest.at}  [{kinds}]  {newest.artifact}")
    for e in cov["errors"]:
        lines.append(f"  ERR {e}")
    lines.append("\nA row means someone fresh looked and said what they did NOT look at.")
    lines.append("It does not mean the reading was any good — that is judgment, and")
    lines.append("nothing here can check it (enforceability.md, disposition 3).")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--unread", action="store_true", help="print unread target names only")
    ap.add_argument("--ratchet", action="store_true",
                    help="exit 2 if the unread set GREW against the recorded baseline")
    args = ap.parse_args(argv)

    workspace = port_workspace(args.workspace)
    cov = coverage(workspace)

    if args.unread:
        for t in cov["unread"]:
            print(t)
        return 0
    if args.ratchet:
        try:
            ok, msg = ratchet(workspace)
        except RuntimeError as exc:
            print(f"REFUSING: {exc}", file=sys.stderr)
            return 2
        print(msg if ok else "", end="" if not ok else "\n")
        if not ok:
            print(f"REFUSING: {msg}", file=sys.stderr)
            return 2
        return 0

    print(f"readings: {workspace}")
    print(render(cov))
    # Advisory by construction. The coverage number is a reason to consider
    # reading, never a verdict that the work is unread-and-therefore-bad.
    return 0


if __name__ == "__main__":
    sys.exit(main())
