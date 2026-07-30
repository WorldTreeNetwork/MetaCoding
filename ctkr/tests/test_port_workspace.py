"""The port workspace is DISCOVERED, and only its root is.

The workspace — ``port_runs/`` + ``results/``: packs, seals, PACKS.jsonl, the
bound CM-decision registry, builds — is the TARGET's ledger, not the
instrument's, and is being extracted into its own repo (MetaCoding-1gt).

These tests replaced a set that pinned a ``METACODING_PORT_WORKSPACE``
environment variable. The variable is gone: it was the eighth path-ish knob in a
system whose actual problem was that a port had no identity, so a port now
declares itself with a ``port.toml`` and the instrument walks up from the working
directory to find it — the way ``git`` finds ``.git``.

What is pinned here:

1. With no manifest anywhere above cwd, resolution falls back to today's in-repo
   layout, the resolved registry actually EXISTS (MetaCoding still holds the
   authoritative copy), and the workspace reports itself ``implicit`` — assumed,
   not declared.
2. A manifest wins, whether it sits in cwd or any parent.
3. The manifest moves the ROOT and nothing else. The registry's location *within*
   the workspace stays fixed and no manifest key can move it, because a port
   author who can move the registry is back to citing sanctions from a file they
   just wrote — the self-certification INVARIANT 2 exists to refuse.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from ctkr.oracle.port_contract import (
    DECISION_REGISTRY_RELPATHS,
    DEFAULT_PORT_WORKSPACE,
    decision_sources,
    port_workspace,
)
from ctkr.workspace import MANIFEST_NAME, WorkspaceError, discover, find_manifest

REPO_ROOT = Path(__file__).resolve().parents[2]


def _manifest(root: Path, **sections: str) -> Path:
    """Write a minimal port.toml at ``root`` and return its path."""
    root.mkdir(parents=True, exist_ok=True)
    body = ["[port]", 'name = "testport"']
    for section, entries in sections.items():
        body.append(f"[{section}]")
        body.append(entries)
    path = root / MANIFEST_NAME
    path.write_text("\n".join(body) + "\n")
    return path


# --------------------------------------------------------------------------- #
# 1. the fallback, while the ledger still lives in this repo                    #
# --------------------------------------------------------------------------- #
def test_with_no_manifest_the_in_repo_workspace_is_used_and_resolves(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)  # nothing above tmp_path carries a port.toml
    assert find_manifest(tmp_path) is None
    assert port_workspace(REPO_ROOT) == REPO_ROOT / DEFAULT_PORT_WORKSPACE

    sources = decision_sources(REPO_ROOT)
    assert sources, "the fallback must name at least one registry"
    assert [p for p in sources if p.exists()], (
        f"fallback registry missing: {[str(p) for p in sources]}"
    )


def test_an_assumed_workspace_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`implicit` is the difference between declared and guessed."""
    monkeypatch.chdir(tmp_path)
    assumed = discover(fallback=REPO_ROOT / DEFAULT_PORT_WORKSPACE)
    assert assumed.implicit is True

    declared = discover(start=_manifest(tmp_path / "ws").parent)
    assert declared.implicit is False


def test_no_manifest_and_no_fallback_is_an_error_that_says_what_to_do(
    tmp_path: Path,
) -> None:
    with pytest.raises(WorkspaceError) as exc:
        discover(start=tmp_path)
    assert MANIFEST_NAME in str(exc.value)


# --------------------------------------------------------------------------- #
# 2. a declared manifest wins, and is found by walking up                      #
# --------------------------------------------------------------------------- #
def test_a_manifest_in_cwd_wins(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = tmp_path / "farmos-port"
    _manifest(ws)
    monkeypatch.chdir(ws)
    assert port_workspace(REPO_ROOT) == ws
    assert decision_sources(REPO_ROOT) == tuple(
        ws / rel for rel in DECISION_REGISTRY_RELPATHS
    )


def test_a_manifest_in_a_parent_is_found_from_a_subdirectory(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = tmp_path / "farmos-port"
    _manifest(ws)
    deep = ws / "port_runs" / "wave2" / "spine-asset"
    deep.mkdir(parents=True)
    monkeypatch.chdir(deep)
    assert port_workspace(REPO_ROOT) == ws


def test_the_manifest_carries_the_source_pin(tmp_path: Path) -> None:
    """A pin is not optional: a floating tag silently re-based 43 packs."""
    src = tmp_path / "src"
    src.mkdir()
    _manifest(
        tmp_path / "ws",
        source=f'path = "{src}"\npin = "3fe0ce7e23de807be9b8bc97a211ce934327db39"',
    )
    ws = discover(start=tmp_path / "ws")
    assert ws.source.pin == "3fe0ce7e23de807be9b8bc97a211ce934327db39"
    assert ws.source.path == src


# --------------------------------------------------------------------------- #
# 3. only the ROOT moves                                                       #
# --------------------------------------------------------------------------- #
def test_the_registry_path_inside_the_workspace_is_not_configurable(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    ws = tmp_path / "ws"
    # A manifest that TRIES to relocate the registry must be ignored.
    _manifest(ws, ledger='decisions = "somewhere/else/i-wrote-this.jsonl"')
    monkeypatch.chdir(ws)
    assert DECISION_REGISTRY_RELPATHS == (
        "port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
    )
    assert all(
        p.relative_to(ws).as_posix() in DECISION_REGISTRY_RELPATHS
        for p in decision_sources(REPO_ROOT)
    )


def test_port_verify_reads_the_discovered_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """The verifier's decision resolver follows the workspace, end to end."""
    from ctkr.oracle.port_contract import load_decisions

    ws = tmp_path / "ws"
    _manifest(ws)
    registry = ws / DECISION_REGISTRY_RELPATHS[0]
    registry.parent.mkdir(parents=True)
    registry.write_text(
        '{"id": "CM-TEST-1", "text": "a relocated but bound decision"}\n'
    )
    monkeypatch.chdir(ws)

    decisions = load_decisions(decision_sources(REPO_ROOT))
    assert "CM-TEST-1" in decisions


def test_term_incidence_default_roots_follow_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ctkr.commands.term_incidence import default_roots

    monkeypatch.chdir(tmp_path)
    assert default_roots() == (
        REPO_ROOT / DEFAULT_PORT_WORKSPACE / "port_runs" / "wave1",
        REPO_ROOT / DEFAULT_PORT_WORKSPACE / "port_runs" / "wave0-pilot",
    )

    ws = tmp_path / "ws"
    _manifest(ws)
    monkeypatch.chdir(ws)
    assert default_roots() == (
        ws / "port_runs" / "wave1",
        ws / "port_runs" / "wave0-pilot",
    )


def test_propose_adapter_discovery_follows_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from ctkr.commands.propose_adapter import discover_cm_registry

    ws = tmp_path / "ws"
    _manifest(ws)
    registry = ws / DECISION_REGISTRY_RELPATHS[0]
    registry.parent.mkdir(parents=True)
    registry.write_text('{"id": "CM-TEST-2", "text": "bound elsewhere"}\n')

    # `start` is an unrelated tree with its own .git: only the discovered
    # workspace can find this registry.
    start = tmp_path / "elsewhere"
    start.mkdir()
    (start / ".git").mkdir()
    monkeypatch.chdir(ws)
    assert discover_cm_registry(start=start) == registry
