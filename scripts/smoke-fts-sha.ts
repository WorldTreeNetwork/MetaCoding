// scripts/smoke-fts-sha.ts
//
// Smoke test for MetaCoding-pon: FTS5 tokens table now has a repo_commit_sha
// column; writeTokens persists it; searchTokens can filter by it.
//
// Inserts a handful of tokens against two synthetic shas in one store, then
// exercises the sha filter via the Store API and via the codeSearch MCP tool.

import { existsSync, rmSync } from "node:fs";

import { Store } from "../src/store";
// Smoke scripts use the RAW rows, not the fitness-gated tool surface.
import { codeSearchRows } from "../src/mcp/tools";
import type { TokenRow } from "../src/store/types";
import { beginRun, type Floor } from "../src/testkit/floors.ts";

// Every check is COUNTED (src/testkit/floors.ts): the count is derived from
// the calls that run, so a deleted assertion is visible instead of silent.
const run = beginRun("fts-sha");

const FLOORS: Floor[] = [
  {
    min: 7,
    measuredAs: "checks",
    why: "counted from the source: 7 assertion sites across the 4 numbered scenarios (sha=aaa: 2, sha=bbb: 2, unscoped: 1, absent sha: 1, codeSearch end-to-end: 1)",
  },
];

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
    run.check("sha=aaa returns exactly 1 Foo hit", aaaHits.length === 1, `got ${aaaHits.length}`);
    run.check("sha=aaa hit is Foo_in_aaa", aaaHits[0]!.text === "Foo_in_aaa", `got ${aaaHits[0]!.text}`);
    console.log(`store.searchTokens sha=aaa OK: ${aaaHits[0]!.text}`);

    const bbbHits = store.searchTokens("Foo", 10, undefined, "bbb");
    run.check("sha=bbb returns exactly 1 Foo hit", bbbHits.length === 1, `got ${bbbHits.length}`);
    run.check("sha=bbb hit is Foo_in_bbb", bbbHits[0]!.text === "Foo_in_bbb", `got ${JSON.stringify(bbbHits)}`);
    console.log(`store.searchTokens sha=bbb OK: ${bbbHits[0]!.text}`);

    // 2. No sha filter — both snapshots returned.
    const allHits = store.searchTokens("Foo", 10);
    run.check("unscoped returns both snapshots", allHits.length === 2, `got ${allHits.length}`);
    console.log(`store.searchTokens unscoped OK: ${allHits.length} hits`);

    // 3. Non-existent sha — empty.
    const emptyHits = store.searchTokens("Foo", 10, undefined, "ccc");
    run.check("absent sha=ccc returns 0 hits", emptyHits.length === 0, `got ${emptyHits.length}`);
    console.log(`store.searchTokens sha=ccc (absent) OK: 0 hits`);

    // 4. Via codeSearch MCP tool — sha filter end-to-end.
    const csHits = codeSearchRows(store, { query: "Bar", repo_commit_sha: "aaa", limit: 10 });
    run.check(
      "codeSearch applies the sha filter end-to-end",
      csHits.length === 1 && csHits[0]!.text === "Bar_in_aaa",
      `got ${JSON.stringify(csHits)}`,
    );
    console.log(`codeSearch sha=aaa OK: ${csHits[0]!.text}`);

    run.finish(FLOORS);
  } finally {
    await store.close();
    cleanup();
  }
}

main().catch((err) => {
  console.error("FTS_SHA_SMOKE_FAIL:", err?.message ?? err);
  process.exit(1);
});
