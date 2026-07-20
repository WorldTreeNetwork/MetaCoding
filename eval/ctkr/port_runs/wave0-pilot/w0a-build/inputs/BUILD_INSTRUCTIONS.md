# Blind build — Asset Inventory feature, ON the shared kernel

You are a blind port builder. Build a TypeScript (Bun) implementation of the
**Asset Inventory** feature described by the inputs in this directory. You MUST
build on the shared kernel provided in `inputs/kernel/` as fixed substrate.

## Hard blindness rules
- You may read ONLY the files in this `inputs/` directory.
- You are FORBIDDEN to read or search: any farmOS/Drupal source, the MetaCoding
  repo, the web, or any other port/build. Do not `grep`/`find` outside `inputs/`.
- If you think you recognize this from farmOS: ignore that memory. Build ONLY
  from the surface + candidate semantics given here.

## Inputs
- `inputs/kernel/` — the shared kernel v1 (READ its files: index.ts, events.ts,
  ids.ts, hlc.ts, lww.ts, status.ts, decisions.ts). This is your substrate.
- `inputs/ADAPTER_CONTRACT_GENERATED.md` — the machine-proposed adapter surface.
  Implement the **inventory-core** methods only: `appendInventoryAdjustment` and
  `getInventory`. IGNORE the quantity-migration / quantity-type / rendering
  methods (`migrateQuantities`, `appendQuantityRevision`,
  `appendQuantityTypeRevision`, `getQuantitySnapshot`, `getQuantityTypeSnapshot`,
  `renderQuantityPlainText`, `createQuantity`) — they are out of scope for this
  build.
- `inputs/CANDIDATE_SEMANTICS_UNOBSERVED.json` — the behavioral semantics to
  satisfy, as given/when/then. NOTE: these were mined from source, NOT observed
  from a live oracle, so treat their exact `then` numbers as the intended design
  but do not over-index on any single value; the SEMANTICS (reset-assigns,
  done-only, per-(measure,units), as-of cutoff, same-timestamp tie-break) are
  what matter.

## What to build (`build/`)
A Bun package with `src/inventory.ts` exporting `makeAssetInventoryAdapter()` and
`src/kernel/` (copy the provided kernel in). Implement:
- `appendInventoryAdjustment(asset, { logStatus, occurredAt, measure, units, kind: 'increment'|'decrement'|'reset', value })` — appends ONE event to the kernel `EventLog`.
- `getInventory(asset, asOf)` — returns `{measure, units, value}[]`, one summary
  per exact (measure, units) pair, computed as: consider only adjustments whose
  status is `done` AND whose `occurredAt <= asOf`; find the latest `reset`
  timestamp; the running value starts at that reset's value; then apply
  increment/decrement deltas for adjustments at-or-after that reset, in order.

## Kernel-integration REQUIREMENTS (these are graded)
1. **Event kinds MUST be registered** in a `KindRegistry` and the registry frozen
   before use. Appends go through the kernel `EventLog` (which rejects unregistered
   kinds). NO ad-hoc kind strings at append sites.
2. **Entity/event ids MUST come from the kernel `IdMinter`** (replica-scoped). NO
   bare ordinal/integer ids.
3. **Ordering of adjustments MUST be deterministic and kernel-legal.** The domain
   orders by `occurredAt` (valid-time / effectiveTime, a payload field). For
   ties (same `occurredAt`), you MUST break the tie using the kernel **HLC**
   (`compareHlc`) — NOT by entity id (the kernel's ids.ts explicitly forbids
   ordering by id). Record in PORT_DECISIONS.md that you did this and how it
   differs from a naive id-ascending tie-break.
4. **Status filtering MUST go through the kernel status contract.** Inventory's
   gate is `require-confirmed` (pending adjustments are inert). If the kernel's
   `STATUS_CONTRACT` has no `currentInventory` row, note that in PORT_DECISIONS.md
   as a required kernel addition, and gate via `passesGate(status, "require-confirmed")`.
5. Write `build/PORT_DECISIONS.md` documenting: which kernel primitives you used
   directly; **which fold(s) you had to hand-roll because the kernel provides no
   primitive for them** (be specific — the reset/increment/decrement running
   balance is NOT latest-wins, so `pickLatest`/`LwwRegister` do not cover it);
   and any place the kernel felt under-provisioned for this feature.

## Verify
- Write `build/test/inventory.test.ts` with `bun test` cases covering each
  candidate semantic. All must pass.
- Run `bun test` and paste the result into PORT_DECISIONS.md.

## Your final message (the report back to me)
Report, concisely:
1. Did the kernel primitives suffice to build inventory? YES/NO + what was missing.
2. The exact fold you hand-rolled (the running-balance-with-reset) and whether the
   kernel should ship it as a sanctioned primitive.
3. How you handled the same-`occurredAt` tie-break (HLC vs id) and whether that
   diverges from the source's apparent id-ascending rule.
4. Whether the kernel prevention gates (registered kinds, IdMinter, status gate)
   fit naturally or fought you.
5. `bun test` pass/fail count.
Your final message IS the report; put the complete findings there.
