/**
 * TypeScript row types for CTKR Layer-1 and Layer-3 artifacts.
 *
 * These mirror the pydantic models in:
 *   ctkr/ctkr/schema.py    (L1 — Parquet artifacts)
 *   ctkr/ctkr/schema_l3.py (L3 — JSONL artifacts)
 *
 * Column names and types are kept in sync with the Python source of truth.
 * Future bead MetaCoding-0pz will autogenerate these from JSON Schema.
 */

import type { EdgeKind } from "../store/types.ts";

// Re-export EdgeKind so consumers of this module have a single import surface.
export type { EdgeKind };

// ---------------------------------------------------------------------------
// Layer-1 Parquet row types
// ---------------------------------------------------------------------------

/** One symbol's embedding vector. Mirrors EmbeddingRow in schema.py. */
export interface EmbeddingRow {
  symbol_id: string;
  repo: string;
  qualified_name: string;
  /** float32 in Parquet; surfaced as number[] in TS. */
  vec: number[];
  schema_version: number;
}

/** One frequent typed subgraph. Mirrors MotifRow in schema.py. */
export interface MotifRow {
  motif_id: string;
  /** Canonical typed-edge-list serialization; join key into motif_instances. */
  signature: string;
  size_nodes: number;
  size_edges: number;
  /** Total corpus-wide occurrence count. */
  support: number;
  /** Repos containing at least one instance. */
  repo_coverage: string[];
  /** Distinct edge kinds present in the motif. */
  edge_kinds: EdgeKind[];
  schema_version: number;
}

/** One concrete occurrence of a motif. Mirrors MotifInstanceRow in schema.py. */
export interface MotifInstanceRow {
  motif_id: string;
  /** Anchor symbol — first node by signature order. */
  symbol_id: string;
  repo: string;
  file: string;
  line: number;
  schema_version: number;
}

/**
 * Persistent-homology shape signature for one (repo, homology-dim) pair.
 * Mirrors ShapePDRow in schema.py.
 *
 * birth[i] / death[i] are parallel arrays encoding persistence pairs.
 */
export interface ShapePDRow {
  repo: string;
  /** Homology dimension: 0, 1, or 2 typically. */
  dim: number;
  birth: number[];
  death: number[];
  schema_version: number;
}

/**
 * Pairwise topological distance between two repos.
 * Mirrors WassersteinH1Row in schema.py.
 *
 * Despite the name, the metric is the bottleneck (L∞-Wasserstein) distance
 * between H₁ persistence diagrams. Upper-triangle only (repo_a < repo_b).
 *
 * Note: wasserstein_h1.parquet in the wild may lack schema_version; treat it
 * as optional to match the pydantic default.
 */
export interface WassersteinH1Row {
  repo_a: string;
  repo_b: string;
  distance: number;
  schema_version?: number;
}

/** Per-symbol centrality scores. Mirrors CentralityRow in schema.py. */
export interface CentralityRow {
  symbol_id: string;
  repo: string;
  qualified_name: string;
  pagerank: number;
  betweenness: number;
  eigenvector: number;
  schema_version: number;
}

/** Per-symbol community assignment. Mirrors SpectralClusterRow in schema.py. */
export interface SpectralClusterRow {
  symbol_id: string;
  repo: string;
  qualified_name: string;
  /** Scoped to repo — not meaningful cross-repo. */
  cluster_id: number;
  cluster_size: number;
  schema_version: number;
}

/**
 * Metadata sidecar for the nn_index/ directory.
 * Mirrors NNIndexMeta in schema.py.
 */
export interface NNIndexMeta {
  backend: "faiss" | "hnswlib";
  metric: "cosine" | "l2" | "ip";
  embedding_dim: number;
  n_symbols: number;
  built_at: string; // ISO-8601
  /** Relative path to embeddings.parquet this index was built from. */
  embeddings_source: string;
  schema_version: number;
}

/** One row from nn_index labels (symbol_id at ordinal position). */
export interface NNLabelRow {
  ordinal: number;
  symbol_id: string;
}

/**
 * One symbol's hom-profile — raw integer edge counts by (kind, direction).
 * Mirrors HomProfileRow in schema.py (MetaCoding-23q.1).
 *
 * Counts are stored at maximal precision (UInt32 on disk). Callers re-
 * normalise / discretize at query time — see docs/notes/entropy-as-dial.md.
 * Dimension ordering: for each ek in EDGE_KINDS, (ek, "in") precedes
 * (ek, "out"); see DIMS in ctkr/hom_profiles.py.
 */
export interface HomProfileRow {
  symbol_id: string;
  repo: string;
  qualified_name: string;
  /** Length = 2 * EDGE_KINDS (28 today). Integer counts, no normalisation. */
  profile_vec: number[];
  schema_version: number;
}

