// floors.ts — a floor is not a number. It is a PAIR: a value, and the NAME of
// the field the instrument publishes it against.
//
// WHY THIS FILE EXISTS (docs/design/lessons-as-mechanism.md, mechanism 4)
// ======================================================================
// The root cause was not that thresholds were guessed. It is that the
// INSTRUMENT DID NOT PUBLISH THE QUANTITY THE BUILDER WAS TOLD TO CALIBRATE
// FROM: a section's ROW count is not its CHECK count, and only rows were
// visible. Three rounds of guessing followed, each refused by a correct run.
// The fix that worked was three lines — farmos-port/tools/ledger.py:425
// publishes a `coverage` object on the SUMMARY row, and :421 records why:
//
//     "the comments tell a builder to set floors from a measurement, so the
//      measurement has to be in the file."
//
// The SHARED ledger then initially LOST that line, which every hand-written
// version had. That is why the rule has to be structural rather than
// remembered: a discipline that four independent authors each invented and a
// fifth extraction dropped is not a discipline, it is a missing mechanism.
//
// THE RULE, stated so it can refuse things
// ----------------------------------------
// A floor over a field the instrument does not publish is an INSTRUMENT
// failure, never a pass and never a warning. That distinction is the entire
// mechanism. Without it this file is a comment: "calibrate from a measurement
// that does not exist" stays a soft problem you solve by guessing again.
//
// MEASURED BEFORE THIS SHIPPED: 22 scripts/smoke-*.ts, 4 to 11 assertions
// each, and ZERO published how many checks they ran. A truncated run and a
// complete run were BYTE-IDENTICAL — `PATHS_SMOKE_PASS`, exit 0, either way.
//
// WHY THE COUNT IS DERIVED AND NOT DECLARED
// -----------------------------------------
// A hand-maintained `checks: 7` defeats the whole thing in the exact way the
// failure happened: delete three assertions, the constant still says 7, the
// floor still passes. So `checks` is counted by `run.check()` at the moment
// each check RUNS, and `pairs` is read from discriminate.ts's registry
// (rule 3 of mechanism 1). Neither number can be written down; both can only
// be earned. Two checks sharing one label are refused (DUPLICATE_CHECK) —
// counting one check twice is how a derived count gets faked back into a
// declared one.
//
// THE PASS TOKEN BELONGS TO THE GATE
// ----------------------------------
// `run.finish(floors)` is what prints `<NAME>_SMOKE_PASS`. A script that does
// not reach the gate cannot print the token that says it passed. This is the
// only defence available against "the author forgot to publish", and it is
// partial: a script that never calls `beginRun` at all is not checked by this
// module. That limit is stated rather than hidden (lessons-as-mechanism.md:274);
// the suite-level half is scripts/smoke-all.ts, which refuses a script that
// emitted no record.
//
// HOW THIS IS STILL FAKEABLE, at the point of use
// -----------------------------------------------
// `measuredAs` proves the FIELD exists. Nothing here proves the `min` was
// derived from a deliberate measurement rather than copied from last night's
// output. A floor set to yesterday's number is a ratchet that never fires.
// `why` is a prose mitigation and prose mitigations are what the design
// document argues against; its status is OPEN and deliberately accepted
// (lessons-as-mechanism.md:264), because the failure mode is a floor that
// UNDER-fires, which is where we already are. What is NOT accepted, and is
// refused structurally below, is a floor that CANNOT fire: `min < 1` is
// VACUOUS_FLOOR, because the cheapest green is an empty run
// (farmos-port/tools/ledger.py:176-186).
//
// A floor also says nothing about whether the checks it counts are any good.
// An instrument that runs every check, publishes every count, and applies the
// wrong predicate satisfies this file completely (lessons-as-mechanism.md:36).

import { appendFileSync } from "node:fs";

import { recordedPairs } from "./discriminate.ts";

/**
 * A floor: a value AND the name of the published field it is measured against.
 * `why` records what the min was derived from — see the fakeability note above
 * for exactly how much that is worth.
 */
export interface Floor {
  min: number;
  measuredAs: string;
  why: string;
}

/** A published record: field name -> the number the instrument actually emitted. */
export type Published = Record<string, number>;

