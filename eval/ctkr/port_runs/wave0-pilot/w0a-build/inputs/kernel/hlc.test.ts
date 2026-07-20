import { test, expect } from "bun:test";
import { HlcClock, compareHlc, hlcEqual, hlcToString, parseHlc, type Hlc } from "./hlc.ts";

test("tick is strictly monotonic within a replica even at a frozen wall clock", () => {
  const clock = new HlcClock("R1", () => 1000); // wall never advances
  const a = clock.tick();
  const b = clock.tick();
  const c = clock.tick();
  expect(a.physical).toBe(1000);
  expect(a.logical).toBe(0);
  expect(b.logical).toBe(1);
  expect(c.logical).toBe(2);
  expect(compareHlc(a, b)).toBeLessThan(0);
  expect(compareHlc(b, c)).toBeLessThan(0);
});

test("physical advance resets the logical counter", () => {
  let now = 1000;
  const clock = new HlcClock("R1", () => now);
  const a = clock.tick(); // 1000:0
  now = 1005;
  const b = clock.tick(); // 1005:0
  expect(a).toEqual({ physical: 1000, logical: 0, replicaId: "R1" });
  expect(b).toEqual({ physical: 1005, logical: 0, replicaId: "R1" });
  expect(compareHlc(a, b)).toBeLessThan(0);
});

test("compareHlc is a TOTAL order across replicas (replicaId tie-break)", () => {
  const a: Hlc = { physical: 10, logical: 0, replicaId: "A" };
  const b: Hlc = { physical: 10, logical: 0, replicaId: "B" };
  expect(compareHlc(a, b)).toBeLessThan(0);
  expect(compareHlc(b, a)).toBeGreaterThan(0);
  expect(compareHlc(a, a)).toBe(0);
  expect(hlcEqual(a, { ...a })).toBe(true);
});

test("receive merges a remote clock so causality survives", () => {
  const clock = new HlcClock("R1", () => 1000);
  const local = clock.tick(); // 1000:0
  const remote: Hlc = { physical: 2000, logical: 5, replicaId: "R2" };
  const merged = clock.receive(remote);
  expect(merged.physical).toBe(2000);
  expect(merged.logical).toBe(6); // follows the remote
  expect(compareHlc(merged, remote)).toBeGreaterThan(0);
  expect(compareHlc(merged, local)).toBeGreaterThan(0);
});

test("hlcToString / parseHlc round-trip", () => {
  const h: Hlc = { physical: 42, logical: 3, replicaId: "R1" };
  expect(hlcToString(h)).toBe("42:3:R1");
  expect(parseHlc("42:3:R1")).toEqual(h);
});
