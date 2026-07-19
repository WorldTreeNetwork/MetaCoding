# Feature × event-kind dependency graph — kernel-surface detector + wave scheduler (MetaCoding-9h5.21)

> Bead MetaCoding-9h5.21 · 2026-07-20 · the target-side complement to the composition
> run (`two-feature-composition-2026-07-20.md`, 9h5.16). That run proved the fan-out's
> real product is **one event log, one asset model, one ID scheme** shared by features
> whose projections overlap, and that N independent blind builders diverge on every
> shared axis — so a **shared kernel** must be frozen before wave 1. This run makes the
> kernel *mechanical instead of judged*: build the bipartite graph **features ↔ event
> kinds** straight off the committed build sources, and read the kernel surface and the
> wave schedule off the graph. Every 9h5.16 conflict is an edge here.

## Bottom line

- **The kernel surface is now computed, not adjudicated.** `ctkr feature-kinds` (new
  command + `ctkr/feature_kinds.py` lib, boundary_quality.py-shaped) extracts, per
  feature, the event kinds its **mutators emit** and its **projections fold** (with a
  **status-gated** flag), from a *name-blind, deterministic* parse of the composed build's
  `store.ts` + the two thin adapter views — **no LLM**. The two real features
  (logs+quantities, location+movement) yield a **2 features × 7 kinds, 17-edge** bipartite
  graph. The **kernel** (event kinds with cross-feature degree ≥2) is
  **`asset_created` and `log_status_changed`** — the identity substrate and the status
  channel — recovered mechanically.
- **Against the 9h5.16 prescription, the graph confirms 2 of its named conflicts as
  extracted degree-≥2 edges (status, asset-creation) and shows the other three
  (group-assignment, asset-archive, movement-vs-log) are *latent at n=2* — real, but not
  yet degree-2 because the composed single mind resolved each into one kind or one
  feature.** This is the honest reading, and it is the whole point of R1: the conflicts
  become shared edges only when a *second* feature folds the same kind. The
  movement-vs-log taxonomy split (CP2) is surfaced as a distinct **taxonomy tension**, not
  faked into a shared edge.
- **Wave scheduling reproduces R1 exactly.** On the 2 real features the graph is **one
  connected component** — they **must serialize through one builder** (they share
  `asset_created` + `log_status_changed`), which is precisely why the composed build
  worked and seven isolated builds diverged. Freeze the kernel and the two features
  **decouple into parallel singletons** — the kernel is the coupling.
- **Projected forward over the farmOS inventory (117 clean modules → 6 module-family
  proxies), all seven observed kinds become kernel, and the full graph collapses to one
  serialized blob** — the "core/mega-island" problem in graph form. Freezing only the
  *identity/lifecycle/status/membership* kernel (`asset_created`, `asset_archived`,
  `log_status_changed`, `group_assigned`) reveals the true parallel structure: one large
  **log/movement domain lane** that serializes through shared domain kinds, plus
  `asset+group` and `organization` that parallelize. **Projected edges are labelled
  `projected`; none is presented as extracted.**

## 1. What was extracted (deterministic, LM-free)

`ctkr feature-kinds` parses the composed build's `store.ts` name-blind: per store method
it reads emitted kinds from event-tag object literals (`type: "asset_created"`), folded
kinds from discriminant comparisons (`e.type === "asset_created"`), transitively closes
over intra-class helper calls (so `assetsAtLocation` inherits the `movement_recorded`
fold through `latestMovement`), and flags a fold **status-gated** when the method filters
on a status value (`movementStatus(e) === "done"`). Each feature's methods are attributed
by which `store.<method>(…)` calls its thin adapter view makes — so the *same* shared
store yields *per-feature* emit/fold profiles. Inputs are the committed ground truth:
`eval/ctkr/port_runs/compose-9h5.16/build/src/{store,logsAdapter,locationAdapter}.ts`.

### Extracted bipartite graph — 2 real features × 7 event kinds (17 edges)

