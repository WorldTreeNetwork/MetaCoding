"""The PORT WORKSPACE and its manifest — a port that knows its own paths.

Why this exists (MetaCoding-1gt, docs/design/instrument-lens-source.md)
----------------------------------------------------------------------

A port used to have no identity. There were four separately-addressed piles —
source, lens, ledger, build — so every artifact earned another flag: 44 commands
share 7 path-ish flags, and an eighth arrived as the ``METACODING_PORT_WORKSPACE``
environment variable. Adding a ninth would have been the same mistake with a
longer name.

So the port is named instead. A workspace root carries a ``port.toml``, and the
paths stop being arguments: they are facts the port already knows. Discovery
walks up from the working directory the way ``git`` finds ``.git``.

What the manifest is NOT
------------------------

It is not a general configuration file, and nothing should be added to it that a
command could discover for itself. Two rules keep it from decaying into the flag
pile it replaced:

* **The registry path within a workspace stays fixed.** Only the ROOT is
  discovered. ``--decisions <anything>`` once let a port author point the
  resolver at a registry they had just written — self-certification one level up
  — and :data:`ctkr.oracle.port_contract.DECISION_REGISTRY_RELPATHS` exists to
  refuse it. A manifest key for it would hand the pen straight back.
* **``[cache]`` is never load-bearing.** Anything under it must be
  reconstructible from ``[source]`` plus the ledger by one command. The graph
  export the wave-2 partition was built on lived in ``/tmp``, vanished, and
  nothing could tell — that is the failure this rule refuses to repeat.
"""

from __future__ import annotations

import tomllib
from dataclasses import dataclass, field
from pathlib import Path

#: The manifest filename, at the workspace root.
MANIFEST_NAME = "port.toml"


class WorkspaceError(RuntimeError):
    """No workspace could be discovered, or its manifest is unusable."""


@dataclass(frozen=True)
class Source:
    """The pristine codebase being ported. Read-only, always."""

    path: Path | None = None
    #: The commit the ledger's evidence was recorded against. A floating tag
    #: silently re-based 43 sealed packs for six days; a pin is not optional.
    pin: str = ""


@dataclass(frozen=True)
class Workspace:
    """One port, self-described."""

    root: Path
    name: str = ""
    source: Source = field(default_factory=Source)
    build: Path | None = None
    cache: Path | None = None
    #: True when this workspace was assumed rather than declared — no manifest
    #: was found and the in-repo default was used. Callers that care about
    #: provenance (anything that writes) should say so.
    implicit: bool = False

    @property
    def manifest_path(self) -> Path:
        return self.root / MANIFEST_NAME


def find_manifest(start: Path | None = None) -> Path | None:
    """Walk up from ``start`` (default: cwd) looking for a ``port.toml``."""
    here = (start or Path.cwd()).resolve()
    for candidate in (here, *here.parents):
        manifest = candidate / MANIFEST_NAME
        if manifest.is_file():
            return manifest
    return None


def load(manifest: Path) -> Workspace:
    """Read a workspace from its manifest."""
    try:
        data = tomllib.loads(manifest.read_text())
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise WorkspaceError(f"{manifest}: cannot read the port manifest — {exc}") from exc

    root = manifest.parent

    def _path(section: str, key: str) -> Path | None:
        raw = (data.get(section) or {}).get(key)
        if not raw:
            return None
        p = Path(str(raw)).expanduser()
        return p if p.is_absolute() else (root / p).resolve()

    port = data.get("port") or {}
    src = data.get("source") or {}
    return Workspace(
        root=root,
        name=str(port.get("name", "")),
        source=Source(path=_path("source", "path"), pin=str(src.get("pin", ""))),
        build=_path("build", "path"),
        cache=_path("cache", "path"),
    )


def discover(start: Path | None = None, *, fallback: Path | None = None) -> Workspace:
    """The workspace in effect.

    A discovered manifest wins. Otherwise ``fallback`` — the in-repo workspace,
    which exists while the farmOS ledger still lives inside this repo — is used
    and flagged :attr:`Workspace.implicit`. Otherwise it is an error that says
    what to do, because guessing a workspace is how a run writes its evidence
    somewhere nobody looks.
    """
    manifest = find_manifest(start)
    if manifest is not None:
        return load(manifest)
    if fallback is not None:
        return Workspace(root=fallback, implicit=True)
    raise WorkspaceError(
        f"no {MANIFEST_NAME} found in this directory or any parent, and no "
        f"in-repo workspace to fall back on. Run from inside a port workspace, "
        f"or create a {MANIFEST_NAME} at its root."
    )
