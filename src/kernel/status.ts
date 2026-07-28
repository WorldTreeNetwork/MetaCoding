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
 * THE GATE IS PER-PROJECTION, NOT GLOBAL (v1.3, re-bound on evidence 2026-07-20,
 * MetaCoding-ci2). v1.2 applied one blanket confirmed-only rule to the whole port.
 * The first oracle observation falsified that: farmOS is NOT uniform about pending.
 *   - a pending inventory adjustment does NOT move stock  (w0a-observe)
 *   - a pending adjustment IS counted by adjustment_count (w0a-observe)
 *   - a pending BIRTH log is FULLY effective — lineage and birth date both
 *     delivered (w0b-observe)
 *   - a pending MOVEMENT does not move the asset  (location-observe, 2026-07-28)
 * Same status field, same system, opposite answers. So each projection names its
 * own gate, and each row below cites what decided it: OBSERVED, or chosen.
 *
 * THE ONE DELIBERATE DIVERGENCE (Duke, MetaCoding-tkj) is `yieldTotal`/`logCount`:
 * farmOS counts pending harvests there (73ed7c69, d8607818 — records of the SOURCE,
 * never rewritten), and the port refuses to, on the grounds that a pending row in
 * the official total makes the pending state meaningless. The pending mass is
 * surfaced BESIDE the official figure via a `pending-only` partner rather than
 * blended in or dropped. That divergence was chosen with the evidence in hand; it
 * survived the re-bind. What did NOT survive was extending it to everything else.
 *
 * A projection whose gate is `require-confirmed` because the PORT chose it (not
 * because the source does) declares a `PENDING_PARTNER`, so the excluded mass is
 * always visible somewhere. See docs/design/shared-kernel.md §Element 4.
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
  // ---- logs: the ONE deliberate divergence Duke chose, knowing the evidence ----
  /** logs: THE official yield — confirmed harvests only. **Source-divergent by
   * choice** (v1.2): farmOS counts pending harvests here (73ed7c69, d8607818). */
  yieldTotal: "require-confirmed",
  /** logs: the pending yield, surfaced beside the official one, never added to it. */
  pendingYieldTotal: "pending-only",
  /** logs: the official log count — confirmed only. Same chosen divergence. */
  logCount: "require-confirmed",
  /** logs: how many logs are still pending — the partner of `logCount`. */
  pendingLogCount: "pending-only",
  /** logs: status is REPORTED as-is (the latest-wins value), never gated away. */
  logStatus: "count-regardless",

  // ---- location: gates set BY OBSERVATION (location-observe, 2026-07-28) ----
  // These three rows carried a "NOT OBSERVED" banner from 2026-07-20 to
  // 2026-07-28: the label had claimed observation agreed with the pick, no
  // recorded observation existed (all ten legacy location fixtures carry
  // provenance:null), and the OBSERVE pass was blocked because the flow DSL had
  // no location verbs. MetaCoding-b0s added them; the pass ran. The pack is
  // eval/ctkr/port_runs/lexicon-bind/location/observe (seal f3460165d338, 10
  // flows, self-verified 10/10 cold against the live farmOS 4.x oracle), and
  // every value below is one it recorded. The legacy synthetic fixtures are
  // superseded, not endorsed.
  /** location: a pending movement is proposed, not yet physically true → inert —
   * OBSERVED (`b0s-loc-a-pending-movement-is-inert`: after a done move to A and a
   * pending move to B, is_at_location(A) true and is_at_location(B) false).
   * A future-dated DONE movement is inert too, by the same rule
   * (`b0s-loc-a-future-dated-movement-is-not-yet-effective`). */
  currentLocation: "require-confirmed",
  /** location: assets-at-location reflects only confirmed movements — OBSERVED
   * from the ASSET's side, which is the only side farmOS answers at its
   * boundary: `filter[location.id]` 500s, and the reverse read exists solely as
   * AssetLocation::getAssetsByLocation, a raw SQL query. A probe for it would
   * re-implement the rule rather than transcribe it — the `group_member` defect —
   * so the same semantic is pinned per asset instead
   * (`b0s-loc-one-movement-carries-two-assets`: both named assets read at the
   * location, the third at none). The fan-out assertion stays open on
   * MetaCoding-b0s. */
  assetsAtLocation: "require-confirmed",
  /** location: a non-fixed asset's geometry comes from its confirmed movement —
   * OBSERVED (`b0s-loc-geometry-comes-from-the-movement`: an asset moved with
   * geometry "POINT (30 40)" reads back exactly that, while the PLACE it moved to
   * reads ""). A FIXED asset ignores movements entirely and keeps its own shape
   * (`b0s-loc-a-fixed-asset-ignores-movements`: moved with "POINT (30 40)", it
   * reads its own "POINT (1 2)" and is at no location). */
  currentGeometry: "require-confirmed",

  // ---- inventory: gates set BY OBSERVATION (w0a-observe, 2026-07-20) ----
  /** inventory: a pending adjustment does not move stock — OBSERVED
   * (`w0a-pending-adjustment-does-not-move-stock`: stock 2.0, the pending +3 excluded). */
  currentInventory: "require-confirmed",
  /** inventory: the pending stock movement, surfaced beside the official figure.
   * Port-additive — a projection farmOS does not offer, which changes no observed value. */
  pendingInventory: "pending-only",
  /** inventory: the adjustment COUNT includes pending ones — OBSERVED (same fixture:
   * adjustment_count == 2 while stock counted only the done one). Source-faithful. */
  adjustmentCount: "count-regardless",

  // ---- lineage: gates set BY OBSERVATION, and they are the OPPOSITE of inventory ----
  /** birth: a PENDING birth log is fully effective for lineage — OBSERVED
   * (`w0b-pending-birth-record`: parent_count == 1, has_parent(MOTHER) == True).
   * This is why the v1.2 blanket rule was wrong: pending is invisible to stock and
   * fully visible to lineage, in the SAME system. */
  parentage: "count-regardless",
  /** birth: a pending birth still delivers its date — OBSERVED (same fixture). */
  birthDate: "count-regardless",
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
  currentInventory: "pendingInventory",
} as const satisfies Partial<Record<string, string>>;

/** Convenience: does `status` pass the gate declared for `projection`? */
export function admits(projection: ProjectionName, status: LifecycleStatus): boolean {
  return passesGate(status, gateFor(projection));
}
