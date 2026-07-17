"""Tests for the mechanical intention harvest (Stage T5a / §9.2).

Hermetic: a small synthetic graph + real source files under ``tmp_path`` so the
source-slice harvest (S4/A2/A6/S3) has something to read. Pins the mechanism;
the MetaCoding self-index acceptance run (determinism, port-critical conflict,
≥70% boundary-export test-linkage) lives in the task evidence, not here.
"""

from __future__ import annotations

from pathlib import Path

import networkx as nx
import polars as pl

from ctkr.intention import (
    canonical_marker,
    compute_intention,
    fold_affixes,
    load_norm_tables,
    naming_pattern,
    tokenize_identifier,
    write_intention_signals,
)
from ctkr.schema import (
    INTENTION_CONFLICTS_COLUMNS,
    INTENTION_LOAD_COLUMNS,
    INTENTION_SIGNALS_COLUMNS,
    SUBSYSTEM_MEMBERS_COLUMNS,
    IntentionConflictRow,
    IntentionLoadRow,
    IntentionSignalRow,
)

TABLES = load_norm_tables()


# ───────────────────────── tokenizer / normalization ─────────────────────────


def test_tokenizer_case_equivalence() -> None:
    """§7.1(1): camelCase ≡ snake_case ≡ PascalCase all fold to one sequence."""
    want = ["get", "user", "by", "id"]
    assert tokenize_identifier("getUserById") == want
    assert tokenize_identifier("get_user_by_id") == want
    assert tokenize_identifier("GetUserByID") == want
    assert tokenize_identifier("get-user-by-id") == want


def test_tokenizer_qualified_and_digits() -> None:
    assert tokenize_identifier("a/svc.ts::SessionCache") == ["a", "svc", "ts", "session", "cache"]
    assert tokenize_identifier("parseV2Config") == ["parse", "v", "2", "config"]


def test_fold_affixes_marks_convention() -> None:
    """Abstract-prefix + Impl-suffix fold out, tagged with portability (§7.1(2))."""
    domain, folded = fold_affixes(["abstract", "session", "impl"], TABLES, "ts")
    assert domain == ["session"]
    assert {a for a, _ in folded} == {"abstract", "impl"}


def test_marker_canonicalization() -> None:
    assert canonical_marker("TODO", TABLES) == "TODO"
    assert canonical_marker("fix-me", TABLES) == "FIXME"
    assert canonical_marker("kludge", TABLES) == "HACK"
    assert canonical_marker("banana", TABLES) is None


def test_naming_pattern_coherent_is_low_entropy() -> None:
    """A coherent role (all *Validator) has ~0 entropy; a mixed one is higher."""
    content, ent = naming_pattern(
        ["RateValidator", "NameValidator", "SizeValidator"], TABLES, "py"
    )
    assert "validator" in content
    assert ent == 0.0
    _, ent_mixed = naming_pattern(["Loader", "Parser", "Sink"], TABLES, "py")
    assert ent_mixed > ent


# ───────────────────────── synthetic corpus ─────────────────────────


