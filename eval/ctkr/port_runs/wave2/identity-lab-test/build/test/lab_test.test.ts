// Identity-tier tests for the lab_test port (MetaCoding-wgy). The oracle-observed
// shape (pack 066d1701271199f5cec70e0d742000ba): five bundle fields the source
// states on log--lab_test read back verbatim ('' when absent), the recorded lab
// NAME reads back as the laboratory, and the ordered test_method names on the
// first quantity--test read back as the measurement ([] when the quantity is
// standard or carries no method). Plus the port-only invariants the recording
// cannot state: the fields are independent, a non-lab_test log answers the empty
// value (never invents one), a deleted test quantity drops from the fold, and an
// unknown or deleted log is unanswerable, never the empty value.

import { test, expect } from "bun:test";
import { Wave1LogStore, type QuantityInput } from "../../../../wave1/shared-store/src/store.ts";

function setup() {
  const store = new Wave1LogStore({ replicaId: "W2L" });
  const land = store.createAsset({ entity: "land", name: "Panel Plot" });
  return { store, land };
}

// A quantity--test carrying a method, mirroring the wire the bridge builds.
function testQty(method?: string): QuantityInput {
  return {
    measure: "ratio", value: 12, unit: "percent", label: "measured",
    quantityType: "test",
    ...(method ? { testMethods: [method] } : {}),
  };
}

test("each bundle field reads back verbatim; a second log recording none reads back ''", () => {
  const { store, land } = setup();
  const full = store.recordLog({
    kind: "lab_test", name: "Complete panel", status: "done", assetIds: [land],
    quantities: [testQty("Spectrometry")],
    extras: {
      labSampleType: "tissue",
      laboratory: "Meridian Labs",
      labProcessedDate: "2026-05-25T00:00:00+00:00",
      labReceivedDate: "2026-05-20T00:00:00+00:00",
      soilTexture: "Sandy loam",
    },
  });
  expect(store.labSampleType(full)).toBe("tissue");
  expect(store.laboratory(full)).toBe("Meridian Labs");
  expect(store.labProcessingDate(full)).toBe("2026-05-25T00:00:00+00:00");
  expect(store.sampleReceivedDate(full)).toBe("2026-05-20T00:00:00+00:00");
  expect(store.soilTexture(full)).toBe("Sandy loam");
  expect(store.labTestMeasurement(full)).toEqual(["Spectrometry"]);

  const bare = store.recordLog({
    kind: "lab_test", name: "Empty panel", status: "done", assetIds: [land],
    quantities: [],
  });
  expect(store.labSampleType(bare)).toBe("");
  expect(store.laboratory(bare)).toBe("");
  expect(store.labProcessingDate(bare)).toBe("");
  expect(store.sampleReceivedDate(bare)).toBe("");
  expect(store.soilTexture(bare)).toBe("");
  expect(store.labTestMeasurement(bare)).toEqual([]);
});

test("sample types track their own log (the recorded contrast)", () => {
  const { store, land } = setup();
  const soil = store.recordLog({
    kind: "lab_test", name: "Soil panel", status: "done", assetIds: [land],
    quantities: [], extras: { labSampleType: "soil" },
  });
  const water = store.recordLog({
    kind: "lab_test", name: "Water panel", status: "done", assetIds: [land],
    quantities: [], extras: { labSampleType: "water" },
  });
  expect(store.labSampleType(soil)).toBe("soil");
  expect(store.labSampleType(water)).toBe("water");
});

test("laboratories track their own log by NAME", () => {
  const { store, land } = setup();
  const cascade = store.recordLog({
    kind: "lab_test", name: "Cascade panel", status: "done", assetIds: [land],
    quantities: [], extras: { laboratory: "Cascade Soil Lab" },
  });
  const basin = store.recordLog({
    kind: "lab_test", name: "Basin panel", status: "done", assetIds: [land],
    quantities: [], extras: { laboratory: "Basin Ag Testing" },
  });
  expect(store.laboratory(cascade)).toBe("Cascade Soil Lab");
  expect(store.laboratory(basin)).toBe("Basin Ag Testing");
});

