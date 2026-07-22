// log_category vocabulary port — the TERM-STORE SHELL only.
//
// The farmOS farm_log_category module is NOT a pure taxonomy shell (the way the
// other four in this cluster are). It has three parts:
//   1. taxonomy.vocabulary.log_category.yml — the vocabulary itself. SPINE. This
//      shell owns it: term entities with editable name/parent/weight/status.
//   2. src/Hook/FieldHooks.php — injects a `category` entity_reference base field
//      (multi-valued, target log_category terms) onto EVERY log entity. That is a
//      cross-cutting field on the LOG family, not the term store.
//   3. src/Plugin/Action/LogCategorize.php (+ LogCategorizeActionForm) — a bulk
//      action that adds categories to selected logs with APPEND-or-REPLACE merge
//      semantics and array_unique de-duplication.
//
// Parts 2 and 3 are a genuine domain fold the vocabulary scan (which tiered this
// module SPINE on vid-already-in-glossary) never opened. They are PUNTED UP —
// see ./punts.jsonl. This build deliberately implements ONLY part 1, and its
// port manifest declares ONLY term operations — the categorize workflow is NOT
// claimed here (an honest gap, not a masked one).
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/vocabulary_adapter.ts";
import { TaxonomyTermStore } from "../../shared-store/src/term_store.ts";

export function makeLogCategoryAdapter(store?: TaxonomyTermStore): VocabularyAdapter {
  return makeVocabularyAdapter("log_category", store ?? new TaxonomyTermStore({ replicaId: "LC" }));
}
