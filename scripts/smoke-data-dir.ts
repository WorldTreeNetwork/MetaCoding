// scripts/smoke-data-dir.ts
//
// Smoke test for MetaCoding-45b: data-dir resolution.
//
// Verifies:
//   1. --data-dir flag wins (explicit override).
//   2. Legacy ./.metacoding/ wins when it exists.
//   3. XDG default lands at $XDG_DATA_HOME/metacoding/<repo-id>/ for git repos
//      with a remote URL.
//   4. repoIdentity collapses worktrees of the same repo to one id.

import { existsSync, mkdirSync, rmSync } from "node:fs";
import { join, resolve } from "node:path";
import { homedir } from "node:os";

import { resolveDataDir, repoIdentity } from "../src/cli/data-dir";

const TMP_REPO = resolve("./tmp-data-dir-smoke-repo");
const TMP_WORKTREE = resolve("./tmp-data-dir-smoke-wt");
const TMP_XDG = resolve("./tmp-data-dir-smoke-xdg");

function cleanup(): void {
  for (const d of [TMP_REPO, TMP_WORKTREE, TMP_XDG]) {
    if (existsSync(d)) rmSync(d, { recursive: true, force: true });
  }
}

async function initRepo(): Promise<void> {
  mkdirSync(TMP_REPO, { recursive: true });
  await Bun.$`git -C ${TMP_REPO} init -b main`.quiet();
  await Bun.$`git -C ${TMP_REPO} config user.email "smoke@test.local"`.quiet();
  await Bun.$`git -C ${TMP_REPO} config user.name "Smoke Test"`.quiet();
  await Bun.$`git -C ${TMP_REPO} config remote.origin.url "https://example.com/test.git"`.quiet();
  await Bun.$`bash -c 'echo "hi" > ${TMP_REPO}/a.ts'`.quiet();
  await Bun.$`git -C ${TMP_REPO} add a.ts`.quiet();
  await Bun.$`git -C ${TMP_REPO} commit -m "init"`.quiet();
}

async function main(): Promise<void> {
  cleanup();
  await initRepo();

  process.env.XDG_DATA_HOME = TMP_XDG;
  const xdgAbs = TMP_XDG;

  // 1. --data-dir flag wins.
  const explicit = await resolveDataDir(TMP_REPO, "/tmp/custom-data-dir");
  if (explicit !== "/tmp/custom-data-dir") {
    throw new Error(`expected explicit flag to win, got ${explicit}`);
  }
  console.log(`explicit override OK: ${explicit}`);

  // 2. Legacy .metacoding/ wins.
  const legacy = join(TMP_REPO, ".metacoding");
  mkdirSync(legacy, { recursive: true });
  const resolvedLegacy = await resolveDataDir(TMP_REPO, undefined);
  if (!resolvedLegacy.endsWith(".metacoding")) {
    throw new Error(`expected legacy path, got ${resolvedLegacy}`);
  }
  console.log(`legacy .metacoding/ OK: ${resolvedLegacy}`);
  rmSync(legacy, { recursive: true, force: true });

  // 3. XDG default.
  const xdg = await resolveDataDir(TMP_REPO, undefined);
  if (!xdg.startsWith(xdgAbs)) {
    throw new Error(`expected XDG path, got ${xdg}`);
  }
  console.log(`xdg default OK: ${xdg}`);

  // 4. Worktree-collapse via repoIdentity. Use absolute paths because
  //    `git -C X worktree add <rel>` resolves <rel> relative to X.
  await Bun.$`git -C ${TMP_REPO} worktree add ${TMP_WORKTREE} -b feature/x`.quiet();

  const idA = await repoIdentity(TMP_REPO);
  const idB = await repoIdentity(TMP_WORKTREE);
  if (idA !== idB) {
    throw new Error(`worktree collapse failed: ${idA} (main) vs ${idB} (worktree)`);
  }
  console.log(`worktree collapse OK: ${idA}`);

  // 5. Same identity by remote URL across "clones" — two separate paths with
  //    the same remote should produce the same id.
  const TMP_CLONE = resolve("./tmp-data-dir-smoke-clone");
  if (existsSync(TMP_CLONE)) rmSync(TMP_CLONE, { recursive: true, force: true });
  mkdirSync(TMP_CLONE, { recursive: true });
  await Bun.$`git -C ${TMP_CLONE} init -b main`.quiet();
  await Bun.$`git -C ${TMP_CLONE} config user.email "smoke@test.local"`.quiet();
  await Bun.$`git -C ${TMP_CLONE} config user.name "Smoke Test"`.quiet();
  await Bun.$`git -C ${TMP_CLONE} config remote.origin.url "https://example.com/test.git"`.quiet();
  const idClone = await repoIdentity(TMP_CLONE);
  if (idClone !== idA) {
    throw new Error(`remote-url-based identity should match across clones: ${idA} vs ${idClone}`);
  }
  console.log(`remote-url collapse OK: ${idClone}`);
  rmSync(TMP_CLONE, { recursive: true, force: true });

  cleanup();
  console.log("DATA_DIR_SMOKE_PASS");
}

main().catch((err) => {
  console.error("DATA_DIR_SMOKE_FAIL:", err?.message ?? err);
  cleanup();
  process.exit(1);
});