export type FloorFailureKind =
  // INSTRUMENT tier — the measuring apparatus is broken or absent.
  | "NO_FLOORS" // zero floors declared; nothing can be refused
  | "VACUOUS_FLOOR" // min < 1: satisfied by a run that did nothing
  | "MISSING_MEASURED_AS" // a floor with no field name is just a number
  | "MISSING_WHY" // a floor that does not say what it was derived from
  | "DUPLICATE_FLOOR" // two floors over one field; the weaker one hides the other
  | "UNPUBLISHED_FIELD" // THE ONE: a floor over a field nobody emits
  | "NON_NUMERIC_FIELD" // published, but not a finite number
  | "RECORD_SINK_UNWRITABLE" // SMOKE_RECORD_FILE was asked for and could not be written
  // CHECK tier — the apparatus worked and the measurement came up short.
  | "FLOOR_UNMET";

export type FloorTier = "INSTRUMENT" | "CHECK";

export interface FloorFailure {
  kind: FloorFailureKind;
  tier: FloorTier;
  /** The field this failure is about, when there is one. */
  measuredAs?: string;
  /** What the instrument published for it, when it published anything. */
  observed?: number | string;
  detail: string;
}

export interface FloorsResult {
  ok: boolean;
  /** True if ANY failure is INSTRUMENT tier. Distinct from a short measurement. */
  instrumentFailed: boolean;
  published: Published;
  failures: FloorFailure[];
}

const registry: FloorsResult[] = [];

/** Every floors evaluation in this process, in order. */
export function recordedFloors(): readonly FloorsResult[] {
  return registry;
}

/** Clear the registry. For this module's own fixtures; not for gates. */
export function resetRecordedFloors(): void {
  registry.length = 0;
}

/**
 * Evaluate floors against what the instrument published, RETURNING the result
 * without throwing.
 *
 * This is the raw form and it deliberately does not own the advertised name.
 * The fixtures in floors.test.ts must be able to OBSERVE a refusal without the
 * suite dying — that argues for this function's existence, not for it being
 * what a gate reaches for. A gate that calls a non-throwing verb and drops the
 * result is green while the floors are refused; that is a check that cannot
 * fail wearing the name of the mechanism against checks that cannot fail. It
 * is not hypothetical: it was measured on discriminate.ts (MetaCoding-3ad),
 * where a pair refusing with DUPLICATE_TAG left its test GREEN.
 *
 * Gates call `evaluateFloors`, which throws.
 */
export function observeFloors(floors: readonly Floor[], published: Published): FloorsResult {
  const failures: FloorFailure[] = [];

  if (floors.length === 0) {
    failures.push({
      kind: "NO_FLOORS",
      tier: "INSTRUMENT",
      detail:
        "no floors declared. A record with nothing measured against it cannot " +
        "refuse anything, and reports PASS for a run that did nothing.",
    });
  }

  const seen = new Set<string>();
  for (const f of floors) {
    const field = f.measuredAs;
    if (typeof field !== "string" || field.trim() === "") {
      failures.push({
        kind: "MISSING_MEASURED_AS",
        tier: "INSTRUMENT",
        observed: String(field),
        detail:
          `a floor of ${f.min} with no measuredAs is just a number. A floor is ` +
          `a PAIR — a value and the NAME of the field it is measured against.`,
      });
      continue;
    }
    if (typeof f.why !== "string" || f.why.trim() === "") {
      failures.push({
        kind: "MISSING_WHY",
        tier: "INSTRUMENT",
        measuredAs: field,
        detail:
          `floor over "${field}" does not say what its min was derived from. ` +
          `This is the weakest guard in this file (see the header) but an ` +
          `undocumented threshold is the shape the failure took three times.`,
      });
    }
    if (!Number.isFinite(f.min) || f.min < 1) {
      failures.push({
        kind: "VACUOUS_FLOOR",
        tier: "INSTRUMENT",
        measuredAs: field,
        observed: f.min,
        detail:
          `min=${f.min} over "${field}" is satisfied by a run that did nothing. ` +
          `The cheapest green is an empty run; a floor that an empty run passes ` +
          `is not a floor.`,
      });
    }
    if (seen.has(field)) {
      failures.push({
        kind: "DUPLICATE_FLOOR",
        tier: "INSTRUMENT",
        measuredAs: field,
        detail:
          `two floors over "${field}". Only one can be the binding one, and ` +
          `which is silent — a weaker duplicate hides a stronger floor.`,
      });
    }
    seen.add(field);

    // THE RULE. A floor over a field the instrument does not publish is an
    // INSTRUMENT failure. Absence of an answer is never a pass.
    if (!Object.prototype.hasOwnProperty.call(published, field)) {
      failures.push({
        kind: "UNPUBLISHED_FIELD",
        tier: "INSTRUMENT",
        measuredAs: field,
        detail:
          `floor of ${f.min} is measured against "${field}", which this ` +
          `instrument does not publish. Published fields: ` +
          `[${Object.keys(published).join(", ") || "<none>"}]. This is an ` +
          `INSTRUMENT failure, not a check failure and not a warning: the ` +
          `builder was told to calibrate from a measurement that does not ` +
          `exist. Publish "${field}", or measure the floor against something ` +
          `the instrument actually emits.`,
      });
      continue;
    }

    const value = published[field];
    if (typeof value !== "number" || !Number.isFinite(value)) {
      failures.push({
        kind: "NON_NUMERIC_FIELD",
        tier: "INSTRUMENT",
        measuredAs: field,
        observed: String(value),
        detail:
          `"${field}" was published as ${typeof value} (${String(value)}); a ` +
          `floor needs a finite number. A field that is present but not a ` +
          `measurement is absence wearing presence's clothes.`,
      });
      continue;
    }

    if (value < f.min) {
      failures.push({
        kind: "FLOOR_UNMET",
        tier: "CHECK",
        measuredAs: field,
        observed: value,
        detail: `"${field}" = ${value}, floor is ${f.min} (${f.why})`,
      });
    }
  }

  const result: FloorsResult = {
    ok: failures.length === 0,
    instrumentFailed: failures.some((f) => f.tier === "INSTRUMENT"),
    published,
    failures,
  };
  registry.push(result);
  return result;
}

