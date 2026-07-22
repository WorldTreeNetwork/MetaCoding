// spine-asset · material — asset bundle with ONE required typed field and no
// farm_location flags.
//
//   material_type  entity_reference → taxonomy_term(material_type), REQUIRED,
//                  single, auto_create (term creation NOT modeled)
//
// Source: modules/asset/material/src/Plugin/Asset/AssetType/Material.php.
//
// PUNTED UP (out of this asset-spine surface): farm_material also implements a
// quantity_presave hook (src/Hook/EntityHooks.php) that COPIES a material
// asset's material_type onto a referencing material-bundle quantity via its
// inventory_asset reference. That is a cross-entity denormalizing fold over the
// quantity entity + inventory_asset field — none of which exist in the asset
// spine. See punts.jsonl spine-asset-material-quantity-presave.

import { SpineAssetStore, type Handle } from "../../shared-store/src/store.ts";

export function makeMaterialAdapter(store: SpineAssetStore = new SpineAssetStore()) {
  return {
    store,
    /** material_type is REQUIRED — a missing/empty term throws at creation. */
    createMaterial(name: string, materialType: string): Handle {
      return store.createAsset({
        bundle: "material",
        name,
        fields: { material_type: materialType },
      });
    },
    archive(asset: Handle): void {
      store.archiveAsset(asset);
    },
    isActive(asset: Handle): boolean {
      return store.assetActive(asset);
    },
    materialTypeOf(asset: Handle): string | undefined {
      return store.fieldOf(asset, "material_type") as string | undefined;
    },
    listMaterial(): Handle[] {
      return store.listByBundle("material");
    },
  };
}
