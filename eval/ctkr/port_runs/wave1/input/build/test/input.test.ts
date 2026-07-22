import { test, expect } from "bun:test";
import { makeInputLogAdapter } from "../src/input.ts";
import { Wave1LogStore } from "../../../shared-store/src/store.ts";

const NOW = Date.now();

function setup() {
  const store = new Wave1LogStore({ replicaId: "W1D" });
  const port = makeInputLogAdapter(store);
  return { store, port };
}

test("recordMaterialInput refuses an empty quantity set", () => {
  const { port } = setup();
  expect(() => port.recordMaterialInput(NOW, [], "done")).toThrow(/non-empty/);
});

test("quantities default to the material type without restricting mixing", () => {
  const { port } = setup();
  const h = port.recordMaterialInput(NOW - 10_000, [
    { measure: "weight", value: 2, unit: "kilograms", materialTypes: ["compost"] },
    { measure: "count", value: 40, unit: "seeds", quantityType: "standard" },
  ], "done");
  const [view] = port.listInputLogs({}, NOW);
  expect(view!.log).toBe(h);
  expect(view!.quantities[0]!.quantityType).toBe("material");
  expect(view!.quantities[1]!.quantityType).toBe("standard"); // default, not a constraint
});

test("material-type filter is ∃-quantity membership: one match admits the log ONCE", () => {
  const { port } = setup();
  const both = port.recordMaterialInput(NOW - 30_000, [
    { measure: "weight", value: 1.5, unit: "kilograms", materialTypes: ["compost"] },
    { measure: "weight", value: 2.5, unit: "kilograms", materialTypes: ["compost"] },
  ], "done");
  const other = port.recordMaterialInput(NOW - 20_000, [
    { measure: "volume", value: 100, unit: "liters", materialTypes: ["water"] },
  ], "done");
  const compost = port.listInputLogs({ materialType: "compost" }, NOW);
  expect(compost.map((v) => v.log)).toEqual([both]); // once, not twice
  expect(port.listInputLogs({ materialType: "water" }, NOW).map((v) => v.log)).toEqual([other]);
  expect(port.listInputLogs({ materialType: "lime" }, NOW)).toEqual([]);
});

test("multi-valued material types on a single quantity all admit the log", () => {
  const { port } = setup();
  const h = port.recordMaterialInput(NOW - 10_000, [
    { measure: "weight", value: 3, unit: "kilograms", materialTypes: ["fertilizer", "organic"] },
  ], "done");
  expect(port.listInputLogs({ materialType: "fertilizer" }, NOW).map((v) => v.log)).toEqual([h]);
  expect(port.listInputLogs({ materialType: "organic" }, NOW).map((v) => v.log)).toEqual([h]);
});

test("listInputLogs is as-of bounded by effective time and exposes status as of then", () => {
  const { port } = setup();
  const past = port.recordMaterialInput(NOW - 30_000, [
    { measure: "weight", value: 5, unit: "kilograms" }], "pending");
  port.recordMaterialInput(NOW + 86_400_000, [
    { measure: "weight", value: 6, unit: "kilograms" }], "done");
  const list = port.listInputLogs({}, NOW);
  expect(list.map((v) => v.log)).toEqual([past]);
  expect(list[0]!.status).toBe("pending");
});

test("purchase_date is inert metadata: it never moves the log in effective-time order", () => {
  const { port } = setup();
  const early = port.recordMaterialInput(NOW - 40_000,
    [{ measure: "weight", value: 1, unit: "kilograms" }], "done",
    { purchaseDate: NOW - 1_000 }); // bought recently, applied early
  const late = port.recordMaterialInput(NOW - 10_000,
    [{ measure: "weight", value: 2, unit: "kilograms" }], "done",
    { purchaseDate: NOW - 90_000 });
  expect(port.listInputLogs({}, NOW).map((v) => v.log)).toEqual([early, late]);
});

test("input logs share the kernel folds when recorded against assets", () => {
  const { store, port } = setup();
  const bed = store.createAsset({ entity: "planting", name: "bed" });
  const h = port.recordInputAgainst(NOW - 20_000, [bed],
    [{ measure: "weight", value: 5, unit: "kilograms", materialTypes: ["compost"] }], "done");
  port.recordInputAgainst(NOW - 10_000, [bed],
    [{ measure: "weight", value: 7, unit: "kilograms" }], "pending");
  expect(store.yieldTotal(bed, "weight", "kilograms")).toBe(5);
  expect(store.pendingYieldTotal(bed, "weight", "kilograms")).toBe(7);
  expect(store.logCount(bed, "input")).toBe(1);
  expect(store.quantityRecorded(h, "weight", "kilograms")).toBe(5);
});
