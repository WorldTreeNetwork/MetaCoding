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

**THE WITNESS SPEAKS (MetaCoding-96q).** Content-addressing alone bought only
*internal consistency*: three separate forgeries reached EXIT=0 / clean=true /
"reproduced 100%" by editing a fixture, recomputing ``content_id()``, and running
the shipped ``ctkr oracle-seal``. They worked because the pack's own witness was
mute — ``observation_refs`` were checked for RESOLUTION and never for CONTENT, and
an observation's excerpt was ``{"type","id"}``, so the recorder had never written
down the value a probe actually saw.

Now every assertion is minted with the witness that produced it
(:data:`ctkr.oracle.recorder.WITNESS_RECORD`), and loading enforces three things
the forger must now defeat:

* **every assertion cites a witness, and the witness agrees.** Same question,
  same value. A fixture whose expected value contradicts its own witness is
  INVALID EVIDENCE — not a pass, not a warning (attack (a), surgical forgery).
* **every witness is claimed.** A witness observation no assertion cites is an
  orphan, and a pack with orphans is a pack somebody took fixtures OUT of. This
  is what makes the subset attack visible in the artifact itself rather than only
  in a ledger somebody has to read (attack (b)).
* **the evidence class is inside the fixture's hash** (see
  :meth:`ctkr.oracle.fixtures.SemanticFixture._body_for_hash`), so a port cannot
  re-label the one fixture it fails as corroboration-only (attack (c)).

**AUTHORITY IS ISSUED BY OBSERVATION.** There is no longer a function that seals
a path. :func:`seal_recording` takes the in-memory
:class:`~ctkr.oracle.recorder.SessionResult` a recording produced and writes all
three files itself; the public CLI has ``oracle-validate`` (which VERIFIES a seal)
and no verb that issues one.

**What this still does not buy, stated plainly.** The seal is an unkeyed hash.
Anyone who can import this module can construct a ``SessionResult`` and seal it,
so a determined forger with write access can still produce a self-consistent
pack — they must now forge the fixture, its witness, the orphan set, and both
file digests together, which is re-recording the pack by hand rather than editing
a number. The residual gap is narrowed, not closed, and it is not closed by
:data:`REGISTRY_NAME` either: the registry is a real check now
(:func:`registered_seals`, consulted by :func:`load_pack`) but it only binds packs
that live under a tree containing one, and a forger works elsewhere. What the
registry buys is that a pack shipped from THIS repo cannot be quietly re-sealed
or truncated without a visible diff in a file the party being judged does not own.

**THE POSTURE (2026-07-21, closes MetaCoding-fmw).** The residual gap above is
closed by decision, not by escalation. This harness ASSUMES GOOD FAITH: its
machinery defends against error, saturation, and drift — the failure modes of
honest work — not against a determined forger among ourselves, because no
internal machinery can (every defense here is built by the hands it would
defend against; there is no fixed point inside the system). Its authorities
are external and named: the live source, reviewed history, human eyes. The
seal IDENTIFIES a pack; the witness CITES an observation; the ledger REMEMBERS
what was recorded; none of them prosecutes. Further tamper-resistance against
ourselves is out of scope — see docs/design/epistemology-charter.md.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from blake3 import blake3
from pydantic import BaseModel, ConfigDict, Field

