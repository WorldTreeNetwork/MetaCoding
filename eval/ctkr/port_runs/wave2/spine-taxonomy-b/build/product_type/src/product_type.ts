// w2b — Product type vocabulary port, on the shared wave-2 taxonomy-vocabulary store.
//
// The farm_product_type module declares ONLY the 'product_type' vocabulary (name "Product type",
// see config/install/taxonomy.vocabulary.product_type.yml) and adds NO fields, values,
// measures, or workflow states (partition-2026-07-22.jsonl: vocab_new 0). So this
// port is the shared vocabulary adapter with vid "product_type" pinned — nothing more.

import {
  TaxonomyVocabStore,
  type Handle,
  type TermView,
} from "../../shared-store/src/store.ts";
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/adapter.ts";

export const PRODUCTTYPE_VID = "product_type" as const;

export type ProductTypeTermHandle = Handle;
export type ProductTypeTerm = TermView;
export type ProductTypeAdapter = VocabularyAdapter;

export function makeProductTypeAdapter(
  store: TaxonomyVocabStore = new TaxonomyVocabStore({ replicaId: "W2B_PT" }),
): ProductTypeAdapter {
  return makeVocabularyAdapter(PRODUCTTYPE_VID, store);
}
