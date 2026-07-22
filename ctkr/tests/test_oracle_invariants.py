"""The three invariants, and the attacks that produced each of them.

Hermetic: no Docker, no oracle, no network. Every test here is a *structural*
test — it asserts that a defect is impossible to express, not that a particular
guard happens to fire. Where a test names an attack, the numbers in its docstring
are measured results from the adversarial review of 2026-07-20
(``eval/ctkr/results/wave1-readiness-v2-2026-07-20.md``).

  I1  every value declares its authority
  I2  the defendant never holds a pen that touches the verdict
  I3  absence of an answer is never an answer
"""

from __future__ import annotations

import json
import time
from pathlib import Path

import pytest

from blake3 import blake3

from ctkr.oracle.fixtures import (
    SemanticFixture,
    probe_descriptor,
    write_fixtures,
)
from ctkr.oracle.pack import PackError, load_pack, seal_recording
from ctkr.oracle.port_adapter import BridgeError, PortAdapter, PortBridge
from ctkr.oracle.port_contract import PortManifest, decision_covers
from ctkr.oracle.port_verify import (
    AssertionStatus,
    NoVerdictCause,
    verify_port,
)
from ctkr.oracle.probes import (
    BOUNDARY,
    DERIVED,
    PROBE_CONTRACT,
    contract_gaps,
    current_derivations,
    unvalidated_probes,
)
from tests.test_oracle_flow_bridge import FakeFarmOS, _adapter
from tests.test_port_verify import (
    ALL_OPS,
    fixture,
    make_adapter,
    make_manifest,
    pack,
    soh,
)


# =========================================================================== #
# I1 — EVERY VALUE DECLARES ITS AUTHORITY                                     #
# =========================================================================== #
def test_every_probe_declares_boundary_or_derived() -> None:
    """There is no third option and no default.

    A probe added without an authority is a hole in the contract table, reported
    by the table's own gap function — which is why it cannot be forgotten.
    """
    assert contract_gaps() == []
    for term, spec in PROBE_CONTRACT.items():
        assert spec.authority in (BOUNDARY, DERIVED), term


def test_a_derived_probe_must_say_what_it_computes_and_what_validates_it() -> None:
    for term, spec in PROBE_CONTRACT.items():
        if spec.authority != DERIVED:
            continue
        assert spec.derivation, f"{term} does not say what it computes"
        # It may be UNVALIDATED — that is allowed and consequential (its values
        # cannot score). What is not allowed is claiming validation vacuously.
        if spec.validated_against:
            assert len(spec.validated_against) > 20, term


def test_group_member_is_validated_against_farmos_own_authority() -> None:
    """C1, the decisive blocker.

    The old derivation — "the group of the LATEST done assignment" — was a
    hand-written belief whose own comment claimed to implement "farmOS's
    group-membership semantics". farmOS's actual authority,
    ``GroupMembership.php::getGroupMembers($groups, $recurse = TRUE, $timestamp
    = NULL)``, recurses BY DEFAULT and gates on ``lfd.timestamp <= :timestamp``.
    Measured consequence: a port MATCHING farmOS scored 95.2% NOT-CLEAN while a
    port matching our adapter scored 100% clean.
    """
    spec = PROBE_CONTRACT["group_member"]
    assert spec.authority == DERIVED
    assert spec.is_evidence, "the corrected derivation must now be evidence"
    v = spec.validated_against
    assert "GroupMembership.php" in v
    assert "recurse = TRUE" in v
    assert "timestamp" in v
    # And the derivation itself must state both facts, not just cite them.
    assert "recursive" in spec.derivation
    assert "not in the future" in spec.derivation


def test_an_unvalidated_derivation_is_not_evidence_in_either_direction() -> None:
    """A derived value with no source authority yields NO VERDICT before the
    port is called at all — because comparing a port to our own unvalidated
    belief cannot produce evidence whichever way it comes out."""
    spec = PROBE_CONTRACT["stock_on_hand"]
    hollow = type(spec)(
        assertion=spec.assertion, method=spec.method, params=spec.params,
        authority=DERIVED, derivation="we made it up", validated_against="",
    )
    assert not hollow.is_evidence
    assert "NO VERDICT" in hollow.unvalidated_reason

    fx = fixture("f-unval", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest)
    bridge = adapter._bridge
    with _patched_probe("stock_on_hand", hollow):
        report = verify_port(adapter, pack([fx]), manifest)

    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.NO_VERDICT
    assert o.cause == NoVerdictCause.UNVALIDATED_AUTHORITY
    assert "stock_on_hand" not in bridge.calls  # the port was never asked
    assert not report.clean
    assert report.score.scored_passed == 0


