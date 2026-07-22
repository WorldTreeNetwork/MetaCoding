// Wave-2 taxonomy-vocabulary closed kind taxonomy — the ONE shared store shape
// all four spine-taxonomy-b features (product_type / season / test_method / unit)
// fold through. None of these leaf modules add event kinds beyond the stock
// taxonomy-term lifecycle: a term is created into a vocabulary, its core fields
// (name / description / weight) are restated latest-wins, and it is deleted.
//
// The four vocabularies are NOT event kinds — they are the `vocab` FIELD of a
// term_created payload (exactly as the wave-1 log family made activity/observation
// the `kind` field of a log). Vocabulary descriptors live in vocabularies.ts.

import {
  KindRegistry,
  type KindSpec,
} from "../../../../../../../../src/kernel/index.ts";

/** Kinds shared by the whole spine-taxonomy-b vocabulary family. */
export const TAXONOMY_CORE_KINDS: readonly KindSpec[] = [
  { kind: "term_created", family: "term", isLog: false, description: "births a taxonomy term into a vocabulary (name/description/weight)" },
  { kind: "term_renamed", family: "term", isLog: false, description: "latest-wins restatement of a term's name" },
  { kind: "term_redescribed", family: "term", isLog: false, description: "latest-wins restatement of a term's description" },
  { kind: "term_reweighted", family: "term", isLog: false, description: "latest-wins restatement of a term's Drupal core weight" },
  { kind: "term_deleted", family: "lifecycle", isLog: false, description: "deletion of a taxonomy term; drops it from every projection" },
];

/**
 * The frozen registry for a spine-taxonomy-b store. A feature may pass its own
 * declared extension; registration happens BEFORE freeze, per the kernel rule.
 */
export function makeTaxonomyRegistry(extra: readonly KindSpec[] = []): KindRegistry {
  return new KindRegistry().extend(TAXONOMY_CORE_KINDS).extend(extra).freeze();
}
