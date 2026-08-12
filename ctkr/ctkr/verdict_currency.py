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

ONE MANIFEST IS ONE BUILD, AND ONE VERDICT SATISFIES ONE BUILD
==============================================================
`MetaCoding-hy6.57`: this file used to name a build after the second path
component, so `spine-asset/build/{compost,equipment,…}` — seven ported packages —
collapsed into ONE row with ONE seal and ONE verdict lookup. One verdict would
have marked seven packages verified, and a per-package verdict was not even
representable. Builds are now keyed by `<wave>/<path under the wave>`, so every
manifest is its own row and the headline counts what it names.

Matching is EXACT, against identifiers that distinguish one build from every
other: the `port` id the manifest declares, or the build key. It used to be
`endswith`, under which `w2-identity-land` also satisfied builds named `land` and
`entity-land`, and nothing constrained a verdict to its wave. A judge replaced
that body with `return True` — any verdict satisfies any build — and all thirteen
tests still passed. If two builds declare the same port id, neither is scored:
an ambiguous identifier is not an identifier.

TIER SCOPING IS A BOUND DECISION, NOT A DEFAULT
===============================================
Only IDENTITY-tier builds are gated. `MetaCoding-hy6` records the risk partition:
*"(2) SPINE: bulk port … no per-feature ceremony — build + existing regression +
smoke"* and *"(4) READINGS TRAIL ASYNC — packs recorded behind the builds, nothing
blocks on them."* Duke reaffirmed it on 2026-08-11 (`hy6.51`). Spine builds are
REPORTED and never gate; widening this gate means reopening the partition with a
reversal condition recorded, not editing the constant below.

The partition itself is RECORDED DATA — `results/*/partition-*.jsonl`, one row per
module, each with an explicit `tier`. That is what is read. It used to be read off
the directory NAME (`identity-*` / `spine-*`), and `hy6.55` showed what a proxy for
a bound decision costs: the name rule called `quick-folds` UNKNOWN while both
recorded partitions call all five `quick/*` modules IDENTITY, and outside wave 2
the rule collapses entirely (`activity/`, `harvest/`, `input/`, `observation/` are
all UNKNOWN to it, where the partition says three are spine and one is identity).

The name rule survives only as a FALLBACK for builds the partition does not name,
and every row says which source decided it. A build tiered by the fallback is
visible as such, because deciding a bound question by a proxy is the defect.

A PARTITION THAT NAMES NOTHING IS NOT A PARTITION (`MetaCoding-hy6.60`)
======================================================================
`main()` refused a vacuous SWEEP and not a vacuous RECORD. With the two
`partition-*.jsonl` files present but truncated to zero bytes, the gate reported
`40 build(s) were tiered by the FALLBACK name rule`, moved three builds' gating
status, and refused nothing — i.e. a rename, a bad glob or an unsynced `results/`
hands the bound risk decision for every build back to the directory name, which
is verbatim `hy6.55`'s defect restored. A partition file that exists and names no
module now REFUSES. A partition that is genuinely ABSENT still falls back, and
still says so on every row: there is a difference between "nobody wrote a record"
and "the record I am reading is empty", and only the second is a broken instrument.

The tier VOCABULARY is closed for the same reason. `{"module": "asset/land",
"tier": "SPINE"}` used to be accepted verbatim and printed as `the recorded
partition says SPINE` — the gate could not distinguish "the record says spine"
from "the record says a word I do not recognise". A tier outside
`identity|spine|unknown` is now an ERROR, and the module it names resolves to
UNKNOWN, which gates: absence of an answer is never a yes.

`hy6.51`'s prose enumeration lists `quick-folds` among the spine builds; the
recorded partition says identity. The gate follows the RECORD and prints the
disagreement rather than quietly picking — reconciling the two is `hy6.55`'s job,
not this file's.

