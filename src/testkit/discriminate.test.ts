// The instrument tier applies to the testkit before anything else.
//
// Every fixture below is itself a contrast pair: a REFUSING outcome and the
// contrast that must still PASS. A check only ever seen to pass is
// indistinguishable from one that cannot fail; a check that fires on everything
// is the same as one that never fires. So each F below asserts both halves.
//
// F1.3 (replay seam.test.ts's six input classes through discriminate() and
// assert byte-identical tags to the hand-rolled version) lives where the six
// classes live — src/ingest/seam.test.ts, "F1.3". It is migration evidence and
// it cannot be written here without reimplementing the gate it measures.

import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, readFileSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";
import {
  discriminate,
  observeDiscrimination,
  explain,
  recordedPairs,
  resetRecordedPairs,
  type DiscriminationResult,
  type PairFailureKind,
} from "./discriminate.ts";

const kinds = (r: DiscriminationResult): PairFailureKind[] =>
  r.failures.map((f) => f.kind);

// A miniature gate with a real, closed refusal vocabulary — the shape the
// module argues for: the tags are declared next to the GATE, not in the test.
type Req = { token?: string; slice?: string };
const GATE_TAGS = ["NO_TOKEN", "WRONG_SLICE", "ALLOWED"] as const;
function gate(req: Req): (typeof GATE_TAGS)[number] {
  if (!req.token) return "NO_TOKEN";
  if (req.slice !== "mine") return "WRONG_SLICE";
  return "ALLOWED";
}

