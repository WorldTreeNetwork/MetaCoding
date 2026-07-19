// The ONE shared append-only event log + asset model, re-expressed ON the shared
// kernel (MetaCoding-9h5.24). Same observable behavior as the 9h5.16 composed
// store — 27 fixtures + 5 cross-probes — but every kernel concern now comes from
// the frozen primitives:
//
//   - the log is a kernel EventLog gated by the closed KindRegistry (element 1)
//   - handles are minted by the kernel IdMinter (element 2a) — no bare ordinals
//   - ordering is the kernel HLC via clock.tick() (element 2b) — no serial seq
//   - latest-wins folds go through the kernel pickLatest comparator (element 3)
//   - status gates read the kernel STATUS_CONTRACT (element 4)
//   - CM decisions are checked against a binding registry at construction (element 5)

import {
  HlcClock,
  IdMinter,
  EventLog,
  KindRegistry,
  pickLatest,
  compareHlc,
  gateFor,
  passesGate,
  CmDecisionRegistry,
  type KernelEvent,
  type Hlc,
} from "../../../../../../src/kernel/index.ts";
import {
  makeKernelRegistry,
  BOUND_CM_DECISIONS,
  REQUIRED_DECISIONS,
} from "./kernelConfig.ts";
import type {
  Handle,
  QuantitySpec,
  AssetCreatedPayload,
  LogRecordedPayload,
  LogStatusChangedPayload,
  GroupAssignedPayload,
  AssetArchivedPayload,
  MovementRecordedPayload,
  GeometrySetPayload,
} from "./types.ts";

// The discriminated event union carried by the one EventLog.
type StoreEvent =
  | KernelEvent<"asset_created", AssetCreatedPayload>
  | KernelEvent<"log_recorded", LogRecordedPayload>
  | KernelEvent<"log_status_changed", LogStatusChangedPayload>
  | KernelEvent<"group_assigned", GroupAssignedPayload>
  | KernelEvent<"asset_archived", AssetArchivedPayload>
  | KernelEvent<"movement_recorded", MovementRecordedPayload>
  | KernelEvent<"geometry_set", GeometrySetPayload>;

export interface StoreOptions {
  replicaId?: string;
  registry?: KindRegistry;
  decisions?: CmDecisionRegistry;
}

export class SharedStore {
  private readonly log: EventLog<StoreEvent>;
  private readonly clock: HlcClock;
  private readonly ids: IdMinter;
  private readonly assetOrder: Handle[] = [];

  constructor(opts: StoreOptions = {}) {
    const replicaId = opts.replicaId ?? "R1";
    this.clock = new HlcClock(replicaId);
    this.ids = new IdMinter(replicaId);
    this.log = new EventLog<StoreEvent>(opts.registry ?? makeKernelRegistry());

    // Element 5: FAIL LOUDLY if a CM decision this build depends on is unresolved.
    const decisions = opts.decisions ?? new CmDecisionRegistry(BOUND_CM_DECISIONS);
    decisions.requireAllBound(REQUIRED_DECISIONS);
  }

  // ---- generic append: stamp id + HLC, gate kind through the registry ----
  private emit<K extends StoreEvent["kind"], P>(kind: K, payload: P): void {
    this.log.append({
      id: this.ids.mint("evt"),
      hlc: this.clock.tick(),
      kind,
      payload,
    } as StoreEvent);
  }

  // ---- mutations (shared by both adapters) ----

  createAsset(input: {
    entity: string;
    name: string;
    descriptor?: string;
    isLocation?: boolean;
    isFixed?: boolean;
    intrinsicGeometry?: string;
  }): Handle {
    const assetId = this.ids.mint("asset");
    this.emit<"asset_created", AssetCreatedPayload>("asset_created", {
      assetId,
      entity: input.entity,
      name: input.name,
      descriptor: input.descriptor,
      isLocation: input.isLocation ?? false,
      isFixed: input.isFixed ?? false,
      intrinsicGeometry: input.intrinsicGeometry,
    });
    this.assetOrder.push(assetId);
    return assetId;
  }

