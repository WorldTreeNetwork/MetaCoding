// Stable Symbol ID generation.
//
// Symbol ID = sha256(language|repo|qualified_name)[:16].
// Includes `repo` so the same qualified_name (e.g. "src/main.py::Orchestrator")
// across two different repos resolves to two distinct ids.
// 16 hex chars = 64 bits — plenty of headroom even across many repos.

import { createHash } from "node:crypto";

export function symbolId(language: string, repo: string, qualified_name: string): string {
  return createHash("sha256")
    .update(`${language}|${repo}|${qualified_name}`)
    .digest("hex")
    .slice(0, 16);
}

// Content hash of a file, used for incremental skip. 16 hex chars is
// plenty for change detection on a per-repo basis.
export function fileContentHash(content: string): string {
  return createHash("sha256").update(content).digest("hex").slice(0, 16);
}
