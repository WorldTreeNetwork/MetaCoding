"""``ctkr oracle-validate`` — validate a semantic-fixture JSONL file (Phase 2).

Checks every fixture for glossary-term legality, alias resolution, per-step
required fields, and the **storage-leak lint** (a fixture that names a table /
column / id / SQL primitive is a defect — it smuggled a data model across the
value line). Exit non-zero if any hard error or leak is found. No Docker, no
network — pure schema validation.
"""

from __future__ import annotations

import argparse
import json
import sys

from ctkr.oracle.fixtures import load_fixtures, validate_fixture


def register(subparsers: argparse._SubParsersAction) -> None:
    p = subparsers.add_parser(
        "oracle-validate",
        help="Validate a semantic-fixture JSONL file (schema + storage-leak lint).",
        description=(
            "Validate value-equivalence semantic fixtures (port-loop Phase 2, "
            "decomposition-schema.md §5): glossary-term legality, alias "
            "resolution, per-step required fields, and the storage-leak lint that "
            "rejects any data-model term. Exits non-zero on any error or leak."
        ),
    )
    p.add_argument("fixtures", help="Path to the semantic-fixture JSONL file.")
    p.add_argument("--json", dest="as_json", action="store_true",
                   help="Emit issues as JSON.")
    p.set_defaults(func=run)


def run(args: argparse.Namespace) -> int:
    fixtures = load_fixtures(args.fixtures)
    all_issues = []
    for fx in fixtures:
        all_issues.extend(validate_fixture(fx))

    if args.as_json:
        sys.stdout.write(
            json.dumps(
                {
                    "fixtures": len(fixtures),
                    "issues": [i.model_dump() for i in all_issues],
                },
                indent=2, default=str,
            ) + "\n"
        )
    else:
        errors = [i for i in all_issues if i.severity == "error"]
        leaks = [i for i in all_issues if i.severity == "leak"]
        sys.stderr.write(
            f"validated {len(fixtures)} fixture(s): "
            f"{len(errors)} error(s), {len(leaks)} leak(s)\n"
        )
        for i in all_issues:
            sys.stderr.write(
                f"  [{i.severity}] {i.fixture_id[:8]} {i.where}: {i.message}\n"
            )
        if not all_issues:
            sys.stderr.write("  all fixtures valid + storage-free.\n")

    return 1 if all_issues else 0
