import { test, expect } from "bun:test";
import { makeMaterialTypeAdapter } from "../src/material_type.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

test("material_type terms are created scoped to their vocabulary", () => {
  const a = makeMaterialTypeAdapter();
  const id = a.createTerm({ name: "Compost" });
  expect(a.term(id)!.vocabulary).toBe("material_type");
});

test("hierarchy + re-parenting via latest-wins parent field", () => {
  const a = makeMaterialTypeAdapter();
  const organic = a.createTerm({ name: "Organic" });
  const synthetic = a.createTerm({ name: "Synthetic" });
  const compost = a.createTerm({ name: "Compost", parent: organic });
  expect(a.ancestors(compost).map((v) => v.name)).toEqual(["Organic"]);
  a.updateTerm(compost, { parent: synthetic });
  expect(a.ancestors(compost).map((v) => v.name)).toEqual(["Synthetic"]);
});

test("bundle scoping hides terms from other vocabularies", () => {
  const store = new TaxonomyTermStore({ replicaId: "SHARED" });
  const a = makeMaterialTypeAdapter(store);
  const foreign = store.createTerm("equipment_type", { name: "Tractor" });
  expect(a.term(foreign)).toBeUndefined();
  expect(a.listTerms()).toHaveLength(0);
});
