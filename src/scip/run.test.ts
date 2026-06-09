/**
 * Regression guard for resolveScipBin — the single resolver shared by
 * runScip (execution) and the CLI's --scip auto-detect.
 *
 * The bug this locks out: detection used to check only ./node_modules/.bin
 * + PATH, missing metacoding's bundled @sourcegraph/scip-* copy. A global
 * `bun add -g @identikey/metacoding` install ships the indexers as deps, so
 * detection must find them even when the cwd has no local install and PATH
 * is bare — otherwise --scip wrongly reports "missing" for binaries runScip
 * would have run.
 */

import { expect, test } from "bun:test";
import { resolveScipBin } from "./run.ts";

test("resolveScipBin finds the bundled scip-typescript indexer", () => {
  const p = resolveScipBin("scip-typescript");
  expect(p).not.toBeNull();
  expect(p!.endsWith("scip-typescript")).toBe(true);
});

test("resolveScipBin finds the bundled scip-python indexer", () => {
  const p = resolveScipBin("scip-python");
  expect(p).not.toBeNull();
  expect(p!.endsWith("scip-python")).toBe(true);
});

test("resolveScipBin returns null for an unknown binary", () => {
  expect(resolveScipBin("definitely-not-a-real-indexer-xyz")).toBeNull();
});
