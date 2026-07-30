"""The fitness test for the dependency arrow (MetaCoding-1gt).

`lens.py` claims "**ctkr never imports a lens module.**" Until this file existed
that claim was a docstring — and this project's own record is that a comment
asserting a semantic the code does not enforce is how the semantic gets lost. The
inversion is only worth what its regression evidence is worth, so the rule is
checked here by reading the source, not by trusting review.

A lens module is target-specific material: the closed sets, the probe tables, the
live client, the target-shaped harvesters. Generic machinery may name them in
prose; it may not IMPORT them.
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest

CTKR = Path(__file__).resolve().parents[1] / "ctkr"

#: Modules that ARE the farmOS lens. They may import each other freely.
LENS_MODULES: frozenset[str] = frozenset({
    "ctkr.oracle.glossary",
    "ctkr.oracle.probes",
    "ctkr.oracle.farmos_adapter",
    "ctkr.oracle.farmos_lens",
    "ctkr.drupal",
    "ctkr.farmos_diff",
    "ctkr.commands.drupal_harvest",
})

#: KNOWN BREACH, tracked not tolerated (MetaCoding-1gt slice 3b). `lexicon.py`
#: imports Drupal YAML helpers (_CONFIG_NAME, _rel, _safe_yaml) because the
#: lexicon scan reads Drupal declarative config directly. Fixing it means giving
#: the Lens a config-harvester interface — real design work, not a rename — so it
#: is listed HERE, visibly, rather than quietly widening the rule. Every entry in
#: this dict must name the bead that removes it.
KNOWN_BREACHES: dict[str, str] = {
    "ctkr.lexicon": "MetaCoding-1gt.2 — needs Lens.config_harvester; see docs/design/instrument-lens-source.md",
}

#: Files allowed to import a lens module: the lens itself, plus the two places
#: whose job is to REACH one. `lens.py` names its builtins as strings and imports
#: them lazily, so it is not an exception — it is checked like anything else.
ALLOWED_IMPORTERS: frozenset[str] = frozenset({
    *LENS_MODULES,
    # add-term's codegen writes INTO the lens's files; it resolves them through
    # Lens.codegen_targets, and its own tests exercise the farmOS lens directly.
    "ctkr.term_codegen",
})


def _module_name(path: Path) -> str:
    rel = path.relative_to(CTKR.parent).with_suffix("")
    return ".".join(rel.parts)


def _imported_modules(path: Path) -> set[str]:
    """Every module named by an import statement, including inside functions."""
    tree = ast.parse(path.read_text(), filename=str(path))
    found: set[str] = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            found.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom):
            if node.level:  # relative import — not how this package refers to lenses
                continue
            if node.module is None:
                continue
            found.add(node.module)
            # `from ctkr.oracle import glossary` names the module in the alias
            found.update(f"{node.module}.{a.name}" for a in node.names)
    return found


def _python_files() -> list[Path]:
    return sorted(p for p in CTKR.rglob("*.py") if "__pycache__" not in p.parts)


def test_the_boundary_is_not_vacuous() -> None:
    """The rule must be able to fail: the lens modules it names must exist.

    A fitness test whose target set has been renamed away passes forever while
    guarding nothing.
    """
    names = {_module_name(p) for p in _python_files()}
    missing = sorted(LENS_MODULES - names)
    assert not missing, (
        f"these are declared lens modules but no longer exist: {missing}. "
        f"Update LENS_MODULES — a boundary test that names nothing enforces nothing."
    )


@pytest.mark.parametrize("path", _python_files(), ids=_module_name)
def test_generic_ctkr_never_imports_a_lens(path: Path) -> None:
    """No generic module may import target-specific material."""
    me = _module_name(path)
    if me in ALLOWED_IMPORTERS:
        pytest.skip("this module is (or reaches) the lens by design")
    if me in KNOWN_BREACHES:
        pytest.xfail(f"known breach: {KNOWN_BREACHES[me]}")

    offenders = sorted(_imported_modules(path) & LENS_MODULES)
    assert not offenders, (
        f"{me} imports the lens module(s) {offenders}.\n"
        f"The arrow points lens -> instrument, never the reverse: a lens supplies "
        f"its vocabulary, probe contract and adapter as DATA, and generic code "
        f"reaches them through ctkr.oracle.lens (active_vocabulary(), "
        f"active_probe_contract(), Lens.build_adapter).\n"
        f"If it truly belongs to the target, move it into the lens; if it is "
        f"instrument, it must not name a target."
    )