def test_unvalidated_probes_are_named_so_a_wave_can_exclude_them() -> None:
    """Feature selection needs to know which assertions cannot score yet."""
    named = unvalidated_probes()
    assert all(t in PROBE_CONTRACT for t in named)
    assert all(not PROBE_CONTRACT[t].is_evidence for t in named)


def test_a_corrected_derivation_invalidates_the_values_it_produced(tmp_path) -> None:
    """A fixture recorded under a derivation we have since CORRECTED is stale by
    construction and is marked INVALID, never silently kept.

    This is the mechanism that catches the pre-fix `group_member` fixtures: they
    answered "is this asset in the group named by its newest assignment", and
    the question is now "is it in the recursive, effective-time-gated membership
    chain". Same field, different question.
    """
    fx = _recorded(tmp_path, "group_member", value=True)
    # Stamp the derivation id of a DIFFERENT (older) computation.
    fx.provenance.derivations["group_member"] = "0" * 16
    _write_pack(tmp_path, [fx])

    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert loaded.fixtures == []
    assert len(loaded.invalid) == 1
    assert "CORRECTED" in loaded.invalid[0].reason
    assert "Re-record" in loaded.invalid[0].reason


def test_a_derived_value_with_no_derivation_stamp_is_invalid(tmp_path) -> None:
    """C3's shape, generalised: an old pack that predates the stamp cannot be
    read as if it had been recorded under today's computation."""
    fx = _recorded(tmp_path, "group_member", value=True)
    fx.provenance.derivations = {}
    _write_pack(tmp_path, [fx])
    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert loaded.fixtures == []
    assert "records no derivation id" in loaded.invalid[0].reason


def test_group_member_recurses_by_default() -> None:
    """A in G1, G1 in G2  =>  group_member(A, G2) is TRUE.

    The recorded fixture said False. farmOS says
    ``getGroupMembers(G2, recurse=TRUE) = [Inner Flock, Ewe Yarrow]``.
    """
    adapter = _adapter(FakeFarmOS())
    a = adapter.create_asset("animal", "Ewe Yarrow", "Sheep")
    g1 = adapter.create_asset("group", "Inner Flock")
    g2 = adapter.create_asset("group", "Outer Flock")
    adapter.assign_to_group(a, g1)
    adapter.assign_to_group(g1, g2)

    assert adapter.group_member(a, g1) is True
    assert adapter.group_member(a, g2) is True, "recursion is the DEFAULT"


def test_group_member_gates_on_effective_time() -> None:
    """A not-yet-effective assignment confers no membership.

    Measured: for an assignment dated ``now + 864000s`` the adapter answered
    ``True`` while farmOS answered ``hasGroup(A) = FALSE``, ``getGroup(A) = []``.
    """
    world = FakeFarmOS()
    adapter = _adapter(world)
    a = adapter.create_asset("animal", "Future Ewe", "Sheep")
    g = adapter.create_asset("group", "Future Flock")
    adapter.assign_to_group(a, g)
    # Push the assignment ten days into the future, as farmOS itself would allow.
    for log in world.logs.values():
        if log["attributes"].get("is_group_assignment"):
            log["attributes"]["timestamp"] = _iso(int(time.time()) + 864_000)

    assert adapter.group_member(a, g) is False


def test_group_member_membership_cycle_terminates() -> None:
    """A closure walk over source data must not be able to hang the recorder."""
    adapter = _adapter(FakeFarmOS())
    g1 = adapter.create_asset("group", "Ouroboros A")
    g2 = adapter.create_asset("group", "Ouroboros B")
    other = adapter.create_asset("group", "Elsewhere")
    adapter.assign_to_group(g1, g2)
    adapter.assign_to_group(g2, g1)
    assert adapter.group_member(g1, other) is False


def test_folds_read_their_bundle_set_from_the_source_index() -> None:
    """An adapter-typed enumeration is `group_member`'s defect one level up.

    The hard-coded list was ``(harvest, input, activity, observation, seeding)``
    — it omitted ``birth``, which farmOS's own ``/api`` index publishes.
    """
    adapter = _adapter(FakeFarmOS())
    assert "birth" in adapter.log_bundles()
    src = Path("ctkr/oracle/farmos_adapter.py").read_text(encoding="utf-8")
    assert '("harvest", "input", "activity", "observation", "seeding")' not in src


