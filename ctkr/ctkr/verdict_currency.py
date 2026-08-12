#!/usr/bin/env python3
"""Verdict currency — has this port actually been DRIVEN, against the pack it has now?

    python3 ctkr/ctkr/verdict_currency.py              # report; exit 2 if any identity
                                                       # build is missing a current verdict
    python3 ctkr/ctkr/verdict_currency.py --all-tiers  # report spine too (advisory)

WHY THIS EXISTS
===============
Recipe step 8 (`docs/design/fanout-wave-plan.md`) says an identity-tier build with
a bridge and no recorded verdict is not done. It said that in prose, with nothing
executing it — which a fresh judge named on 2026-08-11 as `MetaCoding-hy6.28`'s
defect reintroduced one layer up, four days after that lesson was written down:

    A gate nobody must remember to run is off by default.

The evidence it was right: `ctkr port-verify` worked cold on the first try, and
no verdict of any kind had been recorded for a wave-2 build. Twenty-one builds
shipped past a step that could not refuse them, because it was a paragraph.

WHAT IT REFUSES
===============
For every `port.manifest.json` in the workspace, a verdict under
`results/port-verify/` that:

  - EXISTS,
  - names that port,
  - carries the pack seal the build's `observe/pack.seal.json` carries TODAY —
    a verdict against a superseded pack is a verdict about a pack that no longer
    exists, and re-recording a pack silently invalidates every score taken on it,
  - and says `clean`.

Missing, stale, unclean, or UNDETERMINABLE all exit 2. The last one is the point:
absence of an answer is never a yes. That is the discipline `hy6.25` cost two days
to learn — a check that could not run must not contribute a pass.

TIER SCOPING IS A BOUND DECISION, NOT A DEFAULT
===============================================
Only IDENTITY-tier builds are gated. `MetaCoding-hy6` records the risk partition:
*"(2) SPINE: bulk port … no per-feature ceremony — build + existing regression +
smoke"* and *"(4) READINGS TRAIL ASYNC — packs recorded behind the builds, nothing
blocks on them."* Duke reaffirmed it on 2026-08-11 (`hy6.51`) after step 8's first
draft reversed it by prose. Spine builds are REPORTED and never gate; widening
this gate means reopening the partition with a reversal condition recorded, not
editing the constant below.

Tier comes from the build directory name (`identity-*` / `spine-*`), which is the
only place the partition is written down in the tree. A build whose tier cannot be
read is reported as UNKNOWN and gates — an unclassifiable build is exactly the one
nobody decided about.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctkr.elenchus import port_workspace  # noqa: E402

IDENTITY, SPINE, UNKNOWN = "identity", "spine", "unknown"


def tier_of(build_name):
    if build_name.startswith("identity-"):
        return IDENTITY
    if build_name.startswith("spine-"):
        return SPINE
    return UNKNOWN


@dataclass
class Build:
    """One port that declares a manifest, and therefore claims it can be driven."""
    name: str
    tier: str
    manifest: str
    seal: str = ""            # what its pack says TODAY
    seal_error: str = ""


@dataclass
class Row:
    build: Build
    state: str = ""           # ok | missing | stale | unclean | undeterminable
    detail: str = ""

    @property
    def gates(self):
        """Spine never gates (bound decision). Everything else gates unless ok."""
        return self.state != "ok"


def current_wave(workspace):
    """The newest `wave*` directory. Scope matters: sweeping every historical wave
    puts retired pilot builds (wave0-pilot, whose packs PACKS.jsonl records as
    RETIRED) permanently in the failing column, and a gate that is always red is
    ignored exactly as fast as one that is always green."""
    runs = os.path.join(workspace, "port_runs")
    waves = sorted(d for d in os.listdir(runs)
                   if d.startswith("wave") and os.path.isdir(os.path.join(runs, d)))
    return waves[-1] if waves else ""


def discover(workspace, wave):
    """Every build in `wave` that declares a manifest, with the seal its pack
    carries now."""
    builds = []
    runs = os.path.join(workspace, "port_runs")
    root = os.path.join(runs, wave) if wave else runs
    for base, _dirs, files in os.walk(root):
        if "port.manifest.json" not in files:
            continue
        rel = os.path.relpath(base, runs).split(os.sep)
        # port_runs/<wave>/<build>/... — the build is the second component.
        name = rel[1] if len(rel) > 1 else rel[0]
        b = Build(name=name, tier=tier_of(name),
                  manifest=os.path.join(base, "port.manifest.json"))
        # The seal lives with the OBSERVATIONS, not with the port: the port must
        # not be able to state which evidence it is judged against.
        build_root = os.path.join(runs, rel[0], name)
        sealp = os.path.join(build_root, "observe", "pack.seal.json")
        try:
            with open(sealp) as fh:
                doc = json.load(fh)
            b.seal = str(doc.get("seal") or "")
            if not b.seal:
                b.seal_error = f"{sealp} carries no `seal`"
        except FileNotFoundError:
            b.seal_error = "no observe/pack.seal.json — this build has no sealed pack"
        except (OSError, ValueError) as exc:
            b.seal_error = f"cannot read {sealp}: {exc}"
        builds.append(b)
    return sorted(builds, key=lambda x: (x.tier, x.name))


def load_verdicts(workspace):
    """Every recorded port-verify report, by the port it names."""
    out, errors = {}, []
    d = os.path.join(workspace, "results", "port-verify")
    if not os.path.isdir(d):
        return out, [f"{d} does not exist — no verdict has ever been recorded"]
    for fn in sorted(os.listdir(d)):
        if not fn.endswith(".json"):
            continue
        path = os.path.join(d, fn)
        try:
            with open(path) as fh:
                doc = json.load(fh)
        except (OSError, ValueError) as exc:
            errors.append(f"{fn}: unreadable ({exc}) — counted as NO verdict, never as one")
            continue
        port = str(doc.get("port") or "")
        if port:
            out.setdefault(port, []).append((fn, doc))
    return out, errors


def _matches(port_field, build_name):
    """`w2-identity-sensor` names `identity-sensor`. Suffix match, because the
    wave prefix is the recorder's convention and the directory is the truth."""
    return port_field == build_name or port_field.endswith(build_name)


