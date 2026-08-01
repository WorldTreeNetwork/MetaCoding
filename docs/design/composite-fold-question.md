# The composite multi-entity fold (MetaCoding-hy6.12)

**Status: JUDGED, and three of four claims were REFUTED.** The first version of
this document was mined and argued by one agent and would have sent five builds
in wrong directions that every test they wrote would have passed. A fresh
adversarial judge broke it against the live source at `3fe0ce7e`. This version
records what survived, what did not, and what must be observed before any build.

**The kernel-sufficiency answer survived: no new primitive is needed.** But it is
reached by a different route than the original argument, and that argument's
errors must not be carried into the builds.

## Verdicts

| claim | verdict |
|---|---|
| **A1** no cross-entity atomicity to port | **SURVIVES**, but was under-specified — see below |
| **A2** `quick` is grow-only, therefore `GSet` | **REFUTED**, twice, and the second reason is damning |
| **B** rule of three fired for denormalize-on-write | **REFUTED** — instance 3 is not an instance |
| **C** (A)+(B) cover the five forms | **REFUTED** — at least four uncovered semantics, plus a false premise |

---

## A1 — no cross-entity atomicity. SURVIVES, and is stronger than stated.

`grep -rni "transaction"` over the whole tree returns **zero hits in code** — the
only occurrences are in `docs/`. No `startTransaction`, no service wrapper, no
queue, no manual rollback. The claim is not a narrow-grep artifact.

The defence that would have saved atomicity — "validation runs before any save,
so partial failure cannot occur" — **fails, and fails worse than first stated**:

- `QuickAssetTrait::createAsset` validates and saves the *same* entity in
  sequence (`:52` create → `:57` stamp → `:59` validate → `:65` save). There is
  no all-validate-then-all-save phase.
- `Birth::submitForm` calls `createAsset` **inside the child loop**. Child 1 is
  on disk before child 2 is validated.
- **`QuickLogTrait::createLog` saves the quantity entity
  (`QuickQuantityTrait.php:79`) BEFORE the parent log is validated
  (`QuickLogTrait.php:82`) and saved (`:88`).** A log that fails validation
  leaves orphan quantity rows committed.
- **`QuickTermTrait::createOrLoadTerm` (`:69-80`) saves a taxonomy term, and
  `Inventory.php:137` calls it from `buildForm`** — a write during form *render*,
  before any submit exists to fail.

So the failure surface is **not a clean prefix of N entity saves**. It is
interleaved, and it includes entities written before their parent is validated
and terms written before submit. A builder told only "N separate saves" still
gets the quantity and term cases wrong.

**A port that made these acts atomic would diverge from the source while looking
like an improvement.** That warning survives intact and is the most important
sentence here — it also applies to the two errors below.

## A2 — `quick` is a GSet. REFUTED.

**Reason 1: `GSet` is UNBOUND, and this argument is the exact inference that
unbound it.** `src/kernel/gset.ts:5-16` carries a standing warning: *"UNBOUND
since 2026-07-20 (MetaCoding-ci2). Its justifying use case was falsified by
observation. … Do not reach for it without a bound decision naming it."* The
falsified case was **nicknames**: mined from source reading as an ordered
multi-value collection, source reading agreed, and the live system replaced
wholesale. This document re-derived the same conclusion by the same method
(static reading of PHP writers) on a field of the same shape
(`'multiple' => TRUE`, no internal flag). The method was already recorded as
insufficient for exactly this question.

**Reason 2: "every entity" is false, and structurally cannot be true.**
`QuickQuantityTrait::createQuantity` (`:68-82`) creates and saves a Quantity with
**no `quick` stamp**, and cannot have one — `FieldHooks.php:31-36` injects the
field onto `asset` and `log` **only**. Same for taxonomy terms. Composite-act
attribution in farmOS is **partial**. A port that stamped every created entity
would diverge in the "looks like an improvement" direction.

**What the boundary says is still UNKNOWN, and cannot currently be observed.**
The judge argued from `FarmFieldFactory.php:209-223` that `hidden` is only a
display option (correct — it sets `region: hidden` then
`setDisplayConfigurable(TRUE)`), with no `setInternal`, no `setReadOnly`, and no
field-access hook anywhere, and concluded `quick` is wholesale-replaceable at
`/api`. I probed the live oracle to settle it and got 422 *"The attribute quick
does not exist on the asset--equipment resource type"* — **but that probe is
void**: `farm_quick` and all five submodules are **DISABLED** on the pinned
oracle (`drush pm:list --filter=quick` → all Disabled). The field was absent
because the module was absent. That measured the oracle, not farmOS, and it
neither confirms nor refutes the judge.

**This is now the gating unknown**, and it is also a blocker for the builds —
see "The oracle cannot see the quick forms" below.

## B — the rule of three has NOT fired.

**Instance 3 (`quick/movement`) is not a denormalize-on-write.**
`combinedAssetGeometries` has four sites (`Movement.php:127, 143, 154`, defn
`:231`) and **every call is inside `buildForm`**: a map-rendering hint and two
`'#type' => 'hidden', '#value' => …` elements feeding JS.
`Movement::submitForm` (`:255-286`) takes `'geometry' => $form_state->getValue('geometry')`
— **user input from the map widget**, which the field description at `:120`
states outright: *"It is copied from the locations selected above, and can be
modified."* Nothing from `getGeometry()` becomes authoritative state. It is a
display helper.

