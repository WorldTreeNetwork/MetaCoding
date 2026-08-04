// Regression evidence for MetaCoding-0sd — `metacoding index --scip` exiting 0
// over a completely empty graph (ory/fosite: a Go repo shipping package.json,
// so scip-typescript was selected, died with "no files got indexed", and the
// failure was caught, logged, and reported as success).
//
// WHAT THESE TESTS ASSERT, AND WHY IT IS NOT AN EXIT CODE
// -------------------------------------------------------
// The defect was a green exit over an empty store. A test that asserts `exit 0`
// is therefore precisely the check that already failed here — it would have
// passed on the broken build. So the load-bearing assertions below are
// NON-ZERO EDGE COUNTS BY TYPE, read out of a REAL Store after a real ingest
// (`CALLS`, `REFERENCES`, `IMPLEMENTS`), and the gate's verdict is checked
// against those counts. The one exit-status assertion in this file is a
// *wiring* check on the CLI, and it is only meaningful because the tests above
// it already pinned the graph contents.
//
// It also mutation-checks the gate itself (docs/design/iteration-methodology.md:
// "mutation-test the checker, not only the code"): the same store, same code
// path, once with edges and once without, must produce opposite verdicts. A
// gate that fires on everything is as useless as one that fires on nothing, so
// the good case is asserted to PASS with the real measured numbers from the
// 2026-08-04 spike (node-oidc-provider: 12,617 symbols / CALLS 2,557 /
// REFERENCES 3,875), not just to "not crash".

import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";

import { Store } from "../store";
import { loadScip } from "../scip";
import {
  censusSourceFiles,
  evaluateIndexOutcome,
  storeCensus,
  type LaneOutcome,
  type SourceCensus,
  type StoreCensus,
} from "./index-gate.ts";

const DEF = scip.SymbolRole.Definition;
const REPO = "gate-fixture";
const BRANCH = "main";

let dataDir: string;
let repoDir: string;
let store: Store;

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "gate-0sd-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "gate-0sd-repo-"));
  store = await Store.open(dataDir);
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

/** A .scip index with real definitions plus a call/reference between them —
 *  the shape a working lane produces. */
function productiveScip(): Uint8Array {
  const PKG = "scip-typescript npm fixture 1.0.0";
  const caller = `${PKG} \`src/a.ts\`/run().`;
  const callee = `${PKG} \`src/b.ts\`/helper().`;
  const base = `${PKG} \`src/b.ts\`/Base#`;
  const derived = `${PKG} \`src/a.ts\`/Derived#`;
  const docs = [
    new scip.Document({
      relative_path: "src/a.ts",
      language: "typescript",
      occurrences: [
        new scip.Occurrence({ symbol: caller, range: [1, 9, 1, 12], symbol_roles: DEF }),
        // Non-definition occurrence of b.ts's helper inside run()'s body -> CALLS + REFERENCES.
        new scip.Occurrence({ symbol: callee, range: [2, 4, 2, 10], symbol_roles: 0 }),
        new scip.Occurrence({ symbol: derived, range: [6, 6, 6, 13], symbol_roles: DEF }),
      ],
      symbols: [
        new scip.SymbolInformation({
          symbol: derived,
          relationships: [
            new scip.Relationship({ symbol: base, is_implementation: true }),
          ],
        }),
      ],
    }),
    new scip.Document({
      relative_path: "src/b.ts",
      language: "typescript",
      occurrences: [
        new scip.Occurrence({ symbol: callee, range: [1, 9, 1, 15], symbol_roles: DEF }),
        new scip.Occurrence({ symbol: base, range: [4, 6, 4, 10], symbol_roles: DEF }),
      ],
      symbols: [],
    }),
  ];
  return new scip.Index({ documents: docs }).serialize();
}

/** The fosite shape: an indexer that ran, exited, and produced nothing. */
function emptyScip(): Uint8Array {
  return new scip.Index({ documents: [] }).serialize();
}

function writeScip(bytes: Uint8Array, name: string): string {
  const p = join(repoDir, name);
  writeFileSync(p, bytes);
  return p;
}

/** Populate the fixture repo with `n` files of a given extension. */
function seedSourceFiles(ext: string, n: number, body = "// x\n"): void {
  mkdirSync(join(repoDir, "src"), { recursive: true });
  for (let i = 0; i < n; i++) {
    writeFileSync(join(repoDir, "src", `f${i}${ext}`), body, "utf-8");
  }
}