| feature | event kind | emit | fold | status-gated |
|---|---|:--:|:--:|:--:|
| logs+quantities | `asset_created` | ● (createAsset) | | |
| logs+quantities | `log_recorded` | ● (recordLog) | ● (logStatus, logCount, quantityRecorded) | |
| logs+quantities | `log_status_changed` | ● (setStatus) | ● (logStatus) | |
| logs+quantities | `group_assigned` | ● (assignToGroup) | ● (groupMember) | |
| logs+quantities | `asset_archived` | ● (archiveAsset) | ● (assetActive) | |
| location+movement | `asset_created` | ● (createAsset) | ● (isFixed, isLocation, currentGeometry, currentLocations…) | |
| location+movement | `movement_recorded` | ● (recordMovement) | ● (currentLocations, assetsAtLocation…) | **● (done-gated)** |
| location+movement | `log_status_changed` | ● (setStatus) | ● (movementStatus via currentLocations…) | |
| location+movement | `geometry_set` | ● (setIntrinsicGeometry) | ● (currentGeometry, hasGeometry) | |

(● = edge present. `via` methods are carried in the JSON artifact.)

### Mermaid — the extracted graph (kernel kinds are the pink diamonds)

```mermaid
graph LR
  F_logs_quantities["logs+quantities"]
  F_location_movement["location+movement"]
  K_asset_archived("asset_archived")
  K_asset_created{"asset_created"}
  K_geometry_set("geometry_set")
  K_group_assigned("group_assigned")
  K_log_recorded("log_recorded")
  K_log_status_changed{"log_status_changed"}
  K_movement_recorded("movement_recorded")
  F_location_movement --> K_asset_created
  F_location_movement -.-> K_asset_created
  F_location_movement --> K_geometry_set
  F_location_movement -.-> K_geometry_set
  F_location_movement --> K_log_status_changed
  F_location_movement -.-> K_log_status_changed
  F_location_movement --> K_movement_recorded
  F_location_movement -.->|gated| K_movement_recorded
  F_logs_quantities --> K_asset_archived
  F_logs_quantities -.-> K_asset_archived
  F_logs_quantities --> K_asset_created
  F_logs_quantities --> K_group_assigned
  F_logs_quantities -.-> K_group_assigned
  F_logs_quantities --> K_log_recorded
  F_logs_quantities -.-> K_log_recorded
  F_logs_quantities --> K_log_status_changed
  F_logs_quantities -.-> K_log_status_changed
  classDef kernel fill:#f9d,stroke:#933,stroke-width:2px;
  class K_log_status_changed K_asset_created kernel;
```

Solid = emit, dashed = fold, `|gated|` = status-gated fold. The one gated edge in the
whole graph is `location+movement -.->|gated| movement_recorded` — the composed build's
"only *done* movements apply to current location" rule, extracted mechanically. This is
the status-semantics-contract axis (kernel prescription item 4) showing up as a concrete
flag on a concrete edge.

## 2. Kernel surface — confirmation vs the 9h5.16 prescription (honest)

Kernel = event kinds with **cross-feature degree ≥2** (touched by ≥2 distinct features,
emitting or folding). Degrees over the 2 real features:

| event kind | degree | emit features | fold features | kernel? |
|---|:--:|---|---|:--:|
| `asset_created` | **2** | logs, location | location | **★ kernel** |
| `log_status_changed` | **2** | logs, location | logs, location | **★ kernel** |
| `asset_archived` | 1 | logs | logs | — |
| `geometry_set` | 1 | location | location | — |
| `group_assigned` | 1 | logs | logs | — |
| `log_recorded` | 1 | logs | logs | — |
| `movement_recorded` | 1 | location | location | — |

The 9h5.16 shared-kernel prescription named a conflict set: **group-assignment, status,
asset-creation/archive, movement-vs-log taxonomy**. Scored against the *extracted* graph:

