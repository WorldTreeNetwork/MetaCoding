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
  if (empty.symbols !== 0) {
    throw new Error(`fresh store: expected symbols=0, got ${empty.symbols}`);
  }
  if (empty.indexed !== false) {
    throw new Error(`fresh store: expected indexed=false, got ${empty.indexed}`);
  }
  if (empty.dataDir !== DATA_DIR) {
    throw new Error(`fresh store: dataDir mismatch ${empty.dataDir} !== ${DATA_DIR}`);
  }

  const emptyState = await gatherIndexState(store, DATA_DIR);
  if (emptyState.indexed !== false) {
    throw new Error(`fresh gatherIndexState: expected indexed=false, got ${emptyState.indexed}`);
  }
  if (emptyState.staleness !== null) {
    throw new Error(`fresh gatherIndexState: expected staleness=null`);
  }
  console.log(`empty summary OK: symbols=0 indexed=false`);

  // 2. After writing symbols.
  await store.upsertSymbol(makeSymbol("a", "alpha"));
  await store.upsertSymbol(makeSymbol("b", "beta"));

  const filled = await store.summary();
  if (filled.symbols !== 2) {
    throw new Error(`filled store: expected symbols=2, got ${filled.symbols}`);
  }
  if (filled.indexed !== true) {
    throw new Error(`filled store: expected indexed=true, got ${filled.indexed}`);
  }
  const snap = filled.repos.find((r) => r.repo === "smoke-repo");
  if (!snap) {
    throw new Error(`filled store: repo 'smoke-repo' missing from ${JSON.stringify(filled.repos)}`);
  }
  if (snap.symbols !== 2) {
    throw new Error(`filled store: expected smoke-repo count=2, got ${snap.symbols}`);
  }
  if (typeof snap.indexed_at !== "string") {
    throw new Error(`filled store: expected indexed_at string, got ${snap.indexed_at}`);
  }
  console.log(`filled summary OK: symbols=2 indexed=true repo=smoke-repo`);

  await store.close();
  cleanup();
  console.log("SUMMARY_SMOKE_PASS");
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("SUMMARY_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
