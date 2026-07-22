/**
 * Binding CM-decision registry (kernel element 5).
 *
 * WHY THIS EXISTS. The target profile offers a MENU of legal options for each
 * invariant (preserve-via-convergence-rule / weaken-to-eventual / …). Blind
 * builders pick DIFFERENT ones from identical inputs — birth-uniqueness split
 * three ways across the isolated builds (two-feature-composition-2026-07-20.md §4
 * & §5.5). A menu is not enough; the fan-out needs a registry that binds each
 * invariant to ONE chosen option AND its exact convergence rule, consumed by
 * every build, so a build FAILS LOUDLY if a decision it depends on is unresolved
 * or missing its convergence key.
 *
 * This is a typed reader over the ctkr port-decisions machinery
 * (src/ctkr/portDecisions.ts): a CmDecision is the convergence-carrying
 * specialization of a PortDecision, and {@link cmDecisionFromPortDecision} adapts
 * the PD JSONL format. The registry is the enforcement point where "locally
 * valid, globally incompatible" is actually prevented.
 */

import { existsSync, readFileSync } from "node:fs";

/** Sensitivity class from the target profile's decision_menu keys. */
export type Sensitivity = "hard" | "soft" | "none";

/**
 * Resolution state of a decision:
 *  - `bound`       — Duke-approved; the fan-out builds against it as fixed.
 *  - `provisional` — the kernel author's recommended pick, implemented now,
 *                    awaiting Duke's resolution. Still has a named convergence
 *                    rule, so it is buildable; flagged so it is never mistaken
 *                    for final.
 *  - `unresolved`  — no option chosen. A build depending on it MUST fail.
 */
export type ResolutionStatus = "bound" | "provisional" | "unresolved";

/**
 * One binding CM decision: an invariant tied to a single menu option and, for a
 * hard invariant preserved via convergence, the named rule that decides which
 * write wins and what happens to the loser.
 */
export interface CmDecision {
  /** invariant id, e.g. "birth-uniqueness", "id-scheme". */
  readonly invariant: string;
  readonly sensitivity: Sensitivity;
  /** the chosen option from the target-profile decision_menu. */
  readonly menuChoice: string;
  /** the named convergence rule (required for a bound/provisional HARD invariant). */
  readonly convergenceKey?: string;
  readonly status: ResolutionStatus;
  readonly rationale?: string;
  /** who recommended a provisional pick (so provenance is never silent). */
  readonly recommendedBy?: string;
  /**
   * Glossary ASSERTION TERMS this decision sanctions divergence on — a typed
   * citation, never a prose mention. The verifier resolves a port's declared
   * divergence against this list; names in `rationale`/`convergenceKey` never
   * sanction anything (the wave-1 lesson, MetaCoding-n9o: prose said
   * `yieldTotal`, the verifier speaks `yield_total`, and the one chosen
   * divergence scored as a bug in all four readings).
   */
  readonly sanctions?: readonly string[];
}

/** Thrown when a required CM decision is unresolved / missing / underspecified. */
export class UnboundDecisionError extends Error {
  constructor(
    message: string,
    public readonly invariant: string,
  ) {
    super(message);
    this.name = "UnboundDecisionError";
  }
}

const VALID_STATUS: ReadonlySet<ResolutionStatus> = new Set([
  "bound",
  "provisional",
  "unresolved",
]);
const VALID_SENSITIVITY: ReadonlySet<Sensitivity> = new Set(["hard", "soft", "none"]);

/**
 * The registry consumed by a build. `requireBound` is the enforcement call: a
 * build declares the invariants it depends on and the kernel refuses to hand
 * back a store until each is bound (or provisional-with-a-rule).
 */
export class CmDecisionRegistry {
  private readonly byInvariant = new Map<string, CmDecision>();

  constructor(decisions: readonly CmDecision[] = []) {
    for (const d of decisions) this.add(d);
  }

  add(d: CmDecision): this {
    this.byInvariant.set(d.invariant, d);
    return this;
  }

  get(invariant: string): CmDecision | undefined {
    return this.byInvariant.get(invariant);
  }

  list(): CmDecision[] {
    return [...this.byInvariant.values()];
  }

