// discriminate() — a contrast pair and a mutation test are ONE operation.
//
// WHY THIS FILE EXISTS (docs/design/lessons-as-mechanism.md, mechanism 1)
// ======================================================================
// A contrast pair is a mutation applied to the SUBJECT; a mutation test is a
// contrast pair applied to the INSTRUMENT. Both are the same four things:
// two or more inputs, ONE verdict function, verdicts that must DIFFER, and a
// difference that is NAMED. That is one function, not a framework.
//
// The pattern existed in this repo hand-rolled exactly once —
// src/ingest/seam.test.ts:439, whose own comment states the principle:
//
//     "Each input class must produce a DIFFERENT refusal code, so a check that
//      had collapsed into 'always throw' — or into 'never throw' — would be
//      visible here."
//
// That file also carries the argument against the alternative
// (src/ingest/seam.test.ts:1-36): the instrument it replaced was a text scanner
// over import syntax, a fresh judge found NINE of nine bypass shapes
// undetected, and the conclusion recorded there is that a scanner's coverage is
// the set of shapes its author imagined. Do not build a scanner over test files
// to enforce this module's use; that is the same failure in a new medium. This
// primitive is opt-in by construction and that limit is stated, not hidden
// (lessons-as-mechanism.md:274).
//
// THE THREE RULES, each refusing something that passes without them
// -----------------------------------------------------------------
// 1. The verdict is a TAG from a closed vocabulary — never a boolean, never an
//    exception. An uncaught throw is classified `OTHER:<message>` and FAILS the
//    pair. A boolean verdict makes non-constancy trivially satisfiable by an
//    unrelated crash: half A throws a TypeError, half B returns false, "the
//    verdicts differ", green. A refusal code does not have that hole. The
//    closed vocabulary is the KEY SET of `cases`; `OTHER:` is reserved and
//    declaring it is an instrument failure, because otherwise rule 1 is
//    defeated by writing the crash down as an expectation.
// 2. Every declared tag must be REACHED, and no two cases may produce the same
//    tag. A verdict function collapsed to a constant fails on the first
//    duplicate. Fewer than two cases is not a pair and is refused: the cheapest
//    green is an empty run.
// 3. The pair is RECORDED (see `recordedPairs`), so a pair that was deleted
//    stops appearing. Publishing that record into the smoke suite's own output
//    is floors.ts / mechanism 4 and is NOT shipped here; what is shipped is the
//    registry it will read, plus an optional JSONL sink via DISCRIMINATE_RECORD.
//
// HOW THIS IS STILL FAKEABLE, stated at the point of use
// ------------------------------------------------------
// The verdict function is written by the pair's author and is the thing under
// test. A verdict that catches broadly and maps an unrelated error onto a real
// refusal tag defeats rule 1 completely, in two lines. There is no clean answer
// (lessons-as-mechanism.md:258). The partial mitigation: keep the tag
// vocabulary a closed union declared next to the GATE, not in the test, so the
// mapping is visible in the gate's own source and moves under review.
//
// A SECOND THING THIS DOES NOT DO: it says nothing about fixture SIZE. A pair
// whose inputs are both too small to exercise the component is green and blind
// — CSV dialect sniffing was stable at 6 rows and unstable at 21,282. The
// exemplar to copy is src/store/build.test.ts:211-227; read it before writing a
// pair over anything size-sensitive (sniff, sample, paginate, LIMIT, batch).

import { appendFileSync } from "node:fs";

/** A verdict tag. Non-empty string, from the closed vocabulary of `cases`. */
export type Tag = string;

/** Prefix reserved for uncaught throws. Never a legitimate verdict. */
export const OTHER_PREFIX = "OTHER:";

/** Why a pair failed. A closed vocabulary for the instrument's own failures. */
export type PairFailureKind =
  | "NOT_A_PAIR" // fewer than two cases
  | "RESERVED_TAG_DECLARED" // a declared tag starts with OTHER:
  | "EMPTY_TAG" // a declared tag is empty/blank
  | "NON_TAG_VERDICT" // verdict returned a boolean/number/undefined/…
  | "UNCAUGHT_THROW" // verdict threw; observed OTHER:<message>
  | "UNDECLARED_TAG" // observed a tag outside the closed vocabulary
  | "WRONG_TAG" // case declared X, observed a different declared tag
  | "DUPLICATE_TAG" // two cases produced the same tag
  | "UNREACHED_TAG"; // a declared tag no case produced

export interface PairFailure {
  kind: PairFailureKind;
  /** The declared tag this failure is about, when there is one. */
  declared?: Tag;
  /** What the verdict actually produced, when it produced anything. */
  observed?: string;
  detail: string;
}

export interface DiscriminationResult {
  name: string;
  ok: boolean;
  /** The closed vocabulary, in declaration order. */
  declared: Tag[];
  /** declared tag -> what the verdict actually returned for that case. */
  observed: Record<Tag, string>;
  failures: PairFailure[];
}

export interface DiscriminateSpec<I> {
  /** What property this pair is about. Named, because the difference must be. */
  name: string;
  /** ONE verdict function, shared by every case. Must return a Tag. */
  verdict: (input: I) => Tag | Promise<Tag>;
  /**
   * One input per expected tag. The keys ARE the closed vocabulary.
   * Cases run SEQUENTIALLY in declaration order, never concurrently, so a case
   * may depend on state a previous case established (see seam.test.ts, where
   * class 6 is "the same call once the slice reads HEALTHY").
   */
  cases: Record<Tag, I>;
}

const registry: DiscriminationResult[] = [];

/** Every pair run in this process, in order. Rule 3's half that ships today. */
export function recordedPairs(): readonly DiscriminationResult[] {
  return registry;
}

