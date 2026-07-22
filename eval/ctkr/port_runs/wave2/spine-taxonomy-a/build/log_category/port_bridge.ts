// port-verify bridge for the w2 log_category build (shared term-family runtime).
//
// DECLARED SURFACE IS THE TERM STORE ONLY. The module's `category`-field-on-logs
// and LogCategorize append/replace bulk action are PUNTED UP (see ./punts.jsonl)
// and are NOT reachable here — a categorize op would be refused unsupported:true,
// which is the correct signal that the fold was not ported at the spine tier.
import { runBridge } from "../shared-store/src/term_bridge.ts";
import { TaxonomyTermStore } from "../shared-store/src/term_store.ts";

await runBridge({
  port: "w2-log_category",
  vocabulary: "log_category",
  operations: ["create_term", "update_term", "delete_term"],
  probes: [
    "term_name",
    "term_parent",
    "term_status",
    "term_weight",
    "term_vocabulary",
    "term_depth",
    "term_children",
    "list_terms",
  ],
  makeStore: () => new TaxonomyTermStore({ replicaId: "LC" }),
});
