// Spine-tier SMOKE tests for the maintenance log port. These exercise the thin
// per-feature surface over the shared spine; they are NOT oracle-observed
// recorded packs. Trailing readings will judge against recorded fixtures later —
// here we prove the shell wires the shared spine honestly for kind="maintenance",
// including the abandoned state that the shared farm_log_workflow adds.

import { test, expect } from "bun:test";
import { makeMaintenanceAdapter } from "../src/maintenance.ts";
import { Wave1LogStore } from "../../../../wave1/shared-store/src/store.ts";

const NOW = Date.now();

function setup() {
  const store = new Wave1LogStore({ replicaId: "W2M" });
  const port = makeMaintenanceAdapter(store);
  // maintenance targets Equipment assets (info.yml: "for Equipment assets").
  const tractor = store.createAsset({ entity: "equipment", name: "tractor" });
  return { store, port, tractor };
}

test("recordMaintenance appends one maintenance log linked to all supplied equipment", () => {
  const { store, port, tractor } = setup();
  const baler = store.createAsset({ entity: "equipment", name: "baler" });
  const h = port.recordMaintenance({
    name: "oil change", occurredAt: NOW - 30_000, status: "done",
    assetHandles: [tractor, baler], notes: "both serviced in one visit",
  });
  expect(String(h)).toMatch(/~\d+$/); // replica-scoped client id, never a bare ordinal
  expect(store.logCount(tractor, "maintenance")).toBe(1);
  expect(store.logCount(baler, "maintenance")).toBe(1);
  const v = port.getFirstMaintenanceLogForAsset(tractor, NOW);
  expect(v?.notes).toBe("both serviced in one visit");
});

test("list is newest occurredAt first with HLC tie-break; limit truncates that order", () => {
  const { port, tractor } = setup();
  const a = port.recordMaintenance({ name: "a", occurredAt: NOW - 30_000, status: "done", assetHandles: [tractor] });
  const b = port.recordMaintenance({ name: "b", occurredAt: NOW - 10_000, status: "done", assetHandles: [tractor] });
  const c = port.recordMaintenance({ name: "c", occurredAt: NOW - 20_000, status: "done", assetHandles: [tractor] });
  const list = port.listMaintenanceLogsForAsset(tractor, NOW);
  expect(list.map((v) => v.logId)).toEqual([b, c, a]);
  expect(port.listMaintenanceLogsForAsset(tractor, NOW, { limit: 2 }).map((v) => v.logId)).toEqual([b, c]);
});

test("same-instant maintenance logs tie-break on the HLC (later append is newer), never on id text", () => {
  const { port, tractor } = setup();
  const t = NOW - 5_000;
  const first = port.recordMaintenance({ name: "first", occurredAt: t, status: "done", assetHandles: [tractor] });
  const second = port.recordMaintenance({ name: "second", occurredAt: t, status: "done", assetHandles: [tractor] });
  expect(port.listMaintenanceLogsForAsset(tractor, NOW).map((v) => v.logId)).toEqual([second, first]);
});

test("asOf bounds visibility by occurredAt; status filter applies", () => {
  const { port, tractor } = setup();
  const past = port.recordMaintenance({ name: "past", occurredAt: NOW - 30_000, status: "done", assetHandles: [tractor] });
  port.recordMaintenance({ name: "future", occurredAt: NOW + 86_400_000, status: "done", assetHandles: [tractor] });
  const pend = port.recordMaintenance({ name: "planned", occurredAt: NOW - 20_000, status: "pending", assetHandles: [tractor] });
  expect(port.listMaintenanceLogsForAsset(tractor, NOW).map((v) => v.logId)).toEqual([pend, past]);
  expect(port.listMaintenanceLogsForAsset(tractor, NOW, { status: "pending" }).map((v) => v.logId)).toEqual([pend]);
  expect(port.listMaintenanceLogsForAsset(tractor, NOW, { status: "done" }).map((v) => v.logId)).toEqual([past]);
});

test("getFirst is the newest under the list ordering, or null when none matches", () => {
  const { port, tractor } = setup();
  expect(port.getFirstMaintenanceLogForAsset(tractor, NOW)).toBeNull();
  port.recordMaintenance({ name: "old", occurredAt: NOW - 30_000, status: "done", assetHandles: [tractor] });
  const newest = port.recordMaintenance({ name: "new", occurredAt: NOW - 1_000, status: "done", assetHandles: [tractor] });
  expect(port.getFirstMaintenanceLogForAsset(tractor, NOW)?.logId).toBe(newest);
  expect(port.getFirstMaintenanceLogForAsset(tractor, NOW, "pending")).toBeNull();
});

test("maintenance shares the log spine: status round-trip moves official/pending partners", () => {
  const { store, port, tractor } = setup();
  const h = port.recordMaintenance({ name: "service", occurredAt: NOW - 10_000, status: "pending", assetHandles: [tractor] });
  expect(store.logCount(tractor, "maintenance")).toBe(0);
  expect(store.pendingLogCount(tractor, "maintenance")).toBe(1);
  store.setLogStatus(h, "done");
  expect(store.logCount(tractor, "maintenance")).toBe(1);
  expect(store.pendingLogCount(tractor, "maintenance")).toBe(0);
});

test("abandoned (the farm_log_workflow third state) is inert to official numerics, visible in pending partners", () => {
  // decision w1a-5, inherited unchanged: abandoned !== "done", so it fails the
  // require-confirmed gate (logCount) and is admitted by the pending-only gate.
  const { store, port, tractor } = setup();
  const h = port.recordMaintenance({ name: "aborted service", occurredAt: NOW - 10_000, status: "abandoned", assetHandles: [tractor] });
  expect(store.logStatus(h)).toBe("abandoned");        // count-regardless: the status itself is preserved
  expect(store.logCount(tractor, "maintenance")).toBe(0);       // inert to official numeric
  expect(store.pendingLogCount(tractor, "maintenance")).toBe(1); // surfaced in the pending partner
  // and it is still listable/filterable as its own state through the surface
  expect(port.listMaintenanceLogsForAsset(tractor, NOW, { status: "abandoned" }).map((v) => v.logId)).toEqual([h]);
  // transition abandoned -> done reactivates the official numeric (farm_log_workflow "done" transition)
  store.setLogStatus(h, "done");
  expect(store.logCount(tractor, "maintenance")).toBe(1);
  expect(store.pendingLogCount(tractor, "maintenance")).toBe(0);
});

test("quantities fold through the shared spine even though the maintenance bundle declares none", () => {
  // maintenance carries no source quantities, but the shared store serves them
  // generically; declaring a maintenance-specific measure would be a hand-rolled
  // fold (forbidden). Here we prove the generic path folds, gated by status.
  const { store, port, tractor } = setup();
  const h = port.recordMaintenance({
    name: "parts replaced", occurredAt: NOW - 10_000, status: "done", assetHandles: [tractor],
    quantities: [{ measure: "count", value: 3, unit: "each" }],
  });
  expect(store.quantityRecorded(h, "count", "each")).toBe(3); // per-log, never status-gated
  expect(store.yieldTotal(tractor, "count", "each")).toBe(3); // confirmed done => folds
});

test("maintenance logs are kind-isolated from activity logs in counts", () => {
  const { store, port, tractor } = setup();
  port.recordMaintenance({ name: "svc", occurredAt: NOW - 10_000, status: "done", assetHandles: [tractor] });
  store.recordLog({ kind: "activity", name: "act", status: "done", assetIds: [tractor], quantities: [] });
  expect(store.logCount(tractor, "maintenance")).toBe(1);
  expect(store.logCount(tractor, "activity")).toBe(1);
});
