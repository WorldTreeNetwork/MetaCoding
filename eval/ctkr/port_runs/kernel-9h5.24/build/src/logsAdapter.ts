// The logs+quantities feature adapter (OracleAdapter). A thin projection view
// over the SharedStore — identical surface to the 9h5.16 build; the store behind
// it now runs on the shared kernel.

import type { OracleAdapter, QuantitySpec, Handle } from "./types.ts";
import { SharedStore } from "./store.ts";

export function makeLogsAdapter(store: SharedStore): OracleAdapter {
  return {
    createAsset(entity: string, name: string, descriptor?: string): Handle {
      return store.createAsset({ entity, name, descriptor });
    },

    recordLog(
      kind: string,
      name: string,
      status: string,
      assetHandles: Handle[],
      quantities: QuantitySpec[],
    ): Handle {
      return store.recordLog(kind, name, status, assetHandles, quantities);
    },

    setLogStatus(logHandle: Handle, status: string): void {
      store.setStatus(logHandle, status);
    },

    assignToGroup(assetHandle: Handle, groupHandle: Handle): void {
      store.assignToGroup(assetHandle, groupHandle);
    },

    archiveAsset(assetHandle: Handle): void {
      store.archiveAsset(assetHandle);
    },

    assetYieldTotal(assetHandle: Handle, measure: string, unit: string): number {
      return store.assetYieldTotal(assetHandle, measure, unit);
    },

    logStatus(logHandle: Handle): string {
      return store.logStatus(logHandle);
    },

    logCount(assetHandle: Handle, kind: string): number {
      return store.logCount(assetHandle, kind);
    },

    assetActive(assetHandle: Handle): boolean {
      return store.assetActive(assetHandle);
    },

    groupMember(assetHandle: Handle, groupHandle: Handle): boolean {
      return store.groupMember(assetHandle, groupHandle);
    },

    quantityRecorded(logHandle: Handle, measure: string, unit: string): number {
      return store.quantityRecorded(logHandle, measure, unit);
    },
  };
}