WAVE SCOPING FOLLOWS THE RETIREMENT RECORD, NOT RECENCY
=======================================================
This gate used to sweep only the newest `wave*` directory, justified by wave0's
retired pilot packs. `hy6.56`: `port_runs/PACKS.jsonl` retires exactly two packs,
both wave0, and its own reason text calls wave1 a LIVE lane — while the recency
rule silently exempted wave1 (4 manifests) and wave1-c1 (2), each holding a sealed
pack and no verdict of record. An exclusion justified by wave0-pilot's retirement
excludes wave0-pilot. Every wave is now swept, and a build is exempt only when the
seal its pack carries today is one PACKS.jsonl records as RETIRED. `--wave` still
narrows the sweep by hand.
"""

from __future__ import annotations

import argparse
import glob
import json
import os
import sys
from dataclasses import dataclass, field

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from ctkr.elenchus import port_workspace  # noqa: E402

IDENTITY, SPINE, UNKNOWN = "identity", "spine", "unknown"

#: The closed tier vocabulary, ordered by HOW MUCH EACH ONE GATES. `spine` is
#: advisory, `identity` gates, and `unknown` gates and additionally means nobody
#: decided — the strictest reading, because absence of an answer is never a yes.
TIER_RANK = {SPINE: 0, IDENTITY: 1, UNKNOWN: 2}

NAME_RULE = "directory name (FALLBACK — the partition does not name this build)"


def tier_of(build_name):
    """The FALLBACK rule. Only consulted for builds the recorded partition does
    not name; it is a proxy, and `hy6.55` is the record of what it cost."""
    leaf = build_name.split("/")[-1] if "/" in build_name else build_name
    for candidate in (build_name, leaf):
        if candidate.startswith("identity-"):
            return IDENTITY
        if candidate.startswith("spine-"):
            return SPINE
    return UNKNOWN


# ---------------------------------------------------------------------------
# the recorded risk partition
# ---------------------------------------------------------------------------

@dataclass
class Partition:
    """`results/*/partition-*.jsonl` — the risk partition as DATA, one row per
    module. Two files that disagree about a module do not get averaged: the
    module resolves to UNKNOWN, because a gate is not the place a contradiction
    gets quietly resolved."""
    tier_by_module: dict = field(default_factory=dict)
    modules_by_cluster: dict = field(default_factory=dict)
    files: list = field(default_factory=list)
    errors: list = field(default_factory=list)

    def __bool__(self):
        return bool(self.tier_by_module)

    def unanimous(self, modules):
        tiers = {self.tier_by_module.get(m, UNKNOWN) for m in modules}
        if len(tiers) == 1:
            return tiers.pop()
        return UNKNOWN


def load_partition(workspace):
    """Every recorded partition row, keyed by module."""
    p = Partition()
    seen = {}
    for path in sorted(glob.glob(os.path.join(workspace, "results", "*",
                                              "partition-*.jsonl"))):
        p.files.append(path)
        try:
            with open(path) as fh:
                lines = fh.readlines()
        except OSError as exc:
            p.errors.append(f"cannot read {path}: {exc}")
            continue
        for n, line in enumerate(lines, 1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except ValueError as exc:
                p.errors.append(f"{os.path.basename(path)}:{n}: unreadable ({exc})")
                continue
            module, tier = str(row.get("module") or ""), str(row.get("tier") or "")
            if not module or not tier:
                continue
            if tier not in TIER_RANK:
                # A CLOSED VOCABULARY (hy6.60). `"SPINE"` used to be recorded
                # verbatim and printed as if it were a tier. It gates either way
                # — only the exact string `spine` disables gating — but a gate
                # that cannot tell "the record says spine" from "the record says
                # a word I do not recognise" is not reading the record.
                p.errors.append(
                    f"{os.path.basename(path)}:{n}: {tier!r} is not a tier — the "
                    f"vocabulary is {'|'.join(sorted(TIER_RANK))}. {module} is "
                    "recorded as UNKNOWN, which gates: a tier nobody can read is "
                    "not a decision.")
                tier = UNKNOWN
            seen.setdefault(module, set()).add(tier)
            cluster = str(row.get("cluster") or "")
            if cluster:
                p.modules_by_cluster.setdefault(cluster, [])
                if module not in p.modules_by_cluster[cluster]:
                    p.modules_by_cluster[cluster].append(module)
    for module, tiers in seen.items():
        if len(tiers) == 1:
            p.tier_by_module[module] = tiers.pop()
        else:
            p.tier_by_module[module] = UNKNOWN
            p.errors.append(f"partition rows disagree about {module}: "
                            f"{', '.join(sorted(tiers))} — recorded as UNKNOWN, "
                            "because a gate must not pick between two records")
    return p


def _norm(s):
    return s.replace("-", "_")


def _candidate_lookups(partition, dirname, package, feature):
    """Ordered ways to find a build's modules in the RECORDED partition. The
    first lookup that names any module decides, and its label is printed."""
    tails = lambda s: [m for m in partition.tier_by_module
                       if m.split("/")[-1] == _norm(s)]
    out = []
    if feature:
        out.append((f"manifest declares module {feature}",
                    [feature] if feature in partition.tier_by_module else []))
    if package:
        out.append((f"cluster {dirname} / package {package}",
                    [m for m in partition.modules_by_cluster.get(dirname, ())
                     if m.split("/")[-1] == _norm(package)]))
        out.append((f"module tail {package}", tails(package)))
    out.append((f"cluster {dirname}",
                list(partition.modules_by_cluster.get(dirname, ()))))
    slug = dirname
    for word in ("identity-", "spine-"):
        if slug.startswith(word):
            slug = slug[len(word):]
            break
    as_module = _norm(slug.replace("-", "/", 1))
    out.append((f"module {as_module}",
                [as_module] if as_module in partition.tier_by_module else []))
    out.append((f"module tail {slug}", tails(slug)))
    family = dirname.split("-")[0]
    out.append((f"module family {family}/*",
                [m for m in partition.tier_by_module if m.split("/")[0] == family]))
    return out


def resolve_tier(partition, dirname, package="", feature=""):
    """(tier, source). The partition is the source of truth; the directory name
    is consulted only when no recorded row names this build."""
    for how, modules in _candidate_lookups(partition, dirname, package, feature):
        if not modules:
            continue
        tier = partition.unanimous(modules)
        detail = ", ".join(sorted(modules)[:4]) + ("…" if len(modules) > 4 else "")
        if tier == UNKNOWN:
            return UNKNOWN, f"partition via {how} — rows disagree ({detail})"
        return tier, f"partition via {how} ({detail})"
    return tier_of(dirname), NAME_RULE


# ---------------------------------------------------------------------------
# the retirement record
# ---------------------------------------------------------------------------

def load_retirements(workspace):
    """Seals `port_runs/PACKS.jsonl` records as RETIRED, **with the scope they
    retire**, as {seal: (reason, wave)}. This — not directory recency — is what
    exempts a build.

    THE SCOPE IS REQUIRED, AND THAT IS THE WHOLE FIX (MetaCoding-hy6.58). The
    first version keyed exemption on the seal STRING ALONE, unscoped by wave,
    build or date. A fresh judge copied wave0-pilot's 40-byte `pack.seal.json`
    into a brand-new build in a brand-new wave and the gate reported
    "1 exempt (pack RETIRED) ... of the 0 live" and EXITED 0 on a build with no
    verdict anywhere. `_find_seal` ascends directories on purpose (wave1-c1
    shares one pack across portA/portB), so any manifest dropped under a wave
    root holding a retired seal inherited the exemption silently.

    A RETIREMENT ROW WITH NO SCOPE NOW EXEMPTS NOTHING. That direction is not
    arbitrary: the retirement reason on both live rows is "fixtures no longer
    re-hash", i.e. the pack CANNOT BE REPLAYED — the strongest form of "we did
    not learn the answer", which everywhere else in this file gates. An unscoped
    retirement is a skeleton key, and absence of an answer is never a yes.
    """
    out, errors = {}, []
    path = os.path.join(workspace, "port_runs", "PACKS.jsonl")
    if not os.path.isfile(path):
        return out, errors
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except OSError as exc:
        return out, [f"cannot read {path}: {exc} — nothing is treated as retired"]
    for n, line in enumerate(lines, 1):
        if not line.strip():
            continue
        try:
            row = json.loads(line)
        except ValueError as exc:
            errors.append(f"PACKS.jsonl:{n}: unreadable ({exc}) — "
                          "not treated as a retirement")
            continue
        if str(row.get("record") or "") != "retirement":
            continue
        seal = str(row.get("seal") or "")
        if not seal:
            continue
        reason = str(row.get("reason") or "(no reason recorded)")
        scope = row.get("scope") or {}
        wave = str(scope.get("wave") or "") if isinstance(scope, dict) else ""
        if not wave:
            errors.append(
                f"PACKS.jsonl:{n}: retirement of seal {seal[:12]} names no "
                f"scope.wave — it exempts NOTHING. A retirement without a scope "
                f"is a skeleton key: any build in any wave carrying a copy of "
                f"that seal file would be excused. Add "
                f'"scope": {{"wave": "<the wave this pack belongs to>"}}.')
            continue
        out[seal] = (reason, wave)
    return out, errors


# ---------------------------------------------------------------------------
# discovery
# ---------------------------------------------------------------------------

@dataclass
class Build:
    """One port that declares a manifest, and therefore claims it can be driven.
    One manifest, one build: `<wave>/<path under the wave>` names it."""
    name: str
    tier: str
    tier_source: str
    manifest: str
    #: The wave this build lives in. Carried rather than re-split out of `name`
    #: at the use site: a retirement is scoped BY WAVE (MetaCoding-hy6.58), so
    #: this is decision input, not display.
    wave: str = ""

    dirname: str = ""         # the build directory the old name rule would read
    port_id: str = ""         # the id its manifest declares
    seal: str = ""            # what its pack says TODAY
    seal_error: str = ""
    id_error: str = ""
    retired_reason: str = ""


def _find_seal(runs, wave, parts):
    """The seal for a manifest at `<wave>/<parts>`: the nearest `observe/
    pack.seal.json` at or above the manifest, up to the wave root. A pack shared
    by a whole wave (wave1-c1) and a `X-build`/`X-observe` pair (wave0-pilot) are
    both real conventions in this tree."""
    for depth in range(len(parts), -1, -1):
        base = os.path.join(runs, wave, *parts[:depth])
        cand = os.path.join(base, "observe", "pack.seal.json")
        if os.path.isfile(cand):
            return cand
        if base.endswith("-build"):
            cand = base[: -len("-build")] + "-observe/pack.seal.json"
            if os.path.isfile(cand):
                return cand
    return ""


def discover(workspace, wave=None, partition=None, retired=None):
    """Every manifest in the workspace (or in `wave`), with the tier the recorded
    partition gives it and the seal its pack carries now."""
    partition = partition if partition is not None else Partition()
    retired = retired or {}
    builds = []
    runs = os.path.join(workspace, "port_runs")
    root = os.path.join(runs, wave) if wave else runs
    for base, _dirs, files in os.walk(root):
        if "port.manifest.json" not in files:
            continue
        manifest = os.path.join(base, "port.manifest.json")
        rel = os.path.relpath(base, runs).split(os.sep)
        this_wave, parts = rel[0], rel[1:]
        # `build/` is scaffolding, not identity — drop it from the key so the
        # row reads `wave2/spine-asset/compost`.
        key_parts = [p for p in parts if p != "build"]
        dirname = key_parts[0] if key_parts else this_wave
        package = "/".join(key_parts[1:])
        name = "/".join([this_wave] + (key_parts or [this_wave]))

        port_id, feature, doc_error = "", "", ""
        try:
            with open(manifest) as fh:
                doc = json.load(fh)
            port_id = str(doc.get("port") or "")
            feature = str(doc.get("feature") or "")
        except (OSError, ValueError) as exc:
            doc_error = f"cannot read {manifest}: {exc}"

        tier, source = resolve_tier(partition, dirname, package, feature)
        b = Build(name=name, tier=tier, tier_source=source, manifest=manifest,
                  wave=this_wave, dirname=dirname, port_id=port_id)
        if doc_error:
            b.id_error = doc_error + " — its declared port id is unreadable"

        sealp = _find_seal(runs, this_wave, parts)
        if not sealp:
            b.seal_error = "no observe/pack.seal.json — this build has no sealed pack"
        else:
            try:
                with open(sealp) as fh:
                    b.seal = str(json.load(fh).get("seal") or "")
                if not b.seal:
                    b.seal_error = f"{sealp} carries no `seal`"
            except (OSError, ValueError) as exc:
                b.seal_error = f"cannot read {sealp}: {exc}"
        if b.seal and b.seal in retired:
            reason, scope_wave = retired[b.seal]
            # THE SCOPE CHECK (MetaCoding-hy6.58). The retirement excuses the
            # wave it names and no other. A build carrying a copy of a retired
            # seal from somewhere else is NOT excused — it is a build whose pack
            # cannot be replayed, which gates.
            if b.wave == scope_wave:
                b.retired_reason = reason
            else:
                b.seal_error = (
                    f"carries seal {b.seal[:12]}, which PACKS.jsonl retires FOR "
                    f"{scope_wave!r} — this build is in {b.wave!r}. A retired "
                    f"pack cannot be replayed, so outside the wave it was "
                    f"retired for it is not an exemption, it is an unanswerable "
                    f"build.")
        builds.append(b)

    # An ambiguous identifier is not an identifier: if two builds declare the
    # same port id, a verdict naming it cannot be attributed to either.
    counts = {}
    for b in builds:
        if b.port_id:
            counts.setdefault(b.port_id, []).append(b.name)
    for b in builds:
        others = [n for n in counts.get(b.port_id, []) if n != b.name]
        if others:
            b.id_error = (f"port id {b.port_id!r} is also declared by "
                          f"{', '.join(sorted(others))} — no verdict can be "
                          "attributed to one of them")
    return sorted(builds, key=lambda x: (x.tier, x.name))


# ---------------------------------------------------------------------------
# verdicts
# ---------------------------------------------------------------------------

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


def _matches(port_field, build):
    """EXACT, against identifiers that distinguish this build from every other:
    the port id its manifest declares, or its `<wave>/<path>` key. This was a
    suffix test, under which one verdict satisfied every build whose name it
    ended with, across waves (`hy6.57`)."""
    if not port_field:
        return False
    return port_field == build.port_id or port_field == build.name


@dataclass
class Row:
    build: Build
    state: str = ""           # ok | missing | stale | unclean | undeterminable | retired
    detail: str = ""

    @property
    def gates(self):
        """Retired packs and spine never gate. Retirement is a RECORD
        (PACKS.jsonl), spine is a BOUND DECISION (hy6). Everything else gates
        unless ok."""
        if self.build.retired_reason:
            return False
        if self.build.tier == SPINE:
            return False
        return self.state != "ok"


def gating_rows(rows):
    """THE blocking population — one definition, read by both the report and the
    exit code (`MetaCoding-hy6.59` J10). `hy6.53` was exactly a divergence between
    the population the headline counted and the population the exit was taken
    from; the divergence was fixed and then nothing bound the two together, so a
    judge could blank the report's count and the suite noticed nothing."""
    return [r for r in rows if r.gates]


