import { test, expect } from "bun:test";
import { FoldReduce, type FoldReduceSpec } from "./fold.ts";
import type { Hlc } from "./hlc.ts";

const h = (physical: number, logical = 0, replicaId = "R1"): Hlc => ({ physical, logical, replicaId });

/** A minimal inventory-shaped event for exercising the reset/accumulate reduce. */
interface Ev {
  kind: "reset" | "increment" | "decrement";
  value: number;
  effectiveTime: number;
  hlc: Hlc;
  status?: "done" | "pending";
}

const ev = (
  kind: Ev["kind"],
  value: number,
  effectiveTime: number,
  hlc: Hlc,
  status: Ev["status"] = "done",
): Ev => ({ kind, value, effectiveTime, hlc, status });

/** The running-balance-with-reset spec — inventory's fold, expressed once. */
const balanceSpec: FoldReduceSpec<Ev, number> = {
  effectiveTimeOf: (e) => e.effectiveTime,
  hlcOf: (e) => e.hlc,
  isReset: (e) => e.kind === "reset",
  reset: (e) => e.value,
  accumulate: (acc, e) => (e.kind === "increment" ? acc + e.value : acc - e.value),
  initial: 0,
  admits: (e) => e.status === "done",
};

const balance = new FoldReduce(balanceSpec);

test("no reset: increments and decrements fold additively from initial", () => {
  const events = [
    ev("increment", 10, 100, h(100)),
    ev("decrement", 3, 200, h(200)),
    ev("increment", 1, 300, h(300)),
  ];
  expect(balance.fold(events)).toBe(8);
});

test("reset ASSIGNS: pre-reset +10 excluded, reset assigns 4, later -1 → 3", () => {
  const events = [
    ev("increment", 10, 100, h(100)),
    ev("reset", 4, 200, h(200)),
    ev("decrement", 1, 300, h(300)),
  ];
  expect(balance.fold(events)).toBe(3);
});

test("reset boundary is INCLUSIVE — a same-time delta before the reset is overwritten", () => {
  // +3, reset 4, -1 all at effectiveTime 200; HLC preserves append order.
  const events = [
    ev("increment", 3, 200, h(200, 0)),
    ev("reset", 4, 200, h(200, 1)),
    ev("decrement", 1, 200, h(200, 2)),
  ];
  // +3 applied, overwritten by reset 4, then -1 → 3.
  expect(balance.fold(events)).toBe(3);
});

test("same-effectiveTime ties break on the HLC, not insertion order", () => {
  // reset THEN increment at the same time → 4 + 5 = 9.
  expect(
    balance.fold([ev("reset", 4, 200, h(200, 0)), ev("increment", 5, 200, h(200, 1))]),
  ).toBe(9);
  // increment THEN reset at the same time → +5 overwritten by reset → 4.
  expect(
    balance.fold([ev("increment", 5, 200, h(200, 0)), ev("reset", 4, 200, h(200, 1))]),
  ).toBe(4);
});

test("asOf excludes future-dated events (including a later reset)", () => {
  const events = [
    ev("increment", 10, 100, h(100)),
    ev("reset", 4, 500, h(500)), // after the cutoff
  ];
  expect(balance.fold(events, 200)).toBe(10);
});

test("admits gate drops pending events", () => {
  const events = [
    ev("increment", 2, 100, h(100)),
    ev("increment", 3, 100, h(101), "pending"), // gated out
  ];
  expect(balance.fold(events)).toBe(2);
});

test("empty / all-gated folds to initial", () => {
  expect(balance.fold([])).toBe(0);
  expect(balance.fold([ev("increment", 9, 100, h(100), "pending")])).toBe(0);
});

test("replay-determinism: any input order folds to the same value", () => {
  const events = [
    ev("increment", 10, 100, h(100)),
    ev("reset", 4, 200, h(200)),
    ev("increment", 5, 200, h(200, 1)),
    ev("decrement", 1, 300, h(300)),
  ];
  const forward = balance.fold(events);
  const reversed = balance.fold([...events].reverse());
  const shuffled = balance.fold([events[2]!, events[0]!, events[3]!, events[1]!]);
  expect(forward).toBe(8); // reset 4, +5, -1
  expect(reversed).toBe(forward);
  expect(shuffled).toBe(forward);
});

test("cross-replica merge: events from two replicas fold order-independently", () => {
  // Same physical time on two replicas; replicaId is the final HLC tie-break.
  const r1 = [ev("reset", 10, 200, h(200, 0, "A")), ev("increment", 2, 200, h(200, 0, "B"))];
  const r2 = [ev("increment", 2, 200, h(200, 0, "B")), ev("reset", 10, 200, h(200, 0, "A"))];
  // A precedes B (replicaId "A" < "B"), so reset 10 then +2 = 12, both orders.
  expect(balance.fold(r1)).toBe(12);
  expect(balance.fold(r2)).toBe(12);
});

test("generic over accumulator type: a string-collecting reduce", () => {
  interface Word { text: string; effectiveTime: number; hlc: Hlc; reset: boolean }
  const spec: FoldReduceSpec<Word, string[]> = {
    effectiveTimeOf: (w) => w.effectiveTime,
    hlcOf: (w) => w.hlc,
    isReset: (w) => w.reset,
    reset: () => [],
    accumulate: (acc, w) => [...acc, w.text],
    initial: [],
  };
  const fold = new FoldReduce(spec);
  const words: Word[] = [
    { text: "a", effectiveTime: 1, hlc: h(1), reset: false },
    { text: "b", effectiveTime: 2, hlc: h(2), reset: true }, // clears
    { text: "c", effectiveTime: 3, hlc: h(3), reset: false },
  ];
  expect(fold.fold(words)).toEqual(["c"]);
});
