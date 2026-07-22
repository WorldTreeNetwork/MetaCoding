# Wave-2 spine/identity partition — farmOS clean slices

> Bead MetaCoding-hy6 (epic) · 2026-07-22 · RISK PARTITIONER · deterministic, LLM-free.
> Vocabulary lane: `ctkr glossary-gaps` per module. Structure lane: `ctkr role-gaps`
> per family — **UNAVAILABLE** (graph export missing; see §Degradation). Degraded to
> vocabulary-only + fold-nature judgment, per the task's degrade-gracefully rule.

## Provenance & data-dir scope

- **Source (READ-ONLY):** `/private/tmp/farmos-cell3-2026-07-19/farm-src/modules/**` — nothing written into it.
- **Graph data-dir (attempted, READ-ONLY):** `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2` — `ctkr/export/` is **empty** (no `nodes.jsonl`/`edges.jsonl`); the parquets the boundary map cited are gone.
- **Scratch (all tool output):** `/private/tmp/farmos-partition-scratch-2026-07-22/{gaps,roles}/` — per-module `gaps.jsonl`, per-family `role-gaps` error logs. Sandbox, not production; nothing downstream reads it.
- **Committed artifacts (in-repo):**
  - `eval/ctkr/results/wave2/partition-2026-07-22.jsonl` — 41 rows, one per in-scope module.
  - `eval/ctkr/results/wave2/partition-summary.md` — this file.

## Headline

**41 in-scope feature modules** across 6 clean-slice families → **23 SPINE · 18 IDENTITY**.
**42 modules excluded** (37 `core/*` + 5 `role/*`). The compiled `web/profiles/farm` tree is excluded from all counts (duplication).

## Tier table

Legend: `vocab_new` = workflow-states + bundle-fields + allowed-values + quantity-types introduced beyond the current glossary (the task formula). Bare bundle-label introductions (`asset_type`/`log_type` with no new fields) are **not** counted — they are label-only and stay spine. `role_classes_new` = **unavailable** for every row (structure lane down).

### SPINE (23) — build + regression + smoke, no per-feature recipe

| module | family | vocab_new | cluster | why spine |
|---|---|--:|---|---|
| asset/compost | asset | 0 | spine-asset | label-only asset_type |
| asset/equipment | asset | 0 | spine-asset | type already in glossary |
| asset/group | asset | 0 | spine-asset | type already in glossary |
| asset/material | asset | 0 | spine-asset | label-only asset_type |
| asset/plant | asset | 0 | spine-asset | label-only asset_type |
| asset/product | asset | 0 | spine-asset | label-only asset_type |
| asset/seed | asset | 0 | spine-asset | label-only asset_type |
| asset/water | asset | 0 | spine-asset | label-only asset_type |
| log/activity | log | 0 | spine-log | no new vocab |
| log/harvest | log | 0 | spine-log | no new vocab |
| log/maintenance | log | 0 | spine-log | label-only log_type |
| log/observation | log | 0 | spine-log | no new vocab |
| organization/farm | organization | 0 | spine-misc | no new vocab |
| quantity/standard | quantity | 0 | spine-misc | no new vocab |
| taxonomy/animal_type | taxonomy | 0 | spine-taxonomy-a | empty term vocab |
| taxonomy/equipment_type | taxonomy | 0 | spine-taxonomy-a | empty term vocab |
| taxonomy/lab | taxonomy | 0 | spine-taxonomy-a | empty term vocab |
| taxonomy/log_category | taxonomy | 0 | spine-taxonomy-a | empty term vocab |
| taxonomy/material_type | taxonomy | 0 | spine-taxonomy-a | empty term vocab |
| taxonomy/product_type | taxonomy | 0 | spine-taxonomy-b | empty term vocab |
| taxonomy/season | taxonomy | 0 | spine-taxonomy-b | empty term vocab |
| taxonomy/test_method | taxonomy | 0 | spine-taxonomy-b | empty term vocab |
| taxonomy/unit | taxonomy | 0 | spine-taxonomy-b | empty term vocab |

### IDENTITY (18) — full recipe (mine → observe → decide → build → read)

| module | family | vocab_new | driving evidence |
|---|---|--:|---|
| log/lab_test | log | 7 | 1 allowed_values + 5 bundle_field + 1 quantity_type (richest slice) |
| taxonomy/plant_type | taxonomy | 8 | 8 bundle_field (ASSERTION_TERMS) on the plant-type term |
| log/input | log | 4 | 3 bundle_field + 1 quantity_type (MEASURES) |
| asset/sensor | asset | 3 | 3 bundle_field (data-stream assertions) |
| asset/structure | asset | 2 | 1 allowed_values + 1 bundle_field |
| log/birth | log | 2 | 2 bundle_field (mother/child assertions) |
| log/seeding | log | 2 | 2 bundle_field |
| log/transplanting | log | 2 | 2 bundle_field (+ label-only log_type) |
| asset/animal | asset | 1 | 1 allowed_values (closed descriptor list) |
| asset/land | asset | 1 | 1 bundle_field (ASSERTION_TERMS) |
| log/medical | log | 1 | 1 bundle_field (+ label-only log_type) |
| quantity/material | quantity | 1 | 1 bundle_field |
| quantity/test | quantity | 1 | 1 bundle_field |
| quick/birth | quick | 0 | composite multi-entity fold — tiered UP (see §Structure) |
| quick/group | quick | 0 | composite multi-entity fold — tiered UP |
| quick/inventory | quick | 0 | composite multi-entity fold — tiered UP |
| quick/movement | quick | 0 | composite multi-entity fold — tiered UP |
| quick/planting | quick | 0 | composite multi-entity fold — tiered UP |

