// MetaCoding-87t: the three quantity-adjacent probes added to the
// material-quantity-fold port's surface — lot_number, material_quantity,
// quantity_recorded. Each test is built around the fake-it question:
//   - could lot_number "" hide an unanswerable?  (ghost logs must refuse)
//   - could material_quantity pass by answering "material" whenever ANY
//     quantity is material, or by echoing the last quantity?  (the pack's
//     subject is the LOG and the first-quantity convention must hold)
//   - could quantity_recorded fake the two-quantity sum by reading only the
//     first matching quantity, or fake unanswerable as 0?
// Store-level tests here; the wire-level mapping (top-level `lot_number` on
// record_log, the unanswerable channel) is covered by the bridge round-trip
// in bridge_roundtrip.test.ts.

import { test, expect } from "bun:test";
import { Wave1LogStore } from "../../../../wave1/shared-store/src/store.ts";

function setup() {
  const store = new Wave1LogStore({ replicaId: "W2M" });
  const land = store.createAsset({ entity: "land", name: "Plot" });
  return { store, land };
}

// ---- lot_number -----------------------------------------------------------

test("lot_number: a stated lot reads back verbatim", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "harvest", name: "Lotted", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram" }],
    extras: { lotNumber: "w2x-LOT-A1" },
  });
  expect(store.lotNumber(log)).toBe("w2x-LOT-A1");
});

test("lot_number: a log stating none answers '' — a VALUE, not a refusal", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "harvest", name: "Unlotted", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram" }],
  });
  expect(store.lotNumber(log)).toBe("");
});

test("lot_number: unknown and deleted logs are unanswerable, never '' (the fake-it check)", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "harvest", name: "Doomed", status: "done", assetIds: [land],
    quantities: [], extras: { lotNumber: "w2x-LOT-A1" },
  });
  store.deleteLog(log);
  expect(store.lotNumber(log)).toBeUndefined();
  expect(store.lotNumber(store.mint("log"))).toBeUndefined();
});

// ---- material_quantity ----------------------------------------------------

test("material_quantity: an unstated bundle classifies 'standard' — the boundary's recorded default", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Plain", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram" }],
  });
  expect(store.materialQuantity(log)).toBe("standard");
});

test("material_quantity: a material-bundle quantity classifies 'material'", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Material", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram", quantityType: "material" }],
  });
  expect(store.materialQuantity(log)).toBe("material");
});

test("material_quantity: a quantity-less log answers '' — the recorded no-classification contrast", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Empty", status: "done", assetIds: [land], quantities: [],
  });
  expect(store.materialQuantity(log)).toBe("");
});

test("material_quantity: the FIRST quantity's own classification, never 'any material present' (the fake-it check)", () => {
  const { store, land } = setup();
  // first standard, second material: an any-material fake would answer
  // "material"; a last-quantity fake would too. The subject's own is standard.
  const stdFirst = store.recordLog({
    kind: "input", name: "Std first", status: "done", assetIds: [land],
    quantities: [
      { measure: "weight", value: 2, unit: "kilogram" },
      { measure: "weight", value: 3, unit: "kilogram", quantityType: "material" },
    ],
  });
  expect(store.materialQuantity(stdFirst)).toBe("standard");
  // first material, second standard: an always-'standard' fake fails here.
  const matFirst = store.recordLog({
    kind: "input", name: "Mat first", status: "done", assetIds: [land],
    quantities: [
      { measure: "weight", value: 2, unit: "kilogram", quantityType: "material" },
      { measure: "weight", value: 3, unit: "kilogram" },
    ],
  });
  expect(store.materialQuantity(matFirst)).toBe("material");
});

test("material_quantity: unknown and deleted logs are unanswerable, never ''", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Doomed", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram" }],
  });
  store.deleteLog(log);
  expect(store.materialQuantity(log)).toBeUndefined();
  expect(store.materialQuantity(store.mint("log"))).toBeUndefined();
});

// ---- quantity_recorded ----------------------------------------------------

test("quantity_recorded: sums ALL matching quantities on the one log (the pack's 2+3 -> 5)", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Two quantities", status: "done", assetIds: [land],
    quantities: [
      { measure: "weight", value: 2, unit: "kilogram" },
      { measure: "weight", value: 3, unit: "kilogram" },
    ],
  });
  // a first-match-only fake would answer 2
  expect(store.quantityRecorded(log, "weight", "kilogram")).toBe(5);
});

test("quantity_recorded: a live log with no matching pair answers 0 — a value", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Mismatched", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "pound" }],
  });
  expect(store.quantityRecorded(log, "weight", "kilogram")).toBe(0);
});

test("quantity_recorded: unknown and deleted logs are unanswerable, never 0 (the 5xa house rule)", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "input", name: "Doomed", status: "done", assetIds: [land],
    quantities: [{ measure: "weight", value: 5, unit: "kilogram" }],
  });
  store.deleteLog(log);
  expect(store.quantityRecorded(log, "weight", "kilogram")).toBeUndefined();
  expect(store.quantityRecorded(store.mint("log"), "weight", "kilogram")).toBeUndefined();
});
