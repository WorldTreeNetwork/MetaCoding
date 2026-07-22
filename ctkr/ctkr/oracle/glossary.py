"""Domain glossary for the value-equivalence oracle (port-loop Phase 2, D4).

The oracle's whole discipline is that a semantic fixture speaks in **domain
vocabulary**, never in a data model. This module fixes that vocabulary as a
small, closed, implementation-independent set of terms — the language a fixture
is allowed to use — plus the *forbidden* representation vocabulary a lint rejects
(table names, column names, ids, storage primitives).

Nothing here maps a term to any implementation: the mapping from ``harvest log``
→ a farmOS ``log--harvest`` resource lives entirely in the adapter
(:mod:`ctkr.oracle.farmos_adapter`), *below* the value line. A second
implementation supplies a second adapter with a different mapping; the glossary
and the fixtures do not move. That is the point of Phase 2.

Terms are grouped by role so the fixture validator can check that a term is used
in a position that role allows (an ``entity`` term in ``given``, an ``action``
term in ``when``, an ``assertion`` term in ``then``). The grouping is derived
from ``decomposition-schema.md`` §5 (behavioral scenarios, value-level rule) and
the farmOS worked instantiation (§11): asset / log / quantity / group are the
heart of the farmOS model the Phase 4 vertical slice targets.
"""

from __future__ import annotations

# --- Entity terms: the domain nouns a `given` step may instantiate. ---------
# Deliberately the farmOS core asset vocabulary (asset ≈ a thing the farm
# tracks). Each maps, per implementation, to a concrete resource below the line;
# here it is just "a land asset", "an animal", "a group".
ENTITY_TERMS: frozenset[str] = frozenset(
    {
        "land",  # a parcel / field / paddock
        "animal",  # a tracked animal
        "planting",  # a plant asset (crop / bed)
        "structure",  # a building / greenhouse
        "equipment",  # a tool / machine
        "group",  # a membership grouping of assets
        "material",  # A material asset: a stock of some substance (compost, fertilizer, s… [PROVISIONAL]
    }
)

# --- Action terms: the domain verbs a `when` step may perform. --------------
ACTION_TERMS: frozenset[str] = frozenset(
    {
        "record_log",  # record an observation/activity/harvest/input/seeding
        "set_log_status",  # transition a recorded log pending -> done (or back)
        "assign_to_group",  # place an asset into a group (membership)
        "archive_asset",  # retire an asset from the active set
        # --- stock / inventory (w0a) ---------------------------------------
        "record_inventory_adjustment",  # increment/decrement/reset an asset's stock
        "set_effective_time",  # restate WHEN a recorded event took effect
        # --- lineage (w0b) --------------------------------------------------
        "record_birth",  # register the birth of an animal, optionally from a parent
        "correct_birth",  # restate an already-recorded birth (time and/or parent)
        "set_parents",  # state an animal's parentage directly
        "set_nicknames",  # state an animal's ordered list of informal names
        "delete_log",  # Delete a recorded log, removing it from the source together with th… [PROVISIONAL]
        "delete_quantity",  # Delete a recorded quantity, removing a single measurement from the … [PROVISIONAL]
    }
)

# --- Log kinds: the domain sub-type of a recorded event. --------------------
LOG_KINDS: frozenset[str] = frozenset(
    {"harvest", "input", "activity", "observation", "seeding", "birth"}
)

# --- Adjustment kinds: how a stock adjustment acts on the running total. ----
# ``increment``/``decrement`` accumulate; ``reset`` assigns a new base.
ADJUSTMENT_KINDS: frozenset[str] = frozenset({"increment", "decrement", "reset"})

# --- Animal sexes: the closed domain vocabulary for an animal's sex. --------
ANIMAL_SEXES: frozenset[str] = frozenset({"F", "M"})

# --- Log status: the value-level lifecycle of a recorded event. -------------
# ``abandoned`` is farmOS's third lifecycle state (farm_log.workflows.yml:
# farm_log_workflow.states.abandoned), reachable from either ``pending`` or
# ``done``. It is added here as a VALUE in the existing closed set — the way a
# new MEASURE is added — so it is expressible in a flow (``set_log_status ->
# abandoned``) and observable in a pack (``log_status == "abandoned"``) through
# the SAME set_log_status action and log_status probe already in the contract;
# no new term, probe, or adapter method is required. Whether the kernel should
# treat ``abandoned`` as equivalent to ``not confirmed`` is a freeze-menu
# decision that belongs to Duke, not to this glossary — see MetaCoding-io6.
LOG_STATUSES: frozenset[str] = frozenset({"pending", "done", "abandoned"})

# --- Measures: what a quantity measures (glossary, not a field name). -------
MEASURES: frozenset[str] = frozenset(
    {"weight", "count", "volume", "length", "area", "ratio", "temperature", "time"}
)

