// wave-2 spine-misc — quantity/standard port, on the shared wave-1 log-family
// store (the ONE event-sourced store on the frozen kernel v1.3; consumed via
// import, never vendored).
//
// SPINE CLAIM (confirmed by reading the source): the `standard` quantity type
// is genuinely label-only. Its class body is empty —
//
//   #[QuantityType(id: 'standard', label: 'Standard')]
//   class Standard extends FarmQuantityType {}
//
// — and FarmQuantityType / QuantityTypeBase::buildFieldDefinitions() returns
// [] (the base adds no fields). Every field a standard quantity carries
// (measure / value / units / label) is a BASE field of the core `quantity`
// entity (modules/core/quantity/src/Entity/Quantity.php baseFieldDefinitions):
//   - measure  : list_string over QuantityHelper::quantityMeasureAllowedValues
//   - value    : fraction
//   - units    : entity_reference → taxonomy_term(unit)
//   - label    : string (max 255)
// These are exactly the fields the shared store's QuantityInput / QuantityRecord
// already fold (measure / value / unit / label + the bundle tag quantityType).
//
// So `standard` adds NO new event kinds, NO computed field, NO constraint, NO
// workflow — it is the identity element of the quantity family, the quantity
// analogue of w1a activity in the log family. This port is therefore a thin
// naming surface over the shared quantity spine: it stamps quantityType:
// "standard" and reads back the spine's own folds. Contrast the peers that are
// NOT spine and were tiered `identity`: quantity/material adds a material_type
// bundle field, quantity/test adds a test_method bundle field.

import {
  Wave1LogStore,
  type Handle,
  type QuantityInput,
  type QuantityRecord,
} from "../../../../wave1/shared-store/src/store.ts";
import type { LifecycleStatus } from "../../../../../../../src/kernel/index.ts";

export type AssetHandle = Handle;
export type StandardLogHandle = Handle;
export type LogStatus = LifecycleStatus;

/**
 * A standard quantity: the four base quantity fields, unadorned. This is the
 * whole `standard` bundle — no field beyond the spine. `label` is the base
 * `label` string field (optional; source default ''); the bundle tag is fixed
 * to "standard" by construction, never taken from the caller.
 */
export interface StandardQuantity {
  measure: string;
  value: number;
  unit: string;
  label?: string;
}

/** Build a shared-store QuantityInput tagged as the `standard` bundle. */
export function standardQuantity(q: StandardQuantity): QuantityInput {
  return {
    measure: q.measure,
    value: q.value,
    unit: q.unit,
    ...(q.label === undefined ? {} : { label: q.label }),
    quantityType: "standard",
  };
}

export interface StandardQuantityView {
  quantityId: Handle;
  measure: string;
  value: number;
  unit: string;
  label?: string;
}

function toStandardView(q: QuantityRecord): StandardQuantityView {
  return {
    quantityId: q.quantityId,
    measure: q.measure,
    value: q.value,
    unit: q.unit,
    ...(q.label === undefined ? {} : { label: q.label }),
  };
}

/**
 * Thin `standard`-bundle surface over the shared quantity spine. Every read is
 * a fold the shared store already owns; this adapter only names the bundle and
 * projects the standard quantities back out. It deliberately implements no
 * numeric fold of its own — yield/count semantics (incl. the one chosen
 * confirmed-only status-gate divergence) live once, in the shared store.
 */
export function makeStandardQuantityAdapter(store: Wave1LogStore = new Wave1LogStore()) {
  const adapter = {
    store,

    /** Attach standard quantities to a domain log (default bundle: any). */
    recordWithStandardQuantities(input: {
      kind: string;
      name?: string;
      status: LogStatus;
      assetHandles: readonly AssetHandle[];
      quantities: readonly StandardQuantity[];
      occurredAt?: number;
    }): StandardLogHandle {
      return store.recordLog({
        kind: input.kind,
        name: input.name ?? "",
        status: input.status,
        assetIds: input.assetHandles,
        quantities: input.quantities.map(standardQuantity),
        effectiveTime: input.occurredAt,
      });
    },

    /** The standard quantities recorded on ONE log (bundle-filtered, live). */
    standardQuantitiesOn(log: StandardLogHandle): readonly StandardQuantityView[] {
      const v = store.logView(log);
      if (!v) return [];
      return v.quantities
        .filter((q) => q.quantityType === "standard")
        .map(toStandardView);
    },

    /**
     * Σ recorded value of a (measure, unit) pair on ONE log — the log's own
     * recorded standard quantities, never status-gated (delegates to the
     * shared store's quantityRecorded, which reports what the event says).
     */
    quantityRecordedOn(log: StandardLogHandle, measure: string, unit: string): number {
      return store.quantityRecorded(log, measure, unit);
    },
  };
  return adapter;
}
