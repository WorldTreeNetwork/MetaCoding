# The composite multi-entity fold, answered (MetaCoding-hy6.12)

**Status: PROPOSED, not bound.** This was mined and argued by the same agent, so
it is not load-bearing until a fresh judge checks it against the live source.
What is bound by it — five identity builds — is exactly why it must not be
self-approved. See "What a judge should attack" at the bottom.

The five `quick/*` forms declare **zero** config vocabulary yet every one of them
calls entity `::create` for multiple entities in a single act. They were tiered
IDENTITY on *fold* grounds under structure blindness, and filed as ONE bead
because the question — **can a composite multi-entity fold be expressed over the
frozen kernel v1.3, or does it need a new primitive?** — has to be answered once
before any of the five can be built.

## The question was two questions

Conflating them is the trap, because they have opposite answers.

| | |
|---|---|
| **(A) Composite fan-out** | one user act → N new entities. All five forms. |
| **(B) Denormalize-on-write** | a new entity's field value copied from *another* entity's projection. birth, movement — and `quantity/material`, already shipped. |

## (A) Composite fan-out — NO new primitive. Expressible over frozen v1.3.

Three findings in the source, each a positive observation rather than a failure
to find something:

**1. There is no CROSS-ENTITY atomicity to port.** `grep -rn 'startTransaction'
modules/` over all of farmOS returns **0**. Not "none in the quick forms" — none
anywhere in the codebase. Each entity in a composite act is created and saved on
its own; a failure partway through a birth leaves the children already written.

Stated precisely, because the scope matters: farmOS opens no transaction of its
own. Whether Drupal core makes a *single* entity's multi-table write internally
atomic is a core question this tree cannot answer — farmOS is the profile, and
core is not in it. That does not touch the claim, which is only about atomicity
**across** the entities of one act.

That is the semantic, and it is the one to reproduce. **A port that made these
acts atomic would be diverging from the source while looking like an
improvement** — the most dangerous shape of wrong, because every test of the
better behaviour would pass.

**2. Composite-act attribution already exists in the source, and it is a v1.3
primitive.** `QuickAssetTrait::createAsset` stamps every entity it creates:

```php
$asset->get('quick')->appendItem($this->getQuickId());
```

`quick` is a hidden, `'multiple' => TRUE` base field injected onto **asset and
log** (`farm_quick`'s `FieldHooks::entityBaseFieldInfo`), only ever appended to.
A grow-only ordered collection of provenance stamps is exactly **`GSet`**, kernel
element 3 as extended in v1.1. Nothing new is required to express "these entities
came from this act".

**3. Intra-act causal order is already element 2.** A birth creates N children
and *then* a birth log referencing them; the log's `asset` field points at
entities minted earlier in the same act. That ordering is carried by the HLC —
`ids.ts` + `hlc.ts` — and needs no batch envelope.

So the composite fold is **N appends to the existing `EventLog`, each stamped
into a `GSet`, ordered by HLC**. `EventLog.append` takes one event and is called
N times, which is precisely what farmOS does.

## (B) Denormalize-on-write — the rule of three has fired.

`MetaCoding-dvv` recorded the candidate from `quantity/material` and set the bar:
*keep folds feature-local until a THIRD instance appears.* Mining the quick forms
produced the second and third:

| # | site | what is copied | from what |
|---|---|---|---|
| 1 | `quantity/material` `EntityHooks::quantityPresave` (shipped feature-local, `-5ln`) | `material_type` | the referenced material asset, at record time |
| 2 | `quick/birth` `submitForm` | `animal_type`, `location`, group membership | the **mother's projection at the birthdate** — an as-of read |
| 3 | `quick/movement` `combinedAssetGeometries` | geometry | `assetLocation->getGeometry(asset)` — a current projection |

Instance 2 is the sharpest: `$this->assetLocation->getLocation($birth_mother,
$birthdate->getTimestamp())` reads a **fold's output at an instant** and
materialises it into a new event. That is not "copy a field"; it is "copy what
the projection said at time t", and it is the same shape `-5ln` implemented by
hand.

**Recommendation: promote to a kernel primitive in v1.4** — a
`denormalize-on-write from a referenced entity's projection at an instant`
register. v1.3 is frozen; this does not block the five builds, because each can
implement it feature-local exactly as `-5ln` did, and be re-based when v1.4
lands. What it does mean is that `dvv` is no longer waiting for evidence.

## Consequence for the bead

`hy6.12` splits into five per-form beads. The gating question is answered: the
frozen kernel is sufficient for (A), and (B) is a v1.4 decision that does not
block, because the source's own implementation is feature-local too.

## Incidental findings, filed not fixed

- **`quick/group` injects `GroupMembershipInterface` and never uses it**
  (`Group.php:48`, no other reference in the file). A dead constructor
  dependency; the port should not reproduce it, and should say so as a declared
  divergence rather than silently dropping it.
- **`farm_quick` injects a base field onto every asset and log** — structurally
  identical to `log_category`'s `category` injection, which is `hy6.13`'s whole
  subject. The same "a cross-cutting module owns a field on someone else's
  entity" shape, now with a second instance.

## What a judge should attack

1. **The atomicity claim.** It rests on `startTransaction` returning 0 across
   `modules/`. Is there another atomicity mechanism in play — Drupal entity API
   hooks, a queue, `hook_ENTITY_TYPE_presave` rollback — that makes composite
   acts effectively all-or-nothing despite no explicit transaction? If so, (A)'s
   answer is wrong and the port under-specifies.
2. ~~**Whether `quick` really is a GSet.**~~ **Checked while writing this.**
   `get('quick')` has exactly four call sites in `modules/`: two writers, both
   `appendItem` (`QuickAssetTrait:57`, `QuickLogTrait:79`), and two reads in
   `QuickFormTest`. No `set`, no `removeItem`, no reorder, no update hook
   touching it. Grow-only holds on this tree at `3fe0ce7e`. Re-check if the
   field gains a UI.
3. **Whether the three (B) instances are really one shape.** `-5ln` copies at
   presave from a reference; birth copies an as-of projection; movement copies a
   current projection. Is "projection at an instant" genuinely the common
   primitive, or are current-vs-as-of two different registers being merged for
   the convenience of reaching three?
4. **The five forms' remaining folds.** This pass characterised birth, movement,
   planting, group and inventory by their `::create` and projection-read sites.
   Is there a fold in `inventory` (reset/increment/decrement semantics) or
   `planting` (three log types from one asset) that neither (A) nor (B) covers?
