# Port brief — Log Type Plugin Registry

<!-- brief_digest=brief:119f4e0d454442cd66a661d9 card_id=card:64c2b0630e83a68fb6f01ffb prompt_version=port-brief:v1 fusion_model=claude-sonnet-4-6 -->
> Derived, regenerable view over the decomposition document set (subsystem `ss:761b7d53e7a231e2cf7a7782`, repo `farmos`). Not hand-edited. Every block is labeled **SHAPE** (checked structure), **INTENT** (read from names/tests — cites evidence), or **EVIDENCE** (raw).

**How to read this brief.** The majority of this subsystem is structurally clear — implement the shapes as described. Two areas demand evidence-reading: (1) the Views filter plugin (role:752cb704) is intention-critical; trust its named behavior (material-type subquery deduplication, array parameter handling) as the spec since the structure alone does not fully determine it. (2) role:7ae99936 (Maintenance log type) is ambiguous — its purpose is inferred from naming alone; flag for human confirmation before implementing. All other log-type plugin classes (Birth, Input, Seeding, Medical, Harvest, LabTest, etc.) follow the shared FarmLogType base pattern and can be implemented from structure.

**Purpose.** Defines and registers the family of farmOS log-entry type plugins (Birth, Input, Seeding, Medical, Harvest, LabTest, etc.) by providing a shared base class (FarmLogType) that all concrete log-type plugins extend, along with the supporting configuration-entity contract for lab-test types, validation constraints, hook implementations, and integration/functional tests that verify each log type behaves correctly within the broader entity system.

**Responsibilities.**
- Provide FarmLogType as the canonical base class that all log-type plugins extend, supplying string-translation support and shared plugin infrastructure
- Register concrete log-type plugins (Birth, Input, Seeding, Medical, Harvest, LabTest, etc.) via the #[LogType] attribute so the framework can discover them
- Define the FarmLabTestType configuration-entity interface and implementation for lab-test-specific log type metadata
- Enforce domain integrity rules via validation constraints (e.g. UniqueBirthLogConstraint ensures a child asset has at most one birth log)
- Implement framework hooks (theme, views, entity lifecycle) required by individual log types
- Provide kernel and functional tests that verify log-type behaviour, data synchronisation, and UI filter correctness

**Non-goals.**
- Does not own or manage log entity instances at runtime — only defines their types
- Does not implement the quick-form UI layer (consumed externally by quick/birth etc.)
- Does not provide generic entity storage or querying infrastructure

**Spec basis.** 100% structural / 0% nl-only. 
**Intention load.** structure-clear 71% · intention-critical 14% · ambiguous 14% — structure-clear elements: implement the SHAPE; intention-critical: the names/tests ARE the spec, read the EVIDENCE; ambiguous: flagged for review.

## Domain glossary

- **Log entry type** — A named category of log records (e.g., Birth, Input, Seeding, Medical, Harvest, LabTest, Maintenance) that determines how a log is validated, processed, and displayed within the farm management system.
- **LogType** — The plugin contract (interface + base class) that every concrete log entry type must satisfy to be discoverable and instantiable by the plugin registry.
- **FarmLogType** — The shared base implementation of the LogType contract from which all farm-domain log-type plugins inherit common behavior.
- **Plugin** — A modular, self-describing component registered with the system's plugin registry to extend core functionality without modifying it.
- **Birth log** — A log entry recording the birth event of an animal asset; subject to a uniqueness constraint (only one birth log per asset) and drives synchronization of the asset's date-of-birth from the log timestamp.
- **UniqueBirthLog constraint** — A validation rule that rejects any attempt to create more than one birth log referencing the same asset.
- **FarmLabTestType** — A configuration entity that classifies laboratory tests (e.g., soil, water, crop analysis) performable on farm samples; defines the contract that lab-test-type implementations must satisfy.
- **Pseudo field** — A computed, non-persisted attribute exposed for querying and filtering purposes, derived from related entity data at query time rather than stored in the database.
- **quantity_material_type** — A pseudo field on the log data table representing the material type associated with a logged quantity; used exclusively for filtering/querying logs by material category. _(convention — restated)_
- **LogQuantityMaterialType** — A views filter plugin that filters log records by material type, accepting array parameters and applying subquery logic to prevent duplicate results. _(convention — restated)_
- **Entity** — A persistent, identifiable domain object (e.g., a log record, an asset, a lab-test-type configuration) managed by the entity system.
- **Bundle field override** — A mechanism to alter the default field definition for a specific entity subtype (bundle) without changing the base field definition shared across all subtypes; used here to attach the UniqueBirthLog validation constraint to the asset field of birth logs. _(convention — restated)_
- **Bundle field info hook** — An extension point invoked by the entity system to allow modules to define or alter field metadata for a specific entity subtype; used here to attach validation constraints. _(convention — restated)_

