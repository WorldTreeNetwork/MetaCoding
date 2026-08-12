// Evidence for scripts/smoke-all.ts — the suite-level bracket.
//
// Each check exercises a REFUTING outcome and its contrast, because a guard
// shown only in its passing state cannot be told apart from a guard that
// cannot fire.

import { describe, expect, test } from "bun:test";

import { SUITE_SIZE, missing, parseRecord, scriptsOnDisk, unlisted } from "./smoke-all.ts";

describe("the suite list must match the directory", () => {
  test("a script on disk that the suite never runs is NAMED", () => {
    const disk = ["smoke-a.ts", "smoke-b.ts", "smoke-new.ts"];
    expect(unlisted(disk, ["smoke-a.ts", "smoke-b.ts"])).toEqual(["smoke-new.ts"]);
    // Contrast: the complete list reports nothing.
    expect(unlisted(disk, disk)).toEqual([]);
  });

  test("a script the suite lists but that does not exist is NAMED", () => {
    expect(missing(["smoke-a.ts"], ["smoke-a.ts", "smoke-ghost.ts"])).toEqual(["smoke-ghost.ts"]);
    expect(missing(["smoke-a.ts"], ["smoke-a.ts"])).toEqual([]);
  });

  test("the REAL directory and the REAL suite agree right now", () => {
    // This is the one that fires when someone adds scripts/smoke-foo.ts and
    // forgets the runner. It is a live assertion, not a fixture.
    const disk = scriptsOnDisk();
    expect(unlisted(disk)).toEqual([]);
    expect(missing(disk)).toEqual([]);
    expect(disk.length).toBe(SUITE_SIZE);
  });

  test("the runner does not count itself as a smoke script", () => {
    expect(scriptsOnDisk()).not.toContain("smoke-all.ts");
    // Contrast: it does see the ordinary ones.
    expect(scriptsOnDisk()).toContain("smoke-store.ts");
  });
});

