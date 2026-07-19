import { test, expect } from "bun:test";
import { pickLatest, LwwRegister } from "./lww.ts";
import type { Hlc } from "./hlc.ts";

const h = (physical: number, logical = 0, replicaId = "R1"): Hlc => ({ physical, logical, replicaId });

test("pickLatest returns the HLC-greatest candidate", () => {
  const items = [
    { v: "a", hlc: h(10) },
    { v: "b", hlc: h(30) },
    { v: "c", hlc: h(20) },
  ];
  expect(pickLatest(items, (i) => i.hlc)?.v).toBe("b");
});

test("pickLatest is order-independent (convergence)", () => {
  const items = [
    { v: "a", hlc: h(10, 0, "A") },
    { v: "b", hlc: h(10, 0, "B") },
  ];
  expect(pickLatest(items, (i) => i.hlc)?.v).toBe("b"); // replicaId tie-break
  expect(pickLatest([...items].reverse(), (i) => i.hlc)?.v).toBe("b");
});

test("pickLatest on empty is undefined", () => {
  expect(pickLatest([], (x: { hlc: Hlc }) => x.hlc)).toBeUndefined();
});

test("LwwRegister only accepts strictly-later writes", () => {
  const reg = new LwwRegister<string>();
  expect(reg.set("first", h(10))).toBe(true);
  expect(reg.value).toBe("first");
  expect(reg.set("stale", h(5))).toBe(false); // older HLC loses
  expect(reg.value).toBe("first");
  expect(reg.set("newer", h(20))).toBe(true);
  expect(reg.value).toBe("newer");
});
