// animal_type vocabulary port — a pure taxonomy shell (farmOS module is one
// `taxonomy.vocabulary.animal_type.yml` and nothing else: "A list of animal
// species/breeds"). No new field, fold, or workflow; the whole semantic is the
// shared taxonomy-term spine bound to vocabulary "animal_type".
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/vocabulary_adapter.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

export function makeAnimalTypeAdapter(store?: TaxonomyTermStore): VocabularyAdapter {
  return makeVocabularyAdapter("animal_type", store ?? new TaxonomyTermStore({ replicaId: "AT" }));
}
