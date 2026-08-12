// scripts/smoke-extractor.ts
//
// End-to-end smoke for the Tree-sitter extractor:
//  - Index this very repo's src/ directory (eat our own dogfood).
//  - Verify a handful of expected Symbols landed in the graph.
//  - Verify FTS finds known identifiers.
//
// Run with: bun run scripts/smoke-extractor.ts

import { existsSync, rmSync } from "node:fs";
import { join } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor/walker.ts";
import { issueIngestTicket, revokeIngestTicket } from "../src/ingest/ticket.ts";

// Absolute, both of them. Relative paths here resolve against the CALLER's cwd,
// so the script worked from the repo root and died with ENOENT from anywhere
// else — including from a mutation sandbox, which is where instruments get run
// when someone is checking whether they can fail. Same cwd-assumption family as
// MetaCoding-hy6.52.
const REPO_ROOT = join(import.meta.dir, "..");
const SRC_DIR = join(REPO_ROOT, "src");
const DATA_DIR = join(REPO_ROOT, "tmp-extractor-smoke");

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
}

async function main(): Promise<void> {
  cleanup();
  const store = await Store.open(DATA_DIR);

  // THE SEAM IS A CAPABILITY, AND THIS SCRIPT DID NOT HAVE IT (MetaCoding-6ep).
  // The comment this replaces said "reaches past the ingest seam on purpose (raw
  // primitive)" — which stopped being possible at 037926f, when MetaCoding-9ed
  // turned the seam from a scan into a capability and `indexDirectory` grew a
  // required `opts` carrying a ticket. The script kept calling it with two
  // arguments, so it died on `opts.branch` of undefined and took the whole smoke
  // suite with it: `bun run smoke` fails fast, and only 2 of 22 scripts ever ran.
  //
  // The old comment is the interesting part. A script that declares it is
  // deliberately bypassing a guard is a script that will be broken by the guard
  // becoming real, silently, and stay broken — this one did, for long enough to
  // be the standing "known baseline red" under several other changes.
  const ticket = issueIngestTicket({
    repo: "metacoding-smoke",
    branch: "main",
    runStamp: new Date().toISOString(),
  });

  try {
    const stats = await indexDirectory(store, SRC_DIR, {
      ticket,
      repo: "metacoding-smoke",
      branch: "main",
    });
    console.log(`indexed: ${JSON.stringify(stats)}`);

    if (stats.filesScanned === 0) {
      throw new Error(`no .ts files found under ${SRC_DIR}`);
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
