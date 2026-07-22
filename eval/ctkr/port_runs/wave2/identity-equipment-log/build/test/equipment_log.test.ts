// Identity-tier tests for the equipment-on-log port (MetaCoding-1cv). The
// oracle-observed shape (pack 1e1a8c55b7f5): attached equipment delivers
// used=true, unattached false, a log with none false; the field is
// multi-valued. Plus the port-only invariants the recording cannot state:
// events recorded before the field existed fold as [], and a deleted log is
// unanswerable, never false.

import { test, expect } from "bun:test";
import { Wave1LogStore, type LogRecordedPayload } from "../../../../wave1/shared-store/src/store.ts";

function setup() {
  const store = new Wave1LogStore({ replicaId: "W2E" });
  const land = store.createAsset({ entity: "land", name: "Bed" });
  const tractor = store.createAsset({ entity: "equipment", name: "Tractor" });
  const seeder = store.createAsset({ entity: "equipment", name: "Seeder" });
  return { store, land, tractor, seeder };
}

test("attached equipment is used; unattached is not (the recorded contrast)", () => {
  const { store, land, tractor, seeder } = setup();
  const log = store.recordLog({
    kind: "activity", name: "Till", status: "done",
    assetIds: [land], quantities: [], equipmentIds: [tractor],
  });
  expect(store.equipmentUsed(log, tractor)).toBe(true);
  expect(store.equipmentUsed(log, seeder)).toBe(false);
});

test("a log with no equipment delivers false for any asset", () => {
  const { store, land, tractor } = setup();
  const log = store.recordLog({
    kind: "activity", name: "By hand", status: "done",
    assetIds: [land], quantities: [],
  });
  expect(store.equipmentUsed(log, tractor)).toBe(false);
  expect(store.logView(log)!.equipmentIds).toEqual([]);
});

test("the field is multi-valued: both attached assets deliver used", () => {
  const { store, land, tractor, seeder } = setup();
  const log = store.recordLog({
    kind: "activity", name: "Till and seed", status: "done",
    assetIds: [land], quantities: [], equipmentIds: [tractor, seeder],
  });
  expect(store.equipmentUsed(log, tractor)).toBe(true);
  expect(store.equipmentUsed(log, seeder)).toBe(true);
});

test("an event recorded before the field existed folds as [] (additive schema)", () => {
  const { store, land, tractor } = setup();
  const logId = store.mint("log");
  store.emit<LogRecordedPayload>("log_recorded", {
    logId, kind: "activity", name: "Pre-1cv", status: "done",
    assetIds: [land], quantities: [], effectiveTime: store.now(),
  });
  expect(store.logView(logId)!.equipmentIds).toEqual([]);
  expect(store.equipmentUsed(logId, tractor)).toBe(false);
});

test("a deleted or unknown log is unanswerable, never false", () => {
  const { store, land, tractor } = setup();
  const log = store.recordLog({
    kind: "activity", name: "Doomed", status: "done",
    assetIds: [land], quantities: [], equipmentIds: [tractor],
  });
  store.deleteLog(log);
  expect(store.equipmentUsed(log, tractor)).toBeUndefined();
  expect(store.equipmentUsed(store.mint("log"), tractor)).toBeUndefined();
});
