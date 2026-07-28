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

#: The source's own current-location rule, shared by the two probes that must
#: FOLD it rather than read farmOS's published answer (the as-of read and the
#: fan-out). Stated once so the two cannot drift into disagreeing about what
#: they claim to reproduce.
_MOVEMENT_RULE = (
    "farmOS's own rule, read from AssetLocation.php: getMovementLog() takes the "
    "newest log with is_movement TRUE and status 'done' whose timestamp is <= "
    "the asked-for instant, tie-broken by the larger internal id, and "
    "getLocation() returns that log's location set — with a FIXED asset "
    "short-circuited to no location at all BEFORE any movement is considered. "
    "The fold reads the source's own inputs rather than reconstructing them: "
    "the boundary states is_movement, status, timestamp and the internal id on "
    "every log (validated live 2026-07-28), and the log-bundle set is read from "
    "the source's own /api resource index, never chosen here"
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
    # --- lot_number: authority validated (MetaCoding-spf) ---------------- #
    # Reclassified DERIVED -> BOUNDARY: a direct transcription of a
    # source-stated string attribute (the log_status shape). The field is
    # stated by the source on exactly three log bundles (farm_harvest
    # Harvest.php, farm_input Input.php, farm_seeding Seeding.php
    # buildFieldDefinitions, type 'string'; whole-tree grep confirms no
    # others) and delivered as the log's JSON:API lot_number attribute —
    # VALIDATED LIVE 2026-07-23: recorded 'spf-probe-LOT-A1' read back
    # identical; a log with none delivers attribute null, folded to "" (a
    # representation fold, not semantics). BOUNDARY means derivation_id is
    # "" so the sealed pack 0c77ca7d462e recorded before this refinement
    # stays VALID — no re-record.
    ProbeSpec('lot_number', 'lot_number', (), subject_kind="event",
              doc='The identifying number of the lot or batch to which a recorded harvest, input, or seeding belongs; a string the source states directly on exactly those three log bundles.',
              authority=BOUNDARY),
    # --- material_quantity: authority validated (MetaCoding-spf) --------- #
    # Stays DERIVED: there is a genuine SELECTION of ours (first quantity).
    # The derivation was tightened at validation time to DISCLOSE it — the
    # old text said "the measured quantity" (singular) while the adapter
    # returns the FIRST of possibly many, and any bundle (not only
    # 'material'). The rotation invalidates the pack recorded under the old
    # id — honestly re-recorded and re-bound, the plant_type precedent.
    ProbeSpec('material_quantity', 'material_quantity', (), subject_kind="event",
              doc='A measured quantity classified as material in a farm record.',
              authority=DERIVED,
              derivation="the classification (bundle) of the FIRST quantity "
                         "the subject log records, stripped of the "
                         "'quantity--' prefix ('material'/'standard'), or '' "
                         "when the log records none",
              validated_against="the quantity's classification is its BUNDLE, "
                                "stated by the source (farm_quantity_material "
                                "Material.php QuantityType id 'material' + "
                                "quantity.type.material.yml; "
                                "farm_quantity_standard Standard.php id "
                                "'standard'); JSON:API delivers the bundle as "
                                "the resource type 'quantity--{bundle}' "
                                "(validated live 2026-07-23: a "
                                "quantity--material read back type "
                                "'quantity--material', a quantity--standard "
                                "'quantity--standard'; a no-quantity log "
                                "delivers no included quantities -> ''). The "
                                "bundle VALUE adds no semantics of ours; the "
                                "FIRST-delivered-quantity SELECTION is ours "
                                "(quantities arrive in relationship order — "
                                "validated live with material+standard on one "
                                "log), an unambiguity convention sound only "
                                "while a flow carries at most one quantity "
                                "per subject log — exactly the "
                                "material_type_recorded 'first' punt"),
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
    # Validated the has_parent way (MetaCoding-1cv): the `equipment` reference
    # is stated by the source itself — FieldHooks.php entity_base_field_info
    # declares the multi-valued entity_reference base field (target
    # asset--equipment) on every log, and JSON:API delivers its membership as
    # the log's own `equipment` relationship. Membership of the expected asset
    # adds no semantics of ours.
    ProbeSpec('equipment_used', 'equipment_used', (Param('other', 'equipment'),), subject_kind="event",
              doc='Whether a given equipment asset is recorded as equipment used on a log.',
              authority=DERIVED,
              derivation="Deliver whether a given equipment asset is among the equipment the subject log records as used, so an assertion can confirm the recorded 'Equipment used' reference against an expected asset.",
              validated_against="the equipment reference is stated by the source "
                                "(farm_equipment FieldHooks.php base field; the "
                                "log's JSON:API equipment relationship); "
                                "membership adds no semantics"),
    # --- generated by `ctkr add-term` (PROVISIONAL until bind-term) ----- #
    # DERIVED with no validated_against ON PURPOSE: the derivation below is
    # the spec's proposed semantics, which no source authority has validated
    # yet — so is_evidence is False and values cannot score until it is.
    # Validated the has_parent way (MetaCoding-5ln): the material_type
    # reference on a material quantity is stated by the source itself
    # (farm_quantity_material Material.php bundleFieldDefinition) and each
    # term's name is the term's own stated attribute — the VALUES add no
    # semantics of ours. The "first material quantity of the log" SELECTION is
    # ours, though (distinct from the fold's reset()-first inventory asset,
    # which selects at a different level): it is an unambiguity convention,
    # sound only while flows carry at most one material quantity per log — a
    # multi-material-quantity flow would need the probe to say WHICH.
    # (Review finding on 74c499f: the two "firsts" are not the same thing.)
    ProbeSpec('material_type_recorded', 'material_type_recorded', (), subject_kind="event",
              doc="The material types recorded on a log's material quantity, as an ordered list of term names.",
              authority=DERIVED,
              derivation='Deliver the ordered material_type term names recorded on the first material-classified quantity of the subject log, or an empty list when the log carries no material quantity or the quantity records no material type — the observable of the…',
              validated_against="the material_type reference is stated by the "
                                "source (farm_quantity_material Material.php "
                                "bundle field; each term's own stated name); "
                                "membership and name readback add no semantics"),
    # --- lab_test bundle-field probes (MetaCoding-wgy) ---------------------- #
    # add-term generates every probe DERIVED-with-no-validated_against (it
    # cannot know a term's authority). AUTHORITY REFINED post-generation, after
    # the derivation was validated against the live source (the 5ln/1cv step):
    # four of these read a field the source STATES on the log at its published
    # interface (a list_string, two timestamps, a string) — BOUNDARY
    # transcription, nothing of ours to validate. Two follow a source-stated
    # reference to a term's own stated NAME — DERIVED, validated the
    # material_type_recorded / has_parent way. All six stay PROVISIONAL (the
    # provenance registry) until a sealed recording binds them; the authority
    # here is what makes a BOUND value scorable rather than NO VERDICT.
    ProbeSpec('lab_sample_type', 'lab_sample_type', (), subject_kind="event",
              doc='The laboratory specimen category recorded on a lab test log, such as soil, tissue, or water.',
              authority=BOUNDARY),
    ProbeSpec('laboratory', 'laboratory', (), subject_kind="event",
              doc='The laboratory that performed a recorded laboratory test.',
              authority=DERIVED,
              derivation="the NAME of the term the log's single-valued `lab` "
                         "entity_reference points to; '' when the log records none",
              validated_against="the lab reference is stated by the source "
                                "(farm_lab_test LabTestLog.php fields.lab, target "
                                "taxonomy_term--lab; the log's JSON:API lab "
                                "relationship) and the name is the term's own "
                                "stated attribute — the reference-follow and name "
                                "readback add no semantics"),
    ProbeSpec('lab_test_measurement', 'lab_test_measurement', (), subject_kind="event",
              doc="The testing methods recorded on a lab test's measurement quantity, as an ordered list of term names.",
              authority=DERIVED,
              derivation="the ordered `test_method` term NAMES on the FIRST "
                         "quantity--test of the log; [] when the log carries no "
                         "test quantity or it records no method",
              validated_against="the test_method reference is stated by the "
                                "source (farm_quantity_test TestQuantity.php "
                                "fields.test_method, target "
                                "taxonomy_term--test_method; the quantity's "
                                "JSON:API test_method relationship) and each "
                                "term's name is its own stated attribute; the "
                                "'first test quantity' SELECTION is ours, sound "
                                "while a flow carries at most one (the "
                                "material_type_recorded 'two firsts' caveat)"),
    ProbeSpec('lab_processing_date', 'lab_processing_date', (), subject_kind="event",
              doc='The date on which a laboratory processed a sample for a lab test.',
              authority=BOUNDARY),
    ProbeSpec('sample_received_date', 'sample_received_date', (), subject_kind="event",
              doc='The date on which a laboratory received a sample for a lab test.',
              authority=BOUNDARY),
    ProbeSpec('soil_texture', 'soil_texture', (), subject_kind="event",
              doc='The soil texture reported by a laboratory test.',
              authority=BOUNDARY),
    # add-term generates every probe DERIVED-with-no-validated_against (it cannot
    # know a term's authority). AUTHORITY REFINED post-generation, after the
    # derivation was validated against the live source (the 5ln/1cv/wgy step,
    # missed on the first plant_type pass — see the recipe note): the two day
    # counts read an integer field the source STATES directly on the term at its
    # published interface — BOUNDARY transcription, nothing of ours to validate,
    # exactly the soil_texture/lab_processing_date form. The two references
    # follow a source-stated reference to a term's own stated NAME — DERIVED,
    # validated the laboratory / lab_test_measurement way. All four stay
    # PROVISIONAL (the provenance registry) until a sealed recording binds them;
    # the authority here is what makes a BOUND value scorable rather than NO
    # VERDICT. (Refining authority changes each fixture's authority/derivation
    # stamp, so the pack was RE-RECORDED and RE-BOUND against the refined
    # contract — a correction cannot retroactively bless the old stamps.)
    ProbeSpec('days_to_maturity', 'days_to_maturity', (),
              doc='The number of days a plant type is expected to take to reach maturity, recorded on the plant_type term.',
              authority=BOUNDARY),
    ProbeSpec('days_to_harvest', 'days_to_harvest', (),
              doc="The expected number of days a plant type stays in harvest, recorded on the plant_type term (farmOS label 'Days of harvest').",
              authority=BOUNDARY),
    ProbeSpec('companion_plants', 'companion_plants', (),
              doc='The plant types recorded as companions of a plant type, held on the plant_type term as a multi-valued reference to other plant_type terms.',
              authority=DERIVED,
              derivation="the ordered NAMES of the plant_type terms the term's "
                         "multi-valued `companions` entity_reference points to, in "
                         "the source's stated relationship order; [] when the term "
                         "records none",
              validated_against="the companions reference is stated by the source "
                                "(farm_plant_type "
                                "field.field.taxonomy_term.plant_type.companions.yml, "
                                "target taxonomy_term--plant_type, cardinality -1; "
                                "the term's JSON:API companions relationship) and "
                                "each name is the referenced term's own stated "
                                "attribute; the ORDER is the source's stated "
                                "relationship order (validated live: delivered as a "
                                "JSON array). The reference-follow, name readback, "
                                "and order preservation add no semantics; unlike "
                                "lab_test_measurement there is NO 'first' SELECTION — "
                                "the value is ALL companions, so no selection punt"),
    ProbeSpec('crop_family', 'crop_family', (),
              doc='The crop family a plant type is a member of, recorded on the plant_type term as a single-valued reference to a crop_family term.',
              authority=DERIVED,
              derivation="the NAME of the term the plant_type term's single-valued "
                         "`crop_family` entity_reference points to; '' when the term "
                         "records none",
              validated_against="the crop_family reference is stated by the source "
                                "(farm_plant_type "
                                "field.field.taxonomy_term.plant_type.crop_family.yml, "
                                "target taxonomy_term--crop_family, cardinality 1; "
                                "the term's JSON:API crop_family relationship) and "
                                "the name is the referenced term's own stated "
                                "attribute — the reference-follow and name readback "
                                "add no semantics; the reference is single-valued "
                                "(validated live: delivered as one object, not a "
                                "list)"),
    # --- sensor asset bundle fields (MetaCoding-ej0) -------------------- #
    # Authority refined BEFORE the first recording (the e6p lesson: a BOUND
    # term whose ProbeSpec cannot score is a skipped refinement).
    ProbeSpec('sensor_data_stream', 'sensor_data_stream', (),
              doc='The data streams provided by a sensor, recorded on the sensor asset as an ordered multi-valued reference to data_stream entities.',
              authority=DERIVED,
              derivation="the ordered NAMES of the data_stream entities the "
                         "asset's multi-valued `data_stream` entity_reference "
                         "points to, in the source's stated relationship order; "
                         "[] when the asset records none",
              validated_against="the data_stream reference is stated by the "
                                "source (farm_sensor Sensor.php "
                                "buildFieldDefinitions fields.data_stream, "
                                "entity_reference -> data_stream, multiple TRUE; "
                                "the asset's JSON:API data_stream relationship) "
                                "and each name is the referenced stream's own "
                                "stated attribute; the ORDER is the source's "
                                "stated relationship order (validated live "
                                "2026-07-23: two streams referenced b,a read "
                                "back in exactly that order; no streams "
                                "delivered data:[]). The reference-follow, name "
                                "readback, and order preservation add no "
                                "semantics; the value is ALL streams, so no "
                                "selection punt (the companion_plants form)"),
    ProbeSpec('sensor_private_key', 'sensor_private_key', (),
              doc="The private key of a sensor, recorded on the sensor asset "
                  "as a string; the source STATES it directly at its published "
                  "interface — BOUNDARY transcription. Only explicitly-recorded "
                  "keys are scoreable: an unstated key is oracle-minted per "
                  "instance (DataStream::createUniqueKey — validated live "
                  "2026-07-23) and can never reproduce, so fixtures asserting "
                  "on it always state it.",
              authority=BOUNDARY),
    ProbeSpec('publicly_readable', 'publicly_readable', (),
              doc="Whether data from a sensor may be read publicly without its "
                  "private key; a boolean the source STATES directly on the "
                  "asset at its published interface — BOUNDARY transcription. "
                  "true reads true, false reads false (a recorded value, "
                  "distinct from absent); an unstated flag delivers null at "
                  "the boundary, NOT the entity-level default false (validated "
                  "live 2026-07-23), read back as the empty value.",
              authority=BOUNDARY),
    # --- structure_kind (MetaCoding-xq7) -------------------------------- #
    # Authority refined BEFORE the first recording (the e6p lesson).
    ProbeSpec('structure_kind', 'structure_kind', (),
              doc="The designated kind of a structure (building, greenhouse, "
                  "other), recorded on the structure asset as a required "
                  "list_string from the closed structure_type vocabulary "
                  "(glossary.STRUCTURE_TYPES) and STATED by the source "
                  "directly at its published interface — BOUNDARY "
                  "transcription, machine id verbatim (validated live "
                  "2026-07-23: greenhouse/building/other each read back "
                  "identically; unknown 422s; absent 422s, so through the "
                  "given write surface — descriptor, falling back to 'other' "
                  "— the delivered value is never absent and there is no "
                  "empty-value contrast).",
              authority=BOUNDARY),
    # --- location surface: AUTHORITY REFINED post-generation ------------- #
    # add-term generates every probe DERIVED-with-no-validated_against (it
    # cannot know a term's authority). Refined here after each derivation was
    # validated against the live source — the 5ln/1cv/wgy/ej0 step, and the
    # one the e6p lesson says must happen BEFORE the first recording, since a
    # BOUND term whose ProbeSpec cannot score is a skipped refinement.
    #
    # Three of the five read a field the source STATES on the asset at its
    # published interface (two booleans and a shape) — BOUNDARY transcription,
    # nothing of ours to validate. Two read the source's OWN COMPUTED answer to
    # the location question — DERIVED, because selecting out of a delivered
    # collection is a step, but validated: the rule is entirely farmOS's.
    #
    # What is NOT here, and why: `assets_at_location_count` — the same question
    # asked from the location's side. farmOS answers it only through
    # AssetLocation::getAssetsByLocation, a raw SQL query with no boundary
    # equivalent (validated live 2026-07-28: filter[location.id] 500s). A probe
    # for it would have to re-implement the rule instead of transcribing it,
    # which is the `group_member` defect exactly. The semantic is observable
    # from the asset's side, which is what the pack does. Still open on
    # MetaCoding-b0s as the multi-asset fan-out gap.
    ProbeSpec('is_at_location', 'is_at_location', (Param('other', 'location'),),
              doc='Whether an asset is currently at a given location.',
              authority=DERIVED,
              derivation="membership of the expected location in the "
                         "`location` relationship the boundary delivers on "
                         "the asset",
              validated_against=("farmOS itself computes the whole current-location rule and PUBLISHES the answer: AssetLocation.php getMovementLog() takes the newest log with is_movement TRUE, status 'done' and timestamp <= now (tie-broken by the larger internal id) and getLocation() returns that log's location set, while a FIXED asset short-circuits to no location at all; AssetLocationItemList exposes it as the asset's own `location` relationship, which JSON:API delivers. The probe reads that relationship and adds no rule of its own (validated live 2026-07-28: a done movement placed the asset; a pending one did not; a future-dated one did not; a two-location movement delivered both; a fixed asset delivered none)" +
                                 "; membership adds no semantics — the "
                                 "has_parent form")),
    ProbeSpec('current_location_count', 'current_location_count', (),
              doc='How many locations an asset is currently reported to be at.',
              authority=DERIVED,
              derivation="cardinality of the `location` relationship the "
                         "boundary delivers on the asset",
              validated_against=("farmOS itself computes the whole current-location rule and PUBLISHES the answer: AssetLocation.php getMovementLog() takes the newest log with is_movement TRUE, status 'done' and timestamp <= now (tie-broken by the larger internal id) and getLocation() returns that log's location set, while a FIXED asset short-circuits to no location at all; AssetLocationItemList exposes it as the asset's own `location` relationship, which JSON:API delivers. The probe reads that relationship and adds no rule of its own (validated live 2026-07-28: a done movement placed the asset; a pending one did not; a future-dated one did not; a two-location movement delivered both; a fixed asset delivered none)" +
                                 "; |relationship| adds no semantics — the "
                                 "parent_count form")),
    ProbeSpec('current_geometry', 'current_geometry', (),
              doc="The shape on the ground an asset currently occupies, as "
                  "the source reports it — the `value` member, in well-known "
                  "text, of the geometry the source itself computes and "
                  "STATES on the asset. BOUNDARY transcription of that "
                  "member. The boundary delivers the shape inside an object "
                  "carrying farmOS's own readings OF it (geo_type, lat, lon, "
                  "a bounding box, a geohash); those are computed FROM the "
                  "shape and a port is not obliged to reproduce them, so the "
                  "probe takes the shape and drops the readings — a "
                  "representation fold, not semantics, the lot_number null "
                  "-> '' precedent. Validated live 2026-07-28: an asset moved "
                  "with geometry 'POINT (30 40)' read back exactly that, "
                  "while the PLACE it moved to delivered none — a movable "
                  "asset's shape comes from its movement, not from where it "
                  "went; a fixed asset delivered its own intrinsic shape.",
              authority=BOUNDARY),
    ProbeSpec('is_location', 'is_location', (),
              doc="Whether an asset may hold other assets — whether it is a "
                  "place things can be at. A boolean the source STATES "
                  "directly on the asset at its published interface "
                  "(farm_location, AssetLocation::ASSET_FIELD_LOCATION) — "
                  "BOUNDARY transcription. Validated live 2026-07-28: a land "
                  "asset delivers true and an animal false with neither "
                  "stated, so the per-entity DEFAULT is itself an observable.",
              authority=BOUNDARY),
    ProbeSpec('is_fixed', 'is_fixed', (),
              doc="Whether an asset stays put — whether it has a shape of its "
                  "own rather than one it acquires by being moved. A boolean "
                  "the source STATES directly on the asset "
                  "(AssetLocation::ASSET_FIELD_FIXED) — BOUNDARY "
                  "transcription. It is the switch the whole location surface "
                  "turns on: hasLocation/getLocation/getGeometry each "
                  "short-circuit on it (validated live 2026-07-28: a fixed "
                  "asset moved to a field reads back at NO location, keeping "
                  "its own shape).",
              authority=BOUNDARY),
    # --- the as-of read and the fan-out: AUTHORITY REFINED --------------- #
    # Both are DERIVED and both are OURS in a way the five location probes above
    # are not, which is why they are separate terms rather than parameters on
    # those. Above, farmOS computes the answer and publishes it; here it
    # publishes no answer at all, so we fold — and a fold of ours is not
    # evidence until it is validated against the source's own authority. That is
    # the `group_member` shape done deliberately, to avoid the `group_member`
    # DEFECT: a hand-written "latest done assignment wins" that silently stood
    # in for GroupMembership.php and got a CORRECT port ranked below a wrong one.
    ProbeSpec('was_at_location', 'was_at_location',
              (Param('other', 'location'), Param('as_of')),
              doc="Whether an asset was at a given location at a stated moment "
                  "— the as-of read. Separate from is_at_location because it is "
                  "a different question with a different AUTHORITY: farmOS "
                  "offers NO as-of read at its boundary (validated live "
                  "2026-07-28 — `?timestamp=` is not a boundary parameter and "
                  "the working copy still delivers the current location), so "
                  "where is_at_location transcribes the source's own computed "
                  "answer, this one computes it. One ProbeSpec carries one "
                  "authority; conflating them would have let a transcription "
                  "launder a derivation.",
              authority=DERIVED,
              derivation="the location set of the newest done movement log the "
                         "boundary delivers for the asset whose effective time "
                         "is not after the asked-for instant, tie-broken by the "
                         "larger internal id; empty for a fixed asset, and "
                         "empty when no such movement exists",
              validated_against=_MOVEMENT_RULE),
    ProbeSpec('assets_at_location_count', 'assets_at_location_count',
              (Param('as_of'),),
              doc="How many assets are at a location — the question asked from "
                  "the PLACE's side rather than the thing's, which is the "
                  "question a farm actually asks of a paddock. farmOS answers "
                  "it internally only through AssetLocation::getAssetsByLocation, "
                  "a raw SQL query with no boundary equivalent (validated live "
                  "2026-07-28: filter[location.id] returns 500), so the "
                  "enumeration is ours.",
              authority=DERIVED,
              derivation="cardinality of the set of assets, over every asset "
                         "bundle the source's own index publishes, whose "
                         "location includes the subject — each asset's location "
                         "taken from the source's own computed `location` "
                         "relationship, or from the movement fold when an "
                         "instant is asked for",
              validated_against=(
                  "the MEMBERSHIP is farmOS's, not ours, in both modes: with no "
                  "instant each asset's location is the relationship the source "
                  "COMPUTES and delivers on it, and with one it is the same fold "
                  "`was_at_location` uses — " + _MOVEMENT_RULE + ". Only the "
                  "ENUMERATION is ours, and its bundle set is read from the "
                  "source's own /api asset index rather than typed here (the "
                  "_INDEXED discipline; the hard-coded log list is what silently "
                  "omitted `birth`). Validated live 2026-07-28: two of three "
                  "animals moved to a field were exactly the two the fold "
                  "returned, and an untouched field returned none. KNOWN SCOPE: "
                  "it counts every asset the source publishes at the location, "
                  "including any a flow did not create — on a SHARED oracle that "
                  "is a real hazard, so a flow asking it uses a location no "
                  "other flow touches, which is a discipline of the pack rather "
                  "than a property of the probe"
              )),
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
    # generated by `ctkr add-term` (PROVISIONAL until bind-term)
    OperationSpec('move', ('move',),
                  doc='Move one or more assets to one or more locations: record a movement, the event that changes where an asset is.'),
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
