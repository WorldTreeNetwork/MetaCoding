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

const DATA_DIR = "./tmp-store-smoke";

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
}

function makeSymbol(id: string, short: string, kind: Symbol["kind"]): Symbol {
  return {
    id,
    kind,
    language: "ts",
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
  if (rows.length !== 1 || rows[0]?.aid !== "a" || rows[0]?.bid !== "b") {
    throw new Error(`graph round-trip unexpected: ${JSON.stringify(rows)}`);
  }
  if (rows[0]?.bline !== 99) {
    throw new Error(`MERGE did not update b.line — got ${rows[0]?.bline}`);
  }

  // FTS round-trip.
  const tokens: TokenRow[] = [
    { text: "OrderService", kind: "identifier", file: "x.ts", line: 1, col: 0, symbol_id: "b" },
    { text: "orderService", kind: "literal", file: "y.ts", line: 5, col: 12, symbol_id: null },
    { text: "find rate-limit logic", kind: "comment", file: "z.ts", line: 9, col: 0, symbol_id: null },
  ];
  s.writeTokens(tokens);

  const hits = s.searchTokens("orderService", 10);
  if (hits.length < 1) throw new Error(`FTS search returned no hits`);
  const ids = hits.map((h) => h.file).sort();
  if (!ids.includes("x.ts") && !ids.includes("y.ts")) {
    throw new Error(`FTS missed expected hits: ${JSON.stringify(hits)}`);
  }

  await s.close();

  // Confirm files landed.
  const expected = [
    `${DATA_DIR}/graph.lbug`,
    `${DATA_DIR}/tokens.fts.sqlite`,
  ];
  for (const f of expected) {
    if (!existsSync(f)) throw new Error(`expected ${f} on disk`);
  }

  console.log("STORE_SMOKE_PASS");
  cleanup();
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("STORE_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
