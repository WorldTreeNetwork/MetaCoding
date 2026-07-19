// Composed store entry point, re-expressed on the shared kernel. Same surface as
// the 9h5.16 build: `createComposedStore()` wires BOTH feature adapters to ONE
// shared kernel EventLog + asset model. The committed judges import this
// unchanged.

import { SharedStore, type StoreOptions } from "./store.ts";
import { makeLogsAdapter } from "./logsAdapter.ts";
import { makeLocationAdapter } from "./locationAdapter.ts";
import type { OracleAdapter, LocationAdapter } from "./types.ts";

export function createComposedStore(opts?: StoreOptions): {
  logs: OracleAdapter;
  location: LocationAdapter;
} {
  const store = new SharedStore(opts); // exactly one shared, kernel-backed store per call
  return {
    logs: makeLogsAdapter(store),
    location: makeLocationAdapter(store),
  };
}

export { SharedStore } from "./store.ts";
export type {
  Handle,
  QuantitySpec,
  OracleAdapter,
  AssetSpec,
  MovementSpec,
  LocationAdapter,
} from "./types.ts";