## Interface contract

### `FarmLogType.php::FarmLogType`
- **SHAPE** — usage modes EXTENDS; 10 external caller(s) · load: structure-clear
- **INTENT** — Defines a base plugin interface for log entry type handlers that can be extended by domain-specific log types across the farm management system. [cites 2 signal(s)] Establishes a contract for log type plugins to be discovered and instantiated by the plugin system, enabling modular registration of custom log entry behaviors. _(convention — restated)_ [cites 21 signal(s)] Provides a standardized extension point for test modules and feature modules to define specialized log types (TestLog, Activity, Movement, LabTestLog) without modifying core logging infrastructure. [cites 21 signal(s)]
- **EVIDENCE** — _(none harvested)_
    - _(structure-clear — evidence elided by budget; implement the SHAPE)_

### Dependencies (consumes)
- `external::KernelTestBase` (external) via EXTENDS, IMPLEMENTS — Depends on (external package) via EXTENDS, IMPLEMENTS (8 crossing morphisms).

## Roles

### Mixed subsystem components _(role)_
- **SHAPE** — cardinality 70; invariance tier I; profile depth 1; interface participation: none · load: intention-critical
- **INTENT** — Provide a pseudo field on the log_field_data table that enables filtering logs by quantity material type, with filter logic to support material-type-based queries. [cites 2 signal(s)] Enforce a uniqueness constraint on the asset field of birth logs via entity bundle field info hooks, working around a Drupal core issue with BaseFieldOverride interaction. _(convention — restated)_ [cites 2 signal(s)] Support test scenarios that require authenticated users with appropriate permissions (asset view access, taxonomy access, log view access) to validate log entities and views. _(convention — restated)_ [cites 4 signal(s)] Implement filtering logic that accepts material type parameters as arrays and applies them to views queries via subqueries to prevent duplicate results. [cites 3 signal(s)]
  - ⚠ dissonance (name_incoherence): 70 members share this structural role but their names cohere weakly (top stem in 24% of members): FormHooks.php::Drupal\farm_lab_test\Hook, InputViewMaterialTypeTest.php::InputViewMaterialTypeTest::testMaterialTypeFilter, FarmLabTestType.php::FarmLabTestType::getLabel, FarmLabTestType.php::FarmLabTestType::label, UniqueBirthLogConstraintValidator.php::Drupal\farm_birth\Plugin\Validation\Constraint, BirthTest.php::BirthTest::testUniqueBirthLogConstraint
- **EVIDENCE** — _(none harvested)_
    - `S4/S` Add a quantity_material_type pseudo field to the log_field_data table. ⏎ This pseudo field only has a filter configured to support filtering logs ⏎ by the quantity material type. (modules/log/input/src/Hook/ViewsHooks.php:19-39)
    - `S4/S` Add a quantity_material_type pseudo field to the log_field_data table. ⏎ This pseudo field only has a filter configured to support filtering logs ⏎ by the quantity material type. (modules/log/input/src/Hook/ViewsHooks.php:4)
    - `S4/S` Add the UniqueBirthLog validation constraint to the asset field of birth ⏎ logs. We need to do this via hook_entity_bundle_field_info() instead of ⏎ hook_entity_field_info_alter() because this module also provides a ⏎ BaseFieldOverride for the asset field, and there is a Drupal core issue ⏎ that pr… (modules/log/birth/src/Hook/FieldHooks.php:18-33)
    - `S4/S` Add the UniqueBirthLog validation constraint to the asset field of birth ⏎ logs. We need to do this via hook_entity_bundle_field_info() instead of ⏎ hook_entity_field_info_alter() because this module also provides a ⏎ BaseFieldOverride for the asset field, and there is a Drupal core issue ⏎ that pr… (modules/log/birth/src/Hook/FieldHooks.php:4)
    - `S4/S` Create and login a user with access to view any asset and access ⏎ taxonomy terms. This is necessary to validate the log entities below, ⏎ because the entity module's query access handler enforces view access to ⏎ referenced entities during validation. (modules/log/birth/tests/src/Kernel/BirthTest.php:178-239)
    - `S4/S` Create and login a user with permission to view logs. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:34)
    - `S4/S` Create and login a user with permission to view logs. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:41)
    - `S4/S` Create and login a user with permission to view logs. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:55-114)
    - `S4/S` Filter to only include logs with the specified material type. ⏎ Make sure the parameter is an array. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:119-167)
    - `S4/S` If the log is not new, skip validation. ⏎ A birth log exits so there is no need to check if one can be created. (modules/log/birth/src/Plugin/Validation/Constraint/UniqueBirthLogConstraintValidator.php:4)
    - `S4/S` Sometimes $this->value is an array with a single element so convert it. ⏎ @see TaxonomyIndexTidDepth::query(). (modules/log/input/src/Plugin/views/filter/LogQuantityMaterialType.php:4)
    - `S4/S` Use the subquery in a condition on the views query to prevent duplicates. ⏎ PHPStan throws the following error on the next line: ⏎ Parameter #3 $value of method ⏎ Drupal\views\Plugin\views\query\Sql::addWhere() expects ⏎ array|string|null, Drupal\Core\Database\Query\SelectInterface given. ⏎ We igno… (modules/log/input/src/Plugin/views/filter/LogQuantityMaterialType.php:40-83)
    - `S4/S` [Group('farm')] ⏎ [RunTestsInSeparateProcesses] (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:4)
    - `A5/A` head *type (11/70); affixes=['test']; coherence_entropy=0.90 (modules/log/lab_test/src/Hook/FormHooks.php:)

