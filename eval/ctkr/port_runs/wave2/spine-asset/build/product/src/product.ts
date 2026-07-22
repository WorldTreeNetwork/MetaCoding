// spine-asset · product — asset bundle with ONE required single-valued typed
// field and no farm_location flags.
//
//   product_type  entity_reference → taxonomy_term(product_type), REQUIRED,
//                 single, auto_create (term creation NOT modeled)
//
// Source: modules/asset/product/src/Plugin/Asset/AssetType/Product.php.

import { SpineAssetStore, type Handle } from "../../shared-store/src/store.ts";

export function makeProductAdapter(store: SpineAssetStore = new SpineAssetStore()) {
  return {
    store,
    /** product_type is REQUIRED — a missing/empty term throws at creation. */
    createProduct(name: string, productType: string): Handle {
      return store.createAsset({
        bundle: "product",
        name,
        fields: { product_type: productType },
      });
    },
    archive(asset: Handle): void {
      store.archiveAsset(asset);
    },
    isActive(asset: Handle): boolean {
      return store.assetActive(asset);
    },
    productTypeOf(asset: Handle): string | undefined {
      return store.fieldOf(asset, "product_type") as string | undefined;
    },
    listProduct(): Handle[] {
      return store.listByBundle("product");
    },
  };
}
