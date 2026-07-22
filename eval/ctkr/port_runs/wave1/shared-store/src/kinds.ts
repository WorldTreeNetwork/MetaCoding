// Wave-1 log-family closed kind taxonomy — the ONE shared store shape all four
// wave-1 features (w1a activity, w1b observation, w1c harvest, w1d input) fold
// through. Kinds reused from the kernel-9h5.24 composed build keep their exact
// names (asset_created, log_recorded, log_status_changed, asset_archived,
// movement_recorded); kinds marked NEW below emerged in wave 1 and are punt
// candidates for kernel-registry freezing at the wave boundary (punt-promotion,
// fanout-wave-plan.md).
//
// The four domain log types (activity / observation / harvest / input) are NOT
// event kinds: they are the `kind` FIELD of a log_recorded payload, exactly as
// the 9h5.24 composed store modeled them. is-a-movement-a-log stays resolved
// centrally: movement_recorded has isLog:false (bound decision
// movement-as-log-taxonomy), so movements never inflate logCount/yield.

import {
  KindRegistry,
  type KindSpec,
} from "../../../../../../src/kernel/index.ts";

/** Kinds shared by the whole wave-1 log family (every feature consumes these). */
export const WAVE1_CORE_KINDS: readonly KindSpec[] = [
  { kind: "asset_created", family: "asset", isLog: false, description: "births an asset into the shared model (9h5.24 name)" },
  { kind: "log_recorded", family: "log", isLog: true, statusGate: "require-confirmed", description: "a domain log; payload.kind names the bundle (activity/observation/harvest/input)" },
  { kind: "log_status_changed", family: "status", isLog: false, description: "reassigns the lifecycle status of a log or movement (9h5.24 name)" },
  { kind: "asset_archived", family: "lifecycle", isLog: false, description: "flips assetActive; leaves history intact (9h5.24 name)" },
  // NEW in wave 1 (punt w1-shared-1): the flow DSL restates a log's effective
  // time as a first-class step (set_effective_time), so the restatement is an
  // EVENT, folded latest-wins — not a mutation of the recorded log.
  { kind: "log_time_restated", family: "log-time", isLog: false, description: "NEW w1: latest-wins restatement of a log's effective time" },
  // NEW in wave 1 (punt w1-shared-2): core-log deletion cascade surfaced by the
  // observation contract (EntityHooks::logDelete / quantityDelete) but generic
  // to the whole log family, so it lives in the shared taxonomy.
  { kind: "log_deleted", family: "lifecycle", isLog: false, description: "NEW w1: deletion of a log; its quantities cascade via quantity_deleted" },
  { kind: "quantity_deleted", family: "lifecycle", isLog: false, description: "NEW w1: deletion of one quantity; referencing logs gain a removal revision" },
];

/**
 * The frozen registry for a wave-1 store. A feature passes its own declared
 * extension (harvest's movement/plan/birth/revision kinds, observation's
 * selection kinds); registration happens BEFORE freeze, per the kernel rule.
 */
export function makeWave1Registry(extra: readonly KindSpec[] = []): KindRegistry {
  return new KindRegistry().extend(WAVE1_CORE_KINDS).extend(extra).freeze();
}
