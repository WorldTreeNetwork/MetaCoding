// port-verify bridge for the w1d input build (shared wave-1 bridge runtime).
//
// DECLARED surface follows the w1d flow pack exactly: no archive_asset and no
// asset_active (no input flow archives or probes activity). Same undeclarable
// chosen divergence as the rest of the family on yield_total / log_count
// (confirmed-only per the kernel STATUS_CONTRACT; the source counts pending) —
// see the wave friction log.

import { runBridge } from "../../shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../shared-store/src/store.ts";

await runBridge({
  port: "w1d-input",
  operations: ["record_log", "set_log_status", "set_effective_time"],
  probes: ["log_status", "log_count", "yield_total", "quantity_recorded"],
  makeStore: () => new Wave1LogStore({ replicaId: "W1D" }),
});
