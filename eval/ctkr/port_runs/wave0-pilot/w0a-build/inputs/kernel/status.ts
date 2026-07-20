/**
 * Status-semantics contract (kernel element 4).
 *
 * WHY THIS EXISTS. `status` (pending | done) is one shared field, but each
 * projection's gate is a DIFFERENT, deliberate decision, and the isolated builds
 * disagreed: cell4 gated yield on `done` (wrong — failed 73ed7c69/d8607818) while
 * every other logs build counted pending toward yield; and the location feature
 * needs the opposite reading (a pending movement must NOT change current
 * location). See two-feature-composition-2026-07-20.md §4, "pending/status" row.
 *
 * The contract below FREEZES which projections are status-gated so a fan-out
 * author cannot re-litigate it. Both required readings are expressible and
 * enforced by construction:
 *   - pending-logs-count-toward-yield  → `yieldTotal`/`logCount` gate = count-regardless
 *   - pending-movements-inert          → `currentLocation` gate = require-confirmed
 */

/** How a projection treats a candidate's lifecycle status. */
export type StatusGate = "count-regardless" | "require-confirmed";

/** The lifecycle status carried by log_recorded / movement_recorded events. */
export type LifecycleStatus = "pending" | "done" | (string & {});

/** The status value that satisfies a `require-confirmed` gate. */
export const CONFIRMED_STATUS: LifecycleStatus = "done";

/**
 * The declared projection → gate table. This is the whole contract, as code.
 * Adding a status-bearing projection means adding a row here (a reviewed
 * decision), not re-deciding the gate ad hoc inside a feature.
 */
export const STATUS_CONTRACT = {
  /** logs: a pending harvest still asserts the harvest was recorded → counts. */
  yieldTotal: "count-regardless",
  /** logs: log_count includes pending and done alike. */
  logCount: "count-regardless",
  /** logs: status is REPORTED as-is (the latest-wins value), never gated away. */
  logStatus: "count-regardless",
  /** location: a pending movement is proposed, not yet physically true → inert. */
  currentLocation: "require-confirmed",
  /** location: assets-at-location reflects only confirmed movements. */
  assetsAtLocation: "require-confirmed",
  /** location: a non-fixed asset's geometry comes from its confirmed movement. */
  currentGeometry: "require-confirmed",
} as const satisfies Record<string, StatusGate>;

export type ProjectionName = keyof typeof STATUS_CONTRACT;

/** The frozen gate for a projection. */
export function gateFor(projection: ProjectionName): StatusGate {
  return STATUS_CONTRACT[projection];
}

/**
 * Does a candidate with `status` satisfy `gate`? Projections MUST route their
 * status filtering through this so the contract, not a local `if`, decides.
 */
export function passesGate(status: LifecycleStatus, gate: StatusGate): boolean {
  switch (gate) {
    case "count-regardless":
      return true;
    case "require-confirmed":
      return status === CONFIRMED_STATUS;
  }
}

/** Convenience: does `status` pass the gate declared for `projection`? */
export function admits(projection: ProjectionName, status: LifecycleStatus): boolean {
  return passesGate(status, gateFor(projection));
}
