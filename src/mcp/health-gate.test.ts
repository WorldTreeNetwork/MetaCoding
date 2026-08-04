// PAIR 8 — READ-TIME TYPING. Bead MetaCoding-hy6.16.
//
// "The same query returning zero rows against a fit graph and against a RUNNING
//  graph must return DIFFERENT TYPES."
//
// This is the one test that would have prevented the 41-row loss. A full
// re-scoring pass was computed over a graph holding CALLS = 0 and REFERENCES = 0;
// every query answered `[]`; the pass produced numbers; the numbers were wrong
// in a way nothing downstream could see.
//
// The contrast below is deliberately constructed so that ONLY the health record
// differs: the SAME store, the SAME query, the SAME zero rows. If the two halves
// ever return the same type again, the property is gone.

import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "../store";
import { IndexHealthStore, type IndexHealthRecord } from "../store/health.ts";
import { loadScip } from "../scip/loader.ts";
import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";
import { graphCallers, graphCypher, graphDiff, graphNeighbors } from "./tools.ts";
import { summarizeHealth } from "./health-gate.ts";

const REPO = "gated";
const BRANCH = "main";
const STAMP = "2026-08-04T12:00:00.000Z";

let dataDir: string;
let store: Store;

function record(over: Partial<IndexHealthRecord>): IndexHealthRecord {
  return {
    repo: REPO, branch: BRANCH, status: "HEALTHY", run_id: STAMP,
    commit_sha: "aaaaaaa", prev_commit_sha: null,
    started_at: STAMP, finished_at: STAMP, pid: process.pid, heartbeat_at: STAMP,
    failures: [], lanes: [], contribution: null, fitness: null,
    correspondence: null, index_identities: [], override: null,
    ...over,
  };
}

function setHealth(rec: IndexHealthRecord | null): void {
  const h = IndexHealthStore.open(dataDir);
  try {
    if (rec) h.write(rec);
  } finally {
    h.close();
  }
}

/** A tiny productive index so the store has symbols to be healthy ABOUT. */
function productiveScip(): Uint8Array {
  const PKG = "scip-typescript npm fixture 1.0.0";
  const caller = `${PKG} \`src/a.ts\`/run().`;
  const callee = `${PKG} \`src/b.ts\`/helper().`;
  return new scip.Index({
    documents: [
      new scip.Document({
        relative_path: "src/a.ts", language: "typescript",
        occurrences: [
          new scip.Occurrence({ symbol: caller, range: [1, 9, 1, 12], symbol_roles: scip.SymbolRole.Definition }),
          new scip.Occurrence({ symbol: callee, range: [2, 4, 2, 10], symbol_roles: 0 }),
        ],
        symbols: [],
      }),
      new scip.Document({
        relative_path: "src/b.ts", language: "typescript",
        occurrences: [
          new scip.Occurrence({ symbol: callee, range: [1, 9, 1, 15], symbol_roles: scip.SymbolRole.Definition }),
        ],
        symbols: [],
      }),
    ],
  }).serialize();
}

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "healthgate-"));
  store = await Store.open(dataDir);
  const p = join(dataDir, "fixture.scip");
  await Bun.write(p, productiveScip());
  await loadScip(store, p, { branch: BRANCH, repo: REPO, language: "ts", indexed_at: STAMP });
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
});