describe("F1.1 — a difference that is only a crash is REFUSED; a difference that is a refusal code PASSES", () => {
  test("halves differing only by an unrelated TypeError are refused", async () => {
    const r = await observeDiscrimination<Req>({
      name: "F1.1 crash masquerading as a verdict",
      verdict: (req) => {
        if (!req.token) {
          // The bypass this rule exists for: something unrelated blows up and
          // the "verdicts differ", so a boolean pair would be green.
          return (undefined as unknown as { nope: () => string }).nope();
        }
        return gate(req);
      },
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("UNCAUGHT_THROW");
    expect((r.observed.NO_TOKEN ?? "").startsWith("OTHER:")).toBe(true);
    // and the crash is NOT silently accepted as the missing tag
    expect(kinds(r)).toContain("UNREACHED_TAG");
  });

  test("CONTRAST: the same two inputs, differing by refusal code, pass", async () => {
    const r = await observeDiscrimination<Req>({
      name: "F1.1 contrast — real refusal codes",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(true);
    expect(r.failures).toEqual([]);
    expect(r.observed).toEqual({ NO_TOKEN: "NO_TOKEN", ALLOWED: "ALLOWED" });
  });

  test("a BOOLEAN verdict is refused — this is why the verdict is a tag", async () => {
    const r = await observeDiscrimination<Req>({
      name: "F1.1 boolean verdict",
      // The pre-discriminate shape: "the two must differ" over a boolean.
      verdict: ((req: Req) => Boolean(req.token)) as unknown as (
        i: Req,
      ) => string,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("NON_TAG_VERDICT");
  });

  test("writing the crash down as an expectation is ALSO refused", async () => {
    // Without the reserved prefix, rule 1 is defeated by declaring the crash.
    const r = await observeDiscrimination<Req>({
      name: "F1.1 OTHER: declared as an expectation",
      verdict: (req) => {
        if (!req.token) throw new TypeError("boom");
        return gate(req);
      },
      cases: {
        "OTHER:boom": {},
        ALLOWED: { token: "t", slice: "mine" },
      },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("RESERVED_TAG_DECLARED");
  });
});

describe("F1.2 — a verdict collapsed to a constant fails on the duplicate; restored, it passes", () => {
  const cases = {
    NO_TOKEN: {} as Req,
    WRONG_SLICE: { token: "t", slice: "other" } as Req,
    ALLOWED: { token: "t", slice: "mine" } as Req,
  };

  test("collapsed to () => REFUSED", async () => {
    const r = await observeDiscrimination<Req>({
      name: "F1.2 collapsed verdict",
      verdict: () => "NO_TOKEN",
      cases,
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("DUPLICATE_TAG");
    expect(kinds(r)).toContain("UNREACHED_TAG");
    expect(kinds(r)).toContain("WRONG_TAG");
  });

  // "the difference must be NAMED" is one of this module's four constituent
  // claims, and it was the one with no fixture that could fail: the old
  // assertions were `explain(r)` contains "WRONG_SLICE" / "ALLOWED", and both
  // strings are already in the `vocabulary: [...]` line, so redacting every
  // per-tag line and every failure detail left the suite 33/0 (MetaCoding-lae).
  // These assert STRUCTURE — which line says what — and each has the contrast
  // that a REACHED tag is not reported as unreached.
  test("the report NAMES, per tag, what was observed and what was never reached", async () => {
    const r = await observeDiscrimination<Req>({
      name: "F1.2 collapsed verdict, named",
      verdict: () => "NO_TOKEN",
      cases,
    });
    const report = explain(r);

    // the per-tag observation lines: what each declared tag actually produced
    expect(report).toMatch(/^ {2}NO_TOKEN -> NO_TOKEN$/m);
    expect(report).toMatch(/^ {2}WRONG_SLICE -> NO_TOKEN$/m);
    expect(report).toMatch(/^ {2}ALLOWED -> NO_TOKEN$/m);

    // the failure lines: which tags were never reached, by name, in the
    // UNREACHED_TAG line itself — not merely somewhere in the vocabulary list
    expect(report).toMatch(/! UNREACHED_TAG: [^\n]*"WRONG_SLICE"/);
    expect(report).toMatch(/! UNREACHED_TAG: [^\n]*"ALLOWED"/);
    // CONTRAST: NO_TOKEN WAS reached, and is not reported as unreached
    expect(report).not.toMatch(/! UNREACHED_TAG: [^\n]*"NO_TOKEN"/);
    // and the detail, not just the kind, survives: the duplicate is named with
    // both cases that collided
    expect(report).toMatch(
      /! DUPLICATE_TAG: [^\n]*"NO_TOKEN" and "WRONG_SLICE"[^\n]*"NO_TOKEN"/,
    );
  });

  test("CONTRAST: a passing pair's report names every tag and reports no failure", async () => {
    const report = explain(
      await observeDiscrimination<Req>({
        name: "F1.2 named, contrast",
        verdict: gate,
        cases,
      }),
    );
    expect(report).toMatch(/^ {2}WRONG_SLICE -> WRONG_SLICE$/m);
    expect(report).toMatch(/^ {2}ALLOWED -> ALLOWED$/m);
    expect(report).not.toMatch(/! UNREACHED_TAG/);
    expect(report).not.toMatch(/! DUPLICATE_TAG/);
  });

  test("collapsed to always-throw is also caught, and differently", async () => {
    const r = await observeDiscrimination<Req>({
      name: "F1.2 always-throw verdict",
      verdict: () => {
        throw new Error("always");
      },
      cases,
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("UNCAUGHT_THROW");
    expect(kinds(r)).toContain("DUPLICATE_TAG");
  });

  test("CONTRAST: the same three cases with the real gate pass", async () => {
    const r = await discriminate<Req>({
      name: "F1.2 contrast — real gate",
      verdict: gate,
      cases,
    });
    expect(r.ok).toBe(true);
    expect(r.observed).toEqual({
      NO_TOKEN: "NO_TOKEN",
      WRONG_SLICE: "WRONG_SLICE",
      ALLOWED: "ALLOWED",
    });
  });
});

describe("the cheapest greens are refused", () => {
  test("one case is not a pair", async () => {
    const r = await observeDiscrimination<Req>({
      name: "single case",
      verdict: gate,
      cases: { NO_TOKEN: {} },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("NOT_A_PAIR");
  });

  test("zero cases is not a pass", async () => {
    const r = await observeDiscrimination<Req>({
      name: "empty",
      verdict: gate,
      cases: {},
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("NOT_A_PAIR");
  });

  test("a verdict outside the closed vocabulary is named, not tolerated", async () => {
    const r = await observeDiscrimination<Req>({
      name: "undeclared tag",
      verdict: (req) => (req.token ? "SOMETHING_ELSE" : "NO_TOKEN"),
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("UNDECLARED_TAG");
    expect(kinds(r)).toContain("UNREACHED_TAG");
  });

  // MetaCoding-3ad: the verb the design document, CLAUDE.md and the file name
  // advertise must be the one that ENFORCES. Before this, `discriminate()` was
  // the non-throwing form, so a gate that called it and dropped the result was
  // green while the pair was refused — a check that cannot fail, inside the
  // mechanism against checks that cannot fail.
  test("discriminate() THROWS with the named difference; ignoring the result is not green", async () => {
    await expect(
      discriminate<Req>({
        name: "thrower",
        verdict: () => "NO_TOKEN",
        cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
      }),
    ).rejects.toThrow(/DUPLICATE_TAG/);

    // the shape MetaCoding-3ad measured: a refusing pair whose result is
    // discarded. Under the raw verb that is silent; under `discriminate` the
    // statement itself is what fails.
    let escaped = false;
    try {
      await discriminate<Req>({
        name: "result dropped on the floor",
        verdict: () => "SAME",
        cases: { A: {}, B: { token: "t" } },
      });
      escaped = true;
    } catch {
      /* expected */
    }
    expect(escaped).toBe(false);

    // CONTRAST: a pair that HOLDS returns normally and does not throw.
    const ok = await discriminate<Req>({
      name: "thrower contrast",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(ok.ok).toBe(true);
  });

  // MetaCoding-frl: EMPTY_TAG was the only member of the closed PairFailureKind
  // vocabulary with no fixture — neutering its push left the suite 33/0.
  test("an empty declared tag is refused; a named one is not", async () => {
    const r = await observeDiscrimination<Req>({
      name: "empty tag",
      verdict: gate,
      cases: { "": {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("EMPTY_TAG");
    expect(r.failures.find((f) => f.kind === "EMPTY_TAG")?.declared).toBe("");
  });

  test("a BLANK declared tag is refused too — whitespace is not a name", async () => {
    const r = await observeDiscrimination<Req>({
      name: "blank tag",
      verdict: gate,
      cases: { "   ": {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("EMPTY_TAG");
  });

  test("CONTRAST: the same shape with a named tag raises no EMPTY_TAG", async () => {
    const r = await observeDiscrimination<Req>({
      name: "named tag",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(true);
    expect(kinds(r)).not.toContain("EMPTY_TAG");
  });
});

// MetaCoding-ah5. `cases` is a plain object and JS enumerates array-index-like
// keys FIRST, ascending, whatever the source order. So {"2","10","1"} ran as
// 1,2,10 with ok:true and no report — a different experiment than the declared
// one, silently. Order is load-bearing (seam.test.ts class 6 depends on state
// class 5 established), and the design document's named next target,
// scripts/smoke-incremental.ts's five passes, is exactly where numeric tags are
// the natural thing to write.
describe("integer-like tags are refused, because JS would reorder them", () => {
  const numeric = { "2": {}, "10": {}, "1": {} } as Record<string, Req>;

  test("the reordering is REAL — this is the defect, demonstrated, not asserted", () => {
    // If this ever stops holding, the guard below is guarding nothing and this
    // line says so instead of the suite going quietly green.
    expect(Object.keys(numeric)).toEqual(["1", "2", "10"]);
  });

  test("a pair declaring integer-like tags is refused, by name", async () => {
    const r = await observeDiscrimination<Req>({
      name: "numeric passes",
      verdict: (req) => (req.token ? "10" : "1"),
      cases: numeric,
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("INDEX_LIKE_TAG");
    // every offending tag is named, not just the first
    const named = r.failures
      .filter((f) => f.kind === "INDEX_LIKE_TAG")
      .map((f) => f.declared);
    expect(new Set(named)).toEqual(new Set(["1", "2", "10"]));
  });

  test("CONTRAST: the same five passes, NAMED, pass and run in declaration order", async () => {
    const seen: string[] = [];
    const r = await discriminate<string>({
      name: "five passes, named",
      verdict: (input) => {
        seen.push(input);
        return `PASS_${input}`;
      },
      cases: { PASS_2: "2", PASS_10: "10", PASS_1: "1" },
    });
    expect(r.ok).toBe(true);
    // the vocabulary is in DECLARATION order, not sorted...
    expect(r.declared).toEqual(["PASS_2", "PASS_10", "PASS_1"]);
    // ...and so is the order the cases actually RAN in, which is the half a
    // reorder would break while leaving `declared` looking right.
    expect(seen).toEqual(["2", "10", "1"]);
  });

  test("a lone integer-like tag among named ones is still refused", async () => {
    const r = await observeDiscrimination<Req>({
      name: "one numeric tag",
      verdict: (req) => (req.token ? "ALLOWED" : "0"),
      cases: { "0": {} as Req, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("INDEX_LIKE_TAG");
  });
});

// MetaCoding-04i. Rule 3's shipped sink had ZERO coverage: deleting `emit(result)`
// left the suite 33/0, and emit()'s bare `catch {}` swallowed an unwritable
// DISCRIMINATE_RECORD entirely — ok:true, nothing written, nothing said. That is
// this design document's own property (lessons-as-mechanism.md:31) violated
// inside the mechanism that enforces it, and floors.ts / mechanism 4 is
// specified to READ this record.
describe("rule 3's JSONL sink — written when it can be, REFUSED when it cannot", () => {
  let dir: string;
  const saved = process.env.DISCRIMINATE_RECORD;

  beforeEach(() => {
    dir = mkdtempSync(join(tmpdir(), "discriminate-sink-"));
  });
  afterEach(() => {
    if (saved === undefined) delete process.env.DISCRIMINATE_RECORD;
    else process.env.DISCRIMINATE_RECORD = saved;
  });

  test("a writable sink gets one JSONL line per pair — passing AND failing", async () => {
    const path = join(dir, "record.jsonl");
    process.env.DISCRIMINATE_RECORD = path;

    await observeDiscrimination<Req>({
      name: "sink pass",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    await observeDiscrimination<Req>({
      name: "sink fail",
      verdict: () => "NO_TOKEN",
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });

    const lines = readFileSync(path, "utf-8").trim().split("\n");
    expect(lines.length).toBe(2);
    const rows = lines.map((l) => JSON.parse(l));
    expect(rows.map((r) => r.name)).toEqual(["sink pass", "sink fail"]);
    // a record that only holds successes cannot report a failure
    expect(rows.map((r) => r.ok)).toEqual([true, false]);
    expect(rows[0].observed).toEqual({ NO_TOKEN: "NO_TOKEN", ALLOWED: "ALLOWED" });
    expect(rows[1].failures).toContain("DUPLICATE_TAG");
    expect(rows[1].declared).toEqual(["NO_TOKEN", "ALLOWED"]);
  });

  test("CONTRAST: with no sink asked for, nothing is written and nothing fails", async () => {
    delete process.env.DISCRIMINATE_RECORD;
    const r = await observeDiscrimination<Req>({
      name: "no sink asked for",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(true);
    expect(kinds(r)).not.toContain("RECORD_SINK_UNWRITABLE");
  });

  test("a sink that was ASKED for and cannot be written FAILS the pair", async () => {
    // a regular file used as a directory: ENOTDIR on every platform this runs on
    const blocker = join(dir, "not-a-dir");
    writeFileSync(blocker, "x", "utf-8");
    process.env.DISCRIMINATE_RECORD = join(blocker, "record.jsonl");

    const r = await observeDiscrimination<Req>({
      name: "unwritable sink, otherwise-passing pair",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    // the pair itself HOLDS — this failure is the instrument's, not the gate's
    expect(kinds(r)).toEqual(["RECORD_SINK_UNWRITABLE"]);
    expect(r.ok).toBe(false);
    expect(explain(r)).toMatch(/! RECORD_SINK_UNWRITABLE: [^\n]*record\.jsonl/);
  });

  test("and the throwing verb surfaces it — an unwritable record is not a pass", async () => {
    const blocker = join(dir, "not-a-dir-2");
    writeFileSync(blocker, "x", "utf-8");
    process.env.DISCRIMINATE_RECORD = join(blocker, "record.jsonl");
    await expect(
      discriminate<Req>({
        name: "unwritable sink, throwing verb",
        verdict: gate,
        cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
      }),
    ).rejects.toThrow(/RECORD_SINK_UNWRITABLE/);
  });
});

describe("rule 3 — the pair is recorded, so a deleted pair stops appearing", () => {
  beforeEach(() => resetRecordedPairs());

  test("running two pairs records two; running none records none", async () => {
    expect(recordedPairs().length).toBe(0);
    await observeDiscrimination<Req>({
      name: "recorded A",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    await observeDiscrimination<Req>({
      name: "recorded B",
      verdict: gate,
      cases: { WRONG_SLICE: { token: "t", slice: "x" }, NO_TOKEN: {} },
    });
    const rec = recordedPairs();
    expect(rec.length).toBe(2);
    expect(rec.map((r) => r.name)).toEqual(["recorded A", "recorded B"]);
    // a FAILED pair is recorded too — a record that only holds successes is a
    // record that cannot report a failure.
    await observeDiscrimination<Req>({
      name: "recorded C (failing)",
      verdict: () => "NO_TOKEN",
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(recordedPairs().length).toBe(3);
    expect(recordedPairs()[2]?.ok).toBe(false);
  });
});
