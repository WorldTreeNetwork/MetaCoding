import { test, expect } from "bun:test";
import { makeActivityAdapter } from "../src/activity.ts";
import { Wave1LogStore } from "../../../shared-store/src/store.ts";

const NOW = Date.now();

function setup() {
  const store = new Wave1LogStore({ replicaId: "W1A" });
  const port = makeActivityAdapter(store);
  const field = store.createAsset({ entity: "land", name: "north paddock" });
  return { store, port, field };
}

test("recordActivity appends one event linked to all supplied assets", () => {
  const { store, port, field } = setup();
  const barn = store.createAsset({ entity: "land", name: "barn" });
  const h = port.recordActivity({
    name: "mowing", occurredAt: NOW - 30_000, status: "done",
    assetHandles: [field, barn], notes: "both done in one pass",
  });
  expect(String(h)).toMatch(/~\d+$/); // replica-scoped client id, never a bare ordinal
  expect(store.logCount(field, "activity")).toBe(1);
  expect(store.logCount(barn, "activity")).toBe(1);
});

test("list is newest occurredAt first with HLC tie-break; limit truncates that order", () => {
  const { port, field } = setup();
  const a = port.recordActivity({ name: "a", occurredAt: NOW - 30_000, status: "done", assetHandles: [field] });
  const b = port.recordActivity({ name: "b", occurredAt: NOW - 10_000, status: "done", assetHandles: [field] });
  const c = port.recordActivity({ name: "c", occurredAt: NOW - 20_000, status: "done", assetHandles: [field] });
  const list = port.listActivityLogsForAsset(field, NOW);
  expect(list.map((v) => v.logId)).toEqual([b, c, a]);
  expect(port.listActivityLogsForAsset(field, NOW, { limit: 2 }).map((v) => v.logId)).toEqual([b, c]);
});

test("same-instant activities tie-break on the HLC (later append is newer), never on id text", () => {
  const { port, field } = setup();
  const t = NOW - 5_000;
  const first = port.recordActivity({ name: "first", occurredAt: t, status: "done", assetHandles: [field] });
  const second = port.recordActivity({ name: "second", occurredAt: t, status: "done", assetHandles: [field] });
  expect(port.listActivityLogsForAsset(field, NOW).map((v) => v.logId)).toEqual([second, first]);
});

test("asOf bounds visibility by occurredAt; status filter applies", () => {
  const { port, field } = setup();
  const past = port.recordActivity({ name: "past", occurredAt: NOW - 30_000, status: "done", assetHandles: [field] });
  port.recordActivity({ name: "future", occurredAt: NOW + 86_400_000, status: "done", assetHandles: [field] });
  const pend = port.recordActivity({ name: "planned", occurredAt: NOW - 20_000, status: "pending", assetHandles: [field] });
  expect(port.listActivityLogsForAsset(field, NOW).map((v) => v.logId)).toEqual([pend, past]);
  expect(port.listActivityLogsForAsset(field, NOW, { status: "pending" }).map((v) => v.logId)).toEqual([pend]);
  expect(port.listActivityLogsForAsset(field, NOW, { status: "done" }).map((v) => v.logId)).toEqual([past]);
});

test("getFirst is the newest under the list ordering, or null when none matches", () => {
  const { port, field } = setup();
  expect(port.getFirstActivityLogForAsset(field, NOW)).toBeNull();
  port.recordActivity({ name: "old", occurredAt: NOW - 30_000, status: "done", assetHandles: [field] });
  const newest = port.recordActivity({ name: "new", occurredAt: NOW - 1_000, status: "done", assetHandles: [field] });
  expect(port.getFirstActivityLogForAsset(field, NOW)?.logId).toBe(newest);
  expect(port.getFirstActivityLogForAsset(field, NOW, "pending")).toBeNull();
});

test("activity shares the log spine: status round-trip moves official/pending partners", () => {
  const { store, port, field } = setup();
  const h = port.recordActivity({ name: "shear", occurredAt: NOW - 10_000, status: "pending", assetHandles: [field] });
  expect(store.logCount(field, "activity")).toBe(0);
  expect(store.pendingLogCount(field, "activity")).toBe(1);
  store.setLogStatus(h, "done");
  expect(store.logCount(field, "activity")).toBe(1);
  expect(store.pendingLogCount(field, "activity")).toBe(0);
});

test("activity logs are kind-isolated from observation logs in counts", () => {
  const { store, port, field } = setup();
  port.recordActivity({ name: "act", occurredAt: NOW - 10_000, status: "done", assetHandles: [field] });
  store.recordLog({ kind: "observation", name: "obs", status: "done", assetIds: [field], quantities: [] });
  expect(store.logCount(field, "activity")).toBe(1);
  expect(store.logCount(field, "observation")).toBe(1);
});
