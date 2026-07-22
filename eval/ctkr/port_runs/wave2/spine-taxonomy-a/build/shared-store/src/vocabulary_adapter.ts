// The thin per-vocabulary surface over the shared TaxonomyTermStore. Every
// spine-taxonomy-a feature is one of these bound to a fixed vocabulary — there is
// no per-vocabulary behavior in this cluster (the five farmOS modules are pure
// vocabulary shells: a `taxonomy.vocabulary.<vid>.yml` and nothing else), so the
// adapter carries zero feature-specific logic. That sameness is the finding: the
// vocabulary scan tiered them SPINE precisely because they add no new fold.
//
// (log_category is the exception — it ALSO injects a `category` field onto logs
// and a categorize action. That fold is punted up; see build/log_category. This
// adapter is only the term-store shell, which log_category genuinely shares.)

import {
  TaxonomyTermStore,
  type Handle,
  type Vocabulary,
  type TermInput,
  type TermPatch,
  type TermView,
} from "./term_store.ts";

export interface VocabularyAdapter {
  readonly vocabulary: Vocabulary;
  readonly store: TaxonomyTermStore;
  createTerm(input: TermInput): Handle;
  updateTerm(term: Handle, patch: TermPatch): void;
  deleteTerm(term: Handle): void;
  term(term: Handle): TermView | undefined;
  /** Only terms in THIS vocabulary are visible (bundle scoping). */
  listTerms(opts?: { activeOnly?: boolean }): TermView[];
  roots(opts?: { activeOnly?: boolean }): TermView[];
  children(parent: Handle): TermView[];
  depth(term: Handle): number;
  ancestors(term: Handle): TermView[];
}

export function makeVocabularyAdapter(
  vocabulary: Vocabulary,
  store: TaxonomyTermStore = new TaxonomyTermStore(),
): VocabularyAdapter {
  return {
    vocabulary,
    store,
    createTerm: (input) => store.createTerm(vocabulary, input),
    updateTerm: (term, patch) => store.updateTerm(term, patch),
    deleteTerm: (term) => store.deleteTerm(term),
    term: (term) => {
      const v = store.termView(term);
      // bundle scoping: a handle from another vocabulary is not visible here.
      return v && v.vocabulary === vocabulary ? v : undefined;
    },
    listTerms: (opts) => store.termsInVocabulary(vocabulary, opts),
    roots: (opts) => store.rootsOf(vocabulary, opts),
    children: (parent) => store.childrenOf(parent),
    depth: (term) => store.depthOf(term),
    ancestors: (term) => store.ancestorsOf(term),
  };
}
