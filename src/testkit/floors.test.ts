// Fixtures for floors.ts (docs/design/lessons-as-mechanism.md, mechanism 4).
//
// Every check here exercises a REFUTING outcome AND its contrast. A fixture
// that only shows the passing half cannot tell "the floor held" from "the
// floor cannot fire", which is the exact failure floors.ts is about.
//
// F4.1  three checks deleted -> fails BY NAME; the complete script passes.
//       Both print PASS today, and that is ASSERTED here, not asserted-about.
// F4.2  a floor naming an unpublished field -> INSTRUMENT failure, distinct
//       from a check failure.
// F4.3  an EMPTY run fails rather than passes.

import { afterEach, describe, expect, test } from "bun:test";

import { discriminate, resetRecordedPairs } from "./discriminate.ts";
import {
  type Floor,
  FloorsRefused,
  InstrumentMisuse,
  SmokeCheckFailed,
  beginRun,
  evaluateFloors,
  observeFloors,
  recordedFloors,
  resetRecordedFloors,
} from "./floors.ts";

const FIXTURE = "src/testkit/fixtures/floors-fixture-smoke.ts";

afterEach(() => {
  resetRecordedFloors();
  resetRecordedPairs();
});

interface Ran {
  code: number;
  stdout: string;
  stderr: string;
}

async function runFixture(mode: string): Promise<Ran> {
  const proc = Bun.spawn(["bun", "run", FIXTURE], {
    cwd: new URL("../..", import.meta.url).pathname,
    env: { ...process.env, FLOORS_FIXTURE_MODE: mode, SMOKE_RECORD_FILE: "" },
    stdout: "pipe",
    stderr: "pipe",
  });
  const [stdout, stderr] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
  ]);
  const code = await proc.exited;
  return { code, stdout, stderr };
}

const kinds = (r: { failures: Array<{ kind: string }> }) => r.failures.map((f) => f.kind);

// ---------------------------------------------------------------------------
// F4.1 — truncation. The measurement that motivates the whole file.
// ---------------------------------------------------------------------------

describe("F4.1 truncation", () => {
  test("TODAY: complete and truncated legacy runs are byte-identical and both exit 0", async () => {
    const complete = await runFixture("legacy-complete");
    const truncated = await runFixture("legacy-truncated");

    expect(complete.code).toBe(0);
    expect(truncated.code).toBe(0);
    // The defect, stated as an equality rather than as prose.
    expect(truncated.stdout).toBe(complete.stdout);
    expect(complete.stdout).toContain("FIXTURE_SMOKE_PASS");
  });

  test("UNDER FLOORS: the complete run passes and the truncated run fails BY NAME", async () => {
    const complete = await runFixture("floors-complete");
    const truncated = await runFixture("floors-truncated");

    expect(complete.code).toBe(0);
    expect(complete.stdout).toContain("FIXTURE_SMOKE_PASS");

    expect(truncated.code).toBe(1);
    expect(truncated.stdout).not.toContain("FIXTURE_SMOKE_PASS");
    // BY NAME: the field, the floor, and the number actually reached.
    expect(truncated.stderr).toContain("FLOOR_UNMET");
    expect(truncated.stderr).toContain("checks");
    expect(truncated.stderr).toContain("= 4");
    expect(truncated.stderr).toContain("floor is 7");
  });

  test("the record says WHICH checks ran, so a truncation is diagnosable", async () => {
    const complete = await runFixture("floors-complete");
    const truncated = await runFixture("floors-truncated");

    const rec = (out: string) =>
      JSON.parse(out.split("\n").find((l) => l.startsWith("SMOKE_RECORD "))!.slice(13));

    expect(rec(complete.stdout).published.checks).toBe(7);
    expect(rec(complete.stdout).checkLabels).toContain("seven is seven");
    // The failed run STILL emits its record: that record is what names the loss.
    expect(rec(truncated.stdout).published.checks).toBe(4);
    expect(rec(truncated.stdout).checkLabels).not.toContain("seven is seven");
    expect(rec(truncated.stdout).ok).toBe(false);
  });

  test("the count is DERIVED: `checks` cannot be written by hand", () => {
    const run = beginRun("x");
    expect(() => run.measure("checks", 99)).toThrow(InstrumentMisuse);
    // Contrast: a field the run does NOT derive is measurable.
    expect(() => run.measure("rows", 99)).not.toThrow();
  });

  test("the count cannot be inflated by counting one check twice", () => {
    const run = beginRun("x");
    run.check("a", true);
    expect(() => run.check("a", true)).toThrow(/DUPLICATE_CHECK/);
    // Contrast: a genuinely different check counts.
    run.check("b", true);
    expect(run.publish().checks).toBe(2);
  });

  test("a FAILING check is not counted, and it stops the run", () => {
    const run = beginRun("x");
    run.check("a", true);
    expect(() => run.check("b", false, "b was false")).toThrow(SmokeCheckFailed);
    expect(run.publish().checks).toBe(1);
  });

  test("a truthy non-boolean is not a verdict", () => {
    const run = beginRun("x");
    expect(() => run.check("a", "yes" as unknown as boolean)).toThrow(InstrumentMisuse);
    expect(() => run.check("a", 1 as unknown as boolean)).toThrow(InstrumentMisuse);
    expect(() => run.check("a", true)).not.toThrow();
  });
});

