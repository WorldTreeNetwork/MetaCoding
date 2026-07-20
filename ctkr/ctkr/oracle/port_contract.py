"""What a port DECLARES **about itself** — and nothing else.

INVARIANT 2: *the defendant never holds a pen that touches the verdict.*

A port may state exactly two kinds of thing, and both are claims about the port:

1. **Capabilities** (:class:`PortCapabilities`) — which glossary *operations* it
   can perform and which glossary *probes* it can answer. This is a claim about
   itself, and it is checkable against its own running bridge, so it is safe to
   let the port make it: over-claiming becomes a false declaration, under-claiming
   becomes a gap, and neither is a pass.

2. **Divergences** (:class:`Divergence`) — where it deliberately differs from the
   source, naming the fixture, the assertion, the value it will deliver instead,
   why, and the decision that sanctions it. A divergence never *excuses* anything:
   it is reported in its own bucket, is not counted as a pass, and blocks a clean
   verdict. And its ``decision_id`` must resolve — **topically** — against the
   repo's decision registry, which the port does not write and cannot point
   elsewhere: citing a real decision about birth logs to wave through five stock
   arithmetic errors was an accepted move until the topical check existed.

**What a port may no longer say.** ``fixture_marks`` is gone from the manifest, and
so is the external ``--marks`` file. Both let the party being judged (or anyone
holding its command line) declare which evidence counts: adding five
``corroboration_only`` marks to a port's own manifest turned ``failed 5 / EXIT=1``
into ``failed 0 / reproduced 100% / clean=true / EXIT=0``, with the five FAILs
still printed in the body. Evidence quality is now stated in exactly one place —
``provenance.evidence_class``, written by the recorder into a sealed pack (see
:mod:`ctkr.oracle.pack`) — because the recorder has no stake in the score.
A manifest that still carries ``fixture_marks`` does not load: ``extra="forbid"``
means the pen does not exist rather than being unavailable.
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
    # NOTE: there is deliberately no `fixture_marks` field. `extra="forbid"`
    # makes a manifest that carries one FAIL TO LOAD — the pen is absent, not
    # merely ignored, so a port cannot mark its own failing evidence unscoreable.
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


#: Where decision ids resolve from, relative to the REPO ROOT — never from a
#: caller-supplied path. `--decisions <anything>` let a port author point the
#: resolver at a registry they had just written, which makes "it's a sanctioned
#: divergence" self-certifying again one level up.
DEFAULT_DECISION_SOURCES: tuple[str, ...] = (
    "eval/ctkr/port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
)


def load_decisions(paths: Iterable[str | Path]) -> dict[str, str]:
    """``{decision_id: the decision's own text}`` from JSONL decision registries.

    The TEXT is kept, not just the id, because existence is not warrant: five
    stock-arithmetic divergences citing ``birth-uniqueness`` — a real decision,
    about birth logs — were all accepted, and the exit code was downgraded from
    1 to 3. A sanction must be *topically* bound to what it sanctions
    (:func:`decision_covers`).
    """
    out: dict[str, str] = {}
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
            text = json.dumps(row, sort_keys=True).lower()
            for key in ("invariant", "id", "decision_id", "targetElement"):
                v = row.get(key)
                if isinstance(v, str) and v.strip():
                    out[v.strip()] = out.get(v.strip(), "") + " " + text
    return out


def decision_covers(text: str, assertion: str) -> bool:
    """Whether a decision's own text names the assertion term it is cited for.

    Deliberately a *naming* test rather than a semantic one: the decision must
    have been written with this term in view. A decision that never mentions
    ``stock_on_hand`` cannot sanction a wrong ``stock_on_hand``, whatever the
    port says about it.
    """
    return assertion.lower() in (text or "").lower()