### Test & hook implementer _(role)_
- **SHAPE** — cardinality 42; invariance tier I; profile depth 1; interface participation: consumes · load: structure-clear
- **INTENT** — Provide hook implementations that extend Drupal entity and field metadata to support log-based domain operations (birth tracking, material type filtering, transplanting workflows). _(convention — restated)_ [cites 4 signal(s)] Enforce validation constraints on log entities (e.g., uniqueness of birth logs per asset) through Drupal's constraint validator plugin system. _(convention — restated)_ [cites 2 signal(s)] Synchronize child asset state (date of birth) with log timestamps to maintain consistency between entity records and log events. [cites 1 signal(s)] Enable filtering and querying of logs by derived attributes (quantity material type) through Views integration without persisting those attributes to the database. _(convention — restated)_ [cites 2 signal(s)]
  - ⚠ dissonance (mixed-purpose grouping): Members include both test classes (BirthTest, InputViewMaterialTypeTest, FarmLabTestHelper) designed for validation and hook implementation classes (ThemeHooks, ViewsHooks, EntityHooks) designed for runtime behavior modification. Despite identical structural participation (consumes interface), they serve fundamentally different purposes: tests verify correctness while hooks extend framework behavior.
- **EVIDENCE** — _(none harvested)_
    - _(structure-clear — evidence elided by budget; implement the SHAPE)_

### Log type plugin _(role)_
- **SHAPE** — cardinality 7; invariance tier I; profile depth 1; interface participation: consumes · load: structure-clear
- **INTENT** — This role-class defines a plugin type for handling birth-event logging within a logging system. _(convention — restated)_ [cites 1 signal(s)]
  - ⚠ dissonance (name_incoherence): 7 members share this structural role but their names cohere weakly (top stem in 29% of members): Birth.php::Birth, Input.php::Input, Seeding.php::Seeding, Medical.php::Medical, UniqueBirthLogConstraint.php::UniqueBirthLogConstraint, Harvest.php::Harvest
- **EVIDENCE** — _(none harvested)_
    - _(structure-clear — evidence elided by budget; implement the SHAPE)_

### Log type plugin _(role)_
- **SHAPE** — cardinality 4; invariance tier I; profile depth 1; interface participation: none · load: ambiguous
- **INTENT** — This role-class defines a plugin type for handling maintenance-related logging events within a log management system. _(convention — restated)_ [cites 1 signal(s)]
  - ⚠ dissonance (name_incoherence): 4 members share this structural role but their names cohere weakly (top stem in 25% of members): Maintenance.php::Maintenance, Observation.php::Observation, Transplanting.php::Transplanting, Activity.php::Activity
- **EVIDENCE** — _(none harvested)_
    - `A5/A` head *maintenance (1/4); coherence_entropy=1.00 (modules/log/maintenance/src/Plugin/Log/LogType/Maintenance.php:)

