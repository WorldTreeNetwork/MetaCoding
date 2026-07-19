import { test, expect } from "bun:test";
import {
  CmDecisionRegistry,
  UnboundDecisionError,
  validateCmDecision,
  cmDecisionFromPortDecision,
  type CmDecision,
} from "./decisions.ts";

const birth: CmDecision = {
  invariant: "birth-uniqueness",
  sensitivity: "hard",
  menuChoice: "preserve-via-convergence-rule",
  convergenceKey: "earliest-hlc-wins; loser demoted",
  status: "provisional",
};

test("requireBound accepts a provisional decision that names a convergence key", () => {
  const reg = new CmDecisionRegistry([birth]);
  expect(reg.requireBound("birth-uniqueness").menuChoice).toBe("preserve-via-convergence-rule");
});

test("requireBound throws when a decision is missing", () => {
  const reg = new CmDecisionRegistry([]);
  expect(() => reg.requireBound("birth-uniqueness")).toThrow(UnboundDecisionError);
});

test("requireBound throws when a decision is explicitly unresolved", () => {
  const reg = new CmDecisionRegistry([{ ...birth, status: "unresolved" }]);
  expect(() => reg.requireBound("birth-uniqueness")).toThrow(/UNRESOLVED/);
});

test("requireBound throws when a HARD invariant names no convergence key", () => {
  const reg = new CmDecisionRegistry([{ ...birth, convergenceKey: undefined }]);
  expect(() => reg.requireBound("birth-uniqueness")).toThrow(/convergence key/);
});

test("requireAllBound reports the FIRST unresolved dependency", () => {
  const reg = new CmDecisionRegistry([birth]);
  expect(() => reg.requireAllBound(["birth-uniqueness", "id-scheme"])).toThrow(/id-scheme/);
});

test("validateCmDecision rejects a bad status", () => {
  expect(() => validateCmDecision({ ...birth, status: "maybe" })).toThrow(/status/);
});

test("cmDecisionFromPortDecision adapts the PD format and surfaces the missing key", () => {
  const cm = cmDecisionFromPortDecision(
    { targetElement: "birth-uniqueness", decision: "weaken", rationale: "r" },
    { sensitivity: "hard" },
  );
  expect(cm.menuChoice).toBe("weaken-to-eventual");
  // hard + no convergenceKey ⇒ requireBound must reject it
  expect(() => new CmDecisionRegistry([cm]).requireBound("birth-uniqueness")).toThrow(
    /convergence key/,
  );
});

test("pending() lists everything not yet bound", () => {
  const reg = new CmDecisionRegistry([birth, { ...birth, invariant: "x", status: "bound" }]);
  expect(reg.pending().map((d) => d.invariant)).toEqual(["birth-uniqueness"]);
});
