import { test, expect } from "bun:test";
import { makeProductTypeAdapter, PRODUCTTYPE_VID } from "../src/product_type.ts";
import { TaxonomyVocabStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new TaxonomyVocabStore({ replicaId: "W2B_PT" });
  const port = makeProductTypeAdapter(store);
  return { store, port };
}

test("port serves the product_type vocabulary with its verbatim install-config name", () => {
  const { port } = setup();
  expect(PRODUCTTYPE_VID).toBe("product_type");
  expect(port.vid).toBe("product_type");
  expect(port.vocabularyName()).toBe("Product type");
});

test("addTerm creates a readable term with a replica-scoped handle", () => {
  const { port } = setup();
  const h = port.addTerm({ name: "cheese", description: "a product_type term" });
  expect(String(h)).toMatch(/~\d+$/);
  expect(port.term(h)?.name).toBe("cheese");
  expect(port.term(h)?.vocab).toBe("product_type");
  expect(port.termCount()).toBe(1);
});

test("rename / describe / reweight are latest-wins", () => {
  const { port } = setup();
  const h = port.addTerm({ name: "cheese", weight: 0 });
  port.renameTerm(h, "cheese-renamed");
  port.describeTerm(h, "restated");
  port.reweightTerm(h, 3);
  expect(port.term(h)?.name).toBe("cheese-renamed");
  expect(port.term(h)?.description).toBe("restated");
  expect(port.term(h)?.weight).toBe(3);
});

test("removeTerm drops the term from listing and count", () => {
  const { port } = setup();
  const h = port.addTerm({ name: "butter" });
  expect(port.termCount()).toBe(1);
  port.removeTerm(h);
  expect(port.term(h)).toBeUndefined();
  expect(port.termCount()).toBe(0);
});

test("terms list in Drupal default order (weight asc, then name asc)", () => {
  const { port } = setup();
  const second = port.addTerm({ name: "butter", weight: 0 });
  const first = port.addTerm({ name: "cheese", weight: -1 });
  const ordered = port.terms().map((t) => t.termId);
  expect(ordered[0]).toBe(first); // lower weight sorts first
  expect(ordered).toContain(second);
  expect(ordered.length).toBe(2);
});

test("this port cannot see another vocabulary's terms (vid isolation)", () => {
  const { store, port } = setup();
  // a term written directly into a DIFFERENT vocabulary is invisible here.
  const other = store.createTerm({ vocab: "unit", name: "elsewhere" });
  expect(port.term(other)).toBeUndefined();
  expect(port.termCount()).toBe(0);
});
