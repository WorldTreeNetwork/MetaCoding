// scripts/smoke-commit-sha.ts
//
// Smoke test: every Symbol row written from a real git repo must carry
// non-null repo_commit_sha and indexed_at.
//
// Steps:
//   1. Create a temp dir and init a git repo with one commit.
//   2. Write a tiny TypeScript file into it.
//   3. Run indexDirectory against it, passing the computed sha + indexed_at.
//   4. Query the store — assert every Symbol has non-null values.
//   5. Verify the sha matches what git reported.
//
// Run with: bun run scripts/smoke-commit-sha.ts

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";

const TMP_REPO = "./tmp-commit-sha-smoke-repo";
const TMP_DATA = "./tmp-commit-sha-smoke-data";

function cleanup(): void {
  for (const d of [TMP_REPO, TMP_DATA]) {
    if (existsSync(d)) rmSync(d, { recursive: true, force: true });
  }
}

async function main(): Promise<void> {
  cleanup();

  // --- 1. Create a tiny git repo with one commit ---
  mkdirSync(TMP_REPO, { recursive: true });

  await Bun.$`git -C ${TMP_REPO} init -b main`.quiet();
  await Bun.$`git -C ${TMP_REPO} config user.email "smoke@test.local"`.quiet();
  await Bun.$`git -C ${TMP_REPO} config user.name "Smoke Test"`.quiet();

  writeFileSync(
    join(TMP_REPO, "hello.ts"),
    `export function hello(): string { return "hi"; }\n`,
  );

  await Bun.$`git -C ${TMP_REPO} add hello.ts`.quiet();
  await Bun.$`git -C ${TMP_REPO} commit -m "initial"`.quiet();

  // Capture the expected sha.
  const expectedSha = (
    await Bun.$`git -C ${TMP_REPO} rev-parse HEAD`.quiet()
  ).stdout.toString().trim();

  if (!expectedSha || expectedSha.length !== 40) {
    throw new Error(`unexpected sha from git: ${JSON.stringify(expectedSha)}`);
  }
  console.log(`git HEAD: ${expectedSha}`);

  // --- 2. Index the repo ---
  const indexed_at = new Date().toISOString();
  const store = await Store.open(TMP_DATA);

  try {
    const stats = await indexDirectory(store, TMP_REPO, {
      repo: "smoke-repo",
      branch: "main",
      repo_commit_sha: expectedSha,
      indexed_at,
    });
    console.log(`indexed: ${JSON.stringify(stats)}`);

    if (stats.filesScanned === 0) {
      throw new Error("no files scanned");
    }

    // --- 3. Assert every Symbol has non-null repo_commit_sha and indexed_at ---
    const rows = await store.query<{
      id: string;
      sha: string | null;
      iat: string | null;
    }>(
      `MATCH (s:Symbol)
       RETURN s.id AS id, s.repo_commit_sha AS sha, s.indexed_at AS iat`,
    );

    if (rows.length === 0) {
      throw new Error("no Symbol rows found in store");
    }
    console.log(`total Symbol rows: ${rows.length}`);

    const missing = rows.filter((r) => r.sha === null || r.iat === null);
    if (missing.length > 0) {
      throw new Error(
        `${missing.length} Symbol(s) have null repo_commit_sha or indexed_at:\n` +
          missing.map((r) => `  id=${r.id} sha=${r.sha} iat=${r.iat}`).join("\n"),
      );
    }

    // Verify the sha value is correct.
    const wrongSha = rows.filter((r) => r.sha !== expectedSha);
    if (wrongSha.length > 0) {
      throw new Error(
        `${wrongSha.length} Symbol(s) have wrong repo_commit_sha (expected ${expectedSha}):\n` +
          wrongSha.map((r) => `  id=${r.id} sha=${r.sha}`).join("\n"),
      );
    }

    console.log(`all ${rows.length} Symbol rows have repo_commit_sha=${expectedSha}`);
    console.log("COMMIT_SHA_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("COMMIT_SHA_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