### Log type base _(role)_
- **SHAPE** — cardinality 2; invariance tier I; profile depth 1; interface participation: consumes, provides · load: structure-clear
- **INTENT** — This role-class serves as a persistent structural anchor in the system, maintaining identity and state across operations. [cites 1 signal(s)]
  - ⚠ dissonance (name-purpose mismatch): FarmLogType is a concrete log type plugin class, while TaxonomyIndexTid appears to be a taxonomy reference field or index—fundamentally different purposes despite sharing structural equivalence in the role class. The grouping suggests they serve similar architectural roles (both provide/consume interfaces), but their semantic intent diverges significantly.
- **EVIDENCE** — _(none harvested)_
    - _(structure-clear — evidence elided by budget; implement the SHAPE)_

### Lab test type contract _(role)_
- **SHAPE** — cardinality 1; invariance tier I; profile depth 1; interface participation: consumes · load: structure-clear
- **INTENT** — Define a contract for farm laboratory test type entities, establishing the interface that implementations must satisfy to represent different categories of laboratory tests performed on farm samples. [cites 1 signal(s)]
- **EVIDENCE** — _(none harvested)_
    - _(structure-clear — evidence elided by budget; implement the SHAPE)_

## Composition laws & protocol

### Log type plugin inheritance **[boundary protocol op]**
- **SHAPE** — path, arity 1; roles role:81d68dbc024e348fdf3c8e1a → role:3b5724c1a2a7c9d03ad96e38; edges EXTENDS; support 6; laws: associative=True; violations=0; invariance tier I
- **INTENT** — Callers must extend the FarmLogType base class to implement custom log type plugins that integrate with the logging subsystem.

### Log type plugin extension **[boundary protocol op]**
- **SHAPE** — path, arity 1; roles role:7ae99936dac636c3e6b8ce94 → role:3b5724c1a2a7c9d03ad96e38; edges EXTENDS; support 4; laws: associative=True; violations=0; invariance tier I
- **INTENT** — Callers must extend the FarmLogType base class to register custom log type plugins (Maintenance, Observation, Transplanting, etc.).

## Data shapes

### `InputViewMaterialTypeTest.php::InputViewMaterialTypeTest`
- **SHAPE** — invariance tier A; data alphabet THIN: 0/5 data-edge kinds present (none); missing: TYPE_OF, RETURNS_TYPE, CONSTRUCTS, READS_FIELD, WRITES_FIELD; scip_fraction=0.0. Thin data_shapes for this lane read as extractor coverage, not an empty data model (§3).
- **INTENT** — A functional test class that validates material type filter functionality in input log views, containing test user credentials, material type taxonomy terms, and test log entities with various quantity configurations.
  - fields (SHAPE type/flow · INTENT meaning):
    - `materialTypes`: ? [internal]
    - `modules`: ? [internal]
    - `testLogs`: ? [internal]
    - `user`: ? [internal]
- **EVIDENCE** — _(none harvested)_
    - _(no evidence budgeted)_

### `FarmLabTestType.php::FarmLabTestType`
- **SHAPE** — invariance tier A; data alphabet THIN: 0/5 data-edge kinds present (none); missing: TYPE_OF, RETURNS_TYPE, CONSTRUCTS, READS_FIELD, WRITES_FIELD; scip_fraction=0.0. Thin data_shapes for this lane read as extractor coverage, not an empty data model (§3).
- **INTENT** — FarmLabTestType is a configuration entity that represents a laboratory test type, with an id field for the unique identifier and a label field for the human-readable name of the test type.
  - fields (SHAPE type/flow · INTENT meaning):
    - `id`: ? [internal]
    - `label`: ? [internal]
- **EVIDENCE** — _(none harvested)_
    - _(no evidence budgeted)_

### `BirthTest.php::BirthTest`
- **SHAPE** — invariance tier A; data alphabet THIN: 0/5 data-edge kinds present (none); missing: TYPE_OF, RETURNS_TYPE, CONSTRUCTS, READS_FIELD, WRITES_FIELD; scip_fraction=0.0. Thin data_shapes for this lane read as extractor coverage, not an empty data model (§3).
- **INTENT** — A kernel test class for farmOS birth log functionality that verifies birth log operations correctly synchronize data to child animal assets.
  - fields (SHAPE type/flow · INTENT meaning):
    - `modules`: ? [internal]
- **EVIDENCE** — _(none harvested)_
    - _(no evidence budgeted)_

