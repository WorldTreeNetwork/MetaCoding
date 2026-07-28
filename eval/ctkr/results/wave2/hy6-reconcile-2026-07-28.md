# hy6 reconcile — what the partition asked for vs what is actually ported

> 2026-07-28. Bead `MetaCoding-hy6`. Reads the risk partition
> (`partition-2026-07-22.jsonl`, 41 rows, amended) against the port runs on disk
> and in git history, and turns the difference into the epic's children.
> No builds were run and no port was modified by this reconcile — it is an
> accounting pass over committed artifacts.

## Provenance & data-dir scope

- **Partition (in-repo, read):** `eval/ctkr/results/wave2/partition-2026-07-22.jsonl`
  + `partition-summary.md`. Already carries the 2026-07-22 amendment
  (`asset/group`, `organization/farm` tiered UP): **21 spine / 20 identity / 42 excluded**.
- **Port runs (in-repo, read):** `eval/ctkr/port_runs/{wave0-pilot,wave1,wave1-c1,wave2,compose-9h5.16,lexicon-bind}/`.
- **Git history (read):** `ff714c4` (five spine clusters) and the six identity
  commits `07249b9 74c499f 47c61f2 9052c8f 3b3dad4 a88ec85 cba5ada`.
- **Source sandbox: GONE.** Corrected same day — the first pass of this document
  said "still present" on the strength of `ls -d` returning the directory. It
  returns the directory because macOS's `/tmp` cleaner deletes *files* older than
  three days and leaves the *directory skeleton* standing. Measured:
  `/private/tmp/farmos-cell3-2026-07-19` holds **1,255 directories and 0 files**,
  including an empty `.git`. A path test that cannot distinguish a live tree from
  its skeleton is not a provenance check.
- **Graph data-dir: GONE**, same cause.
  `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2/ctkr/export`.
- **Partition scratch: GONE**, same cause. Every `/private/tmp/farmos-*` path
  this project has ever cited is now zero files.
- **The pin survives, off-repo.** The running oracle container still carries the
  source it was built from: farmOS `4.x-dev` @
  `3fe0ce7e23de807be9b8bc97a211ce934327db39` (`composer.lock` inside
  `farmos-oracle-www`; profile tree at `/opt/drupal/web/profiles/farm`). The
  source is re-clonable at the exact commit the 43 packs were recorded against —
  but that fact lives in a container that has been up 8 days, not in the repo.
  See §Durability.
- **Nothing written outside the repo.** Artifacts of this pass: this file plus
  the hy6 child beads.

## Headline

| lane | in partition | ported | remaining |
|---|--:|--:|--:|
| SPINE | 21 | 18 | **3** |
| IDENTITY | 20 | 5 | **15** |
| total | 41 | 23 | **18** |

23 of 41 in-scope modules are ported (56%). The epic is roughly half-built and
had **zero children**, which is why it read as unstarted.

## SPINE — 18 done, 3 remaining

Delivered by `ff714c4` on frozen kernel v1.3, 101 tests green at commit time:

| cluster | modules | status |
|---|---|---|
| spine-asset | compost, equipment, material, plant, product, seed, water (7) | ported — `SpineAssetStore` + per-bundle surfaces |
| spine-taxonomy-a | animal_type, equipment_type, lab, log_category, material_type (5) | ported — `TaxonomyTermStore`; **log_category is shell-only** (see §Punts) |
| spine-taxonomy-b | product_type, season, test_method, unit (4) | ported — `TaxonomyVocabStore` |
| spine-log | maintenance (1 of 4) | ported |
| spine-misc | quantity/standard (1) | ported (`organization/farm` tiered out of this cluster) |

**Remaining (3):** `log/activity`, `log/harvest`, `log/observation`.
These are not greenfield — `eval/ctkr/port_runs/wave1/{activity,harvest,observation}/build`
holds wave-1 pilot ports of all three, built **before** the kernel was frozen
and against the wave-1 shared store. The work is a rebuild/promotion onto
kernel v1.3 with the spine ceremony (build + existing regression + smoke), not a
first port. Doing them completes `spine-log`, whose whole point was that the log
family serializes through one builder mind.

## IDENTITY — 5 done, 15 remaining

Done on the full recipe (oracle surface → sealed pack → blind build → fresh reading):

| module | bead | evidence |
|---|---|---|
| log/lab_test | `MetaCoding-wgy` | 22/22 scored, 100% reproduced |
| taxonomy/plant_type | `MetaCoding-urn` | 18/18 scored, 100% reproduced |
| asset/sensor | `MetaCoding-ej0` | blind build on pack `44ecd9bff969` |
| asset/structure | `MetaCoding-xq7` | `structure_kind` BOUND on one sealed pack |
| quantity/material | `MetaCoding-5ln`, `-87t` | 5/5 scored, 100% reproduced |

Also delivered but **not a partition row**: `MetaCoding-1cv`, the equipment-on-log
base field — a big-punt from spine-asset, 7/7 scored.

**Remaining (15):**