from ctkr.oracle.fixtures import (
    SemanticFixture,
    load_fixtures,
    order_sensitivity,
    probe_descriptor,
    same_value,
    write_fixtures,
)
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
def seal_recording(
    fixtures: list[SemanticFixture],
    observations: list[Any],
    out_dir: str | Path,
    *,
    source_system: str = "",
    source_version: str = "",
    recorded_at: str = "",
    register: bool = True,
) -> PackSeal:
    """Write and seal a pack **from a recording**. The only way a seal is issued.

    There used to be a ``seal_pack(path)`` — point it at a directory and it
    re-issued that pack's entire authority — and ``ctkr oracle-seal`` exposed it
    as a public, unauthenticated verb. Its own docstring said sealing was done by
    "the RECORDER, which has no stake in a score"; the CLI made that sentence
    false, and all three forgeries in MetaCoding-96q ended with a call to it.

    This function cannot be pointed at a file. It takes the objects a recording
    session produced — the distilled fixtures and the observations, WITNESSES
    INCLUDED, that the live source answered with — and writes ``fixtures.jsonl``,
    ``observations.jsonl`` and ``pack.seal.json`` together. Sealing is therefore
    part of the act of recording, which requires the live source.

    It is not a cryptographic barrier and does not pretend to be one: see the
    module docstring for exactly what a forger must still do.
    """
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    fx_path = out / "fixtures.jsonl"
    obs_path = out / OBSERVATIONS_NAME

    if not observations:
        raise PackError(
            f"cannot seal {fx_path}: the session recorded no observations. A pack "
            f"without its witnesses is a claim without a witness."
        )

    write_fixtures(fixtures, fx_path)
    with obs_path.open("w", encoding="utf-8") as fh:
        for o in observations:
            row = o.model_dump() if hasattr(o, "model_dump") else dict(o)
            fh.write(json.dumps(row, default=str) + "\n")

    written = load_fixtures(fx_path)
    seal = PackSeal(
        recorded_at=recorded_at or (written[0].provenance.recorded_at if written else ""),
        source_system=source_system or (written[0].provenance.source_system if written else ""),
        source_version=source_version or (written[0].provenance.source_version if written else ""),
        fixture_ids=[f.fixture_id for f in written],
        fixtures_blake3=file_digest(fx_path),
        observations_blake3=file_digest(obs_path),
        derivations=current_derivations(),
    ).sealed()
    (out / SEAL_NAME).write_text(
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


def registry_entries(registry: Path | None) -> list[dict[str, Any]]:
    """Every seal ever registered in this ledger, as raw rows."""
    if registry is None or not registry.exists():
        return []
    return [
        json.loads(line)
        for line in registry.read_text(encoding="utf-8").splitlines()
        if line.strip()
    ]


def registered_seals(registry: Path | None) -> set[str]:
    """The seals this ledger vouches for.

    This function was cited by this module's own docstring as the control that
    closed the re-sealing gap, and it had ZERO callers: ``load_pack`` never read
    ``PACKS.jsonl``, so a re-sealed pack verified clean while its seal appeared
    nowhere in the ledger. It is consulted by :func:`registry_problem` now, which
    ``load_pack`` calls. A named control that does not run is worse than silence.
    """
    return {e["seal"] for e in registry_entries(registry) if e.get("seal")}


def registry_problem(seal: PackSeal, registry: Path | None) -> str:
    """Why this ledger does not vouch for this pack, or ``""``.

    Only binds where a ledger exists. That is a real limit, not a hidden one: a
    pack recorded into ``/tmp`` has no ledger above it and this returns ``""``.
    What it does buy is that a pack shipped from a tree WITH a ledger cannot be
    re-sealed or truncated in place and still load.
    """
    if registry is None:
        return ""
    entries = registry_entries(registry)
    if seal.seal not in {e.get("seal") for e in entries}:
        return (
            f"seal {seal.seal} is not in {registry}. This tree keeps a ledger of "
            f"every seal its recorder issued, and this pack's seal is not one of "
            f"them — it was sealed somewhere else, or re-sealed here after "
            f"editing. NO VERDICT."
        )
    mine = set(seal.fixture_ids)
    for e in entries:
        theirs = set(e.get("fixture_ids") or [])
        if theirs > mine:
            return (
                f"this pack is a STRICT SUBSET of registered pack "
                f"{e.get('pack_id', '?')} ({len(mine)} of {len(theirs)} fixtures). "
                f"A pack is judged whole; dropping the fixtures a port fails is "
                f"not a smaller pack, it is the same pack with the failures "
                f"removed. NO VERDICT."
            )
    return ""


# --------------------------------------------------------------------------- #
# Reading                                                                      #
# --------------------------------------------------------------------------- #
def _witness_problem(fx: SemanticFixture, witnesses: dict[str, dict[str, Any]]) -> str:
    """Why this fixture's own witnesses contradict it, or ``""``.

    THE RED, enforced: *no artifact can endorse a claim its own witnesses
    contradict.* Three checks, in the order a forger meets them:

    1. an assertion with no witness is unwitnessed — hand-authored by definition;
    2. a witness that answers a DIFFERENT question cannot answer this one;
    3. a value that differs from what the witness saw is INVALID EVIDENCE.

    (3) is the one that kills the surgical forgery. Editing ``then[0].value`` to
    the diverging port's answer and recomputing ``content_id()`` used to fully
    re-invert the GO test — the port that is WRONG about farmOS scored 14/14.
    The witness saying otherwise was already in the pack; nothing read it.
    """
    for i, t in enumerate(fx.then):
        if not t.witness:
            return (
                f"then[{i}] asserts {t.assert_!r} but names no witness — nothing "
                f"recorded that the source ever delivered this value. An "
                f"unwitnessed expected value is hand-authored, whatever its "
                f"provenance block says"
            )
        w = witnesses.get(t.witness)
        if w is None:
            return (
                f"then[{i}] cites witness {t.witness} which is not in this pack's "
                f"{OBSERVATIONS_NAME} — the assertion names a witness that is "
                f"not here"
            )
        asked = w.get("probe") or {}
        expected = probe_descriptor(t)
        if asked != expected:
            differing = sorted(
                k for k in expected
                if asked.get(k, "") != expected[k]
            )
            return (
                f"then[{i}] cites witness {t.witness}, which answered a DIFFERENT "
                f"question (differs on: {', '.join(differing)}). A witness to one "
                f"probe is not a witness to another"
            )
        if not same_value(w.get("observed"), t.value):
            return (
                f"then[{i}] expects {t.assert_} == {t.value!r}, but its own "
                f"witness {t.witness} records the source delivering "
                f"{w.get('observed')!r}. INVALID EVIDENCE: an artifact cannot "
                f"endorse a claim its own witness contradicts"
            )
    return ""


def _fixture_problems(
    fx: SemanticFixture,
    observation_ids: set[str],
    witnesses: dict[str, dict[str, Any]] | None = None,
) -> str:
    """Why this fixture is not evidence, or ``""``."""
    if fx.fixture_id and fx.fixture_id != fx.content_id():
        return (
            f"fixture_id {fx.fixture_id} does not hash its own body "
            f"({fx.content_id()}) — the scenario, an expected VALUE, a "
            f"witness ref, or the evidence class was edited after recording"
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
    witness_problem = _witness_problem(fx, witnesses or {})
    if witness_problem:
        return witness_problem
    # SELF-MARKING (attack (c)). An exemption from scoring is a claim about the
    # fixture, so it must be re-derivable from the fixture, not asserted by it.
    # Setting evidence_class="corroboration-only" on exactly the fixture a port
    # failed reached EXIT=0 / clean / "reproduced 100%" while "[FAIL]
    # group_member(A) expected == True, got False" still printed in the body.
    # Hashing the field (fixtures.py) makes the naive edit break the id; this
    # makes the edit useless even to someone who re-hashes and re-seals.
    if fx.provenance.evidence_class == "corroboration-only":
        earned = order_sensitivity(fx.when)
        if not earned:
            return (
                "claims evidence_class='corroboration-only', but nothing in the "
                "fixture earns it: no two writes share an effective time against "
                "one subject, so the observed value is not a fingerprint of the "
                "source's tie-break. A pack does not get to exempt its own "
                "fixtures from scoring — the exemption must be re-derivable from "
                "the flow, and this one is not"
            )
    elif fx.provenance.evidence_class not in ("", "scoring"):
        return (
            f"evidence_class {fx.provenance.evidence_class!r} is not a class this "
            f"loader knows; an unknown label is not an exemption"
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
                f"its scope — which is not a thing a defendant may do. There is "
                f"no verb that seals a pack you already have: a seal is issued "
                f"by the act of recording (`ctkr oracle-record`), against the "
                f"live source. Re-record it."
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

        # The ledger is consulted, not merely described. Only binds under a tree
        # that keeps one — see registry_problem for exactly what that is worth.
        problem = registry_problem(seal, registry_for(fx_path))
        if problem:
            raise PackError(f"{fx_path}: {problem}")

    observation_ids: set[str] = set()
    witnesses: dict[str, dict[str, Any]] = {}
    if obs_path.exists():
        for line in obs_path.read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            row = json.loads(line)
            observation_ids.add(row["obs_id"])
            if row.get("record") == "witness":
                witnesses[row["obs_id"]] = row

    # EVERY WITNESS IS CLAIMED. The subset attack — drop the fixtures a port
    # fails, re-seal — produced a pack in which nothing said the pack was partial
    # (fresh pack_id, no lineage to the original). It leaves a trace anyway: the
    # witnesses of the dropped fixtures are still in observations.jsonl with no
    # assertion citing them. A pack that does not account for its own witnesses
    # is a pack somebody took fixtures out of.
    claimed = {t.witness for fx in fixtures for t in fx.then if t.witness}
    orphans = sorted(set(witnesses) - claimed)
    if orphans and seal_path.exists():
        raise PackError(
            f"{fx_path}: {len(orphans)} witness observation(s) are claimed by no "
            f"assertion in this pack (first: {orphans[0]}, a "
            f"{(witnesses[orphans[0]].get('probe') or {}).get('assert', '?')} "
            f"probe). The recorder witnessed values this pack no longer asserts "
            f"— fixtures were removed after recording. A pack is judged whole. "
            f"NO VERDICT."
        )

    good: list[SemanticFixture] = []
    invalid: list[InvalidFixture] = []
    for fx in fixtures:
        problem = _fixture_problems(fx, observation_ids, witnesses)
        if problem:
            invalid.append(InvalidFixture(fx.fixture_id, fx.title, problem))
        else:
            good.append(fx)

    return Pack(path=fx_path, seal=seal, fixtures=good, invalid=invalid,
                observation_ids=observation_ids)