describe("exit 0 without a record is not a pass", () => {
  test("stdout carrying no SMOKE_RECORD parses to null", () => {
    expect(parseRecord("some output\nSTORE_SMOKE_PASS\n")).toBeNull();
    expect(parseRecord("")).toBeNull();
  });

  test("a record is parsed, and the LAST one wins", () => {
    const one = parseRecord('SMOKE_RECORD {"published":{"checks":3},"checkLabels":["a"]}\n');
    expect(one!.published.checks).toBe(3);
    // A script that spawns a child smoke script emits two records; the
    // parent's is last, and it is the one that describes this run.
    const two = parseRecord(
      'SMOKE_RECORD {"published":{"checks":1},"checkLabels":[]}\n' +
        'SMOKE_RECORD {"published":{"checks":9},"checkLabels":[]}\n',
    );
    expect(two!.published.checks).toBe(9);
  });

  test("a MALFORMED record is null, not a silently accepted pass", () => {
    // Absence of an answer is never a pass, and neither is an unreadable one.
    expect(parseRecord("SMOKE_RECORD {not json}\n")).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// THE BRACKET, DRIVEN (MetaCoding-6a0).
//
// Everything above this line tests the four pure helpers. main() — where the
// bracket lives — was asserted by NOTHING, and a judge proved it: five
// mutations (delete the silent-script collection; replace the bracket's
// refusal with a literal `true`; scriptsReported = SUITE.length; drop the
// suite floors whole; lower the runner's own checks floor 5 -> 1) all survived
// the full test suite. Each case below drives runSuite() over a real stub
// suite in a real subprocess, and each names the mutation it kills.
//
// MEASURED, not assumed. Isolated clone at /tmp/rjx-mut, absolute paths, each
// anchor matched EXACTLY ONCE, each mutant parse-checked, baseline 75 pass /
// 0 fail before AND after the run. 12 mutants, 12 KILLED:
//   N6   delete `silent.push(script)`                            KILLED
//   N7   the bracket's refusal -> literal `true`                 KILLED
//   N9   scriptsReported = selected.length, not records parsed   KILLED
//   N10  the checksAcrossSuite floor dropped whole               KILLED
//   N10b the scriptsReported floor dropped whole                 KILLED
//   N11  the runner's own checks floor 5 -> 1                    KILLED
//   N12  the exit-code verdict back to check() (shadows again)   KILLED
//   V1   finish() swallows held verdicts                         KILLED
//   V2   a FAILING verdict counted as a passing check            KILLED
//   V3   a refused label re-used to count a passing check        KILLED
//   P1   measure() accepts a value with no provenance            KILLED
//   P2   every floor reported as `derived`                       KILLED
// N6/N7/N9/N10/N11 are five of the ten the judge ran that SURVIVED before this
// block existed.
// ---------------------------------------------------------------------------

const SUITE_FIXTURE = "src/testkit/fixtures/smoke-suite-fixture.ts";

interface SuiteRan {
  code: number;
  stdout: string;
  stderr: string;
  /** The runner's OWN record — the last one, after the stub scripts' records. */
  record: {
    published: Record<string, number>;
    checkLabels: string[];
    refused: Array<{ label: string; detail: string }>;
    floors: Array<{ min: number; measuredAs: string; basis: string }>;
    ok: boolean;
  } | null;
}

async function runSuiteFixture(fixtureCase: string): Promise<SuiteRan> {
  const proc = Bun.spawn(["bun", "run", SUITE_FIXTURE], {
    cwd: new URL("..", import.meta.url).pathname,
    env: { ...process.env, SUITE_FIXTURE_CASE: fixtureCase, SMOKE_RECORD_FILE: "" },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  const code = await proc.exited;
  const line = stdout
    .split("\n")
    .reverse()
    .find((l) => l.startsWith("SMOKE_RECORD ") && l.includes('"fixture-suite"'));
  return { code, stdout, stderr, record: line ? JSON.parse(line.slice(13)) : null };
}

describe("the bracket refuses a script that exited 0 and said nothing", () => {
  test("CONTRAST: an all-green suite passes and the runner emits its OWN record", async () => {
    const r = await runSuiteFixture("green");
    expect(r.code).toBe(0);
    expect(r.stdout).toContain("FIXTURE_SUITE_SMOKE_PASS");
    expect(r.record).not.toBeNull();
    expect(r.record!.ok).toBe(true);
    expect(r.record!.refused).toEqual([]);
    // The runner's own SIX verdicts, all held (the sixth is the self-refusal
    // check added for MetaCoding-870).
    expect(r.record!.published.checks).toBe(6);
    // Derived, not declared: two stub scripts, 3 + 2 checks between them.
    expect(r.record!.published.scriptsReported).toBe(2);
    expect(r.record!.published.checksAcrossSuite).toBe(5);
  });

  test("REFUTING: a silent script is NAMED, and no PASS token is printed", async () => {
    // Kills: deleting `silent.push(script)`, and replacing the bracket's
    // refusal with a literal `true`.
    const r = await runSuiteFixture("silent");
    expect(r.code).toBe(1);
    expect(r.stdout).not.toContain("FIXTURE_SUITE_SMOKE_PASS");
    expect(r.stderr).toContain("CHECK_REFUSED");
    expect(r.stderr).toContain("no script exited 0 without emitting a record");
    expect(r.stderr).toContain("smoke-silent.ts");
    // The silent script itself exited 0 and printed its own PASS line: that is
    // exactly why the bracket cannot live inside it.
    expect(r.stdout).toContain("SILENT_SMOKE_PASS");
  });

  test("a RED script does not shadow a silent one: BOTH are named", async () => {
    // MetaCoding-u0l stated as an equality. Under the old check()-throws-first
    // ordering the second label never appeared at all.
    const r = await runSuiteFixture("red-and-silent");
    expect(r.code).toBe(1);
    expect(r.record).not.toBeNull();
    expect(r.record!.refused.map((x) => x.label)).toEqual([
      "no script exited non-zero",
      "no script exited 0 without emitting a record",
    ]);
    expect(r.stderr).toContain("smoke-red.ts");
    expect(r.stderr).toContain("smoke-silent.ts");
    // And the runner still reached its gate: floors EVALUATED, not skipped.
    expect(r.stderr).toContain("FLOOR_UNMET");
    expect(r.record!.published.scriptsReported).toBe(1);
  });

  test("scriptsReported counts RECORDS PARSED, not the size of the suite", async () => {
    // Kills: scriptsReported = SUITE.length. Under that mutation the silent
    // suite reports 2 and the floor of 2 passes.
    const silent = await runSuiteFixture("silent");
    expect(silent.record!.published.scriptsReported).toBe(1);
    expect(silent.record!.floors).toContainEqual({
      min: 2,
      measuredAs: "scriptsReported",
      why: expect.any(String),
      basis: "measured",
    });
    expect(silent.stderr).toContain('"scriptsReported" = 1, floor is 2');
    // CONTRAST: the same floor over a suite where every script published.
    const green = await runSuiteFixture("green");
    expect(green.record!.published.scriptsReported).toBe(2);
  });

  test("the suite floors are DECLARED and BINDING, not dropped", async () => {
    // Kills: `if (!only)` -> `if (false)`, and any deletion of the floor list.
    const green = await runSuiteFixture("green");
    const named = green.record!.floors.map((f) => f.measuredAs).sort();
    expect(named).toEqual(["checks", "checksAcrossSuite", "scriptsReported"]);
    // REFUTING: one higher than the suite actually runs, and it fires by name.
    const unmet = await runSuiteFixture("green-floor-unmet");
    expect(unmet.code).toBe(1);
    expect(unmet.stderr).toContain('"checksAcrossSuite" = 5, floor is 6');
    expect(unmet.stdout).not.toContain("FIXTURE_SUITE_SMOKE_PASS");
  });

  test("the runner's own checks floor equals the verdicts it makes", async () => {
    // Kills: lowering the runner's floor 5 -> 1. The floor is not free-floating
    // — it is pinned to the labels the green run actually recorded.
    const green = await runSuiteFixture("green");
    const own = green.record!.floors.find((f) => f.measuredAs === "checks")!;
    expect(own.min).toBe(green.record!.checkLabels.length);
    // 6 since MetaCoding-870 added the self-refusal verdict. Bumping this is the
    // point: the floor is pinned to the labels a green run actually recorded, so
    // a new verdict cannot be added without someone raising the number on purpose.
    expect(own.min).toBe(6);
    expect(own.basis).toBe("derived");
    // REFUTING: a run that reaches only 3 of them fails that floor by name.
    const red = await runSuiteFixture("red-and-silent");
    // 4 of 6 since the self-refusal verdict: a partial run reaches one more check
    // before it refuses. The pair still discriminates — the point is that the
    // truncated run fails its own floor BY NAME, not the specific integers.
    expect(red.stderr).toContain('"checks" = 4, floor is 6');
  });

  test("a script on disk the suite never runs is refused by the RUNNER", async () => {
    const r = await runSuiteFixture("drift");
    expect(r.code).toBe(1);
    expect(r.stderr).toContain("every smoke script on disk is in the suite");
    expect(r.stderr).toContain("smoke-unlisted.ts");
  });

  test("--only narrows the run but not the obligation to publish", async () => {
    const r = await runSuiteFixture("only");
    expect(r.code).toBe(0);
    expect(r.record!.published.scriptsReported).toBe(1);
    // The record floor still binds the one script that ran; only the suite-wide
    // check total is withheld from a narrowed run.
    expect(r.record!.floors.map((f) => f.measuredAs)).toEqual(["checks", "scriptsReported"]);
    // REFUTING: a selection that matches nothing is a refusal, not an empty green.
    const none = await runSuiteFixture("only-matches-nothing");
    expect(none.code).toBe(1);
    expect(none.stderr).toContain("the selection is non-empty");
  });
});

// ---------------------------------------------------------------------------
// The ENTRYPOINT, not runSuite() — MetaCoding-l3b and the J3 survivor
// ---------------------------------------------------------------------------
// A fresh adversary mutated `process.exit(1)` to `process.exit(0)` in this
// file's entrypoint and NOTHING NOTICED: the suite went green with floors unmet
// and `ok:false` in its own record, and `bun test` stayed 75/0. One character
// turns every future red suite green for package.json's smoke chain.
//
// The cases above drive runSuite() — the seam — and the block comment claiming
// they "drive main()" was false. These spawn the real entrypoint as a
// subprocess, which is the only way to assert the thing the source calls
// load-bearing: THE RUNNER'S EXIT CODE IS THE SUITE'S.
import { test as entryTest, expect as entryExpect } from "bun:test";

const ENTRY = new URL("./smoke-all.ts", import.meta.url).pathname;

async function runEntrypoint(args: string[]): Promise<{ code: number; out: string }> {
  const p = Bun.spawn(["bun", "run", ENTRY, ...args], {
    cwd: new URL("..", import.meta.url).pathname,
    stdout: "pipe",
    stderr: "pipe",
  });
  const out = (await new Response(p.stdout).text()) + (await new Response(p.stderr).text());
  return { code: await p.exited, out };
}

entryTest("the entrypoint EXITS NON-ZERO when the suite refuses", async () => {
  // smoke-extractor is red at baseline (MetaCoding-6ep) — a standing, honest
  // red, which makes it the fixture for this. If it is ever repaired, this
  // test must be re-pointed at another refusing selection rather than deleted.
  const { code, out } = await runEntrypoint(["--only", "extractor"]);
  entryExpect(out).toContain("SMOKE_ALL_FAIL");
  entryExpect(code).not.toBe(0);
}, 120_000);

entryTest("the entrypoint EXITS ZERO when the suite is satisfied", async () => {
  // The contrast. Without it, an entrypoint hard-wired to exit 1 would pass the
  // test above and refuse every green run — the failure mode is symmetric.
  const { code } = await runEntrypoint(["--only", "ladybug"]);
  entryExpect(code).toBe(0);
}, 120_000);

entryTest("a script that exits 0 while its OWN record says ok:false is refused", async () => {
  // MetaCoding-870. The child's `ok` was parsed and thrown away, so a script
  // could publish its own no, exit 0, and still be counted as a healthy
  // reporting script — with its numbers carrying the suite-wide floor. The
  // child's self-assessment is the one piece of evidence here written by the
  // party that actually ran; discarding it was the defect.
  const r = await runSuiteFixture("self-refused");
  entryExpect(r.code).toBe(1);
  entryExpect(r.stderr).toContain("no script exited 0 while its own record says ok:false");
  entryExpect(r.stderr).toContain("smoke-selfno.ts");
});

entryTest("CONTRAST: the same suite passes when the script's record says ok:true", async () => {
  // Without this, a guard that refused every record would pass the test above.
  // `green` is the identical shape with an honest ok:true.
  const r = await runSuiteFixture("green");
  entryExpect(r.code).toBe(0);
  entryExpect(r.stderr).not.toContain("self-refused");
});
