// Auto-detect the current git branch from .git/HEAD without spawning git.
// Falls back to "main" if there is no .git or the HEAD format is unexpected.

import { existsSync, readFileSync } from "node:fs";
import { join } from "node:path";

export function currentGitBranch(repoPath: string): string {
  const headPath = join(repoPath, ".git", "HEAD");
  if (!existsSync(headPath)) return "main";
  try {
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
