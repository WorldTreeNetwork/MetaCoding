import { test, expect } from "bun:test";
import {
  makeStandardQuantityAdapter,
  standardQuantity,
} from "../src/quantity-standard.ts";
import { Wave1LogStore } from "../../../../wave1/shared-store/src/store.ts";

const NOW = Date.now();

function setup() {
  const store = new Wave1LogStore({ replicaId: "W2SM" });
  const port = makeStandardQuantityAdapter(store);
  const field = store.createAsset({ entity: "land", name: "north paddock" });
  return { store, port, field };
}

test("standardQuantity stamps the bundle tag and carries only base quantity fields", () => {
  const q = standardQuantity({ measure: "weight", value: 12, unit: "kg", label: "load" });
  expect(q).toEqual({
    measure: "weight",
    value: 12,
    unit: "kg",
    label: "load",
    quantityType: "standard",
  });
  // label is optional (source default '') — omitted rather than defaulted here.
  const noLabel = standardQuantity({ measure: "weight", value: 3, unit: "kg" });
  expect("label" in noLabel).toBe(false);
  expect(noLabel.quantityType).toBe("standard");
});

test("the bundle tag is fixed to 'standard', never taken from the caller", () => {
  // StandardQuantity has no quantityType field; construction always tags standard.
  const q = standardQuantity({ measure: "volume", value: 5, unit: "L" } as any);
  expect(q.quantityType).toBe("standard");
});

test("recorded standard quantities read back bundle-filtered off one log", () => {
  const { store, port, field } = setup();
  const log = port.recordWithStandardQuantities({
    kind: "observation",
    status: "done",
    assetHandles: [field],
    quantities: [
      { measure: "weight", value: 10, unit: "kg", label: "a" },
      { measure: "weight", value: 4, unit: "kg" },
    ],
    occurredAt: NOW - 1000,
  });
  const qs = port.standardQuantitiesOn(log);
  expect(qs.map((q) => q.value)).toEqual([10, 4]);
  expect(qs[0]!.label).toBe("a");
  expect("label" in qs[1]!).toBe(false);
  // every id is a replica-scoped client id, never a bare ordinal.
  for (const q of qs) expect(String(q.quantityId)).toMatch(/~\d+$/);
  // a non-standard quantity on the same log is excluded from the bundle read.
  store.recordLog({
    kind: "observation",
    name: "",
    status: "done",
    assetIds: [field],
    quantities: [{ measure: "weight", value: 99, unit: "kg", quantityType: "material" }],
  });
  expect(port.standardQuantitiesOn(log).map((q) => q.value)).toEqual([10, 4]);
});

test("quantityRecordedOn sums the (measure, unit) pair on one log, ungated", () => {
  const { port, field } = setup();
  // pending log: quantityRecordedOn reports what the event says, not a gated fold.
  const log = port.recordWithStandardQuantities({
    kind: "observation",
    status: "pending",
    assetHandles: [field],
    quantities: [
      { measure: "weight", value: 6, unit: "kg" },
      { measure: "weight", value: 4, unit: "kg" },
      { measure: "volume", value: 2, unit: "L" },
    ],
  });
  expect(port.quantityRecordedOn(log, "weight", "kg")).toBe(10);
  expect(port.quantityRecordedOn(log, "volume", "L")).toBe(2);
  expect(port.quantityRecordedOn(log, "weight", "lb")).toBe(0); // unit opacity: kg != lb
});

test("yield_total over standard quantities inherits the confirmed-only status gate", () => {
  const { store, port, field } = setup();
  const log = port.recordWithStandardQuantities({
    kind: "harvest",
    status: "pending",
    assetHandles: [field],
    quantities: [{ measure: "weight", value: 8, unit: "kg" }],
  });
  // pending → excluded from official yield, present in the pending-only partner.
  expect(store.yieldTotal(field, "weight", "kg")).toBe(0);
  expect(store.pendingYieldTotal(field, "weight", "kg")).toBe(8);
  store.setLogStatus(log, "done");
  expect(store.yieldTotal(field, "weight", "kg")).toBe(8);
  expect(store.pendingYieldTotal(field, "weight", "kg")).toBe(0);
});

test("standard log participates in the shared log-count spine, kind-isolated", () => {
  const { store, port, field } = setup();
  port.recordWithStandardQuantities({
    kind: "harvest",
    status: "done",
    assetHandles: [field],
    quantities: [{ measure: "count", value: 1, unit: "each" }],
  });
  expect(store.logCount(field, "harvest")).toBe(1);
  expect(store.logCount(field, "observation")).toBe(0);
});

test("empty quantity set is allowed — standard adds no non-empty constraint", () => {
  const { port, field } = setup();
  const log = port.recordWithStandardQuantities({
    kind: "activity",
    status: "done",
    assetHandles: [field],
    quantities: [],
  });
  expect(port.standardQuantitiesOn(log)).toEqual([]);
});
