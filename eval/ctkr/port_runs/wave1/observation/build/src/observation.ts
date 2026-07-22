// w1b — observation log port, on the shared wave-1 log-family store.
//
// Observation is the control group of the log family (scope.md: semantics 100%
// inherited); the feature's OWN surface is the add-log selection workflow, the
// raw-asset-list preservation rule, revision-aware quantities, and the two
// deletion cascades. Contract: wave1/observation/adapter_contract.md.
//
// Feature-declared kinds (extension of the shared taxonomy, punt w1b-3):
//   selection_started   — a user-scoped pending add-observation selection
//   selection_confirmed — consumes the selection exactly once → asset query
// Deletion kinds (log_deleted / quantity_deleted) are SHARED taxonomy: the
// cascades come from core-log hooks, not from this module.

import {
  Wave1LogStore,
  type Handle,
  type QuantityInput,
  type QuantityRecord,
  type LogRecordedPayload,
} from "../../../shared-store/src/store.ts";
import type {
  KindSpec,
  LifecycleStatus,
} from "../../../../../../../src/kernel/index.ts";

export const OBSERVATION_KINDS: readonly KindSpec[] = [
  { kind: "selection_started", family: "workflow", isLog: false, description: "w1b: pending add-observation asset selection (actor-scoped)" },
  { kind: "selection_confirmed", family: "workflow", isLog: false, description: "w1b: consumes a pending selection exactly once into an asset query" },
];

export type ActorHandle = Handle;
export type AssetHandle = Handle;
export type ObservationHandle = Handle;
export type QuantityHandle = Handle;
export type QuantityRevisionHandle = Handle;
export type PendingObservationSelectionHandle = Handle;
export type ObservationAssetQueryHandle = Handle;
export type ObservationStatus = LifecycleStatus;

interface SelectionStartedPayload {
  selectionId: Handle;
  actor: ActorHandle;
  assetIds: readonly AssetHandle[];
}
interface SelectionConfirmedPayload {
  selectionId: Handle;
  queryId: Handle;
  actor: ActorHandle;
  assetIds: readonly AssetHandle[];
}

export interface ObservationSnapshot {
  observation: ObservationHandle;
  status: ObservationStatus;
  occurredAt: number;
  /** exactly the raw submitted asset list (contract: never replaced by a
   *  loaded viewable-only subset). */
  assetIds: readonly AssetHandle[];
  quantityRevisions: readonly QuantityRevisionHandle[];
  notes?: string;
}

export interface ObservationRevisionSnapshot {
  observation: ObservationHandle;
  /** revision message; quantity removals carry the deleted quantity id. */
  message: string;
  quantityRevisions: readonly QuantityRevisionHandle[];
}

