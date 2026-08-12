"""The synthetic ledger is held to the real pack contract (MetaCoding-1gt).

A test fixture that builds packs is an INSTRUMENT: every mechanism test that
stops needing the farmOS ledger now believes whatever this builder emits. If it
drifts from the shape the recorder actually writes, those tests keep passing
against a format that no longer exists — the exact "green tick that measures
nothing" the ledger extraction was supposed to avoid.

So the builder is not trusted, it is checked, and checked by the REAL loader
rather than by a second copy of the rules. ``load_pack`` is the same function
that judges the 43 sealed farmOS packs; if it accepts what this emits, the
mechanism tests are standing on the contract and not on a mock of it.
"""

from __future__ import annotations

from _synthetic_ledger import (
    SyntheticLedger,
    ledger_rows,
    observation_rows,
    recorded_fixture,
)

from ctkr.oracle.pack import load_pack, registered_seals
from ctkr.oracle.probes import current_derivations


def test_a_synthetic_pack_loads_through_the_real_loader(
    synthetic_ledger: SyntheticLedger,
) -> None:
    fixtures_path, seal = synthetic_ledger.seal_pack("lane-a")
    loaded = load_pack(fixtures_path)
    assert loaded, "the pack loaded but yielded no fixtures"
    assert seal in registered_seals(synthetic_ledger.ledger)


def test_the_pack_carries_the_current_derivations_not_a_frozen_literal(
    synthetic_ledger: SyntheticLedger,
) -> None:
    # A builder that pinned derivation ids as literals would keep minting packs
    # that look valid after a derivation is superseded — authority laundering by
    # copy-paste. This is why recorded_fixture() calls current_derivations().
    fx = recorded_fixture("log_count", 1)
    assert fx.provenance.derivations == current_derivations()
    assert fx.provenance.derivations, "no derivations means nothing to be wrong about"


def test_every_assertion_is_witnessed_and_every_witness_is_claimed(
    synthetic_ledger: SyntheticLedger,
) -> None:
    fixtures = [recorded_fixture("log_count", 3, title="witnessed")]
    rows = observation_rows(fixtures)
    witnesses = {r["obs_id"] for r in rows if r.get("record") == "witness"}
    cited = {t.witness for fx in fixtures for t in fx.then}
    assert cited == witnesses, "an orphan witness or an uncited assertion"


def test_a_pack_whose_witness_disagrees_is_refused(
    synthetic_ledger: SyntheticLedger,
) -> None:
    """The builder can express a FORGERY, which is what makes it useful.

    If every pack this module could build were valid, the mechanism tests could
    only ever check the happy path. Here the WITNESS is made to report a value
    the fixture does not claim, and the real loader must refuse to score it.

    Note the shape of the refusal: not an exception, but an empty ``fixtures``
    and a populated ``invalid``. A pack does not fail to load — it loads, and
    yields nothing scorable, with the contradiction stated. Asserting the wrong
    shape here would have passed a forgery through as "no error raised".
    """
    fixtures = [recorded_fixture("log_count", 2, title="honest")]
    rows = observation_rows(fixtures)
    for row in rows:
        if row.get("record") == "witness":
            row["observed"] = 999

    pack_dir = synthetic_ledger.port_runs / "forged" / "observe"
    pack_dir.mkdir(parents=True)
    from _synthetic_ledger import _Row, preflight_report

    from ctkr.oracle.pack import seal_recording

    seal_recording(fixtures, [_Row(r) for r in rows], pack_dir, register=True,
                   preflight=preflight_report())
    loaded = load_pack(pack_dir / "fixtures.jsonl")
    assert loaded.fixtures == [], "a value its own witness contradicts must not be scorable"
    assert len(loaded.invalid) == 1
    reason = loaded.invalid[0].reason
    assert "INVALID EVIDENCE" in reason
    assert "999" in reason and "contradicts" in reason


def test_two_builds_of_the_same_pack_seal_identically(
    synthetic_ledger: SyntheticLedger,
    tmp_path,
) -> None:
    """Stable ids, or 'the seal did not move' is not a testable claim."""
    _, seal_a = synthetic_ledger.seal_pack("lane-x")
    other = SyntheticLedger(root=tmp_path / "second")
    (other.root / "port_runs").mkdir(parents=True)
    other.ledger.write_text("", encoding="utf-8")
    _, seal_b = other.seal_pack("lane-x")
    assert seal_a == seal_b


def test_the_ledger_records_what_was_sealed(
    synthetic_ledger: SyntheticLedger,
) -> None:
    _, seal = synthetic_ledger.seal_pack("lane-b")
    rows = ledger_rows(synthetic_ledger.ledger)
    assert [r for r in rows if r.get("seal") == seal], "seal absent from the ledger"
