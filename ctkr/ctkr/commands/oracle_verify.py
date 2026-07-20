"""``ctkr oracle-verify`` — verify semantic fixtures against an implementation.

Runs a semantic-fixture pack through an implementation's adapter and reports
pass/fail per fixture. The default adapter is ``farmos`` (the live JSON:API
boundary); running the *recorded-from-farmOS* fixtures against the same farmOS is
**self-verification** — the acceptance test of the oracle itself. Any other
implementation supplies its own adapter and the pass rate is its value-
equivalence score against the source.
"""

from __future__ import annotations

import argparse
import json
import sys

from ctkr.oracle.fixtures import load_fixtures
from ctkr.oracle.health import DEFAULT_TIMEOUT, OracleDown, require_oracle
from ctkr.oracle.runner import run_fixtures


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "oracle-verify",
        help="Verify semantic fixtures against an implementation adapter (Phase 2).",
        description=(
            "Execute value-equivalence semantic fixtures against an "
            "implementation through its adapter and report pass/fail per fixture. "
            "Default adapter 'farmos' runs against a live farmOS — recorded "
            "fixtures re-run against their source is self-verification."
        ),
    )
    p.add_argument("fixtures", help="Path to the semantic-fixture JSONL file.")
    p.add_argument("--adapter", default="farmos", choices=["farmos"],
                   help="Implementation adapter to verify against.")
    p.add_argument("--base-url", default="http://localhost:8095")
    p.add_argument("--username", default="admin")
    p.add_argument("--password", default="admin")
    p.add_argument("--client-id", default="farm")
    p.add_argument("--client-secret", default="")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="Emit the full per-fixture result as JSON.")
    p.add_argument("--preflight-timeout", type=float, default=DEFAULT_TIMEOUT,
                   help="Seconds for the oracle liveness probe (default: %(default)s).")
    p.add_argument("--skip-preflight", action="store_true",
                   help="Skip the oracle liveness probe (not recommended).")
    p.set_defaults(func=run)


def _build_adapter(args: argparse.Namespace):
    if args.adapter == "farmos":
        from ctkr.oracle.farmos_adapter import FarmOSAdapter
        from ctkr.oracle.recorder import build_client

        client = build_client(
            args.base_url, args.username, args.password, recording=False,
            client_id=args.client_id, client_secret=args.client_secret,
        )
        return FarmOSAdapter(client)
    raise SystemExit(f"unknown adapter {args.adapter!r}")


def run(args: argparse.Namespace) -> int:
    fixtures = load_fixtures(args.fixtures)
    if args.adapter == "farmos" and not args.skip_preflight:
        # Fail in seconds with a remedy, rather than hanging per fixture.
        try:
            require_oracle(
                args.base_url, username=args.username, password=args.password,
                client_id=args.client_id, client_secret=args.client_secret,
                timeout=args.preflight_timeout,
            )
        except OracleDown as exc:
            sys.stderr.write(f"\n{exc}\n")
            return 2
    adapter = _build_adapter(args)
    summary = run_fixtures(adapter, fixtures)

    if args.as_json:
        sys.stdout.write(summary.model_dump_json(indent=2) + "\n")
    else:
        sys.stderr.write(
            f"\n  adapter    : {adapter.name}\n"
            f"  fixtures   : {summary.total}\n"
            f"  passed     : {summary.passed}\n"
            f"  failed     : {summary.failed}\n"
            f"  pass rate  : {summary.pass_rate:.1%}\n\n"
        )
        for r in summary.results:
            mark = "PASS" if r.passed else "FAIL"
            sys.stderr.write(f"  [{mark}] {r.title}\n")
            if r.error:
                sys.stderr.write(f"         error: {r.error.splitlines()[0]}\n")
            for a in r.assertions:
                if not a.passed:
                    sys.stderr.write(
                        f"         {a.assertion}({a.subject}) "
                        f"expected {a.op} {a.expected!r}, got {a.actual!r}"
                        f"{' - ' + a.detail if a.detail else ''}\n"
                    )
    return 0 if summary.failed == 0 else 1
