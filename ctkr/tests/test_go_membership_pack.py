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

from pathlib import Path

from ctkr.oracle.pack import load_pack
from ctkr.oracle.port_adapter import PortAdapter
from ctkr.oracle.port_contract import PortManifest
from ctkr.oracle.port_verify import PortVerifyReport, verify_port

RUN = Path(__file__).resolve().parents[2] / "eval" / "ctkr" / "port_runs" / "wave1-c1"


def _report(port_dir: str) -> PortVerifyReport:
    pack = load_pack(RUN / "observe" / "fixtures.jsonl")
    manifest = PortManifest.load(RUN / port_dir)
    adapter = PortAdapter(manifest)
    return verify_port(adapter, pack, manifest, {})


def test_the_shipped_membership_pack_discriminates_the_c1_fix() -> None:
    matching = _report("portB")   # RECURSIVE=1 — matches GroupMembership.php
    diverging = _report("portA")  # RECURSIVE=0 — the pre-fix adapter's belief

    # The right port is clean and whole.
    assert matching.clean, matching.needs_review
    assert matching.score.scored_failed == 0

    # The wrong port FAILS — visibly, not as a gap or an exclusion.
    assert not diverging.clean
    assert diverging.score.scored_failed > 0

    # And the ranking is strict: wrong can never tie right on this pack.
    assert matching.score.value_score > diverging.score.value_score