### `UniqueBirthLogConstraint.php::UniqueBirthLogConstraint`
- **SHAPE** — invariance tier A; data alphabet THIN: 0/5 data-edge kinds present (none); missing: TYPE_OF, RETURNS_TYPE, CONSTRUCTS, READS_FIELD, WRITES_FIELD; scip_fraction=0.0. Thin data_shapes for this lane read as extractor coverage, not an empty data model (§3).
- **INTENT** — A validation constraint that ensures only one birth log can reference a given child asset, with a customizable violation message.
  - fields (SHAPE type/flow · INTENT meaning):
    - `message`: ? [internal]
- **EVIDENCE** — _(none harvested)_
    - _(no evidence budgeted)_

## Behavioral spec (acceptance list)

_The port's new test suite must cover these. Distilled from the original tests (S1); each scenario cites its source test._

### FarmLogType.php::FarmLogType (interface-export)
- **Log type plugin class can be instantiated** _[cites 11 test(s)]_
  - given A Log type plugin class is defined in a test module; when The plugin class is instantiated; then The instance is successfully created without errors
- **Log type plugin class implements required interface** _[cites 10 test(s)]_
  - given A Log type plugin class is defined; when The class is checked for interface compliance; then The class properly implements the Log type plugin interface

## Warnings

- ⚠ **port-critical** `role:3b5724c1a2a7c9d03ad96e38` — role:3b5724c1a2a7c9d03ad96e38 is marked 'tension': the structural identity of this role-class conflicts with or is underdetermined by its stated intent. The term 'tid' (described as a transaction/temporal identifier) does not align with any named domain concept in the rest of the subsystem. Do not implement until the element's actual domain role is confirmed.
  - _Trust structure for what it persists; treat the 'tid' name and 'transaction identifier' intent as unreliable — resolve against the broader entity schema before porting._
- ⚠ **port-critical** `role:81d68dbc024e348fdf3c8e1a, role:7ae99936dac636c3e6b8ce94` — role:81d68dbc024e348fdf3c8e1a (Birth log-type plugin) and role:7ae99936dac636c3e6b8ce94 (Maintenance log-type plugin) are both marked 'tension': their intent is inferred from naming alone and may not accurately describe their structural role.
  - _Trust the FarmLogType base-class pattern for structure; treat the specific event-category names (Birth, Maintenance) as correct only after cross-checking against the plugin annotation/discovery metadata in the source._
- ● intention-critical `role:70108211922ec388c82a9098, role:752cb704c83993c71bb4c6c2 — UniqueBirthLog constraint attachment` — The bundle-field-override / constraint-hook interaction (role:752cb704, role:70108211) is flagged as a workaround for a known platform bug. The correct attachment point for the UniqueBirthLog constraint is the bundle field info hook, NOT the base field definition — but this is non-obvious and may differ on the target stack.
  - _Verify that the target stack's equivalent of bundle-level field override does not silently drop validation constraints; if it does, attach the constraint directly at the bundle field info extension point instead._
- ● intention-critical `role:752cb704c83993c71bb4c6c2 — LogQuantityMaterialType filter plugin` — The LogQuantityMaterialType views filter (role:752cb704) uses a subquery strategy to prevent duplicate log results when filtering by material type. The structure alone does not specify the subquery shape, join conditions, or how array parameters are normalized before application.
  - _The names and test descriptions ARE the spec here: implement deduplication via subquery, accept material-type values as arrays, and validate against the functional tests that exercise array parameter paths._
- ? ambiguous `role:7ae99936dac636c3e6b8ce94` — role:7ae99936dac636c3e6b8ce94 (Maintenance log type) has no corroborating evidence beyond its name. It is unclear whether 'Maintenance' refers to farm-equipment maintenance, system/software maintenance, or another domain concept.
  - _Flag for human review. Do not infer domain semantics from the name alone; locate the plugin annotation or a test fixture that exercises this log type to confirm its intended category._

## Target adaptation notes

> **Target-conditioned judgment for `farmos-local-first` — farmOS local-first port.** These notes are NOT source-derived INTENT: they say how *this* eventual-consistency target (event-log, materialized-views; sync: selective-disclosure) must re-answer the source's central-authority assumptions. A port to a different target would re-answer differently; a port that keeps the central authority ignores this section entirely. The intent-CM grades below describe the SOURCE and stand without any profile.

_1 consistency-model-sensitive element(s): **1 hard** (must choose a resolution strategy), 0 soft (preserve as eventual)._

### ⛔ **CM-hard** `farmosunique-constraint:entityBundleFieldInfo:log/birth/src/Hook/FieldHooks.php`
- **Source assumption** — the source relies on the store enforcing uniqueness at write time. (log/birth/src/Hook/FieldHooks.php:31)
- **Sensitivity** — hard (unique-constraint).
  - _[unique-constraint] The 'UniqueBirthLog' constraint enforces that only one birth log may exist per asset, a server-side uniqueness invariant that CANNOT hold under eventual consistency because two offline nodes can each independently create a birth log for the same asset and both will appear valid …_
