"""``ctkr add-term`` — spec-driven plumbing codegen (bead MetaCoding-b5r).

Hermetic. --apply is exercised ONLY against a throwaway copy of the oracle
tree built in tmp_path from this installation's own sources; the real tree is
only ever dry-run. The tests do not merely check that text appeared — they
compile and EXECUTE the edited modules and pin the properties:

* the term lands inside the right glossary set and ``all_terms()``;
* a generated assertion probe is DERIVED and NOT evidence (cannot score);
* every generated stub RAISES — the fake-green rule, structurally.
"""

from __future__ import annotations

import ast
import json
import shutil
from pathlib import Path

import pytest

import ctkr.oracle as oracle_pkg
from ctkr.cli import main
from ctkr.oracle.glossary_provenance import load_registry
from ctkr.term_codegen import CodegenError, apply_edits, plan_edits, render_diffs

_ORACLE_FILES = ("glossary.py", "probes.py", "steps.py", "adapter.py",
                 "farmos_adapter.py")


def make_spec(term: str, kind: str) -> dict:
    return {
        "term": term,
        "kind": kind,
        "description": f"A generated {kind} for the codegen tests.",
        "probe_semantics": f"Deliver the {term} the boundary reports for the "
                           "subject as a domain value.",
        "discriminating_flow": {"given": ["an equipment"], "when": [],
                                "then": [f"{term} == 1"]},
        "provenance": {"role_class_id": None, "config_source": "widget.yml",
                       "punts": [], "first_pack_seal": None},
    }


@pytest.fixture
def tree(tmp_path: Path) -> Path:
    """A throwaway target tree copied from this installation's own oracle."""
    src = Path(oracle_pkg.__file__).parent
    dst = tmp_path / "tree"
    (dst / "ctkr" / "oracle").mkdir(parents=True)
    (dst / "tests").mkdir()
    for name in _ORACLE_FILES:
        shutil.copy(src / name, dst / "ctkr" / "oracle" / name)
    (dst / "ctkr" / "oracle" / "glossary_provenance.jsonl").touch()
    return dst


def _exec_module(tree: Path, rel: str) -> dict:
    """Compile AND execute an edited module — text that does not run is not
    plumbing."""
    import sys
    import types
    import uuid

    src = (tree / rel).read_text(encoding="utf-8")
    name = f"generated_{Path(rel).stem}_{uuid.uuid4().hex[:8]}"
    mod = types.ModuleType(name)
    mod.__file__ = str(tree / rel)
    sys.modules[name] = mod  # dataclasses resolves annotations via sys.modules
    try:
        exec(compile(src, str(tree / rel), "exec"), mod.__dict__)  # noqa: S102
    finally:
        sys.modules.pop(name, None)
    return mod.__dict__


def _bare(abc_cls):
    """An instance of an ABC with its abstract gate lifted — the stub under
    test is a default method, not an abstract one."""
    sub = type("_Bare", (abc_cls,), {})
    sub.__abstractmethods__ = frozenset()
    return sub()


def _spec_file(tmp_path: Path, spec: dict) -> Path:
    p = tmp_path / f"{spec['term']}.spec.json"
    p.write_text(json.dumps(spec), encoding="utf-8")
    return p


# --------------------------------------------------------------------------- #
# dry-run                                                                      #
# --------------------------------------------------------------------------- #
def test_dry_run_prints_the_full_diff_and_writes_nothing(
    tree, tmp_path, capsys,
) -> None:
    before = {n: (tree / "ctkr" / "oracle" / n).read_bytes() for n in _ORACLE_FILES}
    spec = make_spec("widget_count", "assertion")
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--dry-run", "--root", str(tree)])
    assert rc == 0
    out = capsys.readouterr().out
    assert '+        "widget_count"' in out
    assert "+    ProbeSpec('widget_count'" in out
    for n in _ORACLE_FILES:  # nothing moved
        assert (tree / "ctkr" / "oracle" / n).read_bytes() == before[n]
    assert not (tree / "tests" / "test_term_widget_count.py").exists()
    assert load_registry(tree / "ctkr" / "oracle" / "glossary_provenance.jsonl") == []


def test_dry_run_is_the_default_mode(tree, tmp_path) -> None:
    spec = make_spec("widget_count", "assertion")
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--root", str(tree)])
    assert rc == 0
    assert '"widget_count"' not in (tree / "ctkr" / "oracle" / "glossary.py").read_text()


