// scripts/smoke-readonly.ts
//
// Validates read-only Store.open (the "use the index while indexing" fix):
//  1. A read-only Store can OPEN and query a dir while a read-WRITE Store is
//     live on the same dir — no lock error (ladybugdb's lock excludes only
//     other writers; see scripts/spike-lock.ts).
//  2. A read-only Store opened on a never-indexed dir bootstraps cleanly and
//     reports indexed=false (rather than throwing).
//  3. After the writer checkpoints (close), a fresh read-only open sees the
//     committed rows (read-only handles are snapshot-pinned; see
//     scripts/spike-refresh.ts).
//
// Run with: bun run scripts/smoke-readonly.ts

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Store } from "../src/store";
import type { Symbol as Sym } from "../src/store/types";
import { beginRun, type Floor } from "../src/testkit/floors.ts";

function makeSym(id: string): Sym {
  return {
    id, kind: "function", language: "ts", repo: "ro-repo",
    qualified_name: `ro.${id}`, short_name: id,
    file: "f.ts", line: 1, col: 0, end_line: 1, end_col: 1,
    signature: null, visibility: null, is_abstract: false, is_static: false,
    ast_hash: id, branch: "main", source: "tree_sitter",
    indexed_at: "2026-06-24T00:00:00.000Z", repo_commit_sha: "deadbeef",
    repo_commit_date: null, partition: null,
  };
}

// Every assert is now a COUNTED check (src/testkit/floors.ts): the count is
// derived from the calls that actually run, so deleting one is visible.
const run = beginRun("readonly");
function assert(cond: boolean, msg: string): void {
  run.check(msg, cond, `ASSERT FAILED: ${msg}`);
}

const FLOORS: Floor[] = [
  {
    min: 5,
    measuredAs: "checks",
    why: "counted from the source: this file has 5 assert() call sites across the 3 numbered scenarios",
  },
];

const dir = mkdtempSync(join(tmpdir(), "ro-smoke-"));
try {
  // (2) Read-only open on a never-indexed dir: bootstraps, reports not-indexed.
  {
    const ro = await Store.open(dir, { readOnly: true });
    const s = await ro.summary();
    assert(ro.readOnly === true, "store should report readOnly=true");
    assert(s.indexed === false && s.symbols === 0, "fresh dir should be indexed=false/0");
    await ro.close();
    console.log("readonly fresh-dir OK: indexed=false symbols=0");
  }

  // Writer opens read-WRITE and writes, WITHOUT closing yet.
  const writer = await Store.open(dir);
  await writer.upsertSymbol(makeSym("A"));
  await writer.upsertSymbol(makeSym("B"));

  // (1) Coexistence: a read-only open succeeds while the writer is still live.
  {
    const ro = await Store.open(dir, { readOnly: true });
    const s = await ro.summary(); // may be 0 (pre-checkpoint) — we assert no throw
    assert(s.symbols >= 0, "read-only summary should run while writer is live");
    await ro.close();
    console.log(`readonly coexist OK: opened alongside live writer (saw ${s.symbols} pre-checkpoint)`);
  }

  // Writer checkpoints by closing.
  await writer.close();

  // (3) Post-checkpoint visibility: a fresh read-only open sees both rows.
  {
    const ro = await Store.open(dir, { readOnly: true });
    const s = await ro.summary();
    assert(s.symbols === 2, `post-checkpoint read-only should see 2 symbols, saw ${s.symbols}`);
    assert(s.indexed === true, "post-checkpoint should be indexed=true");
    await ro.close();
    console.log(`readonly post-checkpoint OK: symbols=${s.symbols} indexed=true`);
  }

  // finish() owns the PASS token: it prints only after the floors hold.
  run.finish(FLOORS);
} finally {
  rmSync(dir, { recursive: true, force: true });
}
process.exit(0);
