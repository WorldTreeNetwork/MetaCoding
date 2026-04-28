// scripts/smoke-multirepo.ts
//
// Validates the multi-repo dimension on a shared Store:
//   - Two fixtures with same short_name `Orchestrator` end up as two
//     distinct Symbol nodes (different ids, different repo).
//   - Cross-repo Cypher returns both rows.
//   - deleteFileData scoped to one repo doesn't touch the other.
//
// Run with: bun run scripts/smoke-multirepo.ts

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";

const ROOT = resolve("./tmp-multirepo-fix");
const A = join(ROOT, "alpha");
const B = join(ROOT, "beta");
const DATA = resolve("./tmp-multirepo-data");

function cleanup(): void {
  for (const d of [ROOT, DATA]) {
    if (existsSync(d)) rmSync(d, { recursive: true, force: true });
  }
}

async function main(): Promise<void> {
  cleanup();
  mkdirSync(A, { recursive: true });
  mkdirSync(B, { recursive: true });

  // Two repos, both define a class `Orchestrator` in src/main.py — same short
  // name, same path, but the repo dimension distinguishes them.
  mkdirSync(join(A, "src"));
  mkdirSync(join(B, "src"));
  writeFileSync(join(A, "src", "main.py"), `class Orchestrator:\n    def from_alpha(self): pass\n`);
  writeFileSync(join(B, "src", "main.py"), `class Orchestrator:\n    def from_beta(self): pass\n`);

  const store = await Store.open(DATA);

  try {
    const ra = await indexDirectory(store, A, { repo: "alpha", branch: "main" });
    const rb = await indexDirectory(store, B, { repo: "beta", branch: "main" });
    if (ra.filesUpdated !== 1 || rb.filesUpdated !== 1) {
      throw new Error(`expected 1 file each; got alpha=${ra.filesUpdated} beta=${rb.filesUpdated}`);
    }

    // Both Orchestrator classes should exist with distinct ids and repos.
    const orchestrators = await store.query<{ id: string; repo: string; method: string | null }>(
      `MATCH (c:Symbol {kind: 'class', short_name: 'Orchestrator'})
       OPTIONAL MATCH (c)-[:CONTAINS]->(m:Symbol {kind: 'method'})
       RETURN c.id AS id, c.repo AS repo, m.short_name AS method
       ORDER BY repo, method`,
    );
    const repos = new Set(orchestrators.map((r) => r.repo));
    if (repos.size !== 2 || !repos.has("alpha") || !repos.has("beta")) {
      throw new Error(`expected both repos in result; got ${JSON.stringify(orchestrators)}`);
    }
    const ids = new Set(orchestrators.map((r) => r.id));
    if (ids.size !== 2) {
      throw new Error(`expected distinct symbol ids per repo; got ${JSON.stringify([...ids])}`);
    }
    // Methods are repo-specific.
    const methodsByRepo: Record<string, string[]> = {};
    for (const r of orchestrators) {
      if (!r.method) continue;
      (methodsByRepo[r.repo] ??= []).push(r.method);
    }
    if (!methodsByRepo.alpha?.includes("from_alpha")) {
      throw new Error(`alpha didn't get its method; got ${JSON.stringify(methodsByRepo)}`);
    }
    if (!methodsByRepo.beta?.includes("from_beta")) {
      throw new Error(`beta didn't get its method; got ${JSON.stringify(methodsByRepo)}`);
    }
    console.log(
      `cross-repo OK: alpha methods=${methodsByRepo.alpha}, beta methods=${methodsByRepo.beta}`,
    );

    // Repo-scoped delete: nuke alpha's main.py only.
    await store.deleteFileData("alpha", "src/main.py", "main");
    const remaining = await store.query<{ repo: string; n: number }>(
      `MATCH (s:Symbol {kind: 'class', short_name: 'Orchestrator'})
       RETURN s.repo AS repo, COUNT(s) AS n
       ORDER BY repo`,
    );
    const flat = remaining.reduce<Record<string, number>>((acc, r) => ((acc[r.repo] = Number(r.n)), acc), {});
    if ((flat.alpha ?? 0) !== 0) {
      throw new Error(`alpha Orchestrator should be 0 after delete; got ${flat.alpha}`);
    }
    if ((flat.beta ?? 0) !== 1) {
      throw new Error(`beta Orchestrator should still be 1; got ${flat.beta}`);
    }
    console.log(`repo-scoped delete OK: alpha=0 (deleted), beta=${flat.beta} (intact)`);

    // FTS: token search returns hits for both repos but `from_alpha` only
    // appears under repo='alpha', `from_beta` only under repo='beta'. Since
    // we just deleted alpha's data, only beta tokens should remain.
    const ftsBeta = store.searchTokens("from_beta", 10);
    if (ftsBeta.length === 0) throw new Error("beta tokens disappeared");
    const ftsAlpha = store.searchTokens("from_alpha", 10);
    if (ftsAlpha.length !== 0) {
      throw new Error(`alpha tokens should be gone after delete; got ${ftsAlpha.length}`);
    }
    console.log(`fts repo isolation OK: from_beta=${ftsBeta.length}, from_alpha=${ftsAlpha.length}`);

    console.log("MULTIREPO_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("MULTIREPO_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
