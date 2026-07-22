// port-verify bridge for the w2b product_type build (shared wave-2 taxonomy bridge
// runtime). Vocabulary vid "product_type" is pinned; every op/probe is scoped to it.
//
// DECLARED (must match port.manifest.json exactly):
//   operations: create_term, rename_term, set_term_description, set_term_weight, delete_term
//   probes:     term_name, term_description, term_weight, term_count, list_terms, vocabulary_name
//
// DECLARED GAP (not masked): term hierarchy (parent/children) is a core-taxonomy
// fold not introduced by farm_product_type; no probe reads or claims it. See
// punts.jsonl (b-shared-1). Any hierarchy fixture is out of this port's surface.

import { runBridge } from "../shared-store/src/bridge.ts";
import { TaxonomyVocabStore } from "../shared-store/src/store.ts";

await runBridge({
  port: "w2b-product-type",
  vocab: "product_type",
  operations: ["create_term","rename_term","set_term_description","set_term_weight","delete_term"],
  probes: ["term_name","term_description","term_weight","term_count","list_terms","vocabulary_name"],
  makeStore: () => new TaxonomyVocabStore({ replicaId: "W2B_PT" }),
});