def _corpus(tmp_path: Path) -> tuple[nx.MultiDiGraph, dict, Path]:
    """Build a repo ``R`` under ``tmp_path/R`` + a graph with an export, a test
    that calls it, a raise site, a docstring, and a role class.

    Layout: ``svc.py`` holds ``get_session`` (a read-named export that WRITES a
    field across the boundary — the port-critical fixture) and ``RateValidator``
    /``NameValidator`` (a coherent role). ``test_svc.py`` calls ``get_session``.
    """
    repo = tmp_path / "R"
    (repo).mkdir()
    (repo / "svc.py").write_text(
        '''\
def get_session(key, ttl):
    """Return the cached session for key.

    :param key: the session key
    """
    raise ValueError("session key %s unknown; expected a live handle" % key)


class RateValidator:
    """Validate the rate policy."""


class NameValidator:
    """Validate the name policy."""
''',
        encoding="utf-8",
    )
    (repo / "test_svc.py").write_text(
        "from svc import get_session\n\n"
        "def test_get_session_raises_on_unknown_key():\n"
        "    get_session('x', 1)\n",
        encoding="utf-8",
    )

    g = nx.MultiDiGraph()

    def add(nid, qn, kind, line, end, sig=None, file="svc.py", lang="py", short=None):
        g.add_node(
            nid, repo="R", qualified_name=qn, file=file, file_path=file, kind=kind,
            line=line, end_line=end, signature=sig, language=lang,
            short_name=short or qn.split("::")[-1],
        )

    add("svcF", "svc.py", "file", 1, 20, file="svc.py")
    add("get_session", "svc.py::get_session", "function", 1, 6, sig="(key, ttl)")
    # Session lives in a DIFFERENT subsystem (model.py) so get_session's writes
    # cross the boundary — the port-critical condition (§6.1 require_boundary).
    add("Session", "model.py::Session", "class", 1, 10, file="model.py")
    add("sess_last", "model.py::Session::last_seen", "field", 2, 2, file="model.py")
    add("RateValidator", "svc.py::RateValidator", "class", 9, 11)
    add("NameValidator", "svc.py::NameValidator", "class", 13, 15)
    # test file symbols
    add("testF", "test_svc.py", "file", 1, 4, file="test_svc.py")
    add("test_get", "test_svc.py::test_get_session_raises_on_unknown_key", "function",
        3, 4, file="test_svc.py")

    for child in ("get_session", "Session", "RateValidator", "NameValidator"):
        g.add_edge("svcF", child, key="CONTAINS", kind="CONTAINS")
    g.add_edge("Session", "sess_last", key="CONTAINS", kind="CONTAINS")
    g.add_edge("testF", "test_get", key="CONTAINS", kind="CONTAINS")

    # get_session WRITES Session.last_seen across the boundary (port-critical:
    # a read-named symbol that mutates external state) + a RAISES edge.
    g.add_edge("get_session", "sess_last", key="WRITES_FIELD", kind="WRITES_FIELD")
    g.add_edge("get_session", "Session", key="CONSTRUCTS", kind="CONSTRUCTS")
    g.add_edge("get_session", "Verr", key="RAISES", kind="RAISES")
    g.add_node("Verr", repo="R", qualified_name="builtins::ValueError", kind="class",
               short_name="ValueError", file="", line=None)
    # the test CALLS the export (reverse-edge test linkage)
    g.add_edge("test_get", "get_session", key="CALLS", kind="CALLS")
    # an external caller in another subsystem references get_session (makes it a
    # boundary export + gives Session a cross-subsystem write target)
    g.add_node("ext", repo="R", qualified_name="app.py::main", kind="function",
               file="app.py", file_path="app.py", line=1, end_line=2, short_name="main")
    g.add_edge("ext", "get_session", key="REFERENCES", kind="REFERENCES")

    members = []
    for n, d in g.nodes(data=True):
        sub = "ss:svc" if (d.get("file") or "").startswith(("svc", "test")) else "ss:app"
        members.append(
            {"subsystem_id": sub, "symbol_id": n, "repo": "R",
             "qualified_name": d.get("qualified_name") or n, "boundary_confidence": 1.0,
             "placement": "structural", "schema_version": 1}
        )
    mem = pl.DataFrame(members).select(SUBSYSTEM_MEMBERS_COLUMNS)

    # interfaces: get_session is provided (external ext references it)
    iface = pl.DataFrame(
        [{
            "subsystem_id": "ss:svc", "repo": "R", "direction": "provides",
            "edge_kind": "REFERENCES", "edge_count": 1,
            "internal_symbol_id": "get_session",
            "internal_qualified_name": "svc.py::get_session",
            "internal_export_symbol_id": "get_session",
            "internal_export_qualified_name": "svc.py::get_session",
            "external_symbol_id": "ext", "external_qualified_name": "app.py::main",
            "external_subsystem_id": "ss:app", "schema_version": 1,
        }]
    )
    presentations = pl.DataFrame(
        [{
            "subsystem_id": "ss:svc", "repo": "R", "role_id": "role:validator",
            "view": "similarity", "granularity": "0.8", "cardinality": 2,
            "members": ["RateValidator", "NameValidator"],
            "exemplar_symbol_id": "RateValidator",
            "exemplar_qualified_name": "svc.py::RateValidator",
            "profile_centroid": [1.0, 2.0], "profile_depth": 1,
            "interface_participation": [], "persistence": 1.0, "config": "{}",
            "generated_at": "t", "schema_version": 1,
        }]
    )
    return g, {"mem": mem, "iface": iface, "pres": presentations}, tmp_path


def test_harvest_shapes_and_schema(tmp_path: Path) -> None:
    g, dfs, root = _corpus(tmp_path)
    sig, load, conf, stats = compute_intention(
        g, members_df=dfs["mem"], interfaces_df=dfs["iface"],
        data_shapes_df=None, presentations_df=dfs["pres"], repo_root=root,
    )
    assert list(sig.columns) == list(INTENTION_SIGNALS_COLUMNS)
    assert list(load.columns) == list(INTENTION_LOAD_COLUMNS)
    assert list(conf.columns) == list(INTENTION_CONFLICTS_COLUMNS)
    for d in sig.to_dicts():
        IntentionSignalRow.model_validate(d)
    for d in load.to_dicts():
        IntentionLoadRow.model_validate(d)
    for d in conf.to_dicts():
        IntentionConflictRow.model_validate(d)


