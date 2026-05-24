// scripts/smoke-paths.ts
//
// Regression-guard smoke test: asserts every Symbol.file written by the
// indexer is repo-relative (not absolute).
//
// This ensures that if someone later changes the walker to write absolute
// paths, this test will catch it immediately.
//
// Run with: bun run scripts/smoke-paths.ts

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { isAbsolute } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";

const DATA_DIR = "./tmp-paths-smoke";
const FIXTURE_DIR = "./tmp-paths-fixture";

function cleanup(): void {
  if (existsSync(DATA_DIR)) rmSync(DATA_DIR, { recursive: true, force: true });
  if (existsSync(FIXTURE_DIR)) rmSync(FIXTURE_DIR, { recursive: true, force: true });
}

async function createFixture(): Promise<void> {
  mkdirSync(FIXTURE_DIR, { recursive: true });

  // Write a simple TypeScript file with a class and function.
  writeFileSync(
    `${FIXTURE_DIR}/example.ts`,
    `
export class Example {
  constructor() {}

  method(): string {
    return "hello";
  }
}

export function greet(name: string): void {
  console.log("Hello, " + name);
}
`,
  );

  // Write another file to ensure we test multiple files.
  writeFileSync(
    `${FIXTURE_DIR}/util.ts`,
    `
export const PI = 3.14159;

export function add(a: number, b: number): number {
  return a + b;
}
`,
  );
}

async function main(): Promise<void> {
  cleanup();
  createFixture();

  const store = await Store.open(DATA_DIR);

  try {
    const stats = await indexDirectory(store, FIXTURE_DIR);
    console.log(`indexed: ${JSON.stringify(stats)}`);

    if (stats.filesScanned === 0) {
      throw new Error("no .ts files found under fixture directory");
    }

    // Query all Symbols with a non-null file field.
    const rows = await store.query<{ file: string | null }>(
      `MATCH (s:Symbol)
       WHERE s.file IS NOT NULL
       RETURN s.file AS file`,
    );

    if (rows.length === 0) {
      throw new Error("expected at least one Symbol with a non-null file; got none");
    }

    // Assert every file is repo-relative (not absolute).
    for (const row of rows) {
      const file = row.file;
      if (file && isAbsolute(file)) {
        throw new Error(
          `REGRESSION: Symbol.file is absolute (should be repo-relative): ${file}`,
        );
      }
    }

    console.log(`asserted ${rows.length} Symbol.file paths are repo-relative`);
    console.log("PATHS_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("PATHS_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
