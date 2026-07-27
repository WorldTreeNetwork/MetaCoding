"""The enum-vocabulary provenance channel (MetaCoding-852).

Closed-set VALUES (LOG_STATUSES 'abandoned', LAND_TYPES, STRUCTURE_TYPES)
previously bound with commit-message provenance only. These tests pin the
channel's whole bar: rows are cited (config_source required at load),
witnessed (bind only via a sealed pack exercising the value in its set's
declared position), reversible (drift in either direction refuses), and
GOVERNED (growing a governed set without a row fails this suite).

The fake-it question, answered per test: a row without a citation, a bind
without a witness, a witness-by-mere-substring, and a set grown behind the
registry's back each fail loudly.
"""

import json
from pathlib import Path

import pytest

from ctkr.oracle.glossary_provenance import (
    ENUM_VALUE_KIND,
    GOVERNED_SETS,
    ProvenanceError,
    add_enum_value,
    bind_enum_value,
    governance_problems,
    load_registry,
    provisional_terms,
)


def _row(term: str, set_name: str, status: str = "provisional",
         seal: str | None = None, config_source: str = "cited.yml:x") -> dict:
    return {
        "term": term, "kind": ENUM_VALUE_KIND, "set": set_name,
        "description": "t",
        "provenance": {"config_source": config_source,
                       "first_pack_seal": seal, "punts": [],
                       "role_class_id": None},
        "status": status,
    }


def _write(tmp_path: Path, rows: list[dict]) -> Path:
    p = tmp_path / "reg.jsonl"
    p.write_text("".join(json.dumps(r) + "\n" for r in rows), encoding="utf-8")
    return p


def test_the_committed_registry_is_governed() -> None:
    """The teeth: every non-grandfathered member of every governed set has a
    row in the COMMITTED registry. Growing LOG_STATUSES / LAND_TYPES /
    STRUCTURE_TYPES in glossary.py without a provenance row fails here."""
    assert governance_problems() == []


def test_witnessed_backfills_are_bound_and_unwitnessed_are_provisional() -> None:
    """Honesty of the backfill itself: 'abandoned' and the three structure
    kinds have sealed witnesses and are bound; no committed pack carries a
    land descriptor, so every LAND_TYPES row is provisional."""
    rows = {(r["set"], r["term"]): r for r in load_registry()
            if r["kind"] == ENUM_VALUE_KIND}
    assert rows[("LOG_STATUSES", "abandoned")]["status"] == "bound"
    for v in ("building", "greenhouse", "other"):
        assert rows[("STRUCTURE_TYPES", v)]["status"] == "bound"
    for v in ("bed", "field", "landmark", "other", "paddock", "property"):
        assert rows[("LAND_TYPES", v)]["status"] == "provisional"


def test_a_row_for_a_value_the_glossary_does_not_carry_refuses_to_load(tmp_path) -> None:
    p = _write(tmp_path, [_row("barn", "STRUCTURE_TYPES")])
    with pytest.raises(ProvenanceError, match="not a member"):
        load_registry(p)


def test_a_row_naming_no_real_glossary_set_refuses_to_load(tmp_path) -> None:
    p = _write(tmp_path, [_row("x", "IMAGINARY_SET")])
    with pytest.raises(ProvenanceError, match="not a glossary frozenset"):
        load_registry(p)


def test_an_uncited_enum_row_refuses_to_load(tmp_path) -> None:
    """A row without config_source is the exact gap the channel closes —
    hand-editing one in must fail as loudly as never writing it."""
    p = _write(tmp_path, [_row("other", "STRUCTURE_TYPES", config_source=" ")])
    with pytest.raises(ProvenanceError, match="no config_source"):
        load_registry(p)


def test_the_same_value_may_row_in_two_sets_but_not_twice_in_one(tmp_path) -> None:
    ok = _write(tmp_path, [_row("other", "STRUCTURE_TYPES"),
                           _row("other", "LAND_TYPES")])
    assert len([r for r in load_registry(ok)]) == 2
    dup = _write(tmp_path, [_row("other", "STRUCTURE_TYPES"),
                            _row("other", "STRUCTURE_TYPES")])
    with pytest.raises(ProvenanceError, match="duplicate"):
        load_registry(dup)