def evaluate(builds, verdicts):
    rows = []
    for b in builds:
        r = Row(build=b)
        found = [(fn, doc) for port, lst in verdicts.items() if _matches(port, b)
                 for fn, doc in lst]
        if b.retired_reason:
            r.state = "retired"
            r.detail = f"pack {b.seal[:12]} is RETIRED in PACKS.jsonl: {b.retired_reason[:120]}"
        elif b.id_error:
            r.state = "undeterminable"
            r.detail = b.id_error
        elif b.seal_error:
            # No pack -> nothing could have been replayed. This is NOT "no verdict
            # needed"; it is the strongest form of undriven.
            r.state = "undeterminable"
            r.detail = b.seal_error
        elif not found:
            r.state = "missing"
            r.detail = f"no verdict names this port (pack seal {b.seal[:12]} is unconsumed)"
        else:
            current = [(fn, d) for fn, d in found if str(d.get("pack_seal") or "") == b.seal]
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
    order = {"missing": 0, "stale": 1, "unclean": 2, "undeterminable": 3,
             "ok": 4, "retired": 5}
    shown = [r for r in rows if all_tiers or r.build.tier != SPINE]
    for r in sorted(shown, key=lambda x: (order[x.state], x.build.name)):
        mark = "ok  " if r.state == "ok" else r.state.upper()[:4]
        if r.build.retired_reason:
            gate = "  (exempt — pack RETIRED in PACKS.jsonl)"
        elif r.build.tier == SPINE:
            gate = "  (advisory — spine, by bound decision)"
        else:
            gate = ""
        lines.append(f"  {mark:5} [{r.build.tier:8}] {r.build.name}{gate}")
        lines.append(f"          tier: {r.build.tier_source}")
        lines.append(f"          {r.detail}")

    # Where the RECORD and the old proxy disagree, say so. This gate is not the
    # place either one quietly wins (hy6.55).
    disagree = sorted({(r.build.dirname, r.build.tier) for r in rows
                       if r.build.tier_source != NAME_RULE
                       and tier_of(r.build.dirname) != r.build.tier})
    for dirname, tier in disagree:
        lines.append(f"  NOTE  {dirname}: the recorded partition says {tier}, the "
                     f"directory name says {tier_of(dirname)} — the record decides "
                     "here; reconciling them is hy6.55's job.")
    for e in extra_errors:
        lines.append(f"  ERR   {e}")

    live = [r for r in rows if not r.build.retired_reason]
    ident = [r for r in live if r.build.tier != SPINE]
    blocking = gating_rows(rows)
    fallback = [r for r in live if r.build.tier_source == NAME_RULE]
    lines.append("")
    lines.append(f"{len(rows)} build(s) declare a manifest — one row per manifest; "
                 f"{len(rows) - len(live)} exempt (pack RETIRED).")
    lines.append(f"of the {len(live)} live: {len(ident)} gate (identity/unknown), "
                 f"{len(live) - len(ident)} advisory (spine).")
    lines.append(f"{len(fallback)} build(s) were tiered by the FALLBACK name rule "
                 "(the partition does not name them).")
    lines.append(f"{len(blocking)} gating build(s) lack a current, clean verdict.")
    return "\n".join(lines)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--workspace", default=None)
    ap.add_argument("--wave", default=None,
                    help="narrow the sweep to one wave. Default: every wave. "
                         "Exemption comes from PACKS.jsonl's retirement record, "
                         "not from a directory being old (hy6.56).")
    ap.add_argument("--all-tiers", action="store_true",
                    help="report spine builds too. They still never gate — that is a "
                         "bound decision (MetaCoding-hy6, reaffirmed hy6.51), not a flag.")
    args = ap.parse_args(argv)

    workspace = port_workspace(args.workspace)
    print(f"verdict currency: {workspace}")
    partition = load_partition(workspace)
    retired, retire_errors = load_retirements(workspace)
    print(f"wave: {args.wave or '(all, minus RETIRED packs)'}")
    print(f"partition: {len(partition.tier_by_module)} module row(s) from "
          f"{len(partition.files)} file(s); retirement record: {len(retired)} seal(s)")
    if partition.files and not partition.tier_by_module:
        # A VACUOUS RECORD, symmetric with the vacuous sweep below (hy6.60). The
        # partition files are THERE and name nothing, so every build would fall
        # back to the directory-name proxy — which is hy6.55's defect restored,
        # and it moved three builds' gating status when it was measured. A gate
        # that cannot read the record it says it decides by is not entitled to an
        # exit code for the right reason.
        for e in partition.errors:
            print(f"  ERR   {e}", file=sys.stderr)
        print("REFUSING: the recorded partition names no module, but its file(s) are "
              f"present: {', '.join(partition.files)}. Falling back to the directory "
              "name for every build hands a bound risk decision back to a proxy "
              "(hy6.55). A truncated, mis-globbed or unsynced partition is not a "
              "clean bill of health.", file=sys.stderr)
        return 2
    builds = discover(workspace, args.wave, partition, retired)
    if not builds:
        # An empty sweep is the classic vacuous pass: no builds found reads exactly
        # like every build verified. Refuse instead.
        print(f"REFUSING: found no port.manifest.json under port_runs/{args.wave or ''}. "
              "Either the workspace is wrong or the discovery is broken; neither is "
              "a clean bill of health.", file=sys.stderr)
        return 2
    verdicts, errors = load_verdicts(workspace)
    rows = evaluate(builds, verdicts)
    print(render(rows, errors + retire_errors + partition.errors, args.all_tiers))

    blocking = gating_rows(rows)
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
