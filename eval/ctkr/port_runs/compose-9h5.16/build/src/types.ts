// Shared types for the composed store: the single event log, the shared
// asset model, and the domain-vocabulary spec types used by both adapters.

export type Handle = string;

// ---- Logs feature spec types (ADAPTER_CONTRACT_LOGS.md) ----

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

// ---- Location feature spec types (ADAPTER_SIGNATURES_LOCATION.md) ----

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

// ---- The ONE shared event log ----
//
// Every mutation from either feature appends one of these event kinds to the
// SAME array. `timestamp` is the domain/logical time used for every
// latest-wins fold (see store.ts): when a mutation carries a real domain
// timestamp (movements), we use it; otherwise we fall back to the event's
// insertion sequence number, which is always strictly increasing. `seq` is
// the tie-break used when two events share the same `timestamp`.

interface BaseEvent {
  seq: number;
  timestamp: number;
}

export interface AssetCreatedEvent extends BaseEvent {
  type: "asset_created";
  assetId: Handle;
  entity: string;
  name: string;
  descriptor?: string;
  isLocation: boolean;
  isFixed: boolean;
  intrinsicGeometry?: string;
}

export interface LogRecordedEvent extends BaseEvent {
  type: "log_recorded";
  logId: Handle;
  kind: string;
  name: string;
  status: string;
  assetIds: Handle[];
  quantities: QuantitySpec[];
}

export interface LogStatusChangedEvent extends BaseEvent {
  type: "log_status_changed";
  // Targets either a log_recorded.logId or a movement_recorded.movementId —
  // both "logs" in the shared status sense (see PORT_DECISIONS.md).
  targetId: Handle;
  status: string;
}

export interface GroupAssignedEvent extends BaseEvent {
  type: "group_assigned";
  assetId: Handle;
  groupId: Handle;
}

export interface AssetArchivedEvent extends BaseEvent {
  type: "asset_archived";
  assetId: Handle;
}

export interface MovementRecordedEvent extends BaseEvent {
  type: "movement_recorded";
  movementId: Handle;
  name?: string;
  assetIds: Handle[];
  locationIds: Handle[];
  status: string;
  geometry?: string;
}

export interface GeometrySetEvent extends BaseEvent {
  type: "geometry_set";
  assetId: Handle;
  wkt: string;
}

export type StoreEvent =
  | AssetCreatedEvent
  | LogRecordedEvent
  | LogStatusChangedEvent
  | GroupAssignedEvent
  | AssetArchivedEvent
  | MovementRecordedEvent
  | GeometrySetEvent;