## Spine cluster plan (one-mind builders, 4–8 features each)

Grouped by shared domain kind (feature-kinds logic): features sharing a NEW kind
serialize through one builder mind; independent families parallelize.

| cluster | n | shared kind / rationale |
|---|--:|---|
| **spine-asset** | 8 | all emit `asset_created`; concrete `FarmAssetType` bundles — one mind holds the asset-bundle idiom |
| **spine-taxonomy-a** | 5 | `taxonomy_term` bundles (animal/equipment/lab/log_category/material) — vocabulary term shells |
| **spine-taxonomy-b** | 4 | `taxonomy_term` bundles (product/season/test_method/unit) — split from -a for context size |
| **spine-log** | 4 | all emit `log_recorded`; serialize through one mind (the log-family lesson) |
| **spine-misc** | 2 | quantity/standard (`quantity_measured`) + organization/farm (`organization`) — independent kinds, parallelizable, bundled for builder efficiency |

All 5 clusters fit a single builder context (2–8 features). spine-asset and spine-log
are true serialize-through-one-mind clusters (shared kind); the taxonomy and misc
clusters are convenience bundles of independent, parallelizable shells.

## Exclusions (not tiered — 42 modules + 1 tree)

- **`core/*` (37):** api, asset, comment, csv, data_stream, entity, export, field, flag,
  form, format, geo, id_tag, image, import, inventory, kml, l10n, location, log, login,
  map, migrate, notification, organization, owner, parent, **plan**, quantity, quick,
  report, role, setup, test, timeline, ui, update. Ported **once** as the kernel + the
  per-family plugin-type adapter surfaces (`FarmAssetType`/`FarmLogType`/`FarmQuantityType`),
  never as N features. Includes `core/{ui, timeline, map}` (UI/theme), `core/{migrate, update, setup}` (migration/update), `core/test` (test).
- **`role/*` (5):** account_admin, config_admin, manager, viewer, worker — **deferred**
  (14% cross-version survival; CM-soft access gates handled later as selective-disclosure
  policies, not ports).
- **`web/profiles/farm`:** compiled install profile — duplication, excluded from all counts.

## Discrepancies vs the boundary map (noted, not resolved)

1. **No top-level `plan` family.** The task named a "plan" family; there is **no
   `modules/plan/`** in the cell3 sandbox. `plan` exists only as **`modules/core/plan`**
   — so it falls inside the excluded `core/*` mega-island (ported as kernel/adapter),
   consistent with the wave plan. Flagged, not resolved.
2. **Clean-slice count.** The boundary map (`boundary-quality-farmos-v2-2026-07-20.md`)
   reports 117 clean slices out of 147 features / 123 declared-with-symbols — that count
   spans all families incl. `core/*` sub-modules and the compiled profile. My in-scope 41
   is that population minus the exclusions above; no contradiction, different denominators.
3. **taxonomy in scope.** The boundary map lists `taxonomy/*` as a clean-slice island; I
   keep it in scope and tier by vocab (9 spine shells + 1 identity, plant_type). The task's
   named families (log/asset/quantity/organization) did not name taxonomy or quick
   explicitly; both are clean-slice peers and are included.

## Degradation — structure lane unavailable (MetaCoding-u00)

`ctkr role-gaps --family <f> --data-dir /private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2`
failed for **all 6 families** with:

```
FileNotFoundError: Could not find nodes.jsonl + edges.jsonl in
  .../farmos-data-v2/ctkr/export or .../farmos-data-v2
```

The graph export directory exists but is **empty** — the 8,059-node export the boundary
map was built on is not present in this data-dir. This is the known-broken lane of bead
**MetaCoding-u00**. Per the task's degrade-gracefully rule:

- `role_classes_new = "unavailable"` on **every** row — no unnamed-domain-role-class signal
  was obtained. The structure column is honestly empty, not improvised.
- Tiering rests on the **vocabulary lane** (deterministic, reproducible) plus the
  **"tier UP when in doubt"** rule for the one family the missing lane would most have
  informed: **quick/\*** forms. All 5 declare zero config vocabulary but their
  `QuickForm` plugins create multiple entities (asset + log + relations) — composite
  folds not expressible as a single kernel fold, and exactly the multi-entity
  orchestration role-gaps would surface. They are tiered IDENTITY on fold grounds; the
  cost asymmetry favors it. Confirmed by source: every `quick/*/src/Plugin/QuickForm/*.php`
  calls entity `::create`.

## Reproduce

```bash
cd /Users/dukejones/work/WorldTree/MetaCoding/ctkr
# vocabulary lane (per module) — e.g. log/lab_test:
uv run python -m ctkr glossary-gaps \
  --src /private/tmp/farmos-cell3-2026-07-19/farm-src/modules/log/lab_test \
  --rel-root /private/tmp/farmos-cell3-2026-07-19/farm-src \
  --out /tmp/scratch/log__lab_test.jsonl --json
# structure lane (currently fails — MetaCoding-u00):
uv run python -m ctkr role-gaps --family log \
  --data-dir /private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2 --out /tmp/scratch/log.jsonl
```
