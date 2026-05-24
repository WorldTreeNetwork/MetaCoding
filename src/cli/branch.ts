// Auto-detect the current git branch from .git/HEAD without spawning git.
// Falls back to "main" if there is no .git or the HEAD format is unexpected.
// Handles git worktrees where .git is a file containing "gitdir: <path>".

import { existsSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, join, resolve } from "node:path";

export function currentGitBranch(repoPath: string): string {
  const gitPath = join(repoPath, ".git");
  if (!existsSync(gitPath)) return "main";

  try {
    let headPath: string;
    const stat = statSync(gitPath);
    if (stat.isFile()) {
      // Worktree case: .git is a file with content "gitdir: <path>"
      const gitfileContent = readFileSync(gitPath, "utf-8").trim();
      const gitdirPrefix = "gitdir: ";
      if (!gitfileContent.startsWith(gitdirPrefix)) return "main";
      const gitdirRaw = gitfileContent.slice(gitdirPrefix.length).trim();
      const gitdir = isAbsolute(gitdirRaw)
        ? gitdirRaw
        : resolve(repoPath, gitdirRaw);
      headPath = join(gitdir, "HEAD");
    } else {
      headPath = join(gitPath, "HEAD");
    }

    if (!existsSync(headPath)) return "main";
    const head = readFileSync(headPath, "utf-8").trim();
    const refPrefix = "ref: refs/heads/";
    if (head.startsWith(refPrefix)) {
      return head.slice(refPrefix.length);
    }
    // Detached HEAD: short SHA.
    return head.slice(0, 7);
  } catch {
    return "main";
  }
}
