// The ONE shared append-only event log + asset model, plus the projection
// (fold) helpers both adapters read through. See PORT_DECISIONS.md for the
// rationale behind every choice made here.

import type {
  StoreEvent,
  AssetCreatedEvent,
  LogRecordedEvent,
  MovementRecordedEvent,
  Handle,
  QuantitySpec,
} from "./types";

export class SharedStore {
  // Exactly one log array. Every mutation from either adapter appends here.
  private events: StoreEvent[] = [];
  private seq = 0;
  private assetOrder: Handle[] = []; // insertion-ordered registry of every asset ever created

  // ---- ID / handle minting: one counter, one scheme, for everything ----
  private mintHandle(prefix: string): Handle {
    this.seq += 1;
    return `${prefix}_${this.seq}`;
  }

  private nextSeq(): number {
    this.seq += 1;
    return this.seq;
  }

  private append<E extends StoreEvent>(event: E): E {
    this.events.push(event);
    return event;
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
    const seq = this.nextSeq();
    const assetId = this.mintHandle("asset");
    this.append<AssetCreatedEvent>({
      type: "asset_created",
      seq,
      timestamp: seq,
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
    const seq = this.nextSeq();
    const logId = this.mintHandle("log");
    this.append<LogRecordedEvent>({
      type: "log_recorded",
      seq,
      timestamp: seq,
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
    const seq = this.nextSeq();
    this.append({
      type: "log_status_changed",
      seq,
      timestamp: seq,
      targetId,
      status,
    });
  }

  assignToGroup(assetId: Handle, groupId: Handle): void {
    const seq = this.nextSeq();
    this.append({
      type: "group_assigned",
      seq,
      timestamp: seq,
      assetId,
      groupId,
    });
  }

  archiveAsset(assetId: Handle): void {
    const seq = this.nextSeq();
    this.append({
      type: "asset_archived",
      seq,
      timestamp: seq,
      assetId,
    });
  }

  recordMovement(input: {
    name?: string;
    assetIds: Handle[];
    locationIds: Handle[];
    status: string;
    timestamp: number;
    geometry?: string;
  }): Handle {
    const seq = this.nextSeq();
    const movementId = this.mintHandle("mvt");
    this.append<MovementRecordedEvent>({
      type: "movement_recorded",
      seq,
      // Movements carry a real domain timestamp from the caller; that IS the
      // ordering time used by the latest-wins fold (see below).
      timestamp: input.timestamp,
      movementId,
      name: input.name,
      assetIds: [...input.assetIds],
      locationIds: [...input.locationIds],
      status: input.status,
      geometry: input.geometry,
    });
    return movementId;
  }

  setIntrinsicGeometry(assetId: Handle, wkt: string): void {
    const seq = this.nextSeq();
    this.append({
      type: "geometry_set",
      seq,
      timestamp: seq,
      assetId,
      wkt,
    });
  }

  // ---- shared read helpers (projections over the ONE log) ----

  private findAsset(assetId: Handle): AssetCreatedEvent | undefined {
    return this.events.find(
      (e): e is AssetCreatedEvent => e.type === "asset_created" && e.assetId === assetId,
    );
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
    return !this.events.some((e) => e.type === "asset_archived" && e.assetId === assetId);
  }

  // THE one latest-wins fold, used by both the group-membership read and the
  // current-location read. Given a list of (orderKey, value) candidates, pick
  // the one with the greatest orderKey, tie-broken by insertion sequence
  // (later `seq` wins on an exact tie). orderKey defaults to `seq` itself for
  // events that carry no real domain timestamp, which is what makes this one
  // rule serve both timestamped movements and un-timestamped logs mutations.
  private pickLatest<T extends { timestamp: number; seq: number }>(candidates: T[]): T | undefined {
    let best: T | undefined;
    for (const c of candidates) {
      if (
        !best ||
        c.timestamp > best.timestamp ||
        (c.timestamp === best.timestamp && c.seq > best.seq)
      ) {
        best = c;
      }
    }
    return best;
  }

  // ---- logs-feature projections ----

  logStatus(logId: Handle): string {
    const created = this.events.find(
      (e): e is LogRecordedEvent => e.type === "log_recorded" && e.logId === logId,
    );
    const candidates: { timestamp: number; seq: number; status: string }[] = [];
    if (created) candidates.push({ timestamp: created.timestamp, seq: created.seq, status: created.status });
    for (const e of this.events) {
      if (e.type === "log_status_changed" && e.targetId === logId) {
        candidates.push({ timestamp: e.timestamp, seq: e.seq, status: e.status });
      }
    }
    return this.pickLatest(candidates)?.status ?? "";
  }

  assetYieldTotal(assetId: Handle, measure: string, unit: string): number {
    let total = 0;
    for (const e of this.events) {
      if (e.type !== "log_recorded") continue;
      if (!e.assetIds.includes(assetId)) continue;
      for (const q of e.quantities) {
        if (q.measure === measure && q.unit === unit) total += q.value;
      }
    }
    return total;
  }

  logCount(assetId: Handle, kind: string): number {
    let count = 0;
    for (const e of this.events) {
      if (e.type === "log_recorded" && e.kind === kind && e.assetIds.includes(assetId)) count += 1;
    }
    return count;
  }

  groupMember(assetId: Handle, groupId: Handle): boolean {
    const candidates: { timestamp: number; seq: number; groupId: Handle }[] = [];
    for (const e of this.events) {
      if (e.type === "group_assigned" && e.assetId === assetId) {
        candidates.push({ timestamp: e.timestamp, seq: e.seq, groupId: e.groupId });
      }
    }
    const latest = this.pickLatest(candidates);
    return latest?.groupId === groupId;
  }

  quantityRecorded(logId: Handle, measure: string, unit: string): number {
    const created = this.events.find(
      (e): e is LogRecordedEvent => e.type === "log_recorded" && e.logId === logId,
    );
    if (!created) return 0;
    let total = 0;
    for (const q of created.quantities) {
      if (q.measure === measure && q.unit === unit) total += q.value;
    }
    return total;
  }

  // ---- location-feature projections ----

  // Effective status of a movement, folding any later log_status_changed
  // events that target it — same latest-wins rule as logStatus().
  private movementStatus(m: MovementRecordedEvent): string {
    const candidates: { timestamp: number; seq: number; status: string }[] = [
      { timestamp: m.timestamp, seq: m.seq, status: m.status },
    ];
    for (const e of this.events) {
      if (e.type === "log_status_changed" && e.targetId === m.movementId) {
        candidates.push({ timestamp: e.timestamp, seq: e.seq, status: e.status });
      }
    }
    return this.pickLatest(candidates)!.status;
  }

  // The latest DONE movement affecting `assetId` at or before `atTimestamp`.
  private latestMovement(assetId: Handle, atTimestamp: number): MovementRecordedEvent | undefined {
    if (this.isFixed(assetId)) return undefined; // fixed assets ignore movements entirely
    const candidates = this.events.filter(
      (e): e is MovementRecordedEvent =>
        e.type === "movement_recorded" &&
        e.assetIds.includes(assetId) &&
        e.timestamp <= atTimestamp &&
        this.movementStatus(e) === "done",
    );
    return this.pickLatest(candidates);
  }

  currentLocations(assetId: Handle, atTimestamp: number): Handle[] {
    const m = this.latestMovement(assetId, atTimestamp);
    return m ? [...m.locationIds] : [];
  }

  hasLocation(assetId: Handle, atTimestamp: number): boolean {
    return this.currentLocations(assetId, atTimestamp).length > 0;
  }

  currentGeometry(assetId: Handle, atTimestamp: number): string {
    if (this.isFixed(assetId)) {
      // Latest explicit setIntrinsicGeometry at/before atTimestamp, else the
      // geometry the asset was created with.
      const created = this.findAsset(assetId);
      const candidates: { timestamp: number; seq: number; wkt: string }[] = [];
      if (created?.intrinsicGeometry !== undefined) {
        candidates.push({ timestamp: created.timestamp, seq: created.seq, wkt: created.intrinsicGeometry });
      }
      for (const e of this.events) {
        if (e.type === "geometry_set" && e.assetId === assetId && e.timestamp <= atTimestamp) {
          candidates.push({ timestamp: e.timestamp, seq: e.seq, wkt: e.wkt });
        }
      }
      return this.pickLatest(candidates)?.wkt ?? "";
    }
    const m = this.latestMovement(assetId, atTimestamp);
    return m?.geometry ?? "";
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
