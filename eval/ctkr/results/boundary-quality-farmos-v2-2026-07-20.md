# Boundary-quality eval + restructure proposal — farmOS v2 (8,059-node graph)

> Bead MetaCoding-9h5.12 · 2026-07-20 · deterministic, **LLM-free** · read-only over a sandbox copy of the farmOS v2 graph.

## Provenance & data-dir scope

- **Source graph (READ-ONLY):** `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2` — the 8,059-node / 11,499-edge farmOS v2 export (`ctkr/export/nodes.jsonl` + `edges.jsonl`), branch `4.x`, `source=tree_sitter`. Never mutated.
- **Sandbox (all writes here):** `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/9h5.12-sandbox` — a full copy of `farmos-data-v2/ctkr` (partition parquets, features, export). `restructure-proposal.md` written here. This is a **sandbox**, not a production data-dir; nothing downstream reads it by default.
- **Edge alphabet:** REFERENCES 4354, CONTAINS 3657, CALLS 1933, CONSTRUCTS 906, EXTENDS 518, IMPLEMENTS 131. **No data-edge kinds** (`READS_FIELD`/`WRITES_FIELD`/`TYPE_OF`/`RETURNS_TYPE` = 0; `scip_fraction=0.0`) — the same thin-alphabet caveat the introspection audit flagged. Boundary quality here is a call/reference/containment/inheritance result, not a data-flow result.
- **Tools (new, shipped this bead):** `ctkr boundary-quality`, `ctkr restructure-proposal`; libs `ctkr/boundary_quality.py`, `ctkr/restructure.py`.

---

## Deliverable 1 — Boundary quality per island

### Partition (default dials: resolution 0.5, dir-prior level 2)

11 islands, 8,059 members, 78.2 % persistent (`boundary_confidence ≥ 0.5`), 652 locality-placed.

| island | members | persistence | dominant dirs / module family |
|---|--:|--:|---|
| `ss:d66d26fc` | 3750 | **0.615** | modules/core/{ui, entity, data_stream} — the core blob |
| `ss:1e8c0656` | 3524 | **0.602** | web/profiles/farm (3337) — the compiled install profile |
| `ss:7044ab31` | 319 | 0.997 | modules/asset/{group, sensor, structure} |
| `ss:761b7d53` | 126 | 1.000 | modules/log/{birth, input, lab_test} |
| `ss:f7ae0f4c` | 121 | 0.995 | modules/quick/{movement, inventory, planting} |
| `ss:f49e059c` | 118 | 0.991 | modules/organization/farm |
| `ss:98705470` | 46 | 1.000 | modules/role/{account_admin, manager, viewer} |
| `ss:aa700b0a` | 38 | 1.000 | modules/taxonomy/{log_category, plant_type} |
| `ss:2cb2e7ea` | 11 | 1.000 | modules/quantity/{material, test, standard} |
| `ss:cf34e94a` | 5 | 1.000 | farm.install |
| `ss:3d4db658` | 1 | 1.000 | docker/dev/files |

**Size distribution is bimodal**: two mega-islands (3750, 3524) with **low persistence (~0.61)**, and nine small islands (≤319) with **near-perfect persistence (0.99–1.00)**. The small islands each map to one farmOS module *family* (asset/log/quick/organization/role/taxonomy/quantity). The two mega-islands are (a) the interconnected `modules/core/*` mass and (b) the vendored/compiled `web/profiles/farm` tree — both are directory-prior artifacts (see §Caveat), and their low persistence flags them as the fuzzy ones.

### Boundary-edge composition: Drupal idiom vs domain coupling

372 non-CONTAINS edges cross an island boundary. Classified name-blind (a crossing edge is a **framework idiom** when an endpoint is a framework node — `qualified_name` starts with `external::`, i.e. a Drupal/Symfony base the indexer resolved *outside* the repo):

| | count | share |
|---|--:|--:|
| **framework idioms** | **328** | **88.2 %** |
| genuine domain coupling | 44 | 11.8 % |

