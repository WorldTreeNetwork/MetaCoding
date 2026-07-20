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
    "assetsAtLocation",
    "currentGeometry",
    "currentLocation",
    "logCount",
    "logStatus",
    "pendingLogCount",
    "pendingYieldTotal",
    "yieldTotal",
  ]);
});