// ---------------------------------------------------------------------------
// F4.2 — a floor over a field nobody publishes. THE mechanism.
// ---------------------------------------------------------------------------

describe("F4.2 unpublished field is an INSTRUMENT failure", () => {
  test("absent field refuses; present field of the same value passes", () => {
    const floors: Floor[] = [{ min: 3, measuredAs: "sectionsCovered", why: "derived" }];

    const absent = observeFloors(floors, { checks: 12 });
    expect(absent.ok).toBe(false);
    expect(kinds(absent)).toContain("UNPUBLISHED_FIELD");
    expect(absent.instrumentFailed).toBe(true);

    // Contrast: publish the field, same floors, same run size -> PASS.
    const present = observeFloors(floors, { checks: 12, sectionsCovered: 3 });
    expect(present.ok).toBe(true);
    expect(present.instrumentFailed).toBe(false);
  });

  test("INSTRUMENT failure is DISTINCT from a check failure", () => {
    const unpublished = observeFloors([{ min: 3, measuredAs: "gone", why: "w" }], { checks: 1 });
    const short = observeFloors([{ min: 3, measuredAs: "checks", why: "w" }], { checks: 1 });

    expect(unpublished.ok).toBe(false);
    expect(short.ok).toBe(false);
    // Both fail — but not in the same way, and the difference is the point:
    // one says "fix the instrument", the other says "the run came up short".
    expect(unpublished.instrumentFailed).toBe(true);
    expect(short.instrumentFailed).toBe(false);
    expect(kinds(unpublished)).toEqual(["UNPUBLISHED_FIELD"]);
    expect(kinds(short)).toEqual(["FLOOR_UNMET"]);
  });

  test("a HIGH count does not buy an unpublished field a pass", () => {
    // The failure mode being refused: "we ran loads of checks, surely that
    // covers it." It does not; the named quantity was never measured.
    const r = observeFloors([{ min: 1, measuredAs: "sectionsCovered", why: "w" }], {
      checks: 100000,
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("UNPUBLISHED_FIELD");
  });

  test("present-but-not-a-number is absence wearing presence's clothes", () => {
    const bad = observeFloors(
      [{ min: 1, measuredAs: "n", why: "w" }],
      { n: "12" } as unknown as Record<string, number>,
    );
    expect(kinds(bad)).toContain("NON_NUMERIC_FIELD");
    expect(bad.instrumentFailed).toBe(true);
    const nan = observeFloors([{ min: 1, measuredAs: "n", why: "w" }], { n: NaN });
    expect(kinds(nan)).toContain("NON_NUMERIC_FIELD");
    // Contrast: a real number of the same shape passes.
    expect(observeFloors([{ min: 1, measuredAs: "n", why: "w" }], { n: 12 }).ok).toBe(true);
  });

  test("a zero-valued published field is NOT absence — it refuses as a CHECK", () => {
    // The joint most likely to be got wrong: `published[f] ?? absent` would
    // treat 0 as missing and report the wrong tier.
    const r = observeFloors([{ min: 1, measuredAs: "checks", why: "w" }], { checks: 0 });
    expect(kinds(r)).toEqual(["FLOOR_UNMET"]);
    expect(r.instrumentFailed).toBe(false);
  });

  test("end to end: the fixture script refuses as INSTRUMENT and prints no PASS", async () => {
    const r = await runFixture("floors-unpublished");
    expect(r.code).toBe(1);
    expect(r.stdout).not.toContain("FIXTURE_SMOKE_PASS");
    expect(r.stderr).toContain("INSTRUMENT");
    expect(r.stderr).toContain("UNPUBLISHED_FIELD");
    expect(r.stderr).toContain("sectionsCovered");
    // It names what IS published, so the fix is one edit away.
    expect(r.stderr).toContain("checks");
  });

  test("duplicate floors over one field are refused: the weaker hides the stronger", () => {
    const r = observeFloors(
      [
        { min: 9, measuredAs: "checks", why: "w" },
        { min: 1, measuredAs: "checks", why: "w" },
      ],
      { checks: 5 },
    );
    expect(kinds(r)).toContain("DUPLICATE_FLOOR");
    expect(r.instrumentFailed).toBe(true);
  });

  test("a floor without a field name is just a number", () => {
    const r = observeFloors([{ min: 3, measuredAs: "", why: "w" }], { checks: 5 });
    expect(kinds(r)).toContain("MISSING_MEASURED_AS");
  });

  test("a floor that does not say what it was derived from is refused", () => {
    const r = observeFloors([{ min: 3, measuredAs: "checks", why: "  " }], { checks: 5 });
    expect(kinds(r)).toContain("MISSING_WHY");
    expect(observeFloors([{ min: 3, measuredAs: "checks", why: "w" }], { checks: 5 }).ok).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// F4.3 — the cheapest green is an empty run.
// ---------------------------------------------------------------------------

describe("F4.3 an empty run fails", () => {
  test("end to end: zero checks refuses; the same script complete passes", async () => {
    const empty = await runFixture("floors-empty");
    expect(empty.code).toBe(1);
    expect(empty.stdout).not.toContain("FIXTURE_SMOKE_PASS");
    expect(empty.stderr).toContain("FLOOR_UNMET");
    expect(empty.stderr).toContain("= 0");

    const complete = await runFixture("floors-complete");
    expect(complete.code).toBe(0);
  });

  test("zero floors cannot be the way out", () => {
    const r = observeFloors([], { checks: 0 });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("NO_FLOORS");
    expect(r.instrumentFailed).toBe(true);
  });

  test("min < 1 cannot be the way out either", () => {
    for (const min of [0, -1, Number.NaN]) {
      const r = observeFloors([{ min, measuredAs: "checks", why: "w" }], { checks: 0 });
      expect(kinds(r)).toContain("VACUOUS_FLOOR");
      expect(r.instrumentFailed).toBe(true);
    }
    // Contrast: the smallest floor that can actually fire is accepted.
    expect(observeFloors([{ min: 1, measuredAs: "checks", why: "w" }], { checks: 1 }).ok).toBe(true);
  });

  test("a run that registered nothing publishes zeroes, not nothing", () => {
    const run = beginRun("x");
    expect(run.publish()).toEqual({ checks: 0, pairs: 0 });
  });
});

// ---------------------------------------------------------------------------
// The advertised verb must ENFORCE — discriminate.ts paid for this lesson
// (MetaCoding-3ad: a caller that dropped the result stayed green).
// ---------------------------------------------------------------------------

describe("the advertised name is the one that enforces", () => {
  test("evaluateFloors THROWS on refusal; observeFloors returns it", () => {
    const floors: Floor[] = [{ min: 3, measuredAs: "gone", why: "w" }];
    expect(() => evaluateFloors(floors, { checks: 9 })).toThrow(FloorsRefused);
    expect(observeFloors(floors, { checks: 9 }).ok).toBe(false); // no throw
  });

  test("the thrown error carries the named failure, not a bare message", () => {
    try {
      evaluateFloors([{ min: 3, measuredAs: "gone", why: "w" }], { checks: 9 });
      throw new Error("unreachable: evaluateFloors did not throw");
    } catch (e) {
      expect(e).toBeInstanceOf(FloorsRefused);
      expect((e as FloorsRefused).result.failures[0]!.kind).toBe("UNPUBLISHED_FIELD");
      expect((e as FloorsRefused).message).toContain("UNPUBLISHED_FIELD");
    }
  });

  test("evaluateFloors returns on success", () => {
    expect(evaluateFloors([{ min: 1, measuredAs: "checks", why: "w" }], { checks: 1 }).ok).toBe(true);
  });

  test("every evaluation is recorded, refusals included", () => {
    resetRecordedFloors();
    observeFloors([{ min: 1, measuredAs: "checks", why: "w" }], { checks: 1 });
    try {
      evaluateFloors([{ min: 9, measuredAs: "checks", why: "w" }], { checks: 1 });
    } catch {
      /* expected */
    }
    expect(recordedFloors().length).toBe(2);
    expect(recordedFloors().map((r) => r.ok)).toEqual([true, false]);
  });
});

// ---------------------------------------------------------------------------
// Composition with mechanism 1: `pairs` is read from discriminate's registry,
// so a deleted pair stops being counted.
// ---------------------------------------------------------------------------

describe("pairs are derived from discriminate(), not declared", () => {
  test("a registered pair is counted; a deleted one is not", async () => {
    resetRecordedPairs();
    const withPair = beginRun("x");
    await discriminate({
      name: "comment-invariance",
      verdict: (s: string) => (s.includes("drush en") ? "CHANGED" : "BASELINE"),
      cases: { BASELINE: "# just a comment", CHANGED: "drush en -y farm_new" },
    });
    expect(withPair.publish().pairs).toBe(1);
    expect(withPair.pairNames()).toEqual(["comment-invariance"]);

    // Contrast: the same run with the pair deleted counts zero and the floor
    // over `pairs` fires by name.
    const withoutPair = beginRun("x");
    expect(withoutPair.publish().pairs).toBe(0);
    const r = observeFloors(
      [{ min: 1, measuredAs: "pairs", why: "this script registers one pair" }],
      withoutPair.publish(),
    );
    expect(kinds(r)).toEqual(["FLOOR_UNMET"]);
  });

  test("a run counts only the pairs registered AFTER it began", async () => {
    resetRecordedPairs();
    await discriminate({
      name: "before",
      verdict: (s: string) => s,
      cases: { A: "A", B: "B" },
    });
    const run = beginRun("x");
    expect(run.publish().pairs).toBe(0);
    await discriminate({
      name: "during",
      verdict: (s: string) => s,
      cases: { A: "A", B: "B" },
    });
    expect(run.pairNames()).toEqual(["during"]);
  });

  test("a REFUSED pair still counts as a pair that ran", async () => {
    // `pairs` measures what the instrument executed, not what it concluded.
    // Conflating the two would let a floor over `pairs` be satisfied by
    // deleting a failing pair, which is the opposite of the intent.
    resetRecordedPairs();
    const run = beginRun("x");
    await discriminate({
      name: "collapsed",
      verdict: () => "SAME",
      cases: { SAME: 1, OTHER_CASE: 2 },
    }).catch(() => {
      /* the pair is refused; that is the point */
    });
    expect(run.publish().pairs).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// The record sink: asked for and unwritable is a FAILURE, never a shrug.
// ---------------------------------------------------------------------------

describe("the record sink", () => {
  test("an unwritable SMOKE_RECORD_FILE refuses the run; a writable one does not", async () => {
    const dir = `/tmp/floors-sink-${process.pid}-${Date.now()}`;
    await Bun.write(`${dir}/ok.jsonl`, "");

    const run = async (file: string) => {
      const proc = Bun.spawn(["bun", "run", FIXTURE], {
        cwd: new URL("../..", import.meta.url).pathname,
        env: { ...process.env, FLOORS_FIXTURE_MODE: "floors-complete", SMOKE_RECORD_FILE: file },
        stdout: "pipe",
        stderr: "pipe",
      });
      const [out, err] = await Promise.all([
        new Response(proc.stdout).text(),
        new Response(proc.stderr).text(),
      ]);
      return { code: await proc.exited, out, err };
    };

    const good = await run(`${dir}/ok.jsonl`);
    expect(good.code).toBe(0);
    expect((await Bun.file(`${dir}/ok.jsonl`).text()).trim().length).toBeGreaterThan(0);

    // Contrast: a path that cannot be written. Same run, same checks, refused.
    const bad = await run(`${dir}/no-such-dir/deeper/x.jsonl`);
    expect(bad.code).toBe(1);
    expect(bad.err).toContain("RECORD_SINK_UNWRITABLE");
    expect(bad.out).not.toContain("FIXTURE_SMOKE_PASS");
  });
});
