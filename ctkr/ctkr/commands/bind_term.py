"""``ctkr bind-term`` — the glossary binding gate (bead MetaCoding-b5r).

A term enters the glossary like a decision enters the registry: cited,
witnessed, reversible. ``add-term --apply`` leaves a term PROVISIONAL; this
command flips it to BOUND if and only if a **sealed** pack — chain of custody
verified by :func:`ctkr.oracle.pack.load_pack` — contains a valid fixture that
exercises the term. The pack's seal becomes the row's ``first_pack_seal``.

This is the only path to a scorable term: ``port-verify`` returns NO VERDICT
for every assertion on a provisional term (mirroring the corroboration-only
and unvalidated-derivation exclusions).
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "bind-term",
        help="Flip a PROVISIONAL glossary term to BOUND because a sealed "
        "pack exercised it (fills first_pack_seal).",
        description=(
            "The binding gate: verifies the pack's whole chain of custody "
            "(seal, digests, witnesses, ledger) via load_pack, checks that a "
            "VALID fixture exercises the term in the position its kind "
            "allows, then fills first_pack_seal and flips "
            "provisional -> bound. Until this succeeds, port-verify scores "
            "nothing asserted in the term's name."
        ),
    )
    p.add_argument("term", help="The provisional term to bind.")
    p.add_argument("--pack", required=True, metavar="PATH",
                   help="Sealed pack: a fixtures.jsonl or the directory "
                        "holding one (with pack.seal.json + observations).")
    p.add_argument("--registry", default="",
                   help="Provenance registry JSONL (default: this "
                        "installation's ctkr/oracle/glossary_provenance.jsonl).")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    from ctkr.oracle.glossary_provenance import ProvenanceError, bind_term
    from ctkr.oracle.pack import PackError

    pack_path = Path(args.pack).expanduser()
    if pack_path.is_dir():
        pack_path = pack_path / "fixtures.jsonl"
    registry = Path(args.registry).expanduser() if args.registry else None

    try:
        row = bind_term(args.term, pack_path, registry)
    except (ProvenanceError, PackError) as exc:
        sys.stderr.write(f"NOT BOUND: {exc}\n")
        return 2

    sys.stderr.write(
        f"BOUND: {row['term']!r} ({row['kind']})\n"
        f"  first_pack_seal : {row['provenance']['first_pack_seal']}\n"
        f"  pack_id         : {row['bound_pack_id']}\n"
        f"  bound_at        : {row['bound_at']}\n"
        f"port-verify will now score assertions on this term.\n"
    )
    return 0