**Instance 2 (`quick/birth`) is two registers off two different entities**:
- `Birth.php:335` — `animal_type` from the **genetic** mother, a plain current
  field read, **no timestamp**. Not a projection.
- `Birth.php:401` / `:416` — location and group from the **birth** mother,
  as-of at the birthdate. Genuine projection reads.

Honest count: *current-value copy from a reference* has two instances
(`material_type`, `animal_type`); *as-of projection materialisation* has two, and
both are in the same call site. **Neither register reaches three independently.**
Merging them to reach three is precisely the "convenience of reaching three" this
document's own judge-question anticipated, and the answer is that it happened.

Promoting a `denormalize-from-projection-at-an-instant` v1.4 primitive on this
evidence would over-model the two cases that actually recur, and a builder handed
it would use it for `animal_type` — silently introducing an as-of read where the
source has none, changing lineage semantics. **The recommendation is withdrawn.
`MetaCoding-dvv` is still waiting for evidence.**

## C — coverage. REFUTED, including this document's opening premise.

- **`Inventory` DOES declare config vocabulary.** It is
  `implements ConfigurableQuickFormInterface` (`Inventory.php:37`) with
  `defaultConfiguration()` (`:73-79`), `buildConfigurationForm()` (`:375`),
  `submitConfigurationForm()` (`:448`), persisting into the
  `farm_quick.quick_form.*` config entity. The "all five declare zero config
  vocabulary" premise is false. (Sub-finding: **no schema is declared** for
  inventory's settings outside the test module, so they fall through the
  `farm_quick.settings.*` wildcard to a keyless mapping.)
- **`group` and `movement` are single-entity.** Both create exactly one log.
  They are not composite fan-outs at all, so "every one of them creates multiple
  entities" is false for two of the five.
- **Inventory's read-side fold is `FoldReduce`-shaped but tie-breaks
  differently.** `AssetInventory::calculateInventory` (`:160-186`) is a left fold
  where `reset` assigns and increment/decrement accumulate; `getAdjustments`
  orders by `l.timestamp ASC, l.id ASC` (`:224-225`) and truncates inclusively at
  the latest reset (`:130-137`, `:228-229`), gating `status = done` (`:287`) and
  `timestamp <= asOf` (`:290`), partitioned by `(measure, units)` with explicit
  `IS NULL` matching (`:277-288`). The kernel's `fold.ts:117` breaks ties on the
  **HLC, never on entity id** — decision `w0a-2`. Two adjustments at an identical
  timestamp fold to different totals. **The inventory build must cite `w0a-2` as
  a declared divergence**, and must implement the `(measure, units)` partition
  including the NULL-matching rule.
- **Planting writes Drupal `State`** — `Planting.php:434`
  `$this->state->set('farm.quick.planting.seasons', …)`: a process-global,
  last-writer-wins register outside the event log entirely, written as a side
  effect and read back as a form default. Needs a decision: replicate outside the
  ledger, or declare a divergence.
- **Planting's logs are conditional and mixed-status** (`:452-491`): three log
  types, each **skipped** when unsubmitted (`:456-458`), `is_movement` derived
  for seeding/transplanting only (`:470-473`), and `status` set per-log from a
  per-log checkbox (`:476-479`) — so one act emits a mix of `done` and `pending`
  logs, which different projections admit differently under `status.ts`.
- **Birth creates children `archived`** — `Birth.php:338`
  `'archived' => empty($child['survived'])`: an entity born into a terminal
  lifecycle state, with a birth log referencing it.
- **`createOrLoadTerm` is upsert-by-natural-key** with a race window; the nearest
  kernel primitive is `GuardedFirstWrite`, but no decision names it for terms.

## The oracle cannot see the quick forms

`farm_quick`, `farm_quick_birth`, `farm_quick_group`, `farm_quick_inventory`,
`farm_quick_movement` and `farm_quick_planting` are **all Disabled** on the
digest-pinned oracle. `bring-up.sh` never enables them.

So **none of the five builds can run their observe step today**, and the `quick`
boundary question above cannot be settled either. Extending `bring-up.sh` to
enable them is the established pattern (it already does this for `farm_sensor`
and `farm_structure_types`) — but `farm_quick` injects a base field onto **every
asset and log**, so the change must be made in `bring-up.sh` (never by hand) and
validated by re-running a reproduction check: re-record `lexicon-bind/location`
and confirm its ten fixture ids still match `f3460165d338da4c6043262a05bd3a99`.
That check is cheap and it is the difference between extending the oracle and
silently re-baselining it.

## Before any of the five builds

1. **Enable the quick modules in `bring-up.sh`**, then re-verify reproduction.
2. **Observe `quick` at the boundary**: can `/api` replace, reorder or clear it?
   That settles A2 empirically instead of by static reading — the method that has
   now failed twice on this exact question.
3. **Bind a CM decision naming whichever primitive `quick` actually is.** It must
   not name `GSet` without one; `gset.ts` forbids it.
4. **Record the partial-provenance divergence**: quantities and terms are
   unstamped and unstampable; the port must not stamp them.
5. **Cite `w0a-2`** in the inventory build for the `l.id` → HLC tie-break.
6. **Decide `Planting.php:434`'s State write** — replicate or diverge.

## What survived

Kernel v1.3 is **sufficient**: `FoldReduce` covers inventory, `EventLog` + HLC
cover the fan-out and its intra-act ordering, `status.ts` covers the mixed-status
emission. No new primitive is needed — which was the question `hy6.12` gated on.
Everything else above is a decision or a divergence to record, not a blocker on
the kernel.