- **Decision menu** — preserve-via-convergence-rule / weaken-to-eventual / move-to-disclosure-layer.
  - _Choose one and record it as a Port Decision; the port-verifier treats the choice as an expected delta, not a failure._

## Appendix — raw evidence

_Budget: 12600 tokens (≈6× the 2100-token distilled budget), allocated by intention load — structure-clear ≈0, intention-critical/ambiguous maximal. 15 signal(s) materialized, 34 elided._

### Mixed subsystem components `role:752cb704c83993c71bb4c6c2` (intention-critical)
- `S4/S` [I] Add a quantity_material_type pseudo field to the log_field_data table. ⏎ This pseudo field only has a filter configured to support filtering logs ⏎ by the quantity material type. (modules/log/input/src/Hook/ViewsHooks.php:19-39)
- `S4/S` [I] Add a quantity_material_type pseudo field to the log_field_data table. ⏎ This pseudo field only has a filter configured to support filtering logs ⏎ by the quantity material type. (modules/log/input/src/Hook/ViewsHooks.php:4)
- `S4/S` [I] Add the UniqueBirthLog validation constraint to the asset field of birth ⏎ logs. We need to do this via hook_entity_bundle_field_info() instead of ⏎ hook_entity_field_info_alter() because this module also provides a ⏎ BaseFieldOverride for the asset field, and there is a Drupal core issue ⏎ that pr… (modules/log/birth/src/Hook/FieldHooks.php:18-33)
- `S4/S` [I] Add the UniqueBirthLog validation constraint to the asset field of birth ⏎ logs. We need to do this via hook_entity_bundle_field_info() instead of ⏎ hook_entity_field_info_alter() because this module also provides a ⏎ BaseFieldOverride for the asset field, and there is a Drupal core issue ⏎ that pr… (modules/log/birth/src/Hook/FieldHooks.php:4)
- `S4/S` [I] Create and login a user with access to view any asset and access ⏎ taxonomy terms. This is necessary to validate the log entities below, ⏎ because the entity module's query access handler enforces view access to ⏎ referenced entities during validation. (modules/log/birth/tests/src/Kernel/BirthTest.php:178-239)
- `S4/S` [I] Create and login a user with permission to view logs. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:34)
- `S4/S` [I] Create and login a user with permission to view logs. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:41)
- `S4/S` [I] Create and login a user with permission to view logs. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:55-114)
- `S4/S` [I] Filter to only include logs with the specified material type. ⏎ Make sure the parameter is an array. (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:119-167)
- `S4/S` [I] If the log is not new, skip validation. ⏎ A birth log exits so there is no need to check if one can be created. (modules/log/birth/src/Plugin/Validation/Constraint/UniqueBirthLogConstraintValidator.php:4)
- `S4/S` [I] Sometimes $this->value is an array with a single element so convert it. ⏎ @see TaxonomyIndexTidDepth::query(). (modules/log/input/src/Plugin/views/filter/LogQuantityMaterialType.php:4)
- `S4/S` [I] Use the subquery in a condition on the views query to prevent duplicates. ⏎ PHPStan throws the following error on the next line: ⏎ Parameter #3 $value of method ⏎ Drupal\views\Plugin\views\query\Sql::addWhere() expects ⏎ array|string|null, Drupal\Core\Database\Query\SelectInterface given. ⏎ We igno… (modules/log/input/src/Plugin/views/filter/LogQuantityMaterialType.php:40-83)
- `S4/S` [I] [Group('farm')] ⏎ [RunTestsInSeparateProcesses] (modules/log/input/tests/src/Functional/InputViewMaterialTypeTest.php:4)
- `A5/A` [N] head *type (11/70); affixes=['test']; coherence_entropy=0.90 (modules/log/lab_test/src/Hook/FormHooks.php:)

### Log type plugin `role:7ae99936dac636c3e6b8ce94` (ambiguous) — **human review flagged** (ambiguous)
- `A5/A` [N] head *maintenance (1/4); coherence_entropy=1.00 (modules/log/maintenance/src/Plugin/Log/LogType/Maintenance.php:)

---
_Brief digest `brief:119f4e0d454442cd66a661d9` · generated 2026-07-17T23:07:56.057522+00:00_
