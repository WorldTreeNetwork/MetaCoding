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
    // The runner's own five verdicts, all held.
    expect(r.record!.published.checks).toBe(5);
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
    expect(own.min).toBe(5);
    expect(own.basis).toBe("derived");
    // REFUTING: a run that reaches only 3 of them fails that floor by name.
    const red = await runSuiteFixture("red-and-silent");
    expect(red.stderr).toContain('"checks" = 3, floor is 5');
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