def test_the_adapter_no_longer_shapes_the_source_ordering() -> None:
    """The adapter used to mint a strictly increasing timestamp per instance so
    that its own ``sort=-timestamp`` read would be well-defined — i.e. it shaped
    the observation to suit its query. farmOS breaks the tie itself on
    ``lfd2.id > lfd.id``; the derivation now reads it that way."""
    src = Path("ctkr/oracle/farmos_adapter.py").read_text(encoding="utf-8")
    assert "_last_assign_ts" not in src
    assert "-timestamp,-drupal_internal__id" in src


# =========================================================================== #
# I2 — THE DEFENDANT NEVER HOLDS A PEN THAT TOUCHES THE VERDICT               #
# =========================================================================== #
def test_a_subset_of_a_pack_is_not_a_pack(tmp_path) -> None:
    """A5. ``sed -n '4,7p'`` of a pack gave ``fixtures 4, coverage 10/10 =
    100.0%, EXIT=0, clean`` — the judged party chose the evidence."""
    fixtures = [_recorded(tmp_path, "stock_on_hand", value=float(i))
                for i in range(4)]
    _write_pack(tmp_path, fixtures)
    assert len(load_pack(tmp_path / "fixtures.jsonl").fixtures) == 4

    lines = (tmp_path / "fixtures.jsonl").read_text(encoding="utf-8").splitlines()
    (tmp_path / "fixtures.jsonl").write_text("\n".join(lines[:2]) + "\n",
                                             encoding="utf-8")
    with pytest.raises(PackError) as exc:
        load_pack(tmp_path / "fixtures.jsonl")
    assert "does not match its seal" in str(exc.value)


def test_an_edited_expected_value_is_rejected_by_the_pack_loader(tmp_path) -> None:
    """C4/F1. The forged fixture (``then[0].value`` 3.0 → 999.0, ``fixture_id``
    untouched) was called "valid + storage-free" by ``oracle-validate`` and was
    then judged and scored by ``port-verify``. Only a live re-verify caught it.
    """
    fx = _recorded(tmp_path, "stock_on_hand", value=3.0)
    _write_pack(tmp_path, [fx])

    path = tmp_path / "fixtures.jsonl"
    row = json.loads(path.read_text(encoding="utf-8"))
    row["then"][0]["value"] = 999.0
    path.write_text(json.dumps(row) + "\n", encoding="utf-8")

    with pytest.raises(PackError):
        load_pack(path)


def test_an_edited_value_fails_validation_even_unsealed(tmp_path) -> None:
    """The id was ALWAYS a content hash; it was simply never recomputed on read.
    So the forgery is detectable with no seal at all."""
    from ctkr.oracle.fixtures import validate_fixture

    fx = _recorded(tmp_path, "stock_on_hand", value=3.0)
    forged = fx.model_copy(deep=True)
    forged.then[0].value = 999.0  # id left as the hash of the ORIGINAL body
    issues = validate_fixture(forged)
    assert any(i.where == "fixture_id" for i in issues)
    assert any("edited" in i.message for i in issues)


def test_an_edited_seal_is_rejected(tmp_path) -> None:
    """Re-sealing is a visible act; forging a seal in place is not even that."""
    fx = _recorded(tmp_path, "stock_on_hand", value=3.0)
    _write_pack(tmp_path, [fx])
    seal_path = tmp_path / "pack.seal.json"
    body = json.loads(seal_path.read_text(encoding="utf-8"))
    body["fixtures_blake3"] = "0" * 32
    seal_path.write_text(json.dumps(body), encoding="utf-8")
    with pytest.raises(PackError, match="does not hash its own contents"):
        load_pack(tmp_path / "fixtures.jsonl")


def test_an_unsealed_pack_yields_no_verdict(tmp_path) -> None:
    """A pack with no seal states nothing about its own extent, so the party
    being judged chooses its scope."""
    fx = _recorded(tmp_path, "stock_on_hand", value=3.0)
    _write_pack(tmp_path, [fx], seal=False)
    with pytest.raises(PackError, match="chooses"):
        load_pack(tmp_path / "fixtures.jsonl")


def test_a_provenance_that_names_a_missing_witness_is_invalid(tmp_path) -> None:
    """C4. ``observation_refs`` were never resolved by anything."""
    fx = _recorded(tmp_path, "stock_on_hand", value=3.0)
    fx.provenance.observation_refs = ["obs-that-does-not-exist"]
    _write_pack(tmp_path, [fx])
    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert loaded.fixtures == []
    assert "do not resolve" in loaded.invalid[0].reason


