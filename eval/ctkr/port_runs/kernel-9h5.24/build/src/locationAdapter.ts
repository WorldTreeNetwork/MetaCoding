// The location+movement feature adapter (LocationAdapter). A thin projection
// view over the SAME SharedStore used by the logs adapter — identical surface to
// the 9h5.16 build.

import type { AssetSpec, MovementSpec, LocationAdapter, Handle } from "./types.ts";
import { SharedStore } from "./store.ts";

export function makeLocationAdapter(store: SharedStore): LocationAdapter {
  return {
    async createAsset(spec: AssetSpec): Promise<Handle> {
      return store.createAsset({
        entity: spec.entity,
        name: spec.name,
        isLocation: spec.isLocation,
        isFixed: spec.isFixed,
        intrinsicGeometry: spec.intrinsicGeometry,
      });
    },

    async recordMovement(spec: MovementSpec): Promise<Handle> {
      return store.recordMovement({
        name: spec.name,
        assetIds: spec.assets,
        locationIds: spec.locations,
        status: spec.status,
        timestamp: spec.timestamp,
        geometry: spec.geometry,
      });
    },

    async setLogStatus(log: Handle, status: string): Promise<void> {
      store.setStatus(log, status);
    },

    async setIntrinsicGeometry(asset: Handle, wkt: string): Promise<void> {
      store.setIntrinsicGeometry(asset, wkt);
    },

    async currentLocations(asset: Handle, atTimestamp: number): Promise<Handle[]> {
      return store.currentLocations(asset, atTimestamp);
    },

    async hasLocation(asset: Handle, atTimestamp: number): Promise<boolean> {
      return store.hasLocation(asset, atTimestamp);
    },

    async currentGeometry(asset: Handle, atTimestamp: number): Promise<string> {
      return store.currentGeometry(asset, atTimestamp);
    },

    async hasGeometry(asset: Handle, atTimestamp: number): Promise<boolean> {
      return store.hasGeometry(asset, atTimestamp);
    },

    async isFixed(asset: Handle): Promise<boolean> {
      return store.isFixed(asset);
    },

    async isLocation(asset: Handle): Promise<boolean> {
      return store.isLocationAsset(asset);
    },

    async assetsAtLocation(location: Handle, atTimestamp: number): Promise<Handle[]> {
      return store.assetsAtLocation(location, atTimestamp);
    },
  };
}
