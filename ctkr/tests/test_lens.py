"""The lens abstraction and its registry (MetaCoding-1gt).

The property under test: the instrument's target-specific material — vocabulary,
probe contract, adapter, provenance ledger, codegen targets — is DATA supplied
by a registered lens, discoverable without editing ctkr's source.
"""

from __future__ import annotations

import types

import pytest

from ctkr.oracle import lens as lens_mod
from ctkr.oracle.lens import (
    CODEGEN_TARGETS,
    ENTRY_POINT_GROUP,
    Lens,
    LensError,
    Vocabulary,
    active_lens,
    active_probe_contract,
    active_vocabulary,
    get_lens,
    lens_names,
    use_lens,
)


def _tiny_vocabulary(**over: object) -> Vocabulary:
    base: dict[str, object] = {name: frozenset() for name in lens_mod.VOCABULARY_SETS}
    base["COMPARISON_OPS"] = frozenset({"=="})
    base["FORBIDDEN_SUBSTRINGS"] = ()
    base["FORBIDDEN_WORDS"] = frozenset()
    base.update(over)
    return Vocabulary(**base)  # type: ignore[arg-type]


def _tiny_lens(name: str = "tiny", **over: object) -> Lens:
    kwargs: dict[str, object] = {
        "name": name,
        "vocabulary": _tiny_vocabulary(),
        "probe_contract": {},
    }
    kwargs.update(over)
    return Lens(**kwargs)  # type: ignore[arg-type]


# --------------------------------------------------------------------------- #
# Vocabulary                                                                  #
# --------------------------------------------------------------------------- #
def test_vocabulary_all_terms_is_the_union_of_the_term_sets() -> None:
    v = _tiny_vocabulary(
        ENTITY_TERMS=frozenset({"widget"}),
        ACTION_TERMS=frozenset({"poke"}),
        ASSERTION_TERMS=frozenset({"pokes"}),
    )
    assert v.all_terms() == {"widget", "poke", "pokes"}
    # COMPARISON_OPS is vocabulary but not a TERM — same as glossary.all_terms().
    assert "==" not in v.all_terms()


def test_vocabulary_from_module_carries_every_closed_set() -> None:
    mod = types.SimpleNamespace(
        **{name: frozenset({name.lower()}) for name in lens_mod.VOCABULARY_SETS},
        COMPARISON_OPS=frozenset({"=="}),
        FORBIDDEN_WORDS=frozenset({"table"}),
        FORBIDDEN_SUBSTRINGS=["uuid"],
    )
    v = Vocabulary.from_module(mod)
    for name in lens_mod.VOCABULARY_SETS:
        assert getattr(v, name) == {name.lower()}
    assert v.FORBIDDEN_SUBSTRINGS == ("uuid",)
    assert v.FORBIDDEN_WORDS == {"table"}


def test_vocabulary_from_module_refuses_a_module_missing_a_set() -> None:
    mod = types.SimpleNamespace(ENTITY_TERMS=frozenset())
    with pytest.raises(AttributeError):
        Vocabulary.from_module(mod)


def test_enum_provenance_getattr_still_works_on_a_vocabulary() -> None:
    # glossary_provenance resolves set names dynamically; a Vocabulary must
    # answer getattr(vocab, "LOG_STATUSES") the way the module did.
    v = _tiny_vocabulary(LOG_STATUSES=frozenset({"done"}))
    assert getattr(v, "LOG_STATUSES") == {"done"}
    assert getattr(v, "NOT_A_SET", None) is None


# --------------------------------------------------------------------------- #
# The lens object                                                             #
# --------------------------------------------------------------------------- #
def test_a_lens_declaring_partial_codegen_targets_is_refused() -> None:
    with pytest.raises(LensError, match="omits"):
        _tiny_lens(codegen_targets={"glossary": "g.py"})


def test_codegen_target_lookup_names_the_known_targets_on_a_miss() -> None:
    targets = {name: f"{name}.py" for name in CODEGEN_TARGETS}
    lens = _tiny_lens(codegen_targets=targets)
    assert lens.codegen_target("probes") == "probes.py"
    with pytest.raises(LensError, match="no codegen target"):
        lens.codegen_target("nope")


# --------------------------------------------------------------------------- #
# The registry                                                                #
# --------------------------------------------------------------------------- #
def test_farmos_is_registered_and_carries_the_farmos_material() -> None:
    assert "farmos" in lens_names()
    lens = get_lens("farmos")
    assert lens.name == "farmos"
    # The vocabulary is the farmOS one, carried rather than imported.
    assert "animal" in lens.vocabulary.ENTITY_TERMS
    assert "yield_total" in lens.vocabulary.ASSERTION_TERMS
    assert "==" in lens.vocabulary.COMPARISON_OPS
    # The probe contract dispatches assertions to adapter methods.
    assert "yield_total" in lens.probe_contract
    assert "record_log" in lens.operation_contract
    # Its ledger and its codegen targets are its own.
    assert lens.provenance_path is not None
    assert lens.provenance_path.name == "glossary_provenance.jsonl"
    assert lens.provenance_path.exists()
    assert set(lens.codegen_targets) == set(CODEGEN_TARGETS)
    assert lens.codegen_target("adapter_impl") == "ctkr/oracle/farmos_adapter.py"


