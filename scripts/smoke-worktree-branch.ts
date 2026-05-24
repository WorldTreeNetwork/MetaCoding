// Smoke test for currentGitBranch() — covers regular repo, git worktree, and fallback cases.

import { mkdirSync, mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";
import { currentGitBranch } from "../src/cli/branch.ts";

function assert(condition: boolean, message: string): void {
  if (!condition) throw new Error(`FAIL: ${message}`);
  console.log(`PASS: ${message}`);
}

// ── helpers ──────────────────────────────────────────────────────────────────

function makeTmp(): string {
  return mkdtempSync(join(tmpdir(), "metacoding-branch-test-"));
}

function cleanup(dirs: string[]): void {
  for (const d of dirs) {
    try { rmSync(d, { recursive: true, force: true }); } catch { /* ignore */ }
  }
}

// ── Test 1: fallback — non-git directory ─────────────────────────────────────

{
  const tmp = makeTmp();
  try {
    const result = currentGitBranch(tmp);
    assert(result === "main", `fallback non-git dir returns "main" (got "${result}")`);
  } finally {
    cleanup([tmp]);
  }
}

// ── Test 2: regular repo (directory .git) ────────────────────────────────────

{
  const tmp = makeTmp();
  try {
    // Set up a minimal regular git repo on-disk (no git binary needed)
    const gitDir = join(tmp, ".git");
    mkdirSync(join(gitDir, "refs", "heads"), { recursive: true });
    writeFileSync(join(gitDir, "HEAD"), "ref: refs/heads/my-feature\n");

    const result = currentGitBranch(tmp);
    assert(result === "my-feature", `regular repo returns correct branch (got "${result}")`);
  } finally {
    cleanup([tmp]);
  }
}

// ── Test 3: git worktree (file .git) via real "git worktree add" ─────────────

{
  const baseRepo = makeTmp();
  const worktreeDir = makeTmp();
  const dirs = [baseRepo, worktreeDir];
  try {
    // Init a real repo so "git worktree add" works.
    const init = Bun.spawnSync(["git", "init", baseRepo]);
    if (init.exitCode !== 0) throw new Error("git init failed: " + init.stderr.toString());

    // Configure git identity so commit works in CI.
    Bun.spawnSync(["git", "-C", baseRepo, "config", "user.email", "test@example.com"]);
    Bun.spawnSync(["git", "-C", baseRepo, "config", "user.name", "Test"]);

    // Need at least one commit before creating a worktree.
    writeFileSync(join(baseRepo, "README"), "hello");
    Bun.spawnSync(["git", "-C", baseRepo, "add", "README"]);
    const commit = Bun.spawnSync(["git", "-C", baseRepo, "commit", "-m", "init"]);
    if (commit.exitCode !== 0) throw new Error("git commit failed: " + commit.stderr.toString());

    // Create branch "feature-x" so the worktree can check it out.
    const branch = Bun.spawnSync(["git", "-C", baseRepo, "branch", "feature-x"]);
    if (branch.exitCode !== 0) throw new Error("git branch failed: " + branch.stderr.toString());

    // Add a worktree for "feature-x" at worktreeDir.
    const wt = Bun.spawnSync(["git", "-C", baseRepo, "worktree", "add", worktreeDir, "feature-x"]);
    if (wt.exitCode !== 0) throw new Error("git worktree add failed: " + wt.stderr.toString());

    const result = currentGitBranch(worktreeDir);
    assert(result === "feature-x", `git worktree returns "feature-x" (got "${result}")`);
  } finally {
    // Prune worktrees before removing dirs to avoid git state issues.
    Bun.spawnSync(["git", "-C", baseRepo, "worktree", "prune"]);
    cleanup(dirs);
  }
}

// ── Test 4: worktree with manually constructed .git file (no git binary) ─────

{
  const fakeGitDir = makeTmp();   // acts as .git/worktrees/wt inside main repo
  const worktreeDir = makeTmp();
  const dirs = [fakeGitDir, worktreeDir];
  try {
    // Populate just enough for HEAD to be readable.
    writeFileSync(join(fakeGitDir, "HEAD"), "ref: refs/heads/hand-crafted\n");

    // Write .git file pointing at fakeGitDir (absolute path).
    writeFileSync(join(worktreeDir, ".git"), `gitdir: ${fakeGitDir}\n`);

    const result = currentGitBranch(worktreeDir);
    assert(result === "hand-crafted", `manual .git file returns "hand-crafted" (got "${result}")`);
  } finally {
    cleanup(dirs);
  }
}

// ── Test 5: malformed .git file → fallback ───────────────────────────────────

{
  const worktreeDir = makeTmp();
  try {
    writeFileSync(join(worktreeDir, ".git"), "not-a-gitdir-line\n");
    const result = currentGitBranch(worktreeDir);
    assert(result === "main", `malformed .git file falls back to "main" (got "${result}")`);
  } finally {
    cleanup([worktreeDir]);
  }
}

console.log("\nAll smoke-worktree-branch tests passed.");
