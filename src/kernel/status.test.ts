import { test, expect } from "bun:test";
import { gateFor, passesGate, admits, STATUS_CONTRACT } from "./status.ts";

test("pending logs count toward yield (count-regardless)", () => {
  expect(gateFor("yieldTotal")).toBe("count-regardless");
  expect(passesGate("pending", gateFor("yieldTotal"))).toBe(true);
  expect(passesGate("done", gateFor("yieldTotal"))).toBe(true);
  expect(admits("logCount", "pending")).toBe(true);
});

test("pending movements are inert for current location (require-confirmed)", () => {
  expect(gateFor("currentLocation")).toBe("require-confirmed");
  expect(passesGate("pending", gateFor("currentLocation"))).toBe(false);
  expect(passesGate("done", gateFor("currentLocation"))).toBe(true);
  expect(admits("assetsAtLocation", "pending")).toBe(false);
});

test("the contract is a closed, declared table", () => {
  expect(Object.keys(STATUS_CONTRACT).sort()).toEqual([
    "assetsAtLocation",
    "currentGeometry",
    "currentLocation",
    "logCount",
    "logStatus",
    "yieldTotal",
  ]);
});