def test_a_fixture_with_no_witness_at_all_is_invalid(tmp_path) -> None:
    """C6. Ten location fixtures carried ``provenance: null`` and zero refs and
    were published as part of "27 fixtures, all green" — 37% synthetic."""
    fx = _recorded(tmp_path, "stock_on_hand", value=3.0)
    fx.provenance.observation_refs = []
    _write_pack(tmp_path, [fx])
    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert "hand-authored" in loaded.invalid[0].reason


# --------------------------------------------------------------------------- #
# THE RED: no artifact can endorse a claim its own witnesses contradict.       #
#                                                                             #
# Three attacks, all measured at EXIT=0 / clean=true / "reproduced 100%" on   #
# 2026-07-20 (MetaCoding-96q). Each is run here in full — including the        #
# re-hash and the re-seal, which is what defeated the previous generation of   #
# checks — and each is now blocked BY CONSTRUCTION, named per test.            #
# --------------------------------------------------------------------------- #
def test_no_public_verb_issues_a_seal() -> None:
    """B. ``ctkr oracle-seal`` was a public, unauthenticated verb that re-issued
    a pack's entire authority, and every one of the three forgeries ended with a
    call to it. It is REMOVED. The public surface may verify a seal
    (``oracle-validate``) and never issue one.

    Structural, not a spot-check: the whole command package is enumerated the way
    the CLI enumerates it, and no module may reach the sealer.
    """
    import importlib
    import inspect
    import pkgutil

    import ctkr.commands

    issuers = []
    for info in pkgutil.iter_modules(ctkr.commands.__path__):
        mod = importlib.import_module(f"ctkr.commands.{info.name}")
        if getattr(mod, "register", None) is None:
            continue
        src = inspect.getsource(mod)
        if "seal_recording" in src or "seal_pack" in src:
            issuers.append(info.name)
    # The recorder alone, because it is the party that made the observations.
    assert issuers == ["oracle_record"], issuers
    assert not hasattr(importlib.import_module("ctkr.oracle.pack"), "seal_pack"), (
        "seal_pack(path) re-issued authority over any file on disk"
    )


