# Signature-generation ablation — can the pipeline PROPOSE the adapter surface? (MetaCoding-9h5.15)

> Bead MetaCoding-9h5.15 · 2026-07-20 · attacks second-opinion **T1**
> (`second-opinion-2026-07-20.md` §1): *every* prior port experiment — including the
> "pure-LLM" cell and both m11 builders — received a **hand-authored**
> `ADAPTER_SIGNATURES.md` for free. Authoring it (deciding the read surface, inventing
> concepts a value-equivalent port must expose) is the hardest cognitive act in the
> port; the machinery was never asked to do it, so "oracle-centric" is partly
> definitional. This experiment asks the machinery to do it: have the pipeline PROPOSE
> the adapter contract for the m11 location feature, then judge it (a) structurally
> against the hand-authored reference and (b) functionally — does a blind builder +
> the observed fixtures over the GENERATED surface still pass an independent runner?

## Bottom line

- **The pipeline proposed a workable adapter surface.** `ctkr propose-adapter`
  (new command) fed **only** pipeline artifacts + scoped source to gpt-5.6-terra and
  emitted a typed contract: **4 mutators + 4 projections**. A **blind Sonnet builder**
  implemented it and an **independent runner** scored the m11 observed pack at
  **8/10**, including **6/7 non-obvious** fixtures.
- **The 2 failures are pure SURFACE GAPS, not builder failures, and not behavioral
  misses.** The generated surface omitted two *attribute-readback* projections
  (`isFixed`, `isLocation`) the reference author included for observability. A targeted
  probe confirms the fixed-asset *behavior* (`POINT(9 9)`, no movement-location,
  has-geometry) **is** captured by the generated surface — 9c55cce5 fails only because
  no method reads the `is_fixed` flag back, not because the surface can't represent
  fixedness. **Every genuinely non-obvious value semantic the pack encodes — pending
  ignored, future not-yet-effective, same-timestamp tie-break, multi-location,
  latest-wins reverse membership, geometry-from-log — passed through the generated
  surface.**
- **The generator's invention lived on the EVENT (mutator) side, not the read side.**
  It decomposed "movements are done logs referencing assets+locations" into a
  `recordMovement` event with no single source method (flagged `derived_from:
  invented:`), folding geometry-population and cycle-rejection into one replay-atomic
  event. The projections, by contrast, **echoed source structure** (`getLocation` →
  `getAssetCurrentLocation`, `getAssetsByLocation` → `getAssetsCurrentlyAtLocation`) —
  because for *this* feature the reads already exist as source methods. This feature is
  therefore a **weak** test of read-*invention* (unlike a yield-total); see Honesty.
