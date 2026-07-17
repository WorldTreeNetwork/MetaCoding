# farmOS 1.x ↔ 2.x differential intention harvest — portability calibration

_Generated 2026-07-17T22:02:30+00:00 · bead MetaCoding-k12 · deterministic, LLM-free._

The N=2 instance the intention design (`ct-intention-extraction.md` §7.2, §10) says it lacks: farmOS 1.x (Drupal 7) → 2.x (Drupal 9) was a ground-up rewrite of the **same product**, with the old→new map written down in `farm_migrate`. A signal that **survived** the rewrite is intent-I (universal) *by construction*; one that **changed** is idiom. These are empirical numbers against that hypothesis.

## Provenance

- **1.x source** (harvested): `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/farmos-clones/farmOS-1.x` — Drupal 7 tree; sandbox clone of `farmOS@7.x-1.x`.
- **2.x source** (harvested): `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/farmos-clones/farmOS-2.x-branch` — Drupal 9/10 tree; sandbox clone of `farmOS@2.x`.
- **Ground-truth map**: `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/farmos-clones/farmOS-2.x-branch/modules/core/migrate` — `farm_migrate`, 40 migration templates parsed.
- All paths are **sandbox** checkouts (temp clones), not a user production tree. No farmOS data was mutated; the diff reads source only.

## Method + honest fidelity

- **2.x harvest** uses the shipped `ctkr drupal-harvest` declarative lane (`ctkr.drupal.harvest_site`) — YAML config-entity ids, `.info.yml` modules, `*.permissions.yml`. Test-fixture modules (`**/tests/**`) excluded.
- **1.x harvest** uses a new **Drupal-7 adapter** (`ctkr.farmos_diff.harvest_d7`) — farmOS 1.x predates YAML config. Fidelity is regex-level, not a PHP parser:
  - **module**: .info files are INI (`key = value`, `dependencies[] = x`); parsed line-wise, not by a Drupal .info parser — good fidelity for name/description/dependencies, ignores rarely-used directives.
  - **asset_type|log_type**: recovered from `entity_import('farm_asset_type'|'log_type', '{json}')` feature exports in *.features.inc via regex over the JSON blob's `type`/`label` keys — this is how D7 farmOS ships its default bundles. Bundles created only at runtime (none in core) are missed.
  - **permission**: recovered from `hook_permission()` returning an array literal; the permission machine-name keys + `title`/`description` are read by a brace-balanced regex over the function body. Dynamically-built permission names are missed.
  - **taxonomy_vocab**: D7 does not export vocabularies via entity_import in farmOS core; the 1.x vocabulary machine-names are taken from the ground-truth migrate source bundles (d7_taxonomy_term) rather than a direct D7 parse — flagged as oracle-derived.
- **Normalization**: every identifier is compared as a **token sequence** via the shipped tokenizer (`ct-intention-extraction.md` §7.1(1)) with shipped convention affixes folded (§7.1(2)). A rename is `convention` if the versions differ only by affix / namespace-prefix / plural, else `semantic`. Never raw-string comparison.
- **Correspondence oracle**: the `farm_migrate` map first (source-bundle → destination-type; `process.<field>.source` field maps); token-similarity is the fallback where the map is silent.
- **Caveat — field denominator**: `field` rows come from the migrate map, so the population is *migrated* fields only; D7 fields the rewrite dropped outright are not counted (they appear in no migration). Bundle/module/permission populations are the full independent harvests.

## Survival by signal kind (the headline)

`survival` = survived_verbatim + survived_renamed, over the 1.x population. `domain-root` = verbatim + convention-only rename (the domain root token is preserved; a semantic rename moved it). `pred` = the §7.2 default portability tier this kind was *assigned* going in.

| kind | pred tier | 1.x pop | verbatim | renamed (conv/sem) | dropped | new | survival | domain-root |
|---|---|--:|--:|--:|--:|--:|--:|--:|
| asset_type | I | 6 | 5 | 1 (0/1) | 0 | 5 | 100.0% | 83.3% |
| field | N | 57 | 17 | 40 (16/24) | 0 | 9 | 100.0% | 57.9% |
| log_type | I | 13 | 0 | 9 (9/0) | 4 | 1 | 69.2% | 69.2% |
| module | A | 69 | 17 | 4 (4/0) | 48 | 69 | 30.4% | 30.4% |
| permission | N | 21 | 1 | 2 (2/0) | 18 | 18 | 14.3% | 14.3% |
| taxonomy_vocab | I | 7 | 0 | 7 (4/3) | 0 | 2 | 100.0% | 57.1% |

