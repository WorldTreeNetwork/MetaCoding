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
"""

import json
from pathlib import Path

import pytest

from ctkr.oracle.pack import (
    PackError,
    load_pack,
    registered_seals,
    registry_entries,
    retire_seal,
)
from _workspace import PORT_RUNS  # the ledger lives in its own repo (MetaCoding-1gt)

ROOT = PORT_RUNS
LEDGER = ROOT / "PACKS.jsonl"


def test_the_wave0_packs_are_retired_and_refuse_to_load() -> None:
    for lane in ("w0a", "w0b"):
        fx = ROOT / "wave0-pilot" / f"{lane}-observe" / "fixtures.jsonl"
        if not fx.exists():
            pytest.skip("no committed wave0 tree")
        with pytest.raises(PackError, match="RETIRED"):
            load_pack(fx)


def test_a_retired_seal_no_longer_vouches_but_its_row_remains() -> None:
    if not LEDGER.exists():
        pytest.skip("no ledger")
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
