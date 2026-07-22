import { test, expect } from "bun:test";
import { makeMaterialAdapter } from "../src/material.ts";
import { SpineAssetStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new SpineAssetStore({ replicaId: "material" });
  return { store, port: makeMaterialAdapter(store) };
}

test("material requires material_type at creation", () => {
  const { port } = setup();
  // @ts-expect-error material_type is required by the surface
  expect(() => port.createMaterial("compost tea")).toThrow(/requires field 'material_type'/);
  expect(() => port.createMaterial("compost tea", "")).toThrow(/requires field 'material_type'/);
});

test("a material asset carries its required term and archives on the spine", () => {
  const { port, store } = setup();
  const m = port.createMaterial("straw", "term:straw");
  expect(port.materialTypeOf(m)).toBe("term:straw");
  expect(store.isLocation(m)).toBe(false);
  port.archive(m);
  expect(port.isActive(m)).toBe(false);
});
