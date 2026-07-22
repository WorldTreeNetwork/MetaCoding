// port-verify bridge for the w1b observation build (shared wave-1 bridge
// runtime). Same declared log-family surface as w1a — observation is the
// control group: its verified semantics ARE the shared log spine.
//
// Same undeclarable chosen divergence as w1a: log_count / yield_total are
// confirmed-only per the kernel STATUS_CONTRACT while the observed source
// counts pending (observation/scope.md post-observation note records exactly
// this contradiction). See the w1a bridge header and the wave friction log.

import { runBridge } from "../../shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../shared-store/src/store.ts";
import { OBSERVATION_KINDS } from "./src/observation.ts";

await runBridge({
  port: "w1b-observation",
  operations: ["record_log", "set_log_status", "set_effective_time", "archive_asset"],
  probes: ["log_status", "log_count", "yield_total", "quantity_recorded", "asset_active"],
  makeStore: () => new Wave1LogStore({ replicaId: "W1B", extraKinds: OBSERVATION_KINDS }),
});
