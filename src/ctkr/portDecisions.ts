/**
 * Port Decisions log — ADR-style records of conscious divergence from the source
 * system's extracted spec (port-loop-plan.md cross-cutting #2).
 *
 * Format: one JSONL file per subsystem at `port_decisions/<subsystem_id>.jsonl`
 * relative to the data directory. Each record names the superseded source
 * intention, the target element (by the same cardSection address the punch list
 * uses), and why the divergence is deliberate. The port-verifier reads these
 * records to reclassify waived punch-list items; raw and net-of-waivers gate
 * scores are kept separate — waivers never weaken a check, only reclassify its
 * reporting.
 *
 * Subsystem ids are arbitrary strings (may contain "::" or "/"); the file-name
 * helper `portDecisionsPath` replaces unsafe characters with "__".
 */

import { readFileSync, existsSync } from "node:fs";

// ---------------------------------------------------------------------------
// Types
// ---------------------------------------------------------------------------

/**
 * What the decision does to the source intention:
 *
 * - `supersede`          — the source intention is intentionally not preserved;
 *                          the port replaces it with a different behavior or
 *                          design (e.g. replacing a central-authority constraint
 *                          with an eventual-consistency rule).
 * - `weaken`             — the source intention is partially relaxed (e.g.
 *                          optional vs. required, eventual vs. strong
 *                          consistency). Weaker than supersede; the intent
 *                          survives in reduced form.
 * - `preserve-with-note` — the intention is preserved but the port implements it
 *                          differently; the note records why the structural diff
 *                          (which the verifier would otherwise flag) is expected
 *                          and correct.
 */
export type DecisionKind = "supersede" | "weaken" | "preserve-with-note";

/**
 * One ADR-style port decision record.
 *
 * `targetElement` uses the same cardSection addressing scheme as the punch list:
 *   `roles[role_id=<id>]`
 *   `interface.provides[symbol=<qualified_name_or_id>]`
 *   `composition_rules[operation_id=<id>]`
 *   `functor.fidelity`
 *   `functor.cycle_consistency`
 *
 * A decision is matched against the punch list by exact string equality on
 * `targetElement` vs. `PunchListItem.cardSection`. If the targetElement appears
 * in the punch list, the item is marked waived (reported but not counted as a
 * failure in the net gates). If it matches nothing, the decision is reported as
 * a stale waiver — waivers must never silently rot.
 */
export interface PortDecision {
  /** Stable, unique id for this decision (e.g. "PD-001", "PD-auth-role-split"). */
  id: string;
  /** ISO-8601 date the decision was recorded (YYYY-MM-DD). */
  date: string;
  /** The subsystem this decision applies to (matches SubsystemSpec.subsystemId). */
  subsystem: string;
  /**
   * The punch-list cardSection address this decision waives, using the same
   * addressing scheme as `PunchListItem.cardSection`.
   */
  targetElement: string;
  /** What the decision does to the source intention. */
  decision: DecisionKind;
  /**
   * Free-text description of the source intention being superseded or modified.
   * Used in reports to identify exactly what was consciously changed.
   */
  supersededSourceIntention: string;
  /**
   * Optional row references into intention_signals.parquet that back the source
   * intention claim (e.g. a signal id or "intention_signals row 42").
   */
  intentionSignalRefs?: string[];
  /** Why this divergence is deliberate and acceptable. */
  rationale: string;
  /** Who recorded this decision (name or email). */
  author: string;
}

// ---------------------------------------------------------------------------
// Validation
// ---------------------------------------------------------------------------

const VALID_DECISIONS: ReadonlySet<DecisionKind> = new Set([
  "supersede",
  "weaken",
  "preserve-with-note",
]);

const REQUIRED_STRING_FIELDS = [
  "id",
  "date",
  "subsystem",
  "targetElement",
  "decision",
  "supersededSourceIntention",
  "rationale",
  "author",
] as const;

/**
 * Validate a raw parsed object as a `PortDecision`. Throws a descriptive error
 * if required fields are missing or have wrong types.
 */
export function validatePortDecision(raw: unknown, lineHint?: string): PortDecision {
  const ctx = lineHint ? ` (${lineHint})` : "";
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error(`port decision must be a non-null object${ctx}`);
  }
  const r = raw as Record<string, unknown>;
  for (const field of REQUIRED_STRING_FIELDS) {
    if (typeof r[field] !== "string" || !(r[field] as string).trim()) {
      throw new Error(`port decision missing or empty string field "${field}"${ctx}`);
    }
  }
  if (!VALID_DECISIONS.has(r["decision"] as DecisionKind)) {
    throw new Error(
      `port decision "decision" must be one of ${[...VALID_DECISIONS].join(" | ")} — got ${JSON.stringify(r["decision"])}${ctx}`,
    );
  }
  if (r["intentionSignalRefs"] !== undefined) {
    if (
      !Array.isArray(r["intentionSignalRefs"]) ||
      !r["intentionSignalRefs"].every((x) => typeof x === "string")
    ) {
      throw new Error(`port decision "intentionSignalRefs" must be a string[] when present${ctx}`);
    }
  }
  return raw as PortDecision;
}

// ---------------------------------------------------------------------------
// Loader
// ---------------------------------------------------------------------------

/**
 * Load port decision records from a JSONL file. Returns `[]` when the file
 * does not exist — no decisions recorded yet is a valid, non-error state.
 * Throws on JSON parse errors or validation failures.
 *
 * Lines that are empty or start with `//` are skipped (comments).
 */
export function loadPortDecisions(path: string): PortDecision[] {
  if (!existsSync(path)) return [];
  const text = readFileSync(path, "utf8");
  const records: PortDecision[] = [];
  let lineNo = 0;
  for (const line of text.split("\n")) {
    lineNo++;
    const trimmed = line.trim();
    if (!trimmed || trimmed.startsWith("//")) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(trimmed);
    } catch (e) {
      throw new Error(
        `port_decisions line ${lineNo}: JSON parse error — ${(e as Error).message}`,
      );
    }
    records.push(validatePortDecision(parsed, `line ${lineNo}`));
  }
  return records;
}

/**
 * Conventional path for a subsystem's decisions file within a data directory.
 *
 * Subsystem ids may contain "::", "/", or ":" — these are replaced with "__"
 * to produce a safe filename. The directory `<dataDir>/port_decisions/` must
 * exist or be created by the caller before writing; `loadPortDecisions` handles
 * a missing file gracefully.
 *
 * @example
 *   portDecisionsPath("/data/.metacoding", "ss:farmOS::logs")
 *   // → "/data/.metacoding/port_decisions/ss__farmOS____logs.jsonl"
 */
export function portDecisionsPath(dataDir: string, subsystemId: string): string {
  const safe = subsystemId.replace(/[:/\\]+/g, "__");
  return `${dataDir}/port_decisions/${safe}.jsonl`;
}
