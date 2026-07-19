import { test, expect } from "bun:test";
import { KindRegistry, EventLog, type KernelEvent } from "./events.ts";
import type { EntityId } from "./ids.ts";
import type { Hlc } from "./hlc.ts";

const hlc: Hlc = { physical: 1, logical: 0, replicaId: "R1" };
const evt = (kind: string): KernelEvent => ({ id: "e_R1~1" as EntityId, hlc, kind, payload: {} });

function coreRegistry(): KindRegistry {
  return new KindRegistry()
    .register({ kind: "log_recorded", family: "log", isLog: true })
    .register({ kind: "movement_recorded", family: "movement", isLog: false })
    .freeze();
}

test("a registered kind appends; the isLog facet resolves is-a-movement-a-log", () => {
  const reg = coreRegistry();
  expect(reg.isLog("log_recorded")).toBe(true);
  expect(reg.isLog("movement_recorded")).toBe(false); // a movement is NOT a log
  const log = new EventLog(reg);
  expect(() => log.append(evt("log_recorded"))).not.toThrow();
  expect(log.all().length).toBe(1);
});

test("registering after freeze throws", () => {
  const reg = coreRegistry();
  expect(() => reg.register({ kind: "sneaky", family: "x", isLog: false })).toThrow(/frozen/);
});

test("duplicate registration throws", () => {
  expect(() =>
    new KindRegistry()
      .register({ kind: "dup", family: "x", isLog: false })
      .register({ kind: "dup", family: "x", isLog: false }),
  ).toThrow(/duplicate/);
});

test("spec() on an unknown kind names the closed taxonomy", () => {
  const reg = coreRegistry();
  expect(() => reg.spec("nope")).toThrow(/closed taxonomy/);
});
