// The ONE shared wave-1 log-family store — event-sourced on the frozen kernel
// (src/kernel, v1.3, consumed via import, never vendored). All four wave-1
// features (activity / observation / harvest / input) append through this one
// store and read through its kernel-folded projections, which is why they
// serialize through one builder (the 27/27 one-mind lesson).
//
//   - ids: kernel IdMinter (replica-scoped, collision-free; no bare ordinals)
//   - ordering: kernel HLC only (no serial seq, no id-ordering)
//   - latest-wins: kernel pickLatest / compareHlc
//   - status gates: kernel STATUS_CONTRACT rows yieldTotal / pendingYieldTotal /
//     logCount / pendingLogCount / logStatus — the one chosen divergence
//     (confirmed-only official numerics + pending-only partners) is implemented
//     here, once, for the whole family.
//
// Deliberate readings taken from the observed boundary (observation/scope.md
// post-observation note) where the kernel binds nothing:
//   - yield folds are NOT as-of-gated (a future-dated done log counts now)
//   - yield folds sum ACROSS domain log kinds (observation + harvest merge)
//   - log listing order is ascending (effectiveTime, HLC) — the LogQueryFactory
//     sort with the id tie-break replaced by the kernel HLC (decision w0a-2)

import {
  HlcClock,
  IdMinter,
  EventLog,
  KindRegistry,
  pickLatest,
  compareHlc,
  gateFor,
  passesGate,
  type KernelEvent,
  type EntityId,
  type Hlc,
  type LifecycleStatus,
} from "../../../../../../src/kernel/index.ts";
import { makeWave1Registry } from "./kinds.ts";
import type { KindSpec } from "../../../../../../src/kernel/index.ts";

export type Handle = EntityId;

/** One measured quantity as recorded on a log (glossary QuantitySpec + wave-1 extras). */
export interface QuantityInput {
  measure: string;
  value: number;
  unit: string;
  label?: string;
  /** quantity bundle, e.g. "material" | "standard" (input feature). */
  quantityType?: string;
  /** material_type taxonomy terms (multi-valued, input feature). */
  materialTypes?: readonly string[];
}

export interface QuantityRecord extends QuantityInput {
  quantityId: Handle;
}

/** Feature-specific optional metadata carried verbatim on a log payload. */
export interface LogExtras {
  notes?: string;
  lotNumber?: string;
  method?: string;
  purchaseDate?: number; // inert metadata — NEVER an ordering key (input scope)
  source?: string;
  /** harvest: the exact recorded quantity payload incl. [null] (contract w1c). */
  quantityPayload?: readonly (QuantityInput | null)[];
}

export interface AssetCreatedPayload {
  assetId: Handle;
  entity: string;
  name: string;
  descriptor?: string;
  sex?: string;
}

export interface LogRecordedPayload {
  logId: Handle;
  /** the domain log bundle: activity | observation | harvest | input | ... */
  kind: string;
  name: string;
  status: LifecycleStatus;
  assetIds: readonly Handle[];
  quantities: readonly QuantityRecord[];
  /** valid-time of the log (epoch ms). Restatements supersede it latest-wins. */
  effectiveTime: number;
  extras?: LogExtras;
  /**
   * Equipment assets the log states as used — the cross-family `equipment`
   * base field farm_equipment adds to EVERY log (MetaCoding-1cv; owned by the
   * log spine, not the asset bundle). Additive and optional: events recorded
   * before the field existed fold as [].
   */
  equipmentIds?: readonly Handle[];
}

export interface LogStatusChangedPayload {
  targetId: Handle;
  status: LifecycleStatus;
}

export interface LogTimeRestatedPayload {
  targetId: Handle;
  effectiveTime: number;
}

export interface AssetArchivedPayload {
  assetId: Handle;
}

export interface LogDeletedPayload {
  logId: Handle;
}

export interface QuantityDeletedPayload {
  quantityId: Handle;
}

export type StoreEvent = KernelEvent<string, unknown>;

/** A materialized log view (deleted quantities removed, latest status/time). */
export interface LogView {
  logId: Handle;
  kind: string;
  name: string;
  status: LifecycleStatus;
  assetIds: readonly Handle[];
  quantities: readonly QuantityRecord[];
  effectiveTime: number;
  extras?: LogExtras;
  /** Equipment stated as used; [] for logs recorded before the field existed. */
  equipmentIds: readonly Handle[];
  hlc: Hlc;
}

export interface StoreOptions {
  replicaId?: string;
  /** a feature's declared kind extension, registered before freeze. */
  extraKinds?: readonly KindSpec[];
}

export class Wave1LogStore {
  readonly registry: KindRegistry;
  private readonly log: EventLog<StoreEvent>;
  private readonly clock: HlcClock;
  private readonly ids: IdMinter;

  constructor(opts: StoreOptions = {}) {
    const replicaId = opts.replicaId ?? "R1";
    this.clock = new HlcClock(replicaId);
    this.ids = new IdMinter(replicaId);
    this.registry = makeWave1Registry(opts.extraKinds ?? []);
    this.log = new EventLog<StoreEvent>(this.registry);
  }