| prescription conflict | graph verdict | evidence |
|---|---|---|
| **status** (`log_status_changed`) | **CONFIRMED — degree-2 kernel** | emitted by *both* features (`setLogStatus`) and folded by *both* (logs `logStatus`; location `movementStatus`). The single shared status channel is real and mechanically found. |
| **asset-creation** (`asset_created`) | **CONFIRMED — degree-2 kernel** | both features mint via the shared `createAsset`; location also folds it (`isFixed`/`isLocation`/geometry). The one asset model = one shared kind. |
| **asset-archive** (`asset_archived`) | **LATENT (degree 1)** | only logs touches archive in this slice (`archiveAsset`→`assetActive`); location has no archive-aware read, so no shared edge *yet*. Becomes kernel the moment any location/inventory read must respect archival. |
| **group-assignment** (`group_assigned`) | **LATENT (degree 1)** | only logs (`assignToGroup`→`groupMember`). The prescription's specific fear — `location.assetsAtLocation` folding group events — **did not occur**: `assetsAtLocation` folds `movement_recorded` + `asset_created`, not `group_assigned`. That conflict is a *projected* fan-out edge, not one the single-mind build created. |
| **movement-vs-log taxonomy** | **LATENT — surfaced as a taxonomy tension, not a shared edge** | the composed mind kept `log_recorded` (logs) and `movement_recorded` (location) as **distinct** kinds (CP2's free choice), so they are two degree-1 nodes. The detector flags them as a cross-feature `*_recorded` pair that logs' **kind-filtered** `logCount` would collapse if a builder modeled movements as activity logs (as farmOS does). Latent, correctly not faked into degree-2. |

**Honest headline:** with only 2 real features, **2 of the 5 kernel elements manifest as
extracted degree-≥2 edges** (the identity/asset kind and the status kind). The other three
are *real but latent at n=2* — a conflict needs a *second* feature to fold the same kind,
and the single composed mind resolved each into one kind (taxonomy) or one feature
(archive, group). This is not a miss of the method; it is the method correctly reporting
that **n=2 under-determines the kernel** — exactly R1's point that the danger is N
builders, not one. §3 shows every named conflict *does* become a degree-≥2 kernel edge
once more features enter.

## 3. Projected wave structure for the fan-out (projections labelled as projections)

To forecast the fan-out we add **6 projected features**, one per clean farmOS module
family from the boundary map (`boundary-quality-farmos-v2-2026-07-20.md`: 117/147 modules
map 1:1 to a domain island — asset/group, log/birth/input, quick/movement/inventory,
quantity, taxonomy, organization). Each family's emit/fold kinds are **guesses from module
family**, tagged `provenance="projected"` and **never mixed into the extracted
kernel table above**. New guessed kinds beyond the 7 observed carry a `?` marker
(`inventory_adjusted?`, `term_assigned?`).

**Projected kernel (8 features).** Every one of the seven *observed* kinds crosses
degree-≥2 once the families join — the full 9h5.16 conflict set materializes:

| kind | projected degree | now shared by (families) |
|---|:--:|---|
| `asset_created` | 5 | logs, location, asset+group, logs+birth+input (+ organization folds) |
| `log_recorded` | 5 | logs, logs+birth+input, quantity, quick+movement+inventory (+ taxonomy folds) |
| `group_assigned` | 3 | logs, asset+group, organization |
| `log_status_changed` | 3 | logs, location, logs+birth+input |
| `asset_archived` | 2 | logs, asset+group |
| `geometry_set` | 2 | location, quick+movement+inventory |
| `movement_recorded` | 2 | location, quick+movement+inventory |

So **group-assignment and asset-archive and the movement/geometry kinds all become kernel
edges under the fan-out** — confirming the prescription's full set, but honestly, as
*projections* contingent on the module-family kind guesses.

**Wave clusters.**

- **Full graph (kernel counted): one serialized blob of all 8 features**, coupled through
  `asset_created` + `log_status_changed` + `log_recorded` + `group_assigned`. This is the
  boundary report's "core is monolithic in structure" finding in event-kind form: *the
  kernel is the monolith*. Nothing parallelizes while the kernel is a live coupling.
- **Freeze the identity/lifecycle/status/membership kernel** (`asset_created`,
  `asset_archived`, `log_status_changed`, `group_assigned`) — i.e. ship it as R1 demands —
  and the domain lanes emerge:

  | cluster | size | features | serializes through |
  |---|:--:|---|---|
  | log/movement domain lane | 6 | location+movement, logs+quantities, logs+birth+input, quantity, quick+movement+inventory, taxonomy | `log_recorded`, `movement_recorded`, `geometry_set` |
  | asset+group | 1 | asset+group | — (parallel-ok) |
  | organization | 1 | organization | — (parallel-ok) |

  The 6-feature lane is chained because the **`quick+movement+inventory`** family (guessed
  to emit *both* `log_recorded` and `movement_recorded`) **bridges** the pure-logs
  features and the location/movement features — a real structural prediction (farmOS quick
  movements *are* activity logs), but flagged: it rests on that guessed dual-emit edge.
  Freezing the domain kinds too (i.e. a per-kind expert builder owns each) splits this lane
  into a logs lane and a location/movement lane that parallelize.

**Wave reading for the fan-out:** ship the kernel first (wave 0); then features
parallelize *only* to the extent they don't share a live domain kind. The graph names the
serialization chains up front — `quick` cannot be built independently of both the logs
expert and the location expert unless the movement-vs-log taxonomy is frozen first.

## 4. Limits (the projections are projections)

- **n=2 real features.** The extracted kernel (`asset_created`, `log_status_changed`) and
  the "one serialized cluster" wave are solid, but two features **under-determine** the
  kernel by construction — three of the five prescribed conflicts are latent here and only
  confirmed under projection. Treat the extracted graph as ground truth and everything in
  §3 as forecast.
- **The projected families are kind-*guesses* from module family**, not extracted edges.
  `inventory_adjusted?`/`term_assigned?` are invented kind names; the `quick` dual-emit
  bridge that creates the 6-feature lane is the single load-bearing guess. A real port of
  each family (via `ctkr propose-adapter` + `mine-fixtures`, then this extractor over the
  build) would replace each projected profile with an extracted one.
- **Ground truth is one coherent mind's build.** The composed `store.ts` is what *one*
  Sonnet builder chose (movements distinct from logs, one `pickLatest`, integer IDs). The
  taxonomy tension and the latent group/archive edges are exactly the axes where a
  *different* blind builder would diverge — which is why they belong in the kernel, and why
  a bipartite graph over *independent* per-feature builds (not one composed build) would
  show *more* conflict, not less. This run reads the friendliest possible target; the
  fan-out's is harsher.
- **Deterministic parser scope.** Extraction assumes prettier/biome 2-space class-member
  formatting (every committed build uses it) and the farmOS status-gate idiom
  (`*Status(…) === "…"` / `.status === "…"`). The terra prose fallback exists and is
  tested (mock provider) for contracts with no build source, but was **not needed** for the
  two real features — both had committed build sources, so this run is **100% LM-free**.

## 5. What shipped

New `ctkr` command + core + tests (production code, on the worktree branch — NOT pushed):

- `ctkr/ctkr/feature_kinds.py` — the lib: `FeatureKindProfile` schema; `extract_from_build`
  (deterministic name-blind TS parse with transitive fold closure + status-gate detection);
  `build_terra_fallback_prompt`/`extract_from_prose` (prose fallback, repair retry, cites
  contract line); `build_graph`; `kernel_surface`; `taxonomy_tensions`; `wave_schedule`
  (with `freeze_kinds`); `projected_profiles` + `PROJECTED_FAMILY_KINDS`; `render_mermaid`.
- `ctkr/ctkr/commands/feature_kinds.py` — the `ctkr feature-kinds` CLI (`--store`/
  `--feature NAME=adapter.ts`, `--prose NAME=contract.md`, `--project`, `--freeze-kernel`,
  `--out-json`, `--out-mermaid`, `--json`).
- `ctkr/tests/test_feature_kinds.py` — **13 hermetic tests** (synthetic TS contracts for
  extraction incl. status-gating + transitive fold; graph aggregation; kernel degree/
  threshold; taxonomy tension; wave serialize/freeze/disjoint; projected labelling; mermaid;
  mock-provider prose fallback).
- This report.

**Quality gates:** `ctkr` full suite **green** (all pass, 1 pre-existing skip); `ruff
check` on the three new files **clean**. The two real features extract **17 edges over 7
kinds, LM-free**.

## 6. Artifacts & sandbox paths (ALL sandbox unless noted)

- **In-repo committed (production):**
  `eval/ctkr/results/feature-kind-graph-2026-07-20.md` (this report) + the three `ctkr/`
  code files above. **No `.metacoding/` data-dir created or mutated.**
- **Inputs consumed (in-repo, read-only, GROUND TRUTH):**
  `eval/ctkr/port_runs/compose-9h5.16/build/src/{store,logsAdapter,locationAdapter,types}.ts`
  (the composed 9h5.16 build) and `boundary-quality-farmos-v2-2026-07-20.md` (the module
  families for §3's projection).
- **Graph artifacts (SANDBOX):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/m21/`
  — `graph_real.json` (2-feature extracted graph + edges), `graph_projected.json`
  (8-feature projected graph), `graph_real.mermaid`. These are reproducible from the
  committed sources by re-running `ctkr feature-kinds`; nothing downstream consumes them.
- **LLM spend: $0.00** — the run is fully deterministic (no `--prose`, no terra). Well
  under the $2 cap.

No push / no merge; bead MetaCoding-9h5.21 left open.
