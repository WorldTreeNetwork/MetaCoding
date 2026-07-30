"""The ten synthetic location fixtures are retired (MetaCoding-4vh / -b0s).

`src/kernel/status.ts` cited them as observation. They are hand-authored: every
row carries `provenance: null` with zero observation refs, and the kernel-v1
headline — "27 fixtures + 5 probes" — read as 27 observed while being 17
observed plus 10 synthetic.

Retiring them is a CLAIM, so this file makes it checkable instead of trusting a
markdown table. Three things are asserted, and the third is the one that
matters:

1. the synthetic files really are synthetic — they fail validation for the
   reason claimed, not for some other reason;
2. the replacement packs really are sealed and observed;
3. **every assertion the synthetic set makes is either recorded in a sealed
   pack or provably redundant.** Retirement without that is just deletion, and
   the semantics would go quiet rather than move.

The files themselves are deliberately left on disk. `compose-9h5.16` and
`kernel-9h5.24` are records of what those runs actually scored, and they scored
these rows; a past run's inputs are not ours to rewrite. What was wrong was the
claim made about them, which is corrected where it was made.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctkr.oracle.probes import PROBE_CONTRACT
from _workspace import PORT_RUNS  # the ledger lives in its own repo (MetaCoding-1gt)

_ROOT = PORT_RUNS

SYNTHETIC = [
    _ROOT / "kernel-9h5.24" / "build" / "inputs" / "FIXTURES_LOCATION.jsonl",
    _ROOT / "compose-9h5.16" / "build" / "inputs" / "FIXTURES_LOCATION.jsonl",
]

#: The packs that replaced them, with the seals the recorder issued.
REPLACEMENTS = {
    "lexicon-bind/location/observe": "f3460165d338da4c6043262a05bd3a99",
    "lexicon-bind/location_asof/observe": "d7f164e35f204fe59d670570a5322711",
}

#: Assertions the synthetic set makes that were deliberately NOT minted as
#: terms, with the recorded term that answers the same question. A term adding
#: no semantics still costs a probe binding, an adapter method, an authority
#: judgement and a port surface — each one somewhere an implementation can be
#: wrong for no reason.
REDUNDANT = {
    "has_location": "current_location_count",
    "has_geometry": "current_geometry",
    "location_contains": "is_at_location",
}


def _rows(path: Path) -> list[dict]:
    return [json.loads(l) for l in path.read_text().splitlines() if l.strip()]


@pytest.mark.parametrize("path", SYNTHETIC, ids=lambda p: p.parts[-4])
def test_the_retired_fixtures_are_synthetic_for_the_stated_reason(path) -> None:
    if not path.is_file():
        pytest.skip(f"no build tree at {path}")
    rows = _rows(path)
    assert len(rows) == 10
    assert all(r.get("provenance") is None for r in rows), (
        "the retirement rests on these carrying no provenance — if that "
        "changed, re-read the claim before trusting it"
    )


@pytest.mark.parametrize("path", SYNTHETIC, ids=lambda p: p.parts[-4])
def test_the_retirement_is_recorded_beside_the_file(path) -> None:
    """A reader who opens the directory must not have to know the history."""
    if not path.is_file():
        pytest.skip(f"no build tree at {path}")
    note = path.with_suffix(".RETIRED.md")
    assert note.is_file(), f"no retirement note beside {path}"
    text = note.read_text()
    for seal in REPLACEMENTS.values():
        assert seal[:12] in text, "the note must name what replaced the file"


def test_the_replacement_packs_are_sealed_and_load_through_the_judging_path() -> None:
    from ctkr.oracle.pack import load_pack

    for rel, seal in REPLACEMENTS.items():
        pack_dir = _ROOT / rel
        if not pack_dir.is_dir():
            pytest.skip(f"no pack at {pack_dir}")
        pack = load_pack(pack_dir / "fixtures.jsonl")
        assert pack.fixtures, f"{rel} loaded no fixtures"
        assert pack.seal.seal == seal, (
            f"{rel} is sealed {pack.seal.seal}, not the seal the retirement "
            f"cites ({seal}) — it was re-recorded and the note is stale"
        )
        for fx in pack.fixtures:
            assert fx.provenance.observation_refs, (
                f"{rel}/{fx.provenance.flow} cites no observation — the "
                f"replacement would be as synthetic as what it replaced"
            )


def test_every_retired_assertion_is_recorded_or_provably_redundant() -> None:
    """THE test. Retirement without this is deletion: the semantics would go
    quiet rather than move somewhere they are actually observed."""
    from ctkr.oracle.pack import load_pack

    synthetic_terms: set[str] = set()
    asks_as_of = False
    for path in SYNTHETIC:
        if not path.is_file():
            continue
        for r in _rows(path):
            for t in r["then"]:
                synthetic_terms.add(t["assert"])
                asks_as_of = asks_as_of or "at" in t
    if not synthetic_terms:
        pytest.skip("no synthetic location fixtures on disk")

    recorded: set[str] = set()
    recorded_as_of = False
    for rel in REPLACEMENTS:
        pack_dir = _ROOT / rel
        if not pack_dir.is_dir():
            pytest.skip(f"no pack at {pack_dir}")
        for fx in load_pack(pack_dir / "fixtures.jsonl").fixtures:
            for t in fx.then:
                recorded.add(t.assert_)
                recorded_as_of = recorded_as_of or bool(t.as_of)

    unaccounted = sorted(
        term for term in synthetic_terms
        if term not in recorded and term not in REDUNDANT
    )
    assert not unaccounted, (
        f"retired assertions nothing replaced: {unaccounted}. Either record "
        f"them or state why they add no semantics — do not let them go quiet"
    )

    for term, answered_by in REDUNDANT.items():
        if term not in synthetic_terms:
            continue
        assert term not in PROBE_CONTRACT, (
            f"{term!r} was called redundant and then minted anyway — pick one"
        )
        assert answered_by in recorded, (
            f"{term!r} is only redundant because {answered_by!r} is recorded, "
            f"and it is not"
        )

    if asks_as_of:
        assert recorded_as_of, (
            "the synthetic set asks about a MOMENT and the replacement never "
            "does — the as-of semantic would be the one thing retirement lost"
        )
