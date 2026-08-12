// scripts/smoke-summary.ts
//
// Smoke test for MetaCoding-3p6.1: Store.summary() + the gatherIndexState seam.
//
// Verifies:
//   1. A fresh (un-indexed) store reports symbols=0 / indexed=false, and
//      gatherIndexState reports indexed:false.
//   2. After upserting Symbols, summary() reports the count, indexed=true, and
//      a per-repo RepoSnapshot with the right repo + count.
//
// Run with: bun run scripts/smoke-summary.ts

import { existsSync, mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "../src/store";
import type { Symbol } from "../src/store/types";
import { gatherIndexState } from "../src/index-state";
import { beginRun, type Floor } from "../src/testkit/floors.ts";

// Every check is COUNTED (src/testkit/floors.ts): the count is derived from
// the calls that run, so a deleted assertion is visible instead of silent.
const run = beginRun("summary");

const FLOORS: Floor[] = [
  {
    min: 10,
    measuredAs: "checks",
    why: "counted from the source: 10 assertion sites - 5 on the fresh store (symbols, indexed, dataDir, gatherIndexState indexed, staleness) and 5 on the filled one (symbols, indexed, snapshot present, snapshot count, indexed_at type)",
  },
];

const DATA_DIR = mkdtempSync(join(tmpdir(), "metacoding-summary-smoke-"));

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
}

function makeSymbol(id: string, short: string): Symbol {
  return {
    id,
    kind: "function",
    language: "ts",
    repo: "smoke-repo",
    qualified_name: `pkg.${short}`,
    short_name: short,
    file: "src/example.ts",
    line: 1,
    col: 0,
    end_line: 2,
    end_col: 0,
    signature: null,
    visibility: "public",
    is_abstract: false,
    is_static: false,
    ast_hash: null,
    branch: "main",
    source: "tree_sitter",
    repo_commit_sha: "0123456789abcdef0123456789abcdef01234567",
    indexed_at: new Date().toISOString(),
  };
}

async function main(): Promise<void> {
  const store = await Store.open(DATA_DIR);

  // 1. Fresh store: nothing indexed.
  const empty = await store.summary();
  run.check("fresh store reports symbols=0", empty.symbols === 0, `got ${empty.symbols}`);
  run.check("fresh store reports indexed=false", empty.indexed === false, `got ${empty.indexed}`);
  run.check("fresh store reports its dataDir", empty.dataDir === DATA_DIR, `got ${empty.dataDir}`);

  const emptyState = await gatherIndexState(store, DATA_DIR);
  run.check("fresh gatherIndexState reports indexed=false", emptyState.indexed === false, `got ${emptyState.indexed}`);
  run.check("fresh gatherIndexState reports staleness=null", emptyState.staleness === null, `got ${emptyState.staleness}`);
  console.log(`empty summary OK: symbols=0 indexed=false`);

  // 2. After writing symbols.
  await store.upsertSymbol(makeSymbol("a", "alpha"));
  await store.upsertSymbol(makeSymbol("b", "beta"));

  const filled = await store.summary();
  run.check("filled store reports symbols=2", filled.symbols === 2, `got ${filled.symbols}`);
  run.check("filled store reports indexed=true", filled.indexed === true, `got ${filled.indexed}`);
  const snap = filled.repos.find((r) => r.repo === "smoke-repo");
  run.check(
    "filled store carries a smoke-repo snapshot",
    snap !== undefined,
    `repos: ${JSON.stringify(filled.repos)}`,
  );
  run.check("smoke-repo snapshot counts 2 symbols", snap!.symbols === 2, `got ${snap!.symbols}`);
  run.check("smoke-repo snapshot carries indexed_at", typeof snap!.indexed_at === "string", `got ${snap!.indexed_at}`);
  console.log(`filled summary OK: symbols=2 indexed=true repo=smoke-repo`);

  await store.close();
  cleanup();
  run.finish(FLOORS);
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("SUMMARY_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
