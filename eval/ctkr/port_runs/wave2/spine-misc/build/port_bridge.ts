// port-verify bridge for the wave-2 spine-misc quantity/standard build.
// Reuses the shared wave-1 bridge runtime (one JSON object per line; the
// ctkr.oracle.port_adapter line protocol). `standard` adds no operation and no
// probe of its own — it is the identity quantity bundle, so its surface is a
// subset of the shared quantity-spine surface, declared honestly.
//
// DECLARED (must match port.manifest.json exactly):
//   operations: record_log, set_log_status, set_effective_time
//   probes:     log_status, log_count, yield_total, quantity_recorded
//
// KNOWN DIVERGENCE, deliberately NOT masked (inherited from the shared store,
// same as the whole wave-1 log family): yield_total and log_count are
// confirmed-only per the kernel STATUS_CONTRACT (the ONE chosen divergence,
// decision pending-status-gates / MetaCoding-tkj), while the observed source
// counts pending logs in both. The excluded pending mass is available in the
// store's pendingLogCount / pendingYieldTotal partners, which no glossary probe
// reads. No fixture_ids are fabricated here (spine-tier smoke, no oracle
// contact this run); trailing readings will record the divergence against real
// packs.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-quantity-standard",
  operations: ["record_log", "set_log_status", "set_effective_time"],
  probes: ["log_status", "log_count", "yield_total", "quantity_recorded"],
  makeStore: () => new Wave1LogStore({ replicaId: "W2SM" }),
});
