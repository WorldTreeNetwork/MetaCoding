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
// and REFUSES ONE THAT EMITTED NO RECORD. A script cannot opt out by staying
// SILENT, because the check is not in its import graph.
//
// WHAT IT CANNOT DO, and the first draft of this comment claimed it could
// (MetaCoding-870): it cannot detect FORGERY. A stub that imports nothing and
// prints two console.log lines — a hand-written SMOKE_RECORD with checks:9999
// and a PASS token — satisfies this bracket, counts toward scriptsReported, and
// carries the checksAcrossSuite floor on its own say-so. A fresh adversary did
// exactly that and the suite went green. Detecting forgery would need the child
// to PROVE it ran the code, which nothing here can ask for, so the claim is
// narrowed to what it can back rather than left overstated:
//
//   this bracket refuses SILENCE and MIS-EXIT. It does not authenticate counts.
//
// The two holes that were real defects rather than limits are closed below: the
// child's own `ok:false` is now read and refused (it was parsed and discarded),
// and the entrypoint's exit code is now asserted by a test (it was stated as
// load-bearing in the source and asserted by nothing — flipping exit(1) to
// exit(0) turned every red suite green and `bun test` stayed 75/0).
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

import { FloorsRefused, beginRun, evaluateFloors, type Floor } from "../src/testkit/floors.ts";

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
export function unlisted(
  disk: string[] = scriptsOnDisk(),
  suite: readonly string[] = SUITE,
): string[] {
  const listed = new Set(suite);
  return disk.filter((f) => !listed.has(f));
}

/** Scripts the suite lists that are not on disk. A suite naming a ghost. */
export function missing(
  disk: string[] = scriptsOnDisk(),
  suite: readonly string[] = SUITE,
): string[] {
  const present = new Set(disk);
  return suite.filter((f) => !present.has(f));
}

export interface ScriptOutcome {
  script: string;
  exitCode: number;
  /** The parsed SMOKE_RECORD, or null if the script emitted none. */
  record: {
    published: Record<string, number>;
    checkLabels: string[];
    /** The floors the child says it gated itself on. Re-run by the parent. */
    floors?: Floor[];
    /** The child's OWN verdict on itself. Parsed and then DISCARDED until
     *  MetaCoding-870: a script could publish ok:false and still be counted as
     *  a reporting script. Its own no is now a refusal. */
    ok?: boolean;
  } | null;
}

/**
 * Re-run the child's OWN declared floors against its OWN published numbers,
 * with the ADVERTISED verb. Returns null when they hold, or the named failures.
 *
 * WHY (MetaCoding-cn0): `evaluateFloors` had zero production callers. Every real
 * gate went through `SmokeRun.finish()`, which reaches the same refusal by its
 * own code — TWO COPIES OF ONE INVARIANT, one of them dead. A dead copy is a
 * copy nothing keeps in step: the day finish() and evaluateFloors disagree,
 * nothing would say so. This is where they are made to agree, on real records,
 * on every run.
 *
 * It cannot detect FORGERY — a forged record is internally consistent, and the
 * header says so. What it detects is a record that CONTRADICTS ITSELF: exit 0
 * and `ok:true` while a floor the child published is unmet, or measured against
 * a field the child did not publish, or no floors at all. That is the same
 * refusal one level up, and it is the child's own numbers doing the refusing.
 */
export function recheckOwnFloors(record: NonNullable<ScriptOutcome["record"]>): string | null {
  try {
    evaluateFloors(record.floors ?? [], record.published);
    return null;
  } catch (e) {
    if (!(e instanceof FloorsRefused)) throw e;
    return e.result.failures.map((f) => `${f.tier} ${f.kind}`).join(", ");
  }
}

/**
 * The suite's exit code, and the ONE decision that reads `instrumentFailed`.
 *
 * WHY (MetaCoding-cn0): the INSTRUMENT/CHECK tier was a word in a diagnostic
 * string and an assertion about itself — both tiers threw the same error and
 * exited the same 1, so "structurally distinct" was distinct in the report and
 * in no decision. They are different diagnoses and they need different
 * responses: a CHECK failure says the run came up short and the operator reads
 * the numbers; an INSTRUMENT failure says the apparatus is broken and the
 * numbers mean nothing yet. Exit 2 is that difference, machine-readable, so a
 * CI job can route the two without parsing prose.
 */
