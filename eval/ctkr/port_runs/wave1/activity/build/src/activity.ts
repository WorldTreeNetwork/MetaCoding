// w1a — activity log port, on the shared wave-1 log-family store.
//
// Activity is the identity element of the log family (scope.md: "functionally
// empty"); the port therefore adds NO new event kinds — every semantic is the
// shared log spine exercised through payload.kind === "activity".
//
// Contract: eval/ctkr/port_runs/wave1/activity/adapter_contract.md

import {
  Wave1LogStore,
  type Handle,
  type QuantityInput,
  type LogView,
} from "../../../shared-store/src/store.ts";
import { compareHlc } from "../../../../../../../src/kernel/index.ts";

export type AssetHandle = Handle;
export type ActivityLogHandle = Handle;
export type ActivityStatus = "pending" | "done";

export interface ActivityLogView {
  logId: ActivityLogHandle;
  name: string;
  status: string;
  occurredAt: number;
  assetIds: readonly AssetHandle[];
  notes?: string;
  quantities: LogView["quantities"];
}

export interface ActivityLogAdapter {
  recordActivity(input: {
    name: string;
    occurredAt: number;
    status: ActivityStatus;
    assetHandles: readonly AssetHandle[];
    notes?: string;
  }): ActivityLogHandle;
  /** newest occurredAt first, HLC as the deterministic tie-break (contract). */
  listActivityLogsForAsset(
    asset: AssetHandle,
    asOf: number,
    options?: { status?: ActivityStatus; limit?: number },
  ): readonly ActivityLogView[];
  getFirstActivityLogForAsset(
    asset: AssetHandle,
    asOf: number,
    status?: ActivityStatus,
  ): ActivityLogView | null;
}

function toView(v: LogView): ActivityLogView {
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

export function makeActivityAdapter(store: Wave1LogStore = new Wave1LogStore()) {
  const adapter: ActivityLogAdapter & { store: Wave1LogStore } = {
    store,

    recordActivity(input) {
      // one atomic event linked to all supplied assets; isLog:true by kind spec.
      return store.recordLog({
        kind: "activity",
        name: input.name,
        status: input.status,
        assetIds: input.assetHandles,
        quantities: [] as QuantityInput[],
        effectiveTime: input.occurredAt,
        extras: input.notes === undefined ? undefined : { notes: input.notes },
      });
    },

    listActivityLogsForAsset(asset, asOf, options = {}) {
      // shared store lists ascending; the activity contract orders NEWEST first
      // with the HLC as tie-break, and limit truncates that order.
      const asc = store.logsForAsset(asset, {
        kind: "activity",
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

    getFirstActivityLogForAsset(asset, asOf, status) {
      const list = adapter.listActivityLogsForAsset(asset, asOf, { status });
      return list.length > 0 ? list[0]! : null;
    },
  };
  return adapter;
}
