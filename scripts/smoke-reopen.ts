// scripts/smoke-reopen.ts
//
// Smoke-tests the BUILDING BLOCKS of serve's reopen-on-refresh (bead
// MetaCoding-gh0.1). The reopen logic itself lives in a serveMcp closure
// (src/mcp/server.ts), so we exercise the Store-level primitives it stands on,
// using the same cross-process pattern as scripts/spike-refresh.ts:
//
//   1. Store.generation(dir) advances when a separate writer process
//      checkpoints new data into graph.lbug.
//   2. A fresh read-only Store.open(dir) opened AFTER that advance sees the
//      new rows — which is exactly what currentStore() automates when it
//      detects the generation has moved.
//
// Run:   bun run scripts/smoke-reopen.ts
// Child: bun run scripts/smoke-reopen.ts write <dir> <id>   (internal)

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store";
import type { Symbol as Sym } from "../src/store/types";

const SCRIPT = import.meta.path;

function makeSym(id: string): Sym {
  return {
    id, kind: "function", language: "ts", repo: "reopen",
    qualified_name: `reopen.${id}`, short_name: id,
    file: "f.ts", line: 1, col: 0, end_line: 1, end_col: 1,
    signature: null, visibility: null, is_abstract: false, is_static: false,
    ast_hash: id, branch: "main", source: "tree_sitter",
    indexed_at: "2026-06-24T00:00:00.000Z", repo_commit_sha: "deadbeef",
    repo_commit_date: null, partition: null,
  };
}

function assert(cond: boolean, msg: string): void {
  if (!cond) throw new Error(`ASSERT FAILED: ${msg}`);
}

// ---------- child writer ----------
if (process.argv[2] === "write") {
  const dir = process.argv[3]!;
  const id = process.argv[4]!;
  const store = await Store.open(dir);   // RW open in its own process
  await store.upsertSymbol(makeSym(id));
  await store.close();                   // close → checkpoint/persist
  process.exit(0);
}

// ---------- orchestrator ----------
const dir = mkdtempSync(join(tmpdir(), "reopen-smoke-"));
try {
  // (1) Seed via a read-write Store, close to checkpoint. Record the
  //     generation marker at this point.
  {
    const writer = await Store.open(dir);
    await writer.upsertSymbol(makeSym("A"));
    await writer.close();
  }
  const g0 = Store.generation(dir);
  assert(g0 > 0, `generation should be > 0 after seeding, got ${g0}`);

  // (2) Open the long-lived read-only "serve" handle; it sees 1 symbol.
  const serveStore = await Store.open(dir, { readOnly: true });
  {
    const s = await serveStore.summary();
    assert(s.symbols === 1, `serve handle should see 1 symbol, saw ${s.symbols}`);
  }

  // (3) A SEPARATE writer process commits "B" while the serve handle is open.
  const child = Bun.spawn(["bun", "run", SCRIPT, "write", dir, "B"], {
    stdout: "ignore", stderr: "ignore",
  });
  const code = await child.exited;
  assert(code === 0, `writer child should exit 0, exited ${code}`);

  // (4) The on-disk generation advanced past g0 (graph.lbug mtime moved).
  const g1 = Store.generation(dir);
  assert(g1 > g0, `generation should advance past ${g0}, got ${g1}`);

  // (5) Reopen a fresh read-only Store (what currentStore() does on advance);
  //     it sees the new row. The original serve handle stays snapshot-pinned.
  const reopened = await Store.open(dir, { readOnly: true });
  {
    const s = await reopened.summary();
    assert(s.symbols === 2, `reopened handle should see 2 symbols, saw ${s.symbols}`);
  }

  await reopened.close();
  await serveStore.close();

  console.log("REOPEN_SMOKE_PASS");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
process.exit(0);
