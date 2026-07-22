import { test, expect } from "bun:test";
import { TaxonomyVocabStore } from "../src/store.ts";
import { VOCABULARIES } from "../src/vocabularies.ts";

function store() {
  return new TaxonomyVocabStore({ replicaId: "B0" });
}

test("all four spine-b vocabularies are registered with verbatim names/descriptions", () => {
  const s = store();
  expect(s.vocabularyName("product_type")).toBe("Product type");
  expect(s.vocabularyName("season")).toBe("Season");
  expect(s.vocabularyName("test_method")).toBe("Test method");
  expect(s.vocabularyName("unit")).toBe("Unit");
  expect(s.vocabulary("unit")?.description).toBe("A list of units for measurement purposes.");
  expect(s.hasVocabulary("nope")).toBe(false);
  expect(VOCABULARIES.length).toBe(4);
});

test("createTerm mints a replica-scoped handle (never a bare ordinal) and is readable", () => {
  const s = store();
  const t = s.createTerm({ vocab: "season", name: "Spring", description: "the wet one", weight: 2 });
  expect(String(t)).toMatch(/~\d+$/);
  expect(s.termName(t)).toBe("Spring");
  expect(s.termDescription(t)).toBe("the wet one");
  expect(s.termWeight(t)).toBe(2);
});

test("createTerm into an unregistered vocabulary is refused (closed vocab set)", () => {
  const s = store();
  expect(() => s.createTerm({ vocab: "not_a_vocab", name: "x" })).toThrow(/no vocabulary/);
});

test("rename / redescribe / reweight are latest-wins on the HLC", () => {
  const s = store();
  const t = s.createTerm({ vocab: "unit", name: "kg", description: "kilograms", weight: 0 });
  s.renameTerm(t, "kilogram");
  s.setTermDescription(t, "SI mass unit");
  s.setTermWeight(t, 5);
  expect(s.termName(t)).toBe("kilogram");
  expect(s.termDescription(t)).toBe("SI mass unit");
  expect(s.termWeight(t)).toBe(5);
  // a later rename supersedes the earlier one
  s.renameTerm(t, "kg (final)");
  expect(s.termName(t)).toBe("kg (final)");
});

test("description can be cleared latest-wins to undefined", () => {
  const s = store();
  const t = s.createTerm({ vocab: "unit", name: "each", description: "a countable unit" });
  expect(s.termDescription(t)).toBe("a countable unit");
  s.setTermDescription(t, undefined);
  expect(s.termDescription(t)).toBeUndefined();
});

test("deleteTerm drops the term from every projection", () => {
  const s = store();
  const t = s.createTerm({ vocab: "test_method", name: "titration" });
  expect(s.termView(t)).toBeDefined();
  s.deleteTerm(t);
  expect(s.termView(t)).toBeUndefined();
  expect(s.termName(t)).toBeUndefined();
  expect(s.termCount("test_method")).toBe(0);
});

test("listTerms is Drupal default order: weight asc, then name asc, HLC as final tie-break", () => {
  const s = store();
  const c = s.createTerm({ vocab: "product_type", name: "cheese", weight: 0 });
  const a = s.createTerm({ vocab: "product_type", name: "apple", weight: 0 });
  const b = s.createTerm({ vocab: "product_type", name: "butter", weight: -1 });
  const dup1 = s.createTerm({ vocab: "product_type", name: "dup", weight: 5 });
  const dup2 = s.createTerm({ vocab: "product_type", name: "dup", weight: 5 });
  // butter (weight -1) first; then apple, cheese (weight 0, name asc); then the
  // two "dup" terms in append (HLC) order.
  expect(s.listTerms("product_type").map((t) => t.termId)).toEqual([b, a, c, dup1, dup2]);
});

test("terms are vocabulary-isolated in listing and count", () => {
  const s = store();
  s.createTerm({ vocab: "season", name: "Spring" });
  s.createTerm({ vocab: "unit", name: "liter" });
  expect(s.termCount("season")).toBe(1);
  expect(s.termCount("unit")).toBe(1);
  expect(s.listTerms("season").map((t) => t.name)).toEqual(["Spring"]);
});

test("every emitted event carries a registered kind (closed taxonomy holds)", () => {
  const s = store();
  const t = s.createTerm({ vocab: "unit", name: "gram" });
  s.renameTerm(t, "g");
  s.deleteTerm(t);
  for (const e of s.events()) {
    expect(s.registry.isLog(e.kind)).toBe(false); // no term event is a log
  }
});
