# w1a — activity log: scope (stage 1)

> Wave-1 PREP, 2026-07-21. Source: /private/tmp/farmos-cell3-2026-07-19/farm-src
> (read-only sandbox copy of farmOS 4.x). Entity prefix: `w1a-`.

## The module itself

`modules/log/activity` is **four files and functionally empty**:

- `farm_activity.info.yml` — depends on `farm:farm_entity`, `log:log`.
- `src/Plugin/Log/LogType/Activity.php` — `class Activity extends FarmLogType {}`
  with `#[LogType(id: 'activity', label: 'Activity')]`. **No body. No extra
  fields, no hooks, no services.**
- `config/install/log.type.activity.yml` — the bundle config:
  - `workflow: farm_log_workflow`
  - `name_pattern: 'Activity log [log:id]'`
  - `new_revision: true`

There is no `.module` file. Activity is the **degenerate/baseline log type**:
it exists to give generic "work was done" records a bundle, and every behavior
it has is inherited.

## Inherited behavior (boundary-adjacent scope, read-only semantics)

- `modules/core/entity/src/Plugin/Log/LogType/{FarmLogType,LogTypeBase}.php` —
  base plugin: `buildFieldDefinitions()` returns `[]` (confirmed: activity adds
  zero bundle fields).
- `modules/core/log` (farm_log) — `farm_log.workflows.yml` defines the shared
  log workflow: states **done / pending / abandoned**, transitions allow any
  state to reach any other (done←{pending,abandoned}, pending←{done,abandoned},
  abandoned←{done,pending}).
- `modules/core/quantity` (via core/log/modules/quantity glue) — every log type,
  activity included, carries 0..n quantity references (measure/value/units/label),
  independent per (measure, units).
- Movement/location fields (farm_location applied to logs) — activity logs CAN
  be movements (is_movement + geometry + location), though nothing in this
  module makes that special.

These adjacent modules are scoped **for the fields/semantics they give activity
logs only** — their own feature surfaces (quantity migration/rendering, location
assignment logic) are NOT part of this feature (wave-0 friction F3).

## What this log type does beyond generic logs

**Nothing — and that is the finding.** Activity is the identity element of the
log-type family. The discriminating semantics to observe are therefore exactly
the shared log-spine semantics, exercised through kind "activity":

1. **Status gating** — pending vs done participation in projections
   (log_count/quantity_recorded); done-only conventions.
2. **The third state, `abandoned`** — the kernel status contract speaks in
   pending/done gates; whether abandoned behaves as "not done" (inert) or as a
   distinct observable state is a discriminating observation.
3. **Effective time** — timestamp ≤ asOf cutoff; future-dated done logs.
4. **Per-quantity independence** — multiple quantities on one activity log,
   distinct (measure, units) pairs do not sum.
5. **Auto-naming** — `Activity log [log:id]` when no name given (id-derived —
   note the kernel forbids id-ordering/id-derivation; naming is presentation,
   flagged in DECIDE, not asserted).
6. **Revisioning** (`new_revision: true`) — storage idiom, not domain value
   (wave-0 F6); out of scope for fixtures.

## Non-goals

- No inventory adjustment semantics (activity is not an inventory log type by
  default — record_inventory_adjustment flows only if mining shows otherwise).
- No harvest/yield conventions (that is log/harvest).
- Quantity-module's own surface (migrations, rendering) — reads only.
