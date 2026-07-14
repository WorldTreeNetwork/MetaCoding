"""Tests for scoped operad recovery (Stage C / §4.3, T4).

Pure NumPy/Polars/NetworkX — no scipy — so these run in the base ctkr venv.

The centrepiece is a **hand-analyzed fixture**: a small synthetic "pipeline +
orchestrator" repo with a *written-down composition grammar* (the ``GRAMMAR``
table below). The acceptance shape (§9 T4) is asserted directly against it:

- recovered operations **cover the grammar** (recall ≥ 0.8);
- a support-ranked **precision** spot-check (no spurious high-support ops);
- **associativity / violation bookkeeping** is demonstrated (an observed
  associative composite; a ``missing_composite`` and a ``back_call_cycle``
  ``non_operadic`` row);
- **boundary ops** are correctly flagged against the T2 interface participation.

The graph is name-blind to the recovery code: roles come from a hand-built
``presentations`` frame (role_id ``role:<Label>`` so the test can read the label
back), exactly the T3 artifact ``operads.py`` consumes.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.operads import compute_operads, write_operads
from ctkr.schema import OPERADS_COLUMNS, OperadRow

FIXED_TS = "2026-07-14T00:00:00Z"
SUB = "ss:pipe"
REPO = "R"

# ── the hand-analyzed composition grammar (over role LABELS) ──────────────────
# Every rule here is a composition the fixture author put into the graph on
# purpose. Recovery must rediscover them from structure alone.
#
# path ops are (input_labels_tuple, output_label); fan_in ops are the same shape
# with the inputs as a *set* (order-insensitive). The recovered artifact is
# matched back to labels via the role_id ("role:<Label>") convention.
GRAMMAR_PATH: set[tuple[tuple[str, ...], str]] = {
    # arity-1 generators
    (("Handler",), "Validator"),
    (("Validator",), "Loader"),
    (("Loader",), "Store"),
    (("Orchestrator",), "Worker"),
    (("Worker",), "Orchestrator"),
    (("Handler",), "Serializer"),
    (("Worker",), "Serializer"),
    (("Cache",), "Store"),
    (("Store",), "Logger"),
    # arity-2 composites
    (("Handler", "Validator"), "Loader"),
    (("Validator", "Loader"), "Store"),
    (("Orchestrator", "Worker"), "Serializer"),
    (("Loader", "Store"), "Logger"),
}
GRAMMAR_FAN_IN: set[tuple[frozenset[str], str]] = {
    (frozenset({"Handler", "Worker"}), "Serializer"),
}

# roles exposed on the subsystem interface (T2 participation) → protocol roles.
PUBLIC_ROLES = {"Handler", "Store", "Serializer"}

# role → member symbol_ids (two-plus instances each so every composition recurs).
ROLE_MEMBERS: dict[str, list[str]] = {
    "Handler": ["h1", "h2"],
    "Validator": ["v1", "v2"],
    "Loader": ["l1", "l2"],
    "Store": ["st1", "st2", "st3", "st4"],
    "Cache": ["c1", "c2"],
    "Logger": ["lg1", "lg2"],
    "Orchestrator": ["o1", "o2"],
    "Worker": ["w1", "w2"],
    "Serializer": ["sz1", "sz2"],
}

# concrete CALLS edges — the behaviour the grammar is recovered from.
EDGES: list[tuple[str, str]] = [
    # pipeline chain: Handler→Validator→Loader→Store, twice
    ("h1", "v1"), ("h2", "v2"),
    ("v1", "l1"), ("v2", "l2"),
    ("l1", "st1"), ("l2", "st2"),
    # Store→Logger (from the Loader-fed Store nodes) → Loader→Store→Logger composite
    ("st1", "lg1"), ("st2", "lg2"),
    # Cache→Store into DISJOINT Store nodes (st3,st4) that never emit → the
    # Cache→Store→Logger composite is composable-at-role-level but never realized
    # → a missing_composite violation.
    ("c1", "st3"), ("c2", "st4"),
    # orchestrator loop with a genuine back-call (both directions recur) →
    # back_call_cycle violation.
    ("o1", "w1"), ("o2", "w2"),
    ("w1", "o1"), ("w2", "o2"),
    # fan-in at Serializer: called by Handler AND Worker → n-ary op; also gives
    # the Orchestrator→Worker→Serializer composite.
    ("h1", "sz1"), ("h2", "sz2"),
    ("w1", "sz1"), ("w2", "sz2"),
]


# ── fixture builders ──────────────────────────────────────────────────────────


def _sym2role() -> dict[str, str]:
    out: dict[str, str] = {}
    for role, members in ROLE_MEMBERS.items():
        for m in members:
            out[m] = role
    return out


def _build_graph() -> nx.MultiDiGraph:
    g = nx.MultiDiGraph()
    for role, members in ROLE_MEMBERS.items():
        for m in members:
            g.add_node(
                m,
                qualified_name=f"{REPO}::mod::{role}::{m}",
                kind="function",
                repo=REPO,
                file="mod.py",
            )
    for u, v in EDGES:
        g.add_edge(u, v, key="CALLS", kind="CALLS")
    return g


def _members_df() -> pl.DataFrame:
    rows = [
        {
            "subsystem_id": SUB,
            "symbol_id": m,
            "repo": REPO,
            "qualified_name": f"{REPO}::mod::{_sym2role()[m]}::{m}",
            "boundary_confidence": 1.0,
            "placement": "structural",
            "schema_version": 1,
        }
        for m in _sym2role()
    ]
    return pl.DataFrame(rows)


def _presentations_df(views: tuple[str, ...] = ("orbit", "similarity")) -> pl.DataFrame:
    """Hand-built role quotient — role_id encodes the label for readback.

    Mirrors the real T3 artifact, which always emits *both* the orbit and
    similarity views; the fixture roles are identical across views (clean,
    well-separated classes) so either dial recovers the same operad.
    """
    rows = []
    for view in views:
        for role, members in ROLE_MEMBERS.items():
            rows.append(
                {
                    "subsystem_id": SUB,
                    "repo": REPO,
                    "role_id": f"role:{role}",
                    "view": view,
                    "granularity": "exact" if view == "orbit" else "cos>=0.9",
                    "cardinality": len(members),
                    "members": members,
                    "exemplar_symbol_id": members[0],
                    "exemplar_qualified_name": f"{REPO}::mod::{role}::{members[0]}",
                    "profile_centroid": [0.0],
                    "profile_depth": 1,
                    "interface_participation": (
                        ["provides"] if role in PUBLIC_ROLES else []
                    ),
                    "persistence": 1.0,
                    "config": "{}",
                    "generated_at": FIXED_TS,
                    "schema_version": 1,
                }
            )
    return pl.DataFrame(rows)


def _label(role_id: str) -> str:
    return role_id.removeprefix("role:")


def _recovered_path_ops(df: pl.DataFrame) -> set[tuple[tuple[str, ...], str]]:
    out: set[tuple[tuple[str, ...], str]] = set()
    for r in df.filter(pl.col("op_kind") == "path").iter_rows(named=True):
        out.add((tuple(_label(x) for x in r["input_roles"]), _label(r["output_role"])))
    return out


def _recovered_fan_in_ops(df: pl.DataFrame) -> set[tuple[frozenset[str], str]]:
    out: set[tuple[frozenset[str], str]] = set()
    for r in df.filter(pl.col("op_kind") == "fan_in").iter_rows(named=True):
        out.add((frozenset(_label(x) for x in r["input_roles"]), _label(r["output_role"])))
    return out


def _run(view: str = "similarity", **kw) -> tuple[pl.DataFrame, object]:
    return compute_operads(
        _build_graph(),
        _members_df(),
        _presentations_df(),
        view=view,
        min_support=2,
        generated_at=FIXED_TS,
        **kw,
    )


# ── schema / structural invariants ────────────────────────────────────────────


def test_schema_columns_and_row_validation() -> None:
    df, _ = _run()
    assert list(df.columns) == list(OPERADS_COLUMNS)
    for d in df.to_dicts():
        OperadRow.model_validate(d)
    # every op is tier-I (composition laws over roles are port-invariant, §6.1)
    assert set(df["invariance_tier"].unique().to_list()) == {"I"}


# ── the acceptance: recall / precision against the written grammar ─────────────


def test_recall_covers_grammar() -> None:
    """Recovered ops cover the hand-written grammar with recall ≥ 0.8 (§9 T4)."""
    df, _ = _run()
    rec_path = _recovered_path_ops(df)
    rec_fan = _recovered_fan_in_ops(df)

    path_hits = len(GRAMMAR_PATH & rec_path)
    fan_hits = len(GRAMMAR_FAN_IN & rec_fan)
    total = len(GRAMMAR_PATH) + len(GRAMMAR_FAN_IN)
    recall = (path_hits + fan_hits) / total
    assert recall >= 0.8, (
        f"recall {recall:.2f} < 0.8; missing path "
        f"{GRAMMAR_PATH - rec_path}; missing fan {GRAMMAR_FAN_IN - rec_fan}"
    )
    # the clean fixture actually recovers everything.
    assert recall == 1.0


def test_precision_support_ranked_spot_check() -> None:
    """Support-ranked precision: every recovered path/fan_in op (the real
    operations, support ≥ 2) is a genuine grammar rule — no spurious ops."""
    df, _ = _run()
    real = df.filter(pl.col("op_kind").is_in(["path", "fan_in"]))
    # support-rank descending; spot-check the whole set (small fixture).
    grammar_all = GRAMMAR_PATH | {(tuple(sorted(s)), o) for s, o in GRAMMAR_FAN_IN}
    spurious = []
    for r in real.sort("support", descending=True).iter_rows(named=True):
        inp = tuple(_label(x) for x in r["input_roles"])
        out = _label(r["output_role"])
        key = (tuple(sorted(inp)), out) if r["op_kind"] == "fan_in" else (inp, out)
        if key not in grammar_all:
            spurious.append(key)
    precision = 1.0 - len(spurious) / max(1, real.height)
    assert precision >= 0.8, f"precision {precision:.2f} < 0.8; spurious {spurious}"
    assert spurious == []


# ── n-ary fan-in ──────────────────────────────────────────────────────────────


def test_fan_in_operation_recovered_with_arity() -> None:
    df, _ = _run()
    fan = df.filter(pl.col("op_kind") == "fan_in")
    assert fan.height == 1
    row = fan.to_dicts()[0]
    assert row["arity"] == 2
    assert {_label(x) for x in row["input_roles"]} == {"Handler", "Worker"}
    assert _label(row["output_role"]) == "Serializer"
    assert row["support"] == 2  # two Serializer targets exhibit the fan-in


# ── associativity + violation bookkeeping ─────────────────────────────────────


def test_associative_composite_observed() -> None:
    """A 3-node composite whose generators + composite are all observed is
    recorded associativity-consistent."""
    df, _ = _run()
    comp = df.filter(
        (pl.col("op_kind") == "path") & (pl.col("arity") == 2)
    )
    assert comp.height >= 1
    for r in comp.iter_rows(named=True):
        assert r["associative_observed"] is True
        assert r["law_violations"] == 0


def test_missing_composite_violation_recorded() -> None:
    """Cache→Store and Store→Logger both recur (compose at role level) but the
    Cache→Store→Logger composite is never realized → a non_operadic row."""
    df, _ = _run()
    viol = df.filter(pl.col("violation_kind") == "missing_composite")
    keys = {
        (tuple(_label(x) for x in r["input_roles"]), _label(r["output_role"]))
        for r in viol.iter_rows(named=True)
    }
    assert (("Cache", "Store"), "Logger") in keys
    for r in viol.iter_rows(named=True):
        assert r["op_kind"] == "non_operadic"
        assert r["associative_observed"] is False
        assert r["law_violations"] == 1


def test_back_call_cycle_violation_recorded() -> None:
    """Orchestrator→Worker and Worker→Orchestrator both recur → an observed
    2-cycle (the 'never calls back except through Callback' non-law)."""
    df, _ = _run()
    cyc = df.filter(pl.col("violation_kind") == "back_call_cycle")
    assert cyc.height == 1
    row = cyc.to_dicts()[0]
    roles = {_label(x) for x in row["input_roles"]} | {_label(row["output_role"])}
    assert roles == {"Orchestrator", "Worker"}
    assert row["op_kind"] == "non_operadic"


def test_stats_bookkeeping() -> None:
    df, stats = _run()
    assert stats.n_missing_composite == 1
    assert stats.n_back_call_cycle == 1
    assert stats.n_non_operadic == 2
    # the operad is non-trivial: path ops for all 13 grammar paths, 1 fan-in.
    assert stats.n_path_ops == len(GRAMMAR_PATH)
    assert stats.n_fan_in_ops == 1


# ── boundary (protocol) op flagging against T2 interfaces ─────────────────────


def test_boundary_ops_flagged_against_interface_participation() -> None:
    """is_boundary_op ⇔ some role of the op is public in the T2 interface."""
    df, _ = _run()
    for r in df.iter_rows(named=True):
        roles = {_label(x) for x in r["input_roles"]} | {_label(r["output_role"])}
        expected = len(roles & PUBLIC_ROLES) > 0
        assert r["is_boundary_op"] is expected, (r["op_kind"], roles)

    # concrete anchors: Loader→Store is a boundary/protocol op (Store public);
    # Validator→Loader is purely internal.
    def find(inp, out):
        for r in df.filter(pl.col("op_kind") == "path").iter_rows(named=True):
            if tuple(_label(x) for x in r["input_roles"]) == inp and _label(r["output_role"]) == out:
                return r
        return None

    assert find(("Loader",), "Store")["is_boundary_op"] is True
    assert find(("Validator",), "Loader")["is_boundary_op"] is False


def test_no_interface_participation_means_no_boundary_ops() -> None:
    """With interface participation stripped, no op is a protocol op — the flag
    is genuinely driven by the T2 join, not a constant."""
    pres = _presentations_df().with_columns(
        pl.lit([]).cast(pl.List(pl.Utf8)).alias("interface_participation")
    )
    df, _ = compute_operads(
        _build_graph(), _members_df(), pres, min_support=2, generated_at=FIXED_TS
    )
    assert df.filter(pl.col("is_boundary_op")).height == 0


# ── views + determinism ───────────────────────────────────────────────────────


def test_both_views_emitted() -> None:
    df, _ = _run(view="both")
    assert set(df["view"].unique().to_list()) == {"orbit", "similarity"}


def test_deterministic_byte_identical(tmp_path: Path) -> None:
    for tag in ("run1", "run2"):
        df, _ = _run()
        write_operads(df, tmp_path / f"op_{tag}.parquet")
    assert (tmp_path / "op_run1.parquet").read_bytes() == (
        tmp_path / "op_run2.parquet"
    ).read_bytes()


def test_operation_id_content_addressed_not_time_dependent() -> None:
    df_a, _ = _run()
    df_b, _ = compute_operads(
        _build_graph(),
        _members_df(),
        _presentations_df(),
        view="similarity",
        min_support=2,
        generated_at="2099-12-31T00:00:00Z",
    )
    assert set(df_a["operation_id"].to_list()) == set(df_b["operation_id"].to_list())


def test_min_support_filters_one_offs() -> None:
    """Raising min_support drops role-paths that don't recur."""
    # add a single Handler→Cache edge (support 1) — must not become an op.
    g = _build_graph()
    g.add_edge("h1", "c1", key="CALLS", kind="CALLS")
    df, _ = compute_operads(
        g, _members_df(), _presentations_df(), min_support=2, generated_at=FIXED_TS
    )
    ops = _recovered_path_ops(df)
    assert (("Handler",), "Cache") not in ops