test("a standard (non-test) quantity reports no method; a test quantity with no method reports none", () => {
  const { store, land } = setup();
  const standard = store.recordLog({
    kind: "lab_test", name: "Ordinary-quantity panel", status: "done", assetIds: [land],
    quantities: [{ measure: "ratio", value: 12, unit: "percent", label: "measured" }],
  });
  expect(store.labTestMeasurement(standard)).toEqual([]);

  const methodless = store.recordLog({
    kind: "lab_test", name: "Methodless test panel", status: "done", assetIds: [land],
    quantities: [testQty()],
  });
  expect(store.labTestMeasurement(methodless)).toEqual([]);
});

test("the measurement folds off the FIRST test quantity", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "lab_test", name: "Two-method panel", status: "done", assetIds: [land],
    quantities: [testQty("Titration"), testQty("Spectrometry")],
  });
  expect(store.labTestMeasurement(log)).toEqual(["Titration"]);
});

test("the five fields are independent: recording only one leaves the rest ''", () => {
  const { store, land } = setup();
  const texturedOnly = store.recordLog({
    kind: "lab_test", name: "Textured panel", status: "done", assetIds: [land],
    quantities: [], extras: { soilTexture: "Silty clay loam" },
  });
  expect(store.soilTexture(texturedOnly)).toBe("Silty clay loam");
  expect(store.labSampleType(texturedOnly)).toBe("");
  expect(store.laboratory(texturedOnly)).toBe("");
  expect(store.labProcessingDate(texturedOnly)).toBe("");
  expect(store.sampleReceivedDate(texturedOnly)).toBe("");
});

test("a non-lab_test log answers the empty value, never an invented one", () => {
  const { store, land } = setup();
  // An activity log carrying a test quantity: it has none of the lab bundle
  // fields, so every scalar lab probe reads '' — and the measurement still
  // folds the quantity's method (test_method rides on the quantity, not the
  // log's bundle), which is the material_type_recorded house form.
  const activity = store.recordLog({
    kind: "activity", name: "Field work", status: "done", assetIds: [land],
    quantities: [testQty("Titration")],
  });
  expect(store.labSampleType(activity)).toBe("");
  expect(store.laboratory(activity)).toBe("");
  expect(store.soilTexture(activity)).toBe("");
  expect(store.labProcessingDate(activity)).toBe("");
  expect(store.sampleReceivedDate(activity)).toBe("");
});

test("a deleted test quantity drops from the measurement fold (recorded state, not input echo)", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "lab_test", name: "Corrected panel", status: "done", assetIds: [land],
    quantities: [testQty("Titration")],
  });
  expect(store.labTestMeasurement(log)).toEqual(["Titration"]);
  const qId = store.logView(log)!.quantities[0].quantityId;
  store.deleteQuantity(qId);
  expect(store.labTestMeasurement(log)).toEqual([]);
});

test("an unknown or deleted log is unanswerable, never the empty value", () => {
  const { store, land } = setup();
  const log = store.recordLog({
    kind: "lab_test", name: "Doomed panel", status: "done", assetIds: [land],
    quantities: [testQty("Titration")],
    extras: { labSampleType: "soil", laboratory: "Redwood Analytical",
              soilTexture: "Loam", labProcessedDate: "2026-06-15T00:00:00+00:00",
              labReceivedDate: "2026-06-10T00:00:00+00:00" },
  });
  store.deleteLog(log);
  expect(store.labSampleType(log)).toBeUndefined();
  expect(store.laboratory(log)).toBeUndefined();
  expect(store.labProcessingDate(log)).toBeUndefined();
  expect(store.sampleReceivedDate(log)).toBeUndefined();
  expect(store.soilTexture(log)).toBeUndefined();
  expect(store.labTestMeasurement(log)).toBeUndefined();

  const ghost = store.mint("log");
  expect(store.labSampleType(ghost)).toBeUndefined();
  expect(store.labTestMeasurement(ghost)).toBeUndefined();
});
