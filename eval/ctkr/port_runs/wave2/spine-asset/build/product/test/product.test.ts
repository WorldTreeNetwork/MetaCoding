import { test, expect } from "bun:test";
import { makeProductAdapter } from "../src/product.ts";
import { SpineAssetStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new SpineAssetStore({ replicaId: "product" });
  return { store, port: makeProductAdapter(store) };
}

test("product requires product_type at creation", () => {
  const { port } = setup();
  // @ts-expect-error product_type is required by the surface
  expect(() => port.createProduct("jam")).toThrow(/requires field 'product_type'/);
  expect(() => port.createProduct("jam", "")).toThrow(/requires field 'product_type'/);
});

test("a product carries its required term and archives on the spine", () => {
  const { port } = setup();
  const p = port.createProduct("strawberry jam", "term:preserve");
  expect(port.productTypeOf(p)).toBe("term:preserve");
  port.archive(p);
  expect(port.isActive(p)).toBe(false);
});
