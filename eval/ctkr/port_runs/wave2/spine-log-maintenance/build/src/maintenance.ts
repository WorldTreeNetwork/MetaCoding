// w2/spine-log-maintenance — maintenance log port, on the ONE shared wave-1
// log-family store (imported, never re-vendored).
//
// SPINE-TIER VERIFICATION (source: farm-src/modules/log/maintenance/):
//   - Maintenance.php: `class Maintenance extends FarmLogType {}` — an EMPTY
//     subclass, id "maintenance", label "Maintenance". No baseFieldDefinitions,
//     no bundleFieldDefinitions, no new quantity types.
//   - log.type.maintenance.yml: workflow "farm_log_workflow" — the SAME workflow
//     activity/harvest/observation use (states: done / pending / abandoned).
//   Therefore maintenance is the log-family identity element, exactly like
//   activity (scope.md "functionally empty"), differing ONLY by payload.kind ===
//   "maintenance". It adds NO new event kinds; every semantic is the shared spine.
//   Partition claim ("label-only new bundle (log_type) — no new fields/values/
//   measures") is CONFIRMED against source. No big-punt.
//
// "abandoned" is NOT a maintenance novelty: it is a state of the shared
// farm_log_workflow, already admissible via the kernel's open LifecycleStatus
// union and handled by passesGate (abandoned !== "done": inert to
// require-confirmed official numerics, admitted by the pending-only partners) —
// wave-1 decision w1a-5 already bound those semantics for the whole family. This
// port inherits them unchanged through the shared store.

import {
  Wave1LogStore,
  type Handle,
  type QuantityInput,
  type LogView,
} from "../../../../wave1/shared-store/src/store.ts";
import { compareHlc } from "../../../../../../../src/kernel/index.ts";

export type AssetHandle = Handle;
export type MaintenanceLogHandle = Handle;
/** The farm_log_workflow states, verbatim from source. */
export type MaintenanceStatus = "pending" | "done" | "abandoned";

export interface MaintenanceLogView {
  logId: MaintenanceLogHandle;
  name: string;
  status: string;
  occurredAt: number;
  assetIds: readonly AssetHandle[];
  notes?: string;
  quantities: LogView["quantities"];
}

export interface MaintenanceLogAdapter {
  /** Record a maintenance log (kind="maintenance") linked to equipment assets.
   *  quantities are accepted through the shared spine even though the source
   *  bundle declares none — the store carries them generically, and declaring
   *  them here would be the one forbidden hand-rolled fold, so they are simply
   *  passed through unmodified. */
  recordMaintenance(input: {
    name: string;
    occurredAt: number;
    status: MaintenanceStatus;
    assetHandles: readonly AssetHandle[];
    notes?: string;
    quantities?: readonly QuantityInput[];
  }): MaintenanceLogHandle;
  /** newest occurredAt first, HLC as the deterministic tie-break. */
  listMaintenanceLogsForAsset(
    asset: AssetHandle,
    asOf: number,
    options?: { status?: MaintenanceStatus; limit?: number },
  ): readonly MaintenanceLogView[];
  getFirstMaintenanceLogForAsset(
    asset: AssetHandle,
    asOf: number,
    status?: MaintenanceStatus,
  ): MaintenanceLogView | null;
}

function toView(v: LogView): MaintenanceLogView {
  return {
    logId: v.logId,
    name: v.name,
    status: v.status,
    occurredAt: v.effectiveTime,
    assetIds: v.assetIds,
    notes: v.extras?.notes,
    quantities: v.quantities,
  };
}

export function makeMaintenanceAdapter(store: Wave1LogStore = new Wave1LogStore()) {
  const adapter: MaintenanceLogAdapter & { store: Wave1LogStore } = {
    store,

    recordMaintenance(input) {
      return store.recordLog({
        kind: "maintenance",
        name: input.name,
        status: input.status,
        assetIds: input.assetHandles,
        quantities: (input.quantities ?? []) as QuantityInput[],
        effectiveTime: input.occurredAt,
        extras: input.notes === undefined ? undefined : { notes: input.notes },
      });
    },

    listMaintenanceLogsForAsset(asset, asOf, options = {}) {
      // shared store lists ascending; this surface orders NEWEST first with the
      // HLC as tie-break (mirrors the activity contract, w1a-4), limit truncates.
      const asc = store.logsForAsset(asset, {
        kind: "maintenance",
        status: options.status,
        asOf,
      });
      const desc = [...asc].sort((a, b) =>
        a.effectiveTime !== b.effectiveTime
          ? b.effectiveTime - a.effectiveTime
          : compareHlc(b.hlc, a.hlc),
      );
      const limited =
        options.limit !== undefined ? desc.slice(0, options.limit) : desc;
      return limited.map(toView);
    },

    getFirstMaintenanceLogForAsset(asset, asOf, status) {
      const list = adapter.listMaintenanceLogsForAsset(asset, asOf, { status });
      return list.length > 0 ? list[0]! : null;
    },
  };
  return adapter;
}