export function makeObservationAdapter(
  store: Wave1LogStore = new Wave1LogStore({ extraKinds: OBSERVATION_KINDS }),
) {
  // revision-aware quantity handles minted by this surface; recordObservation
  // resolves them into the ONE log_recorded write path (single write path is
  // what keeps the bridge and the contract adapter the same port).
  const pendingQuantities = new Map<QuantityRevisionHandle, QuantityInput>();

  function specsFor(handles: readonly QuantityRevisionHandle[]): QuantityInput[] {
    return handles.map((h) => {
      const spec = pendingQuantities.get(h);
      if (!spec) throw new Error(`unknown quantity revision handle ${String(h)}`);
      return spec;
    });
  }

  function observationView(observation: ObservationHandle) {
    const v = store.logView(observation);
    return v && v.kind === "observation" ? v : undefined;
  }

  const adapter = {
    store,

    /** Mint a revision-aware quantity reference to record on an observation. */
    mintQuantityRevision(spec: QuantityInput): QuantityRevisionHandle {
      const h = store.mint("qrev");
      pendingQuantities.set(h, spec);
      return h;
    },

    startObservationAddSelection(
      actor: ActorHandle,
      selectedAssetIds: AssetHandle[],
    ): PendingObservationSelectionHandle {
      const selectionId = store.mint("sel");
      store.emit<SelectionStartedPayload>("selection_started", {
        selectionId,
        actor,
        assetIds: [...selectedAssetIds],
      });
      return selectionId;
    },

    confirmObservationAddSelection(
      actor: ActorHandle,
      selection: PendingObservationSelectionHandle,
    ): ObservationAssetQueryHandle {
      const started = store
        .eventsOf<SelectionStartedPayload>("selection_started")
        .find((e) => e.payload.selectionId === selection);
      if (!started) throw new Error(`unknown selection ${String(selection)}`);
      const already = store
        .eventsOf<SelectionConfirmedPayload>("selection_confirmed")
        .some((e) => e.payload.selectionId === selection);
      if (already) {
        // consumed exactly once — a second confirmation has no selection left.
        throw new Error(`selection ${String(selection)} was already consumed`);
      }
      // PUNT w1b-1: the wave-1 store has no access/disclosure model, so "assets
      // visible to the actor at confirmation" filters nothing — every selected
      // asset is visible. The silent-omission semantic is preserved in shape
      // (the query is built from the visible subset), inert in effect.
      const queryId = store.mint("aq");
      store.emit<SelectionConfirmedPayload>("selection_confirmed", {
        selectionId: selection,
        queryId,
        actor,
        assetIds: started.payload.assetIds,
      });
      return queryId;
    },

    recordObservation(
      assetIds: AssetHandle[],
      quantityRevisions: QuantityRevisionHandle[],
      status: ObservationStatus,
      occurredAt: number,
      notes?: string,
    ): ObservationHandle {
      // asset field is EXACTLY the supplied raw list (contract).
      const specs = specsFor(quantityRevisions);
      return store.recordLog({
        kind: "observation",
        name: notes ?? "",
        status,
        assetIds,
        quantities: specs,
        effectiveTime: occurredAt,
        extras: notes === undefined ? undefined : { notes },
      });
    },

    cloneObservation(source: ObservationHandle, occurredAt: number): ObservationHandle {
      const v = observationView(source);
      if (!v) throw new Error(`unknown observation ${String(source)}`);
      // distinct cloned quantity per source quantity revision: recordLog mints
      // NEW quantity ids, so the clone never references source quantities.
      return store.recordLog({
        kind: "observation",
        name: v.name,
        status: v.status,
        assetIds: v.assetIds,
        quantities: v.quantities.map(({ quantityId: _drop, ...spec }) => spec),
        effectiveTime: occurredAt,
        extras: v.extras,
      });
    },

    recordQuantityDeletion(quantity: QuantityHandle, _occurredAt: number): Handle {
      store.deleteQuantity(quantity);
      return quantity;
    },

    recordObservationDeletion(observation: ObservationHandle, _occurredAt: number): Handle {
      const v = observationView(observation);
      if (v) {
        // cascade: every quantity currently referenced is deleted with the log.
        for (const q of v.quantities) store.deleteQuantity(q.quantityId);
      }
      store.deleteLog(observation);
      return observation;
    },

    getObservationAssetPrepopulation(
      operation: "create" | "edit",
      rawAssetQueryIds: AssetHandle[],
      _asOf: number,
    ): AssetHandle[] {
      // edit forms never prepopulate from the query (contract).
      return operation === "create" ? [...rawAssetQueryIds] : [];
    },

    getConfirmedObservationAssetQuery(
      assetQuery: ObservationAssetQueryHandle,
      asOf: number,
    ): AssetHandle[] {
      const confirmed = store
        .eventsOf<SelectionConfirmedPayload>("selection_confirmed")
        .find((e) => e.payload.queryId === assetQuery && e.hlc.physical <= asOf);
      return confirmed ? [...confirmed.payload.assetIds] : [];
    },

    getObservation(observation: ObservationHandle, asOf: number): ObservationSnapshot | null {
      const v = observationView(observation);
      if (!v || v.effectiveTime > asOf) return null;
      return {
        observation: v.logId,
        status: v.status,
        occurredAt: v.effectiveTime,
        assetIds: v.assetIds,
        quantityRevisions: v.quantities.map((q) => q.quantityId),
        notes: v.extras?.notes,
      };
    },

    listObservationRevisions(
      observation: ObservationHandle,
      asOf: number,
    ): ObservationRevisionSnapshot[] {
      // revision history known at asOf, derived from the event log: the initial
      // recording, then one revision per quantity removal touching this
      // observation, carrying the deleted-quantity id in its message (contract).
      const rec = store
        .eventsOf<LogRecordedPayload>("log_recorded")
        .find((e) => e.payload.logId === observation);
      if (!rec) return [];
      const revisions: ObservationRevisionSnapshot[] = [];
      let current: QuantityRecord[] = [...rec.payload.quantities];
      if (rec.hlc.physical <= asOf) {
        revisions.push({
          observation,
          message: "created",
          quantityRevisions: current.map((q) => q.quantityId),
        });
      }
      for (const e of store.eventsOf<{ quantityId: Handle }>("quantity_deleted")) {
        if (e.hlc.physical > asOf) continue;
        const affected = current.find((q) => q.quantityId === e.payload.quantityId);
        if (!affected) continue;
        current = current.filter((q) => q.quantityId !== e.payload.quantityId);
        revisions.push({
          observation,
          message: `Deleted quantity ${String(e.payload.quantityId)}`,
          quantityRevisions: current.map((q) => q.quantityId),
        });
      }
      return revisions;
    },

    listObservationsForAsset(asset: AssetHandle, asOf: number): ObservationHandle[] {
      // ascending (effectiveTime, HLC) — the materialized log-query ordering
      // (LogQueryFactory sort with the kernel HLC replacing the id tie-break).
      return store
        .logsForAsset(asset, { kind: "observation", asOf })
        .map((v) => v.logId);
    },

    getFirstObservationForAsset(asset: AssetHandle, asOf: number): ObservationHandle | null {
      const list = adapter.listObservationsForAsset(asset, asOf);
      return list.length > 0 ? list[0]! : null;
    },

    getDefaultQuantityType(_asOf: number): Handle | null {
      // PUNT w1b-2: no quantity-configuration event source exists in the wave-1
      // surface (no mutator can set a default), so the materialized
      // configuration is empty and the contract's null branch is the answer.
      return null;
    },
  };
  return adapter;
}
