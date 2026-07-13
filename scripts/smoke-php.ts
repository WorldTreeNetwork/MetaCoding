// scripts/smoke-php.ts
//
// Validates the PHP Tree-sitter extractor:
//   - top-level functions land as kind='function'
//   - classes/interfaces/traits/enums are recognized
//   - methods inside a class land as kind='method' and are CONTAIN-ed by it
//   - typed properties land as kind='field'
//   - the file Symbol's ast_hash gates incremental skip on a re-run
//   - FTS picks up identifiers
//
// Run with: bun run scripts/smoke-php.ts

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";

const FIX = resolve("./tmp-php-fixture");
const DATA = resolve("./tmp-php-data");

function cleanup(): void {
  for (const d of [FIX, DATA]) {
    if (existsSync(d)) rmSync(d, { recursive: true, force: true });
  }
}

const PHP_BODY = `<?php
namespace App\\Services;

interface Runner {
    public function run(int $x): int;
}

trait Loggable {
    public function log(string $m): void {}
}

abstract class Orchestrator implements Runner {
    use Loggable;

    public string $name = "demo";
    private int $count = 0;

    public function __construct(string $name) {
        $this->name = $name;
    }

    public function run(int $x): int {
        return helper($x);
    }

    public static function kind(): string {
        return "demo";
    }
}

function helper(int $x): int {
    return $x + 1;
}

enum Suit: string {
    case Hearts = 'H';
}
`;

async function main(): Promise<void> {
  cleanup();
  mkdirSync(FIX, { recursive: true });
  writeFileSync(join(FIX, "orchestrator.php"), PHP_BODY, "utf-8");

  const store = await Store.open(DATA);

  try {
    // Pass 1: full index.
    const r1 = await indexDirectory(store, FIX, { repo: "php-fixture", branch: "main" });
    if (r1.filesUpdated !== 1) {
      throw new Error(`expected 1 file updated; got ${JSON.stringify(r1)}`);
    }

    // Top-level members of the file.
    const tops = await store.query<{ kind: string; name: string }>(
      `MATCH (f:Symbol {kind: 'file'})-[:CONTAINS]->(s:Symbol)
       WHERE f.repo = 'php-fixture'
       RETURN s.kind AS kind, s.short_name AS name
       ORDER BY name`,
    );
    const flat = tops.map((t) => `${t.kind}:${t.name}`).sort();
    const expected = [
      "class:Loggable",
      "class:Orchestrator",
      "enum:Suit",
      "function:helper",
      "interface:Runner",
      "namespace:App\\Services",
    ].sort();
    if (JSON.stringify(flat) !== JSON.stringify(expected)) {
      throw new Error(`top-level mismatch:\n  got=${JSON.stringify(flat)}\n  exp=${JSON.stringify(expected)}`);
    }
    console.log(`top-level OK: ${flat.join(", ")}`);

    // Methods inside Orchestrator: __construct, run, kind.
    const methods = await store.query<{ name: string }>(
      `MATCH (c:Symbol {kind: 'class', short_name: 'Orchestrator'})
              -[:CONTAINS]->(m:Symbol {kind: 'method'})
       WHERE c.repo = 'php-fixture'
       RETURN m.short_name AS name
       ORDER BY name`,
    );
    const mNames = methods.map((m) => m.name).sort();
    const mExpected = ["__construct", "kind", "run"];
    if (JSON.stringify(mNames) !== JSON.stringify(mExpected)) {
      throw new Error(`methods mismatch: ${JSON.stringify(mNames)}`);
    }
    console.log(`methods OK: ${mNames.join(", ")}`);

    // Fields inside Orchestrator: name, count.
    const fields = await store.query<{ name: string }>(
      `MATCH (c:Symbol {kind: 'class', short_name: 'Orchestrator'})
              -[:CONTAINS]->(fld:Symbol {kind: 'field'})
       WHERE c.repo = 'php-fixture'
       RETURN fld.short_name AS name
       ORDER BY name`,
    );
    const fNames = fields.map((f) => f.name).sort();
    const fExpected = ["count", "name"];
    if (JSON.stringify(fNames) !== JSON.stringify(fExpected)) {
      throw new Error(`fields mismatch: ${JSON.stringify(fNames)}`);
    }
    console.log(`fields OK: ${fNames.join(", ")}`);

    // Pass 2: re-index, expect skip.
    const r2 = await indexDirectory(store, FIX, { repo: "php-fixture", branch: "main" });
    if (r2.filesSkipped !== 1 || r2.filesUpdated !== 0) {
      throw new Error(`re-index should be a no-op; got ${JSON.stringify(r2)}`);
    }
    console.log("incremental skip: 1 file skipped on re-run");

    // FTS: identifier search picks up `Orchestrator`.
    const hits = store.searchTokens("Orchestrator", 20);
    if (hits.length === 0) throw new Error("FTS missed 'Orchestrator'");
    console.log(`fts OK: ${hits.length} hits for 'Orchestrator'`);

    console.log("PHP_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("PHP_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
