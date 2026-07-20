import { test, expect } from "bun:test";
import {
  gateFor,
  passesGate,
  admits,
  STATUS_CONTRACT,
  PENDING_PARTNER,
} from "./status.ts";

test("the official numerics are confirmed-only (v1.2 source divergence)", () => {
  expect(gateFor("yieldTotal")).toBe("require-confirmed");
  expect(passesGate("pending", gateFor("yieldTotal"))).toBe(false);
  expect(passesGate("done", gateFor("yieldTotal"))).toBe(true);
  expect(admits("logCount", "pending")).toBe(false);
  expect(admits("logCount", "done")).toBe(true);
});

test("the pending partners surface exactly what the official ones exclude", () => {
  expect(gateFor("pendingYieldTotal")).toBe("pending-only");
  expect(admits("pendingYieldTotal", "pending")).toBe(true);
  expect(admits("pendingYieldTotal", "done")).toBe(false);
  expect(admits("pendingLogCount", "pending")).toBe(true);
  expect(admits("pendingLogCount", "done")).toBe(false);
});

test("official + pending partition the candidates: no blending, no blind spot", () => {
  for (const [official, pending] of Object.entries(PENDING_PARTNER)) {
    for (const status of ["pending", "done"] as const) {
      const inOfficial = admits(official as never, status);
      const inPending = admits(pending as never, status);
      // exactly one side admits each status
      expect(inOfficial !== inPending).toBe(true);
    }
  }
});

test("every require-confirmed numeric declares a pending partner", () => {
  const partnered = new Set<string>(Object.keys(PENDING_PARTNER));
  const partners = new Set<string>(Object.values(PENDING_PARTNER));
  for (const [projection, gate] of Object.entries(STATUS_CONTRACT)) {
    if (gate !== "pending-only") continue;
    expect(partners.has(projection)).toBe(true);
  }
  for (const projection of partnered) {
    expect(gateFor(projection as never)).toBe("require-confirmed");
  }
});

test("pending movements are inert for current location (require-confirmed)", () => {
  expect(gateFor("currentLocation")).toBe("require-confirmed");
  expect(passesGate("pending", gateFor("currentLocation"))).toBe(false);
  expect(passesGate("done", gateFor("currentLocation"))).toBe(true);
  expect(admits("assetsAtLocation", "pending")).toBe(false);
});

test("log status is reported as-is, never gated away", () => {
  expect(gateFor("logStatus")).toBe("count-regardless");
  expect(admits("logStatus", "pending")).toBe(true);
});

test("the contract is a closed, declared table", () => {
  expect(Object.keys(STATUS_CONTRACT).sort()).toEqual([
    "adjustmentCount",
    "assetsAtLocation",
    "birthDate",
    "currentGeometry",
    "currentInventory",
    "currentLocation",
    "logCount",
    "logStatus",
    "parentage",
    "pendingInventory",
    "pendingLogCount",
    "pendingYieldTotal",
    "yieldTotal",
  ]);
});

// --------------------------------------------------------------------------- //
// v1.3 — the gate is PER-PROJECTION. Each of these was set by observation, and //
// the pair of them is why the v1.2 blanket rule was falsified: the same status //
// field means opposite things in the same system.                              //
// --------------------------------------------------------------------------- //
test("a pending adjustment does not move stock, but IS counted (observed)", () => {
  expect(gateFor("currentInventory")).toBe("require-confirmed");
  expect(admits("currentInventory", "pending")).toBe(false);
  // adjustment_count == 2 while stock counted only the done one
  expect(gateFor("adjustmentCount")).toBe("count-regardless");
  expect(admits("adjustmentCount", "pending")).toBe(true);
});

test("a pending BIRTH is fully effective — the opposite of inventory (observed)", () => {
  expect(gateFor("parentage")).toBe("count-regardless");
  expect(admits("parentage", "pending")).toBe(true);
  expect(gateFor("birthDate")).toBe("count-regardless");
  expect(admits("birthDate", "pending")).toBe(true);
});

test("no single blanket gate could satisfy the contract", () => {
  const gates = new Set(Object.values(STATUS_CONTRACT));
  expect(gates.size).toBeGreaterThan(1);
  // the specific pair that falsified v1.2
  expect(gateFor("currentInventory")).not.toBe(gateFor("parentage"));
});
