"""The probe-surface contract — one table binding fixture vocabulary to a surface.

A fixture speaks glossary terms (``stock_on_hand``, ``adjustment_count``,
``record_inventory_adjustment``). An implementation offers *methods* on an
:class:`~ctkr.oracle.adapter.ImplementationAdapter`. Until this module existed the
binding between the two lived, unwritten, in whoever was driving the
implementation that day — which is exactly how thirteen assertions that no port
surface could answer were quietly scored as if they had been.

The contract here is the single place that binding exists:

* :data:`PROBE_CONTRACT` — one :class:`ProbeSpec` per glossary **assertion**
  term: the adapter method that answers it and how the assertion's fields become
  that method's arguments.
* :data:`OPERATION_CONTRACT` — one :class:`OperationSpec` per glossary **action**
  term: the adapter methods a ``when`` step of that action needs.

Both the oracle runner (which drives a live source system) and ``port-verify``
(which drives a built port) read this table, so "which method answers
``adjustment_count``" cannot drift between them. A port DECLARES which glossary
terms it offers; anything it does not declare is an *unanswerable* assertion —
a declared gap — never a pass and never a silent drop.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from ctkr.oracle import glossary


@dataclass(frozen=True)
class Param:
    """One argument of a probe call, taken from the ``then`` assertion.

    ``alias_noun`` non-empty marks the field as a **logical alias** that must be
    resolved to a run-time handle before the call; the noun is used in the error
    message when the alias was never created ("group alias 'G' was never
    created").
    """

    field_name: str
    alias_noun: str = ""

    @property
    def is_alias(self) -> bool:
        return bool(self.alias_noun)


@dataclass(frozen=True)
class ProbeSpec:
    """How one glossary assertion term is answered by an adapter."""

    assertion: str
    method: str
    #: Arguments after the subject handle, in call order.
    params: tuple[Param, ...] = ()
    #: What the ``subject`` alias denotes — an entity or a recorded event.
    subject_kind: str = "entity"  # "entity" | "event"
    doc: str = ""


@dataclass(frozen=True)
class OperationSpec:
    """How one glossary action term is performed by an adapter."""

    action: str
    #: Methods always required to perform the action.
    methods: tuple[str, ...] = ()
    #: Methods additionally required when the step carries an effective time.
    methods_when_timed: tuple[str, ...] = field(default_factory=tuple)
    doc: str = ""


# --------------------------------------------------------------------------- #
# The read surface: assertion term -> adapter method                           #
# --------------------------------------------------------------------------- #
_PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec("yield_total", "asset_yield_total",
              (Param("measure"), Param("unit")),
              doc="Σ of a measure across recorded logs against an asset."),
    ProbeSpec("log_status", "log_status", (), subject_kind="event",
              doc="The lifecycle status delivered for a recorded event."),
    ProbeSpec("log_count", "log_count", (Param("kind"),),
              doc="How many logs of a kind reference an asset."),
    ProbeSpec("asset_active", "asset_active", (),
              doc="Whether an asset is in the active set."),
    ProbeSpec("group_member", "group_member", (Param("group", "group"),),
              doc="Whether an asset is a member of a group."),
    ProbeSpec("quantity_recorded", "quantity_recorded",
              (Param("measure"), Param("unit")), subject_kind="event",
              doc="A measured value recorded on one specific event."),
    ProbeSpec("stock_on_hand", "stock_on_hand", (Param("measure"), Param("unit")),
              doc="Running stock for one (measure, unit) pair."),
    ProbeSpec("stock_pair_count", "stock_pair_count", (),
              doc="How many (measure, unit) pairs report stock."),
    ProbeSpec("adjustment_count", "adjustment_count", (),
              doc="How many stock adjustments are readable against an asset."),
    ProbeSpec("animal_sex", "animal_sex", (),
              doc="The sex delivered for an animal."),
    ProbeSpec("nicknames", "nicknames", (),
              doc="The ordered informal names delivered for an animal."),
    ProbeSpec("birth_date", "birth_date", (),
              doc="The date of birth delivered for an animal."),
    ProbeSpec("parent_count", "parent_count", (),
              doc="How many parents an animal is delivered with."),
    ProbeSpec("has_parent", "has_parent", (Param("other", "animal"),),
              doc="Whether one animal is delivered as another's parent."),
    ProbeSpec("birth_record_count", "birth_record_count", (),
              doc="How many birth records claim an animal as issue."),
)

PROBE_CONTRACT: dict[str, ProbeSpec] = {p.assertion: p for p in _PROBES}


# --------------------------------------------------------------------------- #
# The write surface: action term -> adapter method(s)                          #
# --------------------------------------------------------------------------- #
_OPERATIONS: tuple[OperationSpec, ...] = (
    OperationSpec("record_log", ("record_log",), ("set_effective_time",),
                  doc="Record a log; a dated log also needs a restatement."),
    OperationSpec("set_log_status", ("set_log_status",)),
    OperationSpec("assign_to_group", ("assign_to_group",)),
    OperationSpec("archive_asset", ("archive_asset",)),
    OperationSpec("record_inventory_adjustment", ("record_inventory_adjustment",)),
    OperationSpec("set_effective_time", ("set_effective_time",)),
    OperationSpec("record_birth", ("record_birth",)),
    OperationSpec("correct_birth", ("correct_birth",)),
    OperationSpec("set_parents", ("set_parents",)),
    OperationSpec("set_nicknames", ("set_nicknames",)),
)

OPERATION_CONTRACT: dict[str, OperationSpec] = {o.action: o for o in _OPERATIONS}

#: Every ``given`` step needs this, whatever the entity term.
GIVEN_METHOD: str = "create_asset"


def probe_for(assertion: str) -> ProbeSpec | None:
    """The probe that answers a glossary assertion term (``None`` if unknown)."""
    return PROBE_CONTRACT.get(assertion)


def methods_for_probe(assertion: str) -> tuple[str, ...]:
    """Adapter methods a given assertion term requires (empty if unknown)."""
    spec = PROBE_CONTRACT.get(assertion)
    return (spec.method,) if spec else ()


def methods_for_action(action: str, *, timed: bool = False) -> tuple[str, ...]:
    """Adapter methods a ``when`` step of ``action`` requires.

    ``timed`` is True when the step carries an effective time, which for some
    actions (``record_log``) means an extra restatement call.
    """
    spec = OPERATION_CONTRACT.get(action)
    if spec is None:
        return ()
    return spec.methods + (spec.methods_when_timed if timed else ())


def contract_gaps() -> list[str]:
    """Terms in the glossary with no binding here (a contract hole, not a port's).

    The vocabulary is closed and this table must cover it exactly. Anything
    reported here means a fixture could be written that no implementation could
    ever be asked to answer — a defect in this module, caught by its own test.
    """
    gaps = [
        f"assertion term {t!r} has no probe binding"
        for t in sorted(glossary.ASSERTION_TERMS)
        if t not in PROBE_CONTRACT
    ]
    gaps += [
        f"action term {t!r} has no operation binding"
        for t in sorted(glossary.ACTION_TERMS)
        if t not in OPERATION_CONTRACT
    ]
    gaps += [
        f"probe {t!r} is not a glossary assertion term"
        for t in sorted(PROBE_CONTRACT)
        if t not in glossary.ASSERTION_TERMS
    ]
    gaps += [
        f"operation {t!r} is not a glossary action term"
        for t in sorted(OPERATION_CONTRACT)
        if t not in glossary.ACTION_TERMS
    ]
    return gaps
