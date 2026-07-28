"""The PORT WORKSPACE root is operator configuration, and only the root is.

The workspace — ``port_runs/`` + ``results/``: packs, seals, PACKS.jsonl, the
bound CM-decision registry, builds — is the TARGET's ledger, not the
instrument's, and is being extracted into its own repo (MetaCoding-1gt). These
tests pin the two halves of that move:

1. Unset ``METACODING_PORT_WORKSPACE`` resolves to today's in-repo layout, and
   the resolved registry actually EXISTS — MetaCoding still holds the
   authoritative copy, so a default that merely spells the path is not enough.
2. An override moves the ROOT and nothing else. The registry's location *within*
   the workspace stays fixed, because a port author who can move the registry
   inside it is back to citing sanctions from a file they just wrote — the
   self-certification INVARIANT 2 exists to refuse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ctkr.oracle.port_contract import (
    DECISION_REGISTRY_RELPATHS,
    DEFAULT_PORT_WORKSPACE,
    PORT_WORKSPACE_ENV,
    decision_sources,
    port_workspace,
)

REPO_ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture(autouse=True)
def _clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv(PORT_WORKSPACE_ENV, raising=False)


def test_default_is_the_in_repo_workspace_and_it_resolves() -> None:
    assert port_workspace(REPO_ROOT) == REPO_ROOT / DEFAULT_PORT_WORKSPACE
    sources = decision_sources(REPO_ROOT)
    assert sources, "the default must name at least one registry"
    assert [p for p in sources if p.exists()], (
        f"default registry missing: {[str(p) for p in sources]}"
    )


@pytest.mark.parametrize("blank", ["", "   "])
def test_a_blank_override_is_treated_as_unset(
    monkeypatch: pytest.MonkeyPatch, blank: str
) -> None:
    monkeypatch.setenv(PORT_WORKSPACE_ENV, blank)
    assert port_workspace(REPO_ROOT) == REPO_ROOT / DEFAULT_PORT_WORKSPACE


def test_an_absolute_override_is_honoured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.setenv(PORT_WORKSPACE_ENV, str(tmp_path))
    assert port_workspace(REPO_ROOT) == tmp_path
    assert decision_sources(REPO_ROOT) == tuple(
        tmp_path / rel for rel in DECISION_REGISTRY_RELPATHS
    )


def test_a_relative_override_resolves_against_the_repo_root(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv(PORT_WORKSPACE_ENV, "../farmos-port")
    assert port_workspace(REPO_ROOT) == REPO_ROOT / "../farmos-port"


def test_the_registry_path_inside_the_workspace_is_not_configurable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Moving the workspace must not let anyone move the registry within it."""
    monkeypatch.setenv(PORT_WORKSPACE_ENV, str(tmp_path))
    assert DECISION_REGISTRY_RELPATHS == (
        "port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
    )
    assert all(
        p.relative_to(tmp_path).as_posix() in DECISION_REGISTRY_RELPATHS
        for p in decision_sources(REPO_ROOT)
    )


def test_port_verify_reads_the_override(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The verifier's decision resolver follows the workspace, end to end."""
    from ctkr.oracle.port_contract import load_decisions

    registry = tmp_path / DECISION_REGISTRY_RELPATHS[0]
    registry.parent.mkdir(parents=True)
    registry.write_text(
        '{"id": "CM-TEST-1", "text": "a relocated but bound decision"}\n'
    )
    monkeypatch.setenv(PORT_WORKSPACE_ENV, str(tmp_path))

    decisions = load_decisions(decision_sources(REPO_ROOT))
    assert "CM-TEST-1" in decisions


def test_term_incidence_default_roots_follow_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ctkr.commands.term_incidence import default_roots

    assert default_roots() == (
        REPO_ROOT / DEFAULT_PORT_WORKSPACE / "port_runs" / "wave1",
        REPO_ROOT / DEFAULT_PORT_WORKSPACE / "port_runs" / "wave0-pilot",
    )
    monkeypatch.setenv(PORT_WORKSPACE_ENV, str(tmp_path))
    assert default_roots() == (
        tmp_path / "port_runs" / "wave1",
        tmp_path / "port_runs" / "wave0-pilot",
    )


def test_propose_adapter_discovery_follows_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ctkr.commands.propose_adapter import discover_cm_registry

    registry = tmp_path / DECISION_REGISTRY_RELPATHS[0]
    registry.parent.mkdir(parents=True)
    registry.write_text('{"id": "CM-TEST-2", "text": "bound elsewhere"}\n')
    monkeypatch.setenv(PORT_WORKSPACE_ENV, str(tmp_path))

    # Discovery starts from an unrelated tree: only the override can find this.
    start = tmp_path / "elsewhere"
    start.mkdir()
    (start / ".git").mkdir()
    assert discover_cm_registry(start=start) == registry
