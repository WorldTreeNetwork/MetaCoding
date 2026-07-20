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
 *   4. Status filtering is routed through the kernel status contract and the gate
 *      is READ FROM IT: `gateFor("currentInventory")`. The row exists as of
 *      kernel v1.3, where observation set it (a pending adjustment does not move
 *      stock). A feature-local constant here was the exact re-litigation
 *      `status.ts` exists to forbid.
 *   5. The projection is KIND-GUARDED: it folds only events of the registered
 *      adjustment kind, so a composed store carrying other features' events
 *      cannot leak a foreign payload into this balance.
 *   6. The adjustment behaviour set is CLOSED: an unrecognized sub-kind throws
 *      rather than falling through to a silent decrement.
 *
 * The kernel is IMPORTED FROM ITS ONE SOURCE (../../src/kernel), never vendored.
 * This build previously carried its own copy, which had already drifted — it
 * still held the pre-v1.3 blanket status contract that observation falsified. A
 * kernel that is copied per build cannot prevent anything at wave scale.
 */

import {
  compareHlc,
  EventLog,
  HlcClock,
  IdMinter,
  KindRegistry,
  gateFor,
  passesGate,
  type EntityId,
  type Hlc,
  type KernelEvent,
  type KindSpec,
  type LifecycleStatus,
  type StatusGate,
} from "../../../../../../../src/kernel/index.ts";

/** The kernel kind under which every inventory adjustment is logged. */
export const INVENTORY_ADJUSTMENT_KIND = "inventory_adjustment";

/**
 * Inventory's status gate, taken FROM THE KERNEL CONTRACT — not named here.
 *
 * This was a feature-local constant, which is the exact re-litigation
 * `status.ts` exists to forbid: a local constant cannot be re-decided centrally,
 * and kernel v1.3 proved that matters — observation showed the pending gate is
 * PER-PROJECTION (a pending adjustment does not move stock but IS counted; a
 * pending birth is fully effective), so a build holding its own copy of the
 * answer would have silently kept the falsified one.
 */
const INVENTORY_GATE: StatusGate = gateFor("currentInventory");

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

/**
 * The CLOSED set of adjustment behaviours. The fold used to end in a bare
 * `else running -= value`, so any unrecognized sub-kind silently DECREMENTED —
 * an unregistered taxonomy hiding inside a registered kind, and precisely the
 * ad-hoc-kind failure the kernel's KindRegistry exists to make impossible one
 * level up. A new behaviour must be added here deliberately.
 */
export const ADJUSTMENT_KINDS: readonly AdjustmentKind[] = [
  "reset",
  "increment",
  "decrement",
] as const;

export function isAdjustmentKind(k: string): k is AdjustmentKind {
  return (ADJUSTMENT_KINDS as readonly string[]).includes(k);
}

/** Thrown when an adjustment names a behaviour outside the closed set. */
export class UnknownAdjustmentKind extends Error {
  constructor(kind: string) {
    super(
      `unknown adjustment behaviour ${JSON.stringify(kind)}; ` +
      `the closed set is ${ADJUSTMENT_KINDS.join(", ")}. A silent fallback here ` +
      `would apply an arbitrary sign to a real quantity.`,
    );
    this.name = "UnknownAdjustmentKind";
  }
}

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
  /**
   * A SHARED kind registry + event log, for a composed store where several
   * features append to one log. Supplying them is what makes the projection's
   * kind-guard load-bearing rather than theoretical: with a private log this
   * feature is the only writer, so nothing foreign could ever be folded and the
   * guard is untested by construction.
   */
  registry?: KindRegistry;
  log?: EventLog<KernelEvent<string, unknown>>;
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
    // No catch-all: an unrecognized behaviour is an error, never a decrement.
    if (kind === "reset") running = value;
    else if (kind === "increment") running += value;
    else if (kind === "decrement") running -= value;
    else throw new UnknownAdjustmentKind(String(kind));
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
  // In a composed store the registry and log are SHARED — this feature registers
  // its kind into the common taxonomy and appends to the common log.
  const registry =
    opts.registry ?? new KindRegistry().register(INVENTORY_ADJUSTMENT_SPEC).freeze();
  const log = (opts.log ??
    new EventLog<InventoryEvent>(registry)) as EventLog<InventoryEvent>;

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
            // Kind-guard FIRST: in a composed store the log carries every
            // feature's events, and an unguarded projection would fold a
            // foreign kind whose payload happens to have the right shape.
            e.kind === INVENTORY_ADJUSTMENT_KIND &&
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
