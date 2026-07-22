import { test, expect } from "bun:test";
import { makeWaterAdapter } from "../src/water.ts";
import { SpineAssetStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new SpineAssetStore({ replicaId: "water" });
  return { store, port: makeWaterAdapter(store) };
}

test("water defaults is_location=true and is_fixed=true (the only such bundle)", () => {
  const { port } = setup();
  const w = port.createWater("north reservoir");
  expect(port.isLocation(w)).toBe(true);
  expect(port.isFixed(w)).toBe(true);
  expect(port.isActive(w)).toBe(true);
});

test("a per-asset override wins over the water bundle default", () => {
  const { port } = setup();
  const mobile = port.createWater("water tanker", { isLocation: false, isFixed: false });
  expect(port.isLocation(mobile)).toBe(false);
  expect(port.isFixed(mobile)).toBe(false);
});

test("water archives on the shared spine", () => {
  const { port } = setup();
  const w = port.createWater("pond");
  port.archive(w);
  expect(port.isActive(w)).toBe(false);
});
