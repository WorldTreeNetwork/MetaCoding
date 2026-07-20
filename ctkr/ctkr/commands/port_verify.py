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

from ctkr.oracle.fixtures import load_fixtures
from ctkr.oracle.port_adapter import BridgeError, PortAdapter
from ctkr.oracle.port_contract import (
    DEFAULT_DECISION_SOURCES,
    ContractError,
    PortManifest,
    load_decision_ids,
    load_marks,
)


def _repo_root() -> Path:
    """The repo root, from this file's location (ctkr/ctkr/commands/…)."""
    return Path(__file__).resolve().parents[3]
from ctkr.oracle.port_verify import AssertionStatus, PortVerifyReport, verify_port

_MARK = {
    AssertionStatus.PASSED: "PASS",
    AssertionStatus.FAILED: "FAIL",
    AssertionStatus.DIVERGED: "DIVG",
    AssertionStatus.UNANSWERABLE: "GAP ",
}


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "port-verify",
        help="Replay an observed fixture pack against a built port (mechanical JUDGE).",
        description=(
            "Execute a recorded semantic-fixture pack against a port through the "
            "port's declared bridge. Reports passed / failed / sanctioned-"
            "divergence / UNANSWERABLE separately: an assertion no declared probe "
            "can answer is a gap, never a pass, and corroboration-only fixtures "
            "are reported but excluded from the value score."
        ),
    )
    p.add_argument("fixtures", help="Path to the observed semantic-fixture JSONL pack.")
    p.add_argument("--port", required=True,
                   help="Port directory containing port.manifest.json (or the "
                        "manifest file itself).")
    p.add_argument("--marks", default="",
                   help="Optional fixture-marks file (JSON or JSONL) marking "
                        "fixtures corroboration-only / order-sensitive. Kept "
                        "outside the pack: a recorded pack is evidence.")
    p.add_argument("--decisions", default="",
                   help="Decision registry (JSONL) that divergence decision_ids "
                        "must resolve against. Defaults to the kernel CM registry.")
    p.add_argument("--no-decision-check", action="store_true",
                   help="Do not resolve divergence decision_ids (not recommended: "
                        "an unresolvable sanction is how a wrong value gets waved "
                        "through).")
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
        f"  fixtures        : {s.fixtures_total}"
        f" ({s.fixtures_unrunnable} could not run,"
        f" {s.fixtures_excluded} corroboration-only)\n"
        f"  assertions      : {s.assertions_total}\n"
        f"  answered        : {s.answered}\n"
        f"  UNANSWERABLE    : {s.unanswerable}   <- declared gaps, not passes\n"
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
    if report.marks_source:
        w(f"  marks           : {s.fixtures_excluded} fixture(s) excluded via "
          f"{report.marks_source}\n")
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

    try:
        fixtures = load_fixtures(args.fixtures)
    except (OSError, ValueError) as exc:
        sys.stderr.write(f"\n{exc}\n")
        return 2

    marks = []
    if args.marks:
        try:
            marks = load_marks(args.marks)
        except (OSError, ContractError, ValueError) as exc:
            sys.stderr.write(f"\n{exc}\n")
            return 2

    # Resolve the decision ids a divergence may cite. Unless the caller opts out
    # explicitly, an unresolvable sanction is a declaration problem.
    known_ids: set[str] | None = None
    if not args.no_decision_check:
        sources = (
            [args.decisions] if args.decisions
            else [_repo_root() / s for s in DEFAULT_DECISION_SOURCES]
        )
        known_ids = load_decision_ids(sources)
        if not known_ids:
            sys.stderr.write(
                "\n  no decision registry found — divergence decision_ids cannot be "
                "resolved. Pass --decisions <file>, or --no-decision-check to accept "
                "unverified sanctions (they will still be reported).\n"
            )

    adapter = PortAdapter(manifest)
    try:
        report = verify_port(adapter, fixtures, manifest, marks,
                             fixtures_path=str(args.fixtures),
                             known_decision_ids=known_ids)
    except BridgeError as exc:
        sys.stderr.write(f"\n  port bridge unusable: {exc}\n")
        return 2
    report.marks_source = str(args.marks) if args.marks else ""

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