# --------------------------------------------------------------------------- #
# --apply: assertion term                                                      #
# --------------------------------------------------------------------------- #
def test_apply_assertion_term_generates_working_plumbing(tree, tmp_path) -> None:
    spec = make_spec("widget_count", "assertion")
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--apply", "--root", str(tree)])
    assert rc == 0

    # Glossary: the term is in the right set and in all_terms().
    g = _exec_module(tree, "ctkr/oracle/glossary.py")
    assert "widget_count" in g["ASSERTION_TERMS"]
    assert "widget_count" in g["all_terms"]()

    # Probe contract: bound, DERIVED, and NOT evidence — it cannot score until
    # someone validates the derivation AND bind-term flips the provenance row.
    p = _exec_module(tree, "ctkr/oracle/probes.py")
    spec_row = p["PROBE_CONTRACT"]["widget_count"]
    assert spec_row.method == "widget_count"
    assert spec_row.authority == p["DERIVED"]
    assert not spec_row.is_evidence
    assert "widget_count" in p["unvalidated_probes"]()

    # ABC stub: raises AdapterError, never answers (fake-green rule).
    a = _exec_module(tree, "ctkr/oracle/adapter.py")
    with pytest.raises(a["AdapterError"], match="widget_count"):
        _bare(a["ImplementationAdapter"]).widget_count("H1")

    # farmOS stub: inside the class, raises NotImplementedError, carries the
    # probe semantics so the implementer knows what to build.
    f = _exec_module(tree, "ctkr/oracle/farmos_adapter.py")
    farm = f["FarmOSAdapter"]
    with pytest.raises(NotImplementedError, match="PROVISIONAL"):
        farm.__dict__["widget_count"](farm.__new__(farm), "H1")

    # Test skeleton exists and parses.
    skel = tree / "tests" / "test_term_widget_count.py"
    ast.parse(skel.read_text(encoding="utf-8"))

    # Provenance row: PROVISIONAL, seal empty.
    rows = load_registry(tree / "ctkr" / "oracle" / "glossary_provenance.jsonl")
    assert [r["term"] for r in rows] == ["widget_count"]
    assert rows[0]["status"] == "provisional"
    assert rows[0]["provenance"]["first_pack_seal"] is None


def test_apply_action_term_generates_the_interpreter_arm(tree, tmp_path) -> None:
    spec = make_spec("record_widget", "action")
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--apply", "--root", str(tree)])
    assert rc == 0

    g = _exec_module(tree, "ctkr/oracle/glossary.py")
    assert "record_widget" in g["ACTION_TERMS"]

    p = _exec_module(tree, "ctkr/oracle/probes.py")
    assert p["OPERATION_CONTRACT"]["record_widget"].methods == ("record_widget",)

    # The interpreter arm dispatches to the adapter — executed, not grepped.
    s = _exec_module(tree, "ctkr/oracle/steps.py")
    from ctkr.oracle.fixtures import WhenStep

    calls: list[str] = []

    class _Fake:
        def record_widget(self, handle: str) -> None:
            calls.append(handle)

    s["apply_when"](_Fake(), WhenStep(action="record_widget", ref="bin"),
                    {"bin": "H9"})
    assert calls == ["H9"]

    # And the ABC default still RAISES, so the arm cannot fake a flow.
    a = _exec_module(tree, "ctkr/oracle/adapter.py")
    with pytest.raises(a["AdapterError"]):
        _bare(a["ImplementationAdapter"]).record_widget("H1")


def test_apply_entity_term_touches_only_glossary_and_tests(tree, tmp_path) -> None:
    probes_before = (tree / "ctkr" / "oracle" / "probes.py").read_bytes()
    spec = make_spec("widget", "entity")
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--apply", "--root", str(tree)])
    assert rc == 0
    g = _exec_module(tree, "ctkr/oracle/glossary.py")
    assert "widget" in g["ENTITY_TERMS"]
    assert (tree / "ctkr" / "oracle" / "probes.py").read_bytes() == probes_before
    assert (tree / "tests" / "test_term_widget.py").exists()


# --------------------------------------------------------------------------- #
# Refusals                                                                     #
# --------------------------------------------------------------------------- #
def test_an_existing_glossary_term_is_refused(tree, tmp_path) -> None:
    spec = make_spec("stock_on_hand", "assertion")
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--apply", "--root", str(tree)])
    assert rc == 2
    assert load_registry(tree / "ctkr" / "oracle" / "glossary_provenance.jsonl") == []


def test_a_registered_term_is_refused_before_any_edit(tree, tmp_path) -> None:
    spec = make_spec("widget_count", "assertion")
    sf = _spec_file(tmp_path, spec)
    assert main(["add-term", "--spec", str(sf), "--apply", "--root", str(tree)]) == 0
    glossary_after = (tree / "ctkr" / "oracle" / "glossary.py").read_bytes()
    assert main(["add-term", "--spec", str(sf), "--apply", "--root", str(tree)]) == 2
    assert (tree / "ctkr" / "oracle" / "glossary.py").read_bytes() == glossary_after


def test_a_broken_spec_is_refused(tree, tmp_path) -> None:
    spec = make_spec("widget_count", "assertion")
    spec["kind"] = "adjective"
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--root", str(tree)])
    assert rc == 2


def test_a_drifted_tree_fails_loudly_never_guesses(tree) -> None:
    """Anchor discipline: a tree the generator does not recognise is an error,
    not a best-effort insertion."""
    (tree / "ctkr" / "oracle" / "probes.py").write_text(
        "# gutted\n", encoding="utf-8"
    )
    with pytest.raises(CodegenError, match="anchor|drifted"):
        plan_edits(make_spec("widget_count", "assertion"), tree)


def test_apply_refuses_if_the_tree_moved_after_planning(tree) -> None:
    edits = plan_edits(make_spec("widget_count", "assertion"), tree)
    gpath = tree / "ctkr" / "oracle" / "glossary.py"
    gpath.write_text(gpath.read_text(encoding="utf-8") + "\n# drift\n",
                     encoding="utf-8")
    with pytest.raises(CodegenError, match="re-plan"):
        apply_edits(edits, tree)


def test_render_diffs_names_every_file(tree) -> None:
    edits = plan_edits(make_spec("widget_count", "assertion"), tree)
    diff = render_diffs(edits)
    for rel in ("ctkr/oracle/glossary.py", "ctkr/oracle/probes.py",
                "ctkr/oracle/adapter.py", "ctkr/oracle/farmos_adapter.py",
                "tests/test_term_widget_count.py"):
        assert f"b/{rel}" in diff