def test_harvest_indicators_present(tmp_path: Path) -> None:
    """The export yields S2 (name+params), S4 (docstring), S3 (raise + errmsg),
    and S1 (the test that calls it)."""
    g, dfs, root = _corpus(tmp_path)
    sig, _, _, _ = compute_intention(
        g, members_df=dfs["mem"], interfaces_df=dfs["iface"],
        data_shapes_df=None, presentations_df=dfs["pres"], repo_root=root,
    )
    exp = sig.filter(pl.col("element_id") == "get_session")
    kinds = set(exp["indicator_kind"].to_list())
    assert {"S1", "S2", "S3", "S4"} <= kinds
    contents = exp["content"].to_list()
    assert any(c.startswith("param:") for c in contents)  # parameter names
    assert any("raises:ValueError" in c for c in contents)  # raised type
    assert any("errmsg:" in c and "session key" in c for c in contents)  # error string
    assert any(c.startswith("test:") for c in contents)  # S1 test linkage
    # A5 naming pattern on the role class
    a5 = sig.filter(pl.col("indicator_kind") == "A5")
    assert a5.height == 1
    assert "validator" in a5["content"][0]


def test_portability_tiers_assigned(tmp_path: Path) -> None:
    g, dfs, root = _corpus(tmp_path)
    sig, _, _, _ = compute_intention(
        g, members_df=dfs["mem"], interfaces_df=dfs["iface"],
        data_shapes_df=None, presentations_df=dfs["pres"], repo_root=root,
    )
    tiers = set(sig["portability_tier"].to_list())
    assert tiers <= {"I", "N", "A"}
    # S1 test linkage is universal (intent-I); S2 identifiers are convention (N)
    s1 = sig.filter(pl.col("indicator_kind") == "S1")
    assert set(s1["portability_tier"].to_list()) == {"I"}
    s2 = sig.filter(pl.col("indicator_kind") == "S2")
    assert set(s2["portability_tier"].to_list()) == {"N"}


def test_port_critical_conflict_surfaced(tmp_path: Path) -> None:
    """The seeded read-named-but-writes-state export trips a port-critical
    conflict and is forced out of structure-clear (§5.2 override, §6.1)."""
    g, dfs, root = _corpus(tmp_path)
    _, load, conf, stats = compute_intention(
        g, members_df=dfs["mem"], interfaces_df=dfs["iface"],
        data_shapes_df=None, presentations_df=dfs["pres"], repo_root=root,
    )
    assert stats.n_port_critical >= 1
    pc = conf.filter(pl.col("severity") == "port-critical")
    assert "get_session" in pc["element_id"].to_list()
    assert "read-name-writes-state" in pc["detector_id"].to_list()
    # the override: get_session is not structure-clear despite determinate shape
    row = load.filter(pl.col("element_id") == "get_session").to_dicts()[0]
    assert row["port_critical_conflict"] is True
    assert row["load_class"] != "structure-clear"


def test_load_scores_have_drivers(tmp_path: Path) -> None:
    g, dfs, root = _corpus(tmp_path)
    _, load, _, _ = compute_intention(
        g, members_df=dfs["mem"], interfaces_df=dfs["iface"],
        data_shapes_df=None, presentations_df=dfs["pres"], repo_root=root,
    )
    for row in load.to_dicts():
        assert 0.0 <= row["structural_determinacy"] <= 1.0
        assert 0.0 <= row["intention_richness"] <= 1.0
        assert row["drivers"]  # §5.3: ship the drivers so the score is auditable


def test_harvest_deterministic_byte_identical(tmp_path: Path) -> None:
    g, dfs, root = _corpus(tmp_path)
    out = tmp_path / "out"
    for tag in ("run1", "run2"):
        sig, _, _, _ = compute_intention(
            g, members_df=dfs["mem"], interfaces_df=dfs["iface"],
            data_shapes_df=None, presentations_df=dfs["pres"], repo_root=root,
        )
        write_intention_signals(sig, out / f"sig_{tag}.parquet")
    assert (out / "sig_run1.parquet").read_bytes() == (out / "sig_run2.parquet").read_bytes()
