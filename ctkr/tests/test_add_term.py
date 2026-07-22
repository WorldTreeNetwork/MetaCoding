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
                 "farmos_adapter.py", "recorder.py", "fixtures.py")


def make_spec(term: str, kind: str, **extra) -> dict:
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
        **extra,
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

    # farmOS stub: INSIDE the class (both live runs had to hand-relocate a
    # module-scope insertion — MetaCoding-td9), raises NotImplementedError,
    # carries the probe semantics so the implementer knows what to build.
    f = _exec_module(tree, "ctkr/oracle/farmos_adapter.py")
    farm = f["FarmOSAdapter"]
    assert "widget_count" in farm.__dict__
    with pytest.raises(NotImplementedError, match="PROVISIONAL"):
        farm.__dict__["widget_count"](farm.__new__(farm), "H1")

    # Recorder seam: the _observe_probe dispatch arm exists and calls the
    # adapter — the gap the first live recording died on (MetaCoding-td9).
    r = _exec_module(tree, "ctkr/oracle/recorder.py")
    calls: list[tuple] = []

    class _FakeAdapter:
        def widget_count(self, subject):
            calls.append((subject,))
            return 3

    probe = r["Probe"](assert_="widget_count", subject="A")
    assert r["_observe_probe"](_FakeAdapter(), probe, {"A": "H1"}) == 3
    assert calls == [("H1",)]

    # Fixture validator: the required-fields row exists, so a flow author is
    # told which fields the assertion demands instead of discovering it live.
    x = _exec_module(tree, "ctkr/oracle/fixtures.py")
    assert x["_ASSERT_REQUIRED"]["widget_count"] == ("value",)

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
# Probe shape: spec-declared params + subject_kind (MetaCoding-td9)            #
# --------------------------------------------------------------------------- #
def _ref_spec(term: str = "has_gadget") -> dict:
    """An entity-reference assertion — the ``has_parent`` shape that previously
    required hand edits across five files."""
    return make_spec(
        term, "assertion",
        subject_kind="event",
        params=[{"field_name": "other", "alias_noun": "gadget"}],
    )


def test_apply_entity_reference_assertion_generates_the_full_shape(
    tree, tmp_path,
) -> None:
    spec = _ref_spec()
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--apply", "--root", str(tree)])
    assert rc == 0

    # ProbeSpec carries the param and the subject kind — no hand edit.
    p = _exec_module(tree, "ctkr/oracle/probes.py")
    row = p["PROBE_CONTRACT"]["has_gadget"]
    assert [(q.field_name, q.alias_noun) for q in row.params] == [("other", "gadget")]
    assert row.subject_kind == "event"

    # Both adapter stubs take the resolved handle and still RAISE.
    a = _exec_module(tree, "ctkr/oracle/adapter.py")
    with pytest.raises(a["AdapterError"], match="has_gadget"):
        _bare(a["ImplementationAdapter"]).has_gadget("H1", "H2")
    f = _exec_module(tree, "ctkr/oracle/farmos_adapter.py")
    assert "has_gadget" in f["FarmOSAdapter"].__dict__
    with pytest.raises(NotImplementedError, match="PROVISIONAL"):
        f["FarmOSAdapter"].__dict__["has_gadget"](
            f["FarmOSAdapter"].__new__(f["FarmOSAdapter"]), "H1", "H2")

    # Recorder arm resolves the alias through handles, like has_parent.
    r = _exec_module(tree, "ctkr/oracle/recorder.py")
    calls: list[tuple] = []

    class _FakeAdapter:
        def has_gadget(self, subject, other):
            calls.append((subject, other))
            return True

    probe = r["Probe"](assert_="has_gadget", subject="L", other="G")
    assert r["_observe_probe"](_FakeAdapter(), probe, {"L": "H1", "G": "H2"}) is True
    assert calls == [("H1", "H2")]

    # The validator demands exactly the fields the probe consumes.
    x = _exec_module(tree, "ctkr/oracle/fixtures.py")
    assert x["_ASSERT_REQUIRED"]["has_gadget"] == ("other", "value")

    # And the generated skeleton still parses (its stub call matches the arity).
    ast.parse((tree / "tests" / "test_term_has_gadget.py").read_text(encoding="utf-8"))


def test_generated_term_records_end_to_end_against_a_fake_transport(
    tree, tmp_path,
) -> None:
    """The bead's definition of done: a generated term must RECORD — given +
    probe through the edited recorder, with the observed value witnessed —
    without any hand-wiring."""
    spec = _ref_spec("holds_widget")
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--apply", "--root", str(tree)])
    assert rc == 0

    r = _exec_module(tree, "ctkr/oracle/recorder.py")

    class _FakeClient:
        observations: list = []

    class _FakeAdapter:
        client = _FakeClient()
        _n = 0

        def create_asset(self, entity, name, descriptor="", sex=""):
            _FakeAdapter._n += 1
            return f"asset--{entity}--{_FakeAdapter._n}"

        def holds_widget(self, subject, other):
            return True

    flow = r["FlowSpec"](
        key="holds-widget-e2e", title="Generated term records end to end",
        feature="codegen", glossary_terms=["holds_widget"],
        given=[r["GivenStep"](entity="land", alias="L", name="Field"),
               r["GivenStep"](entity="equipment", alias="G", name="Gadget")],
        when=[],
        probes=[r["Probe"](assert_="holds_widget", subject="L", other="G")],
    )
    fixture, observations = r["record_flow"](_FakeAdapter(), flow)
    (assertion,) = fixture.then
    assert assertion.assert_ == "holds_widget"
    assert assertion.value is True
    assert assertion.other == "G"
    # The value arrived with its witness, minted in the same breath.
    assert assertion.witness in {o.obs_id for o in observations}


def test_a_spec_with_params_on_a_non_assertion_is_refused(tree, tmp_path) -> None:
    spec = make_spec("record_gadget", "action",
                     params=[{"field_name": "other", "alias_noun": "gadget"}])
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--root", str(tree)])
    assert rc == 2


def test_a_spec_with_an_unknown_param_field_is_refused(tree, tmp_path) -> None:
    """ThenAssertion is a closed field set — a spec cannot invent a wire field."""
    spec = make_spec("has_gadget", "assertion",
                     params=[{"field_name": "gadget_ref"}])
    rc = main(["add-term", "--spec", str(_spec_file(tmp_path, spec)),
               "--root", str(tree)])
    assert rc == 2


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
                "ctkr/oracle/recorder.py", "ctkr/oracle/fixtures.py",
                "tests/test_term_widget_count.py"):
        assert f"b/{rel}" in diff
