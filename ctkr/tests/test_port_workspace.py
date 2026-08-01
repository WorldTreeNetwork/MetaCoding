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

1. With no manifest anywhere above cwd, the SEARCH PATH finds the extracted
   workspace repo beside this one, the resolved registry actually EXISTS (a path
   that is merely spelled correctly is not enough), the source pin still travels,
   and the workspace reports itself ``implicit`` — the root was assumed from the
   search path rather than found from cwd.
2. A manifest wins, whether it sits in cwd or any parent.
3. The manifest moves the ROOT and nothing else. The registry's location *within*
   the workspace stays fixed and no manifest key can move it, because a port
   author who can move the registry is back to citing sanctions from a file they
   just wrote — the self-certification INVARIANT 2 exists to refuse.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from _workspace import requires_ledger  # the ledger is its own repo (MetaCoding-1gt)

from ctkr.oracle.port_contract import (
    DECISION_REGISTRY_RELPATHS,
    decision_sources,
    port_workspace,
)
from ctkr.workspace import (
    MANIFEST_NAME,
    WORKSPACE_SEARCH_PATH,
    WorkspaceError,
    default_workspace,
    discover,
    find_manifest,
)

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
# 1. the search path, now that the ledger is a sibling repo                     #
# --------------------------------------------------------------------------- #
def _sibling_workspace(tmp_path: Path, **sections: str) -> tuple[Path, Path]:
    """A fake instrument root with a workspace on its search path.

    The resolver's search path is relative to the root it is HANDED, so the
    mechanism can be exercised without depending on what happens to be cloned
    beside the developer's checkout. Before MetaCoding-1gt these tests read the
    real sibling and therefore FAILED (not skipped) on a clone without it —
    an environment assertion wearing a mechanism test's clothes.
    """
    root = tmp_path / "instrument"
    root.mkdir()
    ws = (root / WORKSPACE_SEARCH_PATH[0]).resolve()
    _manifest(ws, **sections)
    return root, ws


def test_with_no_manifest_the_search_path_finds_the_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """Run from anywhere, and the ledger is still found — by search, not by env."""
    monkeypatch.chdir(tmp_path)  # nothing above tmp_path carries a port.toml
    assert find_manifest(tmp_path) is None

    root, ws = _sibling_workspace(tmp_path)
    found = default_workspace(root)
    assert found == ws, (
        f"nothing found on the search path {list(WORKSPACE_SEARCH_PATH)} "
        f"relative to {root}"
    )
    assert port_workspace(root) == found

    sources = decision_sources(root)
    assert sources, "the resolved workspace must name at least one registry"
    assert all(str(p).startswith(str(ws)) for p in sources), (
        f"a resolved registry escaped the workspace: {[str(p) for p in sources]}"
    )


def test_a_searched_workspace_still_carries_its_manifest_metadata(
    tmp_path: Path,
) -> None:
    """Found by search, not by cwd — but the pin must still travel."""
    _, ws = _sibling_workspace(tmp_path, source='pin = "deadbeef"')
    found = default_workspace(ws.parent / "instrument")
    assert found == ws
    workspace = discover(start=Path(tmp_path.anchor), fallback=found)
    assert workspace.implicit is True, "the ROOT was assumed from the search path"
    assert workspace.source.pin == "deadbeef", (
        "a searched workspace must still deliver its source pin"
    )


@requires_ledger
def test_the_real_farmos_workspace_is_on_this_checkouts_search_path() -> None:
    """CORPUS (MetaCoding-1gt): the mechanism above is environment-free; THIS is
    the environment claim, and it is the one that may legitimately be absent."""
    found = default_workspace(REPO_ROOT)
    assert found is not None, (
        f"no workspace on the search path {list(WORKSPACE_SEARCH_PATH)} relative "
        f"to {REPO_ROOT} — clone github.com/WorldTreeNetwork/FarmOS2 beside it"
    )
    assert port_workspace(REPO_ROOT) == found
    assert [p for p in decision_sources(REPO_ROOT) if p.exists()], (
        "the real workspace names no registry that exists"
    )
    assert discover(start=Path(REPO_ROOT.anchor), fallback=found).source.pin


def test_an_assumed_workspace_says_so(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """`implicit` is the difference between declared and guessed."""
    monkeypatch.chdir(tmp_path)
    assumed = discover(fallback=tmp_path / "assumed")
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

    ws = tmp_path / "ws"
    _manifest(ws)
    monkeypatch.chdir(ws)
    assert default_roots() == (
        ws / "port_runs" / "wave1",
        ws / "port_runs" / "wave0-pilot",
    )


@requires_ledger
def test_term_incidence_falls_back_to_the_searched_workspace(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    """CORPUS: with no manifest above cwd, the roots come off the SEARCH PATH.

    Unlike the test above, this one cannot be handed a synthetic root —
    ``default_roots()`` takes no root argument and falls back to the real
    checkout's search path by construction, so what it resolves to is a fact
    about this machine rather than about the code.
    """
    from ctkr.commands.term_incidence import default_roots

    monkeypatch.chdir(tmp_path)  # nothing above tmp_path carries a port.toml
    searched = default_workspace(REPO_ROOT)
    assert searched is not None
    assert default_roots() == (
        searched / "port_runs" / "wave1",
        searched / "port_runs" / "wave0-pilot",
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
