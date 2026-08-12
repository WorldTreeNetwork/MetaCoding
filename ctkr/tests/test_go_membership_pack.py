"""The GO test, shipped (MetaCoding-ck2).

The C1 fix (transitive membership + effective-time gate) lived in the code and
in a pack the reader authored for one occasion — core-pack and hardening-pack
scored the farmOS-matching and adapter-matching ports byte-identically, so a
re-broken adapter would have re-recorded green tomorrow. This test promotes the
discriminating evidence into the suite: the wave1-c1 membership pack, recorded
live and sealed, is run against the GO test's own minimal pair — two bridges
differing in exactly one line (`RECURSIVE`).

Property: a port that is wrong about farmOS membership cannot score better than
one that is right. If this inverts or flattens, the evidence line for C1 is
broken, whatever the code says.

Hermetic: the bridges are local python processes; no Docker, no oracle.
"""

from __future__ import annotations

from _workspace import (  # the ledger lives in its own repo (MetaCoding-1gt)
    PORT_RUNS,
    requires_ledger,
)

from ctkr.oracle.pack import load_pack
from ctkr.oracle.port_adapter import PortAdapter
from ctkr.oracle.port_contract import PortManifest
from ctkr.oracle.port_verify import PortVerifyReport, verify_port

RUN = PORT_RUNS / "wave1-c1"


def _report(port_dir: str) -> PortVerifyReport:
    pack = load_pack(RUN / "observe" / "fixtures.jsonl")
    manifest = PortManifest.load(RUN / port_dir)
    adapter = PortAdapter(manifest)
    return verify_port(adapter, pack, manifest, {})


@requires_ledger
def test_the_shipped_membership_pack_discriminates_the_c1_fix() -> None:
    matching = _report("portB")   # RECURSIVE=1 — matches GroupMembership.php
    diverging = _report("portA")  # RECURSIVE=0 — the pre-fix adapter's belief

    # The right port answers everything and fails nothing.
    assert matching.score.scored_failed == 0
    assert matching.score.no_verdict == 0
    assert not matching.invalid_evidence
    assert not matching.declaration_problems

    # It is still NOT `clean`, and the only reason is the pack (MetaCoding-hy6.48):
    # wave1-c1 was recorded before the oracle preflight was a precondition, so
    # nothing witnesses that the bundles it probed were the ones bring-up.sh
    # rebuilds. That is a fact about the EVIDENCE, and it does not move any of the
    # port's numbers above — which is exactly why the reading must be spelled out
    # here rather than inferred from a green tick. Only re-observation behind the
    # gate can clear it; nothing this suite does may.
    assert matching.pack_ungated
    assert matching.needs_review == [
        "UNGATED PACK — " + matching.pack_ungated
    ], matching.needs_review
    assert not matching.clean

    # The wrong port FAILS — visibly, not as a gap or an exclusion.
    assert not diverging.clean
    assert diverging.score.scored_failed > 0

    # And the ranking is strict: wrong can never tie right on this pack. The
    # ungated flag is not a way out of this — it is identical on both reports, so
    # it cannot flatten the discrimination it sits beside.
    assert matching.score.value_score > diverging.score.value_score
    assert diverging.pack_ungated == matching.pack_ungated
