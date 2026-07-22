// w2b — Test method vocabulary port, on the shared wave-2 taxonomy-vocabulary store.
//
// The farm_test_method module declares ONLY the 'test_method' vocabulary (name "Test method",
// see config/install/taxonomy.vocabulary.test_method.yml) and adds NO fields, values,
// measures, or workflow states (partition-2026-07-22.jsonl: vocab_new 0). So this
// port is the shared vocabulary adapter with vid "test_method" pinned — nothing more.

import {
  TaxonomyVocabStore,
  type Handle,
  type TermView,
} from "../../shared-store/src/store.ts";
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/adapter.ts";

export const TESTMETHOD_VID = "test_method" as const;

export type TestMethodTermHandle = Handle;
export type TestMethodTerm = TermView;
export type TestMethodAdapter = VocabularyAdapter;

export function makeTestMethodAdapter(
  store: TaxonomyVocabStore = new TaxonomyVocabStore({ replicaId: "W2B_TM" }),
): TestMethodAdapter {
  return makeVocabularyAdapter(TESTMETHOD_VID, store);
}
