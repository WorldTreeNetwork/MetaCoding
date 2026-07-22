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

import json
from dataclasses import dataclass, field

from blake3 import blake3

from ctkr.oracle import glossary

# --------------------------------------------------------------------------- #
# INVARIANT 1 — every value declares its authority                             #
# --------------------------------------------------------------------------- #
#: The source system STATES this value at its published interface. Reading it is
#: transcription: there is no place for us to be wrong about the semantics,
#: only about the transport.
BOUNDARY = "boundary"
#: WE compute this value — an adapter query, a fold, an inference over what the
#: boundary delivered. A derived value carries our beliefs about the source's
#: semantics, and a belief is not evidence until it is validated against the
#: source's OWN authority (its published service/module code, or a documented
#: behaviour of the source). `group_member` is the proof this matters: a
#: hand-written "latest done assignment wins" query stood in for farmOS's
#: GroupMembership.php, which recurses by default and gates on effective time,
#: and the judge consequently ranked a port that MATCHED farmOS below one that
#: diverged from it.
DERIVED = "derived"

AUTHORITIES: frozenset[str] = frozenset({BOUNDARY, DERIVED})


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
    subject_kind: str = "entity"  # "entity" | "event" | "attempt"
    #: This probe returns an INSTANT. Such a probe cannot appear in a flow whose
    #: effective times are relative offsets: the recorded value is an absolute
    #: instant computed from the recording run's wall clock, so re-running the
    #: fixture minutes later reads a different one and it cannot self-verify.
    #: (MetaCoding-bdy — w0b first self-verified at 63.6%, every failure a uniform
    #: +24s, the gap between the record run and the verify run.)
    returns_timestamp: bool = False
    doc: str = ""

    # ---- INVARIANT 1: authority ------------------------------------------- #
    #: :data:`BOUNDARY` or :data:`DERIVED`. There is no third option and no
    #: default: a probe added without stating its authority fails
    #: :func:`contract_gaps`, which the test suite runs.
    authority: str = ""
    #: For a DERIVED probe: the SOURCE's own authority this derivation was
    #: validated against — its module/service code, or a documented behaviour.
    #: Empty means the derivation is our unvalidated belief, and a value produced
    #: by it is **not evidence**: it can never score an implementation.
    validated_against: str = ""
    #: What we compute, in one sentence. Hashed into :attr:`derivation_id`, so
    #: changing the derivation invalidates every fixture recorded under the old
    #: one instead of silently re-labelling old values as current.
    derivation: str = ""

    @property
    def is_evidence(self) -> bool:
        """Whether a value from this probe may SCORE an implementation.

        A boundary value always may. A derived value may only once its
        derivation is validated against the source's own authority. This is the
        structural form of invariant 1 — not a check that runs somewhere, but
        the gate every scoring path passes through.
        """
        return self.authority == BOUNDARY or bool(self.validated_against)

    @property
    def derivation_id(self) -> str:
        """Content id of this probe's derivation — empty for a boundary probe.

        A recorded fixture stamps the derivation_id of every derived probe it
        used. When we CHANGE a derivation (as `group_member` was changed to
        recurse and to gate on effective time), every fixture recorded under the
        old id no longer matches and is marked INVALID at load. Corrections
        cannot quietly bless stale values.
        """
        if self.authority != DERIVED:
            return ""
        canonical = json.dumps(
            {"assertion": self.assertion, "derivation": self.derivation,
             "validated_against": self.validated_against},
            sort_keys=True,
        )
        return blake3(canonical.encode("utf-8")).hexdigest()[:16]

    @property
    def unvalidated_reason(self) -> str:
        """Why this probe's values are not evidence, or ``""`` when they are."""
        if self.is_evidence:
            return ""
        return (
            f"{self.assertion!r} is a DERIVED value: {self.derivation or 'computed by adapter logic'}. "
            f"No validation against the source's own authority is recorded, so it "
            f"states OUR belief about the source, not the source's answer. "
            f"NO VERDICT."
        )


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
#: The published-index derivation shared by every probe that folds over the
#: source's log collections. What makes it validated rather than a belief: the
#: BUNDLE SET is read from farmOS's own `/api` resource index, not chosen by us.
#: An adapter-chosen enumeration is exactly the `group_member` defect one level
#: up — the hard-coded five-kind list silently omitted `birth`.
_INDEXED = (
    "the log-bundle set is read from the source's own /api resource index; "
    "the fold is over exactly the rows the boundary returns for the "
    "boundary-published filter, with no adapter-chosen predicate"
)

