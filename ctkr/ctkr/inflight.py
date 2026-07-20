"""In-flight decision emission — surfacing a needed decision WHILE agents run.

WHY THIS EXISTS (MetaCoding-9h5.22). Every decision-surfacing mechanism the port
loop has is either build-time or after-the-fact: ``requireBound`` throws at store
construction for a decision the build DECLARED, and ``ctkr decisions collect``
mines artifacts once a build has finished. Neither helps during a wave.

Two gaps that closed together on 2026-07-20:

* **The decision that needs surfacing is usually one nobody declared.** w0b-1
  (parent lineage) was invented mid-build; no registry entry existed to be
  unresolved, so nothing could fire. ``requireBound`` cannot catch what was never
  declared.
* **A decision can be falsified while builders are running.** That morning three
  bound decisions were re-bound on observed evidence. Had 15 builders been in
  flight they would have spent the day building on refuted decisions, and — since
  the pilot build carried a private copy of the kernel — a fix would have reached
  none of them.

So a builder appends a record the MOMENT it defers, invents, or hits a conflict,
rather than reporting at the end. The ledger is append-only JSONL with a
deliberately trivial contract: an agent in any language can append one line
without importing anything. This module is the reader, the validator, and the
convenience writer — never a gatekeeper on the write path, because a channel that
can refuse a report is a channel that loses reports.

The orchestrator polls between checkpoints; ``by_topic`` is what punt-promotion
counts (N deferrals on one topic promote it to a kernel candidate — the mechanism
that already proved itself when 7/7 builds independently punted on cross-replica
ordering, and the HLC requirement emerged from the pattern).
"""

from __future__ import annotations

import json
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

#: Ledger path relative to a data dir. One file per wave, appended by every agent.
INFLIGHT_RELPATH = "ctkr/inflight-decisions.jsonl"

#: What an agent is telling us. Each is a different call for the orchestrator.
KINDS: frozenset[str] = frozenset(
    {
        # "I deferred this and rolled forward on an assumption." The punt-promotion
        # input: N of these on one topic means the kernel is missing something.
        "punt",
        # "I had to decide something no registry knew about." w0b-1 was this.
        "invented",
        # "What I need contradicts a bound decision." Stop, do not resolve locally.
        "conflict",
        # "I cannot proceed without an answer." A blocked agent, not a guess.
        "blocked",
    }
)


class InflightError(ValueError):
    """A malformed in-flight record."""


@dataclass(frozen=True)
class InflightRecord:
    """One decision signal from a running agent."""

    #: who emitted it — an agent label or build id, so an interrupt can find them.
    agent: str
    #: the feature being ported, for blast-radius lookup in the feature×kind graph.
    feature: str
    #: a STABLE slug for what is being decided. Punt-promotion counts by this, so
    #: two agents hitting the same wall must choose the same topic — prefer an
    #: invariant name already in the registry ("birth-uniqueness") over prose.
    topic: str
    kind: str
    #: what was deferred/invented/contradicted, in one sentence.
    statement: str
    #: event kinds this touches — the join key to the feature×kind graph, which
    #: turns "someone needs a decision" into "these three agents are affected".
    event_kinds: tuple[str, ...] = ()
    #: what the agent did in the meantime. An honest punt says so.
    assumption: str = ""
    #: the kernel pin the agent was running against, if it knows it.
    kernel: str = ""
    #: ISO-8601, supplied by the caller (never generated here: a deterministic
    #: reader must not invent time).
    at: str = ""

    def to_json(self) -> str:
        return json.dumps(
            {
                "agent": self.agent,
                "feature": self.feature,
                "topic": self.topic,
                "kind": self.kind,
                "statement": self.statement,
                "event_kinds": list(self.event_kinds),
                "assumption": self.assumption,
                "kernel": self.kernel,
                "at": self.at,
            },
            sort_keys=True,
        )


