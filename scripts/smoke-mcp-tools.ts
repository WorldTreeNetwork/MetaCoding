// scripts/smoke-mcp-tools.ts
//
// Validates the MCP tool implementations against a real indexed Store.
// Runs them as plain functions (no MCP transport) — server.ts is a thin
// adapter, so if the tools work, the MCP wiring works.
//
// Run with: bun run scripts/smoke-mcp-tools.ts

import { existsSync, rmSync } from "node:fs";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";
import {
  graphNeighbors,
  codeSearch,
  graphCypher,
  describeApi,
} from "../src/mcp/tools";

const DATA_DIR = "./tmp-mcp-smoke";

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
}

async function main(): Promise<void> {
  cleanup();
  const store = await Store.open(DATA_DIR);

  try {
    await indexDirectory(store, "src");

    // 1. describe_api returns all twenty-two tools (6 graph/text + 4 LSP + 1
    // describe_api + 11 CTKR).
    const desc = describeApi();
    const names = desc.tools.map((t) => t.name).sort();
    const expected = [
      "code_search",
      "ctkr.centrality_query",
      "ctkr.composition_rules",
      "ctkr.functor_between",
      "ctkr.interface_of",
      "ctkr.motif_search",
      "ctkr.nearest_symbols",
      "ctkr.pattern_search",
      "ctkr.role_equivalent",
      "ctkr.shape_distance",
      "ctkr.subsystem_card",
      "ctkr.subsystems",
      "describe_api",
      "graph_callers",
      "graph_cypher",
      "graph_diff",
      "graph_implementers",
      "graph_neighbors",
      "lsp_definition",
      "lsp_diagnostics",
      "lsp_hover",
      "lsp_references",
    ];
    if (JSON.stringify(names) !== JSON.stringify(expected)) {
      throw new Error(`tool names mismatch: got ${JSON.stringify(names)}`);
    }

    // 2. graph_neighbors on the Store class -> its methods.
    const storeRows = await store.query<{ id: string }>(
      `MATCH (s:Symbol) WHERE s.short_name = 'Store' AND s.kind = 'class' RETURN s.id AS id LIMIT 1`,
    );
    const storeId = storeRows[0]?.id;
    if (!storeId) throw new Error("Store class not found in index");

    const neighbors = await graphNeighbors(store, { symbol: storeId, direction: "out" });
    const neighborMethods = neighbors
      .filter((n) => n.symbol.kind === "method")
      .map((n) => n.symbol.short_name)
      .sort();
    for (const want of ["open", "close", "query", "upsertSymbol", "addEdge"]) {
      if (!neighborMethods.includes(want)) {
        throw new Error(`graph_neighbors missed ${want}: ${JSON.stringify(neighborMethods)}`);
      }
    }

    // 3. graph_neighbors also works via qualified_name (resolveSymbol path).
    // File paths are relative to the indexed root ("src"), so Store's qn is "store/index.ts::Store".
    const byQn = await graphNeighbors(store, {
      symbol: "store/index.ts::Store",
      direction: "out",
      limit: 50,
    });
    if (byQn.length === 0) throw new Error("qualified_name resolution failed");

    // 4. code_search returns hits.
    const hits = codeSearch(store, { query: "Store", limit: 20 });
    if (hits.length === 0) throw new Error("code_search returned 0 hits for 'Store'");

    // 5. code_search with kind filter returns only that kind.
    const idHits = codeSearch(store, { query: "Store", kind: "identifier", limit: 50 });
    if (!idHits.every((h) => h.kind === "identifier")) {
      throw new Error("code_search kind filter leaked non-identifier rows");
    }

    // 6. graph_cypher escape hatch works.
    const cypherRows = await graphCypher(store, {
      cypher: `MATCH (s:Symbol) WHERE s.kind = 'class' RETURN s.short_name AS name ORDER BY name`,
    });
    if (cypherRows.length === 0) throw new Error("graph_cypher returned no classes");

    console.log(`describe_api: ${desc.tools.length} tools`);
    console.log(`graph_neighbors(Store, out) -> ${neighbors.length} rows`);
    console.log(`code_search('Store') -> ${hits.length} hits`);
    console.log(`graph_cypher classes -> ${cypherRows.length} rows`);
    console.log("MCP_TOOLS_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("MCP_TOOLS_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
