import { test, expect } from "bun:test";
import { makeSeedAdapter } from "../src/seed.ts";
import { SpineAssetStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new SpineAssetStore({ replicaId: "seed" });
  return { store, port: makeSeedAdapter(store) };
}

test("seed requires at least one plant_type (crop/variety)", () => {
  const { port } = setup();
  expect(() => port.createSeed("packet 1", [])).toThrow(/requires field 'plant_type'/);
});

test("seed shares the plant field shape: multi crop/variety + optional seasons", () => {
  const { port, store } = setup();
  const s = port.createSeed("tomato seed", ["term:tomato"], ["term:2026", "term:spring"]);
  expect(port.plantTypesOf(s)).toEqual(["term:tomato"]);
  expect(port.seasonsOf(s)).toEqual(["term:2026", "term:spring"]);
  expect(store.bundleOf(s)).toBe("seed");
  port.archive(s);
  expect(port.isActive(s)).toBe(false);
});
