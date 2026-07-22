"""``ctkr add-term`` — spec-driven plumbing codegen for one glossary term.

Takes a TERM-SPEC v1 (the contract ``propose-terms`` emits) and generates the
whole plumbing a new term needs — glossary set entry, probe/operation contract
row, interpreter arm, adapter stubs that FAIL LOUDLY, test skeleton — as one
reviewable diff (``--dry-run``, the default) or as written files plus a
PROVISIONAL provenance row (``--apply``).

Applying never binds: the term stays PROVISIONAL — excluded from scoring by
``port-verify`` — until a real sealed recording exercises its discriminating
flow and ``ctkr bind-term`` fills ``first_pack_seal``. See
:mod:`ctkr.oracle.glossary_provenance` (bead MetaCoding-b5r; the 9-file survey
is MetaCoding-yph).
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "add-term",
        help="Generate the plumbing for one TERM-SPEC v1 (dry-run diff by "
        "default; --apply writes it + a PROVISIONAL provenance row).",
        description=(
            "Spec-driven codegen for a new glossary term (MetaCoding-b5r, "
            "subsuming the MetaCoding-yph 9-file survey). --dry-run (default) "
            "prints the full unified diff and writes NOTHING. --apply writes "
            "the edits under --root and registers the term PROVISIONAL in the "
            "provenance registry; only `ctkr bind-term`, against a real sealed "
            "recording, can make it scorable."
        ),
    )
    p.add_argument("--spec", required=True, metavar="JSON",
                   help="Path to one TERM-SPEC v1 JSON object (e.g. one line "
                        "of a propose-terms output JSONL, saved to a file).")
    mode = p.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true", default=False,
                      help="Print the full diff; write nothing (the default).")
    mode.add_argument("--apply", action="store_true", default=False,
                      help="Write the edits and add the PROVISIONAL row.")
    p.add_argument("--root", default="",
                   help="Target tree: the directory containing the `ctkr` "
                        "package and `tests/` (default: this installation's "
                        "own tree). Point at a copy to rehearse.")
    p.add_argument("--registry", default="",
                   help="Provenance registry JSONL (default: the target "
                        "tree's ctkr/oracle/glossary_provenance.jsonl).")
    p.set_defaults(func=run)


def _default_root() -> Path:
    import ctkr

    return Path(ctkr.__file__).resolve().parent.parent


def run(args: argparse.Namespace) -> int:
    from ctkr.oracle.glossary_provenance import (
        ProvenanceError,
        add_provisional,
        load_registry,
    )
    from ctkr.term_codegen import CodegenError, apply_edits, plan_edits, render_diffs

    spec_path = Path(args.spec).expanduser()
    if not spec_path.is_file():
        sys.stderr.write(f"ERROR: --spec {spec_path} is not a file.\n")
        return 2
    try:
        spec = json.loads(spec_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        sys.stderr.write(
            f"ERROR: {spec_path} is not one JSON object ({exc}). For a "
            f"proposals JSONL, save one line to its own file first.\n"
        )
        return 2

    root = Path(args.root).expanduser().resolve() if args.root else _default_root()
    registry = (
        Path(args.registry).expanduser()
        if args.registry
        else root / "ctkr" / "oracle" / "glossary_provenance.jsonl"
    )

    try:
        rows = load_registry(registry)
        if any(r["term"] == spec.get("term") for r in rows):
            sys.stderr.write(
                f"ERROR: term {spec.get('term')!r} already has a provenance "
                f"row in {registry}.\n"
            )
            return 2
        edits = plan_edits(spec, root)
    except (CodegenError, ProvenanceError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2

    if not args.apply:
        sys.stdout.write(render_diffs(edits))
        sys.stderr.write(
            f"\nDRY RUN — nothing written. {spec['term']!r} ({spec['kind']}) "
            f"would touch {len(edits)} file(s) under {root}:\n"
            + "".join(f"  {'new     ' if e.is_new else 'modified'}  {e.rel_path}\n"
                      for e in edits)
            + f"  + 1 PROVISIONAL row in {registry}\n"
            "Re-run with --apply to write (then record + `ctkr bind-term` to "
            "make it scorable).\n"
        )
        return 0

    try:
        written = apply_edits(edits, root)
        row = add_provisional(spec, registry)
    except (CodegenError, ProvenanceError) as exc:
        sys.stderr.write(f"ERROR: {exc}\n")
        return 2
    sys.stderr.write(
        f"applied {spec['term']!r} ({spec['kind']}) — {len(written)} file(s):\n"
        + "".join(f"  {p}\n" for p in written)
        + f"  registry row: {registry} (status={row['status']})\n"
        f"The term is PROVISIONAL: port-verify will not score it until a "
        f"sealed recording exercises it and `ctkr bind-term {spec['term']}` "
        f"fills first_pack_seal.\n"
    )
    return 0
