// Tests for the walker's watch-mode indexFile path, with focus on the
// scoped resolver-hydrate added in MetaCoding-zq2.
//
// The perf change reshuffles indexFile so edge candidates are collected first,
// then the resolver is hydrated ONLY for the short_names those candidates need
// (`... AND s.short_name IN $names`). These tests assert that scoping does NOT
// drop cross-file behavior edges: a CONSTRUCTS edge whose target class lives in
// a *different* file already in the store must still resolve.

import { test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, mkdirSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "../store";
import { indexDirectory, indexFile } from "./walker";

let dataDir: string;
let repoDir: string;
let store: Store;

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "zq2-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "zq2-repo-"));
  store = await Store.open(dataDir);
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

function write(name: string, body: string): void {
  const p = join(repoDir, name);
  mkdirSync(join(repoDir, name, ".."), { recursive: true });
  writeFileSync(p, body, "utf-8");
}

async function constructsCount(repo: string, branch: string): Promise<number> {
  const rows = await store.query<{ n: number }>(
    `MATCH (a:Symbol)-[:CONSTRUCTS]->(b:Symbol)
     WHERE a.repo = $repo AND a.branch = $branch
     RETURN COUNT(*) AS n`,
    { repo, branch },
  );
  return Number(rows[0]?.n ?? 0);
}

test("watch-mode indexFile resolves a cross-file CONSTRUCTS via scoped hydrate", async () => {
  const repo = "zq2";
  const branch = "main";

  // foo.ts defines the class; user.ts (added later, single-file) constructs it.
  write("foo.ts", "export class Foo { hello() { return 1; } }\n");
  // Seed the store with foo.ts so its Foo symbol is on disk for the hydrate.
  await indexDirectory(store, repoDir, { repo, branch });
  expect(await constructsCount(repo, branch)).toBe(0);

  // Now add user.ts and index it SINGLE-FILE (the watch-mode path). Its
  // `new Foo()` target lives in foo.ts, only resolvable via store hydrate.
  write(
    "user.ts",
    "import { Foo } from './foo';\nexport function make() { return new Foo(); }\n",
  );
  const r = await indexFile(store, repoDir, join(repoDir, "user.ts"), {
    repo,
    branch,
  });
  expect(r.skipped).toBe(false);

  // The scoped hydrate must have pulled Foo (short_name "Foo" is referenced by
  // the CONSTRUCTS candidate), so the cross-file edge resolves.
  expect(await constructsCount(repo, branch)).toBe(1);
});

test("indexFile with no behavior-edge candidates skips the hydrate query cleanly", async () => {
  const repo = "zq2";
  const branch = "main";

  // A file with no constructs/writes/returns-type — empty candidate set means
  // the scoped hydrate is skipped entirely. Must still index without error.
  write("plain.ts", "export const answer = 42;\n");
  const r = await indexFile(store, repoDir, join(repoDir, "plain.ts"), {
    repo,
    branch,
  });
  expect(r.skipped).toBe(false);
  expect(await constructsCount(repo, branch)).toBe(0);
});

test("scoped hydrate matches indexDirectory for the same cross-file edge", async () => {
  const repo = "zq2";
  const branch = "main";

  write("foo.ts", "export class Foo { hello() { return 1; } }\n");
  write(
    "user.ts",
    "import { Foo } from './foo';\nexport function make() { return new Foo(); }\n",
  );

  // Full directory pass resolves the cross-file CONSTRUCTS in-memory.
  await indexDirectory(store, repoDir, { repo, branch });
  const full = await constructsCount(repo, branch);
  expect(full).toBe(1);

  // Re-index user.ts single-file (content changed) — the scoped watch path must
  // arrive at the same resolved edge, not drop it.
  write(
    "user.ts",
    "import { Foo } from './foo';\nexport function make2() { return new Foo(); }\n",
  );
  await indexFile(store, repoDir, join(repoDir, "user.ts"), { repo, branch });
  expect(await constructsCount(repo, branch)).toBe(1);
});

// ---------------------------------------------------------------------------
// PHP field-access provenance (bead MetaCoding-vju). scip-php emits no
// ReadAccess/WriteAccess roles, so the Tree-sitter heuristic lane is the ONLY
// source of PHP READS_FIELD/WRITES_FIELD edges. They must persist with a
// provenance marker so downstream consumers can tell them apart from
// SCIP-derived field edges.
// ---------------------------------------------------------------------------
async function fieldEdgeProvenance(
  kind: "READS_FIELD" | "WRITES_FIELD",
  repo: string,
): Promise<string[]> {
  const rows = await store.query<{ p: string | null }>(
    `MATCH (a:Symbol)-[e:${kind}]->(b:Symbol)
     WHERE a.repo = $repo
     RETURN e.provenance AS p`,
    { repo },
  );
  return rows.map((r) => r.p ?? "NULL");
}

test("PHP $this->field writes/reads persist as heuristic-provenance field edges", async () => {
  const repo = "vju";
  const branch = "main";
  write(
    "Widget.php",
    `<?php
class Widget {
  private $bar;
  public function m() {
    $this->bar = 1;
    $x = $this->bar;
    return $x;
  }
}
`,
  );
  await indexDirectory(store, repoDir, { repo, branch });

  const writes = await fieldEdgeProvenance("WRITES_FIELD", repo);
  const reads = await fieldEdgeProvenance("READS_FIELD", repo);
  expect(writes.length).toBe(1);
  expect(reads.length).toBe(1);
  // Every PHP field edge is heuristic — never SCIP-derived.
  expect(writes.every((p) => p === "tree_sitter_heuristic")).toBe(true);
  expect(reads.every((p) => p === "tree_sitter_heuristic")).toBe(true);
});