# --- Land descriptors: the closed vocabulary for a land asset's kind. --------
# farmOS's ``land_type`` option set (modules/asset/land/.../farm_land.land_type.*
# and Land.php:fields.land_type). Blessed here as the descriptor vocabulary a
# ``given`` land step may carry — the value flows in through GivenStep.descriptor
# and the adapter maps it onto ``land_type`` (an unrecognised descriptor still
# falls back to ``other`` in the adapter). Only the ``land`` entity is gated
# against this set (see fixtures.validate_fixture); every other entity's
# descriptor stays free text, so this addition constrains nothing that was legal
# before — no existing land fixture carries a descriptor at all.
LAND_TYPES: frozenset[str] = frozenset(
    {"bed", "field", "landmark", "other", "paddock", "property"}
)

# --- Assertion terms: the value predicates a `then` step may assert. --------
# Every one asserts a VALUE the system delivers — a total, a status, a count, a
# visibility, a membership — never a representation. This is the oracle's target
# list; the runner asks the adapter to evaluate each against the live boundary.
ASSERTION_TERMS: frozenset[str] = frozenset(
    {
        "yield_total",  # Σ of a measure across recorded logs against an asset
        "log_status",  # the lifecycle status delivered for a recorded log
        "log_count",  # how many logs of a kind reference an asset
        "asset_active",  # whether an asset is in the active (non-archived) set
        "group_member",  # whether an asset is a member of a group
        "quantity_recorded",  # a specific measured value recorded on a log
        # --- stock / inventory (w0a) ---------------------------------------
        "stock_on_hand",  # the running stock an asset currently holds, per
                          # (measure, unit) pair, after all effective adjustments
        "stock_pair_count",  # how many (measure, unit) pairs the asset reports
                             # stock for — surfaces pairs reported at zero
        "adjustment_count",  # how many stock adjustments are readable against
                             # an asset (the reduce INPUT, not its result)
        # --- lineage (w0b) --------------------------------------------------
        "animal_sex",  # the sex delivered for an animal
        "nicknames",  # the ordered list of informal names for an animal
        "birth_date",  # the date of birth delivered for an animal
        "parent_count",  # how many parents an animal is delivered with
        "has_parent",  # whether one animal is delivered as another's parent
        "birth_record_count",  # how many birth records claim an animal as issue
        # --- refusal (B3) ---------------------------------------------------
        "refused",  # whether the system REFUSED the attempted write. A refusal
                    # is a delivered answer, not an absence of one: "you may not
                    # record a second birth for this animal" is a semantic the
                    # boundary states. Answered by the ATTEMPT, not by a probe
                    # method — see probes.ProbeSpec.subject_kind == "attempt".
        "lot_number",  # The identifying number of the lot or batch to which a recorded harv… [PROVISIONAL]
        "material_quantity",  # A measured quantity classified as material in a farm record. [PROVISIONAL]
        "birth_mother",  # The mother recorded for a birth. It identifies the animal recognize… [PROVISIONAL]
        "equipment_used",  # Whether a given equipment asset is recorded as equipment used on a … [PROVISIONAL]
        "material_type_recorded",  # The material types recorded on a log's material quantity, as an ord… [PROVISIONAL]
    }
)

# --- Comparison operators an assertion may use. -----------------------------
COMPARISON_OPS: frozenset[str] = frozenset({"==", "!=", ">", ">=", "<", "<="})

# --- Forbidden representation vocabulary — the storage-leak lint (§5). -------
# A fixture that names any of these is a defect: it has smuggled a data model
# across the value line. Matched case-insensitively as substrings of any string
# VALUE in a fixture (not the schema keys, which are fixed by us).
FORBIDDEN_SUBSTRINGS: tuple[str, ...] = (
    "field_data_",
    "field_revision_",
    "entity_id",
    "revision_id",
    "->",  # PHP arrow / SQL join hint
    "select ",
    "insert into",
    "update ",
    "join ",
    "primary key",
    "foreign key",
    "autoincrement",
    "uuid",
    "nid",
    "vid",
    "tid",
    ".sql",
    "drupal",
    "jsonapi",
    "/api/",
)

# Whole-word forbidden tokens (matched as isolated words, so "table salt" in a
# domain name is fine but "table" as a storage term is caught only in the
# substring pass where it is unambiguous — kept out of the word list to avoid
# false positives on legitimate domain prose).
FORBIDDEN_WORDS: frozenset[str] = frozenset(
    {"table", "column", "schema", "database", "sql", "orm"}
)


def all_terms() -> frozenset[str]:
    """Every legal glossary term across all roles (for validator membership)."""
    return (
        ENTITY_TERMS
        | ACTION_TERMS
        | LOG_KINDS
        | LOG_STATUSES
        | MEASURES
        | ASSERTION_TERMS
        | ADJUSTMENT_KINDS
        | LAND_TYPES
    )
