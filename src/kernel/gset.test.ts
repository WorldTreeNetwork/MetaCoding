import { test, expect } from "bun:test";
import { GSet } from "./gset.ts";
import type { Hlc } from "./hlc.ts";

const h = (physical: number, logical = 0, replicaId = "R1"): Hlc => ({ physical, logical, replicaId });

test("appends are read back in HLC order, not insertion order", () => {
  const s = new GSet<string>();
  s.add("Bess", h(30));
  s.add("Bessie", h(10));
  s.add("Bee", h(20));
  expect(s.values()).toEqual(["Bessie", "Bee", "Bess"]);
});

test("grow-only: no dedup by value (a multiset)", () => {
  const s = new GSet<string>();
  s.add("Bess", h(10));
  s.add("Bess", h(20)); // same value, distinct HLC — BOTH kept
  expect(s.values()).toEqual(["Bess", "Bess"]);
  expect(s.size).toBe(2);
});

test("re-adding the same HLC is an idempotent no-op (replay-safe)", () => {
  const s = new GSet<string>();
  expect(s.add("Bess", h(10))).toBe(true);
  expect(s.add("Bess", h(10))).toBe(false); // replay of the same append
  expect(s.size).toBe(1);
});

test("replay-determinism: any add order yields the same sequence", () => {
  const forward = new GSet<string>();
  forward.add("a", h(10));
  forward.add("b", h(20));
  forward.add("c", h(30));

  const shuffled = new GSet<string>();
  shuffled.add("c", h(30));
  shuffled.add("a", h(10));
  shuffled.add("b", h(20));

  expect(shuffled.values()).toEqual(forward.values());
  expect(forward.values()).toEqual(["a", "b", "c"]);
});

test("cross-replica merge is a commutative, idempotent union", () => {
  const r1 = new GSet<string>();
  r1.add("Bess", h(10, 0, "A"));
  r1.add("Bee", h(30, 0, "A"));

  const r2 = new GSet<string>();
  r2.add("Bella", h(20, 0, "B"));
  r2.add("Bee", h(30, 0, "A")); // r2 already saw r1's Bee

  const m12 = new GSet<string>().merge(r1).merge(r2);
  const m21 = new GSet<string>().merge(r2).merge(r1);

  // Order-independent, and the shared Bee entry is not doubled.
  expect(m12.values()).toEqual(["Bess", "Bella", "Bee"]);
  expect(m21.values()).toEqual(m12.values());
  expect(m12.size).toBe(3);
});

test("merging twice changes nothing (idempotent)", () => {
  const src = new GSet<string>();
  src.add("x", h(10));
  const dst = new GSet<string>().merge(src).merge(src);
  expect(dst.size).toBe(1);
});

test("constructs from entries and reports membership", () => {
  const s = new GSet<string>([
    { value: "x", hlc: h(10) },
    { value: "y", hlc: h(20) },
  ]);
  expect(s.has("x")).toBe(true);
  expect(s.has("z")).toBe(false);
  expect(s.entries().map((e) => e.value)).toEqual(["x", "y"]);
});
