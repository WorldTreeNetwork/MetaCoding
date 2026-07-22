// port-verify bridge for the w2 identity-equipment-log build (shared wave-1
// bridge runtime, imported not vendored).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: record_log, set_log_status, set_effective_time, archive_asset
//   probes:     equipment_used, log_status, log_count, asset_active
//
// equipment_used is genuinely served by the shared Wave1LogStore: record_log
// carries the oracle's `equipment` handles onto the log_recorded event and the
// probe folds membership off the materialized view (the has_parent house
// form). Nothing here is stubbed. The term is BOUND (pack 1e1a8c55b7f5), so
// port-verify scores it.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-identity-equipment-log",
  operations: ["record_log", "set_log_status", "set_effective_time", "archive_asset"],
  probes: ["equipment_used", "log_status", "log_count", "asset_active"],
  makeStore: () => new Wave1LogStore({ replicaId: "W2E" }),
});
