// THE INGEST SEAM, enforced structurally.
//
// docs/design/index-fitness.md is explicit about why this file exists:
//
//   "`indexDirectory` and `loadScip` stop being exported ingest entry points and
//    become internal to the session. That is what makes `watch`'s current bypass
//    STRUCTURALLY IMPOSSIBLE rather than fixed-once."
//
// and, from the fake-it analysis:
//
//   "Writing around the session — any direct Store.upsertSymbol leaves a stale
//    HEALTHY. Why the session must be the ONLY exported ingest entry: otherwise
//    the fix is a guard, and a guard is a patch the next reader walks around."
//
// `metacoding watch` bypassed the gate entirely, and the reason was not that
// cmdWatch forgot — it was that the barrel handed out the primitive. Adding a
// call in cmdWatch would fix one caller and leave the property depending on
// every future caller's memory. So this test fails the suite the moment a new
// module in src/ reaches past the session.
//
// AND THE CHECKER IS ITSELF MUTATION-TESTED HERE. A structural test that scans
// files has the exact failure mode iteration-methodology.md warns about: an
// instrument capable of reporting nothing but success. So `findViolations` is
// run against synthetic content KNOWN to be a violation, and must report it.

import { test, expect, describe } from "bun:test";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

const SRC = join(import.meta.dir, "..");

/**
 * Modules permitted to touch the raw ingest primitives:
 *   - the session itself (the seam);
 *   - the modules that DEFINE them;
 *   - the watcher, which is only reachable through runWatchSession and whose
 *     initial pass is skipped when the session has already run (and judged) it.
 */
const ALLOWED = new Set([
  "ingest/session.ts",
  "extractor/walker.ts",
  "extractor/watcher.ts",
  "scip/loader.ts",
  "scip/index.ts", // type-only re-export of LoadScipOpts/LoadScipStats
]);

/** Ingest entry points that write to a Store outside any fitness judgement. */
const GUARDED = ["indexDirectory", "loadScip", "ingestPrebuiltScip"];

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    const p = join(dir, name);
    if (statSync(p).isDirectory()) { walk(p, out); continue; }
    if (p.endsWith(".ts")) out.push(p);
  }
  return out;
}

interface Violation { file: string; symbol: string; line: string }

/** Find `import { …guarded… } from …` in a file's source text. */
function findViolationsIn(rel: string, text: string): Violation[] {
  if (ALLOWED.has(rel)) return [];
  if (rel.endsWith(".test.ts")) return []; // tests may exercise the primitives
  const out: Violation[] = [];
  for (const raw of text.split("\n")) {
    const line = raw.trim();
    if (!line.startsWith("import ")) continue;
    if (line.startsWith("import type")) continue;
    for (const sym of GUARDED) {
      // Match the identifier inside the import clause only.
      if (new RegExp(`[{,\\s]${sym}\\s*[,}]`).test(line)) {
        out.push({ file: rel, symbol: sym, line });
      }
    }
  }
  return out;
}

function scanTree(): Violation[] {
  const out: Violation[] = [];
  for (const abs of walk(SRC)) {
    const rel = relative(SRC, abs);
    out.push(...findViolationsIn(rel, readFileSync(abs, "utf-8")));
  }
  return out;
}

describe("the ingest seam", () => {
  test("no module in src/ reaches past src/ingest/session.ts to ingest", () => {
    const violations = scanTree();
    expect(
      violations.map((v) => `${v.file} imports ${v.symbol}: ${v.line}`),
    ).toEqual([]);
  });

  test("THE CHECKER FIRES — the same scan flags a synthetic bypass", () => {
    // The mirror half. Without this, a scanner with a broken regex reports an
    // empty violation list forever and reads exactly like "the seam holds".
    const bypass = findViolationsIn(
      "cli/some-future-command.ts",
      `import { Store } from "../store";\nimport { indexDirectory } from "../extractor/walker.ts";\n`,
    );
    expect(bypass).toHaveLength(1);
    expect(bypass[0]!.symbol).toBe("indexDirectory");

    const loaderBypass = findViolationsIn(
      "mcp/some-tool.ts",
      `import { loadScip, type LoadScipStats } from "../scip/loader.ts";\n`,
    );
    expect(loaderBypass).toHaveLength(1);

    // ...and the allowlist and the test-file exemption are real, not accidents.
    expect(findViolationsIn("ingest/session.ts", `import { loadScip } from "../scip/loader.ts";`)).toEqual([]);
    expect(findViolationsIn("cli/x.test.ts", `import { loadScip } from "../scip/loader.ts";`)).toEqual([]);
  });

  test("the public barrels do not re-export the ingest primitives", () => {
    const extractor = readFileSync(join(SRC, "extractor/index.ts"), "utf-8");
    const scipIndex = readFileSync(join(SRC, "scip/index.ts"), "utf-8");
    expect(/export\s*{[^}]*\bindexDirectory\b/.test(extractor)).toBe(false);
    expect(/export\s*{[^}]*\bwatch\b/.test(extractor)).toBe(false);
    expect(/export\s*{[^}]*\bloadScip\b/.test(scipIndex)).toBe(false);
    // CONTRAST: the same check on what they DO still export must be true, or
    // the regex is simply broken and would pass over anything.
    expect(/export\s*{[^}]*\bindexFile\b/.test(extractor)).toBe(true);
    expect(/export\s*{[^}]*\brunScip\b/.test(scipIndex)).toBe(true);
  });
});