Crossing edges by kind: `EXTENDS 215, REFERENCES 130, IMPLEMENTS 25, CALLS 2`. **Only 2 of 1,933 CALLS edges and 0 of 906 CONSTRUCTS edges cross a boundary** — behavioral (call/construct) coupling is almost entirely *intra*-island. The boundary is made of inheritance + references, and 88 % of that is inheritance/reference to Drupal base classes every module shares.

**The 44 "domain-coupling" crossings are themselves almost all framework-shaped** — every one is an `EXTENDS`/`IMPLEMENTS` to a farmOS *plugin-type base class*, not a behavioral dependency:

```
10  EXTENDS  FarmLogType         3  EXTENDS  FarmQuantityType     2  IMPLEMENTS QuickFormInterface
 7  EXTENDS  FarmAssetType       5  EXTENDS  QuickFormBase        1  EXTENDS  FarmOrganizationType
 5  EXTENDS  FarmBrowserTestBase 2  EXTENDS  QuickFormActionBase  … + AssetLocation(Interface), a formatter, 1 notification iface
```

So the genuine cross-island domain seam is exactly one thing: **concrete plugins (`AnimalAsset`, `BirthLog`, a quantity type…) inherit their plugin-type base (`FarmAssetType`/`FarmLogType`/`FarmQuantityType`) which lives in the `core/entity` mega-island.** That is a real seam (the entity plugin-type contract), but it is a *scaffolding* seam, not behavioral coupling. Cross-island behavioral coupling (a domain call/construct from one module family to another) is **effectively nil in this graph**.

### Stability — do the boundaries survive framework-idiom pruning?

Prune every `external::` node and all edges touching one (4,517 edges dropped, 276 nodes), then re-run the identical partition and diff.

| metric | value |
|---|--:|
| ARI (baseline vs framework-pruned) | **0.9965** |
| nodes leaving their island's majority image | **11 / 7,783 (0.1 %)** |
| baseline island sizes | 3750, 3524, 319, 126, 121, 118, 46, 38, 11, 5, 1 |
| pruned island sizes | 3676, 3337, 316, 125, 121, 107, 46, 38, 11, 5, 1 |

**The boundaries are domain seams, not wiring artifacts.** Removing 100 % of the framework scaffolding — the very edges that make up 88 % of the boundary composition — leaves the partition essentially unchanged (ARI 0.9965; 0.1 % churn). The framework edges *span* the boundaries but do not *create* them; the islands are held together by domain containment/reference/locality, and the boundaries would sit in the same place with the scaffolding gone.

### Which boundaries are Drupal-wiring artifacts vs real domain seams — concretely

- **Real domain seams (survive prune, high persistence, ~0 framework-created):** all nine small islands — `asset/*`, `log/*`, `quick/*`, `organization/*`, `role/*`, `taxonomy/*`, `quantity/*`. These are genuine, stable module-family boundaries. The one cross-seam that carries meaning is the **plugin-type inheritance seam** (concrete plugin → `Farm{Asset,Log,Quantity}Type` base in `core/entity`).
- **Not wiring artifacts, but not clean either — directory-prior artifacts:** the two mega-islands. They are low-persistence (0.61) because the `dir-prior` at level 2 fuses everything under `modules/core/*` and everything under `web/profiles/farm/*` into one cohesion basin regardless of behavior. This is a *partition-dial* artifact (the directory prior), **not** a Drupal-wiring artifact — pruning framework edges does not split them (ARI 0.9965). Splitting them needs a resolution/dir-level change, not idiom pruning (see §Caveat).
- **No boundary in this graph is created by Drupal framework wiring.** The honest headline: the boundary *composition* is 88 % Drupal idiom, but the boundary *location* is 0 % Drupal idiom.

---

## Deliverable 2 — Restructure proposal & farmOS boundary disagreements

`ctkr restructure-proposal --data-dir <sandbox>` → `restructure-proposal.md` (sandbox). Summary:

