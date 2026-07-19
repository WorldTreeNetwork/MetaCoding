# Build task — port TWO features into ONE shared local-first store

You are porting a farm record-keeping system to a new **local-first** runtime.
Unlike a single-feature port, you must implement **two features over ONE unified
store**: they share one append-only event log, one asset/entity model, and one
ID scheme. You will NOT see the original system's source code.

## Your inputs (in this `inputs/` dir — the ONLY files you may read)

- `ADAPTER_CONTRACT_LOGS.md` — the logs+quantities feature's adapter interface
  (`OracleAdapter`): assets, logs of a `kind`, quantities, group membership,
  archival, yield totals, log counts.
- `ADAPTER_SIGNATURES_LOCATION.md` — the location+movement feature's adapter
  interface (`LocationAdapter`): assets that can be locations / fixed, movement
  events with `atTimestamp` reads, current location & geometry projections.
- `FIXTURES_LOGS.jsonl` (17) — observed behavioral fixtures for the logs feature.
- `FIXTURES_LOCATION.jsonl` (10) — observed behavioral fixtures for the location
  feature. Each `then` value was recorded from the real system; your port must
  reproduce every one across BOTH packs.
- `TARGET_PROFILE.yaml` — the local-first target architecture and the menu of
  legal answers for each consistency-model decision.

## The hard requirement — ONE store, not two

This is the point of the exercise. Both adapters MUST be **thin views over the
SAME append-only event log**. Concretely:

1. **One append-only event log.** Every mutation from either feature
   (`createAsset`, `recordLog`, `setLogStatus`, `assignToGroup`, `archiveAsset`,
   `recordMovement`, `setIntrinsicGeometry`) appends to the SAME log. There must
   be exactly one log array/structure in your store. NO parallel per-feature
   stores.
2. **One asset/entity model.** An asset created through either adapter lives in
   ONE shared asset space. An asset created via the logs adapter must be
   referenceable by the location adapter and vice-versa — they are the same asset.
3. **One ID scheme.** Handles minted by either adapter come from the same minting
   function and are drawn from one identity space.
4. **Both reads are projections over that one log.** No read returns a mutated-in-
   place field; each recomputes from the shared log.

## Required exports

Create `src/store.ts` (or similar) and export from `src/index.ts`:

```ts
// The composed store: both adapters wired to ONE shared event log + asset model.
export function createComposedStore(): {
  logs: OracleAdapter;          // exactly the ADAPTER_CONTRACT_LOGS.md interface
  location: LocationAdapter;    // exactly the ADAPTER_SIGNATURES_LOCATION.md interface
};
```

Both returned adapters MUST share the one underlying log/asset store created by
that single `createComposedStore()` call. Two calls create two independent stores;
one call's `.logs` and `.location` share everything.

Also re-export the two interface types (`OracleAdapter`, `LocationAdapter`, and
their spec types) so an external runner can import them.

## PORT_DECISIONS.md — required, and this is graded

Document **every** design decision in `build/PORT_DECISIONS.md`. In particular,
be explicit and concrete about how the ONE log serves OVERLAPPING projections:

- **Event schema.** The exact event kinds and fields of your single log. How does
  a movement event relate to a log event? Is a movement a kind of log, or a
  distinct event kind? Does a movement count in `logCount`? State your choice.
- **ID / handle minting.** One scheme for assets, logs, movements. Describe it.
- **Asset model.** One asset record shared by both features. How do
  `isLocation`/`isFixed`/`intrinsicGeometry` (location feature) and
  `entity`/`name`/`descriptor` (logs feature) coexist on one asset?
- **Membership model.** The logs pack's group reassignment is **latest-wins**
  (assigning to a new group revokes the prior — see fixture behavior). The
  location pack's `assetsAtLocation` / current-location is also **latest-wins**
  (moving away removes the asset). Both fold the SAME log. State the ONE
  fold/tie-break rule you use for "latest wins" and confirm it serves both reads.
- **Tie-break scheme.** When two events share a timestamp (or a mutation has no
  timestamp), what breaks the tie — insertion sequence, a UUID, a hybrid logical
  clock? State the ONE scheme used everywhere. Note the location pack has a
  same-timestamp fixture; the logs pack has un-timestamped mutations
  (`assignToGroup`, `archiveAsset`, `setLogStatus`).
- **Pending / status semantics — note the divergence.** In the logs feature a
  **pending** log STILL contributes to `yield_total` and `logCount`. In the
  location feature a **pending** movement does NOT change current location. Same
  `status` field on the shared log, opposite treatment per projection. Document
  how your projections read `status` differently and why that is consistent with
  one shared event schema.
- **Birth-log uniqueness (CM-hard).** If you model a `birth` log kind and its
  "at most one birth log per asset" invariant, state your menu choice from
  `TARGET_PROFILE.yaml` (preserve-via-convergence-rule / weaken-to-eventual /
  move-to-disclosure-layer) and why. (No shipped fixture exercises it; this is a
  design-notes deliverable.)

## What to build in `build/`

1. `src/*.ts` — the composed store + both adapters as thin views.
2. `src/index.ts` exporting `createComposedStore()` and the interface types.
3. `test/*.test.ts` — your own `bun test` suite derived from BOTH fixture packs,
   exercising both adapters against ONE `createComposedStore()` where sensible.
4. `PORT_DECISIONS.md` per above.
5. `package.json` + `tsconfig.json` so `bun test` runs.

## Hard rules (blindness protocol)

- Do NOT search for, open, or infer from: the original system's source code; any
  file outside this build dir and your `inputs/` dir; any other builder's work or
  prior port; the tool that produced your inputs. Work ONLY from the provided
  inputs.
- Author the projection logic yourself. Fixtures tell you WHAT the values are; you
  decide HOW to project them from the ONE event log.
- Budget: keep total work modest (a couple dollars of model spend). Stop when your
  suite is green and both adapters are complete.

Your final message must state: files written, `bun test` pass/fail count, and a
one-paragraph summary of how the ONE log serves both features.
