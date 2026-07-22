import { test, expect } from "bun:test";
import { makeEquipmentTypeAdapter } from "../src/equipment_type.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

test("equipment_type terms are created scoped to their vocabulary", () => {
  const a = makeEquipmentTypeAdapter();
  const id = a.createTerm({ name: "Tractor" });
  expect(a.term(id)!.vocabulary).toBe("equipment_type");
});

test("editable weight re-orders the listing (latest-wins)", () => {
  const a = makeEquipmentTypeAdapter();
  const t = a.createTerm({ name: "Tiller", weight: 10 });
  a.createTerm({ name: "Auger", weight: 5 });
  expect(a.listTerms().map((v) => v.name)).toEqual(["Auger", "Tiller"]);
  a.updateTerm(t, { weight: 0 });
  expect(a.listTerms().map((v) => v.name)).toEqual(["Tiller", "Auger"]);
});

test("bundle scoping hides terms from other vocabularies", () => {
  const store = new TaxonomyTermStore({ replicaId: "SHARED" });
  const a = makeEquipmentTypeAdapter(store);
  const foreign = store.createTerm("animal_type", { name: "Cattle" });
  expect(a.term(foreign)).toBeUndefined();
  expect(a.listTerms()).toHaveLength(0);
});
