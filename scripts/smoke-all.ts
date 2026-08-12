// scripts/smoke-all.ts — the suite runner, and the half of mechanism 4 that is
// not opt-in.
//
// WHY THIS EXISTS
// ===============
// src/testkit/floors.ts is opt-in by construction: a script that never calls
// beginRun() is not checked by it. That is failure 4's shape — a guard in a
// library the caller did not import — and lessons-as-mechanism.md:274 names it
// as a known weakness of mechanisms 1, 4 and 5. The bracket is the answer
// there, and this file is the bracket for the smoke suite: it runs the scripts
// and REFUSES ONE THAT EMITTED NO RECORD. A script cannot opt out by not
// importing anything, because the check is not in its import graph.
//
// It also refuses a suite LIST that has drifted from the directory. Today the
// list lives in package.json's `smoke` script as a && chain, and nothing
// notices when a new scripts/smoke-*.ts is never added to it — the suite gets
// quietly narrower and every run still says PASS. That is the same shape as a
// truncated script, one level up.
//
// KNOWN RED, NOT CHASED: several scripts fail at baseline for reasons that
// predate this file (MetaCoding-6ep and an indexDirectory signature drift).
// This runner reports them; it does not fix them and does not paper over them.
//
// Run: bun run scripts/smoke-all.ts [--keep-going] [--only <substr>]

import { readdirSync } from "node:fs";
import { join } from "node:path";

import { beginRun, type Floor } from "../src/testkit/floors.ts";

const SCRIPTS_DIR = join(import.meta.dir);

/**
 * The suite, in order. Order is load-bearing where a later script reuses an
 * earlier one's artifacts, so this is a list and not a glob — but it is
 * CHECKED against the glob below, which is what makes the list honest.
 */
const SUITE = [
  "smoke-ladybug.ts",
  "smoke-store.ts",
  "smoke-extractor.ts",
  "smoke-mcp-tools.ts",
  "smoke-scip.ts",
  "smoke-lsp.ts",
  "smoke-lsp-php.ts",
  "smoke-incremental.ts",
  "smoke-python.ts",
  "smoke-php.ts",
  "smoke-multirepo.ts",
  "smoke-paths.ts",
  "smoke-commit-sha.ts",
  "smoke-worktree-branch.ts",
  "smoke-mcp-scope.ts",
  "smoke-fts-sha.ts",
  "smoke-per-commit-identity.ts",
  "smoke-graph-diff.ts",
  "smoke-data-dir.ts",
  "smoke-summary.ts",
  "smoke-readonly.ts",
  "smoke-reopen.ts",
];

/**
 * Every smoke script on disk. The runner and any *.test.ts beside it are not
 * smoke scripts — the first version of this filter swept in smoke-all.test.ts
 * and the live agreement assertion below is what caught it.
 */
export function scriptsOnDisk(dir: string = SCRIPTS_DIR): string[] {
  return readdirSync(dir)
    .filter(
      (f) =>
        f.startsWith("smoke-") &&
        f.endsWith(".ts") &&
        !f.endsWith(".test.ts") &&
        f !== "smoke-all.ts",
    )
    .sort();
}

/** Scripts on disk that the suite never runs. A silently narrower suite. */
export function unlisted(disk: string[] = scriptsOnDisk(), suite: string[] = SUITE): string[] {
  const listed = new Set(suite);
  return disk.filter((f) => !listed.has(f));
}

/** Scripts the suite lists that are not on disk. A suite naming a ghost. */
export function missing(disk: string[] = scriptsOnDisk(), suite: string[] = SUITE): string[] {
  const present = new Set(disk);
  return suite.filter((f) => !present.has(f));
}

export interface ScriptOutcome {
  script: string;
  exitCode: number;
  /** The parsed SMOKE_RECORD, or null if the script emitted none. */
  record: { published: Record<string, number>; checkLabels: string[] } | null;
}

export function parseRecord(stdout: string): ScriptOutcome["record"] {
  const line = stdout
    .split("\n")
    .reverse()
    .find((l) => l.startsWith("SMOKE_RECORD "));
  if (!line) return null;
  try {
    return JSON.parse(line.slice("SMOKE_RECORD ".length));
  } catch {
    return null;
  }
}

async function runScript(script: string): Promise<ScriptOutcome> {
  const proc = Bun.spawn(["bun", "run", join(SCRIPTS_DIR, script)], {
    stdout: "pipe",
    stderr: "pipe",
  });
  const [out, err] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  const exitCode = await proc.exited;
  process.stdout.write(out);
  if (exitCode !== 0) process.stderr.write(err);
  return { script, exitCode, record: parseRecord(out) };
}

