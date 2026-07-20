"""What a port DECLARES about itself — capabilities, divergences, fixture marks.

``port-verify`` never infers anything about a port. Three things must be stated
up front, as data, before a single fixture runs:

1. **Capabilities** (:class:`PortCapabilities`) — which glossary *operations* the
   port can perform and which glossary *probes* it can answer. An assertion whose
   probe is not declared is an **unanswerable gap**; it can never become a pass.

2. **Divergences** (:class:`Divergence`) — where the port deliberately differs
   from the source system, naming the fixture, the assertion, the value the port
   is expected to deliver instead, why, and the decision that sanctioned it. A
   mismatch matching a declaration is EXPECTED-AND-CORRECT. A mismatch with no
   declaration is a failure, always. A declaration is never consulted for an
   *unanswerable* assertion, so "it's the divergence" can never excuse a gap.

3. **Fixture marks** (:class:`FixtureMark`) — evidence-quality facts about a
   recorded fixture that no port can fix: chiefly ``corroboration_only``, for a
   fixture whose observed value encodes the source's own insertion order (six
   permutations of the same events give four different values). Such a fixture
   is REPORTED but EXCLUDED from the value score: passing it proves nothing and
   failing it condemns nothing.

Marks live outside the fixture pack on purpose — a recorded pack is evidence and
``port-verify`` must never rewrite it. :class:`SemanticFixture` also carries an
optional ``scoring`` block for packs recorded after the schema learned about
this; when both exist the external marks file wins and says so.
"""

from __future__ import annotations

import json
from collections.abc import Iterable
from pathlib import Path
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from ctkr.oracle import glossary
from ctkr.oracle.probes import OPERATION_CONTRACT, PROBE_CONTRACT


class ContractError(ValueError):
    """A declaration is malformed, contradictory, or names an unknown term."""


class PortCapabilities(BaseModel):
    """The surface a port declares it offers, in glossary terms."""

    model_config = ConfigDict(extra="forbid")

    operations: list[str] = Field(default_factory=list)  # glossary action terms
    probes: list[str] = Field(default_factory=list)  # glossary assertion terms

    def unknown_terms(self) -> list[str]:
        bad = [f"operation {o!r} is not a glossary action term"
               for o in self.operations if o not in OPERATION_CONTRACT]
        bad += [f"probe {p!r} is not a glossary assertion term"
                for p in self.probes if p not in PROBE_CONTRACT]
        return bad

    def as_sets(self) -> tuple[frozenset[str], frozenset[str]]:
        return frozenset(self.operations), frozenset(self.probes)


class Divergence(BaseModel):
    """One declared, sanctioned difference between the port and the source.

    ``port_value`` is required: a divergence states *what the port will deliver
    instead*, not merely "this one is allowed to differ". Without it a
    declaration would be a blank cheque against the source's value.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    fixture_id: str
    assert_: str = Field(alias="assert")
    subject: str = ""
    measure: str = ""  # optional discriminator when a fixture asserts a term twice
    unit: str = ""
    index: int | None = None  # 0-based, among assertions matching the above
    port_value: Any  # what the port is expected to deliver instead — required
    reason: str
    #: REQUIRED and RESOLVED. A sanction must point at a decision that actually
    #: exists in the decision registry. Free text alone made a divergence an
    #: unbounded blank cheque: an adversarial review wrote a port that answered
    #: 999 to everything, declared 30 reason-only divergences, and turned a
    #: 0/30 verdict into "100%, clean, exit 0". A sanction now names its warrant.
    decision_id: str

    def matches(self, t: Any, occurrence: int) -> bool:
        """Whether this declaration addresses assertion ``t`` (its ``occurrence``-th
        among same-shaped assertions of the fixture)."""
        if t.assert_ != self.assert_:
            return False
        if self.subject and t.subject != self.subject:
            return False
        if self.measure and t.measure != self.measure:
            return False
        if self.unit and t.unit != self.unit:
            return False
        if self.index is not None and occurrence != self.index:
            return False
        return True


class FixtureMark(BaseModel):
    """Evidence-quality facts about one recorded fixture."""

    model_config = ConfigDict(extra="forbid")

    fixture_id: str
    corroboration_only: bool = False
    order_sensitive: bool = False
    reason: str = ""

    @property
    def excluded_from_score(self) -> bool:
        return self.corroboration_only or self.order_sensitive


class BridgeSpec(BaseModel):
    """How to start the port's verification bridge process."""

    model_config = ConfigDict(extra="forbid")

    command: list[str]
    cwd: str = ""  # relative to the manifest's directory when not absolute
    env: dict[str, str] = Field(default_factory=dict)
    timeout: float = 30.0


