// port-verify bridge for the w2 spine-log-maintenance build (shared wave-1
// bridge runtime, imported not vendored).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: record_log, set_log_status, set_effective_time, archive_asset
//   probes:     log_status, log_count, yield_total, quantity_recorded, asset_active
//
// Every declared op/probe is genuinely served by the shared Wave1LogStore for
// kind="maintenance"; nothing here is stubbed. maintenance carries no bundle
// quantities in source, but yield_total/quantity_recorded remain declarable
// because the shared spine implements them generically (a maintenance log with
// no quantities simply folds to 0) — same surface activity declared.
//
// KNOWN DIVERGENCE, deliberately NOT masked: log_count and yield_total are
// confirmed-only per the kernel STATUS_CONTRACT (the one CHOSEN divergence,
// pending-status-gates / MetaCoding-tkj); the observed source counts pending
// logs in both. abandoned logs are likewise inert to these official numerics and
// surface only through pendingLogCount/pendingYieldTotal (decision w1a-5). This
// is spine-tier SMOKE: no oracle-observed maintenance fixtures were consulted, so
// no fixture_ids are asserted — trailing readings bind the recorded pack later.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-spine-log-maintenance",
  operations: ["record_log", "set_log_status", "set_effective_time", "archive_asset"],
  probes: ["log_status", "log_count", "yield_total", "quantity_recorded", "asset_active"],
  makeStore: () => new Wave1LogStore({ replicaId: "W2M" }),
});
