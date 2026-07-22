// w2b — Unit vocabulary port, on the shared wave-2 taxonomy-vocabulary store.
//
// The farm_unit module declares ONLY the 'unit' vocabulary (name "Unit",
// see config/install/taxonomy.vocabulary.unit.yml) and adds NO fields, values,
// measures, or workflow states (partition-2026-07-22.jsonl: vocab_new 0). So this
// port is the shared vocabulary adapter with vid "unit" pinned — nothing more.

import {
  TaxonomyVocabStore,
  type Handle,
  type TermView,
} from "../../shared-store/src/store.ts";
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/adapter.ts";

export const UNIT_VID = "unit" as const;

export type UnitTermHandle = Handle;
export type UnitTerm = TermView;
export type UnitAdapter = VocabularyAdapter;

export function makeUnitAdapter(
  store: TaxonomyVocabStore = new TaxonomyVocabStore({ replicaId: "W2B_UN" }),
): UnitAdapter {
  return makeVocabularyAdapter(UNIT_VID, store);
}