## Per-kind detail + examples

### asset_type — asset bundle — domain vocabulary (noun) (predicted tier **I**)

- survived verbatim (5): `animal`, `compost`, `equipment`, `group`, `sensor`
- renamed / convention-only (0): 
- renamed / semantic (1): `planting`→`plant`
- dropped (0): 
- new in 2.x (5): `land`, `material`, `seed`, `structure`, `water`

### field — field machine name — data-shape vocab (predicted tier **N**)

- survived verbatim (17): `access`, `condition`, `created`, `fid`, `filemime`, `filename`, `init`, `inventory_asset` … (+9)
- renamed / convention-only (16): `field_farm_animal_type`→`animal_type`, `field_farm_companions`→`companions`, `field_farm_crop_family`→`crop_family`, `field_farm_images`→`image`, `field_farm_lot_number`→`lot_number`, `field_farm_manufacturer`→`manufacturer`, `field_farm_maturity_days`→`maturity_days`, `field_farm_model`→`model` … (+8)
- renamed / semantic (24): `animal_tags`→`id_tag`, `email`→`delivery`, `field_farm_animal_castrated`→`is_castrated`, `field_farm_animal_nicknames`→`nickname`, `field_farm_animal_sex`→`sex`, `field_farm_area_type`→`land_type`, `field_farm_crop`→`plant_type`, `field_farm_date_purchase`→`purchase_date` … (+16)
- dropped (0): 
- new in 2.x (9): `_notifications`, `changed`, `lab_test_type`, `parent_id`, `preferred_admin_langcode`, `providing_asset`, `public_key`, `role` … (+1)

### log_type — log bundle — domain vocabulary (event noun) (predicted tier **I**)

- survived verbatim (0): 
- renamed / convention-only (9): `farm_activity`→`activity`, `farm_birth`→`birth`, `farm_harvest`→`harvest`, `farm_input`→`input`, `farm_maintenance`→`maintenance`, `farm_medical`→`medical`, `farm_observation`→`observation`, `farm_seeding`→`seeding` … (+1)
- renamed / semantic (0): 
- dropped (4): `farm_purchase`, `farm_sale`, `farm_soil_test`, `farm_water_test`
- new in 2.x (1): `lab_test`

### module — module machine name — authors' decomposition (predicted tier **A**)

- survived verbatim (17): `farm_api`, `farm_equipment`, `farm_group`, `farm_import`, `farm_inventory`, `farm_l10n`, `farm_log`, `farm_map_mapbox` … (+9)
- renamed / convention-only (4): `farm_asset`→`asset`, `farm_flags`→`farm_flag`, `farm_plan`→`plan`, `farm_quantity`→`quantity`
- renamed / semantic (0): 
- dropped (48): `farm_access_roles`, `farm_access`, `farm_api_development`, `farm_area_generate`, `farm_area_import`, `farm_area_types`, `farm_area`, `farm_asset_children` … (+40)
- new in 2.x (69): `data_stream_notification`, `data_stream`, `farm_activity`, `farm_animal_type`, `farm_animal`, `farm_birth`, `farm_compost`, `farm_entity_fields` … (+61)

### permission — access-policy controlled vocab (predicted tier **N**)

- survived verbatim (1): `access farm dashboard`
- renamed / convention-only (2): `administer farm_asset types`→`administer asset types`, `administer farm_plan types`→`administer plan types`
- renamed / semantic (0): 
- dropped (18): `access farm api info`, `access farm help`, `access farm metrics`, `administer farm api oauth clients`, `administer farm_access module`, `administer farm_asset module`, `administer farm_map module`, `administer farm_mapknitter module` … (+10)
- new in 2.x (18): `access farm import index`, `access farm report index`, `access farm setup`, `access locations overview`, `administer assets`, `administer farm language`, `administer farm map`, `administer farm notification` … (+10)

### taxonomy_vocab — vocabulary — domain vocabulary (noun) (predicted tier **I**)

- survived verbatim (0): 
- renamed / convention-only (4): `farm_animal_types`→`animal_type`, `farm_crop_families`→`crop_family`, `farm_log_categories`→`log_category`, `farm_season`→`season`
- renamed / semantic (3): `farm_crops`→`plant_type`, `farm_materials`→`material_type`, `farm_quantity_units`→`unit`
- dropped (0): 
- new in 2.x (2): `lab`, `test_method`

## Value-level renames (`static_map` in farm_migrate)

Controlled-vocabulary *values* the migration explicitly rewrites — the crispest intent-N evidence: the value's meaning survives, its spelling is idiom.

