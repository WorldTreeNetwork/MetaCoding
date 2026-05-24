// Stable Symbol ID generation.
//
// Symbol ID = sha256(language|repo|qualified_name)[:16].
// Includes `repo` so the same qualified_name (e.g. "src/main.py::Orchestrator")
// across two different repos resolves to two distinct ids.
// 16 hex chars = 64 bits — plenty of headroom even across many repos.
//
// When `commit_sha` is provided and non-empty (opt-in per-commit-identity mode,
// bead MetaCoding-izn), it is folded into the hash so two indexes of different
// commits coexist in one DB without overwriting:
//   sha256(language|repo|qualified_name|commit_sha)[:16].

import { createHash } from "node:crypto";

export function symbolId(
  language: string,
  repo: string,
  qualified_name: string,
  commit_sha?: string,
): string {
  const input =
    commit_sha && commit_sha.length > 0
      ? `${language}|${repo}|${qualified_name}|${commit_sha}`
      : `${language}|${repo}|${qualified_name}`;
  return createHash("sha256").update(input).digest("hex").slice(0, 16);
}

// Content hash of a file, used for incremental skip. 16 hex chars is
// plenty for change detection on a per-repo basis.
export function fileContentHash(content: string): string {
  return createHash("sha256").update(content).digest("hex").slice(0, 16);
}
