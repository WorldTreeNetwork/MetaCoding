// port-verify bridge for the w2 animal_type build (shared term-family runtime).
// DECLARED (must match port.manifest.json exactly):
//   operations: create_term, update_term, delete_term
//   probes:     term_name, term_parent, term_status, term_weight,
//               term_vocabulary, term_depth, term_children, list_terms
import { runBridge } from "../shared-store/src/term_bridge.ts";
import { TaxonomyTermStore } from "../shared-store/src/term_store.ts";

await runBridge({
  port: "w2-animal_type",
  vocabulary: "animal_type",
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
  makeStore: () => new TaxonomyTermStore({ replicaId: "AT" }),
});