def _reseal(tmp_path: Path, rows: list[dict], *, prune: bool = False) -> None:
    """What an attacker does after editing: re-issue the whole chain of custody.

    The public verb is gone, so this reaches past the CLI into the library —
    which is the residual gap this repo names rather than pretends away. The
    point of these tests is that reaching it no longer helps.
    """
    from ctkr.oracle.fixtures import load_fixtures

    (tmp_path / "fixtures.jsonl").write_text(
        "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    forged = load_fixtures(tmp_path / "fixtures.jsonl")
    obs = [json.loads(line) for line
           in (tmp_path / "observations.jsonl").read_text(encoding="utf-8").splitlines()
           if line.strip()]
    if prune:
        # A competent attacker also removes the witnesses nothing cites, so the
        # artifact stays internally consistent.
        claimed = {t.get("witness") for r in rows for t in r["then"]}
        obs = [o for o in obs
               if o.get("record") != "witness" or o["obs_id"] in claimed]
    seal_recording(forged, [_Row(o) for o in obs], tmp_path, register=False)


def test_attack_a_surgical_forgery_is_refused_by_the_fixtures_own_witness(
    tmp_path,
) -> None:
    """(a) SURGICAL FORGERY, the attack that fully re-inverted the GO test.

    Edit a fixture's expected value to the diverging port's answer, recompute
    ``SemanticFixture.content_id()``, re-seal. Measured at HEAD on 2026-07-20:
    the port that is WRONG about farmOS scored 14/14 clean and the correct one
    10/14, reported as "0 INVALID EVIDENCE, NO VERDICT 0".

    Blocked BY CONSTRUCTION: the value is now checked against the witness that
    produced it. The forger keeps the id and the seal consistent and still
    cannot make the observation say what it did not see.
    """
    fx = _recorded(tmp_path, "stock_on_hand", value=3.0)
    _write_pack(tmp_path, [fx])
    assert len(load_pack(tmp_path / "fixtures.jsonl").fixtures) == 1

    row = json.loads((tmp_path / "fixtures.jsonl").read_text(encoding="utf-8"))
    row["then"][0]["value"] = 999.0
    row["fixture_id"] = ""  # recompute it, exactly as the attack did
    _reseal(tmp_path, [row])

    # Every earlier layer is now SATISFIED — that is the point of the test.
    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert loaded.fixtures == [], "a forged value must not be scorable"
    assert len(loaded.invalid) == 1
    reason = loaded.invalid[0].reason
    assert "INVALID EVIDENCE" in reason
    assert "3.0" in reason and "999.0" in reason
    assert "contradicts" in reason


def test_attack_a_variant_repointing_the_witness_does_not_help(tmp_path) -> None:
    """The obvious next move: cite a DIFFERENT witness that happens to say 999.

    A witness answers one question. Re-pointing an assertion at a witness of
    another probe is caught by comparing the question, not just the value —
    otherwise "yield_total in pounds" could be witnessed by "yield_total in
    kilograms" and the unit filter would be unfalsifiable.
    """
    good = _recorded(tmp_path, "stock_on_hand", value=3.0, title="honest")
    other = _recorded(tmp_path, "group_member", value=True, title="other")
    _write_pack(tmp_path, [good, other])

    rows = [json.loads(l) for l
            in (tmp_path / "fixtures.jsonl").read_text(encoding="utf-8").splitlines()]
    rows[0]["then"][0]["value"] = True
    rows[0]["then"][0]["witness"] = other.then[0].witness
    rows[0]["provenance"]["observation_refs"] = ["obs-1", other.then[0].witness]
    rows[0]["fixture_id"] = ""
    _reseal(tmp_path, rows, prune=True)

    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert len(loaded.invalid) == 1
    assert "DIFFERENT question" in loaded.invalid[0].reason


def test_attack_b_a_subset_pack_is_refused_by_its_own_orphaned_witnesses(
    tmp_path,
) -> None:
    """(b) SUBSET. Drop the fixtures a port fails, re-seal. Measured: clean, and
    nothing in the artifact said the pack was partial — fresh pack_id, no lineage
    to the original.

    Blocked BY CONSTRUCTION: the recorder witnessed values this pack no longer
    asserts. A pack that does not account for its own witnesses is a pack
    somebody took fixtures out of, and it says so in its own bytes.
    """
    fixtures = [_recorded(tmp_path, "stock_on_hand", value=float(i))
                for i in range(3)]
    _write_pack(tmp_path, fixtures)
    assert len(load_pack(tmp_path / "fixtures.jsonl").fixtures) == 3

    rows = [json.loads(l) for l
            in (tmp_path / "fixtures.jsonl").read_text(encoding="utf-8").splitlines()]
    _reseal(tmp_path, rows[:2])  # drop the third and re-issue the whole chain

    with pytest.raises(PackError) as exc:
        load_pack(tmp_path / "fixtures.jsonl")
    assert "claimed by no assertion" in str(exc.value)
    assert "judged whole" in str(exc.value)


def test_attack_b_a_subset_that_also_strips_the_witnesses_is_caught_by_the_ledger(
    tmp_path,
) -> None:
    """The completion of attack (b): drop the orphans too, so the pack is
    internally consistent again.

    Nothing inside a self-consistent artifact can refute it — this is the honest
    limit of local checks. What catches it is the ledger the module has always
    named and never called: ``registered_seals`` now has a caller, and the
    original pack's fixture set is on record as a superset of this one.
    """
    from ctkr.oracle.pack import REGISTRY_NAME

    (tmp_path / REGISTRY_NAME).write_text("", encoding="utf-8")
    pack_dir = tmp_path / "pack"
    fixtures = [_recorded(tmp_path, "stock_on_hand", value=float(i))
                for i in range(3)]
    honest = seal_recording(fixtures, [_Row(r) for r in _observations(fixtures)],
                            pack_dir)
    assert len(load_pack(pack_dir / "fixtures.jsonl").fixtures) == 3

    kept = fixtures[:2]
    seal_recording(kept, [_Row(r) for r in _observations(kept)], pack_dir)
    with pytest.raises(PackError) as exc:
        load_pack(pack_dir / "fixtures.jsonl")
    assert "STRICT SUBSET" in str(exc.value)
    assert honest.pack_id in str(exc.value)


def test_attack_c_a_fixture_cannot_mark_its_own_evidence_corroboration_only(
    tmp_path,
) -> None:
    """(c) SELF-MARKING. Set ``evidence_class="corroboration-only"`` on just the
    failing fixture and re-seal. Measured: EXIT=0, clean, "reproduced 100%",
    while ``[FAIL] group_member(A) expected == True, got False`` still printed.

    Blocked BY CONSTRUCTION twice over: the class is inside the fixture's hash,
    so the naive edit breaks the id; and the loader RE-DERIVES the exemption from
    the flow rather than believing the label, so re-hashing and re-sealing buys
    nothing either.
    """
    fx = _recorded(tmp_path, "group_member", value=True)
    _write_pack(tmp_path, [fx])
    assert len(load_pack(tmp_path / "fixtures.jsonl").fixtures) == 1

    row = json.loads((tmp_path / "fixtures.jsonl").read_text(encoding="utf-8"))
    row["provenance"]["evidence_class"] = "corroboration-only"
    row["provenance"]["evidence_note"] = "order-sensitive, honest"

    # 1. Without re-hashing: the id no longer hashes its own body.
    (tmp_path / "fixtures.jsonl").write_text(json.dumps(row) + "\n",
                                             encoding="utf-8")
    with pytest.raises(PackError):
        load_pack(tmp_path / "fixtures.jsonl")

    # 2. With the full attack — re-hash AND re-seal.
    row["fixture_id"] = ""
    _reseal(tmp_path, [row])
    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert loaded.fixtures == [], "an unearned exemption must not be honoured"
    assert "nothing in the fixture earns it" in loaded.invalid[0].reason


def test_a_corroboration_mark_the_loader_can_re_derive_still_stands(tmp_path) -> None:
    """The rule must not be a blanket refusal: the w0a case is genuinely
    order-sensitive and its exemption survives, because the loader can see the
    two writes sharing one effective time against one subject."""
    from ctkr.oracle.fixtures import order_sensitivity
    from ctkr.oracle.fixtures import WhenStep

    when = [
        WhenStep(action="record_log", alias="L1", kind="harvest",
                 against=["bin"], at="+0"),
        WhenStep(action="record_log", alias="L2", kind="harvest",
                 against=["bin"], at="+0"),
    ]
    assert order_sensitivity(when), "this flow IS order-sensitive"
    assert not order_sensitivity([]), "and an empty flow is not"


def test_invalid_evidence_is_carried_as_no_verdict_never_dropped(tmp_path) -> None:
    """A pack must not be able to shrink its own denominator by becoming
    unreadable — an unjudgeable fixture is NO VERDICT, not absence."""
    from ctkr.oracle.pack import InvalidFixture

    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(
        make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
        pack([fixture("ok", [soh(4.0)])],
             invalid=[InvalidFixture("bad", "a stale fixture", "derivation moved")]),
        manifest,
    )
    assert report.score.fixtures_invalid == 1
    assert report.score.no_verdict == 1
    assert report.score.no_verdict_by_cause[NoVerdictCause.INVALID_EVIDENCE] == 1
    assert not report.clean
    assert report.invalid_evidence


def test_a_real_decision_about_the_wrong_topic_cannot_sanction() -> None:
    """Risk 2. Five stock-arithmetic divergences all citing ``birth-uniqueness``
    — a real kernel decision, about BIRTH LOGS — were accepted:
    ``diverged 5 / failed 0 / reproduced 25/25 = 100.0%``, exit downgraded 1→3.
    """
    from ctkr.oracle.port_contract import Divergence

    fx = fixture("f-topic", [soh(4.0)])
    declared = [Divergence.model_validate({
        "fixture_id": "f-topic", "assert": "stock_on_hand", "subject": "bin",
        "port_value": 9.0, "reason": "sanctioned", "decision_id": "birth-uniqueness",
    })]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=declared)
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           overrides={"stock_on_hand": 9.0})
    report = verify_port(
        adapter, pack([fx]), manifest,
        decisions={"birth-uniqueness": "an animal has at most one birth log"},
    )
    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.FAILED
    assert report.score.scored_diverged == 0
    assert any("does not CITE" in p for p in report.declaration_problems)


