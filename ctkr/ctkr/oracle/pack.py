"""The SEALED PACK — evidence with a chain of custody the defendant cannot hold.

INVARIANT 2: *the defendant never holds a pen that touches the verdict.*

A recorded fixture pack used to be three loose files in a directory, named on the
command line by whoever was being judged. That gave the port four pens it should
never have had:

* it chose **which pack** (``sed -n '4,7p'`` of a pack → "coverage 10/10 = 100%");
* it chose **which fixtures within it** (a subset file is still a valid file);
* it could **edit the expected values** (the forged ``3.0 → 999.0`` validated
  clean and was scored, because ``fixture_id`` — a blake3 content hash — was
  recomputed on write and never on read);
* it could **mark evidence corroboration-only** in its own manifest.

A pack is now a single sealed artifact. The recorder — which has no stake in any
score — writes ``pack.seal.json`` over the whole pack: the exact fixture id set,
the byte hash of both files, the source it was recorded from, and the id of every
DERIVATION the values were produced by (invariant 1). Loading a pack verifies all
of it. There is no partial load: you get the pack the recorder sealed, or you get
:class:`PackError` and no verdict at all.

**What this does and does not buy.** It makes every one of the four moves above a
*detected* tampering rather than an accepted input. It does not make a pack
unforgeable by someone with write access to both the pack and the seal — nothing
in a filesystem can. That last gap is closed socially, by :data:`REGISTRY_NAME`:
the seal of every pack is appended to a version-controlled registry, so re-sealing
an edited pack is a visible diff on a file the port author does not own, rather
than an invisible edit inside their own build directory.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from blake3 import blake3
from pydantic import BaseModel, ConfigDict, Field

from ctkr.oracle.fixtures import SemanticFixture, load_fixtures
from ctkr.oracle.probes import PROBE_CONTRACT, current_derivations

#: The sealed-pack sidecar, next to ``fixtures.jsonl``.
SEAL_NAME = "pack.seal.json"
#: The raw boundary observations the fixtures were distilled from.
OBSERVATIONS_NAME = "observations.jsonl"
#: Version-controlled ledger of every seal ever issued, at the repo's port_runs
#: root. Re-sealing an edited pack is a diff here, in a file the party being
#: judged does not own.
REGISTRY_NAME = "PACKS.jsonl"


class PackError(RuntimeError):
    """The pack is not the pack the recorder sealed. There is no verdict."""


def file_digest(path: str | Path) -> str:
    return blake3(Path(path).read_bytes()).hexdigest()[:32]


class PackSeal(BaseModel):
    """What the recorder attests about a pack, written before anyone is judged."""

    model_config = ConfigDict(extra="forbid")

    pack_id: str = ""
    recorded_at: str = ""
    source_system: str = ""
    source_version: str = ""
    #: The pack IS these fixtures — not a superset, not a subset.
    fixture_ids: list[str] = Field(default_factory=list)
    fixtures_blake3: str = ""
    observations_blake3: str = ""
    #: ``{assertion: derivation_id}`` in force when the values were observed.
    derivations: dict[str, str] = Field(default_factory=dict)
    seal: str = ""

    def _body(self) -> dict[str, Any]:
        return {
            "recorded_at": self.recorded_at,
            "source_system": self.source_system,
            "source_version": self.source_version,
            "fixture_ids": sorted(self.fixture_ids),
            "fixtures_blake3": self.fixtures_blake3,
            "observations_blake3": self.observations_blake3,
            "derivations": dict(sorted(self.derivations.items())),
        }

    def compute_seal(self) -> str:
        return blake3(
            json.dumps(self._body(), sort_keys=True).encode("utf-8")
        ).hexdigest()[:32]

    def sealed(self) -> PackSeal:
        s = self.compute_seal()
        return self.model_copy(update={"seal": s, "pack_id": s[:12]})


@dataclass(frozen=True)
class InvalidFixture:
    """A fixture that is present but is NOT evidence, and exactly why.

    Never dropped and never kept: it is carried into the verdict as its own
    bucket so a pack cannot shed a fixture by making it unreadable.
    """

    fixture_id: str
    title: str
    reason: str


@dataclass
class Pack:
    """A verified pack: the fixtures that stand, and the ones that do not."""

    path: Path
    seal: PackSeal
    fixtures: list[SemanticFixture] = field(default_factory=list)
    invalid: list[InvalidFixture] = field(default_factory=list)
    observation_ids: set[str] = field(default_factory=set)

    @property
    def all_fixture_ids(self) -> set[str]:
        return {f.fixture_id for f in self.fixtures} | {
            i.fixture_id for i in self.invalid
        }


# --------------------------------------------------------------------------- #
# Writing                                                                      #
# --------------------------------------------------------------------------- #
def seal_pack(
    fixtures_path: str | Path,
    *,
    source_system: str = "",
    source_version: str = "",
    recorded_at: str = "",
    register: bool = True,
) -> PackSeal:
    """Seal a written pack. Called by the RECORDER, which has no stake in a score."""
    fx_path = Path(fixtures_path)
    obs_path = fx_path.parent / OBSERVATIONS_NAME
    if not obs_path.exists():
        raise PackError(
            f"cannot seal {fx_path}: no {OBSERVATIONS_NAME} beside it. A pack "
            f"without its observations is a claim without a witness."
        )
    fixtures = load_fixtures(fx_path)
    seal = PackSeal(
        recorded_at=recorded_at or (fixtures[0].provenance.recorded_at if fixtures else ""),
        source_system=source_system or (fixtures[0].provenance.source_system if fixtures else ""),
        source_version=source_version or (fixtures[0].provenance.source_version if fixtures else ""),
        fixture_ids=[f.fixture_id for f in fixtures],
        fixtures_blake3=file_digest(fx_path),
        observations_blake3=file_digest(obs_path),
        derivations=current_derivations(),
    ).sealed()
    (fx_path.parent / SEAL_NAME).write_text(
        seal.model_dump_json(indent=2) + "\n", encoding="utf-8"
    )
    if register:
        register_seal(seal, registry_for(fx_path))
    return seal


def registry_for(fixtures_path: str | Path) -> Path | None:
    """The nearest ``PACKS.jsonl`` ledger above a pack, if the tree has one."""
    p = Path(fixtures_path).resolve()
    for parent in p.parents:
        candidate = parent / REGISTRY_NAME
        if candidate.exists():
            return candidate
        if (parent / ".git").exists():
            break
    return None


def register_seal(seal: PackSeal, registry: Path | None) -> None:
    if registry is None:
        return
    existing = {
        json.loads(line)["seal"]
        for line in registry.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }
    if seal.seal in existing:
        return
    with registry.open("a", encoding="utf-8") as fh:
        fh.write(json.dumps(seal.model_dump(), sort_keys=True) + "\n")


def registered_seals(registry: Path | None) -> set[str]:
    if registry is None or not registry.exists():
        return set()
    return {
        json.loads(line)["seal"]
        for line in registry.read_text(encoding="utf-8").splitlines()
        if line.strip()
    }


# --------------------------------------------------------------------------- #
# Reading                                                                      #
# --------------------------------------------------------------------------- #
def _fixture_problems(fx: SemanticFixture, observation_ids: set[str]) -> str:
    """Why this fixture is not evidence, or ``""``."""
    if fx.fixture_id and fx.fixture_id != fx.content_id():
        return (
            f"fixture_id {fx.fixture_id} does not hash its own body "
            f"({fx.content_id()}) — the scenario or an expected VALUE was edited "
            f"after recording"
        )
    missing = [r for r in fx.provenance.observation_refs if r not in observation_ids]
    if missing:
        return (
            f"{len(missing)} observation ref(s) do not resolve in this pack's "
            f"{OBSERVATIONS_NAME} (first: {missing[0]}) — the provenance names a "
            f"witness that is not here"
        )
    if not fx.provenance.observation_refs:
        return (
            "no observation refs — nothing recorded that this value was ever seen "
            "at a source boundary; a fixture with no witness is hand-authored"
        )
    # INVARIANT 1, enforced at load: a value produced by a derivation we have
    # since CORRECTED is stale, whatever it says about itself.
    current = current_derivations()
    for t in {a.assert_ for a in fx.then}:
        spec = PROBE_CONTRACT.get(t)
        if spec is None or not spec.derivation_id:
            continue
        # The FIXTURE's own stamp, not the seal's. A pack-level map would let a
        # pack recorded before the stamps existed be blessed wholesale by a seal
        # issued today — which is the silent-keep this exists to prevent.
        stamped = fx.provenance.derivations.get(t, "")
        if not stamped:
            return (
                f"asserts {t!r}, a DERIVED value, but the pack records no "
                f"derivation id for it — we cannot tell which of our own "
                f"computations produced this number"
            )
        if stamped != current[t]:
            return (
                f"asserts {t!r} under derivation {stamped}, which has since been "
                f"CORRECTED to {current[t]} ({spec.validated_against[:120]}). The "
                f"recorded value answers the old question. Re-record it."
            )
    return ""


def load_pack(fixtures_path: str | Path, *, require_seal: bool = True) -> Pack:
    """Load a pack, verifying the whole chain of custody. Never partial."""
    fx_path = Path(fixtures_path)
    seal_path = fx_path.parent / SEAL_NAME
    obs_path = fx_path.parent / OBSERVATIONS_NAME

    if not seal_path.exists():
        if require_seal:
            raise PackError(
                f"no {SEAL_NAME} beside {fx_path}. An unsealed pack states nothing "
                f"about its own completeness, so the party being judged chooses "
                f"its scope — which is not a thing a defendant may do. Seal it "
                f"with `ctkr oracle-seal {fx_path.parent}` (only meaningful if the "
                f"pack came from a recorder, not from an editor)."
            )
        seal = PackSeal()
    else:
        try:
            seal = PackSeal.model_validate_json(seal_path.read_text(encoding="utf-8"))
        except Exception as exc:  # noqa: BLE001
            raise PackError(f"{seal_path}: unreadable seal: {exc}") from exc
        if seal.seal != seal.compute_seal():
            raise PackError(
                f"{seal_path}: the seal does not hash its own contents "
                f"({seal.seal} vs {seal.compute_seal()}) — the seal itself was edited"
            )

    fixtures = load_fixtures(fx_path)

    if seal_path.exists():
        actual = file_digest(fx_path)
        if actual != seal.fixtures_blake3:
            raise PackError(
                f"{fx_path} does not match its seal ({actual} vs "
                f"{seal.fixtures_blake3}). The pack was changed after recording: "
                f"a subset, an addition, or an edited expected value. NO VERDICT."
            )
        if sorted(f.fixture_id for f in fixtures) != sorted(seal.fixture_ids):
            raise PackError(
                f"{fx_path} carries {len(fixtures)} fixtures; the seal names "
                f"{len(seal.fixture_ids)}. A pack is judged whole."
            )
        if not obs_path.exists():
            raise PackError(f"no {OBSERVATIONS_NAME} beside {fx_path}")
        obs_actual = file_digest(obs_path)
        if obs_actual != seal.observations_blake3:
            raise PackError(
                f"{obs_path} does not match its seal ({obs_actual} vs "
                f"{seal.observations_blake3}) — the witnesses were changed"
            )

    observation_ids: set[str] = set()
    if obs_path.exists():
        for line in obs_path.read_text(encoding="utf-8").splitlines():
            if line.strip():
                observation_ids.add(json.loads(line)["obs_id"])

    good: list[SemanticFixture] = []
    invalid: list[InvalidFixture] = []
    for fx in fixtures:
        problem = _fixture_problems(fx, observation_ids)
        if problem:
            invalid.append(InvalidFixture(fx.fixture_id, fx.title, problem))
        else:
            good.append(fx)

    return Pack(path=fx_path, seal=seal, fixtures=good, invalid=invalid,
                observation_ids=observation_ids)
