// scripts/smoke-extractor.ts
//
// End-to-end smoke for the Tree-sitter extractor:
//  - Index this very repo's src/ directory (eat our own dogfood).
//  - Verify a handful of expected Symbols landed in the graph.
//  - Verify FTS finds known identifiers.
//
// Run with: bun run scripts/smoke-extractor.ts

import { existsSync, rmSync } from "node:fs";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";

const DATA_DIR = "./tmp-extractor-smoke";

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
}

async function main(): Promise<void> {
  cleanup();
  const store = await Store.open(DATA_DIR);

  try {
    const stats = await indexDirectory(store, "src");
    console.log(`indexed: ${JSON.stringify(stats)}`);

    if (stats.filesScanned === 0) {
      throw new Error("no .ts files found under src/");
    }

    // 1. The Store class itself should be in the graph.
    const storeRows = await store.query<{ qn: string; kind: string }>(
      `MATCH (s:Symbol)
       WHERE s.short_name = 'Store' AND s.kind = 'class'
       RETURN s.qualified_name AS qn, s.kind AS kind`,
    );
    if (storeRows.length === 0) {
      throw new Error(`expected a Store class symbol; got none`);
    }

    // 2. The class should CONTAIN the upsertSymbol method.
    const methodRows = await store.query<{ method: string }>(
      `MATCH (c:Symbol {kind: 'class', short_name: 'Store'})
              -[:CONTAINS]->(m:Symbol {kind: 'method'})
       RETURN m.short_name AS method
       ORDER BY method`,
    );
    const methods = methodRows.map((r) => r.method);
    for (const expected of ["open", "close", "query", "upsertSymbol", "addEdge"]) {
      if (!methods.includes(expected)) {
        throw new Error(`expected method ${expected} in Store; got ${JSON.stringify(methods)}`);
      }
    }

    // 3. FTS should find the class name.
    const ftsHits = store.searchTokens("Store", 50);
    if (ftsHits.length === 0) {
      throw new Error("FTS returned no hits for 'Store'");
    }

    console.log(
      `extracted ${stats.symbols} symbols, ${stats.edges} edges, ${stats.tokens} tokens`,
    );
    console.log(`Store class methods found: ${methods.join(", ")}`);
    console.log(`FTS hits for 'Store': ${ftsHits.length}`);
    console.log("EXTRACTOR_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("EXTRACTOR_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
