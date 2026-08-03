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

// ── appendAll: one act, one atomic append (decision composite-act-atomicity) ──

test("appendAll commits every event of a valid act", () => {
  const reg = new KindRegistry().extend([
    { kind: "a_happened", family: "f", isLog: false },
    { kind: "b_happened", family: "f", isLog: false },
  ]).freeze();
  const log = new EventLog(reg);
  const act = [
    { id: "e1" as EntityId, hlc: { physical: 1, logical: 0, replicaId: "R" }, kind: "a_happened", payload: {} },
    { id: "e2" as EntityId, hlc: { physical: 1, logical: 1, replicaId: "R" }, kind: "b_happened", payload: {} },
  ];
  log.appendAll(act);
  expect(log.all()).toHaveLength(2);
});

test("a REJECTED act commits NOTHING — not even its valid prefix", () => {
  // The defect this replaces: farmOS commits the prefix. A loop over append()
  // would too, and would pass every other test here — this is the one that tells
  // appendAll apart from `events.forEach(e => log.append(e))`.
  const reg = new KindRegistry().extend([
    { kind: "a_happened", family: "f", isLog: false },
  ]).freeze();
  const log = new EventLog(reg);
  const act = [
    { id: "e1" as EntityId, hlc: { physical: 1, logical: 0, replicaId: "R" }, kind: "a_happened", payload: {} },
    { id: "e2" as EntityId, hlc: { physical: 1, logical: 1, replicaId: "R" }, kind: "a_happened", payload: {} },
    { id: "e3" as EntityId, hlc: { physical: 1, logical: 2, replicaId: "R" }, kind: "not_registered", payload: {} },
  ];
  expect(() => log.appendAll(act)).toThrow(/was REFUSED; nothing was committed/);
  expect(log.all()).toHaveLength(0); // the two VALID events are not on disk
});

test("a rejected act leaves an existing log untouched", () => {
  const reg = new KindRegistry().extend([
    { kind: "a_happened", family: "f", isLog: false },
  ]).freeze();
  const log = new EventLog(reg);
  log.append({ id: "prior" as EntityId, hlc: { physical: 0, logical: 0, replicaId: "R" }, kind: "a_happened", payload: {} });
  expect(() =>
    log.appendAll([
      { id: "e1" as EntityId, hlc: { physical: 1, logical: 0, replicaId: "R" }, kind: "a_happened", payload: {} },
      { id: "e2" as EntityId, hlc: { physical: 1, logical: 1, replicaId: "R" }, kind: "bogus", payload: {} },
    ]),
  ).toThrow();
  expect(log.all()).toHaveLength(1);
  expect(log.all()[0]!.id).toBe("prior");
});

test("an empty act is a no-op, not an error", () => {
  const reg = new KindRegistry().extend([{ kind: "a_happened", family: "f", isLog: false }]).freeze();
  const log = new EventLog(reg);
  expect(log.appendAll([])).toHaveLength(0);
  expect(log.all()).toHaveLength(0);
});
