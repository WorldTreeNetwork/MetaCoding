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
    }
)

# --- Action terms: the domain verbs a `when` step may perform. --------------
ACTION_TERMS: frozenset[str] = frozenset(
    {
        "record_log",  # record an observation/activity/harvest/input/seeding
        "set_log_status",  # transition a recorded log pending -> done (or back)
        "assign_to_group",  # place an asset into a group (membership)
        "archive_asset",  # retire an asset from the active set
    }
)

# --- Log kinds: the domain sub-type of a recorded event. --------------------
LOG_KINDS: frozenset[str] = frozenset(
    {"harvest", "input", "activity", "observation", "seeding"}
)

# --- Log status: the value-level lifecycle of a recorded event. -------------
LOG_STATUSES: frozenset[str] = frozenset({"pending", "done"})

# --- Measures: what a quantity measures (glossary, not a field name). -------
MEASURES: frozenset[str] = frozenset(
    {"weight", "count", "volume", "length", "area", "ratio", "temperature", "time"}
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
    )
