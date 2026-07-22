# Wave-1 scope — feature: harvest (w1c- lane)

> Stage 1 of the per-feature production recipe (fanout-wave-plan.md). Observed
> from source only; no values authored. Source tree: READ-ONLY sandbox
> `/private/tmp/farmos-cell3-2026-07-19/farm-src/modules/log/harvest`.
> Recorded 2026-07-21.

## What the module IS

`farm_harvest` is one of the thinnest clean-slice log modules (3 files):

- `farm_harvest.info.yml` — depends on `farm:farm_entity` + `log:log`.
- `config/install/log.type.harvest.yml` — registers the `harvest` log bundle:
  - `workflow: farm_log_workflow` (states: **pending / done / abandoned**;
    transitions free among all three — `modules/core/log/farm_log.workflows.yml`)
  - `name_pattern: 'Harvest log [log:id]'` — an auto-name idiom, not a domain
    value (and it names the storage id; excluded from the value line)
  - `new_revision: true` — Drupal revisioning idiom, not domain
- `src/Plugin/Log/LogType/Harvest.php` — extends `FarmLogType` (which is an
  empty subclass of `LogTypeBase`; ALL behavior is inherited from the generic
  log + farm-field machinery) and adds exactly ONE bundle field:
  - **`lot_number`** — plain string, optional; "If this harvest is part of a
    batch or lot, enter the lot number here."

## What harvest does BEYOND a generic log

Almost nothing structural — that is the finding. Its domain identity is:

1. **The `lot_number` field.** The only harvest-specific data. It is a free
   string on the log; no code anywhere in `farm-src/modules` *reads*
   `lot_number` back (grep: only seeding, input, and harvest each *define* their
   own `lot_number` — a shared batch/lot convention across three log types, with
   no consumer in core).
2. **Yield-by-quantity convention.** Harvest logs carry standard quantity
   entities (measure/value/units/label); "yield" is the conventional label. The
   quantity machinery itself is the already-built logs+quantities feature; the
   harvest feature only relies on it.
3. **Quick-form producer.** `modules/quick/planting` (Planting quick form)
   creates harvest logs against a plant asset, names them "Harvest @asset",
   defaults status to **pending** unless "done" is ticked, and — unlike
   seeding/transplanting — a harvest log is **NOT a movement**. Boundary-adjacent
   read: the quick form writes harvest logs; nothing reads them back.

## Boundary-adjacent modules considered

| module | relation | in scope? |
|---|---|---|
| `core/entity` (`FarmLogType`, `LogTypeBase`, farm field factory) | base-class machinery harvest inherits | read-only context, not a surface (core is ported once, per the mega-island rule) |
| `core/log` (`farm_log_workflow`) | status lifecycle harvest logs use | context; the kernel status contract already covers pending/done |
| `core/quantity` | harvest quantities | context only — 9h5.25 F3 lesson: scoping it in drags in its own surface |
| `quick/planting` | writes harvest logs | read-authoring producer; informs flows (pending default, non-movement), not the surface |
| `log/seeding`, `log/input` | each defines its own `lot_number` | out of scope; noted as a shared-idiom punt candidate |

## Discriminating semantics to observe (stage-4 targets)

- yield accumulation across done harvest logs (single + multi-log sum)
- **pending-vs-done gating** of yield_total / log_status (harvest defaults to
  pending from the quick form — the gating is live product behavior)
- **effective-time**: a harvest restated to a different instant; as-of behavior
- **per-(measure,unit) independence**: weight kg vs count vs volume on one asset
  never sum across pairs
- status round-trip done→pending (workflow allows every transition)
- multiple quantities on ONE harvest log (per-quantity independence within a log)

## Glossary gap surfaced (stage-5 material, NOT decided here)

`lot_number` — harvest's only distinguishing field — has **no glossary term**:
no `when` field can set it and no assertion can read it. The observe pack
therefore cannot exercise the one thing that makes harvest harvest. Recorded as
a punt for the wave-boundary elicitation menu (shared across seeding/input/
harvest, so it may auto-promote).