describe("PAIR 8 — the same zero-row query returns DIFFERENT TYPES", () => {
  const NO_SUCH = { symbol: "does::not::exist" };

  test("fit graph -> { ok: true, rows: [] }; RUNNING graph -> a refusal with NO rows", async () => {
    // --- half A: fitness ESTABLISHED -----------------------------------------
    setHealth(record({ status: "HEALTHY" }));
    const healthy = await graphCallers(store, NO_SUCH);
    expect(healthy.ok).toBe(true);
    if (!healthy.ok) throw new Error("unreachable");
    expect(healthy.rows).toEqual([]);          // empty-from-healthy stays []

    // --- half B: the SAME query, the SAME store, a RUNNING record ------------
    setHealth(record({ status: "RUNNING", finished_at: null }));
    const running = await graphCallers(store, NO_SUCH);
    expect(running.ok).toBe(false);
    if (running.ok) throw new Error("unreachable");
    expect(running.error).toBe("INDEX_FITNESS_UNESTABLISHED");

    // THE ASSERTION THAT IS THE POINT: the refusal has no `rows` at all, so a
    // consumer written as `answer.rows.map(...)` — the hy6.16 rescore — throws
    // on row 1 instead of writing 41 wrong rows.
    expect("rows" in running).toBe(false);
    expect("rows" in healthy).toBe(true);
    expect(typeof (healthy as { rows?: unknown }).rows).not.toBe(
      typeof (running as { rows?: unknown }).rows,
    );
  });

  test("REFUSED and UNKNOWN are unestablished too; OVERRIDDEN is established-with-a-caveat", async () => {
    for (const status of ["REFUSED", "RUNNING"] as const) {
      setHealth(record({ status }));
      const r = await graphCallers(store, NO_SUCH);
      expect(r.ok).toBe(false);
    }

    // UNKNOWN: no health DB at all — every store indexed before this shipped.
    rmSync(join(dataDir, "index-health.sqlite"), { force: true });
    const unknown = await graphCallers(store, NO_SUCH);
    expect(unknown.ok).toBe(false);
    if (unknown.ok) throw new Error("unreachable");
    expect(unknown.health.unestablished[0]!.status).toBe("UNKNOWN");

    // OVERRIDDEN: an operator waived a refusal. The answer comes back, and the
    // waiver is visible at read time forever.
    setHealth(record({ status: "OVERRIDDEN", override: { flag: "--allow-empty-index", value: "true" } }));
    const overridden = await graphCallers(store, NO_SUCH);
    expect(overridden.ok).toBe(true);
  });

  test("a NON-EMPTY answer is never refused — it carries a caveat instead", async () => {
    setHealth(record({ status: "RUNNING" }));
    const rows = await store.query<{ id: string }>(
      `MATCH (s:Symbol) WHERE s.repo = $repo RETURN s.id AS id LIMIT 1`, { repo: REPO },
    );
    const real = await graphNeighbors(store, { symbol: rows[0]!.id, direction: "both" });
    // Real data is real data. A gate that swallowed it would be turned off.
    expect(real.ok).toBe(true);
    if (!real.ok) throw new Error("unreachable");
    expect(real.rows.length).toBeGreaterThan(0);
    expect(real.caveat).toContain("not established");

    // CONTRAST: the same tool, the same store, a symbol with no neighbours.
    const empty = await graphNeighbors(store, { symbol: "no-such-symbol" });
    expect(empty.ok).toBe(false);
  });

  test("graph_cypher — the escape hatch is gated too", async () => {
    setHealth(record({ status: "HEALTHY" }));
    const ok = await graphCypher(store, { cypher: `MATCH (s:Symbol) WHERE s.repo = 'nope' RETURN s.id AS id` });
    expect(ok.ok).toBe(true);
    setHealth(record({ status: "REFUSED" }));
    const refused = await graphCypher(store, { cypher: `MATCH (s:Symbol) WHERE s.repo = 'nope' RETURN s.id AS id` });
    expect(refused.ok).toBe(false);
  });
});

describe("AGGREGATING consumers refuse by default, empty or not", () => {
  // "An aggregate silently absorbs a zero, and hy6.16 WAS an aggregate."
  test("graph_diff refuses on RUNNING even though it would have returned data", async () => {
    setHealth(record({ status: "HEALTHY" }));
    const healthy = await graphDiff(store, { repo: REPO, from_sha: "a", to_sha: "b" });
    expect(healthy.ok).toBe(true);

    setHealth(record({ status: "RUNNING" }));
    const running = await graphDiff(store, { repo: REPO, from_sha: "a", to_sha: "b" });
    expect(running.ok).toBe(false);
    if (running.ok) throw new Error("unreachable");
    expect(running.message).toContain("AGGREGATING");
    expect("result" in running).toBe(false);

    // ...and the explicit acknowledgment gets the data back, with the caveat
    // recorded in the response rather than in someone's memory.
    const acked = await graphDiff(store, {
      repo: REPO, from_sha: "a", to_sha: "b", acknowledge_unestablished_fitness: true,
    });
    expect(acked.ok).toBe(true);
    if (!acked.ok) throw new Error("unreachable");
    expect(acked.caveat).toContain("UNESTABLISHED");
  });
});

describe("summarizeHealth", () => {
  test("a store holding TWO repos reports each slice separately", async () => {
    const p = join(dataDir, "second.scip");
    await Bun.write(p, productiveScip());
    await loadScip(store, p, { branch: BRANCH, repo: "second", language: "ts", indexed_at: STAMP });
    setHealth(record({ status: "HEALTHY" })); // only `gated` has a record

    const h = await summarizeHealth(store);
    expect(h.slices.length).toBeGreaterThanOrEqual(2);
    expect(h.established).toBe(false);
    // The repo WITHOUT a record is the unestablished one — a healthy sibling
    // in a shared corpus cannot vouch for it.
    expect(h.unestablished.map((s) => s.repo)).toContain("second");
    expect(h.unestablished.map((s) => s.repo)).not.toContain(REPO);
  });

  test("a RUNNING record whose pid is gone is reported ABANDONED", async () => {
    // pid 0x7FFFFFFF is not a live process; process.pid is.
    setHealth(record({ status: "RUNNING", pid: 0x7ffffffe }));
    const dead = await summarizeHealth(store);
    expect(dead.slices.find((s) => s.repo === REPO)?.abandoned).toBe(true);

    setHealth(record({ status: "RUNNING", pid: process.pid }));
    const alive = await summarizeHealth(store);
    expect(alive.slices.find((s) => s.repo === REPO)?.abandoned).toBeUndefined();
    // Both are unestablished; only the REASON differs. A marker that cannot
    // tell "running now" from "died" is a marker users learn to ignore.
    expect(dead.established).toBe(false);
    expect(alive.established).toBe(false);
  });
});