  // ---- primitives ---------------------------------------------------------
  mint(prefix: string): Handle {
    return this.ids.mint(prefix);
  }

  /** Append any registered event kind (feature kinds included). */
  emit<P>(kind: string, payload: P): KernelEvent<string, P> {
    const e: KernelEvent<string, P> = {
      id: this.ids.mint("evt"),
      hlc: this.clock.tick(),
      kind,
      payload,
    };
    this.log.append(e);
    return e;
  }

  events(): readonly StoreEvent[] {
    return this.log.all();
  }

  eventsOf<P>(kind: string): KernelEvent<string, P>[] {
    return this.events().filter((e) => e.kind === kind) as KernelEvent<string, P>[];
  }

  now(): number {
    return Date.now();
  }

  // ---- shared mutations ----------------------------------------------------
  createAsset(input: { entity: string; name: string; descriptor?: string; sex?: string }): Handle {
    const assetId = this.ids.mint("asset");
    this.emit<AssetCreatedPayload>("asset_created", { assetId, ...input });
    return assetId;
  }

  recordLog(input: {
    kind: string;
    name: string;
    status: LifecycleStatus;
    assetIds: readonly Handle[];
    quantities: readonly QuantityInput[];
    effectiveTime?: number;
    extras?: LogExtras;
    equipmentIds?: readonly Handle[];
  }): Handle {
    const logId = this.ids.mint("log");
    const quantities: QuantityRecord[] = input.quantities.map((q) => ({
      ...q,
      quantityId: this.ids.mint("qty"),
    }));
    this.emit<LogRecordedPayload>("log_recorded", {
      logId,
      kind: input.kind,
      name: input.name,
      status: input.status,
      assetIds: [...input.assetIds],
      quantities,
      effectiveTime: input.effectiveTime ?? this.now(),
      extras: input.extras,
      ...(input.equipmentIds?.length
        ? { equipmentIds: [...input.equipmentIds] }
        : {}),
    });
    return logId;
  }

  setLogStatus(targetId: Handle, status: LifecycleStatus): void {
    this.emit<LogStatusChangedPayload>("log_status_changed", { targetId, status });
  }

  restateEffectiveTime(targetId: Handle, effectiveTime: number): void {
    this.emit<LogTimeRestatedPayload>("log_time_restated", { targetId, effectiveTime });
  }

  archiveAsset(assetId: Handle): void {
    this.emit<AssetArchivedPayload>("asset_archived", { assetId });
  }

  deleteLog(logId: Handle): void {
    this.emit<LogDeletedPayload>("log_deleted", { logId });
  }

  deleteQuantity(quantityId: Handle): void {
    this.emit<QuantityDeletedPayload>("quantity_deleted", { quantityId });
  }

  // ---- folded views --------------------------------------------------------
  private recordedEvent(logId: Handle): KernelEvent<string, LogRecordedPayload> | undefined {
    return this.eventsOf<LogRecordedPayload>("log_recorded").find(
      (e) => e.payload.logId === logId,
    );
  }

  isLogDeleted(logId: Handle): boolean {
    return this.eventsOf<LogDeletedPayload>("log_deleted").some(
      (e) => e.payload.logId === logId,
    );
  }

  isQuantityDeleted(quantityId: Handle): boolean {
    return this.eventsOf<QuantityDeletedPayload>("quantity_deleted").some(
      (e) => e.payload.quantityId === quantityId,
    );
  }