def test_a_term_row_may_not_carry_set(tmp_path) -> None:
    row = _row("other", "STRUCTURE_TYPES")
    row["kind"] = "assertion"
    p = _write(tmp_path, [row])
    with pytest.raises(ProvenanceError, match="only an enum_value row"):
        load_registry(p)


def test_add_requires_a_citation_and_registers_once(tmp_path) -> None:
    p = tmp_path / "reg.jsonl"
    with pytest.raises(ProvenanceError, match="config_source"):
        add_enum_value("other", "STRUCTURE_TYPES", config_source="  ", path=p)
    add_enum_value("other", "STRUCTURE_TYPES", config_source="c.yml:x", path=p)
    with pytest.raises(ProvenanceError, match="registered once"):
        add_enum_value("other", "STRUCTURE_TYPES", config_source="c.yml:x", path=p)


def test_bind_refuses_a_pack_without_the_witness_position(tmp_path) -> None:
    """The sensor pack is sealed and VALID but carries no structure given —
    a real pack in the wrong position must not witness the value (and a mere
    substring match anywhere in the pack must never count)."""
    p = tmp_path / "reg.jsonl"
    add_enum_value("greenhouse", "STRUCTURE_TYPES", config_source="c.yml:x", path=p)
    sensor_pack = (Path(__file__).resolve().parents[2] / "eval" / "ctkr"
                   / "port_runs" / "wave2" / "identity-sensor" / "observe"
                   / "fixtures.jsonl")
    if not sensor_pack.exists():
        pytest.skip("no committed sensor pack in this tree")
    with pytest.raises(ProvenanceError, match="witness position"):
        bind_enum_value("greenhouse", "STRUCTURE_TYPES", sensor_pack, path=p)


def test_bind_flips_via_a_real_witnessing_pack(tmp_path) -> None:
    p = tmp_path / "reg.jsonl"
    add_enum_value("greenhouse", "STRUCTURE_TYPES", config_source="c.yml:x", path=p)
    pack = (Path(__file__).resolve().parents[2] / "eval" / "ctkr"
            / "port_runs" / "wave2" / "identity-structure" / "observe"
            / "fixtures.jsonl")
    if not pack.exists():
        pytest.skip("no committed structure pack in this tree")
    row = bind_enum_value("greenhouse", "STRUCTURE_TYPES", pack, path=p)
    assert row["status"] == "bound" and row["provenance"]["first_pack_seal"]
    with pytest.raises(ProvenanceError, match="issued once"):
        bind_enum_value("greenhouse", "STRUCTURE_TYPES", pack, path=p)


def test_an_ungoverned_set_cannot_bind_without_a_declared_witness_position(tmp_path) -> None:
    """The witness map is CLOSED on purpose: 'appears somewhere in the
    fixture' would let any string constant witness anything."""
    p = tmp_path / "reg.jsonl"
    add_enum_value("increment", "ADJUSTMENT_KINDS", config_source="c.yml:x", path=p)
    pack = (Path(__file__).resolve().parents[2] / "eval" / "ctkr"
            / "port_runs" / "wave2" / "identity-structure" / "observe"
            / "fixtures.jsonl")
    if not pack.exists():
        pytest.skip("no committed structure pack in this tree")
    with pytest.raises(ProvenanceError, match="no declared witness position"):
        bind_enum_value("increment", "ADJUSTMENT_KINDS", pack, path=p)


def test_enum_values_never_leak_into_term_gating() -> None:
    """provisional_terms feeds port-verify's NO-VERDICT gate on TERM names;
    a provisional enum value (e.g. LAND_TYPES 'field') must not shadow or
    gate anything there."""
    assert "bed" not in provisional_terms()
    assert "field" not in provisional_terms()


def test_every_governed_set_has_a_witness_position() -> None:
    """A set can be governed only if its values can eventually bind."""
    from ctkr.oracle.fixtures import GivenStep
    from ctkr.oracle.glossary_provenance import _enum_witness_positions

    class _FX:  # minimal fixture shape
        given = [GivenStep(entity="land", alias="A", name="n")]
        when: list = []
        then: list = []

    for set_name in GOVERNED_SETS:
        _enum_witness_positions(set_name, "x", _FX())  # must not raise
