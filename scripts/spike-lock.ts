// scripts/spike-lock.ts
//
// Spike: empirically map ladybugdb's cross-process lock semantics so we can
// decide whether a read-only `serve` can coexist with a staged/in-place writer
// (toward the single-writer-daemon design, bead discussion 2026-06-24).
//
// ladybugdb's Database constructor exposes a `readOnly` flag (positional arg 4:
//   new Database(path, bufferSize?, enableCompression?, readOnly?, ...)).
// This probes the 2-process matrix: a "holder" process opens + holds the DB,
// then a "tester" attempt opens the SAME db (and, for the staged case, a
// DIFFERENT db) while the holder is live.
//
// Run: bun run scripts/spike-lock.ts
// Child mode (internal): bun run scripts/spike-lock.ts hold <graphPath> <ro|rw> <holdMs>

import { mkdtempSync, rmSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { Database, Connection } from "@ladybugdb/core";
import { Store } from "../src/store";

const SCRIPT = import.meta.path;

/** Open raw ladybug at graphPath with the given mode; run a trivial query. */
async function openRaw(graphPath: string, readOnly: boolean) {
  const db = new Database(graphPath, undefined, undefined, readOnly);
  const conn = new Connection(db);
  const qr = await conn.query("RETURN 1 AS one");
  await qr.getAll();
  await qr.close();
  return { db, conn };
}

// ---------- child "hold" mode ----------
if (process.argv[2] === "hold") {
  const graphPath = process.argv[3]!;
  const ro = process.argv[4] === "ro";
  const holdMs = Number(process.argv[5] ?? "4000");
  const readyFlag = `${graphPath}.holder-ready`;
  try {
    const { db, conn } = await openRaw(graphPath, ro);
    await Bun.write(readyFlag, "ok");
    await Bun.sleep(holdMs);
    await conn.close();
    await db.close();
    process.exit(0);
  } catch (e) {
    await Bun.write(`${readyFlag}.failed`, (e as Error).message.split("\n")[0]);
    process.exit(1);
  }
}

// ---------- orchestrator ----------
function freshDb(): { dir: string; graph: string } {
  const dir = mkdtempSync(join(tmpdir(), "lbug-spike-"));
  return { dir, graph: join(dir, "graph.lbug") };
}

/** Seed a valid ladybug DB at dir via the real Store (ensures schema), then close. */
async function seed(dir: string) {
  const store = await Store.open(dir);
  await store.close();
}

async function waitReady(graph: string, timeoutMs = 8000): Promise<"ready" | "failed" | "timeout"> {
  const ready = `${graph}.holder-ready`;
  const failed = `${ready}.failed`;
  const start = performance.now();
  while (performance.now() - start < timeoutMs) {
    if (existsSync(ready)) return "ready";
    if (existsSync(failed)) return "failed";
    await Bun.sleep(50);
  }
  return "timeout";
}

/**
 * holderMode opens `holderGraph` and holds it; then we try to open
 * `testerGraph` in `testerMode` from THIS process. Same graph unless a
 * staged (different-dir) scenario passes a distinct testerGraph.
 */
async function scenario(
  label: string,
  holderMode: "ro" | "rw",
  testerMode: "ro" | "rw",
  opts: { staged?: boolean } = {},
): Promise<void> {
  const holder = freshDb();
  await seed(holder.dir);

  let testerGraph = holder.graph;
  let stagedDir: string | null = null;
  if (opts.staged) {
    const t = freshDb();
    await seed(t.dir);
    testerGraph = t.graph;
    stagedDir = t.dir;
  }

  const child = Bun.spawn(
    ["bun", "run", SCRIPT, "hold", holder.graph, holderMode, "5000"],
    { stdout: "ignore", stderr: "ignore" },
  );

  const ready = await waitReady(holder.graph);
  if (ready !== "ready") {
    console.log(`  ${label}: holder(${holderMode}) could not open (${ready}) — inconclusive`);
    child.kill();
    rmSync(holder.dir, { recursive: true, force: true });
    if (stagedDir) rmSync(stagedDir, { recursive: true, force: true });
    return;
  }

  // Holder is live. Try the tester open from this process.
  let verdict: string;
  try {
    const { db, conn } = await openRaw(testerGraph, testerMode === "ro");
    verdict = "PASS (coexists)";
    await conn.close();
    await db.close();
  } catch (e) {
    verdict = `BLOCKED — ${(e as Error).message.split("\n")[0]}`;
  }

  const where = opts.staged ? "different dir" : "same dir";
  console.log(`  ${label}: holder=${holderMode} + tester=${testerMode} (${where}) -> ${verdict}`);

  child.kill();
  await child.exited;
  rmSync(holder.dir, { recursive: true, force: true });
  if (stagedDir) rmSync(stagedDir, { recursive: true, force: true });
}

console.log("ladybugdb cross-process lock matrix:");
await scenario("1 RW+RW same", "rw", "rw");
await scenario("2 RW+RO same", "rw", "ro");
await scenario("3 RO+RO same", "ro", "ro");
await scenario("4 RO+RW same", "ro", "rw");
await scenario("5 RW+RO staged", "rw", "ro", { staged: true });
console.log("done.");
process.exit(0);
