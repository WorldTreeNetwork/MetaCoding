// Identity-tier tests for the material quantity_presave fold (MetaCoding-5ln).
// The oracle-observed shape (pack 046155d7d243): a material quantity
// referencing a typed material asset inherits the type; no inventory reference
// or a non-material inventory asset delivers no type. Plus the port-only
// invariants the recording cannot state: the copy is a SNAPSHOT (the source's
// presave semantics — asset changes never restate recorded quantities, which
// in this event-sourced store falls out of asset immutability), a standard
// quantity never folds, and unknown/deleted logs are unanswerable.

import { test, expect } from "bun:test";
import { Wave1LogStore } from "../../../../wave1/shared-store/src/store.ts";

function setup() {
  const store = new Wave1LogStore({ replicaId: "W2M" });
  const land = store.createAsset({ entity: "land", name: "Plot" });
  const compost = store.createAsset({
    entity: "material", name: "Compost Pile", descriptor: "Compost",
  });
  return { store, land, compost };
}

test("a material quantity referencing a typed material asset inherits the type", () => {
  const { store, land, compost } = setup();
  const log = store.recordLog({
    kind: "input", name: "Application", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram",
                   quantityType: "material", inventoryAssetId: compost }],
  });
  expect(store.materialTypeRecorded(log)).toEqual(["Compost"]);
});

test("no inventory reference: no type is delivered (the recorded contrast)", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Untracked", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram",
                   quantityType: "material" }],
  });
  expect(store.materialTypeRecorded(log)).toEqual([]);
});

test("a NON-material inventory asset: the bundle guard bails", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Misfiled", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram",
                   quantityType: "material", inventoryAssetId: land }],
  });
  expect(store.materialTypeRecorded(log)).toEqual([]);
});

test("a typeless material asset: the emptiness guard bails", () => {
  const { store, land } = setup();
  const bare = store.createAsset({ entity: "material", name: "Mystery Pile" });
  const log = store.recordLog({
    kind: "input", name: "Mystery", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram",
                   quantityType: "material", inventoryAssetId: bare }],
  });
  expect(store.materialTypeRecorded(log)).toEqual([]);
});

test("a STANDARD quantity never folds, even with a material inventory ref", () => {
  const { store, land, compost } = setup();
  const log = store.recordLog({
    kind: "input", name: "Standard", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram",
                   inventoryAssetId: compost }],
  });
  expect(store.materialTypeRecorded(log)).toEqual([]);
});

test("an explicitly stated material type is overwritten by the fold — the source SETS, it does not merge", () => {
  const { store, land, compost } = setup();
  const log = store.recordLog({
    kind: "input", name: "Restated", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram",
                   quantityType: "material", inventoryAssetId: compost,
                   materialTypes: ["Hand-entered"] }],
  });
  expect(store.materialTypeRecorded(log)).toEqual(["Compost"]);
});

test("unknown or deleted logs are unanswerable, never []", () => {
  const { store, land, compost } = setup();
  const log = store.recordLog({
    kind: "input", name: "Doomed", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram",
                   quantityType: "material", inventoryAssetId: compost }],
  });
  store.deleteLog(log);
  expect(store.materialTypeRecorded(log)).toBeUndefined();
  expect(store.materialTypeRecorded(store.mint("log"))).toBeUndefined();
});
