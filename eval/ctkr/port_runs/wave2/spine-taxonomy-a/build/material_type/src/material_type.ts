// material_type vocabulary port — a pure taxonomy shell (farmOS module is one
// `taxonomy.vocabulary.material_type.yml`: "A list of material types"). No new
// field, fold, or workflow; the shared term spine bound to "material_type".
//
// Note: material_type terms are REFERENCED by other modules (quantity/material,
// asset/material) as an entity_reference target — but that reference lives on the
// referencing side, not here. This shell only owns the term vocabulary itself.
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/vocabulary_adapter.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

export function makeMaterialTypeAdapter(store?: TaxonomyTermStore): VocabularyAdapter {
  return makeVocabularyAdapter("material_type", store ?? new TaxonomyTermStore({ replicaId: "MT" }));
}
