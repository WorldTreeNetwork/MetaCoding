"""``ctkr port-verify`` — replay an observed fixture pack against a built port.

The mechanical counterpart to ``ctkr oracle-verify``. Where that one re-runs
recorded fixtures against the system they were recorded from (self-verification),
this one runs them against a **port** — a from-scratch build — through the port's
own declared bridge, and reports what the port answers, what it cannot be asked
at all, and where it deliberately differs.

The report never collapses to one number. ``coverage`` (answered ÷ total) and
``value`` (right ÷ scored-answered) are printed together because a build that
answers two of thirty assertions correctly is not a 93% build, and the raw
fraction that says it is was the defect this command exists to kill.

Exit codes::

    0  every scored assertion passed or diverged as declared, nothing unanswerable
    1  at least one value failure
    2  usage / contract / bridge error (nothing was judged)
    3  no failures, but the verdict is incomplete: gaps or bad declarations
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.oracle.pack import PackError, load_pack
from ctkr.oracle.port_adapter import BridgeError, PortAdapter
from ctkr.oracle.port_contract import (
    DEFAULT_DECISION_SOURCES,
    ContractError,
    PortManifest,
    load_decisions,
)


def _repo_root() -> Path:
    """The repo root, from this file's location (ctkr/ctkr/commands/…)."""
    return Path(__file__).resolve().parents[3]
from ctkr.oracle.port_verify import AssertionStatus, PortVerifyReport, verify_port

_MARK = {
    AssertionStatus.PASSED: "PASS",
    AssertionStatus.FAILED: "FAIL",
    AssertionStatus.DIVERGED: "DIVG",
    AssertionStatus.NO_VERDICT: "NONE",
}


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "port-verify",
        help="Replay an observed fixture pack against a built port (mechanical JUDGE).",
        description=(
            "Execute a recorded semantic-fixture pack against a port through the "
            "port's declared bridge. Reports passed / failed / sanctioned-"
            "divergence / NO VERDICT separately. The pack is loaded WHOLE and "
            "checked against the seal its recorder wrote: a subset, an edited "
            "value, or a stale derivation yields no verdict at all. An assertion "
            "no declared probe can answer, one the port declines at run time, and "
            "one whose recorded value is an unvalidated derivation of ours all "
            "reach NO VERDICT — never a pass."
        ),
    )
    p.add_argument("fixtures", help="Path to the observed semantic-fixture JSONL pack.")
    p.add_argument("--port", required=True,
                   help="Port directory containing port.manifest.json (or the "
                        "manifest file itself).")
    # There is deliberately NO --marks and NO --decisions. Both were pens the
    # party being judged could hold: --marks let a caller declare which evidence
    # counts, and --decisions let a port author point the sanction resolver at a
    # registry they had just written. Evidence quality comes from the sealed
    # pack; decisions come from the repo, at a fixed path.
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="Emit the full report as JSON on stdout.")
    p.add_argument("--show-passes", action="store_true",
                   help="List passing assertions too (failures, divergences and "
                        "gaps are always listed).")
    p.set_defaults(func=run)


