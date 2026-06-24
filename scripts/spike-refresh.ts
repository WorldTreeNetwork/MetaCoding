// scripts/spike-refresh.ts
//
// Follow-up to spike-lock.ts. We know a read-only open coexists with a live
// writer on the same dir. The remaining question for a read-only `serve`:
// once a SEPARATE writer process commits new data, does a long-lived read-only
// handle SEE it — on the same connection, a new connection, or only after a
// full reopen? That decides whether read-only serve needs a reopen-on-refresh.
//
// Run: bun run scripts/spike-refresh.ts
// Child (internal): bun run scripts/spike-refresh.ts write <dir> <id>

import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Database, Connection } from "@ladybugdb/core";
import { Store } from "../src/store";
import type { Symbol as Sym } from "../src/store/types";

const SCRIPT = import.meta.path;

function makeSym(id: string): Sym {
  return {
    id, kind: "function", language: "ts", repo: "spike",
    qualified_name: `spike.${id}`, short_name: id,
    file: "f.ts", line: 1, col: 0, end_line: 1, end_col: 1,
    signature: null, visibility: null, is_abstract: false, is_static: false,
    ast_hash: id, branch: "main", source: "tree_sitter",
    indexed_at: "2026-06-24T00:00:00.000Z", repo_commit_sha: "deadbeef",
    repo_commit_date: null, partition: null,
  };
}

// ---------- child writer ----------
if (process.argv[2] === "write") {
  const dir = process.argv[3]!;
  const id = process.argv[4]!;
  const store = await Store.open(dir);          // RW open in its own process
  await store.upsertSymbol(makeSym(id));
  await store.close();                          // close → checkpoint/persist
  process.exit(0);
}

// ---------- orchestrator ----------
async function countOn(conn: Connection): Promise<number> {
  const qr = await conn.query("MATCH (n:Symbol) RETURN count(n) AS c");
  const rows = (await qr.getAll()) as Array<{ c: number | bigint }>;
  await qr.close();
  return Number(rows[0]?.c ?? 0);
}

const dir = mkdtempSync(join(tmpdir(), "lbug-refresh-"));
const graph = join(dir, "graph.lbug");
try {
  // Seed with one symbol via a writer, then close (count = 1).
  {
    const store = await Store.open(dir);
    await store.upsertSymbol(makeSym("A"));
    await store.close();
  }

  // Open a long-lived READ-ONLY handle (this is what `serve` would hold).
  const roDb = new Database(graph, undefined, undefined, true);
  const roConn = new Connection(roDb);
  const c0 = await countOn(roConn);

  // A separate writer process commits a NEW symbol while the RO handle is open.
  const child = Bun.spawn(["bun", "run", SCRIPT, "write", dir, "B"], {
    stdout: "ignore", stderr: "ignore",
  });
  const code = await child.exited;

  // (a) Same long-lived RO connection — does a fresh query see the new row?
  const c1 = await countOn(roConn);

  // (b) A brand-new connection on the same (already-open) RO Database handle.
  const c2 = await countOn(new Connection(roDb));

  await roConn.close();
  await roDb.close();

  // (c) A full reopen (new Database) read-only.
  const reDb = new Database(graph, undefined, undefined, true);
  const reConn = new Connection(reDb);
  const c3 = await countOn(reConn);
  await reConn.close();
  await reDb.close();

  console.log(`writer child exit: ${code}`);
  console.log(`c0 (RO before write)            = ${c0}   (expect 1)`);
  console.log(`c1 (same RO conn, new query)    = ${c1}`);
  console.log(`c2 (new conn, same RO Database)  = ${c2}`);
  console.log(`c3 (full reopen RO)             = ${c3}   (expect 2)`);
  console.log("");
  if (c1 === 2) console.log("=> Live RO connection refreshes per-query. Read-only serve needs NO reopen.");
  else if (c2 === 2) console.log("=> New connection on same Database sees it. serve refreshes by making a fresh Connection per call.");
  else if (c3 === 2) console.log("=> Only a full reopen sees new data. Read-only serve needs reopen-on-refresh (cheap, signal-driven).");
  else console.log("=> Even reopen did not see it — writer didn't checkpoint on close; needs explicit CHECKPOINT.");
} finally {
  rmSync(dir, { recursive: true, force: true });
}
process.exit(0);
