// spine-asset · water — the ONLY cluster bundle that declares farm_location
// third-party settings. asset.type.water.yml:
//   third_party_settings.farm_location: { is_location: true, is_fixed: true }
// so a water asset is born is_location=true, is_fixed=true BY DEFAULT (the
// LocationDefaultValues bundle-default semantics). No bundle fields.
//
// Source: modules/asset/water/src/Plugin/Asset/AssetType/Water.php (bare) +
// config/install/asset.type.water.yml (the flags).

import { SpineAssetStore, type Handle } from "../../shared-store/src/store.ts";

export interface WaterFlags {
  /** override the bundle default (true) for this instance, e.g. a mobile tank. */
  isLocation?: boolean;
  isFixed?: boolean;
}

export function makeWaterAdapter(store: SpineAssetStore = new SpineAssetStore()) {
  return {
    store,
    /** Defaults is_location=true, is_fixed=true; overrides win per-asset. */
    createWater(name: string, flags: WaterFlags = {}): Handle {
      return store.createAsset({
        bundle: "water",
        name,
        isLocation: flags.isLocation,
        isFixed: flags.isFixed,
      });
    },
    archive(asset: Handle): void {
      store.archiveAsset(asset);
    },
    isActive(asset: Handle): boolean {
      return store.assetActive(asset);
    },
    isLocation(asset: Handle): boolean | undefined {
      return store.isLocation(asset);
    },
    isFixed(asset: Handle): boolean | undefined {
      return store.isFixed(asset);
    },
    listWater(): Handle[] {
      return store.listByBundle("water");
    },
  };
}