export function suiteExitCode(err: unknown): number {
  return err instanceof FloorsRefused && err.result.instrumentFailed ? 2 : 1;
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

async function runScript(dir: string, script: string): Promise<ScriptOutcome> {
  const proc = Bun.spawn(["bun", "run", join(dir, script)], {
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

/**
 * Options for one suite run. The DIR and the SUITE are parameters rather than
 * the constants above for exactly one reason: main() below is where the bracket
 * lives, and a bracket nothing drives is a bracket nothing has ever measured.
 * A judge deleted the bracket, replaced its refusal with a literal `true`, and
 * dropped the suite floors whole — five mutations, all SURVIVING the suite,
 * because smoke-all.test.ts could only reach the four pure helpers
 * (MetaCoding-6a0). The fixture suites in src/testkit/fixtures/smoke-suite/
 * drive THIS function as a real subprocess over real stub scripts.
 */
export interface SuiteOptions {
  dir: string;
  suite: readonly string[];
  keepGoing?: boolean;
  only?: string;
  /**
   * Floor over the suite-wide check total. Only a FULL run declares one:
   * --only deliberately narrows the run, and saying so is better than a floor
   * that quietly does not apply.
   */
  checksAcrossSuiteFloor?: number;
  /** Names the run, and supplies the PASS token's prefix. */
  runName?: string;
}

export async function runSuite(opts: SuiteOptions): Promise<void> {
  const { dir, suite, keepGoing = false, only } = opts;
  const run = beginRun(opts.runName ?? "smoke-all");

  // EVERY suite-level outcome is a `verdict`, not a `check`. `check()` throws
  // on the first false, and that made the bracket UNREACHABLE: with 12 of 22
  // scripts red, "no script exited non-zero" threw before "no script exited 0
  // without emitting a record" was ever asked, before the measures, and before
  // the floors were evaluated (MetaCoding-u0l, measured — the bracket had never
  // fired in this repo). `verdict()` holds the refusal until finish(), so an
  // ordinary failure cannot shadow the fundamental one and the record is still
  // emitted.

  // 1. The suite list must match the directory, both ways. This runs even when
  //    --only narrows the execution, because it is about the LIST, not the run.
  const disk = scriptsOnDisk(dir);
  const notListed = unlisted(disk, suite);
  const notOnDisk = missing(disk, suite);
  run.verdict(
    "every smoke script on disk is in the suite",
    notListed.length === 0,
    `unlisted: ${notListed.join(", ")} — the suite is silently narrower than the directory`,
  );
  run.verdict(
    "every script the suite lists exists on disk",
    notOnDisk.length === 0,
    `missing: ${notOnDisk.join(", ")}`,
  );

  const selected = only ? suite.filter((s) => s.includes(only)) : [...suite];
  run.verdict("the selection is non-empty", selected.length > 0, `--only ${only} matched nothing`);

  // 2. Run them.
  const outcomes: ScriptOutcome[] = [];
  const failed: string[] = [];
  const silent: string[] = [];
  const selfRefused: string[] = [];
  const contradicted: string[] = [];
  for (const script of selected) {
    console.log(`\n--- ${script}`);
    const o = await runScript(dir, script);
    outcomes.push(o);
    if (o.exitCode !== 0) failed.push(script);
    // THE BRACKET: exit 0 and no record is not a pass. A script that never
    // reached a floors gate has not said what it ran, and "it printed nothing
    // and nothing was said" is the shape this whole mechanism refuses.
    else if (o.record === null) silent.push(script);
    // ...and a record that says ok:false while the script exits 0 is a script
    // contradicting itself. This was parsed and DISCARDED (MetaCoding-870): the
    // child's own no was the one piece of evidence here written by the party
    // that actually ran, and it was the piece being ignored.
    else if (o.record.ok === false) selfRefused.push(script);
    // ...and a script claiming ok:true whose OWN floors do not hold against its
    // OWN published numbers is refused by the advertised verb, on its own say-so.
    else {
      const contradiction = recheckOwnFloors(o.record);
      if (contradiction !== null) contradicted.push(`${script} (${contradiction})`);
    }
    if (
      (o.exitCode !== 0 ||
        o.record === null ||
        o.record.ok === false ||
        contradicted.length > 0) &&
      !keepGoing
    ) {
      break;
    }
  }

  console.log(`\n=== suite summary`);
  for (const o of outcomes) {
    const c = o.record?.published.checks;
    console.log(
      `  ${o.exitCode === 0 ? "ok  " : "FAIL"} ${o.script.padEnd(32)} ` +
        `${o.record === null ? "NO RECORD" : `checks=${c} pairs=${o.record.published.pairs}`}`,
    );
  }

  run.verdict("no script exited non-zero", failed.length === 0, `failed: ${failed.join(", ")}`);
  run.verdict(
    "no script exited 0 without emitting a record",
    silent.length === 0,
    `silent: ${silent.join(", ")} — exit 0 is not evidence that anything ran`,
  );
  run.verdict(
    "no script exited 0 while its own record says ok:false",
    selfRefused.length === 0,
    `self-refused: ${selfRefused.join(", ")} — the script published its own no and exited 0`,
  );
  run.verdict(
    "no script's own floors are unmet by its own record",
    contradicted.length === 0,
    `contradicted: ${contradicted.join(", ")} — the script exited 0 and said ok:true, ` +
      `and re-running the floors IT published against the numbers IT published refuses`,
  );

  // 3. The suite's OWN floors. `scriptsReported` counts records actually
  //    parsed, so a script that ran without publishing lowers it — the same
  //    refusal as the bracket, stated as a number instead of a name.
  const scriptsWithRecords = outcomes.filter((o) => o.record !== null).length;
  const checksAcrossSuite = outcomes.reduce((n, o) => n + (o.record?.published.checks ?? 0), 0);
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
      min: 7,
      measuredAs: "checks",
      why: "counted from the source: this runner makes 7 verdict() calls (list drift x2, selection non-empty, no failures, no silent scripts, no self-refused scripts, no script contradicting its own floors)",
    },
  ];
  if (selected.length > 0) {
    // Binds the SELECTED set, not only a full run: --only narrows what runs, it
    // does not license a script to run without saying what it ran.
    floors.push({
      min: selected.length,
      measuredAs: "scriptsReported",
      why: `one record per script actually selected (${selected.length}); fewer means a script ran without publishing what it ran`,
    });
  }
  if (opts.checksAcrossSuiteFloor !== undefined) {
    floors.push({
      min: opts.checksAcrossSuiteFloor,
      measuredAs: "checksAcrossSuite",
      why: `${opts.checksAcrossSuiteFloor} = the assertion sites counted from the source of the scripts green at baseline; it is a FLOOR, and it rises as the red scripts are repaired`,
    });
  }

  run.finish(floors);
}

async function main(): Promise<void> {
  const keepGoing = process.argv.includes("--keep-going");
  const onlyAt = process.argv.indexOf("--only");
  const only = onlyAt >= 0 ? process.argv[onlyAt + 1] : undefined;

  await runSuite({
    dir: SCRIPTS_DIR,
    suite: SUITE,
    keepGoing,
    only,
    // 58 = 5+5+5+7+6+10+5+7+3+5, counted from the source of the 10 scripts
    // green at baseline. A narrowed run does not get to carry a full run's floor.
    checksAcrossSuiteFloor: only ? undefined : 58,
  });
}

// The runner is itself an instrument, so its own refusal must be loud and its
// exit code must be the suite's — and WHICH non-zero code is the tier.
if (import.meta.main) {
  main()
  .then(() => process.exit(0))
  .catch((err) => {
    const code = suiteExitCode(err);
    console.error(
      code === 2 ? "SMOKE_ALL_INSTRUMENT_FAIL" : "SMOKE_ALL_FAIL",
      err instanceof Error ? err.message : String(err),
    );
    process.exit(code);
  });
}

/** Floors for this runner, re-exported so a test can assert on them. */
export const SUITE_SIZE = SUITE.length;
