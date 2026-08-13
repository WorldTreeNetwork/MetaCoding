"""What a port DECLARES **about itself** — and nothing else.

INVARIANT 2: *the thesis does not write its own reading.*

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

from ctkr.oracle.lens import active_operation_contract, active_probe_contract, active_vocabulary


class ContractError(ValueError):
    """A declaration is malformed, contradictory, or names an unknown term."""


class PortCapabilities(BaseModel):
    """The surface a port declares it offers, in glossary terms."""

    model_config = ConfigDict(extra="forbid")

    operations: list[str] = Field(default_factory=list)  # glossary action terms
    probes: list[str] = Field(default_factory=list)  # glossary assertion terms

    def unknown_terms(self) -> list[str]:
        bad = [f"operation {o!r} is not a glossary action term"
               for o in self.operations if o not in active_operation_contract()]
        bad += [f"probe {p!r} is not a glossary assertion term"
                for p in self.probes if p not in active_probe_contract()]
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


class QuestionsRaised(BaseModel):
    """What the builder could not answer — declared, so silence is impossible.

    A builder that guesses is the input to everything downstream: two builders
    guessing differently at the same question is not an open question, it is two
    answers already shipped in two places. `ctkr decisions emit` is the channel
    for saying so WHILE running, and it had no caller for three weeks.

    This is the end-of-build half, and it exists because the running half cannot
    be enforced: nothing can make a builder NOTICE it is guessing. What can be
    enforced is that it answers the question. So `none` is not the absence of a
    declaration — it is a POSITIVE CLAIM with a reason attached, exactly like a
    declined affirmation at a wave close. Absence of the block means the build
    never said, and that is a third state the wave close names rather than reads
    as a no.
    """

    model_config = ConfigDict(extra="forbid")

    #: Question slugs, matching the `topic` of the in-flight records emitted for
    #: them. Same string on purpose: the cross-check is "did you also say so
    #: while it could still have been acted on?"
    raised: list[str] = Field(default_factory=list)
    #: REQUIRED when `raised` is empty. "I hit nothing" is a claim, and a claim
    #: with no reason is the rubber stamp this project keeps having to remove.
    none_because: str = ""

    def check(self, where: str) -> list[str]:
        bad = [f"{where}: questions.raised[{i}] is empty"
               for i, q in enumerate(self.raised) if not q.strip()]
        if not self.raised and not self.none_because.strip():
            bad.append(
                f"{where}: questions.raised is empty and questions.none_because is "
                f"not set. Declaring that nothing came up is a CLAIM — say why "
                f"(e.g. 'every decision this build needed was already bound'). An "
                f"empty block that means nothing is indistinguishable from one "
                f"nobody filled in."
            )
        return bad


class PortManifest(BaseModel):
    """``port.manifest.json`` — everything a port declares before being judged."""

    model_config = ConfigDict(extra="forbid")

    port: str
    description: str = ""
    bridge: BridgeSpec
    capabilities: PortCapabilities = Field(default_factory=PortCapabilities)
    divergences: list[Divergence] = Field(default_factory=list)
    #: OPTIONAL IN THE SCHEMA, DELIBERATELY, and not because it is optional in the
    #: recipe. 41 manifests were sealed before this field existed; making it
    #: required would either invalidate them or invite someone to retro-fill a
    #: claim their builders never made. Both are worse than the truth, which is
    #: that those builds never said. `wave close` reports absence as its own
    #: state — see `promotions.declarations`.
    questions: QuestionsRaised | None = None
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
        if self.questions is not None:
            problems += self.questions.check("questions")
        for d in self.divergences:
            if d.assert_ not in active_vocabulary().ASSERTION_TERMS:
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


#: Environment override for the PORT WORKSPACE root — the directory that holds
#: the workspace's ``port_runs/`` and ``results/`` trees. The workspace is the
#: target's ledger (packs, seals, PACKS.jsonl, decisions, partition, builds) and
#: is being extracted into its own repo (MetaCoding-1gt); this variable is how an
#: extracted workspace is pointed at without editing the instrument. Unset means
#: :data:`DEFAULT_PORT_WORKSPACE` under the repo root — today's in-repo layout.
#: The in-repo workspace location, relative to the repo root — the FALLBACK
#: while the farmOS ledger still lives inside this repo. A workspace that has
#: been extracted declares itself with a port.toml instead (MetaCoding-1gt).
DEFAULT_PORT_WORKSPACE = "eval/ctkr"

#: Where decision ids resolve from, relative to the PORT WORKSPACE root — never
#: from a caller-supplied path. `--decisions <anything>` let a port author point
#: the resolver at a registry they had just written, which makes "it's a
#: sanctioned divergence" self-certifying again one level up. Only the workspace
#: ROOT is discovered; the registry path *within* it stays fixed, so no port can
#: move it — and deliberately no port.toml key exposes it.
DECISION_REGISTRY_RELPATHS: tuple[str, ...] = (
    "port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
)


def port_workspace(root: Path) -> Path:
    """The port workspace directory, DISCOVERED rather than configured.

    Walks up from the working directory for a ``port.toml`` (see
    :mod:`ctkr.workspace`); falls back to the in-repo ``eval/ctkr`` while the
    ledger still lives here. ``root`` is the repo root, used only for that
    fallback.

    This replaced a ``METACODING_PORT_WORKSPACE`` environment variable, which
    was the eighth path-ish knob in a system whose problem was that a port had
    no identity. The manifest gives it one.
    """
    from ctkr.workspace import default_workspace, discover

    return discover(fallback=default_workspace(root) or root / DEFAULT_PORT_WORKSPACE).root


def decision_sources(root: Path) -> tuple[Path, ...]:
    """Absolute paths of the bound CM-decision registries under the workspace."""
    workspace = port_workspace(root)
    return tuple(workspace / rel for rel in DECISION_REGISTRY_RELPATHS)


def load_decisions(paths: Iterable[str | Path]) -> dict[str, dict[str, Any]]:
    """``{decision_id: {"text": ..., "sanctions": (...)}}`` from JSONL registries.

    ``sanctions`` is the decision's OWN typed list of glossary assertion terms
    it sanctions divergence on. Existence is not warrant, and — the wave-1
    lesson — neither is prose: the registry's text named the camelCase
    projections (``yieldTotal``) while the verifier speaks glossary terms
    (``yield_total``), so the one deliberately chosen divergence scored as an
    undeclared mismatch in all four readings (MetaCoding-n9o). A sanction is a
    CITATION, not a mention; it must reference the identity of the question
    asked at the boundary, which survives any renaming on either side.
    """
    out: dict[str, dict[str, Any]] = {}
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
            raw = row.get("sanctions")
            sanctions = tuple(
                t.strip() for t in raw if isinstance(t, str) and t.strip()
            ) if isinstance(raw, list) else ()
            for key in ("invariant", "id", "decision_id", "targetElement"):
                v = row.get(key)
                if isinstance(v, str) and v.strip():
                    prev = out.get(v.strip(), {"text": "", "sanctions": ()})
                    out[v.strip()] = {
                        "text": prev["text"] + " " + text,
                        "sanctions": tuple(dict.fromkeys((*prev["sanctions"], *sanctions))),
                    }
    return out


def decision_covers(entry: Any, assertion: str) -> bool:
    """Whether a decision CITES the assertion term in its ``sanctions`` field.

    Names never sanction. The previous implementation was a substring test over
    the decision's prose, which failed both ways: a decision written about
    ``yieldTotal`` could not sanction ``yield_total`` (the wave-1 inversion,
    MetaCoding-n9o), and a decision whose rationale merely *mentioned* a term
    in passing would have sanctioned it. A port is free to rename everything —
    the stable identity is the glossary term of the question asked at the
    boundary, and a sanction must cite it explicitly. Legacy string entries
    (prose only, no ``sanctions``) cover nothing.
    """
    if isinstance(entry, dict):
        return assertion in entry.get("sanctions", ())
    return False
