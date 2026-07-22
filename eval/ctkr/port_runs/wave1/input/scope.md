# Wave-1 SCOPE — feature: input (farm_input)

> Wave-1 PREP · 2026-07-21 · source read from the READ-ONLY sandbox
> `/private/tmp/farmos-cell3-2026-07-19/farm-src/modules/log/input` (farmOS 4.x).
> Boundary-adjacent modules included per the 9h5.10 lesson (read-authoring, not
> island-membership alone).

## What the module is

`farm_input` (7 files, tiny) adds the **Input log type** — a log recording
material applied to assets (fertilizer, compost, spray, seed treatments…).
It contributes NO services, NO new entity types, NO event subscribers, and NO
domain fold logic of its own. Everything it does:

1. **Log bundle `input`** (`config/install/log.type.input.yml`):
   - `workflow: farm_log_workflow` → the standard **pending/done** status
     machine (kernel status-gate territory; nothing input-specific).
   - `name_pattern: 'Input log [log:id]'` — label templating idiom, not domain.
   - `new_revision: true` — Drupal revisioning idiom.
   - **`third_party_settings.farm_log_quantity.default_quantity_type: material`**
     — the one genuinely input-specific quantity convention: quantities attached
     to an input log DEFAULT to the `material` quantity type (a default, not a
     restriction — the module's own functional test attaches a `standard`
     quantity to an input log).

2. **Four bundle fields** (`src/Plugin/Log/LogType/Input.php`, all optional
   scalar metadata, no computed behavior):
   - `lot_number` (string) — batch/lot tracking
   - `method` (string) — how the input was applied
   - `purchase_date` (**timestamp**) — when purchased; independent of the log's
     own timestamp — a second time-like field that is inert metadata (does NOT
     participate in effective-time ordering)
   - `source` (string) — where obtained / manufacturer

3. **Views filter by quantity material type** (`src/Hook/ViewsHooks.php`,
   `ViewsExecutionHooks.php`, `src/Plugin/views/filter/LogQuantityMaterialType.php`):
   a pseudo-field + exposed filter on the `/logs/input` listing that selects
   logs referencing **any quantity whose `material_type` term matches** (IN
   semantics, multi-select, subquery over log→quantity→material_type; duplicate
   rows prevented by the IN-subquery shape). This is the module's only "read"
   with real semantics: *log-level membership = ∃ quantity with matching term*.
   It is a UI/views surface, but the underlying predicate (log has a quantity of
   material type T) is domain-meaningful for a port's query layer.

## Boundary-adjacent scope (read-authoring)

- **`modules/quantity/material` (farm_quantity_material)** — declared
  dependency. Adds quantity bundle `material` with a **multi-value
  `material_type` entity-reference to taxonomy `material_type`, with
  `auto_create: TRUE`** (referencing a nonexistent term name creates it).
  Input's default-quantity-type and the views filter both read this. Scoped for
  READS + the shape of the material quantity; its own surface (bundle install
  config) must not leak into input's adapter (pilot friction F3).
- **`modules/taxonomy/material_type`** — the vocabulary the reference targets.
  Term entities only; no behavior.
- **`log` core module (workflow)** — `farm_log_workflow` pending/done gating is
  kernel-bound (STATUS_CONTRACT); consumed as fixed input, not re-scoped.
- **NOT scoped:** `asset/material` (material *assets* are a separate feature —
  input logs reference material *quantities*, not material assets);
  `farm_ui`/views plumbing beyond the filter predicate.

## What is idiom vs domain (for the port)

| element | classification |
|---|---|
| default_quantity_type: material | **domain convention** — default, not constraint |
| lot_number / method / source | domain metadata (plain strings) |
| purchase_date | domain metadata; **inert** timestamp (no ordering role) |
| material_type multi-ref + auto_create | domain (shape owned by quantity/material) |
| filter-by-material-type predicate | domain-meaningful read (∃-quantity membership) |
| name_pattern, new_revision, views/form weights | Drupal idiom — exclude |

## Discriminating behaviors to exercise in OBSERVE

1. Pending-vs-done gating of input-log quantities (kernel status gate on a new
   bundle — does `quantity_recorded`/totals ignore pending input logs?).
2. Effective-time (a future-dated done input log vs an asOf cutoff).
3. Per-(measure,units) independence of quantities on one input log.
4. `purchase_date` inertness — changing/setting it must not move the log in
   effective-time ordering.
5. Standard-vs-material quantity mixing on one input log (default is not a
   restriction).
6. Multi-valued material_type on a single quantity.
7. The ∃-quantity material-type membership predicate (log with 2 quantities,
   one matching — the log matches once, not twice). *(observable only if an
   existing assertion term covers it — likely a punt; see DECIDE.)*