  recordLog(
    kind: string,
    name: string,
    status: string,
    assetHandles: Handle[],
    quantities: QuantitySpec[],
  ): Handle {
    const logId = this.ids.mint("log");
    this.emit<"log_recorded", LogRecordedPayload>("log_recorded", {
      logId,
      kind,
      name,
      status,
      assetIds: [...assetHandles],
      quantities: quantities.map((q) => ({ ...q })),
    });
    return logId;
  }

  setStatus(targetId: Handle, status: string): void {
    this.emit<"log_status_changed", LogStatusChangedPayload>("log_status_changed", {
      targetId,
      status,
    });
  }

  assignToGroup(assetId: Handle, groupId: Handle): void {
    this.emit<"group_assigned", GroupAssignedPayload>("group_assigned", { assetId, groupId });
  }

  archiveAsset(assetId: Handle): void {
    this.emit<"asset_archived", AssetArchivedPayload>("asset_archived", { assetId });
  }

  recordMovement(input: {
    name?: string;
    assetIds: Handle[];
    locationIds: Handle[];
    status: string;
    timestamp: number;
    geometry?: string;
  }): Handle {
    const movementId = this.ids.mint("mvt");
    this.emit<"movement_recorded", MovementRecordedPayload>("movement_recorded", {
      movementId,
      name: input.name,
      assetIds: [...input.assetIds],
      locationIds: [...input.locationIds],
      status: input.status,
      geometry: input.geometry,
      effectiveTime: input.timestamp,
    });
    return movementId;
  }

  setIntrinsicGeometry(assetId: Handle, wkt: string): void {
    this.emit<"geometry_set", GeometrySetPayload>("geometry_set", { assetId, wkt });
  }

  // ---- typed views over the one log ----

  private events(): readonly StoreEvent[] {
    return this.log.all();
  }

  private findAsset(assetId: Handle): AssetCreatedPayload | undefined {
    for (const e of this.events()) {
      if (e.kind === "asset_created" && e.payload.assetId === assetId) return e.payload;
    }
    return undefined;
  }

  allAssetIds(): Handle[] {
    return [...this.assetOrder];
  }

  isFixed(assetId: Handle): boolean {
    return this.findAsset(assetId)?.isFixed ?? false;
  }

  isLocationAsset(assetId: Handle): boolean {
    return this.findAsset(assetId)?.isLocation ?? false;
  }

  assetActive(assetId: Handle): boolean {
    return !this.events().some(
      (e) => e.kind === "asset_archived" && e.payload.assetId === assetId,
    );
  }

  // ---- logs-feature projections ----

