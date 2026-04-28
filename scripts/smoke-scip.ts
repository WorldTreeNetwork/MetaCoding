// scripts/smoke-scip.ts
//
// End-to-end smoke for the SCIP lane:
//  - Index this repo's src/ directory with Tree-sitter (current behaviour).
//  - Run scip-typescript on this repo, load the .scip file.
//  - Verify SCIP overwrote/added Symbol nodes with source='scip'.
//  - Verify REFERENCES edges exist between distinct files (cross-file
//    resolution, the thing Tree-sitter alone cannot do).
//  - Verify graph_callers wakes up: a Store.upsertSymbol caller should be
//    pointed at by something in the extractor walker.
//
// Run with: bun run scripts/smoke-scip.ts

import { existsSync, rmSync } from "node:fs";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";
import { runScipTypescript, loadScip } from "../src/scip";
import { graphCallers } from "../src/mcp/tools";

const DATA_DIR = "./tmp-scip-smoke";
const SCIP_OUT = "./tmp-scip-smoke.scip";

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
  if (existsSync(SCIP_OUT)) rmSync(SCIP_OUT, { force: true });
}

async function main(): Promise<void> {
  cleanup();
  const store = await Store.open(DATA_DIR);

  try {
    // Lane 1: Tree-sitter pass — walk from project root so file paths
    // (`src/store/index.ts`) align with SCIP's project-root-relative paths.
    const tsStats = await indexDirectory(store, ".");
    console.log(`tree-sitter: ${tsStats.symbols} symbols, ${tsStats.edges} edges`);

    // Lane 2: SCIP pass.
    const { scipPath, durationMs: scipMs } = await runScipTypescript({
      targetRepo: ".",
      output: SCIP_OUT,
    });
    console.log(`scip-typescript: produced ${scipPath} in ${Math.round(scipMs)}ms`);

    const scipStats = await loadScip(store, scipPath, { branch: "main" });
    console.log(
      `scip load: ${scipStats.documents} docs, ${scipStats.symbolsUpserted} upserts, ${scipStats.edgesAdded} edges, ${scipStats.externalRefsSkipped} external refs skipped`,
    );

    // 1. Some Symbol nodes should now have source='scip'.
    const scipNodes = await store.query<{ n: number }>(
      `MATCH (s:Symbol) WHERE s.source = 'scip' RETURN COUNT(s) AS n`,
    );
    if ((scipNodes[0]?.n ?? 0) === 0) {
      throw new Error("no SCIP-sourced Symbol nodes after load");
    }

    // 2. REFERENCES edges exist.
    const refEdges = await store.query<{ n: number }>(
      `MATCH ()-[r:REFERENCES]->() RETURN COUNT(r) AS n`,
    );
    if ((refEdges[0]?.n ?? 0) === 0) {
      throw new Error("no REFERENCES edges after SCIP load");
    }

    // 3. At least one REFERENCES edge crosses file boundaries.
    const crossFile = await store.query<{ n: number }>(
      `MATCH (a:Symbol)-[:REFERENCES]->(b:Symbol)
       WHERE a.file <> b.file
       RETURN COUNT(*) AS n`,
    );
    if ((crossFile[0]?.n ?? 0) === 0) {
      throw new Error("no cross-file REFERENCES edges — SCIP didn't resolve");
    }

    // 4. graph_callers wakes up. Pick a method we know is referenced
    // across files — Store.upsertSymbol is called from the extractor.
    const callers = await graphCallers(store, {
      symbol: "src/store/index.ts::Store::upsertSymbol",
      limit: 20,
    });
    if (callers.length === 0) {
      // Fall back: confirm Cypher sees an incoming edge to upsertSymbol.
      const probe = await store.query<{ qn: string }>(
        `MATCH (a:Symbol)-[:REFERENCES]->(b:Symbol)
         WHERE b.short_name = 'upsertSymbol'
         RETURN b.qualified_name AS qn LIMIT 1`,
      );
      throw new Error(
        `graph_callers(upsertSymbol) empty; cypher probe found qn=${probe[0]?.qn ?? "<none>"}`,
      );
    }
    console.log(`graph_callers(Store.upsertSymbol) -> ${callers.length} rows`);

    // 5. Sanity: total symbol/edge counts after both lanes.
    const totals = await store.query<{
      symbols: number;
      edges: number;
    }>(
      `MATCH (s:Symbol) WITH COUNT(s) AS symbols
       MATCH ()-[r]->() RETURN symbols, COUNT(r) AS edges`,
    );
    console.log(
      `total: ${totals[0]?.symbols ?? 0} symbols, ${totals[0]?.edges ?? 0} edges`,
    );

    console.log("SCIP_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("SCIP_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
