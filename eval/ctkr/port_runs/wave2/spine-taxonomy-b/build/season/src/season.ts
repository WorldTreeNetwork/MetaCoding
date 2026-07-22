// w2b — Season vocabulary port, on the shared wave-2 taxonomy-vocabulary store.
//
// The farm_season module declares ONLY the 'season' vocabulary (name "Season",
// see config/install/taxonomy.vocabulary.season.yml) and adds NO fields, values,
// measures, or workflow states (partition-2026-07-22.jsonl: vocab_new 0). So this
// port is the shared vocabulary adapter with vid "season" pinned — nothing more.

import {
  TaxonomyVocabStore,
  type Handle,
  type TermView,
} from "../../shared-store/src/store.ts";
import {
  makeVocabularyAdapter,
  type VocabularyAdapter,
} from "../../shared-store/src/adapter.ts";

export const SEASON_VID = "season" as const;

export type SeasonTermHandle = Handle;
export type SeasonTerm = TermView;
export type SeasonAdapter = VocabularyAdapter;

export function makeSeasonAdapter(
  store: TaxonomyVocabStore = new TaxonomyVocabStore({ replicaId: "W2B_SE" }),
): SeasonAdapter {
  return makeVocabularyAdapter(SEASON_VID, store);
}
