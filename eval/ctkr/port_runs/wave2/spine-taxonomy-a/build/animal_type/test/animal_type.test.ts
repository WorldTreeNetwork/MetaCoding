import { test, expect } from "bun:test";
import { makeAnimalTypeAdapter } from "../src/animal_type.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

test("animal_type terms are created scoped to their vocabulary", () => {
  const a = makeAnimalTypeAdapter();
  const id = a.createTerm({ name: "Cattle" });
  expect(a.term(id)!.vocabulary).toBe("animal_type");
  expect(a.term(id)!.name).toBe("Cattle");
});

test("species/breed hierarchy via parent reference", () => {
  const a = makeAnimalTypeAdapter();
  const mammal = a.createTerm({ name: "Mammal" });
  const cattle = a.createTerm({ name: "Cattle", parent: mammal });
  expect(a.depth(cattle)).toBe(1);
  expect(a.children(mammal).map((v) => v.name)).toEqual(["Cattle"]);
});

test("bundle scoping hides terms from other vocabularies", () => {
  const store = new TaxonomyTermStore({ replicaId: "SHARED" });
  const a = makeAnimalTypeAdapter(store);
  const foreign = store.createTerm("lab", { name: "Not an animal type" });
  expect(a.term(foreign)).toBeUndefined();
  expect(a.listTerms()).toHaveLength(0);
});
