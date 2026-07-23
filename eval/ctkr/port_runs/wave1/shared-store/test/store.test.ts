import { test, expect } from "bun:test";
import { Wave1LogStore } from "../src/store.ts";

const mk = () => new Wave1LogStore({ replicaId: "T1" });

test("official numerics are confirmed-only; pending mass is in the partner, never blended", () => {
  const s = mk();
  const a = s.createAsset({ entity: "land", name: "field" });
  s.recordLog({ kind: "harvest", name: "done one", status: "done", assetIds: [a],
    quantities: [{ measure: "weight", value: 2, unit: "kilogram" }] });
  s.recordLog({ kind: "harvest", name: "pending one", status: "pending", assetIds: [a],
    quantities: [{ measure: "weight", value: 3, unit: "kilogram" }] });
  expect(s.yieldTotal(a, "weight", "kilogram")).toBe(2);
  expect(s.pendingYieldTotal(a, "weight", "kilogram")).toBe(3);
  expect(s.logCount(a, "harvest")).toBe(1);
  expect(s.pendingLogCount(a, "harvest")).toBe(1);
});

test("status is latest-wins through the kernel comparator; reopening withdraws from officials", () => {
  const s = mk();
  const a = s.createAsset({ entity: "land", name: "field" });
  const l = s.recordLog({ kind: "activity", name: "mow", status: "pending", assetIds: [a],
    quantities: [{ measure: "time", value: 3, unit: "hours" }] });
  expect(s.logStatus(l)).toBe("pending");
  s.setLogStatus(l, "done");
  expect(s.logStatus(l)).toBe("done");
  expect(s.logCount(a, "activity")).toBe(1);
  s.setLogStatus(l, "pending");
  expect(s.logStatus(l)).toBe("pending");
  expect(s.logCount(a, "activity")).toBe(0);
  expect(s.pendingLogCount(a, "activity")).toBe(1);
});

test("yield folds sum across domain log kinds and are not as-of-gated (observed boundary)", () => {
  const s = mk();
  const a = s.createAsset({ entity: "planting", name: "bed" });
  s.recordLog({ kind: "observation", name: "obs", status: "done", assetIds: [a],
    quantities: [{ measure: "weight", value: 3, unit: "kilograms" }] });
  s.recordLog({ kind: "harvest", name: "harv", status: "done", assetIds: [a],
    quantities: [{ measure: "weight", value: 9, unit: "kilograms" }],
    effectiveTime: Date.now() + 86_400_000 }); // future-dated: still counts
  expect(s.yieldTotal(a, "weight", "kilograms")).toBe(12);
});

test("per-(measure,unit) pairs never merge; unit names are opaque", () => {
  const s = mk();
  const a = s.createAsset({ entity: "equipment", name: "scale" });
  const l = s.recordLog({ kind: "activity", name: "calib", status: "done", assetIds: [a],
    quantities: [
      { measure: "weight", value: 10, unit: "kilograms" },
      { measure: "weight", value: 5, unit: "pounds" },
    ] });
  expect(s.quantityRecorded(l, "weight", "kilograms")).toBe(10);
  expect(s.quantityRecorded(l, "weight", "pounds")).toBe(5);
  expect(s.yieldTotal(a, "weight", "kilograms")).toBe(10);
});

test("effective-time restatement is a latest-wins event, and ordering follows it", () => {
  const s = mk();
  const a = s.createAsset({ entity: "land", name: "field" });
  const l1 = s.recordLog({ kind: "activity", name: "first", status: "done", assetIds: [a],
    quantities: [], effectiveTime: 1000 });
  const l2 = s.recordLog({ kind: "activity", name: "second", status: "done", assetIds: [a],
    quantities: [], effectiveTime: 2000 });
  expect(s.logsForAsset(a).map((v) => v.logId)).toEqual([l1, l2]);
  s.restateEffectiveTime(l1, 3000);
  expect(s.effectiveTimeOf(l1)).toBe(3000);
  expect(s.logsForAsset(a).map((v) => v.logId)).toEqual([l2, l1]);
});

