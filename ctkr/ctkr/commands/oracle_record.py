"""``ctkr oracle-record`` — record + distil semantic fixtures from live farmOS.

Runs the scripted session of core value-flows (asset lifecycle, harvest log +
quantity, log status transition, group membership) against a **live** farmOS
instance at its JSON:API boundary, records the request/response pairs, and
distils each flow into a semantic fixture asserting the VALUES the live system
delivered. Writes ``fixtures.jsonl`` + ``observations.jsonl``.

Requires a reachable farmOS + OAuth password-grant credentials (see the bead
report for the Docker bring-up). This command is the only one that needs the
live instance; validation + the schema tests run without it.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.oracle.fixtures import validate_fixture, write_fixtures
from ctkr.oracle.flowspec_io import FlowSpecError, load_flows
from ctkr.oracle.health import DEFAULT_TIMEOUT, OracleDown, require_oracle
from ctkr.oracle.recorder import (
    build_client,
    record_session_result,
    core_flows,
    hardening_flows,
    record_session,
    write_observations,
)


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "oracle-record",
        help="Record + distil semantic fixtures from a live farmOS (Phase 2).",
        description=(
            "Drive a live farmOS JSON:API boundary through the scripted "
            "value-flow session and distil each flow into a value-level semantic "
            "fixture (decomposition-schema.md §5). Writes fixtures.jsonl + "
            "observations.jsonl and validates the distilled fixtures."
        ),
    )
    p.add_argument("--base-url", default="http://localhost:8095",
                   help="farmOS base URL (default: http://localhost:8095).")
    p.add_argument("--username", default="admin")
    p.add_argument("--password", default="admin")
    p.add_argument("--client-id", default="farm")
    p.add_argument("--client-secret", default="")
    p.add_argument("--out-dir", default=".",
                   help="Directory for fixtures.jsonl + observations.jsonl.")
    p.add_argument("--flows", default="", metavar="FILE",
                   help=("Record a supplied flow pack (JSON) instead of a "
                         "built-in pack. The pack says what to DO and what to "
                         "PROBE; every expected value is filled from what the "
                         "live system returns. Fails loudly on an unknown "
                         "action, glossary term, alias, or storage leak."))
    p.add_argument("--pack", default="core", choices=("core", "hardening", "all"),
                   help=("Which built-in flow pack to record when --flows is not "
                         "given (default: %(default)s)."))
    p.add_argument("--preflight-timeout", type=float, default=DEFAULT_TIMEOUT,
                   help="Seconds for the oracle liveness probe (default: %(default)s).")
    p.add_argument("--skip-preflight", action="store_true",
                   help="Skip the oracle liveness probe (not recommended).")
    p.set_defaults(func=run)


def _select_flows(args: argparse.Namespace):
    """Resolve which flows to record. A bad pack fails before the oracle is touched."""
    if args.flows:
        return load_flows(args.flows), f"pack {args.flows}"
    if args.pack == "core":
        return core_flows(), "built-in core pack"
    if args.pack == "hardening":
        return hardening_flows(), "built-in hardening pack"
    return core_flows() + hardening_flows(), "built-in core + hardening packs"


def run(args: argparse.Namespace) -> int:
    from ctkr.oracle.farmos_adapter import FarmOSAdapter

    # Resolve the flows FIRST: a malformed pack must not cost an oracle round-trip,
    # and must never half-record.
    try:
        flows, origin = _select_flows(args)
    except FlowSpecError as exc:
        sys.stderr.write(f"\nINVALID FLOW PACK: {exc}\n")
        return 2

    if not args.skip_preflight:
        # Recording against a dead oracle produces nothing but a long wait; and a
        # half-installed instance would silently record WRONG values.
        try:
            require_oracle(
                args.base_url, username=args.username, password=args.password,
                client_id=args.client_id, client_secret=args.client_secret,
                timeout=args.preflight_timeout,
            )
        except OracleDown as exc:
            sys.stderr.write(f"\n{exc}\n")
            return 2

    client = build_client(
        args.base_url, args.username, args.password, recording=True,
        client_id=args.client_id, client_secret=args.client_secret,
    )
    adapter = FarmOSAdapter(client)

    sys.stderr.write(
        f"recording {len(flows)} value-flows ({origin}) against {args.base_url} ...\n"
    )
    session = record_session_result(adapter, flows)
    fixtures, observations = session.fixtures, session.observations

    out = Path(args.out_dir)
    fx_path = out / "fixtures.jsonl"
    obs_path = out / "observations.jsonl"
    n_fx = write_fixtures(fixtures, fx_path)
    n_obs = write_observations(observations, obs_path)

    issues = [i for fx in fixtures for i in validate_fixture(fx)]
    sys.stderr.write(
        f"\n  flows recorded      : {len(fixtures)}/{len(flows)}\n"
        f"  fixtures distilled  : {n_fx}\n"
        f"  observations logged : {n_obs}\n"
        f"  validation issues   : {len(issues)}\n"
        f"  fixtures            : {fx_path}\n"
        f"  observations        : {obs_path}\n"
    )
    for i in issues:
        sys.stderr.write(f"  [{i.severity}] {i.where}: {i.message}\n")

    # A flow that produced no fixture is never silently dropped: a pack that
    # recorded 11 of 12 is NOT a pack of 11.
    if session.unrecorded:
        sys.stderr.write(
            f"\n  UNRECORDED FLOWS    : {len(session.unrecorded)} "
            f"— these produced NO fixture and are not in the pack\n"
        )
        for u in session.unrecorded:
            sys.stderr.write(f"    - {u.key}: {u.error}\n")
            sys.stderr.write(f"      ({u.title})\n")
        sys.stderr.write(
            "  If the source REFUSED the write, that refusal is a semantic worth\n"
            "  recording: set expect_refusal on the flow and re-run.\n"
        )
    return 1 if (issues or session.unrecorded) else 0
