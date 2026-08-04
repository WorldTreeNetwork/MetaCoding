// The shared seam for index-state observability.
//
// One place that answers "is this graph indexed, and is it stale relative to
// the working tree?" — consumed by the describe_api MCP tool, the serve
// startup warning, and the status CLI. Pure read: it asks the Store for a
// summary and shells out to git read-only; it never mutates and never throws.

import type { Store, RepoSnapshot } from "./store";
import {
  formatHealthLine,
  isFitnessEstablished,
  readAllIndexHealth,
  statusOf,
  type IndexHealthRecord,
} from "./store/health.ts";

export interface Staleness {
  indexed_commit: string | null; // most-recent indexed sha for the workspace's repo
  current_commit: string | null; // live `git rev-parse HEAD`
  head_behind: boolean; // both known AND differ
  dirty_files: number; // `git status --porcelain` line count (0 if unknown/clean)
}

export interface IndexState {
  dataDir: string;
  indexed: boolean;
  symbols: number;
  repos: RepoSnapshot[]; // from Store.summary()
  staleness: Staleness | null; // null when not a git repo or no indexed commit to compare
  /**
   * The PERSISTED fitness verdicts beside this graph (bead MetaCoding-ae5).
   * `indexed` is a symbol count and cannot tell a finished run from a SIGKILLed
   * one: a killed ingest leaves symbols and zero edges — the MetaCoding-hy6.16
   * shape — and `status` used to print "Indexed: 1724 symbol(s)" over it.
   * An EMPTY array means UNKNOWN, never healthy.
   */
  health: IndexHealthRecord[];
  /** True only when at least one slice is recorded AND every one is established. */
  fitness_established: boolean;
}

/**
 * Run `git rev-parse HEAD` in `cwd`. Returns the SHA, or null if the dir is not
 * a git repo, has no commits, or git is unavailable. Never throws. Mirrors the
 * getRepoCommitSha pattern in src/cli/main.ts.
 */
async function gitHead(cwd: string): Promise<string | null> {
  try {
    const result = await Bun.$`git -C ${cwd} rev-parse HEAD`.quiet();
    return result.stdout.toString().trim() || null;
  } catch {
    return null;
  }
}

/**
 * Count working-tree changes via `git status --porcelain` line count. Returns 0
 * when git fails or the tree is clean. Never throws.
 */
async function gitDirtyCount(cwd: string): Promise<number> {
  try {
    const result = await Bun.$`git -C ${cwd} status --porcelain`.quiet();
    const text = result.stdout.toString();
    if (text.trim() === "") return 0;
    return text.split("\n").filter((line) => line.length > 0).length;
  } catch {
    return 0;
  }
}

/**
 * Pick the indexed commit sha to compare HEAD against: the sha of the
 * most-recently-indexed repo (max indexed_at), falling back to the first repo
 * that has a non-null sha.
 */
function pickIndexedCommit(repos: RepoSnapshot[]): string | null {
  let best: RepoSnapshot | null = null;
  for (const r of repos) {
    if (r.indexed_at === null) continue;
    if (best === null || (best.indexed_at !== null && r.indexed_at > best.indexed_at)) {
      best = r;
    }
  }
  if (best?.repo_commit_sha != null) return best.repo_commit_sha;
  // Fall back to the first repo carrying a sha at all.
  for (const r of repos) {
    if (r.repo_commit_sha != null) return r.repo_commit_sha;
  }
  return null;
}

/**
 * Combine the store summary with live git state into a single IndexState.
 * Git failures degrade to null/0 — this never throws.
 */
export async function gatherIndexState(
  store: Store,
  workspacePath: string,
): Promise<IndexState> {
  const summary = await store.summary();
  const indexedCommit = pickIndexedCommit(summary.repos);

  let staleness: Staleness | null = null;
  if (indexedCommit !== null) {
    const currentCommit = await gitHead(workspacePath);
    if (currentCommit !== null) {
      const dirtyFiles = await gitDirtyCount(workspacePath);
      staleness = {
        indexed_commit: indexedCommit,
        current_commit: currentCommit,
        head_behind: indexedCommit !== currentCommit,
        dirty_files: dirtyFiles,
      };
    }
  }

  const health = readAllIndexHealth(summary.dataDir);
  const fitness_established =
    health.length > 0 && health.every((h) => isFitnessEstablished(statusOf(h)));

  return {
    dataDir: summary.dataDir,
    indexed: summary.indexed,
    symbols: summary.symbols,
    repos: summary.repos,
    staleness,
    health,
    fitness_established,
  };
}

/** Short 7-char sha for display, tolerant of null/short input. */
function short(sha: string | null): string {
  if (!sha) return "(none)";
  return sha.slice(0, 7);
}

/**
 * Render an IndexState as a human-readable, multi-line block. When the
 * workspace is not indexed, it says so prominently and prints the exact
 * command to index. When indexed and stale, it appends a warning line.
 */
export function formatIndexState(state: IndexState): string {
  const lines: string[] = [];

  if (!state.indexed) {
    lines.push("⚠ This workspace is NOT indexed — every query will return empty results.");
    lines.push(`  data dir: ${state.dataDir}`);
    // Fitness even here: a store with ZERO symbols and a RUNNING record is a
    // run that died before it wrote anything, which is a different situation
    // from "never indexed" and needs a different fix (MetaCoding-ae5).
    lines.push("  index fitness:");
    if (state.health.length === 0) {
      lines.push("    ⚠ UNKNOWN — no index-health record beside this graph.");
    }
    for (const h of state.health) {
      lines.push(`    ⚠ ${formatHealthLine(h, h.repo, h.branch)}`);
    }
    lines.push("  To index, run:");
    lines.push("      metacoding index . --scip");
    return lines.join("\n");
  }

  lines.push(`Indexed: ${state.symbols} symbol(s) across ${state.repos.length} repo(s).`);
  lines.push(`  data dir: ${state.dataDir}`);
  for (const r of state.repos) {
    const at = r.indexed_at ?? "unknown time";
    lines.push(`  - ${r.repo} @ ${short(r.repo_commit_sha)} (${r.symbols} symbols, indexed ${at})`);
  }

  // FITNESS, beside the symbol count. A symbol count answers "is there data";
  // only the persisted record answers "did a run ever establish that this data
  // is what it claims to be" (MetaCoding-ae5). Repos with symbols but no record
  // are reported UNKNOWN, never healthy.
  lines.push("  index fitness:");
  const byRepo = new Map(state.health.map((h) => [`${h.repo}`, h] as const));
  const seen = new Set<string>();
  for (const r of state.repos) {
    seen.add(r.repo);
    const rec = byRepo.get(r.repo) ?? null;
    lines.push(`    ${statusOf(rec) === "HEALTHY" ? "✓" : "⚠"} ${formatHealthLine(rec, r.repo, rec?.branch ?? "?")}`);
  }
  for (const h of state.health) {
    if (seen.has(h.repo)) continue;
    lines.push(`    ⚠ ${formatHealthLine(h, h.repo, h.branch)}`);
  }

  const s = state.staleness;
  if (s && (s.head_behind || s.dirty_files > 0)) {
    lines.push(
      `⚠ graph is stale: indexed ${short(s.indexed_commit)} but HEAD is ` +
        `${short(s.current_commit)}, ${s.dirty_files} dirty file(s) — ` +
        `prefer lsp_references for changed files.`,
    );
  }

  return lines.join("\n");
}
