"""Tests for the intent-CM → D-score coupling (dial-rec #2, MetaCoding-9h5.2).

Hermetic: synthetic intention_load frames + the shipped scoring dials only (no graph,
no LLM, no disk). Pins the coupling machinery — the discount is a dial, hard vs soft
weights are separate, only CM-tagged elements move, load_class is re-derived at the
discounted D, and the default catches the real UniqueBirthLog structure-clear miss
(D=0.7493, CM-hard) by dropping it below d_hi. The single real-run acceptance number
lives in the task evidence; the invariant is pinned here.
"""

from __future__ import annotations

import polars as pl

from ctkr.intention import (
    apply_cm_coupling,
    cm_discount,
    couple_cm_determinacy,
    load_norm_tables,
)
from ctkr.schema import INTENTION_LOAD_COLUMNS

TABLES = load_norm_tables()


def _load_row(
    eid: str,
    d: float,
    r: float,
    load_class: str,
    *,
    port_critical: bool = False,
    kind: str = "role-class",
) -> dict:
    return {
        "element_id": eid,
        "element_kind": kind,
        "structural_determinacy": d,
        "intention_richness": r,
        "load_class": load_class,
        "port_critical_conflict": port_critical,
        "drivers": ["synthetic"],
        "schema_version": 1,
    }


def _load_df(rows: list[dict]) -> pl.DataFrame:
    return pl.DataFrame(rows).select(INTENTION_LOAD_COLUMNS)


# ───────────────────────── discount dials ─────────────────────────


def test_cm_discount_reads_dials() -> None:
    assert cm_discount("hard", TABLES) == TABLES.scoring["d_cm_hard_discount"]
    assert cm_discount("soft", TABLES) == TABLES.scoring["d_cm_soft_discount"]


def test_cm_discount_none_and_unknown_are_zero() -> None:
    assert cm_discount(None, TABLES) == 0.0
    assert cm_discount("none", TABLES) == 0.0
    assert cm_discount("nonsense", TABLES) == 0.0


def test_cm_discount_accepts_cm_prefixed_grades() -> None:
    # scan_cm emits "CM-hard"/"CM-soft"; the coupling must accept both forms.
    assert cm_discount("CM-hard", TABLES) == TABLES.scoring["d_cm_hard_discount"]
    assert cm_discount("CM-soft", TABLES) == TABLES.scoring["d_cm_soft_discount"]


def test_hard_discount_stronger_than_soft() -> None:
    assert cm_discount("hard", TABLES) >= cm_discount("soft", TABLES)


# ───────────────────────── couple_cm_determinacy ─────────────────────────


def test_couple_returns_input_and_no_driver_for_untagged() -> None:
    d_eff, driver = couple_cm_determinacy(0.9, None, TABLES)
    assert d_eff == 0.9
    assert driver is None


def test_couple_discounts_and_emits_driver_for_hard() -> None:
    d_eff, driver = couple_cm_determinacy(0.7493, "hard", TABLES)
    expected = round(0.7493 * (1 - TABLES.scoring["d_cm_hard_discount"]), 4)
    assert d_eff == expected
    assert driver is not None
    assert "intent-CM hard" in driver


def test_couple_never_raises_on_unknown_grade() -> None:
    d_eff, driver = couple_cm_determinacy(0.5, "banana", TABLES)
    assert d_eff == 0.5
    assert driver is None


# ───────────────────────── apply_cm_coupling ─────────────────────────


def test_untagged_frame_passes_through_identically() -> None:
    df = _load_df([_load_row("e1", 0.9, 0.1, "structure-clear")])
    out = apply_cm_coupling(df, {}, TABLES)
    assert out.equals(df)


def test_empty_frame_returns_empty() -> None:
    df = _load_df([_load_row("e1", 0.9, 0.1, "structure-clear")]).filter(pl.lit(False))
    out = apply_cm_coupling(df, {"e1": "hard"}, TABLES)
    assert out.height == 0


def test_only_tagged_elements_move() -> None:
    df = _load_df([
        _load_row("keep", 0.90, 0.10, "structure-clear"),
        _load_row("hard", 0.7493, 0.4603, "structure-clear"),
    ])
    out = apply_cm_coupling(df, {"hard": "hard"}, TABLES)
    by = {r["element_id"]: r for r in out.iter_rows(named=True)}
    # untagged row identical
    assert by["keep"]["structural_determinacy"] == 0.90
    assert by["keep"]["load_class"] == "structure-clear"
    # tagged row discounted
    assert by["hard"]["structural_determinacy"] < 0.7493


def test_unique_birth_log_default_flips_out_of_structure_clear() -> None:
    """The load-bearing acceptance: the real UniqueBirthLog element (D=0.7493, CM-hard,
    R=0.4603) must leave structure-clear under the shipped default and land
    intention-critical (R >= r_min), catching the lone structure-clear miss."""
    df = _load_df([_load_row("role:70108211", 0.7493, 0.4603, "structure-clear")])
    out = apply_cm_coupling(df, {"role:70108211": "hard"}, TABLES)
    row = out.row(0, named=True)
    assert row["structural_determinacy"] < TABLES.scoring["d_hi"]
    assert row["load_class"] == "intention-critical"


def test_cm_soft_milder_discount_can_keep_structure_clear() -> None:
    # A high-D element tagged soft gets a milder discount; with D far above d_hi it
    # can remain structure-clear (soft != hard).
    df = _load_df([_load_row("s", 0.95, 0.1, "structure-clear")])
    out = apply_cm_coupling(df, {"s": "soft"}, TABLES)
    row = out.row(0, named=True)
    assert row["structural_determinacy"] == round(
        0.95 * (1 - TABLES.scoring["d_cm_soft_discount"]), 4
    )
    assert row["load_class"] == "structure-clear"


def test_zero_dials_disable_coupling() -> None:
    tables = load_norm_tables()
    tables.scoring["d_cm_hard_discount"] = 0.0
    tables.scoring["d_cm_soft_discount"] = 0.0
    df = _load_df([_load_row("e", 0.7493, 0.4603, "structure-clear")])
    out = apply_cm_coupling(df, {"e": "hard"}, tables)
    assert out.row(0, named=True)["structural_determinacy"] == 0.7493
    assert out.row(0, named=True)["load_class"] == "structure-clear"


def test_driver_appended_records_adjustment() -> None:
    df = _load_df([_load_row("e", 0.7493, 0.4603, "structure-clear")])
    out = apply_cm_coupling(df, {"e": "hard"}, TABLES)
    drivers = list(out.row(0, named=True)["drivers"])
    assert drivers[0] == "synthetic"  # original preserved
    assert any("intent-CM hard" in d for d in drivers)


def test_port_critical_low_D_stays_ambiguous_not_intention_critical() -> None:
    # port_critical forbids structure-clear; a discounted low-D + low-R element stays
    # ambiguous (R below r_min), confirming re-classification honors the columns.
    df = _load_df([_load_row("e", 0.60, 0.10, "ambiguous", port_critical=True)])
    out = apply_cm_coupling(df, {"e": "hard"}, TABLES)
    assert out.row(0, named=True)["load_class"] == "ambiguous"


def test_output_schema_preserved() -> None:
    df = _load_df([_load_row("e", 0.7493, 0.4603, "structure-clear")])
    out = apply_cm_coupling(df, {"e": "hard"}, TABLES)
    assert list(out.columns) == list(INTENTION_LOAD_COLUMNS)
