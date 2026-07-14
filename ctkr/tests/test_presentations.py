"""Tests for the per-subsystem role inventory (Stage C / §4.1, T3).

Pure NumPy/Polars — no scipy (union-find, not scipy.sparse.csgraph), so these
run in the base ctkr venv.

The co-classing tests model the design's acceptance directly: same-role members
must land in the same class (recall), distinct roles must stay apart
(discrimination), role_count << member_count (compression), every class has an
exemplar, and both the orbit-exact and similarity-cluster views are emitted.
"""

from __future__ import annotations

from pathlib import Path

import numpy as np
import polars as pl

from ctkr.presentations import (
    compute_role_inventory,
    write_presentations,
)
from ctkr.schema import (
    PRESENTATIONS_COLUMNS,
    PresentationRow,
)

FIXED_TS = "2026-07-14T00:00:00Z"


# ── fixture builders ──────────────────────────────────────────────────────────

# Depth-1 profile dimension used by the fixtures (arbitrary; the real artifact is
# 2*len(EDGE_KINDS)). Kept small so the prototypes are easy to read.
_DIM = 8


def _role_prototypes() -> dict[str, np.ndarray]:
    """Well-separated prototype profiles, one per (fixture) role.

    Each prototype loads a distinct pair of dimensions so cross-role cosine is
    low and same-role cosine is ~1 — the structural regime the depth-1 dial is
    designed for (within one subsystem, same-role members share an edge-mix).
    """
    protos: dict[str, np.ndarray] = {}
    specs = {
        "agent": (0, 1),
        "orchestrator": (2, 3),
        "tool": (4, 5),
        "memory": (6, 7),
        "task": (0, 4),
        "step_node": (1, 5),
    }
    for name, (a, b) in specs.items():
        v = np.zeros(_DIM, dtype=np.float64)
        v[a] = 5.0
        v[b] = 3.0
        protos[name] = v
    return protos


def _profiles_and_members(
    role_members: dict[str, list[str]],
    *,
    jitter: float = 0.0,
    subsystem_id: str = "ss:test",
    repo: str = "R",
) -> tuple[pl.DataFrame, pl.DataFrame]:
    """Build (hom_profiles_df, members_df) for members grouped by ground-truth role.

    ``jitter`` adds a small integer perturbation to one dimension per member so
    same-role members are *close but not identical* (the similarity regime; the
    orbit view needs jitter=0 to co-class). Deterministic per member id.
    """
    protos = _role_prototypes()
    hp_rows: list[dict[str, object]] = []
    mem_rows: list[dict[str, object]] = []
    for role, members in role_members.items():
        base = protos[role]
        for m in members:
            v = base.copy()
            if jitter:
                # deterministic per-member perturbation
                d = (abs(hash(m)) % _DIM)
                v[d] = v[d] + jitter
            hp_rows.append(
                {
                    "symbol_id": m,
                    "repo": repo,
                    "qualified_name": f"{repo}.{role}.{m}",
                    "profile_vec": [float(x) for x in v],
                    "schema_version": 1,
                }
            )
            mem_rows.append(
                {
                    "subsystem_id": subsystem_id,
                    "symbol_id": m,
                    "repo": repo,
                    "qualified_name": f"{repo}.{role}.{m}",
                    "boundary_confidence": 1.0,
                    "placement": "structural",
                    "schema_version": 1,
                }
            )
    hp = pl.DataFrame(hp_rows)
    mem = pl.DataFrame(mem_rows)
    return hp, mem


def _class_of(df: pl.DataFrame, view: str) -> dict[str, str]:
    """symbol_id -> role_id for one view (each member is in exactly one class)."""
    out: dict[str, str] = {}
    for r in df.filter(pl.col("view") == view).iter_rows(named=True):
        for m in r["members"]:
            out[m] = r["role_id"]
    return out


# ── schema / structural invariants ────────────────────────────────────────────


def test_schema_and_both_views_emitted() -> None:
    role_members = {
        "agent": ["a0", "a1", "a2"],
        "tool": ["t0", "t1"],
        "memory": ["m0", "m1"],
    }
    hp, mem = _profiles_and_members(role_members)
    df, stats = compute_role_inventory(hp, mem, None, generated_at=FIXED_TS)
    assert list(df.columns) == list(PRESENTATIONS_COLUMNS)
    for d in df.to_dicts():
        PresentationRow.model_validate(d)
    assert set(df["view"].unique().to_list()) == {"orbit", "similarity"}
    # Every member appears in exactly one class per view.
    for view in ("orbit", "similarity"):
        cls = _class_of(df, view)
        assert set(cls) == set(hp["symbol_id"].to_list())
    # Every class has an exemplar that is one of its members.
    for r in df.iter_rows(named=True):
        assert r["exemplar_symbol_id"] in r["members"]