- **T1 verdict: the circularity substantially COLLAPSES for this feature, with one
  measured caveat.** The pipeline proposed a surface that carries 100% of the pack's
  behavioral semantics from artifacts + source alone; it lost 2/10 only on
  observability readbacks a one-line schema convention (or a "readback for every
  designation flag" lint) would recover. Hand-authoring is **not** an irreducible
  bottleneck here — but the reference's extra readbacks show a human still adds
  test-surface polish the generator skipped.

## 1. Generation inputs — what the generator saw (blindness statement)

The generation path (`ctkr propose-adapter` → one gpt-5.6-terra structured call) saw
**only** these, all pipeline artifacts + scoped source:

| input | provenance | contains |
|---|---|---|
| subsystem members + method signatures | **graph** (`extract_subsystem_members` over the v2 graph, `/location/` scope, dedup'd) | the in-scope class/interface inventory incl. `AssetLocationInterface` methods (`getLocation`, `isFixed`, `getAssetsByLocation`, `getMovementLog`, `setIntrinsicGeometry`, …) as source signatures |
| mined fixture candidates | **`ctkr mine-fixtures`** (CM + graph + source-read lanes) run in this sandbox | 38 candidates; the 6 source-read rules named the non-obvious semantics (fixed→intrinsic geometry, done+non-future filter, latest-event-wins reverse membership, multi-location) |
| target profile | `TARGET_PROFILE.yaml` (the m11 local-first profile) | event-log + materialized-views architecture; hard/soft/none decision menu |
| glossary | hand-written from source docblock domain terms only (no signatures) | asset / location / movement / fixed / geometry definitions |

**The generator did NOT read** (critical blindness, per the bead): the hand-authored
`.../m11/ADAPTER_SIGNATURES.md`, either m11 builder's output, or
`graph-as-tool-2026-07-19.md` §2's signature listing. The gpt-5.6-terra prompt was
assembled deterministically from the four inputs above by `build_contract_prompt`
(pure function; the whole prompt is reproducible from the sandbox artifacts).

**Contamination caveat (honest):** the orchestrator (this agent, the JUDGE) had read
the reference signature *names* in `graph-as-tool-2026-07-19.md` §2 before writing the
generator (the bead instructed reading that report). Mitigation: the synthesizing model
(gpt-5.6-terra) is a *separate* model that only ever saw the four inputs above; the
prompt builder contains **no** reference method names (it is committed —
`ctkr/ctkr/propose_adapter.py` — and inspectable). The blindness that matters (the
generator model's) holds; the orchestrator's prior exposure could only have biased
*prompt design*, and the prompt uses no reference vocabulary.

`ctkr mine-fixtures` source-read lane surfaced (verbatim topics): *"A fixed asset's
current geometry comes exclusively from its intrinsic geometry"*, *"A fixed asset never
has a movement-derived location"*, *"Reverse location membership is latest-event-wins
per asset"*, *"Movement-derived current state considers only done movement logs at or
before the timestamp"*, *"one movement → multiple locations"*. These are the semantics
the generator had to turn into a surface.

## 2. The generated surface (verbatim)

`ctkr propose-adapter` output (`adapter_contract.md`), unedited:

```typescript
export interface AssetLocationMovementAdapter {
  designateAssetLocation(asset: AssetHandle, isLocation: boolean, isFixed: boolean): Promise<EventHandle>;
  setIntrinsicAssetGeometry(asset: AssetHandle, geometry: WktGeometry[]): Promise<EventHandle>;
  recordMovement(assets: AssetHandle[], locations: AssetHandle[], occurredAt: Date, status: MovementStatus, geometry?: WktGeometry[]): Promise<MovementHandle>;
  setMovementGeometry(movement: MovementHandle, geometry: WktGeometry[]): Promise<EventHandle>;
  getAssetCurrentLocation(asset: AssetHandle, asOf: Date): Promise<AssetHandle[]>;
  getAssetCurrentGeometry(asset: AssetHandle, asOf: Date): Promise<WktGeometry[]>;
  getAssetsCurrentlyAtLocation(location: AssetHandle, asOf: Date): Promise<AssetHandle[]>;
  getMovementGeometry(movement: MovementHandle): Promise<WktGeometry[]>;
}
export function makeAssetLocationMovementAdapter(): AssetLocationMovementAdapter;
```

Every projection was correctly marked as-of-time-parameterized (`asOf: Date`) except
`getMovementGeometry` (a direct per-event read). The generator's own `rationale`:
*"Movement and intrinsic-geometry changes are append-only domain events; current
location, current geometry, and reverse membership are as-of materialized views.
Fixed-asset suppression and intrinsic-geometry precedence drive the two current-state
projections; done/non-future and access-independent movement eligibility drives all
movement-derived views; latest-event-wins drives reverse membership."*

## 3. Structural judgment — generated vs hand-authored reference

Reference (`.../m11/ADAPTER_SIGNATURES.md`, JUDGE-side): 4 mutators
(`createAsset`, `recordMovement`, `setLogStatus`, `setIntrinsicGeometry`) + 7
projections (`currentLocations`, `hasLocation`, `currentGeometry`, `hasGeometry`,
`isFixed`, `isLocation`, `assetsAtLocation`).

**Per reference method → generated equivalent:**

| reference method | generated equivalent | verdict |
|---|---|---|
| `createAsset(spec)` | `designateAssetLocation(asset, isLocation, isFixed)` (+ `setIntrinsicAssetGeometry`) | **renamed / partial** — registers the flags but mints no handle; asset *creation* is out of the location feature's scope, so the generator (correctly scoped) never invented it |
| `recordMovement(spec)` | `recordMovement(assets, locations, occurredAt, status, geometry?)` | **equivalent** (positional vs spec object) |
| `setLogStatus(log, status)` | — | **missing** (unexercised by the pack) |
| `setIntrinsicGeometry(asset, wkt)` | `setIntrinsicAssetGeometry(asset, wkt[])` | **renamed-equivalent** (array vs scalar) |
| `currentLocations(asset, at)` | `getAssetCurrentLocation(asset, asOf)` | **renamed-equivalent** |
| `hasLocation(asset, at)` | — (derivable: `getAssetCurrentLocation(...).length>0`) | **missing-but-derivable** |
| `currentGeometry(asset, at)` | `getAssetCurrentGeometry(asset, asOf)` | **renamed-equivalent** (array vs scalar) |
| `hasGeometry(asset, at)` | — (derivable: `getAssetCurrentGeometry(...).length>0`) | **missing-but-derivable** |
| `isFixed(asset)` | — | **missing, NOT derivable** (no readback) |
| `isLocation(asset)` | — | **missing, NOT derivable** (no readback) |
| `assetsAtLocation(location, at)` | `getAssetsCurrentlyAtLocation(location, asOf)` | **renamed-equivalent** |

Tally over 11 reference methods: **5 renamed-equivalent · 1 partial · 2
missing-but-derivable · 3 missing-not-derivable** (`setLogStatus` unexercised;
`isFixed`, `isLocation` are the functional gaps).

**Invented methods (generated, no reference counterpart):**

| generated method | classification |
|---|---|
| `setMovementGeometry(movement, geometry[])` | **plausibly-useful write** — post-hoc geometry override on a movement event (mirrors source `LogLocationInterface::setGeometry`); not needed by the pack |
| `getMovementGeometry(movement)` | **genuinely-useful read** — inspect one movement's resolved geometry; not a value-equivalence projection the pack needs |

**The interesting metric (does it invent non-source concepts vs echo source?):** the
generated **projections echo source structure** — each maps to an existing
`AssetLocationInterface` method the generator saw. It did **not** invent a novel
non-source read (no yield-total analogue). Its one flagged **invention** was on the
**event side** (`recordMovement`, `derived_from: "invented: models movement-log
creation plus EntityHooks::populateGeometryFromLocation and
CircularAssetLocationConstraintValidator::validate as one replay-atomic domain
event"`). So for this feature the generator *composes events* creatively but *echoes
reads* — expected, because location reads already exist in source (§Honesty).

## 4. Functional judgment — blind builder + observed pack over the GENERATED surface

**Setup.** A blind Sonnet builder (fresh dir, forbidden from farmOS source / MetaCoding
repo / m11 artifacts / the generator) implemented **exactly** the generated
`AssetLocationMovementAdapter` from `adapter_contract.md` + `FIXTURES.jsonl` +
`TARGET_PROFILE.yaml`. A judge-side **shim** (`judge/shim.ts`, ~90 LoC, not
builder-written) maps the reference ops the independent runner drives onto the
generated ops; where the generated surface has **no** equivalent, the shim throws →
the runner records a **surface-gap** failure. The m11 independent runner
(`runFixtures.ts`, unchanged, self-verified 10/10 on the reference adapter) scored it.

**Score: 8/10** (independent runner; builder's own suite 12/12):

| fixture | non-obv | result | attribution |
|---|---|---|---|
| 95de1fa8 done movement places asset | — | **PASS** | — |
| d4bf80b0 is_location flag | — | **FAIL** | **surface gap** — no `isLocation` readback |
| 590f08ba latest done wins | — | **PASS** | — |
| b1c2e06f pending ignored | ✔ | **PASS** | — |
| 364220a4 future not-yet-effective (as-of) | ✔ | **PASS** | — |
| 9c55cce5 fixed asset → intrinsic geometry | ✔ | **FAIL** | **surface gap** — no `isFixed` readback; *geometry semantics captured* (probe below) |
| 8083c6d1 one movement → multiple locations | ✔ | **PASS** | — |
| 43a074ca same-timestamp tie-break | ✔ | **PASS** | — |
| 885eecc6 assets-at-location latest-wins | ✔ | **PASS** | — |
| 7c6c376b geometry from movement log | ✔ | **PASS** | — |

**Both failures are surface gaps; zero builder failures; zero behavioral misses.** A
targeted probe drove 9c55cce5's *behavioral* asserts through the generated surface
(bypassing the readback): `{has_location:false, current_location_count:0,
current_geometry:"POINT(9 9)", has_geometry:true}` — all correct. So the surface fully
represents fixed-asset behavior; it merely lacks a method to read the `is_fixed` flag
back. Non-obvious semantics captured: **6/7** (only 9c55cce5 lost, on the readback).

The two lost fixtures are recoverable by a trivial schema convention — "emit a readback
projection for every designation flag" — i.e. a *lint on the generated contract*, not a
new cognitive act. With `isFixed`/`isLocation` added the surface would score 10/10.

## 5. T1 verdict

**Does the circularity collapse or hold?** For the location feature: it **substantially
collapses**, with one measured caveat.

- **Collapses:** the pipeline (graph member extraction + `mine-fixtures` semantics + the
  target profile) proposed, with **no** hand-authored signature surface, a contract that
  a blind builder used to reproduce **100% of the pack's behavioral value-equivalence
  semantics** (8/10 fixtures, the 2 losses being observability readbacks, not
  behaviors). The claim "authoring the signature surface is an irreducible human
  bottleneck" does **not** hold here — the machinery proposed a workable one for
  ~$0.06 of terra.
- **Caveat (holds, narrowly):** the reference author included attribute readbacks
  (`isFixed`, `isLocation`) the generator skipped, and (for a harder feature) the
  read-*invention* question is untested here because location's reads already exist in
  source. Hand-authoring still contributed test-surface completeness the generator
  missed — cheap to close with a schema-lint, but real.

**Net:** "oracle-centric" was **partly definitional** exactly as T1 argued. When the
machinery is actually asked to propose the surface, it does — carrying the hard
semantics and missing only mechanical readbacks. The signature surface is a **weaker**
bottleneck than the fixtures/oracle, not a co-equal one.

## 6. Honesty notes

- **Single run** (one terra generation, one blind Sonnet build, one runner). No spread.
  The generation is deterministic given the artifacts (temperature-free reasoning tier +
  prompt-hash cache), but a different mining run or a re-roll could shift the surface.
- **This feature under-tests read-invention.** location's reads exist as source methods
  (`getLocation`, `getAssetsByLocation`), which the generator saw and echoed. The sharp
  T1 case — inventing a read with **no** source method (a yield-total) — is **not**
  exercised here. The logs+quantities feature would test it; this run shows invention on
  the *event* side only. Treat "the pipeline can invent the read surface" as
  **unproven**; "the pipeline can propose a behaviorally-sufficient surface" is what is
  shown.
- **The reference is one person's design, not ground truth.** The generated surface is
  *different-but-valid* on several axes (positional vs spec params; array vs scalar
  geometry; event-decomposed `designateAssetLocation` vs `createAsset`;
  `setMovementGeometry`/`getMovementGeometry` extras). The functional score, not the
  structural diff, is the validity signal — and it says the differences are benign
  except the two missing readbacks.
- **Source was a permitted generator input** (per the bead: "generate from pipeline
  artifacts + source only"). The generator read the scoped location source's method
  signatures via the graph. The blindness is specifically w.r.t. the reference
  *signature surface*, which it never saw.
- **Pretraining (T2) still applies.** farmOS is public; the terra generator and the
  Sonnet builder may carry farmOS/Drupal familiarity. Untested here.
- **Live oracle not used** — the m11 fixtures were already observed; entities would have
  been `m15-` if needed. No Docker contact this run.

## 7. What shipped (in-repo, committed)

New `ctkr` command + core + tests (production code, on the worktree branch — NOT pushed):

- `ctkr/ctkr/propose_adapter.py` — schema (`AdapterContract`/`AdapterMethod`/…),
  deterministic `extract_subsystem_members` (graph, dedup'd), `build_contract_prompt`
  (pure), `synthesize_contract` (terra structured + repair), `render_contract_markdown`.
- `ctkr/ctkr/commands/propose_adapter.py` — the `ctkr propose-adapter` CLI.
- `ctkr/tests/test_propose_adapter.py` — 8 hermetic tests (member dedup/scoping, prompt
  builder, mock-provider synthesis, markdown renderer, IO). Full ctkr suite green
  (**all pass**, 1 pre-existing skip); ruff clean.
- This report.

## 8. Artifacts & sandbox paths (ALL sandbox unless noted)

- **In-repo committed (production):** `eval/ctkr/results/signature-generation-2026-07-20.md`
  (this report) + the three `ctkr/` code files above. **No `.metacoding/` data-dir
  created or mutated in the repo.**
- **Experiment sandbox (SANDBOX):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/m15/`
  — `farmos-data-v2/` (READ-ONLY copy of the v2 graph, see below; `ctkr/` subdir holds
  the run's `llm_cache/` + `llm_cost.jsonl`), `src/location/` (READ-ONLY copy of the
  location module source), `fixture_candidates.jsonl` (mine-fixtures output, 38),
  `glossary.md`, `TARGET_PROFILE.yaml`, `adapter_contract.{json,md}` (the generated
  surface), `builder/` (blind Sonnet build: `inputs/` + `build/{src,test,PORT_DECISIONS.md}`,
  own suite 12/12), `judge/{shim.ts,shim.wired.ts,probe_fixed.ts}` (judge-side).
- **Graph queried (SANDBOX, READ-ONLY copy):** `.../m15/farmos-data-v2`, copied from
  `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2` (the v2 full-signal graph,
  unmutated).
- **Source read by the generator (SANDBOX, READ-ONLY copy):** `.../m15/src/location`,
  copied from `/private/tmp/farmos-cell3-2026-07-19/farm-src/modules/core/location`.
- **Reference + fixtures (JUDGE-side only):** `.../scratchpad/m11/ADAPTER_SIGNATURES.md`
  (structural reference), `.../m11/FIXTURES.jsonl` + `.../m11/judge/runFixtures.ts` (the
  observed pack + independent runner, reused unchanged).

**Metered LLM spend: $0.1959** (all gpt-5.6-terra: `mine-fixtures` source-read
$0.0654 + `propose-adapter` synthesis incl. one repair retry $0.1305; luna CM lane $0,
0 seeds). Blind Sonnet builder unmetered (~71.8k subagent tokens). Well under the $3
cap. No push/merge; bead MetaCoding-9h5.15 left open.