  /**
   * Return the decision for `invariant`, or throw loudly if it is unresolved,
   * absent, or (for a hard invariant) lacks its named convergence key. A
   * `provisional` decision with a convergence key passes — it is a real,
   * buildable binding awaiting only Duke's sign-off.
   */
  requireBound(invariant: string): CmDecision {
    const d = this.byInvariant.get(invariant);
    if (!d) {
      throw new UnboundDecisionError(
        `CM decision "${invariant}" is UNRESOLVED (no registry entry) — the build cannot proceed. Bind it in the CM-decision registry before fan-out.`,
        invariant,
      );
    }
    if (d.status === "unresolved") {
      throw new UnboundDecisionError(
        `CM decision "${invariant}" is explicitly UNRESOLVED — choose a menu option before building.`,
        invariant,
      );
    }
    if (d.sensitivity === "hard" && !d.convergenceKey) {
      throw new UnboundDecisionError(
        `CM decision "${invariant}" (${d.menuChoice}) is a HARD invariant but names no convergence key — preserve-via-convergence-rule must state which write wins and what happens to the loser.`,
        invariant,
      );
    }
    return d;
  }

  /** Assert every declared dependency is bound; returns the resolved decisions. */
  requireAllBound(invariants: readonly string[]): CmDecision[] {
    return invariants.map((i) => this.requireBound(i));
  }

  /** Invariants still awaiting Duke (provisional or unresolved) — for reporting. */
  pending(): CmDecision[] {
    return this.list().filter((d) => d.status !== "bound");
  }
}

// ---------------------------------------------------------------------------
// Validation + loaders
// ---------------------------------------------------------------------------

export function validateCmDecision(raw: unknown, hint?: string): CmDecision {
  const ctx = hint ? ` (${hint})` : "";
  if (typeof raw !== "object" || raw === null || Array.isArray(raw)) {
    throw new Error(`CM decision must be a non-null object${ctx}`);
  }
  const r = raw as Record<string, unknown>;
  for (const f of ["invariant", "sensitivity", "menuChoice", "status"] as const) {
    if (typeof r[f] !== "string" || !(r[f] as string).trim()) {
      throw new Error(`CM decision missing/empty string field "${f}"${ctx}`);
    }
  }
  if (!VALID_SENSITIVITY.has(r["sensitivity"] as Sensitivity)) {
    throw new Error(
      `CM decision "sensitivity" must be hard|soft|none — got ${JSON.stringify(r["sensitivity"])}${ctx}`,
    );
  }
  if (!VALID_STATUS.has(r["status"] as ResolutionStatus)) {
    throw new Error(
      `CM decision "status" must be bound|provisional|unresolved — got ${JSON.stringify(r["status"])}${ctx}`,
    );
  }
  if (r["convergenceKey"] !== undefined && typeof r["convergenceKey"] !== "string") {
    throw new Error(`CM decision "convergenceKey" must be a string when present${ctx}`);
  }
  return raw as CmDecision;
}

/** Load a CM-decision registry from a JSONL file (empty/`//` lines skipped). */
export function loadCmDecisions(path: string): CmDecision[] {
  if (!existsSync(path)) return [];
  const out: CmDecision[] = [];
  let lineNo = 0;
  for (const line of readFileSync(path, "utf8").split("\n")) {
    lineNo++;
    const t = line.trim();
    if (!t || t.startsWith("//")) continue;
    let parsed: unknown;
    try {
      parsed = JSON.parse(t);
    } catch (e) {
      throw new Error(`cm-decisions line ${lineNo}: JSON parse error — ${(e as Error).message}`);
    }
    out.push(validateCmDecision(parsed, `line ${lineNo}`));
  }
  return out;
}

/**
 * Adapt a ctkr PortDecision (src/ctkr/portDecisions.ts) into a CmDecision. A
 * `weaken` PD maps to `weaken-to-eventual`; `supersede` / `preserve-with-note`
 * map to `preserve-via-convergence-rule`. The PD carries no convergence key, so
 * one must be supplied for a hard invariant — surfacing exactly the gap the
 * kernel exists to close.
 */
export function cmDecisionFromPortDecision(pd: {
  targetElement: string;
  decision: "supersede" | "weaken" | "preserve-with-note";
  rationale: string;
  author?: string;
}, opts: { sensitivity: Sensitivity; convergenceKey?: string; status?: ResolutionStatus }): CmDecision {
  const menuChoice =
    pd.decision === "weaken" ? "weaken-to-eventual" : "preserve-via-convergence-rule";
  return {
    invariant: pd.targetElement,
    sensitivity: opts.sensitivity,
    menuChoice,
    convergenceKey: opts.convergenceKey,
    status: opts.status ?? "provisional",
    rationale: pd.rationale,
    recommendedBy: pd.author,
  };
}
