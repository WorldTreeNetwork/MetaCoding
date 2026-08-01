"""Ledger-level pack retirement (MetaCoding-2oo).

The wave0 pilot's fixtures predate the hash-compat discipline: every one
lands in the invalid bucket, which is per-fixture honest but pack-level
misleading — a pack that "loads" with 0 valid fixtures reads as a degenerate
CURRENT pack. Retirement makes history first-class: append-only (the seal
row stays), reasoned (a why is required), and total (nothing judging loads
the pack at all).

Fake-it answers: deleting the seal row instead of retiring would trip the
existing not-in-ledger refusal; editing the retirement row away is a git-
visible ledger edit; and a retirement row can never vouch (registered_seals
filters it) or shrink another pack (the subset check skips it).

TWO KINDS OF TEST LIVE HERE (MetaCoding-1gt). The MECHANISM tests build their
own ledger and run everywhere, including on a clone with no farmOS ledger beside
it. The CORPUS tests assert something about the REAL committed ledger — that the
wave0 packs specifically are retired in it — and are guarded, because a synthetic
stand-in for that claim would be the claim certifying itself.
"""

import json

import pytest
from _synthetic_ledger import SyntheticLedger
from _workspace import PORT_RUNS, requires_ledger  # the ledger is its own repo

from ctkr.oracle.pack import (
    PackError,
    load_pack,
    registered_seals,
    registry_entries,
    retire_seal,
)

ROOT = PORT_RUNS
LEDGER = ROOT / "PACKS.jsonl"


# --------------------------------------------------------------------------- #
# MECHANISM — a ledger built from nothing; runs with no farmOS checkout present #
# --------------------------------------------------------------------------- #
def test_a_retired_pack_refuses_to_load_at_all(
    synthetic_ledger: SyntheticLedger,
) -> None:
    """Retirement is TOTAL: nothing judging loads the pack, not even degraded.

    The pack is loadable first, so the refusal afterwards is attributable to the
    retirement and not to a pack that was never valid — the failure mode the
    wave0 tree could not distinguish, since those fixtures never loaded clean.
    """
    fixtures_path, seal = synthetic_ledger.seal_pack("retire-me")
    assert load_pack(fixtures_path).fixtures, "pack must be loadable BEFORE retiring"

    synthetic_ledger.retire(seal, "predates the hash-compat discipline")

    with pytest.raises(PackError, match="RETIRED"):
        load_pack(fixtures_path)


def test_a_retired_seal_stops_vouching_but_its_row_survives(
    synthetic_ledger: SyntheticLedger,
) -> None:
    """Append-only: the ledger REMEMBERS the pack was recorded, and stops trusting it."""
    _, seal = synthetic_ledger.seal_pack("remembered")
    assert seal in registered_seals(synthetic_ledger.ledger)

    synthetic_ledger.retire(seal, "superseded")

    entries = registry_entries(synthetic_ledger.ledger)
    issued = {e.get("seal") for e in entries if not e.get("record")}
    retired = {e["seal"] for e in entries if e.get("record") == "retirement"}
    assert seal in issued, "the original row must not be rewritten away"
    assert seal in retired
    assert seal not in registered_seals(synthetic_ledger.ledger)


def test_a_retirement_row_cannot_itself_vouch_for_a_pack(
    synthetic_ledger: SyntheticLedger,
) -> None:
    """A retirement names a seal; that naming must not read as a registration."""
    _, seal = synthetic_ledger.seal_pack("solo")
    synthetic_ledger.retire(seal, "gone")
    assert registered_seals(synthetic_ledger.ledger) == set()


# --------------------------------------------------------------------------- #
# CORPUS — claims about the REAL farmOS ledger; guarded, never synthesised      #
# --------------------------------------------------------------------------- #
@requires_ledger
def test_the_wave0_packs_are_retired_and_refuse_to_load() -> None:
    for lane in ("w0a", "w0b"):
        fx = ROOT / "wave0-pilot" / f"{lane}-observe" / "fixtures.jsonl"
        if not fx.exists():
            pytest.skip("no committed wave0 tree")
        with pytest.raises(PackError, match="RETIRED"):
            load_pack(fx)


@requires_ledger
def test_a_retired_seal_no_longer_vouches_but_its_row_remains() -> None:
    entries = registry_entries(LEDGER)
    retired = {e["seal"] for e in entries if e.get("record") == "retirement"}
    assert retired, "the wave0 retirements should be in the committed ledger"
    issued = {e.get("seal") for e in entries if not e.get("record")}
    # append-only: the retired seals' ORIGINAL rows are still in the ledger
    assert retired <= issued
    # but they vouch nothing
    assert not (retired & registered_seals(LEDGER))


def test_retirement_requires_reason_registration_and_happens_once(tmp_path) -> None:
    reg = tmp_path / "PACKS.jsonl"
    reg.write_text(json.dumps({"seal": "s1", "pack_id": "s1", "fixture_ids": []}) + "\n")
    with pytest.raises(PackError, match="requires a reason"):
        retire_seal("s1", "  ", reg)
    with pytest.raises(PackError, match="nothing to retire"):
        retire_seal("never-issued", "r", reg)
    retire_seal("s1", "r", reg)
    with pytest.raises(PackError, match="already retired"):
        retire_seal("s1", "r", reg)
