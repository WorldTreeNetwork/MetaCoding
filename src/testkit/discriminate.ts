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
//    A sink that was ASKED for and could not be written FAILS the pair
//    (RECORD_SINK_UNWRITABLE). Absence of a record is never a pass: a silent
//    swallow here would be this document's own property violated inside the
//    mechanism that enforces it, and mechanism 4 is specified to read this file.
//
// TWO VERBS, AND THE SHORT NAME IS THE ONE THAT ENFORCES
// -------------------------------------------------------
// `discriminate(spec)` THROWS the named difference when the pair does not hold.
// It is what the design document, CLAUDE.md and this file's name advertise, so
// it is what a gate gets by reaching for the obvious thing. `observeDiscrimination`
// returns the result without throwing; this module's own fixtures need to see a
// REFUSAL without the suite dying, and that argues for its existence, not for it
// owning the short name. It previously did, and the consequence was measured
// (MetaCoding-3ad): a pair that refused with DUPLICATE_TAG + UNREACHED_TAG left
// its containing test GREEN, because nothing made the caller read the result.
//
// TAGS ARE NAMES, AND INTEGER-LIKE TAGS ARE REFUSED
// -------------------------------------------------
// `cases` is a plain object, and JavaScript enumerates array-index-like keys
// FIRST, in ascending numeric order, regardless of insertion order: declaring
// {"2": …, "10": …, "1": …} runs 1, 2, 10. Declaration order is load-bearing —
// seam.test.ts's class 6 depends on the state class 5 established — so a silent
// reorder would run a DIFFERENT experiment than the one declared and still
// report ok. Rather than let that be quiet, an integer-like tag is an instrument
// failure by name (INDEX_LIKE_TAG). Name the pass: `PASS_1`, not `1`.
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
  | "INDEX_LIKE_TAG" // a declared tag is integer-like; JS would reorder it
  | "RECORD_SINK_UNWRITABLE" // DISCRIMINATE_RECORD was set and could not be written
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
   *
   * Declaration order is only honoured because integer-like tags are REFUSED
   * (INDEX_LIKE_TAG) — JS enumerates array-index keys first, ascending, so
   * {"2","10","1"} would silently run 1,2,10. Name the tag; do not number it.
   */
  cases: Record<Tag, I>;
}

/**
 * Tags JavaScript would reorder, plus the near-misses ("007", "-1") that read as
 * numbers to a human. Refused by name; see the header.
 */
const INDEX_LIKE = /^[+-]?\d+$/;

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
 * Run one contrast pair and RETURN the result without throwing.
 *
 * This is the raw form, and it deliberately does not own the short name. The
 * fixtures in discriminate.test.ts must be able to OBSERVE a refusal without
 * the suite dying, which argues for this function's existence — not for it
 * being what a gate reaches for. A gate that calls a non-throwing verb and
 * drops the result is green while the pair is refused; that is a check that
 * cannot fail, wearing the name of the mechanism against checks that cannot
 * fail. Gates call `discriminate`, which throws.
 *
 * Intended caller: src/testkit/discriminate.test.ts, and nothing else.
 */
export async function observeDiscrimination<I>(
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
    if (INDEX_LIKE.test(tag)) {
      failures.push({
        kind: "INDEX_LIKE_TAG",
        declared: tag,
        detail:
          `"${tag}" is integer-like. JavaScript enumerates array-index-like ` +
          `keys FIRST and in ascending numeric order, so a declaration of ` +
          `{"2","10","1"} runs 1,2,10 — a DIFFERENT experiment than the one ` +
          `written down, reported as ok. Declaration order is load-bearing ` +
          `(a case may depend on state an earlier case established). Name the ` +
          `tag instead of numbering it: PASS_1, not 1.`,
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

  // Rule 3's sink. A record that was ASKED for and could not be written is a
  // failure of the pair, not a shrug: "nothing was written and nothing was
  // said" is exactly the report-a-result-for-a-check-that-did-not-run shape
  // this module exists to refuse. `failures` is the same array the result
  // holds, so the registry entry (pushed above) carries this too.
  const sinkError = emit(result);
  if (sinkError !== null) {
    failures.push({
      kind: "RECORD_SINK_UNWRITABLE",
      observed: sinkError,
      detail:
        `DISCRIMINATE_RECORD was set to "${process.env.DISCRIMINATE_RECORD}" ` +
        `and the pair could not be appended to it: ${sinkError}. A record ` +
        `nobody can write is not a record; absence of an answer is never a pass.`,
    });
    result.ok = false;
  }
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

/**
 * Run one contrast pair and THROW, with the named difference, if it does not
 * hold. This is the verb the design document, CLAUDE.md and this file's name
 * advertise, so it is the one that enforces: a caller who ignores the return
 * value still fails. See `observeDiscrimination` for the non-throwing form and
 * why it does not own this name.
 */
export async function discriminate<I>(
  spec: DiscriminateSpec<I>,
): Promise<DiscriminationResult> {
  const r = await observeDiscrimination(spec);
  if (!r.ok) throw new Error(explain(r));
  return r;
}

/** Append the pair to DISCRIMINATE_RECORD. Returns null, or the error message. */
function emit(r: DiscriminationResult): string | null {
  const path = process.env.DISCRIMINATE_RECORD;
  if (!path) return null;
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
    return null;
  } catch (e) {
    return messageOf(e);
  }
}