describe("storeCensus — edge counts BY TYPE out of a real store", () => {
  test("a productive SCIP ingest yields non-zero CALLS / REFERENCES / IMPLEMENTS, and the gate passes", async () => {
    const stats = await loadScip(store, writeScip(productiveScip(), "good.scip"), {
      branch: BRANCH, repo: REPO, language: "ts",
    });
    expect(stats.documents).toBe(2);

    const census = await storeCensus(store, REPO, BRANCH);

    // THE load-bearing assertions: counts by type, not an exit status.
    expect(census.symbols).toBeGreaterThan(0);
    expect(census.edgesByKind["CALLS"]).toBeGreaterThan(0);
    expect(census.edgesByKind["REFERENCES"]).toBeGreaterThan(0);
    expect(census.edgesByKind["IMPLEMENTS"]).toBeGreaterThan(0);
    expect(census.relationalEdges).toBeGreaterThan(0);

    seedSourceFiles(".ts", 2);
    const gate = evaluateIndexOutcome({
      repo: REPO,
      targetPath: repoDir,
      lanes: [
        { lane: "tree-sitter", ok: true, files: 2 },
        { lane: "scip:typescript", ok: true, files: stats.documents },
      ],
      source: censusSourceFiles(repoDir),
      store: census,
      scipRequested: true,
    });
    expect(gate.failures).toEqual([]);
    expect(gate.ok).toBe(true);
  });

  test("the fosite shape — indexer ran, produced nothing — leaves 0 edges of EVERY type and the gate REFUSES it", async () => {
    // 40 Go files no lane can see, exactly like ory/fosite's 262.
    seedSourceFiles(".go", 40, "package main\n");
    const stats = await loadScip(store, writeScip(emptyScip(), "empty.scip"), {
      branch: BRANCH, repo: REPO, language: "ts",
    });
    expect(stats.documents).toBe(0);

    const census = await storeCensus(store, REPO, BRANCH);
    // Same measurement as the passing case, opposite answer — this is the
    // contrast that makes the assertion discriminating rather than confirming.
    expect(census.symbols).toBe(0);
    expect(census.edgesByKind["CALLS"]).toBe(0);
    expect(census.edgesByKind["REFERENCES"]).toBe(0);
    expect(census.edgesByKind["IMPLEMENTS"]).toBe(0);
    expect(census.relationalEdges).toBe(0);

    const gate = evaluateIndexOutcome({
      repo: REPO,
      targetPath: repoDir,
      lanes: [
        { lane: "tree-sitter", ok: true, files: 0 },
        { lane: "scip:typescript", ok: true, files: 0 },
      ],
      source: censusSourceFiles(repoDir),
      store: census,
      scipRequested: true,
    });
    expect(gate.ok).toBe(false);
    const codes = gate.failures.map((f) => f.code);
    expect(codes).toContain("NO_FILES_SCANNED");
    expect(codes).toContain("NO_RELATIONAL_EDGES");
    // The message must name the language nobody indexed, or the operator is
    // left guessing why an apparently fine repo produced nothing.
    expect(gate.failures.map((f) => f.message).join("\n")).toContain(".go");
  });

  test("a lane that DIES fails the run even though a sibling lane filled the store", async () => {
    const stats = await loadScip(store, writeScip(productiveScip(), "good2.scip"), {
      branch: BRANCH, repo: REPO, language: "ts",
    });
    const census = await storeCensus(store, REPO, BRANCH);
    expect(census.edgesByKind["CALLS"]).toBeGreaterThan(0);   // the store IS populated

    seedSourceFiles(".ts", 2);
    const gate = evaluateIndexOutcome({
      repo: REPO,
      targetPath: repoDir,
      lanes: [
        { lane: "tree-sitter", ok: true, files: 2 },
        { lane: "scip:typescript", ok: true, files: stats.documents },
        { lane: "scip:python", ok: false, error: "scip-python exited 1", files: 0 },
      ],
      source: censusSourceFiles(repoDir),
      store: census,
      scipRequested: true,
    });
    expect(gate.ok).toBe(false);
    expect(gate.failures.map((f) => f.code)).toContain("LANE_FAILED");
    expect(gate.failures.map((f) => f.message).join()).toContain("scip-python exited 1");
  });
});

