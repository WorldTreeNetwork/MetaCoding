import { test, expect } from "bun:test";
import { makeLogCategoryAdapter } from "../src/log_category.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

test("log_category terms are created scoped to their vocabulary", () => {
  const a = makeLogCategoryAdapter();
  const id = a.createTerm({ name: "Fieldwork" });
  expect(a.term(id)!.vocabulary).toBe("log_category");
});

test("active-only tree with depth matches the LogCategorize form's loadTree usage", () => {
  // The punted-up categorize form renders active terms with depth-based indent;
  // the term-store shell honestly supports that read (loadTree active + depth),
  // even though the categorize WORKFLOW itself is punted (see punts.jsonl).
  const a = makeLogCategoryAdapter();
  const parent = a.createTerm({ name: "Animal" });
  const child = a.createTerm({ name: "Vaccination", parent: parent });
  const hidden = a.createTerm({ name: "Archived", parent: parent });
  a.updateTerm(hidden, { status: false });
  const active = a.listTerms({ activeOnly: true });
  expect(active.map((v) => v.name)).toEqual(["Animal", "Vaccination"]);
  expect(a.depth(child)).toBe(1);
});

test("bundle scoping hides terms from other vocabularies", () => {
  const store = new TaxonomyTermStore({ replicaId: "SHARED" });
  const a = makeLogCategoryAdapter(store);
  const foreign = store.createTerm("lab", { name: "Soil Lab" });
  expect(a.term(foreign)).toBeUndefined();
  expect(a.listTerms()).toHaveLength(0);
});
