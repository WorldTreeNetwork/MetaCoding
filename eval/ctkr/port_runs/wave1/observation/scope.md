# Scope — feature: observation (farmOS log/observation) — wave 1, w1b lane

> Stage 1 (SCOPE) of the per-feature production recipe. Source read from the
> READ-ONLY sandbox copy `/private/tmp/farmos-cell3-2026-07-19/farm-src/`.
> Recorded 2026-07-21.

## The module itself

`modules/log/observation` (`farm_observation`) is the **minimal log type**: it
is a pure log-type registration and nothing else.

- `src/Plugin/Log/LogType/Observation.php` — `#[LogType(id: 'observation')]`
  extending `FarmLogType` with an **empty body**. No `buildFieldDefinitions()`
  override, so it adds **zero bundle fields** beyond the generic farm log set.
  (Contrast: `log/harvest`'s plugin adds `lot_number`; observation adds nothing.)
- `config/install/log.type.observation.yml` — bundle config:
  - `id: observation`, `label: Observation`
  - `name_pattern: 'Observation log [log:id]'` — auto-name from the log ID token
    (an oracle-side naming behavior; the port never orders by id, so the pattern
    is treated as a display string, not an ordering signal).
  - `workflow: farm_log_workflow` — the shared 3-state workflow.
  - `new_revision: true` — every save creates a revision (Drupal storage idiom).
- `farm_observation.info.yml` — depends only on `farm:farm_entity` + `log:log`.

**Conclusion: observation's domain semantics are 100% inherited.** What this
feature actually tests is the *generic* farm log contract, exercised through the
plainest possible bundle — the control group of the log family.

## Inherited behavior (boundary-adjacent modules read)

- `modules/core/entity/src/Plugin/Log/LogType/FarmLogType.php` — empty base
  (`LogTypeBase` + string translation). Confirms no hidden hooks.
- `modules/core/log/farm_log.workflows.yml` — `farm_log_workflow` states
  **done / pending / abandoned**; transitions allow any state to reach any other
  (done↔pending↔abandoned all defined). Status is therefore mutable in both
  directions — "done" is not terminal.
- `modules/core/log/src/LogQueryFactory.php` — the canonical read gate:
  optional filters on `type`, `status`, `timestamp <=` (the as-of cutoff), and
  referenced `asset`; sort by `timestamp` then **`id`** (the id-tiebreak the
  kernel forbids — already resolved kernel-side as HLC tie-break, decision
  w0a-2, Duke-confirmed).
- `modules/core/log/src/AssetLogs.php` — per-asset log retrieval
  (`getLogs`/`getFirstLog`, ascending time order).
- Quantity attachment comes from the generic log quantity field (core/quantity):
  observation logs may carry 0..n quantities, each an independent
  (measure, units, value) row. Per-(measure,units) independence and done-only
  gating are the already-studied conventions (w0/pilot + kernel status gate).

## What is IN scope for fixtures

1. Generic log lifecycle on kind `observation`: create pending → done, and the
   done→pending→abandoned reversibility of `farm_log_workflow`.
2. Status gating: pending/abandoned observations must be inert to gated
   projections (log_status / quantity_recorded reads; `require-confirmed`).
3. Effective time (timestamp ≤ as-of cutoff): future-dated done observations.
4. Per-quantity independence: multiple quantities on one observation log with
   different (measure, units) pairs do not merge.
5. Multiple observation logs on one asset (count semantics, asset remains
   active — observations never archive assets).
6. The "adds nothing" property itself: an observation log with no quantities is
   valid (quantity is optional on this bundle).

## What is OUT of scope

- UI/display (name_pattern rendering, form alters), revisioning
  (`new_revision: true` is storage idiom, 14%-survival class), the quantity
  module's own migration/rendering surface (F3 lesson: read-only adjacency),
  and role/permission gating.

## Post-observation note (added after oracle-record, seal edc3f5f49731)

The live oracle's answers CONTRADICT two of the pre-observation intuitions
listed above — the recorded values stand, the intuitions do not:

- `yield_total` is **not status-gated** at the observed boundary: a pending
  observation's quantity counts (2 done + 3 pending → 5.0), and sending a done
  observation back to pending does **not** withdraw it (still 4.0). `log_count`
  includes pending logs too.
- `yield_total` is **not as-of-gated**: a future-dated (+86400) done
  observation counts now (7.0, not 2.0).
- `yield_total` sums **across log kinds** (observation 3 + harvest 9 → 12.0).

Confirmed as expected: per-(measure,unit) and per-measure independence, valid
quantity-less observation (0.0 total), archived asset retains its observation
history (asset_active False, log_count 1), one log against two assets delivers
its full value to both (12 and 12, not split).

Two flow titles ("pending … does not move the asset totals", "…withdraws it
from the totals") were authored as intent before recording and are contradicted
by their own recorded values — see frictions in the wave report.

## Boundary note

Observation shares only kernel kinds (log + quantity + status gate); no NEW
kinds surfaced by this scope read → parallelizes cleanly per the wave plan.
