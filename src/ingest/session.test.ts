// WIRED evidence for docs/design/index-fitness.md — the whole CLI, a real
// store, a real health record. Beads MetaCoding-0sd, 4kg, 5fi, e6z, ae5, hy6.16.
//
// Everything here runs `bin.ts` in a subprocess against a sandbox data dir.
// That matters: MetaCoding-e6z/M3 survived because the only wired test in the
// previous suite used an empty `.scip` whose ACCUMULATORS were also zero, so it
// could not tell "measured from the store" from "measured from the indexer's
// own counters". A wired test whose two halves cannot disagree is not evidence.

import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, existsSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";

import { Store } from "../store";
import { readIndexHealth, isAbandonedRun, IndexHealthStore } from "../store/health.ts";
import { graphCallers } from "../mcp/tools.ts";

const BIN = join(import.meta.dir, "..", "cli", "bin.ts");
const CWD = join(import.meta.dir, "..", "..");

let dataDir: string;
let repoDir: string;

beforeEach(() => {
  dataDir = mkdtempSync(join(tmpdir(), "session-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "session-repo-"));
});

afterEach(() => {
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

interface RunOut { code: number | null; stdout: string; stderr: string }

async function cli(args: string[], opts: { timeoutMs?: number } = {}): Promise<RunOut> {
  const proc = Bun.spawn(["bun", BIN, ...args], { stdout: "pipe", stderr: "pipe", cwd: CWD });
  const timer = opts.timeoutMs
    ? setTimeout(() => { try { proc.kill(9); } catch {} }, opts.timeoutMs)
    : null;
  const [stdout, stderr, code] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);
  if (timer) clearTimeout(timer);
  return { code, stdout, stderr };
}

function seed(ext: string, n: number, body: (i: number) => string): string[] {
  mkdirSync(join(repoDir, "src"), { recursive: true });
  const paths: string[] = [];
  for (let i = 0; i < n; i++) {
    writeFileSync(join(repoDir, "src", `f${i}${ext}`), body(i), "utf-8");
    paths.push(`src/f${i}${ext}`);
  }
  return paths;
}

function writeScip(bytes: Uint8Array, name: string): string {
  const p = join(repoDir, name);
  writeFileSync(p, bytes);
  return p;
}

/** A .scip that DEFINES a symbol per path, plus a cross-file reference. */
function productiveScipFor(paths: string[]): Uint8Array {
  const PKG = "scip-typescript npm fixture 1.0.0";
  const sym = (i: number) => `${PKG} \`${paths[i]}\`/fn${i}().`;
  return new scip.Index({
    documents: paths.map((p, i) =>
      new scip.Document({
        relative_path: p,
        language: "typescript",
        occurrences: [
          new scip.Occurrence({ symbol: sym(i), range: [1, 9, 1, 12], symbol_roles: scip.SymbolRole.Definition }),
          new scip.Occurrence({ symbol: sym((i + 1) % paths.length), range: [2, 4, 2, 8], symbol_roles: 0 }),
        ],
        symbols: [],
      }),
    ),
  }).serialize();
}

/**
 * THE ACCUMULATOR TRAP: 40 documents, each with real occurrences, NONE of them
 * a definition — so the lane reports `documents: 40` (a large, healthy-looking
 * accumulator) and the STORE receives nothing.
 */
function referencesOnlyScip(n = 40): Uint8Array {
  const PKG = "scip-typescript npm ghost 1.0.0";
  return new scip.Index({
    documents: Array.from({ length: n }, (_, i) =>
      new scip.Document({
        relative_path: `src/ghost${i}.ts`,
        language: "typescript",
        occurrences: [
          new scip.Occurrence({
            symbol: `${PKG} \`src/nowhere${i}.ts\`/absent${i}().`,
            range: [1, 4, 1, 10],
            symbol_roles: 0,
          }),
        ],
        symbols: [],
      }),
    ),
  }).serialize();
}

// ---------------------------------------------------------------------------
// PAIR 1 — STORE vs ACCUMULATORS, wired. Kills MetaCoding-e6z/M3.
// ---------------------------------------------------------------------------

describe("PAIR 1 — the verdict comes from the STORE, not the indexer's counters", () => {
  test("1a: accumulators NON-ZERO (40 documents) + store EMPTY -> REFUSED", async () => {
    seed(".go", 40, () => "package main\n");
    const barren = writeScip(referencesOnlyScip(40), "ghosts.scip");

    const r = await cli([
      "index", repoDir, "--data-dir", dataDir, "--repo", "ghost",
      "--branch", "main", "--load-scip", barren, "--scip-language", "ts",
    ]);

    expect(r.code).not.toBe(0);
    const rec = readIndexHealth(dataDir, "ghost", "main");
    expect(rec).not.toBeNull();
    expect(rec!.status).toBe("REFUSED");

    // THE CONTRAST INSIDE ONE RUN: the accumulator a gate could have believed
    // is 40, and the store it must believe instead is 0. A census fabricated
    // from `lane.files` (which is exactly what NO_SCIP_DOCUMENTS counted, and
    // exactly what MetaCoding-4kg exploited — "an empty document is a document")
    // would have passed this run.
    const scipLane = rec!.lanes.find((l) => l.lane === "scip:load-scip")!;
    expect(scipLane.files).toBe(40);           // accumulator: healthy-looking
    expect(scipLane.ok).toBe(true);            // the lane did not even fail
    expect(rec!.fitness!.symbols).toBe(0);     // store: empty
    expect(rec!.contribution!.scipSymbols).toBe(0);
    expect(rec!.failures.map((f) => f.code)).toContain("NO_SYMBOLS");

    // And the identity of the ingested file is recorded — citation for the
    // standing open red about re-ingesting yesterday's index.
    expect(rec!.index_identities[0]!.sha256).toHaveLength(64);
  }, 120_000);

  test("1b (the mirror): a warm re-index REBUILDS, and the store is unchanged", async () => {
    // THE CONSTRUCTION CHANGED WITH MetaCoding-9jt, and it is worth saying why.
    //
    // This half used to work by the walker's ast_hash skip: a warm re-index
    // touched nothing, every accumulator read ZERO, and the point was that the
    // verdict followed the STORE rather than those zeros. That skip is deleted
    // — it was destroying cross-file edges (src/store/build.ts) — so a warm
    // re-index now re-extracts and re-writes everything.
    //
    // 1a still carries the store-vs-accumulators property on its own: an
    // accumulator of 40 over an empty store is REFUSED. What this half tests
    // now is the stronger property the rebuild makes available and that the
    // skip path could never have offered: A RE-INDEX OF AN UNCHANGED TREE IS
    // IDEMPOTENT. Same verdict, same store, no drift, no growth.
    seed(".ts", 12, (i) => `export function fn${i}() { return ${i}; }\n`);
    const args = [
      "index", repoDir, "--data-dir", dataDir, "--repo", "warm", "--branch", "main",
      "--scip", "false",
    ];

    const first = await cli(args);
    expect(first.code).toBe(0);
    const rec1 = readIndexHealth(dataDir, "warm", "main")!;
    expect(rec1.status).toBe("HEALTHY");
    expect(rec1.correspondence!.level).toBe("exact");
    expect(rec1.correspondence!.ratio).toBe(1);
    expect(rec1.contribution!.symbols).toBeGreaterThan(0);

    const second = await cli(args);
    expect(second.code).toBe(0);
    const summary = JSON.parse(second.stdout) as {
      treeSitter: { filesScanned: number; filesSkipped: number; filesUpdated: number; symbols: number };
      health: { status: string; fitness: { symbols: number }; contribution: { symbols: number } };
    };
    // ACCUMULATORS: the whole tree, again. Nothing is skipped any more, and
    // `filesSkipped` now means only "no grammar could parse this".
    expect(summary.treeSitter.filesScanned).toBe(12);
    expect(summary.treeSitter.filesUpdated).toBe(12);
    expect(summary.treeSitter.filesSkipped).toBe(0);
    expect(summary.treeSitter.symbols).toBeGreaterThan(0);
    // ...and every symbol in the store carries THIS run's stamp, because this
    // run wrote all of them.
    expect(summary.health.contribution.symbols).toBe(summary.health.fitness.symbols);

    // IDEMPOTENT: rebuilding an unchanged tree neither grows nor shrinks the
    // store. A rebuild that double-wrote, or that dropped the slice it was
    // replacing, fails here — and both are live risks in a bulk-load write path
    // that DELETEs before it COPYs (src/store/build.ts).
    expect(summary.health.fitness.symbols).toBe(rec1.fitness!.symbols);
    expect(summary.health.status).toBe("HEALTHY");
  }, 180_000);
});

// ---------------------------------------------------------------------------
// PAIR 7 — CRASH VISIBILITY (MetaCoding-ae5). Asserted on the RECORD and on a
// TOOL RESPONSE, never on an exit code.
// ---------------------------------------------------------------------------

describe("PAIR 7 — a SIGKILLed run leaves fitness UNESTABLISHED, and readers see it", () => {
  test("killed mid-ingest -> RUNNING + abandoned; the same store finished -> HEALTHY", async () => {
    const paths = seed(".ts", 30, (i) => `export function fn${i}() { return ${i}; }\n`);
    const good = writeScip(productiveScipFor(paths), "good.scip");
    const args = [
      "index", repoDir, "--data-dir", dataDir, "--repo", "killed", "--branch", "main",
      "--load-scip", good, "--scip-language", "ts",
    ];

    // --- half A: KILLED -----------------------------------------------------
    const proc = Bun.spawn(["bun", BIN, ...args], { stdout: "pipe", stderr: "pipe", cwd: CWD });
    // Deterministic: the RUNNING record is written before any lane runs, so we
    // kill as soon as it appears rather than guessing a sleep.
    const deadline = Date.now() + 20_000;
    let running = null as ReturnType<typeof readIndexHealth>;
    while (Date.now() < deadline) {
      running = readIndexHealth(dataDir, "killed", "main");
      if (running?.status === "RUNNING") break;
      await Bun.sleep(25);
    }
    proc.kill(9);
    await proc.exited;

    expect(running).not.toBeNull();
    expect(running!.status).toBe("RUNNING");
    expect(running!.finished_at).toBeNull();

    const after = readIndexHealth(dataDir, "killed", "main")!;
    // The process is gone and the record NEVER finalized. Closed by
    // construction: nothing had to detect the death.
    expect(after.status).toBe("RUNNING");
    expect(isAbandonedRun(after)).toBe(true);

    // A READER sees it — asserted on a tool response, not on an exit code.
    const store = await Store.open(dataDir, { readOnly: true });
    try {
      const answer = await graphCallers(store, { symbol: "nothing::here" });
      expect(answer.ok).toBe(false);
      if (answer.ok) throw new Error("unreachable");
      expect(answer.error).toBe("INDEX_FITNESS_UNESTABLISHED");
    } finally {
      await store.close();
    }

    // ...and `status` says so beside the symbol count, instead of "Indexed:".
    const st = await cli(["status", repoDir, "--data-dir", dataDir]);
    expect(st.stdout).toContain("index fitness:");
    expect(st.stdout).toMatch(/DIED without finalizing|IN PROGRESS/);

    // --- half B: the SAME store, the SAME command, allowed to FINISH ---------
    const done = await cli(args);
    expect(done.code).toBe(0);
    const finalized = readIndexHealth(dataDir, "killed", "main")!;
    expect(finalized.status).toBe("HEALTHY");
    expect(finalized.finished_at).not.toBeNull();
    expect(isAbandonedRun(finalized)).toBe(false);

    const store2 = await Store.open(dataDir, { readOnly: true });
    try {
      // OPPOSITE TYPE from the identical call above.
      const answer = await graphCallers(store2, { symbol: "nothing::here" });
      expect(answer.ok).toBe(true);
      if (!answer.ok) throw new Error("unreachable");
      expect(answer.rows).toEqual([]);
    } finally {
      await store2.close();
    }
  }, 240_000);
});

// ---------------------------------------------------------------------------
// PAIR 9 — `watch` INHERITS the gate.
// ---------------------------------------------------------------------------

describe("PAIR 9 — watch and index give the SAME verdict over the same tree", () => {
  test("the fosite shape refuses under BOTH commands; a good tree passes under both", async () => {
    // `metacoding watch` previously called indexDirectory straight out of the
    // extractor barrel and had no gate at all. The fix is not a call added to
    // cmdWatch — the primitive is no longer reachable from there.
    seed(".go", 40, () => "package main\n");

    const indexed = await cli([
      "index", repoDir, "--data-dir", dataDir, "--repo", "fosite-ish",
      "--branch", "main", "--scip", "false",
    ]);
    const indexRec = readIndexHealth(dataDir, "fosite-ish", "main")!;

    rmSync(dataDir, { recursive: true, force: true });
    const watched = await cli([
      "watch", repoDir, "--data-dir", dataDir, "--repo", "fosite-ish",
      "--branch", "main", "--scip", "false",
    ], { timeoutMs: 20_000 });
    const watchRec = readIndexHealth(dataDir, "fosite-ish", "main")!;

    expect(indexed.code).not.toBe(0);
    expect(watched.code).not.toBe(0);            // watch exits, does not watch
    expect(indexRec.status).toBe("REFUSED");
    expect(watchRec.status).toBe("REFUSED");
    // SAME failure codes, from the same measurement — that is what "inherits"
    // has to mean for the seam to be in the right place.
    expect(watchRec.failures.map((f) => f.code).sort())
      .toEqual(indexRec.failures.map((f) => f.code).sort());
    expect(watched.stderr).toContain("INDEX REFUSED");
  }, 180_000);

  test("watch on a HEALTHY tree starts watching and says so", async () => {
    // The mirror: the gate must not refuse everything, or `watch` is just broken.
    const paths = seed(".ts", 12, (i) => `export function fn${i}() { return ${i}; }\n`);
    const good = writeScip(productiveScipFor(paths), "good.scip");

    const proc = Bun.spawn(
      ["bun", BIN, "watch", repoDir, "--data-dir", dataDir, "--repo", "wok",
       "--branch", "main", "--load-scip", good, "--scip-language", "ts"],
      { stdout: "pipe", stderr: "pipe", cwd: CWD },
    );
    const deadline = Date.now() + 30_000;
    let rec = null as ReturnType<typeof readIndexHealth>;
    while (Date.now() < deadline) {
      rec = readIndexHealth(dataDir, "wok", "main");
      if (rec && rec.status !== "RUNNING") break;
      await Bun.sleep(50);
    }
    // Give the watcher a moment to mark itself, then stop it.
    await Bun.sleep(500);
    const watching = readIndexHealth(dataDir, "wok", "main");
    proc.kill(9);
    await proc.exited;

    expect(rec).not.toBeNull();
    expect(rec!.status).toBe("HEALTHY");
    expect(watching!.watching).toBe(true);   // recorded: incremental writes ongoing
  }, 180_000);
});

// ---------------------------------------------------------------------------
// OVERRIDES become durable facts, and are parsed STRICTLY.
// ---------------------------------------------------------------------------

describe("overrides are recorded, and the parser refuses to guess", () => {
  test("--allow-empty-index turns a REFUSED run into an OVERRIDDEN record", async () => {
    seed(".go", 40, () => "package main\n");
    const barren = writeScip(referencesOnlyScip(40), "ghosts.scip");
    const args = (extra: string[]) => [
      "index", repoDir, "--data-dir", dataDir, "--repo", "ov", "--branch", "main",
      "--load-scip", barren, "--scip-language", "ts", ...extra,
    ];

    const refused = await cli(args([]));
    expect(refused.code).not.toBe(0);
    expect(readIndexHealth(dataDir, "ov", "main")!.status).toBe("REFUSED");

    const overridden = await cli(args(["--allow-empty-index"]));
    expect(overridden.code).toBe(0);
    const rec = readIndexHealth(dataDir, "ov", "main")!;
    expect(rec.status).toBe("OVERRIDDEN");
    // The flag and its value, visible at read time FOREVER — not one stderr
    // line that vanishes with the terminal scrollback.
    expect(rec.override).toEqual({ flag: "--allow-empty-index", value: "true" });
    expect(rec.failures.length).toBeGreaterThan(0);
  }, 180_000);

  test("'--allow-empty-index 0' is REJECTED, not silently treated as true", async () => {
    // Measured by the fresh judge: ANY value other than the literal "false"
    // used to ENABLE the flag, so `0`, `no` and `off` all turned the gate OFF.
    seed(".go", 5, () => "package main\n");
    const r = await cli([
      "index", repoDir, "--data-dir", dataDir, "--repo", "strict",
      "--scip", "false", "--allow-empty-index", "0",
    ]);
    expect(r.code).toBe(2);
    expect(r.stderr).toContain("takes no value or exactly true|false");
    // CONTRAST: the legitimate spellings still work as intended.
    const off = await cli([
      "index", repoDir, "--data-dir", dataDir, "--repo", "strict",
      "--scip", "false", "--allow-empty-index", "false",
    ]);
    expect(off.code).toBe(1);                       // gate still enforced
    expect(readIndexHealth(dataDir, "strict", "main")?.status).toBe("REFUSED");
  }, 120_000);

  test("'--min-coverage 0' no longer silently disables the floor — it is an OVERRIDE", async () => {
    // 12 .go files in the tree — a language no lane can see, so the ONLY thing
    // in the graph is what the pre-built index carries. It carries one file's
    // worth: 1/12 = 8.3%, below the 10% floor.
    const paths = seed(".go", 12, () => "package main\n");
    const sliver = writeScip(productiveScipFor([paths[0]!, paths[0]!]), "sliver.scip");
    const args = (extra: string[]) => [
      "index", repoDir, "--data-dir", dataDir, "--repo", "cov", "--branch", "main",
      "--load-scip", sliver, "--scip-language", "ts", ...extra,
    ];

    const refused = await cli(args([]));
    const refusedRec = readIndexHealth(dataDir, "cov", "main")!;
    expect(refused.code).not.toBe(0);
    expect(refusedRec.status).toBe("REFUSED");
    expect(refusedRec.failures.map((f) => f.code)).toContain("LOW_CORRESPONDENCE");

    const zeroFloor = await cli(args(["--min-coverage", "0"]));
    expect(zeroFloor.code).toBe(0);
    const rec = readIndexHealth(dataDir, "cov", "main")!;
    // NOT "HEALTHY". The run was re-evaluated at the strict default and the
    // difference is the record's whole point.
    expect(rec.status).toBe("OVERRIDDEN");
    expect(rec.override).toEqual({ flag: "--min-coverage", value: "0" });
    expect(rec.failures.map((f) => f.code)).toContain("LOW_CORRESPONDENCE");
    expect(rec.correspondence!.matched).toBe(1);
    expect(rec.correspondence!.sourceFiles).toBe(12);
  }, 180_000);
});

// ---------------------------------------------------------------------------
// UNKNOWN is the honest reading of every store indexed before this shipped.
// ---------------------------------------------------------------------------

describe("migration: an absent health file is UNKNOWN, never HEALTHY", () => {
  test("a fully populated store with no health DB reads UNKNOWN and refuses empties", async () => {
    const paths = seed(".ts", 12, (i) => `export function fn${i}() { return ${i}; }\n`);
    const good = writeScip(productiveScipFor(paths), "good.scip");
    const r = await cli([
      "index", repoDir, "--data-dir", dataDir, "--repo", "legacy", "--branch", "main",
      "--load-scip", good, "--scip-language", "ts",
    ]);
    expect(r.code).toBe(0);

    // Simulate a pre-index-fitness store: the graph is there, the record is not.
    const healthPath = join(dataDir, "index-health.sqlite");
    expect(existsSync(healthPath)).toBe(true);
    rmSync(healthPath, { force: true });
    expect(readIndexHealth(dataDir, "legacy", "main")).toBeNull();

    const store = await Store.open(dataDir, { readOnly: true });
    try {
      const answer = await graphCallers(store, { symbol: "nothing::here" });
      expect(answer.ok).toBe(false);       // UNKNOWN is not healthy
    } finally {
      await store.close();
    }

    // CONTRAST: put the record back and the identical query answers [].
    const h = IndexHealthStore.open(dataDir);
    h.write({
      repo: "legacy", branch: "main", status: "HEALTHY", run_id: "x",
      commit_sha: null, prev_commit_sha: null, started_at: "t", finished_at: "t",
      pid: null, heartbeat_at: "t", failures: [], lanes: [], contribution: null,
      fitness: null, correspondence: null, index_identities: [], override: null,
    });
    h.close();
    const store2 = await Store.open(dataDir, { readOnly: true });
    try {
      const answer = await graphCallers(store2, { symbol: "nothing::here" });
      expect(answer.ok).toBe(true);
    } finally {
      await store2.close();
    }
  }, 180_000);
});