def test_a_topically_bound_decision_still_sanctions() -> None:
    """The check must not be a blanket refusal: an honest divergence survives."""
    from ctkr.oracle.port_contract import Divergence

    fx = fixture("f-topic-ok", [soh(4.0)])
    declared = [Divergence.model_validate({
        "fixture_id": "f-topic-ok", "assert": "stock_on_hand", "subject": "bin",
        "port_value": 9.0, "reason": "pending-bearing numerics",
        "decision_id": "pending-status-gates",
    })]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"], divergences=declared)
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           overrides={"stock_on_hand": 9.0})
    report = verify_port(
        adapter, pack([fx]), manifest,
        # A sanction is a typed CITATION of the glossary term (MetaCoding-n9o);
        # prose naming the term no longer sanctions anything.
        decisions={"pending-status-gates":
                   {"text": "pending logs are excluded from stock",
                    "sanctions": ("stock_on_hand",)}},
    )
    assert report.verdicts[0].outcomes[0].status == AssertionStatus.DIVERGED
    assert decision_covers({"sanctions": ("stock_on_hand",)}, "stock_on_hand")
    assert not decision_covers("… stock_on_hand …", "stock_on_hand")  # names never sanction


# =========================================================================== #
# I3 — ABSENCE OF AN ANSWER IS NEVER AN ANSWER                                #
# =========================================================================== #
def test_a_port_that_declines_where_it_would_be_wrong_is_not_clean() -> None:
    """Risk 1, the sharpest attack on the judge.

    A bridge that declined exactly the inputs it would get wrong reported
    ``answered 24, UNANSWERABLE 6, failed 0, reproduced 24/24 = 100.0%``, versus
    ``5 proven-wrong values, EXIT=1`` when it did not decline. The defendant
    chose whether its own refusal counted as a gap or a failure, and nothing
    flagged "declared this probe, then declined 6/30 of its calls".
    """
    gap = {"unanswerable": "no row for this input"}
    fixtures = [fixture(f"f{i}", [soh(4.0)]) for i in range(3)]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest,
                           overrides={"stock_on_hand": gap})
    report = verify_port(adapter, pack(fixtures), manifest)

    s = report.score
    assert s.no_verdict == 3
    assert s.no_verdict_by_cause[NoVerdictCause.DECLINED] == 3
    assert s.scored_passed == 0
    assert not report.clean
    # The declines are reported AGAINST THE PORT, with the count — they are not
    # gaps in the pack, and they are not silently absorbed into "coverage".
    assert any("declined 3 call(s)" in p for p in report.declaration_problems)
    assert "3/3 NO VERDICT" in s.headline()