  logStatus(logId: Handle): string {
    // latest-wins over the created status + any log_status_changed, keyed on HLC.
    const candidates: { hlc: Hlc; status: string }[] = [];
    for (const e of this.events()) {
      if (e.kind === "log_recorded" && e.payload.logId === logId) {
        candidates.push({ hlc: e.hlc, status: e.payload.status });
      } else if (e.kind === "log_status_changed" && e.payload.targetId === logId) {
        candidates.push({ hlc: e.hlc, status: e.payload.status });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)?.status ?? "";
  }

  assetYieldTotal(assetId: Handle, measure: string, unit: string): number {
    const gate = gateFor("yieldTotal"); // count-regardless: pending counts
    let total = 0;
    for (const e of this.events()) {
      if (e.kind !== "log_recorded") continue;
      if (!e.payload.assetIds.includes(assetId)) continue;
      if (!passesGate(e.payload.status, gate)) continue;
      for (const q of e.payload.quantities) {
        if (q.measure === measure && q.unit === unit) total += q.value;
      }
    }
    return total;
  }

  logCount(assetId: Handle, kind: string): number {
    const gate = gateFor("logCount"); // count-regardless
    let count = 0;
    for (const e of this.events()) {
      if (e.kind !== "log_recorded") continue; // only family "log" — a movement is not a log
      if (e.payload.kind !== kind) continue;
      if (!e.payload.assetIds.includes(assetId)) continue;
      if (!passesGate(e.payload.status, gate)) continue;
      count += 1;
    }
    return count;
  }

  groupMember(assetId: Handle, groupId: Handle): boolean {
    // Membership is a single latest-wins register, never an additive set.
    const candidates: { hlc: Hlc; groupId: Handle }[] = [];
    for (const e of this.events()) {
      if (e.kind === "group_assigned" && e.payload.assetId === assetId) {
        candidates.push({ hlc: e.hlc, groupId: e.payload.groupId });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)?.groupId === groupId;
  }

  quantityRecorded(logId: Handle, measure: string, unit: string): number {
    for (const e of this.events()) {
      if (e.kind === "log_recorded" && e.payload.logId === logId) {
        let total = 0;
        for (const q of e.payload.quantities) {
          if (q.measure === measure && q.unit === unit) total += q.value;
        }
        return total;
      }
    }
    return 0;
  }

  // ---- location-feature projections ----

  private movementStatus(m: KernelEvent<"movement_recorded", MovementRecordedPayload>): string {
    const candidates: { hlc: Hlc; status: string }[] = [
      { hlc: m.hlc, status: m.payload.status },
    ];
    for (const e of this.events()) {
      if (e.kind === "log_status_changed" && e.payload.targetId === m.payload.movementId) {
        candidates.push({ hlc: e.hlc, status: e.payload.status });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)!.status;
  }

  // The latest CONFIRMED movement affecting `assetId` at or before `atTimestamp`.
  // Selection is by valid-time (effectiveTime) primary, HLC as the kernel-owned
  // tie-break for same-timestamp movements (fixture 43a074ca).
  private latestMovement(
    assetId: Handle,
    atTimestamp: number,
  ): KernelEvent<"movement_recorded", MovementRecordedPayload> | undefined {
    if (this.isFixed(assetId)) return undefined; // fixed assets ignore movements
    const gate = gateFor("currentLocation"); // require-confirmed: pending inert
    let best: KernelEvent<"movement_recorded", MovementRecordedPayload> | undefined;
    for (const e of this.events()) {
      if (e.kind !== "movement_recorded") continue;
      if (!e.payload.assetIds.includes(assetId)) continue;
      if (e.payload.effectiveTime > atTimestamp) continue;
      if (!passesGate(this.movementStatus(e), gate)) continue;
      if (
        best === undefined ||
        e.payload.effectiveTime > best.payload.effectiveTime ||
        (e.payload.effectiveTime === best.payload.effectiveTime &&
          compareHlc(e.hlc, best.hlc) > 0)
      ) {
        best = e;
      }
    }
    return best;
  }

  currentLocations(assetId: Handle, atTimestamp: number): Handle[] {
    const m = this.latestMovement(assetId, atTimestamp);
    return m ? [...m.payload.locationIds] : [];
  }

  hasLocation(assetId: Handle, atTimestamp: number): boolean {
    return this.currentLocations(assetId, atTimestamp).length > 0;
  }

  currentGeometry(assetId: Handle, atTimestamp: number): string {
    if (this.isFixed(assetId)) {
      // latest geometry_set (by HLC), else the intrinsic geometry it was born with.
      const created = this.findAsset(assetId);
      const candidates: { hlc: Hlc; wkt: string }[] = [];
      for (const e of this.events()) {
        if (e.kind === "geometry_set" && e.payload.assetId === assetId) {
          candidates.push({ hlc: e.hlc, wkt: e.payload.wkt });
        }
      }
      const latest = pickLatest(candidates, (c) => c.hlc);
      if (latest) return latest.wkt;
      return created?.intrinsicGeometry ?? "";
    }
    const m = this.latestMovement(assetId, atTimestamp);
    return m?.payload.geometry ?? "";
  }

  hasGeometry(assetId: Handle, atTimestamp: number): boolean {
    return this.currentGeometry(assetId, atTimestamp) !== "";
  }

  assetsAtLocation(locationId: Handle, atTimestamp: number): Handle[] {
    return this.assetOrder.filter((assetId) =>
      this.currentLocations(assetId, atTimestamp).includes(locationId),
    );
  }
}
