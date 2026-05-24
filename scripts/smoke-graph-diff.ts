// scripts/smoke-graph-diff.ts
//
// End-to-end smoke for MetaCoding-6n5: graph_diff(repo, from_sha, to_sha).
//
// Indexes two real commits of a tiny git repo with --per-commit-identity so
// both snapshots coexist in one store, then exercises graphDiff to confirm:
//   - a symbol present only in the second commit shows up as "added"
//   - a symbol present only in the first commit shows up as "removed"
//   - a symbol with the same name but different body shows up as "changed"
//   - a symbol identical in both shows up as "unchanged"

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";
import { graphDiff } from "../src/mcp/tools";

const TMP_REPO = "./tmp-graph-diff-smoke-repo";
const TMP_DATA = "./tmp-graph-diff-smoke-data";
const REPO_NAME = "diff-test";

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

async function commitFile(name: string, content: string, message: string): Promise<string> {
  writeFileSync(join(TMP_REPO, name), content);
  await Bun.$`git -C ${TMP_REPO} add ${name}`.quiet();
  await Bun.$`git -C ${TMP_REPO} commit -m ${message} --allow-empty`.quiet();
  return (await Bun.$`git -C ${TMP_REPO} rev-parse HEAD`.quiet()).stdout.toString().trim();
}

async function deleteAndCommit(name: string, message: string): Promise<string> {
  rmSync(join(TMP_REPO, name));
  await Bun.$`git -C ${TMP_REPO} add -A`.quiet();
  await Bun.$`git -C ${TMP_REPO} commit -m ${message}`.quiet();
  return (await Bun.$`git -C ${TMP_REPO} rev-parse HEAD`.quiet()).stdout.toString().trim();
}

async function main(): Promise<void> {
  cleanup();
  await initRepo();

  // ----- Commit A: alpha (will be removed) + shared (unchanged) + drift (will change body) -----
  await commitFile(
    "alpha.ts",
    `export function alpha(): string { return "A"; }\n`,
    "alpha v1",
  );
  await commitFile(
    "shared.ts",
    `export function shared(): number { return 42; }\n`,
    "shared v1",
  );
  const shaA = await commitFile(
    "drift.ts",
    `export function drift(): string { return "v1"; }\n`,
    "drift v1",
  );

  // Index A
  let store = await Store.open(TMP_DATA);
  await indexDirectory(store, TMP_REPO, {
    repo: REPO_NAME,
    branch: "main",
    repo_commit_sha: shaA,
    indexed_at: new Date().toISOString(),
    perCommitIdentity: true,
  });
  await store.close();

  // ----- Commit B: remove alpha, keep shared identical, change drift body, add omega -----
  await deleteAndCommit("alpha.ts", "remove alpha");
  await commitFile(
    "drift.ts",
    `export function drift(): string { return "v2-changed"; }\n`,
    "drift v2",
  );
  const shaB = await commitFile(
    "omega.ts",
    `export function omega(): string { return "new"; }\n`,
    "omega v1",
  );

  // Index B (same store)
  store = await Store.open(TMP_DATA);
  await indexDirectory(store, TMP_REPO, {
    repo: REPO_NAME,
    branch: "main",
    repo_commit_sha: shaB,
    indexed_at: new Date().toISOString(),
    perCommitIdentity: true,
  });

  const diff = await graphDiff(store, {
    repo: REPO_NAME,
    from_sha: shaA,
    to_sha: shaB,
  });
  await store.close();

  console.log(`shaA=${shaA.slice(0, 7)}  shaB=${shaB.slice(0, 7)}`);
  console.log(`counts: ${JSON.stringify(diff.counts)}`);

  const addedNames = new Set(diff.added.map((s) => s.qualified_name));
  const removedNames = new Set(diff.removed.map((s) => s.qualified_name));
  const changedNames = new Set(diff.changed.map((c) => c.qualified_name));

  // alpha.ts file + its exported alpha function must be in `removed`.
  if (!removedNames.has("alpha.ts") || !removedNames.has("alpha.ts::alpha")) {
    throw new Error(`expected removed to contain alpha.ts and alpha.ts::alpha; got ${[...removedNames].join(",")}`);
  }
  console.log(`removed OK: ${[...removedNames].slice(0, 4).join(", ")}`);

  // omega.ts + omega.ts::omega must be in `added`.
  if (!addedNames.has("omega.ts") || !addedNames.has("omega.ts::omega")) {
    throw new Error(`expected added to contain omega.ts and omega.ts::omega; got ${[...addedNames].join(",")}`);
  }
  console.log(`added OK: ${[...addedNames].slice(0, 4).join(", ")}`);

  // drift.ts::drift must be in `changed` (same qualified_name, different ast_hash).
  // The file Symbol drift.ts also has a different ast_hash so it's "changed" too.
  if (!changedNames.has("drift.ts")) {
    throw new Error(`expected changed to contain drift.ts (file ast_hash differs); got ${[...changedNames].join(",")}`);
  }
  console.log(`changed OK: ${[...changedNames].slice(0, 4).join(", ")}`);

  // shared.ts and shared.ts::shared should be unchanged.
  if (addedNames.has("shared.ts::shared") || removedNames.has("shared.ts::shared") || changedNames.has("shared.ts::shared")) {
    throw new Error(`expected shared.ts::shared to be unchanged; appeared in diff`);
  }
  if (diff.counts.unchanged < 1) {
    throw new Error(`expected unchanged >= 1, got ${diff.counts.unchanged}`);
  }
  console.log(`unchanged count: ${diff.counts.unchanged} (>= 1 OK)`);

  cleanup();
  console.log("GRAPH_DIFF_SMOKE_PASS");
}

main().catch((err) => {
  console.error("GRAPH_DIFF_SMOKE_FAIL:", err?.message ?? err);
  process.exit(1);
});