describe("evaluateIndexOutcome — the fake-it cases", () => {
  const populated = (over: Partial<StoreCensus> = {}): StoreCensus => ({
    symbols: 12_617,
    edgesByKind: { CALLS: 2557, REFERENCES: 3875, IMPLEMENTS: 24, CONSTRUCTS: 237 },
    relationalEdges: 6693,
    ...over,
  });
  const census = (byExt: Record<string, number>): SourceCensus => ({
    total: Object.values(byExt).reduce((a, b) => a + b, 0),
    byExt,
  });
  const lanes = (...ls: LaneOutcome[]): LaneOutcome[] => ls;

  test("the REAL node-oidc-provider numbers pass — the gate must not cry wolf", () => {
    // Measured 2026-08-04 (docs/notes/2026-08-04-go-js-lane-spike.md):
    // 413 documents over 413 .js files, 12,617 symbols, CALLS 2,557, REFERENCES 3,875.
    const r = evaluateIndexOutcome({
      repo: "node-oidc-provider",
      targetPath: "/fixture",
      lanes: lanes(
        { lane: "tree-sitter", ok: true, files: 0 },      // no .js grammar — dark, but not fatal on its own
        { lane: "scip:typescript", ok: true, files: 413 },
      ),
      source: census({ ".js": 413 }),
      store: populated(),
      scipRequested: true,
    });
    expect(r.ok).toBe(true);
    expect(r.coverage).toBe(1);
  });

  test("ONE trivial file out of 273 would satisfy a `> 0` threshold — it does not satisfy this gate", () => {
    const r = evaluateIndexOutcome({
      repo: "fosite",
      targetPath: "/fixture",
      lanes: lanes(
        { lane: "tree-sitter", ok: true, files: 0 },
        { lane: "scip:typescript", ok: true, files: 1 },
      ),
      // 1 lonely .js among 272 .go files: symbols and edges are non-zero, so
      // every "> 0" check in the world says yes.
      source: census({ ".go": 272, ".js": 1 }),
      store: populated({ symbols: 3, edgesByKind: { CALLS: 1, REFERENCES: 2 }, relationalEdges: 3 }),
      scipRequested: true,
    });
    expect(r.ok).toBe(false);
    expect(r.failures.map((f) => f.code)).toEqual(["LOW_COVERAGE"]);
    expect(r.coverage).toBeCloseTo(1 / 273, 5);
  });

  test("'0 files scanned' and 'files scanned but 0 symbols' are DISTINGUISHABLE", () => {
    const nothingScanned = evaluateIndexOutcome({
      repo: "r", targetPath: "/f",
      lanes: lanes({ lane: "tree-sitter", ok: true, files: 0 }),
      source: census({ ".go": 100 }),
      store: { symbols: 0, edgesByKind: {}, relationalEdges: 0 },
      scipRequested: false,
    });
    expect(nothingScanned.failures.map((f) => f.code)).toEqual(["NO_FILES_SCANNED"]);

    const scannedButBarren = evaluateIndexOutcome({
      repo: "r", targetPath: "/f",
      lanes: lanes({ lane: "tree-sitter", ok: true, files: 100 }),
      source: census({ ".ts": 100 }),
      store: { symbols: 0, edgesByKind: {}, relationalEdges: 0 },
      scipRequested: false,
    });
    expect(scannedButBarren.failures.map((f) => f.code)).toEqual(["NO_SYMBOLS"]);
  });

  test("symbols without relational edges is refused when SCIP was requested (the hy6.16 rescore graph)", () => {
    // MetaCoding-hy6.16: 4,800 nodes, CALLS = 0, REFERENCES = 0 — a full 41-row
    // re-scoring pass ran on it and the empty result was mistaken for a real one.
    const r = evaluateIndexOutcome({
      repo: "farmos", targetPath: "/f",
      lanes: lanes(
        { lane: "tree-sitter", ok: true, files: 900 },
        { lane: "scip:load-scip", ok: true, files: 900 },
      ),
      source: census({ ".php": 900 }),
      store: { symbols: 4800, edgesByKind: { CONTAINS: 4800 }, relationalEdges: 0 },
      scipRequested: true,
    });
    expect(r.ok).toBe(false);
    expect(r.failures.map((f) => f.code)).toContain("NO_RELATIONAL_EDGES");
  });

  test("CONTAINS alone does not count as a graph — but the same run passes once CALLS appear", () => {
    const base = {
      repo: "r", targetPath: "/f",
      lanes: lanes(
        { lane: "tree-sitter", ok: true, files: 100 },
        { lane: "scip:typescript", ok: true, files: 100 },
      ),
      source: census({ ".ts": 100 }),
      scipRequested: true,
    };
    expect(
      evaluateIndexOutcome({
        ...base,
        store: { symbols: 500, edgesByKind: { CONTAINS: 500 }, relationalEdges: 0 },
      }).ok,
    ).toBe(false);
    expect(
      evaluateIndexOutcome({
        ...base,
        store: { symbols: 500, edgesByKind: { CONTAINS: 500, CALLS: 7 }, relationalEdges: 7 },
      }).ok,
    ).toBe(true);
  });

  test("a run that produced NOTHING cannot coast on a previous run's symbols", () => {
    // The mirror of "trust the store, not the accumulators": the store census
    // sees the whole repo, including what an earlier good run left. Here the
    // SCIP lane exits clean with 0 documents while the tree-sitter lane walks
    // the tree, so symbols and edges are plentiful — and the run still produced
    // no SCIP output, which is what was asked for.
    const r = evaluateIndexOutcome({
      repo: "stale", targetPath: "/f",
      lanes: lanes(
        { lane: "tree-sitter", ok: true, files: 400 },
        { lane: "scip:typescript", ok: true, files: 0 },
      ),
      source: census({ ".ts": 400 }),
      store: populated(),                       // full graph from an earlier run
      scipRequested: true,
    });
    expect(r.ok).toBe(false);
    expect(r.failures.map((f) => f.code)).toEqual(["NO_SCIP_DOCUMENTS"]);
  });

  test("a tree-sitter-only run (--scip false) is still refused when it scanned nothing", () => {
    // The spike measured `metacoding index <fosite> --scip false` at 0 files,
    // 0 symbols, 0 tokens. Not a SCIP problem; still a lie of a graph.
    const r = evaluateIndexOutcome({
      repo: "fosite", targetPath: "/f",
      lanes: lanes({ lane: "tree-sitter", ok: true, files: 0 }),
      source: census({ ".go": 262 }),
      store: { symbols: 0, edgesByKind: {}, relationalEdges: 0 },
      scipRequested: false,
    });
    expect(r.ok).toBe(false);
    expect(r.failures.map((f) => f.code)).toContain("NO_FILES_SCANNED");
  });
});

