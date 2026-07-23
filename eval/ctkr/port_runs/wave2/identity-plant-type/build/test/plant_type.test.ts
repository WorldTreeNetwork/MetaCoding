// Identity-tier tests for the plant_type port (MetaCoding plant-type). The
// oracle-observed shape (pack dba1550722fa632cd2bc0c2d2ca2c7d4): the four
// planning fields carried ON a plant_type TERM read back off the term itself —
// two integer day counts ('' when the term stated none), the crop_family NAME
// ('' when none), and the ordered companion NAMES ([] when none). Plus the
// port-only invariants the recording cannot state: the day-count fields are
// independent (a maturity never bleeds into a harvest), distinct terms keep
// their own values, and a subject that is not a plant_type term (a log, an
// asset, an unknown handle) is unanswerable, never the empty value.
//
// These tests are NOT load-bearing — a fresh reader re-runs them and re-derives
// against the pack. They read the MATERIALIZED term state, never a caller-held
// input echo (a fresh store is folded through its birth event each read).

import { test, expect } from "bun:test";
import { Wave1LogStore } from "../../../../wave1/shared-store/src/store.ts";

function setup() {
  return new Wave1LogStore({ replicaId: "W2P" });
}

test("two terms recording different maturity each report their own count; a term with none reports ''", () => {
  const store = setup();
  const p1 = store.createPlantTypeTerm({ name: "w3a-Tomato Brandywine", maturityDays: 85 });
  const p2 = store.createPlantTypeTerm({ name: "w3a-Pepper Habanero", maturityDays: 110 });
  const p3 = store.createPlantTypeTerm({ name: "w3a-Lettuce Untimed" });
  expect(store.daysToMaturity(p1)).toBe(85);
  expect(store.daysToMaturity(p2)).toBe(110);
  expect(store.daysToMaturity(p3)).toBe("");
});

test("two terms recording different harvest each report their own count; a term with none reports ''", () => {
  const store = setup();
  const p1 = store.createPlantTypeTerm({ name: "w3a-Bean Bush Blue Lake", harvestDays: 30 });
  const p2 = store.createPlantTypeTerm({ name: "w3a-Radish Cherry", harvestDays: 21 });
  const p3 = store.createPlantTypeTerm({ name: "w3a-Kale Untimed" });
  expect(store.daysToHarvest(p1)).toBe(30);
  expect(store.daysToHarvest(p2)).toBe(21);
  expect(store.daysToHarvest(p3)).toBe("");
});

test("maturity and harvest are DISTINCT fields: a maturity-only term reports the maturity and no harvest", () => {
  const store = setup();
  const p1 = store.createPlantTypeTerm({ name: "w3a-Carrot Nantes", maturityDays: 70 });
  expect(store.daysToMaturity(p1)).toBe(70);
  expect(store.daysToHarvest(p1)).toBe("");
  // and the mirror: a harvest-only term reports the harvest and no maturity.
  const p2 = store.createPlantTypeTerm({ name: "w3a-Harvest Only", harvestDays: 12 });
  expect(store.daysToHarvest(p2)).toBe(12);
  expect(store.daysToMaturity(p2)).toBe("");
});

test("two terms naming different crop families each report their own family; a term naming none reports ''", () => {
  const store = setup();
  const p1 = store.createPlantTypeTerm({ name: "w3a-Tomato Roma", cropFamily: "w3a-Solanaceae" });
  const p2 = store.createPlantTypeTerm({ name: "w3a-Cabbage Savoy", cropFamily: "w3a-Brassicaceae" });
  const p3 = store.createPlantTypeTerm({ name: "w3a-Sunflower Mammoth" });
  expect(store.cropFamily(p1)).toBe("w3a-Solanaceae");
  expect(store.cropFamily(p2)).toBe("w3a-Brassicaceae");
  expect(store.cropFamily(p3)).toBe("");
});

