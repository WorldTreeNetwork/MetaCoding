// scripts/smoke-incremental.ts
//
// Validates Phase 4: ast_hash skip path + watch mode.
//
// 1. Build a tiny TS fixture, index it -> all files updated.
// 2. Re-index the same content -> all files skipped (content hash match).
// 3. Modify one file -> only that file updated, the other stays skipped.
// 4. Start watch mode, modify a file -> watcher re-indexes it.
// 5. Delete a file -> watcher detach-deletes its symbols.
//
// Run with: bun run scripts/smoke-incremental.ts

import { existsSync, mkdirSync, rmSync, writeFileSync, unlinkSync } from "node:fs";
import { join, resolve } from "node:path";

import { Store } from "../src/store";
import { indexDirectory, watch } from "../src/extractor";

const FIX = resolve("./tmp-incr-fixture");
const DATA = resolve("./tmp-incr-data");

function cleanup(): void {
  for (const d of [FIX, DATA]) {
    if (existsSync(d)) rmSync(d, { recursive: true, force: true });
  }
}

function writeFixture(name: string, body: string): string {
  const path = join(FIX, name);
  writeFileSync(path, body, "utf-8");
  return path;
}

async function classCount(store: Store, branch: string, file: string): Promise<number> {
  const rows = await store.query<{ n: number }>(
    `MATCH (s:Symbol)
     WHERE s.kind = 'class' AND s.file = $file AND s.branch = $branch
     RETURN COUNT(s) AS n`,
    { file, branch },
  );
  return Number(rows[0]?.n ?? 0);
}

async function symbolCountForFile(store: Store, branch: string, file: string): Promise<number> {
  const rows = await store.query<{ n: number }>(
    `MATCH (s:Symbol) WHERE s.file = $file AND s.branch = $branch RETURN COUNT(s) AS n`,
    { file, branch },
  );
  return Number(rows[0]?.n ?? 0);
}

function sleep(ms: number): Promise<void> {
  return new Promise((r) => setTimeout(r, ms));
}

async function main(): Promise<void> {
  cleanup();
  mkdirSync(FIX, { recursive: true });

  // Initial fixture: two files, each with one class.
  writeFixture("alpha.ts", "export class Alpha { hello() { return 1; } }\n");
  writeFixture("beta.ts", "export class Beta { world() { return 2; } }\n");

  const store = await Store.open(DATA);

  try {
    // 1. First index — both files updated.
    const r1 = await indexDirectory(store, FIX, { branch: "main" });
    if (r1.filesUpdated !== 2 || r1.filesSkipped !== 0) {
      throw new Error(`first index: expected updated=2 skipped=0, got ${JSON.stringify(r1)}`);
    }
    console.log(`pass 1: ${r1.filesUpdated} updated, ${r1.filesSkipped} skipped`);

    // 2. Re-index unchanged — both files skipped.
    const r2 = await indexDirectory(store, FIX, { branch: "main" });
    if (r2.filesUpdated !== 0 || r2.filesSkipped !== 2) {
      throw new Error(`second index: expected updated=0 skipped=2, got ${JSON.stringify(r2)}`);
    }
    console.log(`pass 2: ${r2.filesUpdated} updated, ${r2.filesSkipped} skipped`);

    // 3. Modify alpha.ts — only it should re-index.
    writeFixture("alpha.ts", "export class Alpha2 { hello() { return 1; } }\n");
    const r3 = await indexDirectory(store, FIX, { branch: "main" });
    if (r3.filesUpdated !== 1 || r3.filesSkipped !== 1) {
      throw new Error(`third index: expected updated=1 skipped=1, got ${JSON.stringify(r3)}`);
    }
    // Old class Alpha should be gone; new class Alpha2 present.
    const alphaRows = await store.query<{ name: string }>(
      `MATCH (s:Symbol)
       WHERE s.file = 'alpha.ts' AND s.kind = 'class'
       RETURN s.short_name AS name`,
    );
    const names = alphaRows.map((r) => r.name).sort();
    if (JSON.stringify(names) !== JSON.stringify(["Alpha2"])) {
      throw new Error(`expected only Alpha2 in alpha.ts; got ${JSON.stringify(names)}`);
    }
    console.log(`pass 3: incremental rename works (Alpha -> Alpha2)`);

    // 4. Watch mode: change beta.ts and confirm the watcher re-indexes.
    let processed: Array<{ event: string; path: string }> = [];
    const handle = await watch(store, FIX, {
      branch: "main",
      onProcessed: (event, path) => processed.push({ event, path }),
    });

    // Trigger a change.
    writeFixture("beta.ts", "export class Beta2 { world() { return 2; } }\n");
    // Wait for chokidar to fire and our queue to drain.
    let waited = 0;
    while (processed.length === 0 && waited < 5000) {
      await sleep(100);
      waited += 100;
    }
    await handle.drain();
    if (processed.length === 0) {
      throw new Error("watch: no events fired after writing beta.ts");
    }
    const betaClasses = await store.query<{ name: string }>(
      `MATCH (s:Symbol) WHERE s.file = 'beta.ts' AND s.kind = 'class' RETURN s.short_name AS name`,
    );
    const betaNames = betaClasses.map((r) => r.name).sort();
    if (JSON.stringify(betaNames) !== JSON.stringify(["Beta2"])) {
      throw new Error(`watch: expected Beta2 after edit; got ${JSON.stringify(betaNames)}`);
    }
    console.log(`pass 4: watch caught ${processed.length} event(s); Beta -> Beta2 reflected`);

    // 5. Delete a file — symbols should disappear.
    processed = [];
    unlinkSync(join(FIX, "beta.ts"));
    waited = 0;
    while (processed.length === 0 && waited < 5000) {
      await sleep(100);
      waited += 100;
    }
    await handle.drain();
    const betaAfterDelete = await symbolCountForFile(store, "main", "beta.ts");
    if (betaAfterDelete !== 0) {
      throw new Error(`watch: expected 0 symbols for deleted beta.ts; got ${betaAfterDelete}`);
    }
    const alphaAfterDelete = await classCount(store, "main", "alpha.ts");
    if (alphaAfterDelete !== 1) {
      throw new Error(`watch: alpha.ts should still have 1 class; got ${alphaAfterDelete}`);
    }
    console.log(`pass 5: watch caught delete; beta.ts symbols cleared, alpha.ts intact`);

    await handle.close();

    console.log("INCREMENTAL_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("INCREMENTAL_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