def test_orbit_view_coclasses_exact_profiles() -> None:
    """Same-role members with IDENTICAL profiles co-class in the orbit view;
    distinct roles never merge."""
    role_members = {
        "agent": ["a0", "a1", "a2"],
        "orchestrator": ["o0", "o1"],
        "tool": ["t0", "t1", "t2"],
    }
    hp, mem = _profiles_and_members(role_members, jitter=0.0)
    df, _ = compute_role_inventory(hp, mem, None, generated_at=FIXED_TS)
    cls = _class_of(df, "orbit")
    # same-role → same class
    assert cls["a0"] == cls["a1"] == cls["a2"]
    assert cls["t0"] == cls["t1"] == cls["t2"]
    assert cls["o0"] == cls["o1"]
    # distinct roles → distinct classes
    assert len({cls["a0"], cls["o0"], cls["t0"]}) == 3
    # exactly 3 orbit classes for 8 members
    orbit = df.filter(pl.col("view") == "orbit")
    assert orbit.height == 3


def test_similarity_view_coclasses_jittered_and_discriminates() -> None:
    """Same-role members that are *close but not identical* co-class in the
    similarity view; well-separated roles stay in separate classes."""
    role_members = {
        "agent": [f"a{i}" for i in range(5)],
        "orchestrator": [f"o{i}" for i in range(4)],
        "tool": [f"t{i}" for i in range(4)],
        "memory": [f"m{i}" for i in range(3)],
    }
    hp, mem = _profiles_and_members(role_members, jitter=1.0)
    df, stats = compute_role_inventory(
        hp, mem, None, default_threshold=0.90, generated_at=FIXED_TS
    )
    cls = _class_of(df, "similarity")

    # same-role pairs co-class (recall)
    def all_same(ids: list[str]) -> bool:
        return len({cls[i] for i in ids}) == 1

    assert all_same(role_members["agent"])
    assert all_same(role_members["orchestrator"])
    assert all_same(role_members["tool"])
    assert all_same(role_members["memory"])
    # discrimination: the four roles are four distinct classes
    reps = [role_members[r][0] for r in role_members]
    assert len({cls[r] for r in reps}) == 4
    # compression: 16 members → 4 similarity roles
    assert stats.n_roles_similarity == 4
    assert stats.compression_similarity == 16 / 4


def test_within_repo_same_role_pairs_coclass_recall() -> None:
    """The T3 acceptance shape: same-role WITHIN-repo pairs co-class at ceiling.

    Mirrors the 9-cluster ground truth's within-repo pairs (§4.1 acceptance
    "restricted to within-repo pairs"): each pair is two same-role members in
    one repo. We assert 100% pair co-classing recall in BOTH views (identical
    profiles for the orbit view; the similarity view tolerates jitter) and zero
    false merges across distinct roles.
    """
    # Four within-repo same-role pairs (one per role), all in one subsystem —
    # the structure of the real within-repo restriction of role_equivalent_truth.
    role_members = {
        "agent": ["ag2::ConversableAgent", "ag2::AssistantAgent"],
        "orchestrator": ["agno::Team", "agno::Workflow"],
        "task": ["cf::Task_a", "cf::Task_b"],
        "step_node": ["lg::StateGraph", "lg::ToolNode"],
    }
    pairs = list(role_members.values())

    # orbit (exact profiles): every pair co-classes, roles stay apart.
    hp0, mem0 = _profiles_and_members(role_members, jitter=0.0)
    df0, _ = compute_role_inventory(hp0, mem0, None, generated_at=FIXED_TS)
    orbit = _class_of(df0, "orbit")
    recall_orbit = sum(1 for (x, y) in pairs if orbit[x] == orbit[y]) / len(pairs)
    assert recall_orbit == 1.0
    assert len({orbit[p[0]] for p in pairs}) == len(pairs)  # no false merges

    # similarity (jittered): same pair recall under the cosine dial.
    hp1, mem1 = _profiles_and_members(role_members, jitter=1.0)
    df1, _ = compute_role_inventory(hp1, mem1, None, generated_at=FIXED_TS)
    sim = _class_of(df1, "similarity")
    recall_sim = sum(1 for (x, y) in pairs if sim[x] == sim[y]) / len(pairs)
    assert recall_sim == 1.0


