import { test, expect } from "bun:test";
import { makeHarvestLoggingAdapter, HARVEST_KINDS } from "../src/harvest.ts";
import { Wave1LogStore } from "../../../shared-store/src/store.ts";

const NOW = Date.now();

function setup() {
  const store = new Wave1LogStore({ replicaId: "W1C", extraKinds: HARVEST_KINDS });
  const port = makeHarvestLoggingAdapter(store);
  const actor = store.mint("actor");
  return { store, port, actor };
}

test("recordPlanting creates the plant and its movement legs; movements are never logs", () => {
  const { store, port, actor } = setup();
  const loc = store.createAsset({ entity: "land", name: "greenhouse" });
  const { plant, movements } = port.recordPlanting(actor, {
    seasons: [{ id: store.mint("season"), label: "2026" }],
    crops: [{ id: store.mint("crop"), label: "tomato" }],
    seeding: { location: loc, occurredAt: NOW - 50_000, done: true },
    transplanting: { location: loc, occurredAt: NOW - 20_000 }, // pending by default
  });
  expect(movements.length).toBe(2);
  expect(store.logCount(plant, "harvest")).toBe(0); // movements don't count as logs
  expect(store.registry.isLog("movement_recorded")).toBe(false);
});

test("pending movement does not establish location; confirming it does", () => {
  const { store, port, actor } = setup();
  const seedLoc = store.createAsset({ entity: "land", name: "greenhouse" });
  const fieldLoc = store.createAsset({ entity: "land", name: "field" });
  const { plant, movements } = port.recordPlanting(actor, {
    seasons: [], crops: [],
    seeding: { location: seedLoc, occurredAt: NOW - 50_000, done: true },
    transplanting: { location: fieldLoc, occurredAt: NOW - 20_000 }, // pending
  });
  expect(port.getPlantLocation(actor, plant, NOW)).toBe(seedLoc);
  port.confirmRecord(actor, movements[1]!);
  expect(port.getPlantLocation(actor, plant, NOW)).toBe(fieldLoc);
});

test("display name: custom only when enabled and nonempty; else seasons '/' + crops ', '", () => {
  const { store, port, actor } = setup();
  const mk = (input: Parameters<typeof port.recordPlanting>[1]) =>
    port.recordPlanting(actor, input).plant;
  const gen = mk({
    seasons: [{ id: store.mint("s"), label: "2025" }, { id: store.mint("s"), label: "2026" }],
    crops: [{ id: store.mint("c"), label: "kale" }, { id: store.mint("c"), label: "chard" }],
  });
  expect(port.getPlantDisplayName(actor, gen, NOW)).toBe("2025/2026 kale, chard");
  const custom = mk({
    customName: "Bed 7 kale", customNameEnabled: true,
    seasons: [{ id: store.mint("s"), label: "2026" }], crops: [],
  });
  expect(port.getPlantDisplayName(actor, custom, NOW)).toBe("Bed 7 kale");
  const disabled = mk({
    customName: "ignored", customNameEnabled: false,
    seasons: [{ id: store.mint("s"), label: "2026" }],
    crops: [{ id: store.mint("c"), label: "basil" }],
  });
  expect(port.getPlantDisplayName(actor, disabled, NOW)).toBe("2026 basil");
});

test("remembered season defaults: latest nonempty wins; empty never clears", () => {
  const { store, port, actor } = setup();
  const s1 = store.mint("season");
  const s2 = store.mint("season");
  expect(port.getRememberedSeasonDefaults(actor, Date.now())).toEqual([]);
  port.createPlantingPlan(actor, [{ id: s1, label: "2025" }], []);
  port.createPlantingPlan(actor, [], []); // empty selection — leaves defaults
  expect(port.getRememberedSeasonDefaults(actor, Date.now())).toEqual([s1]);
  port.createPlantingPlan(actor, [{ id: s2, label: "2026" }], []);
  expect(port.getRememberedSeasonDefaults(actor, Date.now())).toEqual([s2]);
});

test("recordHarvest: never a movement; null quantity persists as quantityPayload [null]", () => {
  const { store, port, actor } = setup();
  const { plant } = port.recordPlanting(actor, { seasons: [], crops: [] });
  const h = port.recordHarvest(actor, plant, NOW - 10_000, null, "LOT-7", "done");
  const view = port.getHarvestLog(actor, h, NOW)!;
  expect(view.isMovement).toBe(false);
  expect(view.lotNumber).toBe("LOT-7");
  expect(view.quantityPayload).toEqual([null]);
  expect(store.logCount(plant, "harvest")).toBe(1);
});

test("harvest totals fold through the frozen gates with pending partners", () => {
  const { port, actor } = setup();
  const { plant } = port.recordPlanting(actor, { seasons: [], crops: [] });
  port.recordHarvest(actor, plant, NOW - 30_000,
    { measure: "weight", value: 3, unit: "kilogram", label: "yield" }, null, "done");
  const pending = port.recordHarvest(actor, plant, NOW - 20_000,
    { measure: "weight", value: 6, unit: "kilogram", label: "yield" }, null, "pending");
  let t = port.getHarvestTotals(actor, plant, NOW);
  expect(t.yieldTotal).toEqual({ measure: "weight", unit: "kilogram", value: 3 });
  expect(t.logCount).toBe(1);
  expect(t.pendingYieldTotal).toEqual({ measure: "weight", unit: "kilogram", value: 6 });
  expect(t.pendingLogCount).toBe(1);
  port.confirmRecord(actor, pending);
  t = port.getHarvestTotals(actor, plant, NOW);
  expect(t.yieldTotal).toEqual({ measure: "weight", unit: "kilogram", value: 9 });
  expect(t.logCount).toBe(2);
  expect(t.pendingLogCount).toBe(0);
});

test("birth resolution: earliest-hlc-wins; the later concurrent birth is demoted, never dropped", () => {
  const { port, actor } = setup();
  const { plant } = port.recordPlanting(actor, { seasons: [], crops: [] });
  const b1 = port.recordBirth(actor, plant, NOW - 40_000);
  const b2 = port.recordBirth(actor, plant, NOW - 40_000);
  const res = port.getBirthResolution(actor, plant, Date.now());
  expect(res.canonicalBirth).toBe(b1); // earliest by HLC
  expect(res.demotedObservations).toEqual([b2]); // demoted, present, never dropped
});

test("revision markers are merge-aware: all retained in HLC order, latest is current", () => {
  const { port, actor } = setup();
  const { plant } = port.recordPlanting(actor, { seasons: [], crops: [] });
  const h = port.recordHarvest(actor, plant, NOW - 10_000, null, null, "done");
  expect(port.getRevisionState(actor, h, Date.now())).toBeUndefined();
  const r1 = port.markNewRevision(h);
  const r2 = port.markNewRevision(h);
  const state = port.getRevisionState(actor, h, Date.now())!;
  expect(state.revisionHistory).toEqual([r1, r2]);
  expect(state.currentRevision).toBe(r2);
});
