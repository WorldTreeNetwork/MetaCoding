// port-verify bridge for the w2 identity-structure build (shared wave-1 store
// runtime, imported not vendored).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: archive_asset (fixture 024795's `when` step — the one glossary
//               write action this pack exercises)
//   probes:     asset_active, structure_kind
//
// A structure IS a plain ASSET (farmOS asset--structure): it births through
// the pre-existing GENERIC create_asset given path with entity "structure" and
// its structure_type machine id as the descriptor — no dedicated create op and
// no feature-local birth event (unlike the sensor, whose three bundle fields
// motivate one; a structure carries exactly one). structure_kind folds the
// recorded descriptor back off the materialized asset_created event, with the
// source's stated default "other" when the structure was born without one —
// a FALLBACK VALUE, never an empty string. asset_active answers on the same
// handle through the shared asset lifecycle fold, and archive touches ONLY
// that fold: an archived structure still reports its recorded kind (fixture
// 024795) because kind and lifecycle fold off different events. A subject that
// is not a structure asset — a non-structure asset even when it carries a
// descriptor, a sensor, a log, a plant_type term, a ghost handle — is
// UNANSWERABLE, never "other" and never "". Nothing is stubbed. All values
// fold off MATERIALIZED store state, never an input echo.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-identity-structure",
  operations: ["archive_asset"],
  probes: ["asset_active", "structure_kind"],
  makeStore: () => new Wave1LogStore({ replicaId: "W2ST" }),
});
