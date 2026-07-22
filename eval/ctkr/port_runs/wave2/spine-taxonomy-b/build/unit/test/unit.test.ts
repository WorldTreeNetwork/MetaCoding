import { test, expect } from "bun:test";
import { makeUnitAdapter, UNIT_VID } from "../src/unit.ts";
import { TaxonomyVocabStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new TaxonomyVocabStore({ replicaId: "W2B_UN" });
  const port = makeUnitAdapter(store);
  return { store, port };
}

test("port serves the unit vocabulary with its verbatim install-config name", () => {
  const { port } = setup();
  expect(UNIT_VID).toBe("unit");
  expect(port.vid).toBe("unit");
  expect(port.vocabularyName()).toBe("Unit");
});

test("addTerm creates a readable term with a replica-scoped handle", () => {
  const { port } = setup();
  const h = port.addTerm({ name: "kilogram", description: "a unit term" });
  expect(String(h)).toMatch(/~\d+$/);
  expect(port.term(h)?.name).toBe("kilogram");
  expect(port.term(h)?.vocab).toBe("unit");
  expect(port.termCount()).toBe(1);
});

test("rename / describe / reweight are latest-wins", () => {
  const { port } = setup();
  const h = port.addTerm({ name: "kilogram", weight: 0 });
  port.renameTerm(h, "kilogram-renamed");
  port.describeTerm(h, "restated");
  port.reweightTerm(h, 3);
  expect(port.term(h)?.name).toBe("kilogram-renamed");
  expect(port.term(h)?.description).toBe("restated");
  expect(port.term(h)?.weight).toBe(3);
});

test("removeTerm drops the term from listing and count", () => {
  const { port } = setup();
  const h = port.addTerm({ name: "liter" });
  expect(port.termCount()).toBe(1);
  port.removeTerm(h);
  expect(port.term(h)).toBeUndefined();
  expect(port.termCount()).toBe(0);
});

test("terms list in Drupal default order (weight asc, then name asc)", () => {
  const { port } = setup();
  const second = port.addTerm({ name: "liter", weight: 0 });
  const first = port.addTerm({ name: "kilogram", weight: -1 });
  const ordered = port.terms().map((t) => t.termId);
  expect(ordered[0]).toBe(first); // lower weight sorts first
  expect(ordered).toContain(second);
  expect(ordered.length).toBe(2);
});

test("this port cannot see another vocabulary's terms (vid isolation)", () => {
  const { store, port } = setup();
  // a term written directly into a DIFFERENT vocabulary is invisible here.
  const other = store.createTerm({ vocab: "season", name: "elsewhere" });
  expect(port.term(other)).toBeUndefined();
  expect(port.termCount()).toBe(0);
});
