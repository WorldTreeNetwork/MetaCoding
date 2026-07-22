// w1d — input log port, on the shared wave-1 log-family store.
//
// Contract: wave1/input/adapter_contract.md — one domain event
// (recordMaterialInput) and one filtered materialized read (listInputLogs with
// the ∃-quantity material-type membership predicate: a log matches when AT
// LEAST one of its quantities has the requested material type, and matches
// ONCE, however many quantities match — the IN-subquery shape of
// LogQuantityMaterialType). No new event kinds: material metadata rides the
// shared quantity record (quantityType / materialTypes), so input parallelizes
// on the shared taxonomy alone.

import {
  Wave1LogStore,
  type Handle,
  type QuantityInput,
  type QuantityRecord,
} from "../../../shared-store/src/store.ts";
import type { LifecycleStatus } from "../../../../../../../src/kernel/index.ts";

export type InputLogHandle = Handle;
export type MaterialTypeHandle = string; // taxonomy term name (auto_create: a name IS the term)
export type LogStatus = LifecycleStatus;

export interface MaterialQuantity extends QuantityInput {
  /** material_type taxonomy terms; multi-valued (quantity/material shape). */
  materialTypes?: readonly MaterialTypeHandle[];
}

export interface InputLogView {
  log: InputLogHandle;
  status: LogStatus;
  occurredAt: number;
  quantities: readonly QuantityRecord[];
  lotNumber?: string;
  method?: string;
  /** inert metadata — never participates in effective-time ordering (scope). */
  purchaseDate?: number;
  source?: string;
}

export function makeInputLogAdapter(store: Wave1LogStore = new Wave1LogStore()) {
  const adapter = {
    store,

    recordMaterialInput(
      occurredAt: number,
      materialQuantities: ReadonlyArray<MaterialQuantity>,
      initialStatus: LogStatus,
      extras: { lotNumber?: string; method?: string; purchaseDate?: number; source?: string } = {},
    ): InputLogHandle {
      if (materialQuantities.length === 0) {
        throw new Error(
          "recordMaterialInput requires a non-empty set of material-backed quantities",
        );
      }
      return store.recordLog({
        kind: "input",
        name: "",
        status: initialStatus,
        assetIds: [],
        // default quantity type is `material` — a default, not a restriction
        // (the source's own test attaches a `standard` quantity to an input log).
        quantities: materialQuantities.map((q) => ({
          ...q,
          quantityType: q.quantityType ?? "material",
        })),
        effectiveTime: occurredAt,
        extras,
      });
    },

    /** Record an input log against assets (the flow-pack write path). */
    recordInputAgainst(
      occurredAt: number,
      assetIds: readonly Handle[],
      quantities: ReadonlyArray<MaterialQuantity>,
      initialStatus: LogStatus,
    ): InputLogHandle {
      return store.recordLog({
        kind: "input",
        name: "",
        status: initialStatus,
        assetIds,
        quantities: quantities.map((q) => ({ ...q, quantityType: q.quantityType ?? "material" })),
        effectiveTime: occurredAt,
      });
    },

    listInputLogs(
      filter: { materialType?: MaterialTypeHandle },
      asOf: number,
    ): ReadonlyArray<InputLogView> {
      const views = store
        .allLogs({ kind: "input" })
        .filter((v) => v.effectiveTime <= asOf)
        .filter((v) =>
          filter.materialType === undefined
            ? true
            : // ∃-quantity membership: at least one quantity carries the term;
              // the log matches once, not once per matching quantity.
              v.quantities.some((q) =>
                (q.materialTypes ?? []).includes(filter.materialType!),
              ),
        );
      return views.map((v) => ({
        log: v.logId,
        status: v.status,
        occurredAt: v.effectiveTime,
        quantities: v.quantities,
        lotNumber: v.extras?.lotNumber,
        method: v.extras?.method,
        purchaseDate: v.extras?.purchaseDate,
        source: v.extras?.source,
      }));
    },
  };
  return adapter;
}
