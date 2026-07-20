import { test, expect } from "bun:test";
import {
  makeAssetInventoryAdapter,
  INVENTORY_ADJUSTMENT_KIND,
  type AssetHandle,
  type AdjustmentKind,
} from "../src/inventory.ts";
import { isEntityId } from "../src/kernel/index.ts";

const MASS = "measure:mass";
const KG = "units:kg";
const LB = "units:lb";

/** Shorthand to append a done adjustment. */
function adj(
  kind: AdjustmentKind,
  value: number,
  occurredAt: number,
  extra: { logStatus?: string; measure?: string; units?: string } = {},
) {
  return {
    kind,
    value,
    occurredAt,
    logStatus: extra.logStatus ?? "done",
    measure: extra.measure ?? MASS,
    units: extra.units ?? KG,
  };
}

/** Find the summary for a (measure, units) pair. */
function pair(
  rows: { measure: string; units: string; value: number }[],
  measure: string,
  units: string,
) {
  return rows.find((r) => r.measure === measure && r.units === units);
}

// ── Candidate semantic n1: done-only + as-of cutoff ────────────────────────
test("n1: only the done, pre-cutoff increment contributes (2, not 5 or 3)", () => {
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  // done increment of 5 AFTER the cutoff
  inv.appendInventoryAdjustment(asset, adj("increment", 5, 300));
  // pending increment of 3 BEFORE the cutoff
  inv.appendInventoryAdjustment(asset, adj("increment", 3, 100, { logStatus: "pending" }));
  // done increment of 2 BEFORE the cutoff
  inv.appendInventoryAdjustment(asset, adj("increment", 2, 100));

  const rows = inv.getInventory(asset, 200);
  expect(rows).toEqual([{ measure: MASS, units: KG, value: 2 }]);
});

// ── Candidate semantic n2: reset is an ordered assignment, not additive ─────
test("n2: pre-reset +10 excluded, reset assigns 4, later -1 applied → 3", () => {
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  inv.appendInventoryAdjustment(asset, adj("increment", 10, 100));
  inv.appendInventoryAdjustment(asset, adj("reset", 4, 200));
  inv.appendInventoryAdjustment(asset, adj("decrement", 1, 300));

  const rows = inv.getInventory(asset, 400);
  expect(pair(rows, MASS, KG)!.value).toBe(3);
});

// ── Candidate semantic n3: new asset (no adjustments) → empty array ─────────
test("n3: an asset with no adjustments returns no summaries (not a zero row)", () => {
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  expect(inv.getInventory(asset, 999)).toEqual([]);
});

// ── Candidate semantic n4: same-timestamp reset boundary is inclusive ───────
test("n4: three events sharing the reset timestamp sequence by order → 3", () => {
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  // Appended in the source's id-ascending order (10, 11, 12); HLC preserves it.
  inv.appendInventoryAdjustment(asset, adj("increment", 3, 200)); // "id 10"
  inv.appendInventoryAdjustment(asset, adj("reset", 4, 200)); //     "id 11"
  inv.appendInventoryAdjustment(asset, adj("decrement", 1, 200)); // "id 12"

  const rows = inv.getInventory(asset, 300);
  // +3 is applied then OVERWRITTEN by reset 4, then -1 → 3.
  expect(pair(rows, MASS, KG)!.value).toBe(3);
});

// ── Candidate semantic n5: per exact (measure, units) pair, never merged ────
test("n5: kg and lb yield two independent summaries, not summed or converted", () => {
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  inv.appendInventoryAdjustment(asset, adj("increment", 7, 100, { units: KG }));
  inv.appendInventoryAdjustment(asset, adj("increment", 4, 100, { units: LB }));

  const rows = inv.getInventory(asset, 200);
  expect(rows.length).toBe(2);
  expect(pair(rows, MASS, KG)!.value).toBe(7);
  expect(pair(rows, MASS, LB)!.value).toBe(4);
});

// ── Kernel tie-break: HLC decides equal-occurredAt order, not id ────────────
test("tie-break: same occurredAt is sequenced by HLC (append/tick order)", () => {
  // reset THEN increment at the same timestamp → reset(4) then +5 = 9.
  const a = makeAssetInventoryAdapter();
  const assetA = a.createAsset();
  a.appendInventoryAdjustment(assetA, adj("reset", 4, 200));
  a.appendInventoryAdjustment(assetA, adj("increment", 5, 200));
  expect(pair(a.getInventory(assetA, 300), MASS, KG)!.value).toBe(9);

  // increment THEN reset at the same timestamp → +5 overwritten by reset = 4.
  const b = makeAssetInventoryAdapter();
  const assetB = b.createAsset();
  b.appendInventoryAdjustment(assetB, adj("increment", 5, 200));
  b.appendInventoryAdjustment(assetB, adj("reset", 4, 200));
  expect(pair(b.getInventory(assetB, 300), MASS, KG)!.value).toBe(4);
});

// ── as-of excludes a reset dated after the cutoff ───────────────────────────
test("as-of: a reset later than asOf does not take effect", () => {
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  inv.appendInventoryAdjustment(asset, adj("increment", 10, 100));
  inv.appendInventoryAdjustment(asset, adj("reset", 4, 500)); // after cutoff
  expect(pair(inv.getInventory(asset, 200), MASS, KG)!.value).toBe(10);
});

// ── ledger with no reset folds additively from 0 ────────────────────────────
test("no reset: increments and decrements fold additively from 0", () => {
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  inv.appendInventoryAdjustment(asset, adj("increment", 10, 100));
  inv.appendInventoryAdjustment(asset, adj("decrement", 3, 200));
  inv.appendInventoryAdjustment(asset, adj("increment", 1, 300));
  expect(pair(inv.getInventory(asset, 400), MASS, KG)!.value).toBe(8);
});

// ── Kernel gate 2: ids come from the IdMinter (replica-scoped, opaque) ───────
test("gate: asset + event handles are replica-scoped kernel ids", () => {
  const inv = makeAssetInventoryAdapter({ replicaId: "R7" });
  const asset = inv.createAsset();
  const handle = inv.appendInventoryAdjustment(asset, adj("increment", 1, 100));
  expect(isEntityId(asset)).toBe(true);
  expect(isEntityId(handle)).toBe(true);
  expect(asset).toContain("R7~");
  expect(handle).toContain("R7~");
});

// ── Kernel gate 1: the registered kind is exactly the adjustment kind ───────
test("gate: adjustments are logged under the registered kernel kind", () => {
  // A smoke check that the exported kind constant is what the adapter registers;
  // an ad-hoc kind at the append site would have been rejected by EventLog.
  expect(INVENTORY_ADJUSTMENT_KIND).toBe("inventory_adjustment");
  const inv = makeAssetInventoryAdapter();
  const asset = inv.createAsset();
  // If the kind were unregistered, this append would throw.
  expect(() =>
    inv.appendInventoryAdjustment(asset, adj("increment", 1, 100)),
  ).not.toThrow();
});

// ── Replicas: two adjustments on distinct replicas do not collide ───────────
test("replica ids do not collide across two adapters", () => {
  const r1 = makeAssetInventoryAdapter({ replicaId: "R1" });
  const r2 = makeAssetInventoryAdapter({ replicaId: "R2" });
  const a1 = r1.createAsset();
  const a2 = r2.createAsset();
  expect(a1).not.toBe(a2);
});
