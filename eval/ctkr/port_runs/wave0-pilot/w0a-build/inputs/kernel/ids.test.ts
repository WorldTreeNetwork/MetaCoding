import { test, expect } from "bun:test";
import { IdMinter, isEntityId, replicaOf, REPLICA_SEP } from "./ids.ts";

test("ids are replica-scoped and collision-free across replicas", () => {
  const a = new IdMinter("A");
  const b = new IdMinter("B");
  // both mint their FIRST id — a bare global counter would collide here.
  const idA = a.mint("asset");
  const idB = b.mint("asset");
  expect(idA).not.toBe(idB);
  expect(idA as string).toBe("asset_A~1");
  expect(idB as string).toBe("asset_B~1");
});

test("IdMinter refuses an empty or malformed replicaId", () => {
  expect(() => new IdMinter("")).toThrow(/replicaId/);
  expect(() => new IdMinter(`bad${REPLICA_SEP}id`)).toThrow(/must not contain/);
});

test("isEntityId / replicaOf", () => {
  const id = new IdMinter("R1").mint("log");
  expect(isEntityId(id)).toBe(true);
  expect(isEntityId("log_7")).toBe(false); // a bare ordinal is NOT a kernel id
  expect(isEntityId(7)).toBe(false);
  expect(replicaOf(id)).toBe("R1");
});