test("one log against two assets delivers its full value to both (observed)", () => {
  const s = mk();
  const a = s.createAsset({ entity: "planting", name: "bed" });
  const b = s.createAsset({ entity: "land", name: "field" });
  s.recordLog({ kind: "observation", name: "scout", status: "done", assetIds: [a, b],
    quantities: [{ measure: "count", value: 12, unit: "aphids" }] });
  expect(s.yieldTotal(a, "count", "aphids")).toBe(12);
  expect(s.yieldTotal(b, "count", "aphids")).toBe(12);
});

test("archiving keeps history: asset inactive, logs retained (observed)", () => {
  const s = mk();
  const a = s.createAsset({ entity: "animal", name: "ewe" });
  s.recordLog({ kind: "observation", name: "weigh-in", status: "done", assetIds: [a],
    quantities: [{ measure: "weight", value: 62, unit: "kilograms" }] });
  s.archiveAsset(a);
  expect(s.assetActive(a)).toBe(false);
  expect(s.logCount(a, "observation")).toBe(1);
});

test("deletion cascade: a deleted log leaves every fold; a deleted quantity leaves its log", () => {
  const s = mk();
  const a = s.createAsset({ entity: "land", name: "field" });
  const l = s.recordLog({ kind: "observation", name: "obs", status: "done", assetIds: [a],
    quantities: [
      { measure: "weight", value: 4, unit: "kilograms" },
      { measure: "weight", value: 6, unit: "kilograms" },
    ] });
  const qid = s.logView(l)!.quantities[0]!.quantityId;
  s.deleteQuantity(qid);
  expect(s.quantityRecorded(l, "weight", "kilograms")).toBe(6);
  expect(s.yieldTotal(a, "weight", "kilograms")).toBe(6);
  s.deleteLog(l);
  expect(s.logView(l)).toBeUndefined();
  expect(s.logCount(a, "observation")).toBe(0);
  expect(s.yieldTotal(a, "weight", "kilograms")).toBe(0);
});

test("ad-hoc event kinds are rejected by the frozen registry", () => {
  const s = mk();
  expect(() => s.emit("made_up_kind", {})).toThrow(/frozen|ad-hoc|unknown/);
});

test("the third workflow state (abandoned) is inert to officials, visible to partners", () => {
  const s = mk();
  const a = s.createAsset({ entity: "land", name: "field" });
  const l = s.recordLog({ kind: "activity", name: "x", status: "done", assetIds: [a],
    quantities: [{ measure: "time", value: 1, unit: "hours" }] });
  s.setLogStatus(l, "abandoned");
  expect(s.logStatus(l)).toBe("abandoned");
  expect(s.logCount(a, "activity")).toBe(0);
  expect(s.pendingLogCount(a, "activity")).toBe(1); // not-confirmed partner mass
});

// --- MetaCoding-5xa: asset_active must not be trivially satisfiable --------
// Previously assetActive answered true for ANY unarchived handle, including
// never-created ghosts — "active asset" was indistinguishable from "no asset
// at all". A handle with no birth event is now unanswerable (undefined).

test("assetActive is unanswerable for a handle no birth event minted", () => {
  const s = mk();
  expect(s.assetActive("asset:ghost-never-created")).toBeUndefined();
});

test("assetActive answers for every asset-family birth, generic and feature-local", () => {
  const s = mk();
  const generic = s.createAsset({ entity: "land", name: "Born Field" });
  const sensor = s.createSensorAsset({ name: "Born Sensor" });
  expect(s.assetActive(generic)).toBe(true);
  expect(s.assetActive(sensor)).toBe(true);
  s.archiveAsset(generic);
  expect(s.assetActive(generic)).toBe(false); // archived is a VALUE, not absence
});

test("assetActive is unanswerable for a non-asset birth (a taxonomy term is not an asset)", () => {
  const s = mk();
  const term = s.createPlantTypeTerm({ name: "Tomato" });
  expect(s.assetActive(term)).toBeUndefined();
});
