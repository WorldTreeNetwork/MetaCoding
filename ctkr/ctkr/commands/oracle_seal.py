"""``ctkr oracle-seal`` — seal a recorded pack so it can be judged against.

Sealing is normally automatic: ``oracle-record`` seals what it wrote, which is
the point — the seal is issued by the party with no stake in any score, at the
moment the values were observed.

This command exists for the one legitimate manual case: a pack that predates the
seal format. It is deliberately blunt about what it can and cannot certify. A
seal says *"these exact bytes are what was here when I looked"*. It does **not**
say the values were observed rather than typed. If a pack's provenance is thin
(no observation refs, no derivation stamps), sealing it will not make it evidence
— :func:`ctkr.oracle.pack.load_pack` will still mark those fixtures INVALID, and
the honest remedy is to re-record against the live source.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from ctkr.oracle.pack import OBSERVATIONS_NAME, PackError, seal_pack


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "oracle-seal",
        help="Seal a recorded fixture pack (normally done by oracle-record).",
        description=(
            "Write pack.seal.json over a pack's fixtures + observations and "
            "append it to the version-controlled pack registry. Sealing an "
            "EDITED pack is not a way to make it evidence: a seal certifies "
            "bytes, and re-sealing shows up as a diff in a file the party being "
            "judged does not own."
        ),
    )
    p.add_argument("pack", help="Pack directory, or its fixtures.jsonl.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    target = Path(args.pack)
    fixtures = target / "fixtures.jsonl" if target.is_dir() else target
    if not fixtures.exists():
        sys.stderr.write(f"\n  no fixtures at {fixtures}\n")
        return 2
    try:
        seal = seal_pack(fixtures)
    except (PackError, OSError, ValueError) as exc:
        sys.stderr.write(f"\n  cannot seal: {exc}\n")
        return 2
    sys.stderr.write(
        f"\n  sealed {fixtures}\n"
        f"    pack id       : {seal.pack_id}\n"
        f"    seal          : {seal.seal}\n"
        f"    fixtures      : {len(seal.fixture_ids)}\n"
        f"    fixtures hash : {seal.fixtures_blake3}\n"
        f"    {OBSERVATIONS_NAME} hash: {seal.observations_blake3}\n"
        f"    derivations   : {len(seal.derivations)} derived probe(s) pinned\n\n"
    )
    return 0
