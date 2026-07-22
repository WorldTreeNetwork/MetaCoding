// wave-2 spine-asset closed kind taxonomy — the ONE shared asset-bundle spine
// that all seven concrete bundles (compost / equipment / material / plant /
// product / seed / water) fold through. Modeled on the wave-1 Wave1LogStore
// shape (event-sourced on the frozen kernel v1.3, consumed via import, never
// vendored) but scoped to the asset-bundle idiom rather than the log family.
//
// Only two kinds are needed for the asset spine — the birth of an asset into a
// bundle and its archival. Both names are inherited from the 9h5.24 composed
// store / the wave-1 shared taxonomy (asset_created, asset_archived), so the
// spine claim ("asset_created kind, archive lifecycle") is literal, not novel.

import {
  KindRegistry,
  type KindSpec,
} from "../../../../../../../../src/kernel/index.ts";

/** Kinds shared by the whole wave-2 asset-bundle spine. */
export const SPINE_ASSET_KINDS: readonly KindSpec[] = [
  {
    kind: "asset_created",
    family: "asset",
    isLog: false,
    description:
      "births an asset into a concrete bundle (compost/equipment/material/plant/product/seed/water); payload.bundle names it (9h5.24 name)",
  },
  {
    kind: "asset_archived",
    family: "lifecycle",
    isLog: false,
    description:
      "flips assetActive to false; leaves history intact (9h5.24 name). Monotonic in this spine — see punt spine-asset-archive-monotonic",
  },
];

/**
 * The frozen registry for a spine-asset store. A bundle passes no extra kinds
 * in the base spine (every bundle is asset_created + asset_archived only); the
 * `extra` seam is kept for symmetry with the wave-1 house pattern and for a
 * future bundle that genuinely needs its own event kind.
 */
export function makeSpineAssetRegistry(extra: readonly KindSpec[] = []): KindRegistry {
  return new KindRegistry().extend(SPINE_ASSET_KINDS).extend(extra).freeze();
}
