// Stable Symbol ID generation.
//
// Symbol ID = sha256(language + "|" + qualified_name)[:16].
// Robust against line/column drift; consistent across re-indexing.
// 16 hex chars = 64 bits — plenty of headroom for a single repo's symbol set.

import { createHash } from "node:crypto";

export function symbolId(language: string, qualified_name: string): string {
  return createHash("sha256")
    .update(`${language}|${qualified_name}`)
    .digest("hex")
    .slice(0, 16);
}
