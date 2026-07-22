// The four spine-taxonomy-b vocabulary descriptors, transcribed VERBATIM from the
// modules' install config (the only thing these modules contribute):
//
//   modules/taxonomy/product_type/config/install/taxonomy.vocabulary.product_type.yml
//   modules/taxonomy/season/config/install/taxonomy.vocabulary.season.yml
//   modules/taxonomy/test_method/config/install/taxonomy.vocabulary.test_method.yml
//   modules/taxonomy/unit/config/install/taxonomy.vocabulary.unit.yml
//
// Each yml declares exactly: vid, name, description, weight, new_revision:false.
// No fields, no third-party settings — this IS the whole feature (partition
// vocab_new 0). `new_revision:false` is recorded here for fidelity but is inert
// in the spine store (term revisioning is a core-taxonomy concern, out of scope).

export interface VocabularySpec {
  vid: string;
  name: string;
  description: string;
  weight: number;
  newRevision: boolean;
}

export const VOCABULARIES: readonly VocabularySpec[] = [
  { vid: "product_type", name: "Product type", description: "A list of product types.", weight: 0, newRevision: false },
  { vid: "season", name: "Season", description: "A list of seasons.", weight: 0, newRevision: false },
  { vid: "test_method", name: "Test method", description: "A list of test methods.", weight: 0, newRevision: false },
  { vid: "unit", name: "Unit", description: "A list of units for measurement purposes.", weight: 0, newRevision: false },
];

export function vocabularyByVid(vid: string): VocabularySpec | undefined {
  return VOCABULARIES.find((v) => v.vid === vid);
}