class PortManifest(BaseModel):
    """``port.manifest.json`` — everything a port declares before being judged."""

    model_config = ConfigDict(extra="forbid")

    port: str
    description: str = ""
    bridge: BridgeSpec
    capabilities: PortCapabilities = Field(default_factory=PortCapabilities)
    divergences: list[Divergence] = Field(default_factory=list)
    fixture_marks: list[FixtureMark] = Field(default_factory=list)
    #: Path (relative to the manifest) of the manifest itself, filled on load.
    manifest_path: str = ""

    # ---- loading ----------------------------------------------------------- #
    @classmethod
    def load(cls, path: str | Path) -> PortManifest:
        p = Path(path)
        if p.is_dir():
            p = p / "port.manifest.json"
        if not p.exists():
            raise ContractError(
                f"no port manifest at {p} — a port must DECLARE its probe surface "
                f"before it can be verified (see docs/design/port-verify.md)"
            )
        try:
            raw = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as exc:
            raise ContractError(f"{p}: {exc}") from exc
        try:
            m = cls.model_validate({**raw, "manifest_path": str(p.resolve())})
        except Exception as exc:  # noqa: BLE001 — surface the file
            raise ContractError(f"{p}: {exc}") from exc
        m.check()
        return m

    # ---- validation -------------------------------------------------------- #
    def check(self) -> None:
        problems = self.capabilities.unknown_terms()
        for d in self.divergences:
            if d.assert_ not in glossary.ASSERTION_TERMS:
                problems.append(
                    f"divergence on {d.fixture_id}: {d.assert_!r} is not a "
                    f"glossary assertion term"
                )
            if not d.reason.strip():
                problems.append(
                    f"divergence on {d.fixture_id}/{d.assert_}: reason is required"
                )
            if not d.decision_id.strip():
                problems.append(
                    f"divergence on {d.fixture_id}/{d.assert_}: decision_id is "
                    f"required — a sanctioned divergence must name the decision "
                    f"that sanctions it, not just assert one exists"
                )
        seen: set[str] = set()
        for mark in self.fixture_marks:
            if mark.fixture_id in seen:
                problems.append(f"duplicate fixture mark for {mark.fixture_id}")
            seen.add(mark.fixture_id)
            if mark.excluded_from_score and not mark.reason.strip():
                problems.append(
                    f"fixture mark {mark.fixture_id}: excluding a fixture from the "
                    f"score requires a reason"
                )
        if problems:
            raise ContractError("; ".join(problems))

    @property
    def root(self) -> Path:
        return Path(self.manifest_path).parent if self.manifest_path else Path.cwd()

    def bridge_cwd(self) -> Path:
        if not self.bridge.cwd:
            return self.root
        c = Path(self.bridge.cwd)
        return c if c.is_absolute() else (self.root / c)


def load_marks(path: str | Path) -> list[FixtureMark]:
    """Read an external fixture-marks file (JSON list or JSONL).

    Marks are kept OUT of the recorded pack: a pack is evidence and must not be
    rewritten to make a port look better or worse.
    """
    p = Path(path)
    text = p.read_text(encoding="utf-8").strip()
    if not text:
        return []
    rows: list[dict[str, Any]]
    if text.lstrip().startswith("["):
        rows = json.loads(text)
    else:
        rows = [json.loads(line) for line in text.splitlines() if line.strip()]
    try:
        marks = [FixtureMark.model_validate(r) for r in rows]
    except Exception as exc:  # noqa: BLE001
        raise ContractError(f"{p}: {exc}") from exc

    # The external path WINS over in-manifest marks, so it must be the
    # BEST-validated path, not the unvalidated one. It previously skipped the
    # reason check that in-manifest marks get — which let a reason-less marks
    # file exclude every fixture in a pack and turn 30 wrong answers into a
    # zero-failure run. Excluding evidence from a score always costs a reason.
    problems: list[str] = []
    seen: set[str] = set()
    for m in marks:
        if m.fixture_id in seen:
            problems.append(f"duplicate fixture mark for {m.fixture_id}")
        seen.add(m.fixture_id)
        if m.excluded_from_score and not m.reason.strip():
            problems.append(
                f"fixture mark {m.fixture_id}: excluding a fixture from the score "
                f"requires a reason"
            )
    if problems:
        raise ContractError(f"{p}: " + "; ".join(problems))
    return marks


#: Where decision ids are resolved from, relative to the repo root. A divergence
#: naming a decision that no registry knows about is a declaration problem.
DEFAULT_DECISION_SOURCES: tuple[str, ...] = (
    "eval/ctkr/port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
)


def load_decision_ids(paths: Iterable[str | Path]) -> set[str]:
    """Collect known decision ids from JSONL decision registries.

    Accepts either the kernel CM registry (keyed ``invariant``) or a port-decision
    ledger (keyed ``id`` / ``decision_id`` / ``targetElement``). Missing files are
    skipped by the caller, not silently treated as empty — an unresolvable
    ``decision_id`` must surface, never pass.
    """
    ids: set[str] = set()
    for path in paths:
        p = Path(path)
        if not p.exists():
            continue
        for line in p.read_text(encoding="utf-8").splitlines():
            s = line.strip()
            if not s or s.startswith("//"):
                continue
            try:
                row = json.loads(s)
            except json.JSONDecodeError:
                continue
            for key in ("invariant", "id", "decision_id", "targetElement"):
                v = row.get(key)
                if isinstance(v, str) and v.strip():
                    ids.add(v.strip())
    return ids
