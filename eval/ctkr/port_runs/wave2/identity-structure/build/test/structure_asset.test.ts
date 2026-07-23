// Identity-tier tests for the structure port (MetaCoding-xq7). The
// pack-observed shape (pack b2c2aea9d885): one bundle field — the
// structure_type machine id — read back off the structure asset itself as
// structure_kind, with the stated fallback "other" when the structure was born
// without a descriptor, plus archive_asset / asset_active over the structure's
// handle where the recorded kind survives archive. Plus the port-only
// invariants the recording cannot state, each aimed at a specific fake:
//
//   "could the fallback be faked by always answering 'other'?"      -> distinct
//        recorded kinds must read back distinctly (the pack's fixture 1 also
//        discriminates this, and the tests keep the contrast local).
//   "could kind survive archive by accident?"                        -> archive
//        one of TWO structures: the archived one keeps its kind while its
//        active flips, the sibling's both stay — so kind is provably not
//        derived from lifecycle state, and archive is per-handle.
//   "could the fallback leak onto non-structures?"                   -> a
//        NON-structure asset carrying a descriptor (a typed material) must be
//        unanswerable, never its descriptor and never "other".
//
// These tests are NOT load-bearing — a fresh reader re-runs them and re-derives
// against the pack. They read the MATERIALIZED asset state, never a caller-held
// input echo.

import { test, expect } from "bun:test";
import { Wave1LogStore } from "../../../../wave1/shared-store/src/store.ts";

function setup() {
  return new Wave1LogStore({ replicaId: "W2ST" });
}

test("two structures recording different kinds each report their own recorded kind (never a blanket 'other')", () => {
  const store = setup();
  const s1 = store.createAsset({ entity: "structure", name: "w5a-North Greenhouse", descriptor: "greenhouse" });
  const s2 = store.createAsset({ entity: "structure", name: "w5a-Equipment Shed", descriptor: "building" });
  expect(store.structureKind(s1)).toBe("greenhouse");
  expect(store.structureKind(s2)).toBe("building");
  // The anti-fake contrast: neither reads the fallback, and they differ.
  expect(store.structureKind(s1)).not.toBe("other");
  expect(store.structureKind(s1)).not.toBe(store.structureKind(s2));
});

test("a structure born without a descriptor reads the stated fallback 'other' — a value, not ''", () => {
  const store = setup();
  const s = store.createAsset({ entity: "structure", name: "w5a-Unclassified Lean-to" });
  expect(store.structureKind(s)).toBe("other");
  expect(store.structureKind(s)).not.toBe("");
});

test("wire-'' descriptor is the unstated shape and falls back too — no path materializes an empty kind", () => {
  const store = setup();
  // The bridge normalizes "" off before recording; the fold guards "" as well,
  // so even a direct store caller handing "" through cannot read back "".
  const s = store.createAsset({ entity: "structure", name: "w5a-Blank Shed", descriptor: "" });
  expect(store.structureKind(s)).toBe("other");
});

test("a structure recorded explicitly as 'other' reads 'other' — indistinguishable from the fallback, deliberately", () => {
  const store = setup();
  const explicit = store.createAsset({ entity: "structure", name: "w5a-Odd Silo", descriptor: "other" });
  const unstated = store.createAsset({ entity: "structure", name: "w5a-Mystery Hut" });
  expect(store.structureKind(explicit)).toBe("other");
  expect(store.structureKind(explicit)).toBe(store.structureKind(unstated)!);
});

test("archive flips asset_active per-handle while the recorded kind survives — kind is not derived from lifecycle state", () => {
  const store = setup();
  const retired = store.createAsset({ entity: "structure", name: "w5a-Retired Barn", descriptor: "building" });
  const kept = store.createAsset({ entity: "structure", name: "w5a-Working Greenhouse", descriptor: "greenhouse" });
  store.archiveAsset(retired);
  // The archived structure leaves the active set but keeps its kind.
  expect(store.assetActive(retired)).toBe(false);
  expect(store.structureKind(retired)).toBe("building");
  // The sibling is untouched on BOTH axes — archive is per-handle, and kind
  // could not have survived by accident of a global or lifecycle-coupled read.
  expect(store.assetActive(kept)).toBe(true);
  expect(store.structureKind(kept)).toBe("greenhouse");
});

test("an archived fallback structure still reads 'other' — the fallback also folds off the birth, not the lifecycle", () => {
  const store = setup();
  const s = store.createAsset({ entity: "structure", name: "w5a-Retired Lean-to" });
  store.archiveAsset(s);
  expect(store.assetActive(s)).toBe(false);
  expect(store.structureKind(s)).toBe("other");
});

test("a subject that is not a structure asset is unanswerable — never 'other', never ''", () => {
  const store = setup();
  // The sharpest fake: a NON-structure asset that CARRIES a descriptor (the
  // material fold's typed material). Its descriptor must not surface as a kind,
  // and the fallback must not fire either.
  const material = store.createAsset({ entity: "material", name: "w5a-Compost Sack", descriptor: "compost" });
  expect(store.structureKind(material)).toBeUndefined();
  // A descriptor-less plain asset — the fallback must not leak here.
  const land = store.createAsset({ entity: "land", name: "w5a-Field" });
  expect(store.structureKind(land)).toBeUndefined();
  // A sensor ASSET — an asset, even, but born through its own event.
  const sensor = store.createSensorAsset({ name: "w5a-Probe" });
  expect(store.structureKind(sensor)).toBeUndefined();
  // A log handle.
  const log = store.recordLog({ kind: "activity", name: "Repair roof", status: "done", assetIds: [land], quantities: [] });
  expect(store.structureKind(log)).toBeUndefined();
  // A plant_type TERM handle.
  const term = store.createPlantTypeTerm({ name: "w5a-Tomato" });
  expect(store.structureKind(term)).toBeUndefined();
  // A ghost handle never minted as anything.
  const ghost = store.mint("asset");
  expect(store.structureKind(ghost)).toBeUndefined();
});

test("distinct structures are distinct handles with no cross-structure bleed", () => {
  const store = setup();
  const a = store.createAsset({ entity: "structure", name: "w5a-A", descriptor: "greenhouse" });
  const b = store.createAsset({ entity: "structure", name: "w5a-B" });
  expect(a).not.toBe(b);
  // b stated nothing — it must not inherit a's kind, and a is unchanged by b.
  expect(store.structureKind(b)).toBe("other");
  expect(store.structureKind(a)).toBe("greenhouse");
});

test("a structure participates in the log family as a plain asset (kind adds no log-spine surface)", () => {
  const store = setup();
  const s = store.createAsset({ entity: "structure", name: "w5a-Barn", descriptor: "building" });
  // Its birth is not a log and inflates nothing.
  expect(store.logCount(s, "activity")).toBe(0);
  // A log referencing the structure counts exactly as it would for any asset.
  store.recordLog({ kind: "activity", name: "Sweep floor", status: "done", assetIds: [s], quantities: [] });
  expect(store.logCount(s, "activity")).toBe(1);
  // And recording logs against it never changes its kind.
  expect(store.structureKind(s)).toBe("building");
});