def validate(raw: Any, where: str = "record") -> InflightRecord:
    """Validate one parsed record. Strict about the fields an interrupt needs."""
    if not isinstance(raw, dict):
        raise InflightError(f"{where}: expected an object, got {type(raw).__name__}")
    for f in ("agent", "feature", "topic", "kind", "statement"):
        v = raw.get(f)
        if not isinstance(v, str) or not v.strip():
            raise InflightError(f"{where}: {f!r} is required and must be a non-empty string")
    kind = raw["kind"]
    if kind not in KINDS:
        raise InflightError(
            f"{where}: kind {kind!r} is not one of {sorted(KINDS)}"
        )
    ek = raw.get("event_kinds", [])
    if not isinstance(ek, list) or any(not isinstance(x, str) for x in ek):
        raise InflightError(f"{where}: event_kinds must be a list of strings")
    return InflightRecord(
        agent=raw["agent"], feature=raw["feature"], topic=raw["topic"],
        kind=kind, statement=raw["statement"], event_kinds=tuple(ek),
        assumption=str(raw.get("assumption", "") or ""),
        kernel=str(raw.get("kernel", "") or ""),
        at=str(raw.get("at", "") or ""),
    )


def ledger_path(data_dir: str | Path) -> Path:
    return Path(data_dir) / INFLIGHT_RELPATH


def emit(record: InflightRecord, data_dir: str | Path) -> Path:
    """Append one record. Creates the ledger if absent.

    Append-only and never rewritten: a report an orchestrator has already acted on
    must not be editable by the agent that filed it.
    """
    p = ledger_path(data_dir)
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", encoding="utf-8") as fh:
        fh.write(record.to_json() + "\n")
    return p


@dataclass
class LedgerRead:
    """Everything the ledger holds, plus the lines that would not parse.

    Malformed lines are RETURNED, never skipped silently: a hand-appended record
    from an agent that got the shape wrong is still an agent telling us something,
    and dropping it would recreate exactly the silence this ledger exists to end.
    """

    records: list[InflightRecord] = field(default_factory=list)
    malformed: list[str] = field(default_factory=list)


def read(data_dir: str | Path) -> LedgerRead:
    """Read the ledger. Missing file is an empty read, not an error."""
    p = ledger_path(data_dir)
    out = LedgerRead()
    if not p.exists():
        return out
    for lineno, line in enumerate(p.read_text(encoding="utf-8").splitlines(), 1):
        s = line.strip()
        if not s or s.startswith("//"):
            continue
        try:
            out.records.append(validate(json.loads(s), f"line {lineno}"))
        except (json.JSONDecodeError, InflightError) as exc:
            out.malformed.append(f"line {lineno}: {exc}")
    return out


def by_topic(records: list[InflightRecord]) -> dict[str, list[InflightRecord]]:
    """Group by topic — the punt-promotion input."""
    groups: dict[str, list[InflightRecord]] = defaultdict(list)
    for r in records:
        groups[r.topic].append(r)
    return dict(groups)


def promotion_candidates(
    records: list[InflightRecord], threshold: int = 2
) -> list[tuple[str, list[InflightRecord]]]:
    """Topics that N or more DISTINCT agents deferred or invented on.

    Distinct agents, not distinct records: one agent hitting the same wall five
    times is one signal, while two agents hitting it independently is the pattern
    that means the kernel is missing something. That distinction is the whole
    value of the 7/7 HLC observation — seven builders, not seven mentions.

    A `conflict` or `blocked` record is NOT a promotion signal: it needs answering
    now, not accumulating. It surfaces through `needs_attention`.
    """
    out: list[tuple[str, list[InflightRecord]]] = []
    for topic, rs in sorted(by_topic(records).items()):
        deferrals = [r for r in rs if r.kind in ("punt", "invented")]
        if len({r.agent for r in deferrals}) >= threshold:
            out.append((topic, deferrals))
    return out


def needs_attention(records: list[InflightRecord]) -> list[InflightRecord]:
    """Records an orchestrator must act on NOW: conflicts and blocked agents."""
    return [r for r in records if r.kind in ("conflict", "blocked")]


def affected_agents(
    records: list[InflightRecord], event_kinds: set[str]
) -> list[str]:
    """Which agents are touching any of these event kinds — the interrupt list.

    The join to the feature×kind graph (9h5.21): a decision about an event kind
    affects exactly the in-flight features that touch it, so an interrupt can be
    targeted instead of stopping the whole wave.
    """
    return sorted({
        r.agent for r in records if event_kinds.intersection(r.event_kinds)
    })