test("companions read back as ordered names: multi, single, and empty", () => {
  const store = setup();
  const multi = store.createPlantTypeTerm({ name: "w3a-Tomato Companioned", companions: ["w3a-Basil", "w3a-Marigold"] });
  const single = store.createPlantTypeTerm({ name: "w3a-Carrot Companioned", companions: ["w3a-Chive"] });
  const none = store.createPlantTypeTerm({ name: "w3a-Onion Solitary" });
  expect(store.companionPlants(multi)).toEqual(["w3a-Basil", "w3a-Marigold"]);
  expect(store.companionPlants(single)).toEqual(["w3a-Chive"]);
  expect(store.companionPlants(none)).toEqual([]);
});

test("companion order is preserved (not sorted, not reversed)", () => {
  const store = setup();
  const p = store.createPlantTypeTerm({ name: "w3a-Ordered", companions: ["w3a-Zeta", "w3a-Alpha", "w3a-Mu"] });
  expect(store.companionPlants(p)).toEqual(["w3a-Zeta", "w3a-Alpha", "w3a-Mu"]);
});

test("a term carrying all four fields reports each independently (the all-fields fixture)", () => {
  const store = setup();
  const p = store.createPlantTypeTerm({
    name: "w3a-Bean Three Sisters",
    maturityDays: 95,
    harvestDays: 14,
    cropFamily: "w3a-Fabaceae",
    companions: ["w3a-Corn", "w3a-Squash"],
  });
  expect(store.daysToMaturity(p)).toBe(95);
  expect(store.daysToHarvest(p)).toBe(14);
  expect(store.cropFamily(p)).toBe("w3a-Fabaceae");
  expect(store.companionPlants(p)).toEqual(["w3a-Corn", "w3a-Squash"]);
});

test("a subject that is not a plant_type term is unanswerable, never the empty value", () => {
  const store = setup();
  // An asset handle: real, but not a plant_type term.
  const asset = store.createAsset({ entity: "land", name: "Panel Plot" });
  expect(store.daysToMaturity(asset)).toBeUndefined();
  expect(store.daysToHarvest(asset)).toBeUndefined();
  expect(store.cropFamily(asset)).toBeUndefined();
  expect(store.companionPlants(asset)).toBeUndefined();
  // A log handle: also not a plant_type term.
  const log = store.recordLog({ kind: "activity", name: "Field work", status: "done", assetIds: [asset], quantities: [] });
  expect(store.daysToMaturity(log)).toBeUndefined();
  expect(store.companionPlants(log)).toBeUndefined();
  // A ghost handle that was never minted as a term.
  const ghost = store.mint("term");
  expect(store.daysToMaturity(ghost)).toBeUndefined();
  expect(store.cropFamily(ghost)).toBeUndefined();
  expect(store.companionPlants(ghost)).toBeUndefined();
});

test("distinct terms are distinct handles (no cross-term bleed)", () => {
  const store = setup();
  const a = store.createPlantTypeTerm({ name: "w3a-A", maturityDays: 5, cropFamily: "w3a-Fam-A", companions: ["w3a-Buddy-A"] });
  const b = store.createPlantTypeTerm({ name: "w3a-B" });
  expect(a).not.toBe(b);
  // b stated nothing — it must not inherit a's values.
  expect(store.daysToMaturity(b)).toBe("");
  expect(store.cropFamily(b)).toBe("");
  expect(store.companionPlants(b)).toEqual([]);
  // a is unchanged by b's birth.
  expect(store.daysToMaturity(a)).toBe(5);
  expect(store.cropFamily(a)).toBe("w3a-Fam-A");
  expect(store.companionPlants(a)).toEqual(["w3a-Buddy-A"]);
});

test("the readback is materialized state, not an input-object echo: a mutated caller array does not change the recorded companions", () => {
  const store = setup();
  const companions = ["w3a-Basil", "w3a-Marigold"];
  const p = store.createPlantTypeTerm({ name: "w3a-Snapshot", companions });
  companions.push("w3a-Intruder");
  companions[0] = "w3a-Mutated";
  // The recorded term folds back its OWN copy, unaffected by the caller's edits.
  expect(store.companionPlants(p)).toEqual(["w3a-Basil", "w3a-Marigold"]);
});
