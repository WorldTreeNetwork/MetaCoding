/**
 * Hom-profile math + role-equivalence primitives (MetaCoding-23q.2).
 *
 * The Python side writes raw integer counts to hom_profiles.parquet at
 * maximal precision (see ctkr/ctkr/hom_profiles.py and
 * docs/notes/entropy-as-dial.md). This module exposes the read-side
 * primitives:
 *
 *  - cosineSimilarity / cosineDistance over profile vectors
 *  - l1Normalize for converting raw counts to a probability distribution
 *  - discretizeProfile for the granularity dial — bucket L1-normalised
 *    components into 1/k steps so callers can choose role-equivalence
 *    granularity at query time
 *
 * The KNN query itself lives on CtkrHandle.homProfilesKnn() in
 * artifacts.ts so it can be pushed into DuckDB.
 */

/**
 * Cosine similarity over raw integer count vectors. Returns 0 when either
 * vector has zero norm (no edges), so isolated symbols don't dominate
 * KNN results by spurious similarity to other isolates.
 */
export function cosineSimilarity(a: number[], b: number[]): number {
  if (a.length !== b.length) {
    throw new Error(
      `cosineSimilarity: dim mismatch ${a.length} vs ${b.length}`,
    );
  }
  let dot = 0;
  let na = 0;
  let nb = 0;
  for (let i = 0; i < a.length; i++) {
    const ai = a[i]!;
    const bi = b[i]!;
    dot += ai * bi;
    na += ai * ai;
    nb += bi * bi;
  }
  if (na === 0 || nb === 0) return 0;
  return dot / (Math.sqrt(na) * Math.sqrt(nb));
}

/** Cosine distance = 1 - cosineSimilarity. Range [0, 2] in general; [0, 1]
 *  when inputs are non-negative (which raw counts always are). */
export function cosineDistance(a: number[], b: number[]): number {
  return 1 - cosineSimilarity(a, b);
}

/**
 * L1-normalise counts to a probability distribution (sums to 1). Returns
 * the zero vector when the input has no edges — a no-signal symbol stays
 * no-signal rather than collapsing to a uniform distribution.
 */
export function l1Normalize(v: number[]): number[] {
  let s = 0;
  for (let i = 0; i < v.length; i++) s += v[i]!;
  if (s === 0) return v.map(() => 0);
  return v.map((x) => x / s);
}

/**
 * Bucket each L1-normalised component into 1/k steps — the granularity
 * dial from docs/notes/entropy-as-dial.md.
 *
 * Lower k → fewer buckets, coarser equivalence classes (closer profiles
 * collapse together). Higher k → finer buckets, more distinct classes.
 * k=1 maps every nonzero component to 1; k=∞ would be exact equality.
 *
 * Two profiles with the same discretized output at the same k are in the
 * same role-equivalence class at that granularity. Callers compare via
 * tuple equality on the returned arrays.
 */
export function discretizeProfile(profile: number[], k: number): number[] {
  if (k <= 0 || !Number.isFinite(k)) {
    throw new Error(`discretizeProfile: k must be a positive finite number, got ${k}`);
  }
  return profile.map((x) => Math.round(x * k) / k);
}

/**
 * Discretised L1-normalised profile, then serialised to a stable string —
 * the bucket key callers group by to find symbols in the same role class.
 *
 * Example: two profiles with bucket-2 keys "0|0.5|0|0.5|..." are
 * structurally equivalent at that granularity.
 */
export function profileBucketKey(rawCounts: number[], k: number): string {
  return discretizeProfile(l1Normalize(rawCounts), k).join("|");
}