- `Brand` → `brand`
- `Chip` → `eid`
- `Ear tag` → `ear_tag`
- `Farm Manager` → `farm_manager`
- `Farm Viewer` → `farm_viewer`
- `Farm Worker` → `farm_worker`
- `Leg band` → `leg_band`
- `Other` → `other`
- `Tattoo` → `tattoo`
- `farm_format` → `default`
- `farm_soil_test` → `soil`
- `farm_water_test` → `water`
- `plain_text` → `plain_text`

## Calibration: predicted §7.2 tier vs observed survival

The hypothesis under test: **intent-I signals survive a same-product rewrite; intent-N signals survive in meaning but change in spelling; intent-A signals vanish.** Reading the observed numbers against the assigned tier:

- **asset_type** (predicted **I**): domain-root survival 83.3%, verbatim 83.3%. **Mostly confirms intent-I**, with a semantic-rename tail worth inspecting.
- **field** (predicted **N**): domain-root survival 57.9%, verbatim 29.8%. **Confirms intent-N** — meaning survives (high domain-root) but the verbatim spelling does not (the convention was restated).
- **log_type** (predicted **I**): domain-root survival 69.2%, verbatim 0.0%. **Mostly confirms intent-I**, with a semantic-rename tail worth inspecting.
- **module** (predicted **A**): domain-root survival 30.4%, verbatim 24.6%. **Consistent with intent-A** — largely did not survive as-is.
- **permission** (predicted **N**): domain-root survival 14.3%, verbatim 4.8%. **Confirms intent-N** — meaning survives (high domain-root) but the verbatim spelling does not (the convention was restated).
- **taxonomy_vocab** (predicted **I**): domain-root survival 57.1%, verbatim 0.0%. **Weakens the intent-I assignment** — too many domain roots moved; review.

## Proposed tier / dial adjustments (where data contradicts §7.2 defaults)

- **Add a project-namespace affix to `intention_normalization.json`.** farmOS 1.x prefixes log/taxonomy/field machine names with `farm_`/`field_farm_`; the rewrite drops it wholesale (`farm_activity`→`activity`, `field_farm_animal_sex`→`sex`). This is exactly a §7.1(2) convention affix (portability **N**) but is project-specific, so it must be a *per-project* affix entry, not a global one — evidence the affix table needs a `project_namespace` lane keyed per corpus.
- **Module names (predicted A/B1): observed survival 30.4%, domain-root 30.4%.** The feature decomposition is more portable than B1's 'directories accrete' framing assumes when modules are feature-shaped; but the semantic-rename + dropped tail confirms module *names* are not a reliable cross-version key — keep B1 low-weight, prefer the type vocabulary as the join key.
- **asset_type (predicted I): domain-root survival 83.3%, verbatim 83.3%.** The gap between domain-root and verbatim survival is the intent-N convention layer sitting *on top of* an intent-I root — the design's split of A4 into 'name (N)' vs 'the thing it names (I)' is vindicated: harvest the root as I, the spelling as N.
- **log_type (predicted I): domain-root survival 69.2%, verbatim 0.0%.** The gap between domain-root and verbatim survival is the intent-N convention layer sitting *on top of* an intent-I root — the design's split of A4 into 'name (N)' vs 'the thing it names (I)' is vindicated: harvest the root as I, the spelling as N.
- **taxonomy_vocab (predicted I): domain-root survival 57.1%, verbatim 0.0%.** The gap between domain-root and verbatim survival is the intent-N convention layer sitting *on top of* an intent-I root — the design's split of A4 into 'name (N)' vs 'the thing it names (I)' is vindicated: harvest the root as I, the spelling as N.
- **Fields (predicted A4/N): domain-root survival 57.9% among migrated fields.** Confirms A4's 'boundary shapes portable, internal freely renamed' — but here even the *root* survives once the `field_farm_` namespace is folded, so the D/R richness weight for field-name signals can be raised for same-domain ports (fewer 'ambiguous' misclassifications).
- **D/R dial note (§5.3):** value-level `static_map` renames (13 found) are load-bearing intent-N evidence the current harvest does not capture from a single version — they only become visible with the N=2 diff. Recommend the calibration.parquet schema add a `cross_version_rename` signal so the second instance's renames feed the R score directly.

## Reproduce

```
uv run python eval/ctkr/farmos_differential.py \
    --v1 /private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/farmos-clones/farmOS-1.x \
    --v2 /private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/farmos-clones/farmOS-2.x-branch \
    --migrate /private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/farmos-clones/farmOS-2.x-branch/modules/core/migrate
```
