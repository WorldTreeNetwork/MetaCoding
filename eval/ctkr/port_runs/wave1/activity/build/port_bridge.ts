// port-verify bridge for the w1a activity build (shared wave-1 bridge runtime).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: record_log, set_log_status, set_effective_time, archive_asset
//   probes:     log_status, log_count, yield_total, quantity_recorded, asset_active
//
// KNOWN DIVERGENCE, deliberately NOT masked: log_count and yield_total are
// confirmed-only per the kernel STATUS_CONTRACT (decision pending-status-gates —
// the one CHOSEN divergence, MetaCoding-tkj), while the observed source counts
// pending logs in both. Fixtures exercising pending logs through these probes
// will fail against the recorded values; the pending mass is available in the
// port's pendingLogCount/pendingYieldTotal partners, which no glossary probe
// reads. Undeclarable as a manifest divergence today: the decision registry's
// text names the projections (yieldTotal/logCount) but not the glossary terms
// (yield_total/log_count), so decision_covers() cannot resolve it — reported as
// a wave friction.

import { runBridge } from "../../shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../shared-store/src/store.ts";

await runBridge({
  port: "w1a-activity",
  operations: ["record_log", "set_log_status", "set_effective_time", "archive_asset"],
  probes: ["log_status", "log_count", "yield_total", "quantity_recorded", "asset_active"],
  makeStore: () => new Wave1LogStore({ replicaId: "W1A" }),
});
