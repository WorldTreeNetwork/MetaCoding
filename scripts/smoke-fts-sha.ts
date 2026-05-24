// scripts/smoke-fts-sha.ts
//
// Smoke test for MetaCoding-pon: FTS5 tokens table now has a repo_commit_sha
// column; writeTokens persists it; searchTokens can filter by it.
//
// Inserts a handful of tokens against two synthetic shas in one store, then
// exercises the sha filter via the Store API and via the codeSearch MCP tool.

import { existsSync, rmSync } from "node:fs";

import { Store } from "../src/store";
import { codeSearch } from "../src/mcp/tools";
import type { TokenRow } from "../src/store/types";

const TMP_DATA = "./tmp-fts-sha-smoke-data";

function cleanup(): void {
  if (existsSync(TMP_DATA)) rmSync(TMP_DATA, { recursive: true, force: true });
}

function tokens(sha: string, identifiers: string[]): TokenRow[] {
  return identifiers.map((id, i) => ({
    text: id,
    kind: "identifier" as const,
    repo: "test",
    file: "test.ts",
    line: i,
    col: 0,
    symbol_id: null,
    repo_commit_sha: sha,
  }));
}

async function main(): Promise<void> {
  cleanup();
  const store = await Store.open(TMP_DATA);
  try {
    store.writeTokens(tokens("aaa", ["Foo_in_aaa", "Bar_in_aaa"]));
    store.writeTokens(tokens("bbb", ["Foo_in_bbb", "Bar_in_bbb"]));

    // 1. Direct Store API — sha filter.
    const aaaHits = store.searchTokens("Foo", 10, undefined, "aaa");
    if (aaaHits.length !== 1) throw new Error(`expected 1 Foo hit in sha=aaa, got ${aaaHits.length}`);
    if (aaaHits[0]!.text !== "Foo_in_aaa") {
      throw new Error(`expected Foo_in_aaa, got ${aaaHits[0]!.text}`);
    }
    console.log(`store.searchTokens sha=aaa OK: ${aaaHits[0]!.text}`);

    const bbbHits = store.searchTokens("Foo", 10, undefined, "bbb");
    if (bbbHits.length !== 1 || bbbHits[0]!.text !== "Foo_in_bbb") {
      throw new Error(`unexpected bbb result: ${JSON.stringify(bbbHits)}`);
    }
    console.log(`store.searchTokens sha=bbb OK: ${bbbHits[0]!.text}`);

    // 2. No sha filter — both snapshots returned.
    const allHits = store.searchTokens("Foo", 10);
    if (allHits.length !== 2) throw new Error(`expected 2 unscoped Foo hits, got ${allHits.length}`);
    console.log(`store.searchTokens unscoped OK: ${allHits.length} hits`);

    // 3. Non-existent sha — empty.
    const emptyHits = store.searchTokens("Foo", 10, undefined, "ccc");
    if (emptyHits.length !== 0) throw new Error(`expected 0 hits for sha=ccc, got ${emptyHits.length}`);
    console.log(`store.searchTokens sha=ccc (absent) OK: 0 hits`);

    // 4. Via codeSearch MCP tool — sha filter end-to-end.
    const csHits = codeSearch(store, { query: "Bar", repo_commit_sha: "aaa", limit: 10 });
    if (csHits.length !== 1 || csHits[0]!.text !== "Bar_in_aaa") {
      throw new Error(`codeSearch sha filter failed: ${JSON.stringify(csHits)}`);
    }
    console.log(`codeSearch sha=aaa OK: ${csHits[0]!.text}`);

    console.log("FTS_SHA_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main().catch((err) => {
  console.error("FTS_SHA_SMOKE_FAIL:", err?.message ?? err);
  process.exit(1);
});