/** Clear the registry. For this module's own fixtures; not for gates. */
export function resetRecordedPairs(): void {
  registry.length = 0;
}

function messageOf(e: unknown): string {
  if (e instanceof Error) return e.message;
  return String(e);
}

/**
 * Run one contrast pair. Returns the result; it does NOT throw on a failed
 * pair, because the fixtures for this module must be able to observe a REFUSAL
 * without the suite dying. Use `assertDiscriminates` in a gate.
 */
export async function discriminate<I>(
  spec: DiscriminateSpec<I>,
): Promise<DiscriminationResult> {
  const declared = Object.keys(spec.cases);
  const failures: PairFailure[] = [];
  const observed: Record<Tag, string> = {};

  if (declared.length < 2) {
    failures.push({
      kind: "NOT_A_PAIR",
      detail: `a pair needs at least two cases; got ${declared.length}. ` +
        `A single-case "pair" cannot show that anything differs.`,
    });
  }
  for (const tag of declared) {
    if (tag.trim() === "") {
      failures.push({
        kind: "EMPTY_TAG",
        declared: tag,
        detail: "a declared tag must be a non-empty name",
      });
    }
    if (tag.startsWith(OTHER_PREFIX)) {
      failures.push({
        kind: "RESERVED_TAG_DECLARED",
        declared: tag,
        detail:
          `"${OTHER_PREFIX}" is reserved for uncaught throws and can never be a ` +
          `declared verdict — declaring it would let a crash be written down as ` +
          `an expectation, which is exactly what rule 1 refuses.`,
      });
    }
  }

  // Cases run sequentially, in declaration order.
  for (const tag of declared) {
    let got: string;
    try {
      const raw = await spec.verdict(spec.cases[tag] as I);
      if (typeof raw !== "string" || raw.trim() === "") {
        failures.push({
          kind: "NON_TAG_VERDICT",
          declared: tag,
          observed: typeof raw === "string" ? JSON.stringify(raw) : String(raw),
          detail:
            `verdict returned ${typeof raw} (${String(raw)}); a verdict must be a ` +
            `named tag. A boolean makes non-constancy satisfiable by any crash.`,
        });
        observed[tag] = `NON_TAG:${String(raw)}`;
        continue;
      }
      got = raw;
    } catch (e) {
      got = `${OTHER_PREFIX}${messageOf(e)}`;
      failures.push({
        kind: "UNCAUGHT_THROW",
        declared: tag,
        observed: got,
        detail:
          `the verdict threw instead of returning a tag. An uncaught throw is ` +
          `not a verdict: it is how an unrelated crash passes for a refusal.`,
      });
      observed[tag] = got;
      continue;
    }

    observed[tag] = got;
    if (!declared.includes(got)) {
      failures.push({
        kind: "UNDECLARED_TAG",
        declared: tag,
        observed: got,
        detail:
          `"${got}" is outside the closed vocabulary [${declared.join(", ")}]. ` +
          `An unnamed verdict is an unmeasured one.`,
      });
    } else if (got !== tag) {
      failures.push({
        kind: "WRONG_TAG",
        declared: tag,
        observed: got,
        detail: `case "${tag}" produced "${got}"`,
      });
    }
  }

  // Non-constancy: no two cases may land on the same tag, and every declared
  // tag must have been reached by its own case.
  const seen = new Map<string, Tag>();
  for (const tag of declared) {
    const got = observed[tag];
    if (got === undefined) continue;
    const first = seen.get(got);
    if (first !== undefined) {
      failures.push({
        kind: "DUPLICATE_TAG",
        declared: tag,
        observed: got,
        detail:
          `cases "${first}" and "${tag}" both produced "${got}" — the verdict ` +
          `does not discriminate between them. A verdict collapsed to a ` +
          `constant fails here, on the first duplicate.`,
      });
    } else {
      seen.set(got, tag);
    }
  }
  for (const tag of declared) {
    if (!Object.values(observed).includes(tag)) {
      failures.push({
        kind: "UNREACHED_TAG",
        declared: tag,
        detail:
          `no case produced "${tag}". A declared tag nothing reaches is a check ` +
          `that did not run, and absence of an answer is never a pass.`,
      });
    }
  }

  const result: DiscriminationResult = {
    name: spec.name,
    ok: failures.length === 0,
    declared,
    observed,
    failures,
  };
  registry.push(result);
  emit(result);
  return result;
}

/** Human-readable failure report; the tags are always named. */
export function explain(r: DiscriminationResult): string {
  const lines = [
    `discriminate("${r.name}") ${r.ok ? "PASS" : "FAIL"}`,
    `  vocabulary: [${r.declared.join(", ")}]`,
    ...r.declared.map((t) => `  ${t} -> ${r.observed[t] ?? "<not run>"}`),
    ...r.failures.map((f) => `  ! ${f.kind}: ${f.detail}`),
  ];
  return lines.join("\n");
}

/** Run a pair and throw, with the named difference, if it does not hold. */
export async function assertDiscriminates<I>(
  spec: DiscriminateSpec<I>,
): Promise<DiscriminationResult> {
  const r = await discriminate(spec);
  if (!r.ok) throw new Error(explain(r));
  return r;
}

function emit(r: DiscriminationResult): void {
  const path = process.env.DISCRIMINATE_RECORD;
  if (!path) return;
  try {
    appendFileSync(
      path,
      JSON.stringify({
        name: r.name,
        ok: r.ok,
        declared: r.declared,
        observed: r.observed,
        failures: r.failures.map((f) => f.kind),
      }) + "\n",
      "utf-8",
    );
  } catch {
    // A record sink that cannot be written must not turn a real pair into a
    // failure — but it must not silently claim a record either. Mechanism 4
    // owns the published record; this sink is a convenience.
  }
}
