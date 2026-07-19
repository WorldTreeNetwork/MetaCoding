// Prevention tests (MetaCoding-9h5.24): demonstrate that the shared kernel makes
// the failure modes observed across the 9h5 isolated builds STRUCTURALLY
// impossible in the re-expressed composed store — not merely unobserved.
//
// Each test names the divergence it closes (two-feature-composition-2026-07-20.md §4/§5).

import { test, expect } from "bun:test";
import { join } from "node:path";
import { createComposedStore, SharedStore } from "../src/index.ts";
import { makeKernelRegistry, BOUND_CM_DECISIONS } from "../src/kernelConfig.ts";
import {
  EventLog,
  IdMinter,
  CmDecisionRegistry,
  loadCmDecisions,
  UnboundDecisionError,
  type KernelEvent,
  type EntityId,
} from "../../../../../../src/kernel/index.ts";

// ── 1. Ad-hoc event kinds are rejected (element 1 — closes CP2's latent conflict) ──
test("ad-hoc event kinds cannot enter the log", () => {
  const log = new EventLog(makeKernelRegistry());
  const rogue: KernelEvent = {
    id: "evt_R1~99" as EntityId,
    hlc: { physical: 1, logical: 0, replicaId: "R1" },
    kind: "activity_log", // a plausible farmOS kind a fan-out author might invent
    payload: {},
  };
  expect(() => log.append(rogue)).toThrow(/ad-hoc event kind "activity_log" rejected/);
  // the frozen taxonomy also refuses re-opening
  expect(() =>
    makeKernelRegistry().register({ kind: "activity_log", family: "log", isLog: true }),
  ).toThrow(/frozen/);
});

// ── 2. Ordinal IDs can't be minted (element 2a — closes the ID regression) ──
test("the store mints only replica-scoped ids; bare ordinals collide, kernel ids don't", () => {
  const a = createComposedStore({ replicaId: "A" }).logs.createAsset("animal", "x") as string;
  const b = createComposedStore({ replicaId: "B" }).logs.createAsset("animal", "x") as string;
  // Two replicas each mint their first asset. The composed build's `asset_1`
  // would COLLIDE; the kernel's replica-scoped ids do not.
  expect(a).not.toBe(b);
  expect(a).toContain("~"); // carries a replica scope, not a bare integer
  expect(a).not.toMatch(/^asset_\d+$/); // NOT the `asset_7` ordinal shape
  // There is no API that returns a bare ordinal usable for identity/ordering.
  const minter = new IdMinter("R1") as unknown as Record<string, unknown>;
  expect(typeof minter["nextOrdinal"]).toBe("undefined");
});

// ── 3. An unbound CM decision fails loudly (element 5 — closes the birth 3-way split) ──
test("constructing a store with an unresolved CM decision throws loudly", () => {
  const unresolved = new CmDecisionRegistry([
    { invariant: "birth-uniqueness", sensitivity: "hard", menuChoice: "?", status: "unresolved" },
  ]);
  expect(() => new SharedStore({ decisions: unresolved })).toThrow(UnboundDecisionError);
  // a hard decision that names no convergence key also fails
  const noKey = new CmDecisionRegistry([
    { invariant: "birth-uniqueness", sensitivity: "hard", menuChoice: "preserve-via-convergence-rule", status: "provisional" },
  ]);
  expect(() => new SharedStore({ decisions: noKey })).toThrow(/convergence key/);
  // the default (bound provisional) registry constructs fine
  expect(() => new SharedStore()).not.toThrow();
});

// ── 4. Membership can only be latest-wins via the comparator (element 3) ──
test("group membership is latest-wins, never additive (ce015be4 by construction)", () => {
  const { logs } = createComposedStore();
  // the logs adapter's createAsset is synchronous (returns a Handle, not a Promise).
  const a = logs.createAsset("animal", "a") as string;
  const g1 = logs.createAsset("group", "g1") as string;
  const g2 = logs.createAsset("group", "g2") as string;
  logs.assignToGroup(a, g1);
  logs.assignToGroup(a, g2);
  // additive membership (the 0p7/cell-a bug) would report BOTH true.
  expect(logs.groupMember(a, g2)).toBe(true);
  expect(logs.groupMember(a, g1)).toBe(false); // prior membership revoked
});

// ── registry provenance: jsonl artifact matches the embedded constant ──
test("cm-decisions.jsonl mirrors BOUND_CM_DECISIONS", () => {
  const fromFile = loadCmDecisions(join(import.meta.dir, "..", "cm-decisions.jsonl"));
  expect(fromFile).toEqual([...BOUND_CM_DECISIONS]);
});
