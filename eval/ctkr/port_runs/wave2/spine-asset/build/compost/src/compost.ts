// spine-asset · compost — the barest asset bundle: no bundle fields, no
// farm_location flags (asset.type.compost.yml declares neither is_location nor
// is_fixed). The typed creation surface is just name → compost asset; the whole
// behavior is inherited from the shared asset spine.
//
// Source: modules/asset/compost/src/Plugin/Asset/AssetType/Compost.php
// (extends FarmAssetType, adds nothing) and config/install/asset.type.compost.yml.

import { SpineAssetStore, type Handle } from "../../shared-store/src/store.ts";

export function makeCompostAdapter(store: SpineAssetStore = new SpineAssetStore()) {
  return {
    store,
    createCompost(name: string): Handle {
      return store.createAsset({ bundle: "compost", name });
    },
    archive(asset: Handle): void {
      store.archiveAsset(asset);
    },
    isActive(asset: Handle): boolean {
      return store.assetActive(asset);
    },
    listCompost(): Handle[] {
      return store.listByBundle("compost");
    },
  };
}
