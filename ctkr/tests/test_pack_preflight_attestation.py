"""A sealed pack must witness that the oracle gate ran (MetaCoding-hy6.48).

THE PROPERTY: *a verdict cannot read as gated unless the recording it rests on
was.* Not "packs should be gated" — that is a wish, and a wish is enforced by
whoever remembers it. The gate became a precondition of recording on 2026-08-07
(hy6.25/hy6.28) precisely because two ports had probed bundles that were never
enabled and written down as findings about farmOS what were measurements of the
ORACLE. It left no trace in the artifact, so a pack recorded behind it and a pack
recorded with it skipped were byte-indistinguishable downstream.

WHERE IT IS ENFORCED, and why there: :func:`ctkr.oracle.pack.seal_recording`.
This project has no CI and no git hooks (``docs/design/enforceability.md``), and
three gates here were built correct and wired to nothing. Recording a pack must
traverse the sealing code, so a refusal there is one nothing can route around.

THE FAKE-IT QUESTION, asked of every red below: *would this fixture give the same
answer under the mutation?* The one that matters is
:func:`test_the_ungated_reading_is_not_a_side_effect_of_anything_else`, which runs
the SAME fixtures, the same port and the same score twice, differing in exactly
one thing — whether the seal carries an attestation — so nothing but the
attestation can be producing the difference.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from ctkr.oracle.pack import (
    PackError,
    PreflightAttestation,
    SEAL_NAME,
    load_pack,
    seal_recording,
)
from ctkr.oracle.port_verify import verify_port
from tests._synthetic_ledger import (  # noqa: F401 — synthetic_ledger fixture
    _Row,
    observation_rows,
    preflight_report,
    recorded_fixture,
    synthetic_ledger,
)
from tests.test_port_verify import (
    ALL_OPS,
    fixture,
    make_adapter,
    make_manifest,
    pack,
    soh,
)


def _seal_into(tmp_path: Path, **kw):
    """Seal a one-fixture recording into ``tmp_path``. ``kw`` goes to the sealer."""
    # stock_on_hand, so the pack VALIDATES cleanly: the surface under test in
    # oracle-validate is the sentence printed when nothing else is wrong.
    fixtures = [recorded_fixture("stock_on_hand", 4.0)]
    rows = observation_rows(fixtures)
    return seal_recording(fixtures, [_Row(r) for r in rows], tmp_path,
                          register=False, **kw)


# =========================================================================== #
# The refusal, and its contrast                                               #
# =========================================================================== #
def test_sealing_without_a_preflight_attestation_is_refused(tmp_path) -> None:
    """THE RED. Without the rule this seals happily and returns a PackSeal."""
    with pytest.raises(PackError) as exc:
        _seal_into(tmp_path)
    assert "no preflight attestation" in str(exc.value)
    # And it refuses before it writes: a half-written pack directory would be a
    # pack somebody could seal by hand afterwards.
    assert not (tmp_path / SEAL_NAME).exists()


def test_sealing_with_a_passing_preflight_report_succeeds(tmp_path) -> None:
    """THE CONTRAST. Same call, one argument different, and the pack exists."""
    seal = _seal_into(tmp_path, preflight=preflight_report())
    assert seal.preflight is not None
    assert (tmp_path / SEAL_NAME).exists()
    assert load_pack(tmp_path / "fixtures.jsonl").fixtures


@pytest.mark.parametrize(
    "mutate,expected",
    [
        pytest.param(lambda r: r.update(base_url=""), "which oracle", id="no-base-url"),
        pytest.param(lambda r: r.update(types={}), "ZERO resource types", id="no-types"),
        pytest.param(lambda r: r.update(advertised=[]), "advertised", id="no-advertised"),
        pytest.param(
            lambda r: r["module_drift"].update(checked=False, reason="docker absent"),
            "REFUSAL, not a pass", id="drift-check-did-not-run",
        ),
        pytest.param(
            lambda r: r["types"].update({"log--medical": "MISSING (absent from /api index)"}),
            "CLEARED", id="a-type-that-did-not-clear",
        ),
        pytest.param(
            lambda r: r["types"].update(
                {"log--medical": "GET /api/log/medical -> 200 but body is not JSON"}),
            "CLEARED", id="200-but-not-a-collection",
        ),
        pytest.param(lambda r: r.update(ok=False, error="preflight failed"),
                     "ok=false", id="a-report-of-a-failed-gate"),
        pytest.param(lambda r: r.pop("module_drift"), "did not run", id="no-drift-key"),
    ],
)
def test_a_report_that_does_not_show_a_gate_cannot_become_an_attestation(
    tmp_path, mutate, expected,
) -> None:
    """Absence of an answer is never a yes.

    Each row is a report that a caller could plausibly hold and that does NOT
    say the gate cleared this recording. The two ``200 but …`` rows are the
    discriminating ones: a naive check for "-> 200" in the detail passes both,
    which is why the loader matches the success sentence exactly.
    """
    report = preflight_report()
    mutate(report)
    with pytest.raises(PackError) as exc:
        _seal_into(tmp_path, preflight=report)
    assert expected in str(exc.value)
    assert not (tmp_path / SEAL_NAME).exists()


@pytest.mark.parametrize("junk", ["", None, [], "{}", 7])
def test_a_report_we_cannot_read_is_not_a_report(tmp_path, junk) -> None:
    """A preflight whose report you cannot read must refuse, not pass."""
    with pytest.raises(PackError):
        _seal_into(tmp_path, preflight=junk)


# =========================================================================== #
# The attestation travels, and is bound to the seal                           #
# =========================================================================== #
def test_the_attestation_survives_the_round_trip_with_the_material_that_matters(
    tmp_path,
) -> None:
    """It is verifiable LATER — which is the whole point of putting it in the seal.

    What must survive: that the gate ran, WHICH types it cleared, and enough
    identity of the oracle to tell one instance from another.
    """
    _seal_into(tmp_path, preflight=preflight_report(
        base_url="http://oracle-a:8095", types=("asset--sensor", "log--observation")))
    att = load_pack(tmp_path / "fixtures.jsonl").seal.preflight
    assert att is not None
    assert att.base_url == "http://oracle-a:8095"
    assert att.types_cleared == ["asset--sensor", "log--observation"]
    assert att.modules_checked is True
    assert len(att.oracle_fingerprint) == 32
    assert att.oracle_advertises == 4


def test_the_oracle_fingerprint_tells_two_oracles_apart(tmp_path) -> None:
    """THE FAKE-IT QUESTION for identity: a constant would satisfy the test above.

    Two oracles differing in one enabled bundle — the exact difference hy6.25 is
    about — must not share a fingerprint. Same advertised set, same fingerprint;
    that half is what stops "just hash the timestamp" from passing.
    """
    a = PreflightAttestation.from_report(
        preflight_report(types=("asset--sensor",)))
    b = PreflightAttestation.from_report(
        preflight_report(types=("asset--plant",)))
    same = PreflightAttestation.from_report(
        preflight_report(types=("asset--sensor",)))
    assert a.oracle_fingerprint != b.oracle_fingerprint
    assert a.oracle_fingerprint == same.oracle_fingerprint


def test_stripping_the_attestation_off_a_sealed_pack_is_refused(tmp_path) -> None:
    """The attestation is INSIDE the seal hash, so an attested pack cannot be
    quietly downgraded to a legacy-looking one by deleting a key."""
    _seal_into(tmp_path, preflight=preflight_report())
    seal_path = tmp_path / SEAL_NAME
    body = json.loads(seal_path.read_text(encoding="utf-8"))
    body.pop("preflight")
    seal_path.write_text(json.dumps(body, indent=2), encoding="utf-8")
    with pytest.raises(PackError) as exc:
        load_pack(tmp_path / "fixtures.jsonl")
    assert "does not hash its own contents" in str(exc.value)


def test_a_legacy_seal_that_never_had_one_still_verifies_its_own_hash(
    tmp_path,
) -> None:
    """The contrast to the test above, and the reason the field is omitted rather
    than written as null: a pack sealed in July must keep LOADING. Breaking its
    hash would accuse it of tampering, which is false, and would hide the true
    fact — that nothing gated it — behind a fabricated one.
    """
    _seal_into(tmp_path, preflight=preflight_report())
    seal_path = tmp_path / SEAL_NAME
    body = json.loads(seal_path.read_text(encoding="utf-8"))
    body.pop("preflight")
    from ctkr.oracle.pack import PackSeal

    legacy = PackSeal.model_validate(body).sealed()   # what July's sealer wrote
    seal_path.write_text(legacy.model_dump_json(indent=2), encoding="utf-8")
    loaded = load_pack(tmp_path / "fixtures.jsonl")
    assert loaded.fixtures, "a legacy pack must still load"
    assert loaded.seal.preflight is None
    assert "NO PREFLIGHT ATTESTATION" in loaded.ungated_reason


# =========================================================================== #
# How an un-attested pack READS where a verdict is produced                   #
# =========================================================================== #
def test_the_ungated_reading_is_not_a_side_effect_of_anything_else() -> None:
    """THE DISCRIMINATING FIXTURE.

    Two runs of the same port over the same fixtures, differing in exactly one
    bit: whether the seal carries an attestation. Every number is identical — so
    if `clean` still agreed, or if the ungated run moved a score, the reading
    would be measuring something other than the gate.
    """
    fixtures = [fixture("f-gate", [soh(4.0)])]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])

    gated = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                        pack(fixtures), manifest, {})
    ungated = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                          pack(fixtures, gated=False), manifest, {})

    assert gated.score.model_dump() == ungated.score.model_dump()
    assert gated.clean is True and gated.needs_review == []
    assert ungated.clean is False
    assert ungated.needs_review == ["UNGATED PACK — " + ungated.pack_ungated]
    # The port is not accused: an ungated pack is a fact about the EVIDENCE.
    assert ungated.score.scored_failed == 0
    assert not ungated.declaration_problems
    assert not ungated.invalid_evidence


def test_a_gated_verdict_names_the_oracle_it_was_gated_against() -> None:
    """An attestation nobody can reach from the verdict is a field, not a control."""
    fixtures = [fixture("f-gate", [soh(4.0)])]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    report = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                         pack(fixtures), manifest, {})
    assert report.preflight is not None
    assert report.preflight.base_url
    assert report.preflight.types_cleared


def test_port_verify_prints_the_gate_beside_the_score(capsys) -> None:
    """Visible where a reader is, not only in the JSON. A reader who sees 100%
    and must look elsewhere to learn the pack was ungated will not look."""
    from ctkr.commands.port_verify import _emit_text

    fixtures = [fixture("f-gate", [soh(4.0)])]
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    ungated = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                          pack(fixtures, gated=False), manifest, {})
    _emit_text(ungated)
    out = capsys.readouterr().err
    assert "UNGATED PACK" in out
    assert "NOT A CLEAN PASS" in out

    gated = verify_port(make_adapter(ALL_OPS, ["stock_on_hand"], manifest),
                        pack(fixtures), manifest, {})
    _emit_text(gated)
    out = capsys.readouterr().err
    assert "UNGATED" not in out
    assert "type(s) cleared" in out


def test_oracle_validate_does_not_give_an_ungated_pack_a_clean_bill(
    tmp_path, capsys,
) -> None:
    """The other verdict surface. `invalid: []` over an ungated pack used to read
    as "verified" with nothing said about the gate."""
    import argparse

    from ctkr.commands.oracle_validate import run
    from ctkr.oracle.pack import PackSeal

    _seal_into(tmp_path, preflight=preflight_report())
    seal_path = tmp_path / SEAL_NAME
    body = json.loads(seal_path.read_text(encoding="utf-8"))
    body.pop("preflight")
    seal_path.write_text(
        PackSeal.model_validate(body).sealed().model_dump_json(indent=2),
        encoding="utf-8")

    args = argparse.Namespace(fixtures=str(tmp_path / "fixtures.jsonl"),
                              unsealed_ok=False, as_json=False)
    run(args)
    err = capsys.readouterr().err
    assert "[UNGATED]" in err
    assert "UNGATED" in err.split("all fixtures valid")[1]

    args.as_json = True
    run(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["preflight"] is None
    assert "NO PREFLIGHT ATTESTATION" in payload["ungated"]


def test_a_gated_pack_validates_without_the_ungated_banner(tmp_path, capsys) -> None:
    """The contrast: the banner must not be unconditional decoration."""
    import argparse

    from ctkr.commands.oracle_validate import run

    _seal_into(tmp_path, preflight=preflight_report())
    args = argparse.Namespace(fixtures=str(tmp_path / "fixtures.jsonl"),
                              unsealed_ok=False, as_json=True)
    run(args)
    payload = json.loads(capsys.readouterr().out)
    assert payload["ungated"] == ""
    assert payload["preflight"]["modules_checked"] is True


# =========================================================================== #
# The recording CLI: refuse early, and refuse the wrong oracle                #
# =========================================================================== #
def _record_args(tmp_path, **kw):
    import argparse

    return argparse.Namespace(
        preflight_report=kw.get("report", ""),
        base_url=kw.get("base_url", "http://synthetic-oracle:8095"),
    )


def test_oracle_record_refuses_to_start_without_a_preflight_report(tmp_path) -> None:
    from ctkr.commands.oracle_record import _load_preflight

    with pytest.raises(PackError) as exc:
        _load_preflight(_record_args(tmp_path))
    assert "--preflight-report is required" in str(exc.value)


def test_oracle_record_refuses_a_report_it_cannot_read(tmp_path) -> None:
    from ctkr.commands.oracle_record import _load_preflight

    bad = tmp_path / "preflight.json"
    bad.write_text("not json at all", encoding="utf-8")
    with pytest.raises(PackError) as exc:
        _load_preflight(_record_args(tmp_path, report=str(bad)))
    assert "cannot read preflight report" in str(exc.value)

    with pytest.raises(PackError):
        _load_preflight(_record_args(tmp_path, report=str(tmp_path / "absent.json")))


def test_oracle_record_refuses_a_preflight_of_a_different_oracle(tmp_path) -> None:
    """A gate on one farmOS is not a gate on another — the same defect ledger.py
    closes between its own preflight and its transport (hy6.28)."""
    from ctkr.commands.oracle_record import _load_preflight

    path = tmp_path / "preflight.json"
    path.write_text(json.dumps(preflight_report(base_url="http://oracle-a:8095")),
                    encoding="utf-8")
    with pytest.raises(PackError) as exc:
        _load_preflight(_record_args(tmp_path, report=str(path),
                                     base_url="http://oracle-b:8095"))
    assert "not a gate on this one" in str(exc.value)

    # THE CONTRAST: the same report, against the oracle it actually cleared.
    got = _load_preflight(_record_args(tmp_path, report=str(path),
                                       base_url="http://oracle-a:8095/"))
    assert got["base_url"] == "http://oracle-a:8095"


def test_the_recorder_is_still_the_only_issuer_and_it_now_names_the_gate() -> None:
    """The CLI's own seal call must pass the report it validated — otherwise the
    early check is theatre and the sealer's refusal is the only thing running."""
    import inspect

    from ctkr.commands import oracle_record

    src = inspect.getsource(oracle_record)
    assert "seal_recording(fixtures, observations, out, preflight=preflight)" in src
