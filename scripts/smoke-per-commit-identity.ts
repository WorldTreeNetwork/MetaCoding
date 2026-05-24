// scripts/smoke-per-commit-identity.ts
//
// Smoke test for MetaCoding-izn: --per-commit-identity flag folds repo_commit_sha
// into Symbol.id so two indexes of different commits coexist in one DB.
//
// Procedure:
//   1. Init a git repo, write hello.ts with a `hello` function, commit -> sha A.
//   2. Index with perCommitIdentity=true.
//   3. Mutate hello.ts (change the body), commit -> sha B.
//   4. Re-index with perCommitIdentity=true.
//   5. Assert TWO Symbol rows exist for qualified_name "hello.ts::hello", one per sha.
//   6. Drop the data dir, index again with perCommitIdentity=false (default), twice.
//   7. Assert only ONE row survives (overwrite semantics).

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";

const TMP_REPO = "./tmp-pci-smoke-repo";
const TMP_DATA = "./tmp-pci-smoke-data";

function cleanup(): void {
  for (const d of [TMP_REPO, TMP_DATA]) {
    if (existsSync(d)) rmSync(d, { recursive: true, force: true });
  }
}

async function initRepo(): Promise<void> {
  mkdirSync(TMP_REPO, { recursive: true });
  await Bun.$`git -C ${TMP_REPO} init -b main`.quiet();
  await Bun.$`git -C ${TMP_REPO} config user.email "smoke@test.local"`.quiet();
  await Bun.$`git -C ${TMP_REPO} config user.name "Smoke Test"`.quiet();
}

async function commit(content: string, message: string): Promise<string> {
  writeFileSync(join(TMP_REPO, "hello.ts"), content);
  await Bun.$`git -C ${TMP_REPO} add hello.ts`.quiet();
  await Bun.$`git -C ${TMP_REPO} commit -m ${message}`.quiet();
  return (await Bun.$`git -C ${TMP_REPO} rev-parse HEAD`.quiet()).stdout.toString().trim();
}

async function countHelloRows(store: Store): Promise<Array<{ id: string; sha: string | null }>> {
  return store.query<{ id: string; sha: string | null }>(
    `MATCH (s:Symbol)
     WHERE s.qualified_name = $qn
     RETURN s.id AS id, s.repo_commit_sha AS sha`,
    { qn: "hello.ts::hello" },
  );
}

async function main(): Promise<void> {
  cleanup();
  await initRepo();

  // --- perCommitIdentity: true ---
  const shaA = await commit(
    `export function hello(): string { return "A"; }\n`,
    "first",
  );
  let store = await Store.open(TMP_DATA);
  await indexDirectory(store, TMP_REPO, {
    repo: "pci-test",
    branch: "main",
    repo_commit_sha: shaA,
    indexed_at: new Date().toISOString(),
    perCommitIdentity: true,
  });

  const shaB = await commit(
    `export function hello(): string { return "B"; }\n`,
    "second",
  );
  await indexDirectory(store, TMP_REPO, {
    repo: "pci-test",
    branch: "main",
    repo_commit_sha: shaB,
    indexed_at: new Date().toISOString(),
    perCommitIdentity: true,
  });

  const rowsOn = await countHelloRows(store);
  await store.close();
  console.log(`perCommitIdentity=true rows: ${rowsOn.length}`);
  if (rowsOn.length !== 2) {
    throw new Error(`expected 2 rows with perCommitIdentity=true, got ${rowsOn.length}: ${JSON.stringify(rowsOn)}`);
  }
  const shaSet = new Set(rowsOn.map((r) => r.sha));
  if (!shaSet.has(shaA) || !shaSet.has(shaB)) {
    throw new Error(`expected shas ${shaA}, ${shaB}; got ${JSON.stringify([...shaSet])}`);
  }
  const idsDistinct = new Set(rowsOn.map((r) => r.id));
  if (idsDistinct.size !== 2) {
    throw new Error(`expected 2 distinct ids; got ${idsDistinct.size}`);
  }
  console.log(`  ids distinct, shas match A=${shaA.slice(0, 7)}, B=${shaB.slice(0, 7)}`);

  // --- perCommitIdentity: false (default) — should overwrite ---
  if (existsSync(TMP_DATA)) rmSync(TMP_DATA, { recursive: true, force: true });
  store = await Store.open(TMP_DATA);
  await indexDirectory(store, TMP_REPO, {
    repo: "pci-test",
    branch: "main",
    repo_commit_sha: shaA,
    indexed_at: new Date().toISOString(),
    // perCommitIdentity omitted -> default false
  });
  await indexDirectory(store, TMP_REPO, {
    repo: "pci-test",
    branch: "main",
    repo_commit_sha: shaB,
    indexed_at: new Date().toISOString(),
  });

  const rowsOff = await countHelloRows(store);
  await store.close();
  console.log(`perCommitIdentity=false rows: ${rowsOff.length}`);
  if (rowsOff.length !== 1) {
    throw new Error(`expected 1 row with perCommitIdentity=false (overwrite), got ${rowsOff.length}: ${JSON.stringify(rowsOff)}`);
  }

  cleanup();
  console.log("PER_COMMIT_IDENTITY_SMOKE_PASS");
}

main().catch((err) => {
  console.error("PER_COMMIT_IDENTITY_SMOKE_FAIL:", err?.message ?? err);
  process.exit(1);
});
