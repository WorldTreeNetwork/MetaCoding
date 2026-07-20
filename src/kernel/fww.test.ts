import { test, expect } from "bun:test";
import { pickEarliest, GuardedFirstWrite, demoteToObservation } from "./fww.ts";
import type { Hlc } from "./hlc.ts";

const h = (physical: number, logical = 0, replicaId = "R1"): Hlc => ({ physical, logical, replicaId });

test("pickEarliest returns the HLC-least candidate", () => {
  const items = [
    { v: "a", hlc: h(30) },
    { v: "b", hlc: h(10) },
    { v: "c", hlc: h(20) },
  ];
  expect(pickEarliest(items, (i) => i.hlc)?.v).toBe("b");
});

test("pickEarliest is order-independent (convergence)", () => {
  const items = [
    { v: "a", hlc: h(10, 0, "A") },
    { v: "b", hlc: h(10, 0, "B") },
  ];
  expect(pickEarliest(items, (i) => i.hlc)?.v).toBe("a"); // replicaId tie-break
  expect(pickEarliest([...items].reverse(), (i) => i.hlc)?.v).toBe("a");
});

test("pickEarliest on empty is undefined", () => {
  expect(pickEarliest([], (x: { hlc: Hlc }) => x.hlc)).toBeUndefined();
});

test("GuardedFirstWrite: first write wins, existing value vetoes", () => {
  const reg = new GuardedFirstWrite<string>();
  expect(reg.isSet).toBe(false);
  expect(reg.set("mother-A", h(10))).toBe(true);
  expect(reg.value).toBe("mother-A");
  expect(reg.isSet).toBe(true);
  // A later write is a complete veto — even a well-formed one loses.
  expect(reg.set("mother-B", h(20))).toBe(false);
  expect(reg.value).toBe("mother-A");
});

test("GuardedFirstWrite: an EARLIER HLC displaces a provisional incumbent (merge)", () => {
  // A late-arriving but earlier-stamped write wins — earliest-HLC, not earliest-arrival.
  const reg = new GuardedFirstWrite<string>();
  expect(reg.set("mother-B", h(20))).toBe(true);
  expect(reg.set("mother-A", h(10))).toBe(true); // earlier HLC ⇒ wins
  expect(reg.value).toBe("mother-A");
  expect(reg.set("mother-A", h(10))).toBe(false); // replay of the winner ⇒ no-op
});

test("GuardedFirstWrite: replay-determinism across arrival orders", () => {
  const forward = new GuardedFirstWrite<string>();
  forward.set("x", h(10));
  forward.set("y", h(20));
  forward.set("z", h(15));

  const shuffled = new GuardedFirstWrite<string>();
  shuffled.set("y", h(20));
  shuffled.set("z", h(15));
  shuffled.set("x", h(10));

  expect(forward.value).toBe("x");
  expect(shuffled.value).toBe(forward.value);
});

test("demoteToObservation keeps the earliest, re-emits every loser", () => {
  interface Birth { id: string; hlc: Hlc; kind: "birth" | "observation" }
  const births: Birth[] = [
    { id: "b1", hlc: h(30), kind: "birth" },
    { id: "b2", hlc: h(10), kind: "birth" }, // earliest ⇒ kept
    { id: "b3", hlc: h(20), kind: "birth" },
  ];
  const result = demoteToObservation(
    births,
    (b) => b.hlc,
    (loser) => ({ ...loser, kind: "observation" as const }),
  )!;
  expect(result.kept.id).toBe("b2");
  expect(result.demoted.map((d) => d.id).sort()).toEqual(["b1", "b3"]);
  // Losers are re-emitted, never dropped.
  expect(result.demoted.every((d) => d.kind === "observation")).toBe(true);
});

test("demoteToObservation: single candidate keeps it, demotes nothing", () => {
  const result = demoteToObservation(
    [{ id: "only", hlc: h(5) }],
    (b) => b.hlc,
    (l) => l,
  )!;
  expect(result.kept.id).toBe("only");
  expect(result.demoted).toEqual([]);
});

test("demoteToObservation on empty is undefined", () => {
  expect(
    demoteToObservation([] as { hlc: Hlc }[], (b) => b.hlc, (l) => l),
  ).toBeUndefined();
});

test("demoteToObservation is deterministic under replay (input order irrelevant)", () => {
  interface Birth { id: string; hlc: Hlc }
  const a: Birth[] = [
    { id: "b1", hlc: h(30) },
    { id: "b2", hlc: h(10) },
    { id: "b3", hlc: h(20) },
  ];
  const keep = (bs: Birth[]) =>
    demoteToObservation(bs, (b) => b.hlc, (l) => l)!.kept.id;
  expect(keep(a)).toBe("b2");
  expect(keep([...a].reverse())).toBe("b2");
});