/** Human-readable report. Every field and every floor is named. */
export function explainFloors(r: FloorsResult): string {
  const lines = [
    `floors ${r.ok ? "PASS" : r.instrumentFailed ? "INSTRUMENT FAILURE" : "FAIL"}`,
    `  published: ${JSON.stringify(r.published)}`,
    ...r.failures.map((f) => `  ! ${f.tier} ${f.kind}: ${f.detail}`),
  ];
  return lines.join("\n");
}

/** Thrown by `evaluateFloors`. Carries the result so a caller can inspect it. */
export class FloorsRefused extends Error {
  readonly result: FloorsResult;
  constructor(result: FloorsResult) {
    super(explainFloors(result));
    this.name = "FloorsRefused";
    this.result = result;
  }
}

/**
 * Evaluate floors against the published record and THROW if they do not hold.
 * This is the verb the design document and the bead advertise, so it is the one
 * that enforces: a caller who ignores the return value still fails.
 */
export function evaluateFloors(floors: readonly Floor[], published: Published): FloorsResult {
  const r = observeFloors(floors, published);
  if (!r.ok) throw new FloorsRefused(r);
  return r;
}

// ---------------------------------------------------------------------------
// The recorder: what makes `checks` a DERIVED number rather than a declared one
// ---------------------------------------------------------------------------

/** Field names the run derives itself. A `measure()` may not overwrite them. */
export const DERIVED_FIELDS = ["checks", "pairs"] as const;

export class SmokeCheckFailed extends Error {
  readonly label: string;
  constructor(label: string, detail: string) {
    super(`check "${label}" FAILED: ${detail}`);
    this.name = "SmokeCheckFailed";
    this.label = label;
  }
}

export class InstrumentMisuse extends Error {
  constructor(detail: string) {
    super(detail);
    this.name = "InstrumentMisuse";
  }
}

export interface SmokeRecord {
  script: string;
  published: Published;
  /** Labels of the checks that actually ran, in order. */
  checkLabels: string[];
  /** Names of the discriminate() pairs registered during this run. */
  pairNames: string[];
  floors: Floor[];
  ok: boolean;
}

/**
 * One smoke script's run. `check()` is the only way a check is counted, which
 * is the point: deleting an assertion deletes it from the count too, and the
 * floor over `checks` fails BY NAME rather than the run staying byte-identical.
 */
export class SmokeRun {
  readonly script: string;
  private readonly labels: string[] = [];
  private readonly extra: Published = {};
  private readonly pairsAtStart: number;

  constructor(script: string) {
    if (script.trim() === "") throw new InstrumentMisuse("a run needs a script name");
    this.script = script;
    this.pairsAtStart = recordedPairs().length;
  }