def test_zero_profile_members_form_single_isolated_class() -> None:
    """Edgeless (zero-vector) members collapse into ONE class per view rather
    than exploding into singletons — the §2.3 structural floor."""
    role_members = {"agent": ["a0", "a1"]}
    hp, mem = _profiles_and_members(role_members)
    # add three zero-profile members to the same subsystem
    extra_hp = pl.DataFrame(
        [
            {
                "symbol_id": z,
                "repo": "R",
                "qualified_name": f"R.const.{z}",
                "profile_vec": [0.0] * _DIM,
                "schema_version": 1,
            }
            for z in ("z0", "z1", "z2")
        ]
    )
    extra_mem = pl.DataFrame(
        [
            {
                "subsystem_id": "ss:test",
                "symbol_id": z,
                "repo": "R",
                "qualified_name": f"R.const.{z}",
                "boundary_confidence": 1.0,
                "placement": "locality",
                "schema_version": 1,
            }
            for z in ("z0", "z1", "z2")
        ]
    )
    hp = pl.concat([hp, extra_hp])
    mem = pl.concat([mem, extra_mem])
    df, _ = compute_role_inventory(hp, mem, None, generated_at=FIXED_TS)
    for view in ("orbit", "similarity"):
        cls = _class_of(df, view)
        assert cls["z0"] == cls["z1"] == cls["z2"], f"{view}: zeros not one class"
        # the isolated class is distinct from the agent class
        assert cls["z0"] != cls["a0"]


def test_interface_participation_from_interfaces() -> None:
    role_members = {"agent": ["a0", "a1"], "tool": ["t0", "t1"]}
    hp, mem = _profiles_and_members(role_members)
    interfaces = pl.DataFrame(
        [
            {
                "subsystem_id": "ss:test",
                "repo": "R",
                "direction": "provides",
                "edge_kind": "CALLS",
                "edge_count": 3,
                "internal_symbol_id": "a0",
                "internal_qualified_name": "R.agent.a0",
                "internal_export_symbol_id": "a0",
                "internal_export_qualified_name": "R.agent.a0",
                "external_symbol_id": "x0",
                "external_qualified_name": "R.other.x0",
                "external_subsystem_id": None,
                "schema_version": 1,
            },
            {
                "subsystem_id": "ss:test",
                "repo": "R",
                "direction": "consumes",
                "edge_kind": "CALLS",
                "edge_count": 1,
                "internal_symbol_id": "t0",
                "internal_qualified_name": "R.tool.t0",
                "internal_export_symbol_id": "t0",
                "internal_export_qualified_name": "R.tool.t0",
                "external_symbol_id": "y0",
                "external_qualified_name": "R.other.y0",
                "external_subsystem_id": None,
                "schema_version": 1,
            },
        ]
    )
    df, _ = compute_role_inventory(hp, mem, interfaces, generated_at=FIXED_TS)
    # The agent class (contains a0) participates in provides; tool class in consumes.
    for r in df.filter(pl.col("view") == "orbit").iter_rows(named=True):
        if "a0" in r["members"]:
            assert r["interface_participation"] == ["provides"]
        if "t0" in r["members"]:
            assert r["interface_participation"] == ["consumes"]


def test_compression_ratio_reported() -> None:
    role_members = {
        "agent": [f"a{i}" for i in range(6)],
        "tool": [f"t{i}" for i in range(6)],
    }
    hp, mem = _profiles_and_members(role_members)
    _, stats = compute_role_inventory(hp, mem, None, generated_at=FIXED_TS)
    assert stats.n_members_profiled == 12
    # exact profiles → 2 orbit roles → 6x compression
    assert stats.n_roles_orbit == 2
    assert stats.compression_orbit == 6.0


def test_deterministic_byte_identical(tmp_path: Path) -> None:
    role_members = {
        "agent": [f"a{i}" for i in range(4)],
        "tool": [f"t{i}" for i in range(4)],
        "memory": [f"m{i}" for i in range(3)],
    }
    hp, mem = _profiles_and_members(role_members, jitter=1.0)
    for tag in ("run1", "run2"):
        df, _ = compute_role_inventory(hp, mem, None, generated_at=FIXED_TS)
        write_presentations(df, tmp_path / f"pres_{tag}.parquet")
    assert (tmp_path / "pres_run1.parquet").read_bytes() == (
        tmp_path / "pres_run2.parquet"
    ).read_bytes()


def test_role_id_content_addressed_not_time_dependent() -> None:
    role_members = {"agent": ["a0", "a1"], "tool": ["t0", "t1"]}
    hp, mem = _profiles_and_members(role_members)
    df_a, _ = compute_role_inventory(hp, mem, None, generated_at="2026-01-01T00:00:00Z")
    df_b, _ = compute_role_inventory(hp, mem, None, generated_at="2099-12-31T00:00:00Z")
    assert set(df_a["role_id"].to_list()) == set(df_b["role_id"].to_list())