| module | prior art on disk | note |
|---|---|---|
| asset/animal | `wave0-pilot/w0b-src/animal` | pilot, pre-kernel |
| log/birth | `wave0-pilot/w0b-src/birth` | pilot, pre-kernel; richest bound lexicon (birth/lineage packs) |
| log/input | `wave1/input/build` | pilot, pre-kernel; vocab_new 4 |
| log/seeding | — | vocab_new 2 |
| log/transplanting | — | vocab_new 2 |
| log/medical | — | vocab_new 1 |
| asset/land | — | vocab_new 1; the location lexicon is already bound |
| quantity/test | — | vocab_new 1 |
| asset/group | — | tiered UP: computed membership + circularity constraint |
| organization/farm | — | tiered UP: cross-cutting farm-scoping constraints |
| quick/birth, quick/group, quick/inventory, quick/movement, quick/planting | — | tiered UP as a family: composite multi-entity folds, `::create` in every `QuickForm` plugin |

The five `quick/*` forms are filed as **one** child, not five: they were tiered up
on a single shared ground (a composite fold no single kernel fold expresses), and
the fold-primitive question has to be answered once before any of the five can be
built. Splitting into five features is the right move *after* that answer, not before.

## Punts from the spine run that were never filed

`ff714c4`'s BIG-PUNT valve fired five times. Two became beads and are closed
(`-5ln` material quantity_presave, `-1cv` equipment log field). **Three were
never filed** and are filed now:

- `w2-taxa-lc-1` — `log_category` injects a multi-valued `category` reference
  field onto EVERY log entity. This is why taxonomy-a shipped log_category as a
  shell; the field injection belongs to a log-owning store and is identity-tier.
- `w2-taxa-lc-2` — the `LogCategorize` bulk action with append/replace union
  semantics; flagged as a candidate kernel primitive
  (union-or-replace collection register).
- **taxonomy decision-gaps** — single- vs multi-parent hierarchy (both taxonomy
  clusters), term-delete with dangling children, term revisioning. Undecided in
  both shipped stores.

A punt that is not a bead is a punt that was dropped. Three of five were, for six days.

## Structure lane — worse than degraded

The partition ran with `role_classes_new = "unavailable"` on all 41 rows because
`ctkr role-gaps` could not find `nodes.jsonl`/`edges.jsonl`. Its residual action
was "restore the graph export and re-run role-gaps before identity builds."

That has not happened, **and the data-dir itself is now gone from `/tmp`** — the
8,059-node export the boundary map was built on is no longer recoverable by
pointing at that path; it has to be rebuilt from source. Consequences, stated
plainly rather than assumed away:

- All 15 remaining identity builds are proceeding on **vocabulary evidence plus
  the tier-up-when-in-doubt rule**, which is what tiered `quick/*`, `asset/group`
  and `organization/farm`. Tier-up is the safe direction (cost, not correctness),
  so this does not block building — it blocks *knowing* the partition was right.
- The reverse error is the dangerous one: a module tiered SPINE that a role-class
  signal would have tiered IDENTITY gets no recipe and no reading. All 18 spine
  modules already shipped under exactly that blindness.

Filed as a narrow hy6 child (rebuild the export, re-run role-gaps over the six
families, re-tier if the signal disagrees), linked to the broader `MetaCoding-u00`.

## Durability — what is actually load-bearing and where it lives

Prompted by Duke, 2026-07-28: *"if we expect something to stick around we can't be
writing to a tmp dir."* An inventory, since the `/tmp` losses above were found by
accident rather than by a check anyone runs:

| thing | location | durable? |
|---|---|---|
| the port itself (23 modules) | `eval/ctkr/port_runs/**`, in-repo | **yes** — git + pushed |
| sealed packs, `PACKS.jsonl`, glossary, provenance, decisions | in-repo | **yes** |
| kernel, ctkr, judge, oracle client | in-repo | **yes** |
| **farmOS source (the witness)** | `/private/tmp/farmos-cell3-*` | **NO — already lost** |
| **graph export / data-dir** | `/private/tmp/farmos-rebuild-*` | **NO — already lost** |
| **the live oracle's database** | anonymous Docker volume `621513a8b622…` | **NO** — no name, no bind mount; `docker system prune --volumes` or a `rm` of the container ends it |
| **the oracle's farmOS site + code** | inside the `farmos-oracle-www` container layer | **NO** — zero mounts; the container is the only copy |
| the source commit pin | `composer.lock` inside that same container | **NO** — recorded in this file as of today, which is the first time it has been in the repo |

The deliverable is safe. **Every witness the deliverable was measured against is
one `docker rm` or one `/tmp` sweep from gone**, and one of those sweeps has
already happened. 43 sealed packs assert facts about a source tree no longer on
this disk and an oracle whose only copy is an 8-day-old container.

This is the `MetaCoding-u00` lesson generalized, and it is exactly what
`MetaCoding-1gt` (port-workspace scaffold: source pristine / workspace repo /
hidden regenerable caches) was filed to prevent — filed P3 on 2026-07-22, six
days before the thing it warned about had already happened.

## What this pass did NOT do

- Did not verify that the 23 ported modules still build or that their tests still
  pass at HEAD. The test counts quoted are the ones recorded at their commits.
- Did not re-run `glossary-gaps`; the partition's vocabulary lane is taken as given.
- Did not re-parent the closed feature beads that predate the epic's decomposition
  — they are recorded here instead, since reparenting closed work rewrites history
  the retro will read.
