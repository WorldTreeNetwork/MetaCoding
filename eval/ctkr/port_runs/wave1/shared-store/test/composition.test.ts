// Wave-1 composition smoke: all FOUR features on ONE accumulated store — the
// point of serializing the cluster through one builder. Also the prevention
// checks the wave plan names: no ad-hoc kinds, no ordinal ids.

import { test, expect } from "bun:test";
import { Wave1LogStore } from "../src/store.ts";
import { isEntityId, replicaOf } from "../../../../../../src/kernel/index.ts";
import { makeActivityAdapter } from "../../activity/build/src/activity.ts";
import { makeObservationAdapter, OBSERVATION_KINDS } from "../../observation/build/src/observation.ts";
import { makeHarvestLoggingAdapter, HARVEST_KINDS } from "../../harvest/build/src/harvest.ts";
import { makeInputLogAdapter } from "../../input/build/src/input.ts";

const NOW = Date.now();

function composedStore() {
  return new Wave1LogStore({
    replicaId: "W1",
    extraKinds: [...OBSERVATION_KINDS, ...HARVEST_KINDS],
  });
}

test("four features accumulate coherently in one store: folds agree across kinds", () => {
  const store = composedStore();
  const activity = makeActivityAdapter(store);
  const observation = makeObservationAdapter(store);
  const harvest = makeHarvestLoggingAdapter(store);
  const input = makeInputLogAdapter(store);
  const actor = store.mint("actor");

  const { plant } = harvest.recordPlanting(actor, { seasons: [], crops: [] });

  activity.recordActivity({ name: "weeding", occurredAt: NOW - 50_000, status: "done", assetHandles: [plant] });
  const q = observation.mintQuantityRevision({ measure: "weight", value: 3, unit: "kilograms" });
  observation.recordObservation([plant], [q], "done", NOW - 40_000);
  harvest.recordHarvest(actor, plant, NOW - 30_000,
    { measure: "weight", value: 9, unit: "kilograms", label: "yield" }, null, "done");
  input.recordInputAgainst(NOW - 20_000, [plant],
    [{ measure: "weight", value: 5, unit: "kilograms", materialTypes: ["compost"] }], "pending");

  // per-kind counts stay isolated
  expect(store.logCount(plant, "activity")).toBe(1);
  expect(store.logCount(plant, "observation")).toBe(1);
  expect(store.logCount(plant, "harvest")).toBe(1);
  expect(store.logCount(plant, "input")).toBe(0); // pending
  expect(store.pendingLogCount(plant, "input")).toBe(1);

  // ONE yield fold across kinds (observed source semantic), one gate table:
  // done observation 3 + done harvest 9; the pending input 5 is partner mass.
  expect(store.yieldTotal(plant, "weight", "kilograms")).toBe(12);
  expect(store.pendingYieldTotal(plant, "weight", "kilograms")).toBe(5);

  // feature-local reads still see only their own kind
  expect(observation.listObservationsForAsset(plant, NOW).length).toBe(1);
  expect(activity.listActivityLogsForAsset(plant, NOW).length).toBe(1);
  expect(input.listInputLogs({ materialType: "compost" }, NOW).length).toBe(1);
});

test("prevention: every handle is a replica-scoped kernel id, never a bare ordinal", () => {
  const store = composedStore();
  const activity = makeActivityAdapter(store);
  const a = store.createAsset({ entity: "land", name: "f" });
  const l = activity.recordActivity({ name: "x", occurredAt: NOW, status: "done", assetHandles: [a] });
  for (const h of [a, l]) {
    expect(isEntityId(h)).toBe(true);
    expect(replicaOf(h as never)).toBe("W1");
  }
});

test("prevention: the composed registry is frozen — no ad-hoc kind can enter the log", () => {
  const store = composedStore();
  expect(store.registry.isFrozen).toBe(true);
  expect(() => store.emit("sneaky_kind", {})).toThrow();
  // and the taxonomy answers is-a-movement-a-log centrally:
  expect(store.registry.isLog("log_recorded")).toBe(true);
  expect(store.registry.isLog("movement_recorded")).toBe(false);
});
