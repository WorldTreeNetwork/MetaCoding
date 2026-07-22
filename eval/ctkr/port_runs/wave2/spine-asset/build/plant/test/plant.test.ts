import { test, expect } from "bun:test";
import { makePlantAdapter } from "../src/plant.ts";
import { SpineAssetStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new SpineAssetStore({ replicaId: "plant" });
  return { store, port: makePlantAdapter(store) };
}

test("plant requires at least one plant_type (crop/variety)", () => {
  const { port } = setup();
  expect(() => port.createPlant("row 1", [])).toThrow(/requires field 'plant_type'/);
});

test("plant carries multi-valued crop/variety and optional seasons", () => {
  const { port } = setup();
  const p = port.createPlant("row 1", ["term:tomato", "term:brandywine"], ["term:2026"]);
  expect(port.plantTypesOf(p)).toEqual(["term:tomato", "term:brandywine"]);
  expect(port.seasonsOf(p)).toEqual(["term:2026"]);

  const noSeason = port.createPlant("row 2", ["term:basil"]);
  expect(port.seasonsOf(noSeason)).toEqual([]);
  expect(port.isActive(p)).toBe(true);
});
