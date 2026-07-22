// port-verify bridge for the spine-asset product build (shared spine bridge runtime).
// Declares ONLY the asset-bundle operations/probes genuinely implemented by the
// shared SpineAssetStore for this bundle. Trailing readings judge against the
// recorded packs; gaps are declared, never overclaimed.

import { runBridge } from "../shared-store/src/bridge.ts";
import { SpineAssetStore } from "../shared-store/src/store.ts";

await runBridge({
  port: "w2-spine-asset-product",
  bundle: "product",
  operations: ["create_asset", "archive_asset"],
  probes: ["asset_active", "asset_bundle", "is_location", "is_fixed", "asset_field"],
  makeStore: () => new SpineAssetStore({ replicaId: "W2-product" }),
});