  /**
   * Record and enforce one check. Throws `SmokeCheckFailed` when `ok` is false
   * — the check is counted only when it PASSES, so a truncated run reports a
   * smaller number and a failed run does not report at all.
   */
  check(label: string, ok: boolean, detail = ""): void {
    if (typeof label !== "string" || label.trim() === "") {
      throw new InstrumentMisuse("every check needs a label; the difference must be named");
    }
    if (this.labels.includes(label)) {
      // Counting one check twice is how a derived count is faked back into a
      // declared one.
      throw new InstrumentMisuse(
        `DUPLICATE_CHECK: "${label}" was already recorded by this run. Two ` +
          `checks sharing one label inflate a count that is supposed to be earned.`,
      );
    }
    if (typeof ok !== "boolean") {
      throw new InstrumentMisuse(
        `check "${label}" was given ${typeof ok} (${String(ok)}); a truthy value ` +
          `is not a verdict — pass an explicit boolean.`,
      );
    }
    if (!ok) throw new SmokeCheckFailed(label, detail);
    this.labels.push(label);
  }

  /** Publish an additional measured quantity under `field`. */
  measure(field: string, value: number): void {
    if (typeof field !== "string" || field.trim() === "") {
      throw new InstrumentMisuse("a measurement needs a field name");
    }
    if ((DERIVED_FIELDS as readonly string[]).includes(field)) {
      throw new InstrumentMisuse(
        `"${field}" is DERIVED by the run and may not be written by hand — a ` +
          `hand-written count is the defect this file exists to remove.`,
      );
    }
    if (Object.prototype.hasOwnProperty.call(this.extra, field)) {
      throw new InstrumentMisuse(`"${field}" was already measured by this run`);
    }
    if (typeof value !== "number" || !Number.isFinite(value)) {
      throw new InstrumentMisuse(`"${field}" must be a finite number; got ${String(value)}`);
    }
    this.extra[field] = value;
  }

  /** Names of the discriminate() pairs registered since this run began. */
  pairNames(): string[] {
    return recordedPairs()
      .slice(this.pairsAtStart)
      .map((p) => p.name);
  }

  /**
   * What this run actually did. `checks` and `pairs` are counted, never
   * declared.
   */
  publish(): Published {
    return { checks: this.labels.length, pairs: this.pairNames().length, ...this.extra };
  }

  /**
   * Evaluate the floors against what was actually published, emit the
   * machine-readable record, and print `<SCRIPT>_SMOKE_PASS`.
   *
   * The gate owns the pass token: a script that does not reach here cannot
   * print the line that says it passed.
   */
  finish(floors: readonly Floor[]): FloorsResult {
    const published = this.publish();
    const observed = observeFloors(floors, published);
    const record: SmokeRecord = {
      script: this.script,
      published,
      checkLabels: [...this.labels],
      pairNames: this.pairNames(),
      floors: [...floors],
      ok: observed.ok,
    };
    // Emit BEFORE refusing: the record of a failed run is the thing that says
    // which check went missing, and it must survive the throw.
    const sinkError = emitRecord(record);
    console.log(`SMOKE_RECORD ${JSON.stringify(record)}`);
    if (sinkError !== null) {
      // A sink that was ASKED for and could not be written is a failure, not a
      // shrug. discriminate.ts pays for this same lesson (RECORD_SINK_UNWRITABLE):
      // "nothing was written and nothing was said" is the shape being refused.
      observed.failures.push({
        kind: "RECORD_SINK_UNWRITABLE",
        tier: "INSTRUMENT",
        detail:
          `SMOKE_RECORD_FILE was set to "${process.env.SMOKE_RECORD_FILE}" and ` +
          `the record could not be written: ${sinkError}. A record nobody can ` +
          `write is not a record.`,
      });
      observed.ok = false;
      observed.instrumentFailed = true;
    }
    if (!observed.ok) throw new FloorsRefused(observed);
    console.log(`${this.script.toUpperCase().replace(/[^A-Z0-9]+/g, "_")}_SMOKE_PASS`);
    return observed;
  }
}

/** Begin a smoke run. `script` names it and supplies the PASS token's prefix. */
export function beginRun(script: string): SmokeRun {
  return new SmokeRun(script);
}

function emitRecord(record: SmokeRecord): string | null {
  const path = process.env.SMOKE_RECORD_FILE;
  if (!path) return null;
  try {
    appendFileSync(path, JSON.stringify(record) + "\n", "utf-8");
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : String(e);
  }
}