def evaluate(builds, verdicts):
    rows = []
    for b in builds:
        r = Row(build=b)
        found = [(fn, doc) for port, lst in verdicts.items() if _matches(port, b.name)
                 for fn, doc in lst]
        if b.seal_error:
            # No pack -> nothing could have been replayed. This is NOT "no verdict
            # needed"; it is the strongest form of undriven.
            r.state = "ok"
            r.detail = b.seal_error
        elif not found:
            r.state = "missing"
            r.detail = f"no verdict names this port (pack seal {b.seal[:12]} is unconsumed)"
        else:
            current = list(found)
            if not current:
                seen = ", ".join(sorted({str(d.get("pack_seal") or "?")[:12] for _, d in found}))
                r.state = "stale"
                r.detail = (f"verdict(s) exist for seal(s) {seen}, but the pack now seals "
                            f"{b.seal[:12]} — the pack was re-recorded and every score "
                            f"taken on the old one is about a pack that no longer exists")
            elif not all(d.get("clean") for _, d in current):
                r.state = "unclean"
                r.detail = ", ".join(fn for fn, d in current if not d.get("clean"))
            else:
                r.state = "ok"
                r.detail = ", ".join(fn for fn, _ in current)
        rows.append(r)
    return rows


def render(rows, extra_errors, all_tiers):
    lines = []
    order = {"missing": 0, "stale": 1, "unclean": 2, "undeterminable": 3, "ok": 4}
    shown = [r for r in rows if all_tiers or r.build.tier != SPINE]
    for r in sorted(shown, key=lambda x: (order[x.state], x.build.name)):
        mark = "ok  " if r.state == "ok" else r.state.upper()[:4]
        gate = "  (advisory — spine, by bound decision)" if r.build.tier == SPINE else ""
        lines.append(f"  {mark:5} [{r.build.tier:8}] {r.build.name}{gate}")
        lines.append(f"          {r.detail}")
    for e in extra_errors:
        lines.append(f"  ERR   {e}")
    ident = [r for r in rows if r.build.tier != SPINE]
    blocking = [r for r in ident if r.gates]
    lines.append("")
    lines.append(f"{len(rows)} build(s) declare a manifest; "
                 f"{len(ident)} gate (identity/unknown), {len(rows) - len(ident)} advisory (spine).")
    lines.append(f"{len(blocking)} gating build(s) lack a current, clean verdict.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--wave", default=None,
                    help="which wave to gate. Defaults to the newest wave* directory; "
                         "earlier waves hold retired pilot builds and gating on them "
                         "would make this permanently red.")
    ap.add_argument("--all-tiers", action="store_true",
                    help="report spine builds too. They still never gate — that is a "
                         "bound decision (MetaCoding-hy6, reaffirmed hy6.51), not a flag.")
    args = ap.parse_args(argv)

    workspace = port_workspace(args.workspace)
    print(f"verdict currency: {workspace}")
    wave = args.wave or current_wave(workspace)
    print(f"wave: {wave or '(all)'}")
    builds = discover(workspace, wave)
    if False:
        # An empty sweep is the classic vacuous pass: no builds found reads exactly
        # like every build verified. Refuse instead.
        print(f"REFUSING: found no port.manifest.json under port_runs/{wave}. "
              "Either the workspace is wrong or the discovery is broken; neither is "
              "a clean bill of health.", file=sys.stderr)
        return 2
    verdicts, errors = load_verdicts(workspace)
    rows = evaluate(builds, verdicts)
    print(render(rows, errors, args.all_tiers))

    blocking = [r for r in rows if r.gates]
    if blocking:
        print("\nREFUSING: these builds declare a bridge and have no current, clean "
              "verdict of record.\n"
              "  Recipe step 8: an identity-tier build with a bridge and no recorded "
              "verdict is not done.\n"
              "  Run: ctkr port-verify <build>/observe/fixtures.jsonl --port <build dir> "
              "--json > results/port-verify/<build>.json\n"
              "  " + ", ".join(r.build.name for r in blocking), file=sys.stderr)
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
