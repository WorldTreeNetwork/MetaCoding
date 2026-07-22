import { test, expect } from "bun:test";
import { TaxonomyTermStore } from "../src/term_store.ts";

function store() {
  return new TaxonomyTermStore({ replicaId: "T" });
}

test("a created term materializes with its vocabulary and defaults", () => {
  const s = store();
  const id = s.createTerm("animal_type", { name: "Cattle" });
  const v = s.termView(id)!;
  expect(v.vocabulary).toBe("animal_type");
  expect(v.name).toBe("Cattle");
  expect(v.parent).toBeNull();
  expect(v.weight).toBe(0);
  expect(v.status).toBe(true);
  expect(v.description).toBeUndefined();
});

test("term fields are editable — latest write wins per field", () => {
  const s = store();
  const id = s.createTerm("material_type", { name: "Compost", weight: 5, status: true });
  s.updateTerm(id, { name: "Finished Compost" });
  s.updateTerm(id, { status: false });
  const v = s.termView(id)!;
  expect(v.name).toBe("Finished Compost");
  expect(v.weight).toBe(5); // untouched field keeps its created value
  expect(v.status).toBe(false);
});

test("later restatement of the same field supersedes the earlier one", () => {
  const s = store();
  const id = s.createTerm("lab", { name: "Lab A" });
  s.updateTerm(id, { name: "Lab B" });
  s.updateTerm(id, { name: "Lab C" });
  expect(s.termView(id)!.name).toBe("Lab C");
});

test("deleted terms disappear from view and listings", () => {
  const s = store();
  const id = s.createTerm("lab", { name: "Temp" });
  s.deleteTerm(id);
  expect(s.termView(id)).toBeUndefined();
  expect(s.termsInVocabulary("lab")).toHaveLength(0);
});

test("parent reference builds a hierarchy with depth and ancestors", () => {
  const s = store();
  const root = s.createTerm("animal_type", { name: "Mammal" });
  const child = s.createTerm("animal_type", { name: "Cattle", parent: root });
  const grand = s.createTerm("animal_type", { name: "Angus", parent: child });
  expect(s.depthOf(root)).toBe(0);
  expect(s.depthOf(child)).toBe(1);
  expect(s.depthOf(grand)).toBe(2);
  expect(s.ancestorsOf(grand).map((v) => v.name)).toEqual(["Cattle", "Mammal"]);
  expect(s.childrenOf(root).map((v) => v.name)).toEqual(["Cattle"]);
  expect(s.rootsOf("animal_type").map((v) => v.name)).toEqual(["Mammal"]);
});

test("re-parenting is latest-wins on the parent field", () => {
  const s = store();
  const a = s.createTerm("equipment_type", { name: "A" });
  const b = s.createTerm("equipment_type", { name: "B" });
  const child = s.createTerm("equipment_type", { name: "C", parent: a });
  expect(s.depthOf(child)).toBe(1);
  s.updateTerm(child, { parent: null });
  expect(s.termView(child)!.parent).toBeNull();
  expect(s.depthOf(child)).toBe(0);
  s.updateTerm(child, { parent: b });
  expect(s.termView(child)!.parent).toBe(b);
});

test("listing is ordered by (weight, name) with vocabulary scoping", () => {
  const s = store();
  s.createTerm("material_type", { name: "Zeta", weight: 0 });
  s.createTerm("material_type", { name: "Alpha", weight: 0 });
  s.createTerm("material_type", { name: "First", weight: -5 });
  s.createTerm("lab", { name: "OtherVocab", weight: -100 });
  const names = s.termsInVocabulary("material_type").map((v) => v.name);
  expect(names).toEqual(["First", "Alpha", "Zeta"]);
});

test("activeOnly filters unpublished terms (loadTree semantics)", () => {
  const s = store();
  s.createTerm("log_category", { name: "Visible" });
  const hidden = s.createTerm("log_category", { name: "Hidden" });
  s.updateTerm(hidden, { status: false });
  expect(s.termsInVocabulary("log_category", { activeOnly: true }).map((v) => v.name)).toEqual([
    "Visible",
  ]);
  expect(s.termsInVocabulary("log_category")).toHaveLength(2);
});

test("a cycle in parent references terminates the ancestor walk", () => {
  const s = store();
  const a = s.createTerm("lab", { name: "A" });
  const b = s.createTerm("lab", { name: "B", parent: a });
  s.updateTerm(a, { parent: b }); // a -> b -> a cycle
  // must not infinite-loop; depth is bounded by the visited guard
  expect(s.depthOf(a)).toBeLessThanOrEqual(2);
  expect(s.depthOf(b)).toBeLessThanOrEqual(2);
});

test("ancestor walk stops at a deleted (dangling) parent", () => {
  const s = store();
  const root = s.createTerm("lab", { name: "Root" });
  const child = s.createTerm("lab", { name: "Child", parent: root });
  s.deleteTerm(root);
  expect(s.ancestorsOf(child)).toHaveLength(0);
  expect(s.depthOf(child)).toBe(0);
});

test("ad-hoc event kinds are rejected by the frozen registry", () => {
  const s = store();
  // the registry is frozen at construction; the store never emits an unregistered
  // kind, so this asserts the closed-taxonomy guarantee is actually wired.
  expect(s.registry.isFrozen).toBe(true);
  expect(s.registry.has("term_created")).toBe(true);
  expect(s.registry.has("not_a_real_kind")).toBe(false);
});
