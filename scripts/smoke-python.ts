// scripts/smoke-python.ts
//
// Validates the Python Tree-sitter extractor:
//   - top-level functions land as kind='function'
//   - methods inside a class land as kind='method' and CONTAIN-ed by it
//   - decorators don't break declaration recognition
//   - file Symbol's ast_hash gates incremental skip on a re-run
//
// Run with: bun run scripts/smoke-python.ts

import { existsSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { Store } from "../src/store";
import { indexDirectory } from "../src/extractor";

const FIX = resolve("./tmp-py-fixture");
const DATA = resolve("./tmp-py-data");

function cleanup(): void {
  for (const d of [FIX, DATA]) {
    if (existsSync(d)) rmSync(d, { recursive: true, force: true });
  }
}

const PY_BODY = `# orchestrator.py
from typing import Any


def helper(x: int) -> int:
    return x + 1


class Orchestrator:
    """A toy orchestrator."""

    def __init__(self, name: str):
        self.name = name

    def run(self, payload: Any) -> Any:
        return helper(payload)

    @staticmethod
    def kind() -> str:
        return "demo"


async def amain() -> None:
    o = Orchestrator("a")
    o.run(1)
`;

async function main(): Promise<void> {
  cleanup();
  mkdirSync(FIX, { recursive: true });
  writeFileSync(join(FIX, "orchestrator.py"), PY_BODY, "utf-8");

  const store = await Store.open(DATA);

  try {
    // Pass 1: full index.
    const r1 = await indexDirectory(store, FIX, { repo: "py-fixture", branch: "main" });
    if (r1.filesUpdated !== 1) {
      throw new Error(`expected 1 file updated; got ${JSON.stringify(r1)}`);
    }

    // Top-level: helper (function), Orchestrator (class), amain (function).
    const tops = await store.query<{ kind: string; name: string }>(
      `MATCH (f:Symbol {kind: 'file'})-[:CONTAINS]->(s:Symbol)
       WHERE f.repo = 'py-fixture'
       RETURN s.kind AS kind, s.short_name AS name
       ORDER BY name`,
    );
    const flat = tops.map((t) => `${t.kind}:${t.name}`).sort();
    const expected = ["class:Orchestrator", "function:amain", "function:helper"];
    if (JSON.stringify(flat) !== JSON.stringify(expected)) {
      throw new Error(`top-level mismatch: ${JSON.stringify(flat)}`);
    }
    console.log(`top-level OK: ${flat.join(", ")}`);

    // Methods inside Orchestrator: __init__, run, kind.
    const methods = await store.query<{ name: string }>(
      `MATCH (c:Symbol {kind: 'class', short_name: 'Orchestrator'})
              -[:CONTAINS]->(m:Symbol {kind: 'method'})
       WHERE c.repo = 'py-fixture'
       RETURN m.short_name AS name
       ORDER BY name`,
    );
    const mNames = methods.map((m) => m.name).sort();
    const mExpected = ["__init__", "kind", "run"];
    if (JSON.stringify(mNames) !== JSON.stringify(mExpected)) {
      throw new Error(`methods mismatch: ${JSON.stringify(mNames)}`);
    }
    console.log(`methods OK: ${mNames.join(", ")}`);

    // Pass 2: re-index, expect skip.
    const r2 = await indexDirectory(store, FIX, { repo: "py-fixture", branch: "main" });
    if (r2.filesSkipped !== 1 || r2.filesUpdated !== 0) {
      throw new Error(`re-index should be a no-op; got ${JSON.stringify(r2)}`);
    }
    console.log("incremental skip: 1 file skipped on re-run");

    // FTS: identifier search picks up `Orchestrator`.
    const hits = store.searchTokens("Orchestrator", 20);
    if (hits.length === 0) throw new Error("FTS missed 'Orchestrator'");
    console.log(`fts OK: ${hits.length} hits for 'Orchestrator'`);

    console.log("PYTHON_SMOKE_PASS");
  } finally {
    await store.close();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("PYTHON_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
