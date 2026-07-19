// Adapter surfaces + event payloads for the kernel-based re-expression of the
// 9h5.16 composed store (MetaCoding-9h5.24). The two adapter interfaces
// (OracleAdapter, LocationAdapter) are BYTE-FOR-BYTE the same surfaces the
// committed judges drive — only the store BEHIND them now runs on the shared
// kernel. Handles are the kernel's opaque EntityId (see ../../../../../../src/kernel/ids.ts).

// Handle is an opaque string — identical surface to the 9h5.16 build. The store
// mints these via the kernel IdMinter (which returns the branded EntityId, a
// string subtype), so handles are replica-scoped and collision-free at runtime
// while the adapter/judge surface stays byte-for-byte the original `string`.
export type Handle = string;

// ---- Logs feature spec types (ADAPTER_CONTRACT_LOGS.md) — unchanged surface ----

export interface QuantitySpec {
  measure: string;
  value: number;
  unit: string;
  label?: string;
}

export interface OracleAdapter {
  open?(): void | Promise<void>;
  close?(): void | Promise<void>;

  createAsset(entity: string, name: string, descriptor?: string): Handle | Promise<Handle>;

  recordLog(
    kind: string,
    name: string,
    status: string,
    assetHandles: Handle[],
    quantities: QuantitySpec[],
  ): Handle | Promise<Handle>;

  setLogStatus(logHandle: Handle, status: string): void | Promise<void>;

  assignToGroup(assetHandle: Handle, groupHandle: Handle): void | Promise<void>;

  archiveAsset(assetHandle: Handle): void | Promise<void>;

  assetYieldTotal(assetHandle: Handle, measure: string, unit: string): number | Promise<number>;

  logStatus(logHandle: Handle): string | Promise<string>;

  logCount(assetHandle: Handle, kind: string): number | Promise<number>;

  assetActive(assetHandle: Handle): boolean | Promise<boolean>;

  groupMember(assetHandle: Handle, groupHandle: Handle): boolean | Promise<boolean>;

  quantityRecorded(logHandle: Handle, measure: string, unit: string): number | Promise<number>;
}

// ---- Location feature spec types (ADAPTER_SIGNATURES_LOCATION.md) — unchanged ----

export interface AssetSpec {
  entity: string;
  name: string;
  isLocation?: boolean;
  isFixed?: boolean;
  intrinsicGeometry?: string;
}

export interface MovementSpec {
  name?: string;
  assets: Handle[];
  locations: Handle[];
  status: string;
  timestamp: number;
  geometry?: string;
}

export interface LocationAdapter {
  open?(): Promise<void> | void;
  close?(): Promise<void> | void;

  createAsset(spec: AssetSpec): Promise<Handle>;
  recordMovement(spec: MovementSpec): Promise<Handle>;
  setLogStatus(log: Handle, status: string): Promise<void>;
  setIntrinsicGeometry(asset: Handle, wkt: string): Promise<void>;

  currentLocations(asset: Handle, atTimestamp: number): Promise<Handle[]>;
  hasLocation(asset: Handle, atTimestamp: number): Promise<boolean>;
  currentGeometry(asset: Handle, atTimestamp: number): Promise<string>;
  hasGeometry(asset: Handle, atTimestamp: number): Promise<boolean>;
  isFixed(asset: Handle): Promise<boolean>;
  isLocation(asset: Handle): Promise<boolean>;
  assetsAtLocation(location: Handle, atTimestamp: number): Promise<Handle[]>;
}

// ---- Event payloads (the typed body of each KernelEvent) ----
//
// The envelope (id, hlc, kind, payload) is the kernel's KernelEvent. Below are
// the per-kind payload shapes. `effectiveTime` on a movement is the DOMAIN
// (valid-time) axis used for as-of queries and current-location selection; it is
// distinct from the HLC (record/causal time) the kernel folds latest-wins on.

export interface AssetCreatedPayload {
  assetId: Handle;
  entity: string;
  name: string;
  descriptor?: string;
  isLocation: boolean;
  isFixed: boolean;
  intrinsicGeometry?: string;
}

export interface LogRecordedPayload {
  logId: Handle;
  kind: string;
  name: string;
  status: string;
  assetIds: Handle[];
  quantities: QuantitySpec[];
}

export interface LogStatusChangedPayload {
  targetId: Handle; // a logId OR a movementId — both carry a status lifecycle
  status: string;
}

export interface GroupAssignedPayload {
  assetId: Handle;
  groupId: Handle;
}

export interface AssetArchivedPayload {
  assetId: Handle;
}

export interface MovementRecordedPayload {
  movementId: Handle;
  name?: string;
  assetIds: Handle[];
  locationIds: Handle[];
  status: string;
  geometry?: string;
  /** valid-time (domain timestamp) — NOT the ordering key; the HLC is. */
  effectiveTime: number;
}

export interface GeometrySetPayload {
  assetId: Handle;
  wkt: string;
}
