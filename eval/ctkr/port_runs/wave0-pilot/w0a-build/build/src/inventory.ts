/**
 * Asset Inventory feature — an adjustment-based running balance, built ON the
 * shared kernel v1 as fixed substrate.
 *
 * The inventory value for an asset is a per-(measure, units) running balance
 * folded from an append-only stream of adjustment events:
 *   - `reset`     assigns the running value (an ordered assignment, not a delta),
 *   - `increment` adds a delta,
 *   - `decrement` subtracts a delta.
 *
 * `getInventory(asset, asOf)` is an as-of projection: it considers only
 * adjustments that are `done` (per the kernel status contract) and whose valid
 * time `occurredAt <= asOf`, partitions them by exact (measure, units) pair, and
 * replays each pair from its LATEST reset timestamp onward.
 *
 * KERNEL INTEGRATION (all four prevention gates are load-bearing here):
 *   1. The adjustment kind is REGISTERED in a KindRegistry that is frozen before
 *      use; every append flows through the kernel EventLog, which rejects any
 *      unregistered kind. There is no ad-hoc kind string at an append site.
 *   2. Every asset id and every event id is minted by the kernel IdMinter
 *      (replica-scoped). No bare ordinal ids.
 *   3. The domain orders adjustments by `occurredAt` (valid time, a payload
 *      field). Same-`occurredAt` ties are broken by the kernel HLC via
 *      `compareHlc` — never by entity id (ids.ts forbids ordering by id).
 *   4. Status filtering is routed through the kernel status contract:
 *      `passesGate(status, "require-confirmed")`. Inventory's gate is
 *      require-confirmed (pending adjustments are inert). STATUS_CONTRACT ships
 *      no `currentInventory` row yet — see PORT_DECISIONS.md; we gate against the
 *      "require-confirmed" StatusGate directly, the same gate `currentLocation`
 *      uses, until the kernel adds the row.
 */

import {
  compareHlc,
  EventLog,
  HlcClock,
  IdMinter,
  KindRegistry,
  passesGate,
  type EntityId,
  type Hlc,
  type KernelEvent,
  type KindSpec,
  type LifecycleStatus,
  type StatusGate,
} from "./kernel/index.ts";

/** The kernel kind under which every inventory adjustment is logged. */
export const INVENTORY_ADJUSTMENT_KIND = "inventory_adjustment";

/**
 * Inventory's status gate. STATUS_CONTRACT has no `currentInventory` projection
 * row (a required kernel addition, see PORT_DECISIONS.md §status), so we name the
 * gate locally and still route the actual filtering through the kernel's
 * `passesGate`. It is exactly the reading `currentLocation` already uses:
 * pending adjustments are proposed, not yet true, and stay inert.
 */
const INVENTORY_GATE: StatusGate = "require-confirmed";

/**
 * The KindSpec for inventory adjustments. `isLog: true` — an adjustment IS an
 * asset-log record (the source derives it from EntityHooks::logPresave), so it
 * participates in log folds. `statusGate` records the kind's own require-confirmed
 * lifecycle at the taxonomy level.
 */
export const INVENTORY_ADJUSTMENT_SPEC: KindSpec = {
  kind: INVENTORY_ADJUSTMENT_KIND,
  family: "asset-log",
  isLog: true,
  statusGate: INVENTORY_GATE,
  description:
    "One asset inventory adjustment: reset assigns, increment/decrement are ledger deltas.",
};

export type AdjustmentKind = "increment" | "decrement" | "reset";

/** A handle to an asset — an opaque kernel entity id (minted by IdMinter). */
export type AssetHandle = EntityId;
/** A handle to one appended adjustment event — an opaque kernel entity id. */
export type InventoryLogHandle = EntityId;

/** The caller-supplied fields of one adjustment. */
export interface InventoryAdjustmentInput {
  /** lifecycle status of the backing log, e.g. "done" | "pending". */
  logStatus: LifecycleStatus;
  /** valid time (effectiveTime) of the adjustment — the domain ordering key. */
  occurredAt: number;
  /** the measured dimension, e.g. a "mass" handle. Exact-matched. */
  measure: string;
  /** the units, e.g. a "kg" handle. Exact-matched (kg and lb never merge). */
  units: string;
  kind: AdjustmentKind;
  value: number;
}

/** The payload carried on each kernel event of the adjustment kind. */
export interface InventoryAdjustmentPayload extends InventoryAdjustmentInput {
  /** which asset this adjustment belongs to. */
  asset: AssetHandle;
}

/** One as-of inventory summary: one row per exact (measure, units) pair. */
export interface InventorySummary {
  measure: string;
  units: string;
  value: number;
}

type InventoryEvent = KernelEvent<
  typeof INVENTORY_ADJUSTMENT_KIND,
  InventoryAdjustmentPayload
>;

export interface AssetInventoryAdapter {
  /** Mint a fresh asset handle (a replica-scoped kernel id). */
  createAsset(): AssetHandle;
  /** Append ONE adjustment event to the kernel EventLog; returns its handle. */
  appendInventoryAdjustment(
    asset: AssetHandle,
    adjustment: InventoryAdjustmentInput,
  ): InventoryLogHandle;
  /** As-of projection: one summary per exact (measure, units) pair. */
  getInventory(asset: AssetHandle, asOf: number): InventorySummary[];
}

