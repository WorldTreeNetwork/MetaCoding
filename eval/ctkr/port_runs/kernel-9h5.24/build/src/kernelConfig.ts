// The build's DECLARED extension of the shared kernel: the closed kind taxonomy
// for the logs+location composed store, and the binding CM-decision registry it
// depends on. Both are "fixed input" a fan-out builder consumes — this file is
// where this build states which kinds exist and which CM decisions it relies on.

import {
  KindRegistry,
  type KindSpec,
  type CmDecision,
} from "../../../../../../src/kernel/index.ts";

// ---- Closed event-kind taxonomy (kernel element 1) ----
//
// is-a-movement-a-log is RESOLVED here, centrally: `movement_recorded` has
// `isLog: false` and family "movement". A movement therefore never contributes
// to logCount / yield (which fold family "log"), while still sharing the one
// event log and the one status lifecycle. This is the provisional pick
// (movement-as-log-taxonomy); the alternative (movement IS an `activity` log,
// farmOS-faithful) is documented for Duke in docs/design/shared-kernel.md.
export const CORE_KINDS: readonly KindSpec[] = [
  { kind: "asset_created", family: "asset", isLog: false, description: "births an asset into the shared model" },
  // v1.2: the official numerics are confirmed-only; the pending mass is read
  // through the pending-only partner projections, not through this default.
  { kind: "log_recorded", family: "log", isLog: true, statusGate: "require-confirmed", description: "a domain log (harvest/input/activity/observation/seeding)" },
  { kind: "log_status_changed", family: "status", isLog: false, description: "reassigns the lifecycle status of a log OR a movement" },
  { kind: "group_assigned", family: "membership", isLog: false, description: "latest-wins group membership" },
  { kind: "asset_archived", family: "lifecycle", isLog: false, description: "flips assetActive; leaves history intact" },
  { kind: "movement_recorded", family: "movement", isLog: false, statusGate: "require-confirmed", description: "a location movement — NOT a log (see taxonomy decision)" },
  { kind: "geometry_set", family: "geometry", isLog: false, description: "sets a fixed asset's intrinsic geometry" },
];

/** The frozen registry every store instance shares. */
export function makeKernelRegistry(): KindRegistry {
  return new KindRegistry().extend(CORE_KINDS).freeze();
}