async function main(): Promise<void> {
  const keepGoing = process.argv.includes("--keep-going");
  const onlyAt = process.argv.indexOf("--only");
  const only = onlyAt >= 0 ? process.argv[onlyAt + 1] : undefined;

  const run = beginRun("smoke-all");

  // 1. The suite list must match the directory, both ways. This runs even when
  //    --only narrows the execution, because it is about the LIST, not the run.
  const disk = scriptsOnDisk();
  const notListed = unlisted(disk);
  const notOnDisk = missing(disk);
  run.check(
    "every smoke script on disk is in the suite",
    notListed.length === 0,
    `unlisted: ${notListed.join(", ")} — the suite is silently narrower than the directory`,
  );
  run.check(
    "every script the suite lists exists on disk",
    notOnDisk.length === 0,
    `missing: ${notOnDisk.join(", ")}`,
  );

  const selected = only ? SUITE.filter((s) => s.includes(only)) : SUITE;
  run.check("the selection is non-empty", selected.length > 0, `--only ${only} matched nothing`);

  // 2. Run them.
  const outcomes: ScriptOutcome[] = [];
  const failed: string[] = [];
  const silent: string[] = [];
  for (const script of selected) {
    console.log(`\n--- ${script}`);
    const o = await runScript(script);
    outcomes.push(o);
    if (o.exitCode !== 0) failed.push(script);
    // THE BRACKET: exit 0 and no record is not a pass. A script that never
    // reached a floors gate has not said what it ran, and "it printed nothing
    // and nothing was said" is the shape this whole mechanism refuses.
    else if (o.record === null) silent.push(script);
    if ((o.exitCode !== 0 || o.record === null) && !keepGoing) break;
  }

  console.log(`\n=== suite summary`);
  for (const o of outcomes) {
    const c = o.record?.published.checks;
    console.log(
      `  ${o.exitCode === 0 ? "ok  " : "FAIL"} ${o.script.padEnd(32)} ` +
        `${o.record === null ? "NO RECORD" : `checks=${c} pairs=${o.record.published.pairs}`}`,
    );
  }

  run.check("no script exited non-zero", failed.length === 0, `failed: ${failed.join(", ")}`);
  run.check(
    "no script exited 0 without emitting a record",
    silent.length === 0,
    `silent: ${silent.join(", ")} — exit 0 is not evidence that anything ran`,
  );

  // 3. The suite's OWN floors. `scripts` and `checks` are derived: `scripts`
  //    counts records actually parsed, so a script dropped from SUITE lowers it.
  const scriptsWithRecords = outcomes.filter((o) => o.record !== null).length;
  const checksAcrossSuite = outcomes.reduce(
    (n, o) => n + (o.record?.published.checks ?? 0),
    0,
  );
  run.measure(
    "scriptsReported",
    scriptsWithRecords,
    "counted: outcomes whose stdout carried a parseable SMOKE_RECORD",
  );
  run.measure(
    "checksAcrossSuite",
    checksAcrossSuite,
    "summed: published.checks over every record parsed this run",
  );

  const floors: Floor[] = [
    {
      min: 5,
      measuredAs: "checks",
      why: "counted from the source: this runner makes 5 check() calls (list drift x2, selection non-empty, no failures, no silent scripts)",
    },
  ];
  // Suite-wide floors only bind a FULL run; --only deliberately narrows it and
  // saying so is better than a floor that quietly does not apply.
  if (!only) {
    floors.push({
      min: SUITE.length,
      measuredAs: "scriptsReported",
      why: `one record per script in SUITE (${SUITE.length}); fewer means a script ran without publishing what it ran`,
    });
    floors.push({
      min: 58,
      measuredAs: "checksAcrossSuite",
      why: "58 = the assertion sites counted from the source of the 10 scripts green at baseline (5+5+5+7+6+10+5+7+3+5); it is a FLOOR, and it rises as the red scripts are repaired",
    });
  }

  run.finish(floors);
}

// The runner is itself an instrument, so its own refusal must be loud and its
// exit code must be the suite's.
if (import.meta.main) {
  main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("SMOKE_ALL_FAIL", err instanceof Error ? err.message : String(err));
    process.exit(1);
  });
}

/** Floors for this runner, re-exported so a test can assert on them. */
export const SUITE_SIZE = SUITE.length;