_PROBES: tuple[ProbeSpec, ...] = (
    ProbeSpec("yield_total", "asset_yield_total",
              (Param("measure"), Param("unit")),
              doc="Σ of a measure across recorded logs against an asset.",
              authority=DERIVED,
              derivation="Σ of the boundary-delivered quantity values whose "
                         "measure and units.name match, over every log bundle "
                         "the source's own index publishes",
              validated_against=_INDEXED),
    ProbeSpec("log_status", "log_status", (), subject_kind="event",
              doc="The lifecycle status delivered for a recorded event.",
              authority=BOUNDARY),
    ProbeSpec("log_count", "log_count", (Param("kind"),),
              doc="How many logs of a kind reference an asset.",
              authority=DERIVED,
              derivation="cardinality of the collection the boundary returns "
                         "for its published filter[asset.id] on one bundle",
              validated_against="JSON:API states the membership of the "
                                "collection; |collection| adds no semantics"),
    ProbeSpec("asset_active", "asset_active", (),
              doc="Whether an asset is in the active set.",
              authority=BOUNDARY),
    ProbeSpec("group_member", "group_member", (Param("group", "group"),),
              doc="Whether an asset is a member of a group.",
              authority=DERIVED,
              derivation="walk the asset's membership chain upward: at each "
                         "step the group of the newest done group-assignment "
                         "log whose effective time is not in the future, "
                         "tie-broken by the larger internal id; the asset is a "
                         "member of every group on that chain (recursive)",
              validated_against=(
                  "farmOS asset/group/src/GroupMembership.php — "
                  "getGroupMembers(array $groups, bool $recurse = TRUE, "
                  "$timestamp = NULL): recursion is the DEFAULT and the query "
                  "gates on lfd.timestamp <= :timestamp, tie-breaking on "
                  "lfd2.timestamp = lfd.timestamp AND lfd2.id > lfd.id"
              )),
    ProbeSpec("quantity_recorded", "quantity_recorded",
              (Param("measure"), Param("unit")), subject_kind="event",
              doc="A measured value recorded on one specific event.",
              authority=DERIVED,
              derivation="Σ of the quantities the boundary itself delivers as "
                         "this log's `included` set, filtered on the "
                         "boundary-stated measure and units.name",
              validated_against="the quantity set is stated by the source for "
                                "this one log; the fold adds no membership rule"),
    ProbeSpec("stock_on_hand", "stock_on_hand", (Param("measure"), Param("unit")),
              doc="Running stock for one (measure, unit) pair.",
              authority=DERIVED,
              derivation="row lookup in the `inventory` array the source itself "
                         "computes and delivers on the asset; an absent pair "
                         "reads 0.0",
              validated_against="farmOS computes and publishes the inventory "
                                "rows; the absent-pair 0.0 is distinguished "
                                "from a delivered zero by stock_pair_count"),
    ProbeSpec("stock_pair_count", "stock_pair_count", (),
              doc="How many (measure, unit) pairs report stock.",
              authority=DERIVED,
              derivation="cardinality of the source-computed `inventory` array",
              validated_against="the array is stated by the source; |array| "
                                "adds no semantics"),
    ProbeSpec("adjustment_count", "adjustment_count", (),
              doc="How many stock adjustments are readable against an asset.",
              authority=DERIVED,
              derivation="cardinality of the union, over every log bundle the "
                         "source's own index publishes, of the collections the "
                         "boundary returns for filter[quantity.inventory_asset.id]",
              validated_against=_INDEXED),
    ProbeSpec("animal_sex", "animal_sex", (),
              doc="The sex delivered for an animal.", authority=BOUNDARY),
    ProbeSpec("nicknames", "nicknames", (),
              doc="The ordered informal names delivered for an animal.",
              authority=BOUNDARY),
    ProbeSpec("birth_date", "birth_date", (), returns_timestamp=True,
              doc="The date of birth delivered for an animal.",
              authority=BOUNDARY),
    ProbeSpec("parent_count", "parent_count", (),
              doc="How many parents an animal is delivered with.",
              authority=DERIVED,
              derivation="cardinality of the `parent` relationship the boundary "
                         "delivers on the animal",
              validated_against="the relationship is stated by the source; "
                                "|relationship| adds no semantics"),
    ProbeSpec("has_parent", "has_parent", (Param("other", "animal"),),
              doc="Whether one animal is delivered as another's parent.",
              authority=DERIVED,
              derivation="membership in the `parent` relationship the boundary "
                         "delivers on the animal",
              validated_against="the relationship is stated by the source; "
                                "membership adds no semantics"),
    ProbeSpec("birth_record_count", "birth_record_count", (),
              doc="How many birth records claim an animal as issue.",
              authority=DERIVED,
              derivation="cardinality of the collection the boundary returns "
                         "for its published filter[asset.id] on log--birth",
              validated_against="JSON:API states the membership of the "
                                "collection; |collection| adds no semantics"),
    # Answered by the ATTEMPT itself: there is no method to call, because the
    # value IS whether the `when` was refused. Bound here so the vocabulary stays
    # closed (contract_gaps covers glossary and table against each other), and
    # flagged so no dispatcher tries to invoke an empty method name.
    # Authority is BOUNDARY in the strongest sense available: the source stated
    # "you may not do that" at its own interface, in its own words.
    ProbeSpec("refused", "", (), subject_kind="attempt", authority=BOUNDARY,
              doc="Whether the system REFUSED the attempted write. A refusal is a "
                  "delivered semantic ('this animal already has a birth log'), not "
                  "an absence of one."),
    # --- generated by `ctkr add-term` (PROVISIONAL until bind-term) ----- #
    # DERIVED with no validated_against ON PURPOSE: the derivation below is
    # the spec's proposed semantics, which no source authority has validated
    # yet — so is_evidence is False and values cannot score until it is.
    ProbeSpec('lot_number', 'lot_number', (), subject_kind="event",
              doc='The identifying number of the lot or batch to which a recorded harvest, input, or seeding belongs.',
              authority=DERIVED,
              derivation='Deliver the recorded lot number value for the subject record, or no value when no lot number was recorded.'),
    # --- generated by `ctkr add-term` (PROVISIONAL until bind-term) ----- #
    # DERIVED with no validated_against ON PURPOSE: the derivation below is
    # the spec's proposed semantics, which no source authority has validated
    # yet — so is_evidence is False and values cannot score until it is.
    ProbeSpec('material_quantity', 'material_quantity', (), subject_kind="event",
              doc='A measured quantity classified as material in a farm record.',
              authority=DERIVED,
              derivation='Delivers the classification value of the measured quantity recorded on the log, so an assertion can determine whether that quantity is material.'),
    # --- generated by `ctkr add-term` (PROVISIONAL until bind-term) ----- #
    # DERIVED with no validated_against ON PURPOSE: the derivation below is
    # the spec's proposed semantics, which no source authority has validated
    # yet — so is_evidence is False and values cannot score until it is.
    # Shaped like has_parent (an `other` animal param, boolean delivery): the
    # subject is a birth LOG (subject_kind="event") and the value delivered is
    # whether `other` is the recorded mother — the reproducible, scorable form
    # for an entity reference. A raw per-run asset UUID could never reproduce.
    ProbeSpec('birth_mother', 'birth_mother', (Param("other", "animal"),),
              subject_kind="event",
              doc='The mother recorded for a birth. It identifies the animal recognized as the dam of the newborn in that birth.',
              authority=DERIVED,
              derivation='Deliver whether a given animal is the one recorded as the mother on the birth log, so an assertion can confirm the recorded dam against an expected animal.'),
    # --- generated by `ctkr add-term` (PROVISIONAL until bind-term) ----- #
    # DERIVED with no validated_against ON PURPOSE: the derivation below is
    # the spec's proposed semantics, which no source authority has validated
    # yet — so is_evidence is False and values cannot score until it is.
    ProbeSpec('equipment_used', 'equipment_used', (Param('other', 'equipment'),), subject_kind="event",
              doc='Whether a given equipment asset is recorded as equipment used on a log.',
              authority=DERIVED,
              derivation="Deliver whether a given equipment asset is among the equipment the subject log records as used, so an assertion can confirm the recorded 'Equipment used' reference against an expected asset."),
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
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    OperationSpec('delete_log', ('delete_log',),
                  doc='Delete a recorded log, removing it from the source together with the quantities it owns.'),
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    OperationSpec('delete_quantity', ('delete_quantity',),
                  doc='Delete a recorded quantity, removing a single measurement from the source.'),
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
    # INVARIANT 1 is a property of the TABLE, not of a review: a probe that does
    # not state its authority is a hole here, in the module's own test.
    for t in sorted(PROBE_CONTRACT):
        spec = PROBE_CONTRACT[t]
        if spec.authority not in AUTHORITIES:
            gaps.append(
                f"probe {t!r} declares authority {spec.authority!r}: every value "
                f"must declare {BOUNDARY!r} or {DERIVED!r}"
            )
        if spec.authority == DERIVED and not spec.derivation:
            gaps.append(f"derived probe {t!r} does not say what it computes")
        if spec.authority == BOUNDARY and (spec.derivation or spec.validated_against):
            gaps.append(
                f"probe {t!r} claims boundary authority but describes a "
                f"derivation — a transcribed value has nothing to validate"
            )
    return gaps


def current_derivations() -> dict[str, str]:
    """``{assertion: derivation_id}`` for every DERIVED probe, as of this table.

    Stamped into a recorded pack's provenance. A pack whose stamp disagrees with
    this map was recorded under a derivation we have since changed, and its
    values are stale by construction — see :mod:`ctkr.oracle.pack`.
    """
    return {
        t: s.derivation_id
        for t, s in PROBE_CONTRACT.items()
        if s.authority == DERIVED
    }


def unvalidated_probes() -> list[str]:
    """Probes whose values are NOT evidence — derived, with no source authority."""
    return sorted(t for t, s in PROBE_CONTRACT.items() if not s.is_evidence)