- **11 proposed structural modules** (islands) over **123 declared modules** (features with ≥1 symbol in the graph; 147 total features, 23 declarative-only, 1 no-glob).
- **117 declared modules map 1:1 to a single island** — clean vertical slices. farmOS's declared boundaries agree with structure for the *domain* modules.
- **6 SPLIT disagreements**, **9 MERGE disagreements**, 254 element-level realign moves (each edge-justified).

### The disagreements (this is the validation)

**MERGE — the graph collapses farmOS's fine-grained `core` decomposition.** The largest disagreement: island `ss:d66d26fc` (3750 members, persistence 0.615) absorbs **81 declared modules** into one structural unit, and `ss:7044ab31` absorbs 16, `ss:761b7d53` 11. farmOS declares `core` as dozens of small modules (`farm_ui`, `farm_entity`, `farm_data_stream`, …) but the call/reference graph treats `modules/core/*` as **one interconnected mass** — its declared modularity is *organizational/declarative, not structural*. This is the single most important farmOS boundary disagreement: **farmOS core is modular on paper and monolithic in structure.**

**SPLIT — declared modules the graph scatters across islands** (6):

| declared module | # islands | reading |
|---|--:|---|
| `farm` (install profile) | 7 | the meta-package; expected to span everything |
| `farm_entity` | 3 | the entity API is declared as one module but its symbols distribute across core-blob + asset + log islands — a genuine cross-cutting concern |
| `farm_quick` | 2 | quick-form base vs concrete quick-forms land in different islands |
| `data_stream_notification`, `farm_id_tag`, `farm_quick_test` | 2 each | small bundling-vs-structure splits |

**Clean slices (117)** — every domain module family (`farm_animal`, `farm_activity`, `asset`, the `log/*`, `quantity/*`, `quick/*` concretes…) maps to exactly one island. For these, farmOS's declared boundary **is** the structural boundary — no restructuring warranted; they are good first port targets.

### Interpretation for the monolith use case

The prototype's designed use is a *monolith* → propose module boundaries. farmOS inverts the test: it is already finely modular, so the proposal's value is the **disagreement audit**. The result validates the mechanism twice: (1) where farmOS is genuinely modular (domain modules), the graph confirms it (117/147 clean, persistence ≈1.0); (2) where farmOS's module map is *aspirational* (core), the graph exposes it (81 modules → one low-persistence blob). A real monolith would have `n_declared_modules ≈ 1` and the same code path emits the islands as the proposed decomposition with the same edge-justified moves.

---

## Honest caveats

- **The directory prior dominates the two mega-islands.** `dir-prior` at `dir-level=2` gives every symbol a low-weight edge to a `modules/core`-level hub, which fuses `core/*` (and separately `web/profiles/farm/*`) into single basins at resolution 0.5. The nine small islands are robust to this; the two big ones are a dial artifact. A `--dir-level 3` / higher-resolution sweep would fracture `core` further — worth a follow-up, but out of scope here (the bead asked for boundary *quality* on the default partition, and the default is what downstream consumes).
- **Thin data alphabet (`scip_fraction=0.0`).** No `READS_FIELD`/`WRITES_FIELD`/`TYPE_OF` edges, so data-flow coupling across boundaries is invisible. The "0 cross-island CONSTRUCTS / 2 cross-island CALLS" finding is real for the edges we have, but a `--scip` reindex could surface data-flow seams the current alphabet cannot. Every number here is a lower bound on coupling.
- **Framework classification is name-blind and conservative.** `external::` is the sole driver of the 88.2 % (the in-repo Drupal-base regex adds 0 crossing edges on this graph — farmOS's own bases like `FarmLogType` are correctly *not* treated as framework). The split is robust to the heuristic toggle.

---

## Reproduce

```bash
# sandbox copy first (never touch the read-only source)
cp -R /private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2 <sandbox>
ctkr boundary-quality       --data-dir <sandbox>          # §Deliverable 1
ctkr restructure-proposal   --data-dir <sandbox>          # §Deliverable 2 → restructure-proposal.md
```

Tests: `ctkr/tests/test_boundary_quality.py` (7), `ctkr/tests/test_restructure.py` (5) — hermetic, synthetic graphs.