def _emit_text(report: PortVerifyReport) -> None:
    s = report.score
    w = sys.stderr.write
    w(
        f"\n  port            : {report.port}\n"
        f"  pack            : {report.pack_id or '(unsealed)'}  seal {report.pack_seal[:16]}\n"
        f"  fixtures        : {s.fixtures_total}"
        f" ({s.fixtures_unrunnable} could not run,"
        f" {s.fixtures_excluded} corroboration-only,"
        f" {s.fixtures_invalid} INVALID EVIDENCE)\n"
        f"  assertions      : {s.assertions_total}\n"
        f"  answered        : {s.answered}\n"
        f"  NO VERDICT      : {s.no_verdict}   <- never passes, always blocks clean\n"
        + "".join(f"      - {n} x {cause}\n"
                 for cause, n in sorted(s.no_verdict_by_cause.items()))
        +
        f"  scored          : {s.scored_answered}"
        f"   ({s.excluded_corroboration} answered but excluded from scoring)\n"
        f"    passed        : {s.scored_passed}\n"
        f"    diverged (ok) : {s.scored_diverged}\n"
        f"    failed        : {s.scored_failed}\n"
        f"  coverage        : {s.answered}/{s.assertions_total} = {s.coverage:.1%}\n"
        f"  reproduced      : "
        + (
            "NOTHING SCORED — this run is evidence of nothing\n"
            if s.scored_nothing
            else f"{s.scored_passed}/{s.scored_answered - s.scored_diverged}"
                 f" = {s.value_score:.1%}"
                 f"   (sanctioned divergences are NOT counted as passes)\n"
        )
        + f"  verdict         : {s.headline()}\n"
    )
    if report.needs_review:
        w("  NOT A CLEAN PASS:\n")
        for why in report.needs_review:
            w(f"    - {why}\n")
    for problem in report.declaration_problems:
        w(f"    ! declaration problem: {problem}\n")
    for bad in report.invalid_evidence:
        w(f"    ! INVALID EVIDENCE: {bad}\n")
    w("\n")
    return None


def _emit_detail(report: PortVerifyReport, show_passes: bool) -> None:
    w = sys.stderr.write
    for v in report.verdicts:
        flags = []
        if not v.scored:
            flags.append("corroboration-only, EXCLUDED from score")
        if not v.ran:
            flags.append("did not run")
        w(f"  {v.title}{'  [' + '; '.join(flags) + ']' if flags else ''}\n")
        if v.error:
            w(f"      ! {v.error.splitlines()[0]}\n")
        for o in v.outcomes:
            if o.status == AssertionStatus.PASSED and not show_passes:
                continue
            w(f"      [{_MARK[o.status]}] {o.assertion}({o.subject}) "
              f"expected {o.op} {o.expected!r}, got {o.actual!r}"
              f"{' - ' + o.detail if o.detail else ''}"
              f"{f' [decision {o.decision_id}]' if o.decision_id else ''}\n")
    if report.declaration_problems:
        w("\n  DECLARATION PROBLEMS (a wrong declaration is not a divergence):\n")
        for problem in report.declaration_problems:
            w(f"      ! {problem}\n")
    w("\n")


def run(args: argparse.Namespace) -> int:
    try:
        manifest = PortManifest.load(args.port)
    except ContractError as exc:
        sys.stderr.write(f"\n{exc}\n")
        return 2

    # The pack is loaded WHOLE and verified against its recorder-written seal.
    # A pack that is not the pack the recorder sealed yields no verdict at all —
    # a subset, an edited expected value, or an unresolvable witness stops here.
    try:
        pack = load_pack(args.fixtures)
    except (OSError, ValueError, PackError) as exc:
        sys.stderr.write(f"\n  NO VERDICT — the evidence is not sound:\n  {exc}\n")
        return 2

    decisions = load_decisions(_repo_root() / s for s in DEFAULT_DECISION_SOURCES)
    if not decisions:
        sys.stderr.write(
            "\n  no decision registry found at the repo path — every cited "
            "decision_id will be reported as unresolvable.\n"
        )

    adapter = PortAdapter(manifest)
    try:
        report = verify_port(adapter, pack, manifest, decisions)
    except BridgeError as exc:
        sys.stderr.write(f"\n  port bridge unusable: {exc}\n")
        return 2

    if args.as_json:
        sys.stdout.write(report.model_dump_json(indent=2) + "\n")
        _emit_text(report)
    else:
        _emit_text(report)
        _emit_detail(report, args.show_passes)

    if report.score.scored_failed:
        return 1
    # Exit 0 means "reproduced the source, with nothing excused and nothing
    # missing". Anything short of that is 3 — including a run that sanctioned or
    # excluded its way to zero failures.
    return 0 if report.clean else 3
