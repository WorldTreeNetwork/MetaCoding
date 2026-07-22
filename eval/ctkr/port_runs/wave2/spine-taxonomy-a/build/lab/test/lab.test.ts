import { test, expect } from "bun:test";
import { makeLabAdapter } from "../src/lab.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

test("lab terms are created scoped to their vocabulary", () => {
  const a = makeLabAdapter();
  const id = a.createTerm({ name: "Soil Lab" });
  expect(a.term(id)!.vocabulary).toBe("lab");
});

test("unpublishing a term hides it from the active listing", () => {
  const a = makeLabAdapter();
  a.createTerm({ name: "Active Lab" });
  const closed = a.createTerm({ name: "Closed Lab" });
  a.updateTerm(closed, { status: false });
  expect(a.listTerms({ activeOnly: true }).map((v) => v.name)).toEqual(["Active Lab"]);
  expect(a.listTerms()).toHaveLength(2);
});

test("bundle scoping hides terms from other vocabularies", () => {
  const store = new TaxonomyTermStore({ replicaId: "SHARED" });
  const a = makeLabAdapter(store);
  const foreign = store.createTerm("material_type", { name: "Compost" });
  expect(a.term(foreign)).toBeUndefined();
  expect(a.listTerms()).toHaveLength(0);
});
