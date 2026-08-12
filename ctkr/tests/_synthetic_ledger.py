"""A port workspace built from nothing, so the instrument's suite needs no ledger.

WHY THIS EXISTS (MetaCoding-1gt, step 5). The farmOS ledger moved to its own repo
(FarmOS2). Five test modules read REAL sealed packs out of it, so once MetaCoding
stops carrying a mirror copy, a clone of the instrument alone cannot run them.
Two bad answers were available: depend on a SIBLING CHECKOUT, so a fresh clone
cannot pass its own suite; or skip-guard everything, which turns real coverage
into a green tick measuring nothing.

This is the third answer. It builds a COMPLETE port workspace — port.toml,
``port_runs/PACKS.jsonl``, sealed packs with witnesses — through the same
:func:`~ctkr.oracle.pack.seal_recording` the recorder uses, in a tmp dir, from
code. Nothing is copied out of any ledger, so there is nothing to go stale, and
the workspace regenerates from source on every run (the u00 lesson: derived data
is never load-bearing).

WHAT IT DOES AND DOES NOT REPLACE — the distinction that makes this honest:

* **Mechanism** tests ask "given a pack shaped like this, does the code do X?"
  A synthetic pack answers that completely, and those tests now run everywhere.
* **Corpus** tests ask "does every pack in the REAL farmOS ledger satisfy X?" —
  that the wave0 packs really are retired, that the committed lexicon-bind packs
  still validate, that the sensor pack really witnesses ``structure_kind``. A
  synthetic fixture cannot answer those; substituting one would be exactly the
  self-certifying move this harness exists to prevent. They stay guarded by
  :data:`tests._workspace.requires_ledger` and run when FarmOS2 is beside us.

So a bare clone gets full MECHANISM coverage and an explicit, loud report of the
corpus checks it could not run — instead of a uniform green that hides which
kind of claim was actually tested.

THE FAKE-IT QUESTION, answered in :mod:`tests.test_synthetic_ledger`: a builder
that drifts from the real pack format would let every mechanism test pass against
a shape the recorder no longer writes. So the synthetic pack is required to load
through the real :func:`~ctkr.oracle.pack.load_pack`, with witnesses checked, and
its fixtures must carry the CURRENT derivation ids. If the pack format moves and
this builder does not, the suite fails here rather than quietly elsewhere.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

import pytest
from blake3 import blake3

from ctkr.oracle.fixtures import SemanticFixture, probe_descriptor
from ctkr.oracle.pack import retire_seal, seal_recording
from ctkr.oracle.probes import current_derivations


def preflight_report(
    *,
    base_url: str = "http://synthetic-oracle:8095",
    types: tuple[str, ...] = ("log--observation", "asset--plant"),
    checked: bool = True,
) -> dict:
    """A report shaped exactly like ``oracle_preflight.preflight()`` returns.

    Synthetic packs are recordings, so they are gated recordings: a helper that
    sealed without an attestation would make every mechanism test a test of the
    ungated path, and the one thing the suite must be able to distinguish would
    be the only thing it never exercised. ``checked=False`` is the contrast case
    — a drift check that did not run — and it must NOT seal.
    """
    return {
        "base_url": base_url,
        "types": {t: f"GET /api/{t.replace('--', '/')} -> "
                     f"200, JSON:API collection" for t in types},
        "module_drift": {
            "checked": checked, "unexplained": [], "declared_missing": [],
            "reason": "" if checked else "docker not available",
            "unknown_provider": [],
        },
        "advertised": sorted({*types, "user--user", "file--file"}),
    }


class _Row:
    """A recorded row the sealer can serialise, standing in for an Observation."""

    def __init__(self, row: dict) -> None:
        self._row = row

    def model_dump(self) -> dict:
        return self._row


def recorded_fixture(
    assertion: str,
    value,
    *,
    title: str = "",
    given: list[dict] | None = None,
    subject: str = "bin",
) -> SemanticFixture:
    """A fixture shaped exactly as the RECORDER writes them — witness and all.

    The witness id is derived from the fixture's own identity rather than a
    counter, so two calls with the same arguments produce the same pack and a
    pack's seal is stable across runs. That matters: a fixture whose id moved
    every run would make "the seal did not change" untestable.
    """
    then: dict = {"assert": assertion, "subject": subject, "op": "==", "value": value}
    if assertion == "stock_on_hand":
        then |= {"measure": "weight", "unit": "kilograms"}
    if assertion == "group_member":
        then |= {"group": "herd"}
    if given is None:
        given = [{"entity": "equipment", "alias": "bin", "name": "feed bin"}]
        if assertion == "group_member":
            given.append({"entity": "group", "alias": "herd", "name": "herd"})
    title = title or f"a recorded {assertion}"
    # The given set is part of the witness id: two fixtures that differ only in
    # their given (which is exactly what an enum witness-position test needs)
    # must not collide onto one witness.
    seed = f"w:{title}:{assertion}:{value}:{json.dumps(given, sort_keys=True)}"
    then["witness"] = blake3(seed.encode()).hexdigest()[:16]
    return SemanticFixture.model_validate(
        {
            "title": title,
            "feature": "core",
            "given": given,
            "when": [],
            "then": [then],
            "provenance": {
                "source_system": "synthetic",
                "source_version": "0",
                "flow": "t",
                "observation_refs": ["obs-1", then["witness"]],
                # The CURRENT derivation ids, deliberately not literals: a pack
                # recorded under superseded derivations must not keep validating.
                "derivations": current_derivations(),
            },
        }
    ).with_id()


def typed_entity_fixture(entity: str, descriptor: str) -> SemanticFixture:
    """A fixture that exercises a closed-set VALUE in its declared witness position.

    ``STRUCTURE_TYPES`` / ``LAND_TYPES`` bind only when a sealed pack contains a
    valid fixture whose ``given`` includes that entity carrying that descriptor
    (``glossary_provenance._enum_witness_positions``). The position is what makes
    the binding an observation rather than a substring match, so a synthetic
    witness has to occupy the real position — not merely mention the value.
    """
    return recorded_fixture(
        "log_count",
        1,
        title=f"a recorded {entity} of kind {descriptor}",
        given=[
            {
                "entity": entity,
                "alias": "E1",
                "name": f"a {descriptor}",
                "descriptor": descriptor,
            }
        ],
        subject="E1",
    )


def observation_rows(fixtures: list[SemanticFixture]) -> list[dict]:
    """The boundary record plus one WITNESS per assertion, as the recorder writes.

    Every assertion cites a witness and every witness is claimed — the two
    conditions ``load_pack`` enforces. Omitting either is what an orphaned or
    subsetted pack looks like, which is why the mechanism tests can build one.
    """
    rows: list[dict] = [
        {"obs_id": "obs-1", "method": "GET", "path": "/api", "record": "boundary"}
    ]
    for fx in fixtures:
        for t in fx.then:
            rows.append(
                {
                    "obs_id": t.witness,
                    "method": "OBSERVE",
                    "path": f"probe/{t.assert_}",
                    "record": "witness",
                    "probe": probe_descriptor(t),
                    "observed": t.value,
                }
            )
    return rows


@dataclass
class SyntheticLedger:
    """A port workspace on disk: a root that declares itself, and a ledger."""

    root: Path

    @property
    def port_runs(self) -> Path:
        return self.root / "port_runs"

    @property
    def ledger(self) -> Path:
        return self.port_runs / "PACKS.jsonl"

    def seal_pack(
        self,
        lane: str,
        fixtures: list[SemanticFixture] | None = None,
        *,
        register: bool = True,
        preflight: dict | None = None,
    ) -> tuple[Path, str]:
        """Record and seal one pack under ``port_runs/<lane>/observe``.

        Returns the pack's ``fixtures.jsonl`` and its seal, because callers
        need the seal to retire it and the path to load it.
        """
        if fixtures is None:
            fixtures = [recorded_fixture("log_count", 2, title=f"{lane} log count")]
        pack_dir = self.port_runs / lane / "observe"
        pack_dir.mkdir(parents=True, exist_ok=True)
        rows = observation_rows(fixtures)
        seal = seal_recording(
            fixtures,
            [_Row(r) for r in rows],
            pack_dir,
            source_system="synthetic",
            source_version="0",
            register=register,
            preflight=preflight if preflight is not None else preflight_report(),
        )
        return pack_dir / "fixtures.jsonl", seal.seal

    def retire(self, seal: str, reason: str = "synthetic retirement") -> None:
        retire_seal(seal, reason, self.ledger)


@pytest.fixture
def synthetic_ledger(tmp_path: Path) -> SyntheticLedger:
    """A port workspace with an empty ledger, ready for packs.

    The registry file must exist BEFORE any pack is sealed: ``seal_recording``
    walks up from the pack looking for ``PACKS.jsonl`` and registers into the
    first one it finds, so an absent ledger silently produces unregistered
    packs — a pack that loads while vouched for by nothing.
    """
    root = tmp_path / "synthetic-port"
    (root / "port_runs").mkdir(parents=True)
    (root / "port.toml").write_text(
        '# A synthetic port workspace (tests/_synthetic_ledger.py).\n'
        '[port]\nname = "synthetic"\n',
        encoding="utf-8",
    )
    (root / "port_runs" / "PACKS.jsonl").write_text("", encoding="utf-8")
    return SyntheticLedger(root=root)


def ledger_rows(ledger: Path) -> list[dict]:
    return [
        json.loads(line)
        for line in ledger.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]
