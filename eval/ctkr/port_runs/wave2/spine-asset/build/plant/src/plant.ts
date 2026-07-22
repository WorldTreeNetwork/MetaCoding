// spine-asset · plant — asset bundle with a required multi-valued crop/variety
// field plus an optional multi-valued season field; no farm_location flags.
//
//   plant_type  entity_reference → taxonomy_term(plant_type), REQUIRED, MULTIPLE
//   season      entity_reference → taxonomy_term(season), MULTIPLE
//   (both auto_create; term creation NOT modeled — punt spine-asset-autocreate)
//
// Source: modules/asset/plant/src/Plugin/Asset/AssetType/Plant.php.

import { SpineAssetStore, type Handle } from "../../shared-store/src/store.ts";

export function makePlantAdapter(store: SpineAssetStore = new SpineAssetStore()) {
  return {
    store,
    /** plant_type (crop/variety) is REQUIRED and multi-valued — empty throws. */
    createPlant(name: string, plantType: readonly string[], season: readonly string[] = []): Handle {
      return store.createAsset({
        bundle: "plant",
        name,
        fields: { plant_type: plantType, season },
      });
    },
    archive(asset: Handle): void {
      store.archiveAsset(asset);
    },
    isActive(asset: Handle): boolean {
      return store.assetActive(asset);
    },
    plantTypesOf(asset: Handle): readonly string[] {
      return (store.fieldOf(asset, "plant_type") as readonly string[] | undefined) ?? [];
    },
    seasonsOf(asset: Handle): readonly string[] {
      return (store.fieldOf(asset, "season") as readonly string[] | undefined) ?? [];
    },
    listPlant(): Handle[] {
      return store.listByBundle("plant");
    },
  };
}