def test_no_verdict_is_one_bucket_with_every_cause_named() -> None:
    """The buckets must partition the pack exactly — nothing falls out."""
    fx = fixture("f-mixed", [soh(4.0), {"assert": "adjustment_count",
                                        "subject": "bin", "op": "==",
                                        "value": 1}])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack([fx]), manifest)
    s = report.score
    assert s.answered + s.no_verdict == s.assertions_total
    assert sum(s.no_verdict_by_cause.values()) == s.no_verdict
    assert s.no_verdict_by_cause[NoVerdictCause.UNDECLARED] == 1


def test_a_silent_bridge_yields_a_verdict_within_its_own_timeout() -> None:
    """C5. A bridge that answered ``describe`` and then slept consumed the whole
    tool timeout and produced NO verdict, ever (exit 124, then exit 143).
    ``BridgeSpec.timeout`` was applied only to ``proc.wait()`` at shutdown.
    """
    script = (
        "import sys, json, time\n"
        "line = sys.stdin.readline()\n"
        "sys.stdout.write(json.dumps({'id': json.loads(line)['id'], 'ok': True,"
        " 'value': {'operations': [], 'probes': []}}) + '\\n')\n"
        "sys.stdout.flush()\n"
        "time.sleep(600)\n"
    )
    manifest = PortManifest(
        port="sleeper",
        bridge={"command": ["python3", "-c", script], "timeout": 0.75},
    )
    bridge = PortBridge(manifest)
    assert bridge.call("describe") == {"operations": [], "probes": []}

    started = time.monotonic()
    with pytest.raises(BridgeError, match="did not answer"):
        bridge.call("reset")
    elapsed = time.monotonic() - started
    assert elapsed < 5.0, f"the judge waited {elapsed:.1f}s on a silent bridge"
    # And it does not wait again: the bridge is dead, not slow.
    with pytest.raises(BridgeError):
        bridge.call("reset")
    bridge.stop()


def test_a_dead_bridge_becomes_no_verdict_not_a_crash() -> None:
    """An orchestrator waiting on N results must get N results."""
    class Silent:
        calls: list[str] = []

        def call(self, op, **payload):
            if op == "describe":
                return {"operations": ALL_OPS, "probes": ["stock_on_hand"]}
            raise BridgeError("port bridge did not answer within 0.5s")

        def stop(self) -> None:
            pass

    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = PortAdapter(manifest, bridge=Silent())
    report = verify_port(adapter, pack([fixture("f", [soh(4.0)])]), manifest)
    assert report.score.no_verdict == 1
    assert report.score.no_verdict_by_cause[NoVerdictCause.BRIDGE_DEAD] == 1
    assert not report.clean


