// Composed store entry point. `createComposedStore()` wires BOTH feature
// adapters to ONE shared event log + asset model (see store.ts).

import { SharedStore } from "./store";
import { makeLogsAdapter } from "./logsAdapter";
import { makeLocationAdapter } from "./locationAdapter";
import type { OracleAdapter, LocationAdapter } from "./types";

export function createComposedStore(): {
  logs: OracleAdapter;
  location: LocationAdapter;
} {
  const store = new SharedStore(); // exactly one shared store per call
  return {
    logs: makeLogsAdapter(store),
    location: makeLocationAdapter(store),
  };
}

export type {
  Handle,
  QuantitySpec,
  OracleAdapter,
  AssetSpec,
  MovementSpec,
  LocationAdapter,
} from "./types";
