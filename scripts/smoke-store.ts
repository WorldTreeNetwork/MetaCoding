// scripts/smoke-store.ts
//
// Validates the Store wrapper end-to-end:
//  - Opens both ladybugdb (.lbug) and SQLite FTS5 in one data dir.
//  - Idempotent schema init (run twice, second run is a no-op).
//  - upsertSymbol / addEdge / writeTokens / searchTokens round-trip.
//  - Clean close, no segfault.
//
// Run with: bun run scripts/smoke-store.ts

import { existsSync, rmSync } from "node:fs";
import { Store } from "../src/store";
import type { Symbol, TokenRow } from "../src/store/types";
import { beginRun, type Floor } from "../src/testkit/floors.ts";

// Every check is COUNTED (src/testkit/floors.ts): the count is derived from
// the calls that run, so a deleted assertion is visible instead of silent.
const run = beginRun("store");

const FLOORS: Floor[] = [
  {
    min: 6,
    measuredAs: "checks",
    why: "counted from the source: 6 assertion sites - graph round-trip, MERGE updated b.line, FTS returned hits, FTS hit the expected files, and 2 on-disk files",
  },
];

const DATA_DIR = "./tmp-store-smoke";

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
}

function makeSymbol(id: string, short: string, kind: Symbol["kind"]): Symbol {
  return {
    id,
    kind,
    language: "ts",
    repo: "smoke",
    qualified_name: `pkg.${short}`,
    short_name: short,
    file: "src/example.ts",
    line: 10,
    col: 0,
    end_line: 20,
    end_col: 0,
    signature: null,
    visibility: "public",
    is_abstract: false,
    is_static: false,
    ast_hash: null,
    branch: "main",
    source: "tree_sitter",
  };
}

async function main(): Promise<void> {
  cleanup();

  // First open creates schema.
  const s = await Store.open(DATA_DIR);

  // Second open hits idempotent path — must not throw.
  const s2 = await Store.open(DATA_DIR);
  await s2.close();

  // Insert two symbols and a CONTAINS edge between them.
  const a = makeSymbol("a", "FileExample", "file");
  const b = makeSymbol("b", "ClassA", "class");
  await s.upsertSymbol(a);
  await s.upsertSymbol(b);
  await s.addEdge({ src_id: "a", dst_id: "b", kind: "CONTAINS" });

  // Re-upsert b to confirm MERGE behaviour (no duplicates).
  await s.upsertSymbol({ ...b, line: 99 });

  const rows = await s.query<{ aid: string; bid: string; bline: number }>(
    `MATCH (a:Symbol)-[:CONTAINS]->(b:Symbol)
     RETURN a.id AS aid, b.id AS bid, b.line AS bline`,
  );
  run.check(
    "CONTAINS round-trips a->b",
    rows.length === 1 && rows[0]?.aid === "a" && rows[0]?.bid === "b",
    `got ${JSON.stringify(rows)}`,
  );
  run.check("MERGE updated b.line to 99", rows[0]?.bline === 99, `got ${rows[0]?.bline}`);

  // FTS round-trip.
  const tokens: TokenRow[] = [
    { text: "OrderService", kind: "identifier", repo: "smoke", file: "x.ts", line: 1, col: 0, symbol_id: "b" },
    { text: "orderService", kind: "literal", repo: "smoke", file: "y.ts", line: 5, col: 12, symbol_id: null },
    { text: "find rate-limit logic", kind: "comment", repo: "smoke", file: "z.ts", line: 9, col: 0, symbol_id: null },
  ];
  s.writeTokens(tokens);

  const hits = s.searchTokens("orderService", 10);
  run.check("FTS search returns at least one hit", hits.length >= 1, "got none");
  const ids = hits.map((h) => h.file).sort();
  run.check(
    "FTS hit x.ts or y.ts",
    ids.includes("x.ts") || ids.includes("y.ts"),
    `got ${JSON.stringify(hits)}`,
  );

  await s.close();

  // Confirm files landed.
  const expected = [
    `${DATA_DIR}/graph.lbug`,
    `${DATA_DIR}/tokens.fts.sqlite`,
  ];
  for (const f of expected) {
    run.check(`${f} landed on disk`, existsSync(f), "missing");
  }

  run.finish(FLOORS);
  cleanup();
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("STORE_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