def test_response_correlation_is_mandatory() -> None:
    """Risk 7. ``if resp.get("id") not in (None, req["id"])`` made correlation
    opt-out by the defendant: a bridge omitting ``id`` may answer out of order,
    including replaying a previous fixture's correct answer."""
    script = (
        "import sys, json\n"
        "for line in sys.stdin:\n"
        "    sys.stdout.write(json.dumps({'ok': True, 'value': 1}) + '\\n')\n"
        "    sys.stdout.flush()\n"
    )
    manifest = PortManifest(
        port="uncorrelated",
        bridge={"command": ["python3", "-c", script], "timeout": 5.0},
    )
    bridge = PortBridge(manifest)
    with pytest.raises(BridgeError, match="must echo its request id"):
        bridge.call("describe")
    bridge.stop()


def test_the_report_never_offers_a_quotable_hundred_percent() -> None:
    """Whatever else it says, the headline names the whole pack."""
    fixtures = [fixture(f"g{i}", [soh(4.0)]) for i in range(2)]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack(fixtures), manifest)
    assert "of 2 in the pack" in report.score.headline()


# --------------------------------------------------------------------------- #
# helpers                                                                      #
# --------------------------------------------------------------------------- #
def _iso(epoch: int) -> str:
    from datetime import UTC, datetime

    return datetime.fromtimestamp(epoch, tz=UTC).isoformat(timespec="seconds")


class _patched_probe:
    """Swap one entry of the probe contract for the duration of a test."""

    def __init__(self, term: str, spec) -> None:
        self.term, self.spec = term, spec

    def __enter__(self):
        self.old = PROBE_CONTRACT[self.term]
        PROBE_CONTRACT[self.term] = self.spec
        return self.spec

    def __exit__(self, *exc):
        PROBE_CONTRACT[self.term] = self.old
        return False


def _recorded(tmp_path: Path, assertion: str, value, *,
              title: str = "") -> SemanticFixture:
    """A fixture shaped as the RECORDER writes them — witnesses and stamps."""
    then = {"assert": assertion, "subject": "bin", "op": "==", "value": value}
    if assertion == "stock_on_hand":
        then |= {"measure": "weight", "unit": "kilograms"}
    if assertion == "group_member":
        then |= {"subject": "bin", "group": "herd"}
    given = [{"entity": "equipment", "alias": "bin", "name": "feed bin"}]
    if assertion == "group_member":
        given.append({"entity": "group", "alias": "herd", "name": "herd"})
    title = title or f"a recorded {assertion}"
    then["witness"] = blake3(
        f"w:{title}:{assertion}:{value}".encode()
    ).hexdigest()[:16]
    fx = SemanticFixture.model_validate({
        "title": title,
        "feature": "core",
        "given": given,
        "when": [],
        "then": [then],
        "provenance": {
            "source_system": "farmOS", "source_version": "4.x", "flow": "t",
            "observation_refs": ["obs-1", then["witness"]],
            "derivations": current_derivations(),
        },
    }).with_id()
    return fx


def _observations(fixtures: list[SemanticFixture]) -> list[dict]:
    """The boundary record plus one WITNESS per assertion, as the recorder writes."""
    rows: list[dict] = [{"obs_id": "obs-1", "method": "GET", "path": "/api",
                         "record": "boundary"}]
    for fx in fixtures:
        for t in fx.then:
            rows.append({
                "obs_id": t.witness, "method": "OBSERVE",
                "path": f"probe/{t.assert_}", "record": "witness",
                "probe": probe_descriptor(t), "observed": t.value,
            })
    return rows


def _write_pack(tmp_path: Path, fixtures: list[SemanticFixture],
                *, seal: bool = True, observations: list[dict] | None = None) -> None:
    rows = _observations(fixtures) if observations is None else observations
    if not seal:
        write_fixtures(fixtures, tmp_path / "fixtures.jsonl")
        (tmp_path / "observations.jsonl").write_text(
            "".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
        return
    seal_recording(fixtures, [_Row(r) for r in rows], tmp_path, register=False)


class _Row:
    """A recorded row the sealer can serialise, standing in for an Observation."""

    def __init__(self, row: dict) -> None:
        self._row = row

    def model_dump(self) -> dict:
        return self._row
