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

import { test, expect, describe, beforeEach } from "bun:test";
import {
  discriminate,
  assertDiscriminates,
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
    const r = await discriminate<Req>({
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
    const r = await discriminate<Req>({
      name: "F1.1 contrast — real refusal codes",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(true);
    expect(r.failures).toEqual([]);
    expect(r.observed).toEqual({ NO_TOKEN: "NO_TOKEN", ALLOWED: "ALLOWED" });
  });

  test("a BOOLEAN verdict is refused — this is why the verdict is a tag", async () => {
    const r = await discriminate<Req>({
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
    const r = await discriminate<Req>({
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
    const r = await discriminate<Req>({
      name: "F1.2 collapsed verdict",
      verdict: () => "NO_TOKEN",
      cases,
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("DUPLICATE_TAG");
    expect(kinds(r)).toContain("UNREACHED_TAG");
    expect(kinds(r)).toContain("WRONG_TAG");
    // the report NAMES which tags were never reached
    expect(explain(r)).toContain("WRONG_SLICE");
    expect(explain(r)).toContain("ALLOWED");
  });

  test("collapsed to always-throw is also caught, and differently", async () => {
    const r = await discriminate<Req>({
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
    const r = await assertDiscriminates<Req>({
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
    const r = await discriminate<Req>({
      name: "single case",
      verdict: gate,
      cases: { NO_TOKEN: {} },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("NOT_A_PAIR");
  });

  test("zero cases is not a pass", async () => {
    const r = await discriminate<Req>({
      name: "empty",
      verdict: gate,
      cases: {},
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("NOT_A_PAIR");
  });

  test("a verdict outside the closed vocabulary is named, not tolerated", async () => {
    const r = await discriminate<Req>({
      name: "undeclared tag",
      verdict: (req) => (req.token ? "SOMETHING_ELSE" : "NO_TOKEN"),
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(r.ok).toBe(false);
    expect(kinds(r)).toContain("UNDECLARED_TAG");
    expect(kinds(r)).toContain("UNREACHED_TAG");
  });

  test("assertDiscriminates throws with the named difference", async () => {
    await expect(
      assertDiscriminates<Req>({
        name: "thrower",
        verdict: () => "NO_TOKEN",
        cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
      }),
    ).rejects.toThrow(/DUPLICATE_TAG/);
  });
});

describe("rule 3 — the pair is recorded, so a deleted pair stops appearing", () => {
  beforeEach(() => resetRecordedPairs());

  test("running two pairs records two; running none records none", async () => {
    expect(recordedPairs().length).toBe(0);
    await discriminate<Req>({
      name: "recorded A",
      verdict: gate,
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    await discriminate<Req>({
      name: "recorded B",
      verdict: gate,
      cases: { WRONG_SLICE: { token: "t", slice: "x" }, NO_TOKEN: {} },
    });
    const rec = recordedPairs();
    expect(rec.length).toBe(2);
    expect(rec.map((r) => r.name)).toEqual(["recorded A", "recorded B"]);
    // a FAILED pair is recorded too — a record that only holds successes is a
    // record that cannot report a failure.
    await discriminate<Req>({
      name: "recorded C (failing)",
      verdict: () => "NO_TOKEN",
      cases: { NO_TOKEN: {}, ALLOWED: { token: "t", slice: "mine" } },
    });
    expect(recordedPairs().length).toBe(3);
    expect(recordedPairs()[2]?.ok).toBe(false);
  });
});
