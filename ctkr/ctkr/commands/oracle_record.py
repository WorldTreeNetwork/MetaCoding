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
from ctkr.oracle.recorder import (
    build_client,
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
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.oracle.farmos_adapter import FarmOSAdapter

    client = build_client(
        args.base_url, args.username, args.password, recording=True,
        client_id=args.client_id, client_secret=args.client_secret,
    )
    adapter = FarmOSAdapter(client)

    sys.stderr.write(f"recording value-flows against {args.base_url} ...\n")
    fixtures, observations = record_session(adapter)

    out = Path(args.out_dir)
    fx_path = out / "fixtures.jsonl"
    obs_path = out / "observations.jsonl"
    n_fx = write_fixtures(fixtures, fx_path)
    n_obs = write_observations(observations, obs_path)

    issues = [i for fx in fixtures for i in validate_fixture(fx)]
    sys.stderr.write(
        f"\n  flows recorded      : {len(fixtures)}\n"
        f"  fixtures distilled  : {n_fx}\n"
        f"  observations logged : {n_obs}\n"
        f"  validation issues   : {len(issues)}\n"
        f"  fixtures            : {fx_path}\n"
        f"  observations        : {obs_path}\n"
    )
    for i in issues:
        sys.stderr.write(f"  [{i.severity}] {i.where}: {i.message}\n")
    return 1 if issues else 0
