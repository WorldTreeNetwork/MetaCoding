// lab vocabulary port — a pure taxonomy shell (farmOS module is one
// `taxonomy.vocabulary.lab.yml`: "A list of labs"). No new field, fold, or
// workflow; the shared term spine bound to "lab".
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/vocabulary_adapter.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

export function makeLabAdapter(store?: TaxonomyTermStore): VocabularyAdapter {
  return makeVocabularyAdapter("lab", store ?? new TaxonomyTermStore({ replicaId: "LAB" }));
}
