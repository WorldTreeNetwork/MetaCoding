// port-verify bridge for the w2 identity-material-quantity-fold build (shared
// wave-1 bridge runtime, imported not vendored).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: record_log, set_log_status, set_effective_time, archive_asset
//   probes:     material_type_recorded, log_status, log_count, asset_active
//
// material_type_recorded is genuinely served by the shared Wave1LogStore: the
// bridge normalizes the wire's `bundle`/`inventory_asset` onto the quantity,
// recordLog applies the materialFold (the source's quantity_presave copy,
// snapshot-at-record), and the probe folds the first material quantity's
// names off the materialized view. Nothing here is stubbed. Both terms are
// BOUND (pack 046155d7d243), so port-verify scores them.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-identity-material-quantity-fold",
  operations: ["record_log", "set_log_status", "set_effective_time", "archive_asset"],
  probes: ["material_type_recorded", "log_status", "log_count", "asset_active"],
  makeStore: () => new Wave1LogStore({ replicaId: "W2M" }),
});
