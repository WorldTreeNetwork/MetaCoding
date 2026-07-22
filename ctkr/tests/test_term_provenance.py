"""The glossary binding gate (bead MetaCoding-b5r).

Hermetic: no Docker, no oracle, no network, no dependence on any sandbox. A
term enters the glossary like a decision enters the registry — cited,
witnessed, reversible — and these tests pin the properties, not the guards:

* a registry row claiming ``bound`` with no ``first_pack_seal`` cannot load;
* only a SEALED pack whose valid fixtures exercise a term can bind it;
* a PROVISIONAL term cannot score in port-verify — the port is never asked.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest
from blake3 import blake3

from ctkr.oracle import glossary_provenance as gp
from ctkr.oracle.fixtures import SemanticFixture, probe_descriptor, write_fixtures
from ctkr.oracle.pack import PackError, seal_recording
from ctkr.oracle.port_verify import AssertionStatus, NoVerdictCause, verify_port
from tests.test_port_verify import ALL_OPS, fixture, make_adapter, make_manifest, pack, soh

TERM = "widget_count"

SPEC = {
    "term": TERM,
    "kind": "assertion",
    "description": "How many widgets are delivered against an asset.",
    "probe_semantics": "Deliver the number of widgets the boundary reports "
                       "for the subject as a domain count.",
    "discriminating_flow": {
        "given": ["an equipment"],
        "when": ["record a widget"],
        "then": [f"{TERM} == 1"],
    },
    "provenance": {
        "role_class_id": "abc123",
        "config_source": "modules/widget/widget.type.yml",
        "punts": ["invented for the binding-gate tests"],
        "first_pack_seal": None,
    },
}


def spec(**overrides) -> dict:
    s = json.loads(json.dumps(SPEC))
    s.update(overrides)
    return s


# --------------------------------------------------------------------------- #
# TERM-SPEC v1 validation                                                      #
# --------------------------------------------------------------------------- #
def test_a_valid_spec_has_no_problems() -> None:
    assert gp.validate_term_spec(spec()) == []


@pytest.mark.parametrize(
    "mutation",
    [
        {"term": "Not-Snake"},
        {"kind": "adjective"},
        {"description": "  "},
        {"probe_semantics": ""},
        {"discriminating_flow": {}},
    ],
)
def test_a_broken_spec_is_named(mutation: dict) -> None:
    assert gp.validate_term_spec(spec(**mutation))


def test_a_spec_arriving_with_a_seal_is_refused() -> None:
    """first_pack_seal is filled by observation (bind-term), never supplied."""
    s = spec()
    s["provenance"]["first_pack_seal"] = "deadbeef"
    problems = gp.validate_term_spec(s)
    assert any("first_pack_seal" in p for p in problems)


# --------------------------------------------------------------------------- #
# Registry rows                                                                #
# --------------------------------------------------------------------------- #
def _write_rows(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "glossary_provenance.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def _row(**overrides) -> dict:
    row = {
        "term": TERM, "kind": "assertion", "status": "provisional",
        "provenance": {"role_class_id": None, "config_source": None,
                       "punts": [], "first_pack_seal": None},
    }
    row.update(overrides)
    return row


def test_the_in_repo_registry_exists_and_loads() -> None:
    """The version-controlled registry beside glossary.py is always loadable."""
    assert gp.DEFAULT_REGISTRY.exists()
    gp.load_registry()  # must not raise


def test_a_missing_registry_is_an_empty_registry(tmp_path) -> None:
    assert gp.load_registry(tmp_path / "nope.jsonl") == []
    assert gp.provisional_terms(tmp_path / "nope.jsonl") == frozenset()


def test_a_bound_row_without_a_seal_is_INVALID(tmp_path) -> None:
    """The core rule of the registry, stated by the bead: status=bound with no
    first_pack_seal is not a binding, and the loader refuses the registry."""
    p = _write_rows(tmp_path, [_row(status="bound")])
    with pytest.raises(gp.ProvenanceError, match="first_pack_seal"):
        gp.load_registry(p)


def test_a_provisional_row_with_a_seal_is_INVALID(tmp_path) -> None:
    row = _row()
    row["provenance"]["first_pack_seal"] = "deadbeef"
    p = _write_rows(tmp_path, [row])
    with pytest.raises(gp.ProvenanceError, match="cannot disagree"):
        gp.load_registry(p)


def test_duplicate_and_malformed_rows_refuse_the_registry(tmp_path) -> None:
    p = _write_rows(tmp_path, [_row(), _row()])
    with pytest.raises(gp.ProvenanceError, match="duplicate"):
        gp.load_registry(p)
    p2 = _write_rows(tmp_path, [_row(status="blessed")])
    with pytest.raises(gp.ProvenanceError, match="blessed"):
        gp.load_registry(p2)


def test_add_provisional_appends_a_row_that_reloads(tmp_path) -> None:
    p = tmp_path / "reg.jsonl"
    row = gp.add_provisional(spec(), p)
    assert row["status"] == "provisional"
    assert row["provenance"]["first_pack_seal"] is None
    assert gp.provisional_terms(p) == frozenset({TERM})
    assert "PROVISIONAL" in gp.provisional_reason(TERM, p)
    with pytest.raises(gp.ProvenanceError, match="already has a provenance row"):
        gp.add_provisional(spec(), p)


# --------------------------------------------------------------------------- #
# Sealed-pack helpers (shaped as the recorder writes them)                     #
# --------------------------------------------------------------------------- #
def _recorded(assertion: str, value, extra_then: dict | None = None) -> SemanticFixture:
    then = {"assert": assertion, "subject": "bin", "op": "==", "value": value}
    then |= extra_then or {}
    then["witness"] = blake3(f"w:{assertion}:{value}".encode()).hexdigest()[:16]
    return SemanticFixture.model_validate({
        "title": f"a recorded {assertion}",
        "feature": "core",
        "given": [{"entity": "equipment", "alias": "bin", "name": "feed bin"}],
        "when": [],
        "then": [then],
        "provenance": {
            "source_system": "farmOS", "source_version": "4.x", "flow": "t",
            "observation_refs": ["obs-1", then["witness"]],
        },
    }).with_id()


def _observations(fixtures: list[SemanticFixture]) -> list:
    class _Row:
        def __init__(self, row: dict) -> None:
            self._row = row

        def model_dump(self) -> dict:
            return self._row

    rows = [_Row({"obs_id": "obs-1", "method": "GET", "path": "/api",
                  "record": "boundary"})]
    for fx in fixtures:
        for t in fx.then:
            rows.append(_Row({
                "obs_id": t.witness, "method": "OBSERVE",
                "path": f"probe/{t.assert_}", "record": "witness",
                "probe": probe_descriptor(t), "observed": t.value,
            }))
    return rows


def _sealed_pack(pack_dir: Path, fixtures: list[SemanticFixture]):
    return seal_recording(fixtures, _observations(fixtures), pack_dir,
                          register=False)


# --------------------------------------------------------------------------- #
# bind-term: the gate itself                                                   #
# --------------------------------------------------------------------------- #
def test_bind_requires_a_provenance_row(tmp_path) -> None:
    _sealed_pack(tmp_path / "pack", [_recorded(TERM, 1)])
    with pytest.raises(gp.ProvenanceError, match="no provenance row"):
        gp.bind_term(TERM, tmp_path / "pack" / "fixtures.jsonl",
                     tmp_path / "reg.jsonl")


def test_an_unsealed_pack_cannot_bind(tmp_path) -> None:
    """The chain of custody is the gate: no seal, no binding, whatever is on disk."""
    reg = tmp_path / "reg.jsonl"
    gp.add_provisional(spec(), reg)
    loose = tmp_path / "loose"
    loose.mkdir()
    write_fixtures([_recorded(TERM, 1)], loose / "fixtures.jsonl")
    with pytest.raises(PackError):
        gp.bind_term(TERM, loose / "fixtures.jsonl", reg)
    assert gp.provisional_terms(reg) == frozenset({TERM})


def test_a_sealed_pack_that_does_not_exercise_the_term_cannot_bind(tmp_path) -> None:
    reg = tmp_path / "reg.jsonl"
    gp.add_provisional(spec(), reg)
    _sealed_pack(tmp_path / "pack", [_recorded("asset_active", True)])
    with pytest.raises(gp.ProvenanceError, match="no VALID fixture"):
        gp.bind_term(TERM, tmp_path / "pack" / "fixtures.jsonl", reg)
    assert gp.provisional_terms(reg) == frozenset({TERM})


def test_binding_fills_the_seal_and_flips_the_status_once(tmp_path) -> None:
    reg = tmp_path / "reg.jsonl"
    gp.add_provisional(spec(), reg)
    seal = _sealed_pack(tmp_path / "pack", [_recorded(TERM, 1)])

    row = gp.bind_term(TERM, tmp_path / "pack" / "fixtures.jsonl", reg)
    assert row["status"] == "bound"
    assert row["provenance"]["first_pack_seal"] == seal.seal
    assert row["bound_pack_id"] == seal.pack_id
    # The rewritten registry is still wholly valid, and the term is scorable.
    assert gp.provisional_terms(reg) == frozenset()
    assert gp.provisional_reason(TERM, reg) == ""
    # A binding is issued once.
    with pytest.raises(gp.ProvenanceError, match="already bound"):
        gp.bind_term(TERM, tmp_path / "pack" / "fixtures.jsonl", reg)


def test_exercised_positions_follow_the_kind() -> None:
    fx = _recorded("asset_active", True)
    assert gp._exercises(fx, "equipment", "entity")
    assert not gp._exercises(fx, "asset_active", "entity")
    assert gp._exercises(fx, "asset_active", "assertion")
    assert not gp._exercises(fx, "record_log", "action")


# --------------------------------------------------------------------------- #
# port-verify: a provisional term cannot score                                 #
# --------------------------------------------------------------------------- #
def test_a_provisional_term_yields_NO_VERDICT_and_the_port_is_never_asked(
    tmp_path, monkeypatch,
) -> None:
    """The scoring half of the gate, mirroring the corroboration-only and
    unvalidated-derivation exclusions: the judge consults the provenance
    registry BEFORE the port is called, so agreement with a proposal can never
    masquerade as evidence."""
    reg = _write_rows(tmp_path, [_row(term="stock_on_hand")])
    monkeypatch.setattr(gp, "DEFAULT_REGISTRY", reg)

    fx = fixture("f-prov", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest)
    report = verify_port(adapter, pack([fx]), manifest)

    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.NO_VERDICT
    assert o.cause == NoVerdictCause.PROVISIONAL
    assert "bind-term" in o.detail
    assert "stock_on_hand" not in adapter._bridge.calls  # noqa: SLF001
    assert report.score.scored_passed == 0
    assert not report.clean


def test_a_bound_term_scores_normally(tmp_path, monkeypatch) -> None:
    """Same registry, same term, status=bound: the gate opens and the port is
    judged on the value it delivers."""
    bound = _row(term="stock_on_hand", status="bound")
    bound["provenance"]["first_pack_seal"] = "cafe" * 8
    reg = _write_rows(tmp_path, [bound])
    monkeypatch.setattr(gp, "DEFAULT_REGISTRY", reg)

    fx = fixture("f-bound", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest)
    report = verify_port(adapter, pack([fx]), manifest)

    o = report.verdicts[0].outcomes[0]
    assert o.status == AssertionStatus.PASSED
    assert report.score.scored_passed == 1


def test_an_invalid_registry_stops_the_judge_loudly(tmp_path, monkeypatch) -> None:
    """A broken instrument must halt, never quietly score around itself."""
    reg = _write_rows(tmp_path, [_row(term="stock_on_hand", status="bound")])
    monkeypatch.setattr(gp, "DEFAULT_REGISTRY", reg)

    fx = fixture("f-broken", [soh(4.0)])
    manifest = make_manifest(ALL_OPS, ["stock_on_hand"])
    adapter = make_adapter(ALL_OPS, ["stock_on_hand"], manifest)
    with pytest.raises(gp.ProvenanceError):
        verify_port(adapter, pack([fx]), manifest)
