// The thin per-feature surface for the spine-taxonomy-b family. Every one of the
// four features (product_type / season / test_method / unit) is the SAME
// vocabulary adapter with its `vid` pinned — the modules differ only in which
// vocabulary the terms live in (partition vocab_new 0). Feature src files wrap
// this and re-export it under feature-named types so a reader sees the boundary.

import { TaxonomyVocabStore, type Handle, type TermView } from "./store.ts";

export type TermHandle = Handle;

export interface VocabularyAdapter {
  readonly vid: string;
  readonly store: TaxonomyVocabStore;
  /** the vocabulary's human label, from install config (never invented). */
  vocabularyName(): string | undefined;
  addTerm(input: { name: string; description?: string; weight?: number }): TermHandle;
  renameTerm(term: TermHandle, name: string): void;
  describeTerm(term: TermHandle, description?: string): void;
  reweightTerm(term: TermHandle, weight: number): void;
  removeTerm(term: TermHandle): void;
  term(term: TermHandle): TermView | undefined;
  /** live terms in Drupal default order (weight asc, name asc, HLC tie-break). */
  terms(): readonly TermView[];
  termCount(): number;
}

export function makeVocabularyAdapter(
  vid: string,
  store: TaxonomyVocabStore = new TaxonomyVocabStore(),
): VocabularyAdapter {
  if (!store.hasVocabulary(vid)) {
    throw new Error(`store has no vocabulary registered under vid ${vid}`);
  }
  return {
    vid,
    store,
    vocabularyName: () => store.vocabularyName(vid),
    addTerm: (input) => store.createTerm({ vocab: vid, ...input }),
    renameTerm: (term, name) => store.renameTerm(term, name),
    describeTerm: (term, description) => store.setTermDescription(term, description),
    reweightTerm: (term, weight) => store.setTermWeight(term, weight),
    removeTerm: (term) => store.deleteTerm(term),
    term: (term) => {
      const v = store.termView(term);
      return v && v.vocab === vid ? v : undefined;
    },
    terms: () => store.listTerms(vid),
    termCount: () => store.termCount(vid),
  };
}
