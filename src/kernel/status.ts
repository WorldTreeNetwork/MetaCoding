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
 * author cannot re-litigate it.
 *
 * DELIBERATE SOURCE DIVERGENCE (kernel v1.2, Duke 2026-07-20, MetaCoding-tkj).
 * The live oracle shows farmOS counting PENDING harvests in `yield_total` and
 * `log_count` (observed fixtures 73ed7c69, d8607818 — both carry farmOS 4.x
 * provenance; they remain valid records of the SOURCE and were not rewritten).
 * The port intentionally departs: if a pending row lands in the official total,
 * the pending state means nothing. So the official numbers are CONFIRMED-ONLY and
 * the pending mass is surfaced BESIDE them rather than blended in or dropped:
 *   - `yieldTotal` / `logCount`               → require-confirmed (the official figure)
 *   - `pendingYieldTotal` / `pendingLogCount` → pending-only      (visible, never blended)
 *   - `currentLocation` &c.                   → require-confirmed (unchanged; source agrees)
 * A feature with a status-bearing numeric declares BOTH rows. See
 * docs/design/shared-kernel.md §Element 4.
 */

/**
 * How a projection treats a candidate's lifecycle status.
 *
 * `pending-only` is the mirror of `require-confirmed`: it admits exactly what the
 * official projection excludes, so a (official, pending) pair partitions the
 * candidates — nothing double-counted, nothing invisible.
 */
export type StatusGate = "count-regardless" | "require-confirmed" | "pending-only";

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
  /** logs: THE official yield — confirmed harvests only (source-divergent, v1.2). */
  yieldTotal: "require-confirmed",
  /** logs: the pending yield, surfaced beside the official one, never added to it. */
  pendingYieldTotal: "pending-only",
  /** logs: the official log count — confirmed only (source-divergent, v1.2). */
  logCount: "require-confirmed",
  /** logs: how many logs are still pending — the partner of `logCount`. */
  pendingLogCount: "pending-only",
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
    case "pending-only":
      return status !== CONFIRMED_STATUS;
  }
}

/**
 * The pending partner of an official projection, if the contract declares one.
 * A feature reading `yieldTotal` can find `pendingYieldTotal` without hard-coding
 * the naming convention — and the pairing is checked by test, so a
 * `require-confirmed` numeric can never ship without its pending counterpart.
 */
export const PENDING_PARTNER = {
  yieldTotal: "pendingYieldTotal",
  logCount: "pendingLogCount",
} as const satisfies Partial<Record<string, string>>;

/** Convenience: does `status` pass the gate declared for `projection`? */
export function admits(projection: ProjectionName, status: LifecycleStatus): boolean {
  return passesGate(status, gateFor(projection));
}
