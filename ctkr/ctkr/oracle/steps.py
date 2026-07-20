"""Execution of ``given``/``when`` steps — the one interpreter of the flow DSL.

The recorder (which observes a flow to distil a fixture) and the runner (which
replays a distilled fixture) must drive an implementation **identically**;
otherwise a fixture could pass on replay for a reason the recording never saw.
So both call the functions here, and a new action is added in exactly one place.

Effective times are resolved once per flow against a single ``now`` so that a
flow using relative offsets ("-3600", "+86400") lays its events out in the same
relative arrangement on every run.
"""

from __future__ import annotations

from datetime import UTC, datetime

from ctkr.oracle.adapter import AdapterError, Handle, ImplementationAdapter
from ctkr.oracle.fixtures import GivenStep, WhenStep, resolve_effective_time


def flow_now() -> datetime:
    """The single reference instant a flow's relative effective times hang off."""
    return datetime.now(UTC)


def apply_given(adapter: ImplementationAdapter, g: GivenStep) -> Handle:
    """Instantiate one ``given`` entity and return its handle."""
    if g.sex:
        return adapter.create_asset(g.entity, g.name, g.descriptor, g.sex)
    # Keep the 3-argument call for adapters written before the trait existed.
    return adapter.create_asset(g.entity, g.name, g.descriptor)


def apply_when(
    adapter: ImplementationAdapter,
    w: WhenStep,
    handles: dict[str, Handle],
    now: datetime | None = None,
) -> None:
    """Perform one ``when`` action, binding any handle it creates into ``handles``."""
    at = resolve_effective_time(w.at, now) if w.at else None

    if w.action == "record_log":
        h = adapter.record_log(
            w.kind, w.name or f"{w.kind} log", w.status or "done",
            [handles[a] for a in w.against], w.quantities,
        )
        if at is not None:
            adapter.set_effective_time(h, at)
        if w.alias:
            handles[w.alias] = h
    elif w.action == "set_log_status":
        adapter.set_log_status(handles[w.ref], w.status)
    elif w.action == "assign_to_group":
        adapter.assign_to_group(handles[w.ref], handles[w.group])
    elif w.action == "archive_asset":
        adapter.archive_asset(handles[w.ref])
    elif w.action == "record_inventory_adjustment":
        h = adapter.record_inventory_adjustment(
            w.kind, w.name or f"{w.kind} adjustment", w.status or "done",
            [handles[a] for a in w.against], w.quantities, at,
        )
        if w.alias:
            handles[w.alias] = h
    elif w.action == "set_effective_time":
        adapter.set_effective_time(handles[w.ref], at)
    elif w.action == "record_birth":
        h = adapter.record_birth(
            handles[w.ref], [handles[p] for p in w.parents],
            w.name or "birth", w.status or "done", at,
        )
        if w.alias:
            handles[w.alias] = h
    elif w.action == "correct_birth":
        adapter.correct_birth(
            handles[w.ref],
            [handles[p] for p in w.parents] if w.parents else None,
            at,
        )
    elif w.action == "set_parents":
        adapter.set_parents(handles[w.ref], [handles[p] for p in w.parents])
    elif w.action == "set_nicknames":
        adapter.set_nicknames(handles[w.ref], list(w.names))
    else:
        raise AdapterError(f"no interpreter for action {w.action!r}")