// ---- Binding CM-decision registry (kernel element 5) ----
//
// The three sub-decisions the composition run surfaced, plus the two other
// kernel invariants, each bound to a recommended menu option. birth-uniqueness
// and movement-as-log-taxonomy are `bound` — Duke confirmed both in the
// 2026-07-20 elicitation review (MetaCoding-tkj). The remaining three are still
// `provisional` (kernel author's pick, awaiting review), but each carries a named
// convergence key, so `requireBound` accepts them and the build proceeds.
// Mirrored, line-for-line, by ./cm-decisions.jsonl (loaded + checked in tests).
export const BOUND_CM_DECISIONS: readonly CmDecision[] = [
  {
    invariant: "birth-uniqueness",
    sensitivity: "hard",
    menuChoice: "preserve-via-convergence-rule",
    convergenceKey: "earliest-hlc-wins; later concurrent birth demoted to observation (never dropped)",
    status: "bound",
    rationale:
      "A birth log is a hard 'at most one per asset' invariant, but this target has no coordination layer, so a central write-time gate is off the menu. Two replicas can each record a birth offline; on merge the earliest by HLC survives and the loser is demoted, not silently dropped. BOUND 2026-07-20 by Duke (elicitation review MetaCoding-tkj): a farmer-visible surfaced duplicate is the desired outcome. OBSERVATION NOTE 2026-07-20: this rule is UNOBSERVABLE against the source — farmOS REFUSES a second birth claim at write time (422 'more than one birth log cannot reference the same child'), so no state exists in which two claims coexist and no oracle value can confirm or refute the resolution rule. The decision stands as a port choice (refuse-vs-resolve is a real semantic divergence); it simply has zero oracle grounding. See wave1-readiness-2026-07-20.md §2.5.",
    recommendedBy: "shared-kernel-v1",
  },
  {
    invariant: "id-scheme",
    sensitivity: "hard",
    menuChoice: "preserve-via-convergence-rule",
    convergenceKey: "replica-scoped client id (prefix_replicaId~counter); collision-free by construction, no merge step needed",
    status: "bound",
    rationale:
      "Replaces the composed build's bare integer counter (asset_7), which collides across replicas. Replica-id+counter is collision-free without RNG and keeps the serial component non-portable. uuid-v7 is the alternative (opaque, needs RNG); see design doc. BOUND 2026-07-20 by Duke (elicitation review MetaCoding-tkj): determinism and no-RNG beat uuid-v7's opacity, and uuid-v7's time-sortability would invite ordering by id.",
    recommendedBy: "shared-kernel-v1",
  },
  {
    invariant: "movement-as-log-taxonomy",
    sensitivity: "soft",
    menuChoice: "distinct-kind-not-a-log",
    convergenceKey: "n/a (taxonomy facet, not a convergence rule)",
    status: "bound",
    rationale:
      "A movement is its own event kind with isLog:false, so it never inflates logCount/yield — matches the composed build and keeps the numeric folds clean. Alternative: model it as a farmOS `activity` log (isLog:true), which would change CP2's logCount('activity'). BOUND 2026-07-20 by Duke (elicitation review MetaCoding-tkj): clean numeric folds beat farmOS activity-log fidelity.",
    recommendedBy: "shared-kernel-v1",
  },
  {
    invariant: "membership-model",
    sensitivity: "hard",
    menuChoice: "preserve-via-convergence-rule",
    convergenceKey: "LWW-register on group_assigned keyed by HLC (latest assignment wins; prior revoked)",
    status: "bound",
    rationale:
      "Kills the additive-membership attractor that made three builds fail ce015be4. Membership is a single latest-wins register folded through the kernel comparator, never a growing set. BOUND 2026-07-20 by Duke (elicitation review MetaCoding-tkj): matches the observed fixture 'reassigning an animal to a new group revokes the prior membership' — an asset is in exactly one group at a time.",
    recommendedBy: "shared-kernel-v1",
  },
  {
    invariant: "pending-status-gates",
    sensitivity: "soft",
    menuChoice: "supersede-with-port-semantics",
    convergenceKey: "STATUS_CONTRACT table: yieldTotal/logCount require-confirmed, pendingYieldTotal/pendingLogCount pending-only (partition), currentLocation require-confirmed",
    status: "provisional",
    rationale:
      "CONTESTED BY OBSERVATION — demoted bound->provisional 2026-07-20 pending Duke's re-bind (MetaCoding-ci2). Originally a deliberate source divergence bound by Duke (elicitation review MetaCoding-tkj): official numerics confirmed-only, pending mass surfaced in partner projections. The first oracle observation shows the BLANKET rule is only half right — farmOS excludes pending from inventory stock_on_hand (the port matches) but honours a pending log FULLY for birth lineage and birth_date (the port would report no parent and no date, a divergence v1.2 does not sanction). Evidence: eval/ctkr/port_runs/wave0-pilot/w0b-observe/fixtures.jsonl (w0b-pending-birth-record) and w0a-observe (w0a-pending-adjustment-does-not-move-stock); analysis in eval/ctkr/results/wave1-readiness-2026-07-20.md §2.4. The gate is per-PROJECTION, not global. Still buildable (named convergence key) but NOT settled — do not cite as Duke-approved.",
    recommendedBy: "shared-kernel-v1",
  },
];

/** The CM decisions this build DECLARES it depends on — enforced at store construction. */
export const REQUIRED_DECISIONS: readonly string[] = [
  "birth-uniqueness",
  "id-scheme",
  "movement-as-log-taxonomy",
  "membership-model",
  "pending-status-gates",
];
