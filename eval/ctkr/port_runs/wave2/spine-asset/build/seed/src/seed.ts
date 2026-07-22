// spine-asset · seed — asset bundle sharing plant's crop/variety + season field
// shape (required multi-valued plant_type, optional multi-valued season); no
// farm_location flags. Seed and plant declare the SAME two fields — the shared
// spine already carries this as a bundle config, so the two surfaces stay thin
// wrappers over one validator, never a copied fold.
//
// Source: modules/asset/seed/src/Plugin/Asset/AssetType/Seed.php.

import { SpineAssetStore, type Handle } from "../../shared-store/src/store.ts";

export function makeSeedAdapter(store: SpineAssetStore = new SpineAssetStore()) {
  return {
    store,
    /** plant_type (crop/variety) is REQUIRED and multi-valued — empty throws. */
    createSeed(name: string, plantType: readonly string[], season: readonly string[] = []): Handle {
      return store.createAsset({
        bundle: "seed",
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
    listSeed(): Handle[] {
      return store.listByBundle("seed");
    },
  };
}