export interface AdapterOptions {
  /** replica identity for the id minter + HLC clock (default "R1"). */
  replicaId?: string;
  /** injectable wall clock for deterministic tests. */
  now?: () => number;
}

/**
 * The hand-rolled fold at the heart of inventory. This is NOT latest-wins: the
 * kernel provides `pickLatest`/`LwwRegister` (keyed on the HLC), but a
 * running-balance-with-reset is a stateful left fold over an ORDER, not a pick of
 * a single latest write. See PORT_DECISIONS.md §fold. We compute it here rather
 * than expressing it through a kernel primitive because the kernel ships none.
 *
 * `sorted` MUST already be the pair's eligible events (done, occurredAt <= asOf)
 * in ascending (occurredAt, HLC) order. We locate the latest reset timestamp,
 * discard everything strictly before it, then left-fold from 0 with reset as
 * assignment. Folding from 0 (rather than seeding with the reset's value and
 * skipping to strictly-after) is what makes the same-`occurredAt` case correct:
 * an increment that shares the reset's timestamp but sorts before it is applied
 * and then overwritten by the reset, exactly as the source sequences ties.
 */
function foldRunningBalance(sorted: readonly InventoryEvent[]): number {
  let latestResetTs: number | undefined;
  for (const e of sorted) {
    if (e.payload.kind === "reset") {
      // sorted ascending, so the last reset seen has the greatest occurredAt.
      latestResetTs = e.payload.occurredAt;
    }
  }

  let running = 0;
  for (const e of sorted) {
    // Reset boundary is timestamp-INCLUSIVE: keep events at-or-after the latest
    // reset timestamp (semantic n4), drop everything strictly before it.
    if (latestResetTs !== undefined && e.payload.occurredAt < latestResetTs) {
      continue;
    }
    const { kind, value } = e.payload;
    if (kind === "reset") running = value;
    else if (kind === "increment") running += value;
    else running -= value; // decrement
  }
  return running;
}

/** Ascending domain order: by valid time, ties broken by the kernel HLC. */
function byOccurredThenHlc(a: InventoryEvent, b: InventoryEvent): number {
  if (a.payload.occurredAt !== b.payload.occurredAt) {
    return a.payload.occurredAt - b.payload.occurredAt;
  }
  // Same occurredAt — break the tie with the kernel HLC, NOT the entity id.
  return compareHlc(a.hlc, b.hlc);
}

export function makeAssetInventoryAdapter(
  opts: AdapterOptions = {},
): AssetInventoryAdapter {
  const replicaId = opts.replicaId ?? "R1";

  // Gate 1: closed kind taxonomy. Register the adjustment kind, then FREEZE so
  // no ad-hoc kind can be introduced later, and route appends through EventLog.
  const registry = new KindRegistry().register(INVENTORY_ADJUSTMENT_SPEC).freeze();
  const log = new EventLog<InventoryEvent>(registry);

  // Gate 2: replica-scoped id minting. One minter for both assets and events.
  const minter = new IdMinter(replicaId);
  // Gate 3: the HLC clock is the sole tie-break source for equal occurredAt.
  const clock = new HlcClock(replicaId, opts.now);

  return {
    createAsset(): AssetHandle {
      return minter.mint("asset");
    },

    appendInventoryAdjustment(
      asset: AssetHandle,
      adjustment: InventoryAdjustmentInput,
    ): InventoryLogHandle {
      const id = minter.mint("invadj");
      const hlc: Hlc = clock.tick();
      const event: InventoryEvent = {
        id,
        hlc,
        kind: INVENTORY_ADJUSTMENT_KIND,
        payload: { asset, ...adjustment },
      };
      // EventLog rejects any kind not in the frozen taxonomy — gate 1 enforced.
      log.append(event);
      return id;
    },

    getInventory(asset: AssetHandle, asOf: number): InventorySummary[] {
      // Eligible = this asset's adjustments that are confirmed (gate 4, via the
      // kernel status contract) and not future-dated relative to asOf.
      const eligible = log
        .all()
        .filter(
          (e) =>
            e.payload.asset === asset &&
            passesGate(e.payload.logStatus, INVENTORY_GATE) &&
            e.payload.occurredAt <= asOf,
        );

      // Partition by EXACT (measure, units) pair — never summed or converted
      // (semantic n5). Preserve first-seen order for a stable result.
      const groups = new Map<string, InventoryEvent[]>();
      const order: string[] = [];
      for (const e of eligible) {
        const key = `${e.payload.measure} ${e.payload.units}`;
        let bucket = groups.get(key);
        if (!bucket) {
          bucket = [];
          groups.set(key, bucket);
          order.push(key);
        }
        bucket.push(e);
      }

      const summaries: InventorySummary[] = [];
      for (const key of order) {
        const bucket = groups.get(key)!;
        const sorted = [...bucket].sort(byOccurredThenHlc);
        const value = foldRunningBalance(sorted);
        const { measure, units } = sorted[0]!.payload;
        summaries.push({ measure, units, value });
      }
      return summaries;
    },
  };
}