def test_the_farmos_lens_vocabulary_equals_the_glossary_module() -> None:
    # Belt and braces on the inversion: carrying is not changing.
    from ctkr.oracle import glossary

    v = get_lens("farmos").vocabulary
    for name in lens_mod.VOCABULARY_SETS:
        assert getattr(v, name) == getattr(glossary, name), name
    assert v.all_terms() == glossary.all_terms()
    assert v.FORBIDDEN_SUBSTRINGS == glossary.FORBIDDEN_SUBSTRINGS
    assert v.FORBIDDEN_WORDS == glossary.FORBIDDEN_WORDS


def test_an_unknown_lens_name_is_refused_and_names_the_entry_point_group() -> None:
    with pytest.raises(LensError) as exc:
        get_lens("no-such-lens")
    assert ENTRY_POINT_GROUP in str(exc.value)


def test_an_out_of_repo_lens_registers_through_an_entry_point(monkeypatch) -> None:
    """The property that makes an Nth port cost ZERO instrument edits."""
    outsider = _tiny_lens("outsider")

    class _EP:
        name = "outsider"

        @staticmethod
        def load() -> Lens:
            return outsider

    monkeypatch.setattr(lens_mod, "_entry_point_loaders",
                        lambda: {"outsider": _EP.load})
    lens_mod.clear_lens_cache()
    try:
        assert "outsider" in lens_names()
        assert get_lens("outsider") is outsider
    finally:
        lens_mod.clear_lens_cache()


def test_an_entry_point_may_expose_a_factory_rather_than_a_lens(monkeypatch) -> None:
    built = _tiny_lens("lazy")
    monkeypatch.setattr(lens_mod, "_entry_point_loaders",
                        lambda: {"lazy": lambda: (lambda: built)})
    lens_mod.clear_lens_cache()
    try:
        assert get_lens("lazy") is built
    finally:
        lens_mod.clear_lens_cache()


def test_an_entry_point_resolving_to_a_non_lens_is_refused(monkeypatch) -> None:
    monkeypatch.setattr(lens_mod, "_entry_point_loaders",
                        lambda: {"bogus": lambda: object()})
    lens_mod.clear_lens_cache()
    try:
        with pytest.raises(LensError, match="not a Lens"):
            get_lens("bogus")
    finally:
        lens_mod.clear_lens_cache()


# --------------------------------------------------------------------------- #
# The active lens                                                             #
# --------------------------------------------------------------------------- #
def test_the_single_registered_lens_is_active_without_configuration() -> None:
    assert lens_names() == ("farmos",)
    assert active_lens().name == "farmos"
    assert active_vocabulary() is get_lens("farmos").vocabulary
    assert active_probe_contract() is get_lens("farmos").probe_contract


def test_use_lens_binds_explicitly_and_always_releases() -> None:
    other = _tiny_lens("other")
    with use_lens(other):
        assert active_lens() is other
    assert active_lens().name == "farmos"

    with pytest.raises(ValueError):
        with use_lens(other):
            raise ValueError("boom")
    assert active_lens().name == "farmos"


def test_ambiguity_is_refused_rather_than_guessed(monkeypatch) -> None:
    """Two lenses, none bound: the instrument must NOT pick one."""
    monkeypatch.setattr(lens_mod, "_entry_point_loaders",
                        lambda: {"outsider": lambda: _tiny_lens("outsider")})
    lens_mod.clear_lens_cache()
    try:
        assert set(lens_names()) == {"farmos", "outsider"}
        with pytest.raises(LensError, match="none is bound"):
            active_lens()
        # ... and binding one resolves it.
        with use_lens("outsider"):
            assert active_lens().name == "outsider"
    finally:
        lens_mod.clear_lens_cache()


def test_no_registered_lens_is_an_error_not_a_silent_default(monkeypatch) -> None:
    monkeypatch.setattr(lens_mod, "BUILTIN_LENSES", {})
    monkeypatch.setattr(lens_mod, "_entry_point_loaders", dict)
    lens_mod.clear_lens_cache()
    try:
        assert lens_names() == ()
        with pytest.raises(LensError, match="no lens is registered"):
            active_lens()
    finally:
        lens_mod.clear_lens_cache()


def test_resolution_reads_no_environment_variable(monkeypatch) -> None:
    """MetaCoding-1gt must REDUCE configuration surface, not add a knob."""
    src = (lens_mod.__file__)
    text = open(src, encoding="utf-8").read()
    assert "os.environ" not in text
    assert "getenv" not in text
