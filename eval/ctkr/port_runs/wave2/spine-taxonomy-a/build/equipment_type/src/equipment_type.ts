// equipment_type vocabulary port — a pure taxonomy shell (farmOS module is one
// `taxonomy.vocabulary.equipment_type.yml`: "A list of equipment types"). No new
// field, fold, or workflow; the shared term spine bound to "equipment_type".
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/vocabulary_adapter.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

export function makeEquipmentTypeAdapter(store?: TaxonomyTermStore): VocabularyAdapter {
  return makeVocabularyAdapter("equipment_type", store ?? new TaxonomyTermStore({ replicaId: "ET" }));
}
