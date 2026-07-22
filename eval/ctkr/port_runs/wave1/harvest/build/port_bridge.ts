// port-verify bridge for the w1c harvest build (shared wave-1 bridge runtime).
//
// DECLARED surface follows the w1c flow pack exactly: no archive_asset (no
// harvest flow archives), asset_active IS declared (the pack probes it).
// Same undeclarable chosen divergence as the rest of the family: yield_total /
// log_count are confirmed-only per the kernel STATUS_CONTRACT while the source
// counts pending harvests (73ed7c69 / d8607818 — records of the source, never
// rewritten). See the wave friction log for why the manifest cannot carry the
// divergence declaration yet.

import { runBridge } from "../../shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../shared-store/src/store.ts";
import { HARVEST_KINDS } from "./src/harvest.ts";

await runBridge({
  port: "w1c-harvest",
  operations: ["record_log", "set_log_status", "set_effective_time"],
  probes: ["log_status", "log_count", "yield_total", "quantity_recorded", "asset_active"],
  makeStore: () => new Wave1LogStore({ replicaId: "W1C", extraKinds: HARVEST_KINDS }),
});