/**
 * One discovered (approximate) functor `F : C_src → C_dst`.
 * Mirrors FunctorRow in schema.py (Phase 2b, MetaCoding §6 Task 3).
 *
 * Null semantics: metrics with no evidence are stored as the `-1.0` sentinel
 * (Parquet floats aren't nullable in this artifact set's convention) and are
 * surfaced as `null` by higher-level consumers. `fidelity` is `-1` when
 * `n_edges_internal === 0` (edgeless domain — must NOT read as perfect 1.0);
 * `path_fidelity_2` is `-1` when not computed; `cycle_consistency` is `-1`
 * when the reverse-direction functor wasn't computed.
 */
export interface FunctorRow {
  /** Content-addressed: hash of (repo_src, repo_dst, config, mapping digest). */
  functor_id: string;
  repo_src: string;
  repo_dst: string;
  n_objects_src: number;
  n_mapped: number;
  coverage: number;
  /** n_edges_preserved / n_edges_internal; -1 when n_edges_internal === 0. */
  fidelity: number;
  n_edges_internal: number;
  n_edges_preserved: number;
  /** Sampled 2-path composition diagnostic; -1 if not computed. */
  path_fidelity_2: number;
  /** Fraction of s with G(F(s)) = s; -1 if reverse not computed. */
  cycle_consistency: number;
  /** JSON blob of the search config + runtime metadata. */
  config: string;
  generated_at: string; // ISO-8601
  schema_version: number;
}

/**
 * One object↦object correspondence — a weighted meta-graph edge (Phase 2c).
 * Mirrors FunctorEdgeRow in schema.py.
 *
 * `pair_fidelity` is `-1` when the source has no internal incident edges (no
 * structural evidence — consumers must NOT read as 1.0). Low `margin` = the
 * assignment was a near-coin-flip among lookalikes.
 */
export interface FunctorEdgeRow {
  functor_id: string;
  src_symbol_id: string;
  src_repo: string;
  src_qualified_name: string;
  dst_symbol_id: string;
  dst_repo: string;
  dst_qualified_name: string;
  /** Converged (pre-normalization) propagation score σ. */
  similarity: number;
  /** σ gap to best unaccepted alternative for this source. */
  margin: number;
  /** preserved/total internal incident edges; -1 = no evidence. */
  pair_fidelity: number;
  n_edges_incident: number;
  n_edges_preserved: number;
  schema_version: number;
}

/**
 * Top-level presence manifest for .metacoding/ctkr/.
 * Mirrors ArtifactManifest in schema.py.
 */
export interface ArtifactManifest {
  schema_version: number;
  generated_at: string; // ISO-8601
  metacoding_data_dir: string;
  embeddings: boolean;
  motifs: boolean;
  motif_instances: boolean;
  shape_pds: boolean;
  wasserstein_h1: boolean;
  centrality: boolean;
  spectral_clusters: boolean;
  nn_index: boolean;
  hom_profiles: boolean;
  functors: boolean;
  functor_edges: boolean;
  embedding_dim: number | null;
  profile_vec_dim: number | null;
  /** Hom-profile neighbourhood depth the seeds were built at (1 or 2). */
  profile_depth?: number | null;
  n_symbols: number;
  n_motifs: number;
  n_motif_instances: number;
  n_hom_profiles: number;
  n_functors: number;
  n_functor_edges: number;
  notes: string | null;
  /** Forward-compat: extra keys from future schema versions round-trip. */
  [extra: string]: unknown;
}

// ---------------------------------------------------------------------------
// Layer-3 JSONL row types
// ---------------------------------------------------------------------------

/** Inclusive line span in a source file. Mirrors LineRange in schema_l3.py. */
export interface LineRange {
  start: number;
  end: number;
}

/**
 * One snippet of source evidence for a labeled pattern.
 * Mirrors EvidenceRow in schema_l3.py.
 */
export interface EvidenceRow {
  pattern_id: string;
  repo: string;
  file: string;
  line_range: LineRange;
  snippet: string;
  context: string | null;
  schema_version: number;
}

/**
 * One labeled structural element produced by an L3 labeler.
 * Mirrors PatternRow in schema_l3.py.
 */
export interface PatternRow {
  pattern_id: string;
  source_kind: "motif" | "role-cluster" | "analogy";
  source_ref: string;
  label: string;
  description: string;
  instances: string[];
  evidence_ids: string[];
  confidence: number;
  llm_model: string;
  llm_temperature: number;
  prompt_version: string;
  schema_version: number;
  generated_at: string; // ISO-8601
}
