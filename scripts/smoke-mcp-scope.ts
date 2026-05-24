// scripts/smoke-mcp-scope.ts
//
// Smoke test for MetaCoding-wxt: optional repo_commit_sha filter on MCP tools.
//
// Constructs a synthetic store with two "snapshots" of the same logical graph
// (two pairs of Symbol rows that share qualified_names but have distinct ids
// and distinct repo_commit_sha values) plus one CONTAINS edge per snapshot.
// Verifies that graphNeighbors/Callers/Implementers correctly scope to the
// requested sha.
//
// This bypasses the indexer: it writes rows directly via the Store so we can
// test the filter without depending on bead izn (--per-commit-identity).

import { existsSync, rmSync } from "node:fs";

import { Store } from "../src/store";
import { graphNeighbors } from "../src/mcp/tools";
import type { Symbol } from "../src/store/types";

const TMP_DATA = "./tmp-mcp-scope-smoke-data";

function cleanup(): void {
  if (existsSync(TMP_DATA)) rmSync(TMP_DATA, { recursive: true, force: true });
}

function symbol(id: string, qn: string, sha: string, kind: Symbol["kind"]): Symbol {
  return {
    id,
    kind,
    language: "ts",
    repo: "test",
    qualified_name: qn,
    short_name: qn,
    file: "test.ts",
    line: 0,
    col: 0,
    end_line: 0,
    end_col: 0,
    signature: null,
    visibility: null,
    is_abstract: false,
    is_static: false,
    ast_hash: null,
    branch: "main",
    source: "tree_sitter",
    repo_commit_sha: sha,
    indexed_at: new Date().toISOString(),
  };
}

async function main(): Promise<void> {
  cleanup();
  const store = await Store.open(TMP_DATA);
  try {
    // Two snapshots of the same logical (foo -> bar) graph: shas "aaa" and "bbb".
    await store.upsertSymbol(symbol("aA-aaa", "foo", "aaa", "function"));
    await store.upsertSymbol(symbol("bB-aaa", "bar", "aaa", "function"));
    await store.upsertSymbol(symbol("aA-bbb", "foo", "bbb", "function"));
    await store.upsertSymbol(symbol("bB-bbb", "bar", "bbb", "function"));
    await store.addEdge({ src_id: "aA-aaa", dst_id: "bB-aaa", kind: "CONTAINS" });
    await store.addEdge({ src_id: "aA-bbb", dst_id: "bB-bbb", kind: "CONTAINS" });

    // 1. Scoped to sha=aaa — should return only bB-aaa.
    const aaa = await graphNeighbors(store, {
      symbol: "foo",
      direction: "out",
      edge_kinds: ["CONTAINS"],
      repo_commit_sha: "aaa",
    });
    if (aaa.length !== 1) throw new Error(`expected 1 result for sha=aaa, got ${aaa.length}`);
    if (aaa[0]!.symbol.id !== "bB-aaa") {
      throw new Error(`expected bB-aaa, got ${aaa[0]!.symbol.id}`);
    }
    console.log(`sha=aaa scope OK: ${aaa[0]!.symbol.id}`);

    // 2. Scoped to sha=bbb — should return only bB-bbb.
    const bbb = await graphNeighbors(store, {
      symbol: "foo",
      direction: "out",
      edge_kinds: ["CONTAINS"],
      repo_commit_sha: "bbb",
    });
    if (bbb.length !== 1) throw new Error(`expected 1 result for sha=bbb, got ${bbb.length}`);
    if (bbb[0]!.symbol.id !== "bB-bbb") {
      throw new Error(`expected bB-bbb, got ${bbb[0]!.symbol.id}`);
    }
    console.log(`sha=bbb scope OK: ${bbb[0]!.symbol.id}`);

    // 3. No scope — resolveSymbol arbitrarily picks one snapshot via LIMIT 1.
    //    Verify the call returns one valid neighbor of either snapshot.
    const unscoped = await graphNeighbors(store, {
      symbol: "foo",
      direction: "out",
      edge_kinds: ["CONTAINS"],
    });
    if (unscoped.length !== 1) {
      throw new Error(`expected 1 result for unscoped, got ${unscoped.length}`);
    }
    const id = unscoped[0]!.symbol.id;
    if (id !== "bB-aaa" && id !== "bB-bbb") {
      throw new Error(`unscoped returned unexpected id: ${id}`);
    }
    console.log(`unscoped OK: ${id}`);

    // 4. Scoped to a non-existent sha — empty result.
    const empty = await graphNeighbors(store, {
      symbol: "foo",
      direction: "out",
      edge_kinds: ["CONTAINS"],
      repo_commit_sha: "ccc",
    });
    if (empty.length !== 0) {
      throw new Error(`expected 0 results for sha=ccc, got ${empty.length}`);
    }
    console.log(`sha=ccc (absent) OK: 0 results`);

    console.log("MCP_SCOPE_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main().catch((err) => {
  console.error("MCP_SCOPE_SMOKE_FAIL:", err?.message ?? err);
  process.exit(1);
});
