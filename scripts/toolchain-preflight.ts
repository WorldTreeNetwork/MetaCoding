// scripts/toolchain-preflight.ts — the human-runnable form of the toolchain
// drift check (docs/design/lessons-as-mechanism.md mechanism 3, bead 0bm).
//
// WHICH SURFACE THIS SITS ON, said plainly (docs/design/enforceability.md)
// ------------------------------------------------------------------------
// NOT this script. enforceability.md was written after two correct gates were
// built in three days and NOTHING CALLED EITHER. A standalone script is a
// document with an exit code, and oracle_preflight.py is the proof in both
// directions: run by one build in five as a script, unavoidable the moment
// ledger.py imported it.
//
// So the enforcing surfaces for this mechanism are, in order:
//   1. THE IMPORT PATH — src/extractor/parser.ts registers the digest of the
//      .wasm blob it just read, between the read and the load. You cannot parse
//      without measuring the parser. `layer2Key()` then REFUSES to produce a
//      key when nothing was measured, so a parse-derived build cannot be keyed
//      blind to the grammar that produced it.
//   2. `bun test` — src/toolchain/preflight.test.ts runs THIS check against the
//      REAL toolchain.lock.json and the REAL node_modules, so `bun install`
//      pulling a different grammar turns the habitual command red.
//
// This file exists for the third case: a human who wants the report, and
// `--write` to re-declare the lock deliberately. It is born with published
// floors (docs/design/lessons-as-mechanism.md:288) rather than acquiring them
// later, because it is an instrument.
//
// Usage:
//   bun run scripts/toolchain-preflight.ts [--require-lanes] [--write] [--json]

import { writeFileSync } from "node:fs";
import { join } from "node:path";

import { GRAMMARS } from "../src/extractor/walker.ts";
import { beginRun } from "../src/testkit/floors.ts";
import { toolchainDigest } from "../src/toolchain/identity.ts";
import {
  explainToolchain,
  observeToolchain,
  relock,
  artifactsFrom,
  LOUD_OUTCOMES,
} from "../src/toolchain/preflight.ts";

const ROOT = join(import.meta.dir, "..");
const LOCK = join(ROOT, "toolchain.lock.json");

const argv = process.argv.slice(2);
const requireLanes = argv.includes("--require-lanes");
const write = argv.includes("--write");
const asJson = argv.includes("--json");

if (write) {
  // Deliberate re-declaration. This is the fakeable path and it says so.
  const next = relock({ root: ROOT, lockPath: LOCK });
  writeFileSync(LOCK, JSON.stringify(next, null, 2) + "\n", "utf-8");
  console.log(
    `toolchain.lock.json REWRITTEN from the installed toolchain ` +
      `(${Object.keys(next.lanes).length} lanes). This makes any drift green by ` +
      `construction — the only thing standing between that and a silent ` +
      `regrade is the diff you are about to commit. Read it.`,
  );
  process.exit(0);
}

const result = observeToolchain({ root: ROOT, lockPath: LOCK, requireLanes });
console.log(explainToolchain(result));

const grammarLanes = result.lanes.filter((l) => l.lane.startsWith("tree-sitter:"));
const notChecked = result.lanes.filter((l) => LOUD_OUTCOMES.includes(l.outcome));
const measured = artifactsFrom(result);

if (asJson) {
  console.log(JSON.stringify(result, null, 2));
}

// The toolchain digest the layer-2 key would fold in for THIS install. Printing
// it is what makes "the key moved" a thing a human can see rather than infer.
if (measured.length > 0) {
  console.log(`toolchain_digest (layer-2 key input) = ${toolchainDigest(measured)}`);
}

const run = beginRun("toolchain-preflight");
for (const l of result.lanes) {
  const acceptable =
    l.outcome === "OK" || (!requireLanes && LOUD_OUTCOMES.includes(l.outcome));
  // verdict(), not check(): check() throws on the first false, so one drifted
  // lane would shadow every later one and the report would name a single lane
  // when six had moved (the MetaCoding-u0l shape, recorded in floors.ts:401).
  run.verdict(`lane ${l.lane}`, acceptable, `${l.outcome} — ${l.detail}`);
}
run.measure("lanesDeclared", result.lanes.length, "count of lanes in toolchain.lock.json");
run.measure("lanesOk", result.counts.OK, "lanes whose installed digest equals the declared one");
run.measure("grammarLanes", grammarLanes.length, "declared lanes named tree-sitter:*");
run.measure(
  "lanesNotChecked",
  notChecked.length,
  "lanes reporting UNPINNED or SKIP_UNAVAILABLE — no answer, which is not no drift",
);

run.finish([
  {
    min: 8,
    measuredAs: "lanesDeclared",
    why:
      "A RATCHET, and disclosed as one: 8 was counted from toolchain.lock.json as " +
      "written (4 tree-sitter grammars + web-tree-sitter + scip-typescript + " +
      "scip-python + scip-php), which is the design document's own fake #4 — a " +
      "floor derived from the thing it measures can only ever catch a DELETION. " +
      "That is still worth having (deleting a lane is how this check gets quietly " +
      "narrowed, and it is the one thing a lock cannot report about itself) but it " +
      "is not evidence of coverage. The floor below is; so is assertCoverage() in " +
      "src/toolchain/preflight.test.ts, which runs under `bun test`.",
  },
  {
    min: GRAMMARS.length,
    measuredAs: "grammarLanes",
    why:
      `DERIVED, not counted: GRAMMARS.length (${GRAMMARS.length}) read at runtime ` +
      "from src/extractor/walker.ts, which is the array the `Grammar` type is now " +
      "derived FROM. A fifth grammar cannot typecheck without joining that array, " +
      "so it raises this floor the moment it is added and this check goes red " +
      "until the lock declares it. Before bead MetaCoding-7sv this floor was the " +
      "literal 4 and a fifth grammar would have parsed facts into the graph with " +
      "no digest in the key — bead 0bm restated, one grammar over.",
  },
]);
