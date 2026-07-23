// port-verify bridge for the w2 identity-plant-type build (shared wave-1 store
// runtime, imported not vendored).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: (none — a plant_type carries no glossary write action; the
//               `given` write surface create_plant_type_term is ungated, like
//               create_asset, so it is not a declared operation)
//   probes:     days_to_maturity, days_to_harvest, crop_family, companion_plants
//
// A plant_type is a TAXONOMY TERM (farm_plant_type), NOT a log — so this feature
// does not touch record_log. The shared Wave1LogStore models the term through
// its own birth event (plant_type_term_created) carrying the four planning
// fields; each probe folds its value back off that MATERIALIZED term state, not
// off any caller-held input. days_to_maturity / days_to_harvest deliver the
// recorded integer verbatim ("" when the term stated none — and they are
// separate fields, so a maturity never bleeds into a harvest). crop_family
// delivers the recorded family NAME ("" when none) and companion_plants the
// ordered companion NAMES ([] when none) — the names the wire delivers, never a
// per-run term id, so the readback reproduces across runs and ports. Nothing is
// stubbed. All four terms are BOUND (pack dba1550722fa632cd2bc0c2d2ca2c7d4), so
// port-verify scores them.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-identity-plant-type",
  operations: [],
  probes: [
    "days_to_maturity",
    "days_to_harvest",
    "crop_family",
    "companion_plants",
  ],
  makeStore: () => new Wave1LogStore({ replicaId: "W2P" }),
});