  /** Latest-wins lifecycle status (STATUS_CONTRACT.logStatus: count-regardless). */
  logStatus(logId: Handle): LifecycleStatus | undefined {
    const rec = this.recordedEvent(logId);
    if (!rec) return undefined;
    const candidates: { hlc: Hlc; status: LifecycleStatus }[] = [
      { hlc: rec.hlc, status: rec.payload.status },
    ];
    for (const e of this.eventsOf<LogStatusChangedPayload>("log_status_changed")) {
      if (e.payload.targetId === logId) {
        candidates.push({ hlc: e.hlc, status: e.payload.status });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)?.status;
  }

  /** Latest-wins effective time: the recorded time superseded by restatements. */
  effectiveTimeOf(logId: Handle): number | undefined {
    const rec = this.recordedEvent(logId);
    if (!rec) return undefined;
    const candidates: { hlc: Hlc; t: number }[] = [
      { hlc: rec.hlc, t: rec.payload.effectiveTime },
    ];
    for (const e of this.eventsOf<LogTimeRestatedPayload>("log_time_restated")) {
      if (e.payload.targetId === logId) {
        candidates.push({ hlc: e.hlc, t: e.payload.effectiveTime });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)?.t;
  }

  /** Materialized log view, or undefined when unknown or deleted. */
  logView(logId: Handle): LogView | undefined {
    const rec = this.recordedEvent(logId);
    if (!rec || this.isLogDeleted(logId)) return undefined;
    const p = rec.payload;
    return {
      logId: p.logId,
      kind: p.kind,
      name: p.name,
      status: this.logStatus(logId)!,
      assetIds: p.assetIds,
      quantities: p.quantities.filter((q) => !this.isQuantityDeleted(q.quantityId)),
      effectiveTime: this.effectiveTimeOf(logId)!,
      extras: p.extras,
      equipmentIds: p.equipmentIds ?? [],
      hlc: rec.hlc,
    };
  }

  /**
   * Whether `equipmentId` is among the equipment the log states as used
   * (MetaCoding-1cv, the has_parent house form: membership, never a raw id).
   * `undefined` when the log is unknown or deleted — unanswerable, not false.
   */
  equipmentUsed(logId: Handle, equipmentId: Handle): boolean | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    return v.equipmentIds.includes(equipmentId);
  }

  /**
   * Logs referencing an asset, ascending (effectiveTime, HLC) — the source's
   * LogQueryFactory order with the forbidden id tie-break replaced by the
   * kernel HLC (decision w0a-2). Deleted logs excluded; `asOf` (epoch ms)
   * bounds effectiveTime when supplied.
   */
  logsForAsset(
    assetId: Handle,
    opts: { kind?: string; status?: LifecycleStatus; asOf?: number } = {},
  ): LogView[] {
    const views: LogView[] = [];
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      if (!e.payload.assetIds.includes(assetId)) continue;
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (opts.kind !== undefined && v.kind !== opts.kind) continue;
      if (opts.status !== undefined && v.status !== opts.status) continue;
      if (opts.asOf !== undefined && v.effectiveTime > opts.asOf) continue;
      views.push(v);
    }
    views.sort((a, b) =>
      a.effectiveTime !== b.effectiveTime
        ? a.effectiveTime - b.effectiveTime
        : compareHlc(a.hlc, b.hlc),
    );
    return views;
  }

  /** All live (non-deleted) log views, ascending (effectiveTime, HLC). */
  allLogs(opts: { kind?: string } = {}): LogView[] {
    const views: LogView[] = [];
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (opts.kind !== undefined && v.kind !== opts.kind) continue;
      views.push(v);
    }
    views.sort((a, b) =>
      a.effectiveTime !== b.effectiveTime
        ? a.effectiveTime - b.effectiveTime
        : compareHlc(a.hlc, b.hlc),
    );
    return views;
  }

  // ---- kernel-gated numeric folds -----------------------------------------
  //
  // The official numerics are confirmed-only (the ONE chosen divergence from
  // the source, decision pending-status-gates / MetaCoding-tkj); the excluded
  // pending mass is surfaced through the pending-only partners, never blended.
  // Folds sum across domain log kinds (observed: observation 3 + harvest 9 →
  // 12.0) and are NOT as-of-gated (observed: future-dated done log counts now).

  yieldTotal(assetId: Handle, measure: string, unit: string): number {
    return this.yieldUnder("yieldTotal", assetId, measure, unit);
  }

  pendingYieldTotal(assetId: Handle, measure: string, unit: string): number {
    return this.yieldUnder("pendingYieldTotal", assetId, measure, unit);
  }

  private yieldUnder(
    projection: "yieldTotal" | "pendingYieldTotal",
    assetId: Handle,
    measure: string,
    unit: string,
  ): number {
    const gate = gateFor(projection);
    let total = 0;
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      if (!this.registry.isLog(e.kind)) continue; // movements never contribute
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (!v.assetIds.includes(assetId)) continue;
      if (!passesGate(v.status, gate)) continue;
      for (const q of v.quantities) {
        if (q.measure === measure && q.unit === unit) total += q.value;
      }
    }
    return total;
  }

  logCount(assetId: Handle, kind: string): number {
    return this.countUnder("logCount", assetId, kind);
  }

  pendingLogCount(assetId: Handle, kind: string): number {
    return this.countUnder("pendingLogCount", assetId, kind);
  }

  private countUnder(
    projection: "logCount" | "pendingLogCount",
    assetId: Handle,
    kind: string,
  ): number {
    const gate = gateFor(projection);
    let count = 0;
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (v.kind !== kind) continue;
      if (!v.assetIds.includes(assetId)) continue;
      if (!passesGate(v.status, gate)) continue;
      count += 1;
    }
    return count;
  }

  /** Σ of a (measure, unit) pair on ONE log — the log's own recorded values,
   *  never status-gated (it reports what the event says, not a fold over many). */
  quantityRecorded(logId: Handle, measure: string, unit: string): number {
    const v = this.logView(logId);
    if (!v) return 0;
    let total = 0;
    for (const q of v.quantities) {
      if (q.measure === measure && q.unit === unit) total += q.value;
    }
    return total;
  }

  assetActive(assetId: Handle): boolean {
    return !this.eventsOf<AssetArchivedPayload>("asset_archived").some(
      (e) => e.payload.assetId === assetId,
    );
  }

  assetName(assetId: Handle): string | undefined {
    return this.eventsOf<AssetCreatedPayload>("asset_created").find(
      (e) => e.payload.assetId === assetId,
    )?.payload.name;
  }
}