describe("censusSourceFiles", () => {
  test("counts languages metacoding cannot index, and skips vendor/dot dirs", () => {
    seedSourceFiles(".go", 5, "package main\n");
    mkdirSync(join(repoDir, "node_modules", "dep"), { recursive: true });
    writeFileSync(join(repoDir, "node_modules", "dep", "i.js"), "//\n");
    mkdirSync(join(repoDir, ".git"), { recursive: true });
    writeFileSync(join(repoDir, ".git", "hook.py"), "#\n");
    writeFileSync(join(repoDir, "README.md"), "#\n");

    const c = censusSourceFiles(repoDir);
    expect(c.total).toBe(5);
    expect(c.byExt[".go"]).toBe(5);
    expect(c.byExt[".js"]).toBeUndefined();
    expect(c.byExt[".py"]).toBeUndefined();
  });
});

describe("CLI wiring", () => {
  // Exit status is asserted ONLY here, and only as a wiring check: the graph
  // contents it stands for are pinned by the store-census tests above.
  test("`metacoding index` exits NON-ZERO and names the failure when the graph comes out empty", async () => {
    seedSourceFiles(".go", 30, "package main\n");
    const emptyPath = writeScip(emptyScip(), "cli-empty.scip");
    const cliDataDir = mkdtempSync(join(tmpdir(), "gate-0sd-cli-"));
    try {
      const proc = Bun.spawn(
        [
          "bun", join(import.meta.dir, "bin.ts"), "index", repoDir,
          "--data-dir", cliDataDir, "--repo", "cli-fixture",
          "--load-scip", emptyPath, "--scip-language", "ts",
        ],
        { stdout: "pipe", stderr: "pipe", cwd: join(import.meta.dir, "..", "..") },
      );
      const [stderr, exitCode] = await Promise.all([
        new Response(proc.stderr).text(),
        proc.exited,
      ]);
      expect(exitCode).not.toBe(0);
      expect(stderr).toContain("INDEX FAILED");
      expect(stderr).toContain("NO_FILES_SCANNED");
      expect(stderr).toContain("MetaCoding-0sd");
    } finally {
      rmSync(cliDataDir, { recursive: true, force: true });
    }
  }, 120_000);
});
