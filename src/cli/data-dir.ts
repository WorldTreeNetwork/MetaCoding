// Resolve the data-dir for metacoding commands. (bead MetaCoding-45b)
//
// Discovery order:
//   1. --data-dir <path> on the command line (caller passes it explicitly).
//   2. ./.metacoding/ in the target repo (legacy / per-repo convention).
//   3. XDG: $XDG_DATA_HOME/metacoding/<repo-id>/  (default
//      $HOME/.local/share/metacoding/<repo-id>/) — same identity across
//      worktrees of the same repo, so two worktrees of the same project
//      write into one shared store. This is the precondition that makes
//      graph_diff useful: index branch A from one worktree and branch B
//      from another, then diff in the shared store.
//
// repo-id derivation:
//   1. sha1(`git config --get remote.origin.url`)[:12]  — stable across
//      clones / worktrees as long as the remote URL stays the same.
//   2. sha1(realpath(git rev-parse --show-toplevel))[:12] — for repos
//      without a remote. Uses --git-common-dir's parent so all worktrees
//      of the same repo collapse to one identity.
//   3. sha1(realpath(repoPath))[:12] — last-resort for non-git directories.

import { existsSync } from "node:fs";
import { homedir } from "node:os";
import { join, resolve, dirname } from "node:path";
import { createHash } from "node:crypto";

export async function repoIdentity(repoPath: string): Promise<string> {
  // First derive the underlying repo's toplevel via --git-common-dir, so
  // both worktrees and the primary checkout resolve to the same anchor.
  const toplevel = await canonicalToplevel(repoPath);

  if (toplevel) {
    // Strategy 1: remote origin URL, read from the shared config at the
    // toplevel (not from the worktree's config, which may not see it).
    try {
      const r = await Bun.$`git -C ${toplevel} config --get remote.origin.url`.quiet();
      const url = r.stdout.toString().trim();
      if (url) return sha1Short("remote:" + url);
    } catch { /* no remote */ }

    // Strategy 2: the canonical toplevel itself.
    return sha1Short("toplevel:" + toplevel);
  }

  // Strategy 3: last resort — hash of the absolute path.
  return sha1Short("path:" + resolve(repoPath));
}

async function canonicalToplevel(repoPath: string): Promise<string | null> {
  try {
    const r = await Bun.$`git -C ${repoPath} rev-parse --git-common-dir`.quiet();
    const raw = r.stdout.toString().trim();
    if (!raw) return null;
    const absGitDir = resolve(repoPath, raw);
    return absGitDir.endsWith("/.git") || absGitDir.endsWith("\\.git")
      ? dirname(absGitDir)
      : absGitDir;
  } catch {
    return null;
  }
}

export async function resolveDataDir(
  repoPath: string,
  dataDirFlag: string | undefined,
): Promise<string> {
  if (dataDirFlag) return resolve(dataDirFlag);

  // Legacy per-repo location wins if it already exists. Keeps existing
  // installations working without surprise migration.
  const legacy = join(repoPath, ".metacoding");
  if (existsSync(legacy)) return legacy;

  const xdgBase = process.env.XDG_DATA_HOME && process.env.XDG_DATA_HOME.length > 0
    ? process.env.XDG_DATA_HOME
    : join(homedir(), ".local", "share");
  const id = await repoIdentity(repoPath);
  return join(xdgBase, "metacoding", id);
}

function sha1Short(input: string): string {
  return createHash("sha1").update(input).digest("hex").slice(0, 12);
}
