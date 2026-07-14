/**
 * CTKR Phase 1 MCP tool implementations.
 *
 * Five typed tools over the Layer-1 artifacts:
 *   ctkr.motif_search     — search frequent typed subgraphs
 *   ctkr.nearest_symbols  — brute-force cosine KNN over embeddings
 *   ctkr.pattern_search   — search L3 labeled patterns + evidence
 *   ctkr.shape_distance   — topological distance between repos
 *   ctkr.centrality_query — centrality scores joined with spectral clusters
 *
 * Each handler opens a CtkrHandle, runs its query, and closes the handle.
 * The data dir is resolved from the METACODING_CTKR_DATA_DIR environment
 * variable (the path to .metacoding/). The variable is mandatory — there is
 * no implicit corpus fallback. Tests that need a corpus read ORCHESTRATORS_ROOT
 * (default ~/projects/Orchestrators) to locate one.
 *
 * server.ts calls registerCtkrTools(server) to wire these into the MCP server.
 */

import { join } from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { openCtkrArtifacts } from "../ctkr/artifacts.ts";
import { EDGE_KIND_VALUES } from "../store/types.ts";
import type { ToolDescription } from "./tools.ts";
import type {
  ArtifactManifest,
  CentralityRow,
  DataShapeRow,
  EdgeKind,
  EvidenceRow,
  FunctorRow,
  InterfaceRow,
  MotifRow,
  OperadRow,
  PatternRow,
  SpectralClusterRow,
  SubsystemCard,
  SubsystemMemberRow,
  WassersteinH1Row,
} from "../ctkr/types.ts";

// ---------------------------------------------------------------------------
// Data dir resolution
// ---------------------------------------------------------------------------

function resolveCtkrDataDir(): string {
  const env = process.env["METACODING_CTKR_DATA_DIR"];
  if (env) return env;
  throw new Error(
    "METACODING_CTKR_DATA_DIR is not set. CTKR MCP tools require an explicit " +
      "data directory pointing at .metacoding/ — set the env var before starting " +
      "the MCP server.",
  );
}

// ---------------------------------------------------------------------------
// Output shapes
// ---------------------------------------------------------------------------

/** MotifRow joined with its L3 label if one exists. */
export interface MotifWithLabel extends MotifRow {
  label?: string;
  label_description?: string;
  label_confidence?: number;
}

/** KNN result row for ctkr.nearest_symbols. */
export interface NearestSymbolRow {
  symbol_id: string;
  qualified_name: string;
  repo: string;
  distance: number;
}

/** KNN result row for ctkr.role_equivalent. */
export interface RoleEquivalentRow {
  symbol_id: string;
  qualified_name: string;
  repo: string;
  /** Cosine distance over raw hom-profile vectors. Range [0, 1] (counts are non-negative). */
  hom_profile_distance: number;
}

/** PatternRow with its evidence array attached. */
export interface PatternWithEvidence extends PatternRow {
  evidence: EvidenceRow[];
}

/** Single pairwise shape distance result. `distance` is `null` if the pair is
 *  not present in the wasserstein table. */
export interface ShapeDistancePair {
  repo_a: string;
  repo_b: string;
  distance: number | null;
}

/** Centrality row joined with spectral cluster fields. */
export interface CentralityResult {
  symbol_id: string;
  qualified_name: string;
  repo: string;
  score: number;
  cluster_id?: number;
  cluster_size?: number;
  /** Caveat note (e.g. "kind filter not applied in v1"). Attached to the
   *  first result only when present. */
  _note?: string;
}

/** Functor-level summary for ctkr.functor_between (§4). One directed run. */
export interface FunctorSummary {
  functor_id: string;
  repo_src: string;
  repo_dst: string;
  coverage: number;
  fidelity: number;
  n_mapped: number;
  n_objects_src: number;
  /** Sampled 2-path composition diagnostic; omitted when not computed (−1). */
  path_fidelity_2?: number;
  /**
   * Fraction of committed mappings that are coin-flip ties (MetaCoding-265).
   * High (~0.9 on real code) = the per-symbol mapping is an aggregate-only
   * signal: coverage/fidelity/cycle-consistency stay meaningful, the individual
   * symbol↦symbol rows are unreliable and must not be read as correspondences.
   */
  ambiguity_mass: number;
  generated_at: string;
}

/** One object↦object correspondence row returned by ctkr.functor_between. */
export interface FunctorMappingRow {
  src_symbol_id: string;
  src_qualified_name: string;
  dst_symbol_id: string;
  dst_qualified_name: string;
  similarity: number;
  /** Assignment confidence — low = coin-flip among lookalikes. */
  margin: number;
  /** True = near-tie coin-flip (MetaCoding-265); discount this per-symbol row. */
  is_ambiguous: boolean;
  /** null = no structural evidence (isolated pair); never read as 1.0. */
  pair_fidelity: number | null;
}

/** Result shape for ctkr.functor_between (§4). */
export interface FunctorBetweenResult {
  /** null when the pair has no artifact row passing the filters. */
  functor: FunctorSummary | null;
  /** B→A summary; present only when direction="both". */
  reverse?: FunctorSummary | null;
  /** filtered + truncated correspondence rows for the primary direction. */
  mapping: FunctorMappingRow[];
  /** Count of returned mapping rows flagged is_ambiguous (coin-flip ties). */
  n_ambiguous: number;
  truncated: boolean;
  /** Explanatory landscape note (alternatives, best-available, staleness, …). */
  _note?: string;
}

/** One subsystem summary with boundary-confidence metadata (ctkr.subsystems). */
export interface SubsystemResult {
  subsystem_id: string;
  repo: string;
  n_members: number;
  resolution: number;
  /** Mean pairwise co-association of members across the resolution sweep. */
  persistence_score: number;
  /** Count of members placed by directory locality (zero-profile symbols). */
  n_locality: number;
  /** Count of members placed structurally (carry typed-edge signal). */
  n_structural: number;
  /** Mean member boundary_confidence. */
  mean_boundary_confidence: number;
  /**
   * The lowest-boundary-confidence members — the judgment-call assignments a
   * re-implementer must scrutinise (a subset; up to `boundary_sample`).
   */
  boundary_symbols: Array<{
    symbol_id: string;
    qualified_name: string;
    boundary_confidence: number;
    placement: "structural" | "locality";
  }>;
}

/** Result shape for ctkr.subsystems. */
export interface SubsystemsResult {
  subsystems: SubsystemResult[];
  /** Partition config JSON (resolution sweep, weights, seed) — same for all rows. */
  config: string | null;
  _note?: string;
}

/** Result shape for ctkr.interface_of (§3 / §8.2, T2). The subsystem's raw
 *  contract rows, for programmatic consumers, plus rolled-up summaries. */
export interface InterfaceOfResult {
  subsystem_id: string;
  repo: string | null;
  /** provides rows (external → internal), unless direction="consumes". */
  provides: InterfaceRow[];
  /** consumes rows (internal → external), unless direction="provides". */
  consumes: InterfaceRow[];
  /** Distinct top-level exports referenced across the boundary (the API surface). */
  provides_exports: string[];
  /** Distinct target subsystems this one depends on (the dependency topology);
   *  "(external)" = an unpartitioned/external-package target. */
  consumes_subsystems: string[];
  /** Data shapes crossing (boundary) or private to (internal) the subsystem. */
  data_shapes: DataShapeRow[];
  n_boundary_shapes: number;
  n_internal_shapes: number;
  /** Per-lane data-alphabet coverage note (§3) for this subsystem's repo. */
  alphabet_coverage: Record<string, unknown> | null;
  truncated: boolean;
  _note?: string;
}

/** Result shape for ctkr.composition_rules (§4.3 / §8.2, T4). A subsystem's
 *  composition algebra — its operations, laws, and protocol contract. */
export interface CompositionRulesResult {
  subsystem_id: string;
  repo: string | null;
  /** Which role quotient the operations were projected through. */
  view: "orbit" | "similarity";
  /** The recovered operations (path + fan_in), strongest/protocol first. */
  operations: OperadRow[];
  /** Recorded law violations (op_kind="non_operadic"): the composition non-laws. */
  violations: OperadRow[];
  /** Distinct role_ids appearing on the boundary (protocol) operations — the
   *  order-of-operations contract external callers depend on. */
  protocol_roles: string[];
  n_operations: number;
  n_boundary_ops: number;
  n_missing_composite: number;
  n_back_call_cycle: number;
  truncated: boolean;
  _note?: string;
}

// ---------------------------------------------------------------------------
// Zod schemas
// ---------------------------------------------------------------------------

const EDGE_KIND_SCHEMA = z.enum(EDGE_KIND_VALUES);

const MOTIF_SEARCH_SCHEMA = {
  min_support: z.number().int().min(1).optional(),
  edge_kinds: z.array(EDGE_KIND_SCHEMA).optional(),
  repo_coverage_min: z.number().int().min(1).optional(),
  label: z.string().optional(),
  limit: z.number().int().min(1).max(1000).optional(),
};

const NEAREST_SYMBOLS_SCHEMA = {
  symbol_id: z.string().optional(),
  qualified_name: z.string().optional(),
  k: z.number().int().min(1).max(500).optional(),
  cross_repo_only: z.boolean().optional(),
  embedding_kind: z.string().optional(),
};

const PATTERN_SEARCH_SCHEMA = {
  label: z.string().optional(),
  source_kind: z.string().optional(),
  min_confidence: z.number().min(0).max(1).optional(),
  instances_in_repo: z.string().optional(),
  limit: z.number().int().min(1).max(1000).optional(),
};

const SHAPE_DISTANCE_SCHEMA = {
  repo_a: z.string().min(1),
  repo_b: z.string().optional(),
  k_nearest: z.number().int().min(1).max(200).optional(),
};

const CENTRALITY_QUERY_SCHEMA = {
  repo: z.string().optional(),
  kind: z.string().optional(),
  top_k: z.number().int().min(1).max(10000).optional(),
  metric: z.enum(["pagerank", "betweenness", "eigenvector"]),
};

const ROLE_EQUIVALENT_SCHEMA = {
  symbol_id: z.string().optional(),
  qualified_name: z.string().optional(),
  k: z.number().int().min(1).max(500).optional(),
  scope: z.string().optional(),
  cross_repo_only: z.boolean().optional(),
};

const SUBSYSTEMS_SCHEMA = {
  repo: z.string().optional(),
  resolution: z.number().optional(),
  min_persistence: z.number().min(0).max(1).optional(),
  boundary_sample: z.number().int().min(0).max(200).optional(),
};

const INTERFACE_OF_SCHEMA = {
  subsystem: z.string().min(1),
  repo: z.string().optional(),
  direction: z.enum(["provides", "consumes"]).optional(),
  boundary_shapes_only: z.boolean().optional(),
  limit: z.number().int().min(1).max(5000).optional(),
};

const COMPOSITION_RULES_SCHEMA = {
  subsystem: z.string().optional(),
  repo: z.string().optional(),
  view: z.enum(["orbit", "similarity"]).optional(),
  op_kind: z.enum(["path", "fan_in", "non_operadic"]).optional(),
  min_support: z.number().int().min(1).optional(),
  boundary_only: z.boolean().optional(),
  limit: z.number().int().min(1).max(5000).optional(),
};

const CARD_SECTIONS = [
  "intent",
  "roles",
  "composition_rules",
  "interface",
  "data_shapes",
  "topology",
  "exemplar_slices",
  "nl_only_symbols",
  "dissonance",
] as const;

const SUBSYSTEM_CARD_SCHEMA = {
  subsystem: z.string().min(1),
  repo: z.string().optional(),
  sections: z.array(z.enum(CARD_SECTIONS)).optional(),
};

const FUNCTOR_BETWEEN_SCHEMA = {
  repo_a: z.string().min(1),
  repo_b: z.string().min(1),
  direction: z.enum(["a_to_b", "b_to_a", "both"]).optional(),
  min_coverage: z.number().min(0).max(1).optional(),
  min_fidelity: z.number().min(0).max(1).optional(),
  min_pair_fidelity: z.number().min(0).max(1).optional(),
  // MetaCoding-265: margin floor — drop coin-flip-tie mapping rows below it.
  min_margin: z.number().min(0).max(1).optional(),
  limit: z.number().int().min(1).max(5000).optional(),
  // MetaCoding-4ty: member-set restriction + single-repo endofunctor read-side.
  members_a: z.array(z.string()).optional(),
  members_b: z.array(z.string()).optional(),
  exclude_identity: z.boolean().optional(),
};

// ---------------------------------------------------------------------------
// Handler implementations
// ---------------------------------------------------------------------------

export async function motifSearch(input: {
  min_support?: number;
  edge_kinds?: EdgeKind[];
  repo_coverage_min?: number;
  label?: string;
  limit?: number;
}): Promise<MotifWithLabel[]> {
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const motifRows = await handle.motifs({
      minSupport: input.min_support,
      edgeKinds: input.edge_kinds,
      repoCoverageMin: input.repo_coverage_min,
      limit: input.limit ?? 100,
    });

    if (motifRows.length === 0) return [];

    // Attempt to join with L3 patterns (source_kind='motif') for labels.
    // If patterns.jsonl is absent, skip silently — labels are optional.
    let patternsBySourceRef = new Map<string, PatternRow>();
    try {
      const patterns = await handle.patterns({ sourceKind: "motif" });
      for (const p of patterns) {
        patternsBySourceRef.set(p.source_ref, p);
      }
    } catch {
      // L3 labels not yet generated — continue without them.
    }

    const results: MotifWithLabel[] = motifRows.map((m) => {
      const pattern = patternsBySourceRef.get(m.motif_id);
      const row: MotifWithLabel = { ...m };
      if (pattern) {
        row.label = pattern.label;
        row.label_description = pattern.description;
        row.label_confidence = pattern.confidence;
      }
      return row;
    });

    // Apply label filter if requested (case-insensitive substring match).
    if (input.label !== undefined) {
      const needle = input.label.toLowerCase();
      return results.filter(
        (r) => r.label !== undefined && r.label.toLowerCase().includes(needle),
      );
    }

    return results;
  } finally {
    await handle.close();
  }
}

export async function nearestSymbols(input: {
  symbol_id?: string;
  qualified_name?: string;
  k?: number;
  cross_repo_only?: boolean;
  embedding_kind?: string;
}): Promise<NearestSymbolRow[]> {
  if (!input.symbol_id && !input.qualified_name) {
    throw new Error("Either symbol_id or qualified_name is required.");
  }
  // TODO(MetaCoding-xno.4): Replace with HNSW index once nn_index supports
  // embedding_kind routing (Phase 4 multi-tier embeds).
  // Strategy: fetch only the seed row to get its vector (1 row), then push
  // all cosine ranking into DuckDB via list_inner_product — avoids materializing
  // the full embedding table (potentially 500k+ rows) in JS heap.

  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const k = input.k ?? 10;

    // Step 1: fetch the seed row. If lookup is by symbol_id, filter to 1 row.
    const seedRows = input.symbol_id !== undefined
      ? await handle.embeddings({ symbolIds: [input.symbol_id] })
      : await handle.embeddings();

    const seed = seedRows.find((e) =>
      (input.symbol_id !== undefined && e.symbol_id === input.symbol_id) ||
      (input.qualified_name !== undefined && e.qualified_name === input.qualified_name),
    );
    if (!seed) return [];

    // Step 2: push cosine ranking into DuckDB via handle.nearestByVector.
    // Must await — returning a Promise from try/finally causes finally to run
    // before the Promise resolves, disconnecting the conn too early.
    return await handle.nearestByVector({
      seedVec: seed.vec,
      seedId: seed.symbol_id,
      k,
      seedRepo: input.cross_repo_only ? seed.repo : undefined,
    });
  } finally {
    await handle.close();
  }
}

export async function patternSearch(input: {
  label?: string;
  source_kind?: string;
  min_confidence?: number;
  instances_in_repo?: string;
  limit?: number;
}): Promise<PatternWithEvidence[]> {
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    let patterns = await handle.patterns({
      sourceKind: input.source_kind,
      minConfidence: input.min_confidence,
      label: input.label,
    });

    // instances_in_repo: filter to patterns that have at least one evidence
    // row with that repo. Use a single batch query instead of N+1.
    if (input.instances_in_repo !== undefined) {
      const patternIds = await handle.patternIdsWithEvidenceInRepo(input.instances_in_repo);
      patterns = patterns.filter((p) => patternIds.has(p.pattern_id));
    }

    const limit = input.limit ?? 100;
    const truncated = patterns.slice(0, limit);

    // Attach evidence to each pattern.
    const results: PatternWithEvidence[] = await Promise.all(
      truncated.map(async (p) => {
        let evidence: EvidenceRow[] = [];
        try {
          evidence = await handle.evidence(p.pattern_id);
        } catch {
          // evidence.jsonl may be absent.
        }
        return { ...p, evidence };
      }),
    );

    return results;
  } finally {
    await handle.close();
  }
}

export async function shapeDistance(input: {
  repo_a: string;
  repo_b?: string;
  k_nearest?: number;
}): Promise<ShapeDistancePair | ShapeDistancePair[]> {
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    if (input.repo_b !== undefined) {
      // Point query: return a single distance between repo_a and repo_b.
      // Table is upper-triangle (repo_a < repo_b lexicographically); handle
      // both orderings.
      const rows = await handle.wassersteinH1({
        repoA: input.repo_a,
        repoB: input.repo_b,
      });

      if (rows.length === 0) {
        return { repo_a: input.repo_a, repo_b: input.repo_b, distance: null };
      }

      // The wassersteinH1 query returns rows where either repo appears;
      // find the one that matches both.
      const match = rows.find(
        (r) =>
          (r.repo_a === input.repo_a && r.repo_b === input.repo_b!) ||
          (r.repo_a === input.repo_b! && r.repo_b === input.repo_a),
      );

      if (!match) {
        return { repo_a: input.repo_a, repo_b: input.repo_b, distance: null };
      }

      return {
        repo_a: input.repo_a,
        repo_b: input.repo_b,
        distance: match.distance,
      };
    }

    // k-nearest: return top-k closest repos to repo_a.
    const k = input.k_nearest ?? 10;
    const rows = await handle.wassersteinH1({ repoA: input.repo_a });

    // Each row has repo_a + repo_b; the "other" repo is whichever isn't repo_a.
    const withOther: Array<{ repo: string; distance: number }> = rows.map(
      (r: WassersteinH1Row) => ({
        repo: r.repo_a === input.repo_a ? r.repo_b : r.repo_a,
        distance: r.distance,
      }),
    );

    // Sort ascending (closest first) and take top-k.
    withOther.sort((a, b) => a.distance - b.distance);
    const topK = withOther.slice(0, k);

    return topK.map((x) => ({
      repo_a: input.repo_a,
      repo_b: x.repo,
      distance: x.distance,
    }));
  } finally {
    await handle.close();
  }
}

export async function centralityQuery(input: {
  repo?: string;
  kind?: string;
  top_k?: number;
  metric: "pagerank" | "betweenness" | "eigenvector";
}): Promise<CentralityResult[]> {
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const centrality = await handle.centrality({
      repo: input.repo,
      topK: input.top_k ?? 50,
      metric: input.metric,
    });

    if (centrality.length === 0) return [];

    // Load spectral clusters for joining.
    let clusterMap = new Map<string, SpectralClusterRow>();
    try {
      const clusters = await handle.spectralClusters({ repo: input.repo });
      for (const c of clusters) {
        clusterMap.set(c.symbol_id, c);
      }
    } catch {
      // spectral_clusters may be absent.
    }

    // The `kind` filter maps to SymbolKind in the graph — centrality.parquet
    // does not carry a kind column (it is a Layer-1 artifact over the
    // cross-repo centrality graph, keyed by symbol_id + repo). We cannot
    // filter by kind here without joining back to the graph store, which
    // ctkr-tools.ts deliberately avoids. Emit a note field if kind was
    // requested but cannot be applied.
    const kindFilterNote = input.kind
      ? `[kind filter "${input.kind}" not applied: centrality.parquet lacks kind column]`
      : undefined;

    const results: CentralityResult[] = centrality.map(
      (row: CentralityRow) => {
        const cluster = clusterMap.get(row.symbol_id);
        const score =
          input.metric === "pagerank"
            ? row.pagerank
            : input.metric === "betweenness"
              ? row.betweenness
              : row.eigenvector;
        const result: CentralityResult = {
          symbol_id: row.symbol_id,
          qualified_name: row.qualified_name,
          repo: row.repo,
          score,
        };
        if (cluster) {
          result.cluster_id = cluster.cluster_id;
          result.cluster_size = cluster.cluster_size;
        }
        return result;
      },
    );

    if (kindFilterNote && results.length > 0) {
      // Attach the note on the first result so callers can see it.
      results[0]!._note = kindFilterNote;
    }

    // Already ordered by metric DESC from handle.centrality; return as-is.
    return results;
  } finally {
    await handle.close();
  }
}

export async function roleEquivalent(input: {
  symbol_id?: string;
  qualified_name?: string;
  k?: number;
  scope?: string;
  cross_repo_only?: boolean;
}): Promise<RoleEquivalentRow[]> {
  if (!input.symbol_id && !input.qualified_name) {
    throw new Error("Either symbol_id or qualified_name is required.");
  }

  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const k = input.k ?? 10;

    // Resolve seed to a symbol_id, optionally scoped to a single repo.
    // qualified_name can be ambiguous across repos — scope disambiguates.
    const seedRows = input.symbol_id !== undefined
      ? await handle.homProfiles({
          symbolIds: [input.symbol_id],
          repo: input.scope,
        })
      : await handle.homProfiles({
          qualifiedName: input.qualified_name,
          repo: input.scope,
        });

    if (seedRows.length === 0) return [];
    // If multiple rows match (qualified_name without scope), take the first;
    // a caller who needs a specific one must pass scope or use symbol_id.
    const seed = seedRows[0]!;

    const knn = await handle.homProfilesKnn({
      seedId: seed.symbol_id,
      k,
      differentRepoOnly: input.cross_repo_only,
    });
    return knn.map((r) => ({
      symbol_id: r.symbol_id,
      qualified_name: r.qualified_name,
      repo: r.repo,
      hom_profile_distance: r.distance,
    }));
  } finally {
    await handle.close();
  }
}

// ---------------------------------------------------------------------------
// ctkr.subsystems (subsystem-extraction §2.4 / §8.2, T1)
// ---------------------------------------------------------------------------

export async function subsystemsQuery(input: {
  repo?: string;
  resolution?: number;
  min_persistence?: number;
  boundary_sample?: number;
}): Promise<SubsystemsResult> {
  const boundarySample = input.boundary_sample ?? 5;
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const notes: string[] = [];

    let subs = await handle.subsystems({
      repo: input.repo,
      minPersistence: input.min_persistence,
    });

    // resolution is a filter over the emitted partition's default resolution.
    // The batch runner writes one resolution per artifact; a mismatched value
    // simply yields nothing (surfaced, not silently empty).
    if (input.resolution !== undefined) {
      const before = subs.length;
      subs = subs.filter((s) => Math.abs(s.resolution - input.resolution!) < 1e-9);
      if (before > 0 && subs.length === 0) {
        notes.push(
          `no subsystems at resolution=${input.resolution} ` +
            `(the artifact was cut at a different default resolution — omit the ` +
            `resolution filter to see it, or re-run \`ctkr subsystems --resolution\`)`,
        );
      }
    }

    if (subs.length === 0) {
      if (notes.length === 0) {
        notes.push(
          input.repo !== undefined
            ? `no subsystems found for repo "${input.repo}"`
            : "no subsystems found",
        );
      }
      return { subsystems: [], config: null, _note: notes.join("; ") };
    }

    // Pull all members for the matched repo(s) once, group by subsystem.
    const membersBySub = new Map<string, SubsystemMemberRow[]>();
    const members = await handle.subsystemMembers({ repo: input.repo });
    for (const m of members) {
      const arr = membersBySub.get(m.subsystem_id);
      if (arr) arr.push(m);
      else membersBySub.set(m.subsystem_id, [m]);
    }

    const results: SubsystemResult[] = subs.map((s) => {
      const mem = membersBySub.get(s.subsystem_id) ?? [];
      let nLoc = 0;
      let confSum = 0;
      for (const m of mem) {
        if (m.placement === "locality") nLoc++;
        confSum += m.boundary_confidence;
      }
      // Ascending by confidence → the boundary (judgment-call) members first.
      const boundary = [...mem]
        .sort((a, b) => a.boundary_confidence - b.boundary_confidence)
        .slice(0, boundarySample)
        .map((m) => ({
          symbol_id: m.symbol_id,
          qualified_name: m.qualified_name,
          boundary_confidence: m.boundary_confidence,
          placement: m.placement,
        }));
      return {
        subsystem_id: s.subsystem_id,
        repo: s.repo,
        n_members: s.n_members,
        resolution: s.resolution,
        persistence_score: s.persistence_score,
        n_locality: nLoc,
        n_structural: mem.length - nLoc,
        mean_boundary_confidence: mem.length > 0 ? confSum / mem.length : 0,
        boundary_symbols: boundary,
      };
    });

    const result: SubsystemsResult = {
      subsystems: results,
      config: subs[0]?.config ?? null,
    };
    if (notes.length > 0) result._note = notes.join("; ");
    return result;
  } finally {
    await handle.close();
  }
}

// ---------------------------------------------------------------------------
// ctkr.interface_of (subsystem-extraction §3 / §8.2, T2)
// ---------------------------------------------------------------------------

export async function interfaceOf(input: {
  subsystem: string;
  repo?: string;
  direction?: "provides" | "consumes";
  boundary_shapes_only?: boolean;
  limit?: number;
}): Promise<InterfaceOfResult> {
  const limit = input.limit ?? 1000;
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const notes: string[] = [];

    const manifest = await handle.manifest();
    if (!manifest.interfaces) {
      throw new Error(
        `interface artifacts not found in ${dataDir} — run \`ctkr interfaces\` ` +
          `(Stage B) after \`ctkr subsystems\` (Stage A) to generate them`,
      );
    }

    // Fetch provides/consumes per the direction filter. Over-fetch by one to
    // detect truncation on the primary rows.
    const wantProvides = input.direction !== "consumes";
    const wantConsumes = input.direction !== "provides";
    const provides = wantProvides
      ? await handle.interfaces({
          repo: input.repo,
          subsystemId: input.subsystem,
          direction: "provides",
          limit: limit + 1,
        })
      : [];
    const consumes = wantConsumes
      ? await handle.interfaces({
          repo: input.repo,
          subsystemId: input.subsystem,
          direction: "consumes",
          limit: limit + 1,
        })
      : [];

    if (provides.length === 0 && consumes.length === 0) {
      // Distinguish "unknown subsystem" from "no crossing morphisms".
      const all = await handle.interfaces({ repo: input.repo, limit: 100000 });
      const known = new Set(all.map((r) => r.subsystem_id));
      if (!known.has(input.subsystem)) {
        const sample = [...known].sort().slice(0, 12);
        notes.push(
          `unknown subsystem "${input.subsystem}"` +
            (input.repo ? ` in repo "${input.repo}"` : "") +
            `; known subsystem_ids include: ${sample.join(", ") || "(none)"}` +
            (known.size > sample.length ? ` (+${known.size - sample.length} more)` : ""),
        );
      } else {
        notes.push(
          `subsystem "${input.subsystem}" has no crossing morphisms in the ` +
            `requested direction (an isolated or leaf subsystem)`,
        );
      }
    }

    const truncated = provides.length > limit || consumes.length > limit;
    const provOut = provides.slice(0, limit);
    const consOut = consumes.slice(0, limit);

    // Rolled-up API surface + dependency topology.
    const provExports = [
      ...new Set(
        provOut
          .map((r) => r.internal_export_qualified_name)
          .filter((q) => q && q.includes("::")),
      ),
    ].sort();
    const consSubs = [
      ...new Set(consOut.map((r) => r.external_subsystem_id ?? "(external)")),
    ].sort();

    // Data shapes for this subsystem.
    let shapes = await handle.dataShapes({
      repo: input.repo,
      subsystemId: input.subsystem,
      boundaryOnly: input.boundary_shapes_only,
      limit,
    });
    const boundaryTypes = new Set(
      shapes.filter((s) => s.boundary).map((s) => s.type_symbol_id),
    );
    const internalTypes = new Set(
      shapes.filter((s) => !s.boundary).map((s) => s.type_symbol_id),
    );

    // Resolve the subsystem's repo (rows carry it) for the alphabet note.
    const repo =
      provOut[0]?.repo ?? consOut[0]?.repo ?? shapes[0]?.repo ?? input.repo ?? null;
    const cov =
      (manifest.alphabet_coverage as
        | Record<string, Record<string, unknown>>
        | null
        | undefined) ?? null;
    const alphabet = repo && cov ? (cov[repo] ?? null) : null;

    const result: InterfaceOfResult = {
      subsystem_id: input.subsystem,
      repo,
      provides: provOut,
      consumes: consOut,
      provides_exports: provExports,
      consumes_subsystems: consSubs,
      data_shapes: shapes,
      n_boundary_shapes: boundaryTypes.size,
      n_internal_shapes: internalTypes.size,
      alphabet_coverage: alphabet,
      truncated,
    };
    if (notes.length > 0) result._note = notes.join("; ");
    return result;
  } finally {
    await handle.close();
  }
}

// ---------------------------------------------------------------------------
// ctkr.composition_rules (subsystem-extraction §4.3 / §8.2, T4)
// ---------------------------------------------------------------------------

/**
 * Return a subsystem's composition algebra (Phase 2d, scoped): the operations
 * recovered by projecting its actual typed call/reference paths onto role
 * classes, the composition laws they observe, and the protocol contract its
 * boundary operations impose. The scoped variant of ctkr.composition_rules —
 * ``subsystem`` restricts to one subsystem's operad (the default, most useful
 * query); omitting it returns the corpus-scoped operations under the other
 * filters. Reads operads.parquet only (recovery is the `ctkr operads` batch
 * runner).
 */
export async function compositionRules(input: {
  subsystem?: string;
  repo?: string;
  view?: "orbit" | "similarity";
  op_kind?: "path" | "fan_in" | "non_operadic";
  min_support?: number;
  boundary_only?: boolean;
  limit?: number;
}): Promise<CompositionRulesResult> {
  const limit = input.limit ?? 500;
  const view = input.view ?? "similarity";
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const notes: string[] = [];
    const manifest = await handle.manifest();
    if (!manifest.operads) {
      throw new Error(
        `operad artifacts not found in ${dataDir} — run \`ctkr operads\` ` +
          `(Stage C §4.3) after \`ctkr roles\` (T3) to generate them`,
      );
    }

    // Over-fetch by one to detect truncation.
    const rows = await handle.operads({
      repo: input.repo,
      subsystemId: input.subsystem,
      view,
      opKind: input.op_kind,
      minSupport: input.min_support,
      boundaryOnly: input.boundary_only,
      limit: limit + 1,
    });

    if (rows.length === 0) {
      // Distinguish an unknown subsystem from a genuinely operad-free one.
      if (input.subsystem !== undefined) {
        const all = await handle.operads({ repo: input.repo, view, limit: 100000 });
        const known = new Set(all.map((r) => r.subsystem_id));
        if (!known.has(input.subsystem)) {
          const sample = [...known].sort().slice(0, 12);
          notes.push(
            `unknown subsystem "${input.subsystem}"` +
              (input.repo ? ` in repo "${input.repo}"` : "") +
              ` for view "${view}"; known subsystem_ids include: ` +
              `${sample.join(", ") || "(none)"}` +
              (known.size > sample.length ? ` (+${known.size - sample.length} more)` : ""),
          );
        } else {
          notes.push(
            `subsystem "${input.subsystem}" has no operations matching the ` +
              `filters (raise nothing / lower min_support, or it is a leaf ` +
              `subsystem with no recurring role-paths)`,
          );
        }
      } else {
        notes.push("no operations match the requested filters");
      }
      const empty: CompositionRulesResult = {
        subsystem_id: input.subsystem ?? "",
        repo: input.repo ?? null,
        view,
        operations: [],
        violations: [],
        protocol_roles: [],
        n_operations: 0,
        n_boundary_ops: 0,
        n_missing_composite: 0,
        n_back_call_cycle: 0,
        truncated: false,
        _note: notes.join("; "),
      };
      return empty;
    }

    const truncated = rows.length > limit;
    const out = rows.slice(0, limit);

    const operations = out.filter((r) => r.op_kind !== "non_operadic");
    const violations = out.filter((r) => r.op_kind === "non_operadic");
    const protocolRoles = [
      ...new Set(
        out
          .filter((r) => r.is_boundary_op)
          .flatMap((r) => [...r.input_roles, r.output_role]),
      ),
    ].sort();

    const result: CompositionRulesResult = {
      subsystem_id: input.subsystem ?? out[0]!.subsystem_id,
      repo: out[0]?.repo ?? input.repo ?? null,
      view,
      operations,
      violations,
      protocol_roles: protocolRoles,
      n_operations: operations.length,
      n_boundary_ops: out.filter((r) => r.is_boundary_op).length,
      n_missing_composite: violations.filter(
        (r) => r.violation_kind === "missing_composite",
      ).length,
      n_back_call_cycle: violations.filter(
        (r) => r.violation_kind === "back_call_cycle",
      ).length,
      truncated,
    };
    if (notes.length > 0) result._note = notes.join("; ");
    return result;
  } finally {
    await handle.close();
  }
}

// ---------------------------------------------------------------------------
// ctkr.functor_between (§4)
// ---------------------------------------------------------------------------

/** Project a FunctorRow onto the read-side summary shape. */
function toFunctorSummary(row: FunctorRow): FunctorSummary {
  const summary: FunctorSummary = {
    functor_id: row.functor_id,
    repo_src: row.repo_src,
    repo_dst: row.repo_dst,
    coverage: row.coverage,
    fidelity: row.fidelity,
    n_mapped: row.n_mapped,
    n_objects_src: row.n_objects_src,
    // Additive column (MetaCoding-265): 0 on functors written before it existed.
    ambiguity_mass: row.ambiguity_mass ?? 0,
    generated_at: row.generated_at,
  };
  // path_fidelity_2 is the −1 sentinel when not computed (§3.1) — omit it.
  if (row.path_fidelity_2 !== undefined && row.path_fidelity_2 >= 0) {
    summary.path_fidelity_2 = row.path_fidelity_2;
  }
  return summary;
}

/**
 * Staleness check (§4): the functor's `config.hom_profiles_generated_at` is
 * stamped from the manifest generation it was seeded against. When it differs
 * from the current manifest generation, the correspondence may be built on an
 * older hom-profile set — surface it rather than silently serve stale maps.
 */
function stalenessNote(
  row: FunctorRow,
  manifest: ArtifactManifest,
): string | null {
  let cfg: Record<string, unknown>;
  try {
    cfg = JSON.parse(row.config) as Record<string, unknown>;
  } catch {
    return null;
  }
  const stamp = cfg["hom_profiles_generated_at"];
  const current = manifest.generated_at;
  if (
    typeof stamp === "string" &&
    typeof current === "string" &&
    stamp !== current
  ) {
    return (
      "functor was discovered against an older hom-profile generation " +
      "— re-run the discovery runner"
    );
  }
  return null;
}

export async function functorBetween(input: {
  repo_a: string;
  repo_b: string;
  direction?: "a_to_b" | "b_to_a" | "both";
  min_coverage?: number;
  min_fidelity?: number;
  min_pair_fidelity?: number;
  /** MetaCoding-265: drop mapping rows whose margin < this (coin-flip ties). */
  min_margin?: number;
  limit?: number;
  /** Restrict returned domain rows to these src symbol_ids (subsystem A). */
  members_a?: string[];
  /** Restrict returned codomain rows to these dst symbol_ids (subsystem B). */
  members_b?: string[];
  /**
   * ENDOFUNCTOR read-side (MetaCoding-4ty): drop trivial `s ↦ s` mapping rows.
   * Defaults `true` when repo_a === repo_b (a single-repo endofunctor query,
   * where identities are noise), `false` otherwise.
   */
  exclude_identity?: boolean;
}): Promise<FunctorBetweenResult> {
  const direction = input.direction ?? "a_to_b";
  const minCoverage = input.min_coverage ?? 0;
  const minFidelity = input.min_fidelity ?? 0;
  const minPairFidelity = input.min_pair_fidelity ?? 0;
  const minMargin = input.min_margin ?? 0;
  const limit = input.limit ?? 200;
  const excludeIdentity = input.exclude_identity ?? input.repo_a === input.repo_b;
  // members_a/members_b attach to repo_a/repo_b; map them onto the primary
  // (src, dst) sides, which flip for direction "b_to_a".
  const primaryIsBToA = direction === "b_to_a";
  const srcMemberList = primaryIsBToA ? input.members_b : input.members_a;
  const dstMemberList = primaryIsBToA ? input.members_a : input.members_b;
  const srcMemberSet = srcMemberList ? new Set(srcMemberList) : null;
  const dstMemberSet = dstMemberList ? new Set(dstMemberList) : null;

  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    // Missing-artifact error mode (§4): explicit, actionable message. Checked
    // up front so it fires before any read (mirrors the loader's discipline,
    // but with the runner-specific wording the design calls for).
    const manifest = await handle.manifest();
    if (!manifest.functors) {
      throw new Error(
        `functor artifacts not found in ${dataDir} — run the functor discovery runner first`,
      );
    }

    // The primary direction decides which stored (src, dst) row carries the
    // returned mapping. "both" keeps a→b primary and adds the reverse summary.
    const [primarySrc, primaryDst] =
      direction === "b_to_a"
        ? [input.repo_b, input.repo_a]
        : [input.repo_a, input.repo_b];

    const notes: string[] = [];

    // Best functor for the primary direction among those passing the filters.
    // The loader orders by coverage×fidelity DESC, so passing[0] is the pick
    // and the rest are alternative configs.
    const passing = await handle.functors({
      repoSrc: primarySrc,
      repoDst: primaryDst,
      minCoverage,
      minFidelity,
    });

    let functor: FunctorSummary | null = null;
    let mapping: FunctorMappingRow[] = [];
    let truncated = false;

    if (passing.length > 0) {
      const chosen = passing[0]!;
      functor = toFunctorSummary(chosen);

      if (passing.length > 1) {
        const n = passing.length - 1;
        notes.push(
          `${n} alternative config${n === 1 ? "" : "s"} for this pair not shown ` +
            `(returned the max coverage×fidelity row)`,
        );
      }

      const stale = stalenessNote(chosen, manifest);
      if (stale) notes.push(stale);

      // min_pair_fidelity is the query-time strictness dial (MetaCoding-ebg).
      // At 0 we keep no-evidence pairs (−1 → surfaced as null); a positive
      // threshold drops them, since the loader's `pair_fidelity >= x` filter
      // excludes the −1 sentinel. Fetch one extra row to detect truncation.
      // When a member/identity filter is active the drop happens AFTER the DB
      // read, so fetch the whole mapping (not just limit+1) to keep truncation
      // accurate; otherwise keep the cheap limit+1 probe. (MetaCoding-4ty)
      const filtering =
        srcMemberSet !== null || dstMemberSet !== null || excludeIdentity;
      const edgeOpts: {
        minPairFidelity?: number;
        minMargin?: number;
        limit: number;
      } = {
        limit: filtering ? 1_000_000 : limit + 1,
      };
      if (minPairFidelity > 0) edgeOpts.minPairFidelity = minPairFidelity;
      if (minMargin > 0) edgeOpts.minMargin = minMargin;
      let edges = await handle.functorEdges(chosen.functor_id, edgeOpts);
      if (srcMemberSet !== null) {
        edges = edges.filter((e) => srcMemberSet.has(e.src_symbol_id));
      }
      if (dstMemberSet !== null) {
        edges = edges.filter((e) => dstMemberSet.has(e.dst_symbol_id));
      }
      if (excludeIdentity) {
        edges = edges.filter((e) => e.src_symbol_id !== e.dst_symbol_id);
      }
      truncated = edges.length > limit;
      mapping = edges.slice(0, limit).map((e) => ({
        src_symbol_id: e.src_symbol_id,
        src_qualified_name: e.src_qualified_name,
        dst_symbol_id: e.dst_symbol_id,
        dst_qualified_name: e.dst_qualified_name,
        similarity: e.similarity,
        margin: e.margin,
        // Additive column (MetaCoding-265): false on edges written before it.
        is_ambiguous: e.is_ambiguous ?? false,
        pair_fidelity: e.pair_fidelity === -1 ? null : e.pair_fidelity,
      }));

      // Honest framing (MetaCoding-265): a functor can have high coverage yet an
      // ambiguity_mass ~0.9 — that is NOT a trustworthy per-symbol map, only an
      // aggregate signal. Surface it so an agent sees the coin-flip ties rather
      // than reading the mapping rows as confident correspondences.
      const am = chosen.ambiguity_mass ?? 0;
      if (am >= 0.5) {
        notes.push(
          `ambiguity_mass=${(am * 100).toFixed(0)}% of this functor's mappings are ` +
            `coin-flip ties among structural lookalikes — treat the per-symbol ` +
            `mapping as UNRELIABLE (aggregate coverage/fidelity/cycle-consistency ` +
            `still meaningful); filter with min_margin or inspect is_ambiguous`,
        );
      }
    } else {
      // No functor passes the filters. Distinguish "pair present but below the
      // thresholds" (report best-available so agents learn the landscape) from
      // "no such functor" (unknown repo, or ordered pair never discovered).
      const all = await handle.functors({
        repoSrc: primarySrc,
        repoDst: primaryDst,
      });
      if (all.length > 0) {
        const best = all[0]!;
        const fidStr =
          best.fidelity < 0
            ? "null (no internal edges)"
            : best.fidelity.toFixed(2);
        notes.push(
          `no functor ${primarySrc}→${primaryDst} meets ` +
            `min_coverage=${minCoverage}/min_fidelity=${minFidelity}; best available: ` +
            `coverage=${best.coverage.toFixed(2)}, fidelity=${fidStr}`,
        );
      } else {
        // Unknown-repo error mode (§4): list the repos that do appear.
        const allFunctors = await handle.functors();
        const repos = new Set<string>();
        for (const f of allFunctors) {
          repos.add(f.repo_src);
          repos.add(f.repo_dst);
        }
        const unknown = [primarySrc, primaryDst].filter((r) => !repos.has(r));
        const available = [...repos].sort();
        if (unknown.length > 0) {
          notes.push(
            `unknown repo${unknown.length === 1 ? "" : "s"} ${unknown.join(", ")}; ` +
              `available repos: ${available.join(", ") || "(none)"}`,
          );
        } else {
          notes.push(
            `no functor computed for ${primarySrc}→${primaryDst} ` +
              `(both repos are present in other pairs — run discovery for this ordered pair)`,
          );
        }
      }
    }

    const nAmbiguous = mapping.reduce((n, m) => n + (m.is_ambiguous ? 1 : 0), 0);
    const result: FunctorBetweenResult = {
      functor,
      mapping,
      n_ambiguous: nAmbiguous,
      truncated,
    };

    if (direction === "both") {
      const rev = await handle.functors({
        repoSrc: input.repo_b,
        repoDst: input.repo_a,
        minCoverage,
        minFidelity,
      });
      result.reverse = rev.length > 0 ? toFunctorSummary(rev[0]!) : null;
      if (rev.length === 0) {
        notes.push(
          `no reverse functor ${input.repo_b}→${input.repo_a} meets the filters`,
        );
      }
    }

    if (notes.length > 0) result._note = notes.join("; ");
    return result;
  } finally {
    await handle.close();
  }
}

// ---------------------------------------------------------------------------
// ctkr.subsystem_card (subsystem-extraction §8.1 / §8.2, T5)
// ---------------------------------------------------------------------------

/** Result shape for ctkr.subsystem_card (§8.2). The fused card, optionally
 *  pruned to the requested sections (cards are large; agents usually want one). */
export interface SubsystemCardResult {
  card: Partial<SubsystemCard> | null;
  /** Explanatory note — deck missing, unknown subsystem, section pruning. */
  _note?: string;
}

/**
 * Return one subsystem's fused specification card (§8.1) from the deck
 * (subsystem_cards.jsonl). Optionally section-filtered — the card is the
 * re-implementation reference and can be large, so agents usually want a
 * single section. Read-side only: the deck is written by the `ctkr
 * extract-spec` batch runner.
 */
export async function subsystemCard(input: {
  subsystem: string;
  repo?: string;
  sections?: Array<(typeof CARD_SECTIONS)[number]>;
}): Promise<SubsystemCardResult> {
  const dataDir = resolveCtkrDataDir();
  const handle = await openCtkrArtifacts(dataDir);
  try {
    const manifest = await handle.manifest();
    if (!manifest.subsystem_cards) {
      throw new Error(
        `spec deck not found in ${dataDir} — run \`ctkr extract-spec\` first`,
      );
    }

    const cards = await handle.subsystemCards({
      repo: input.repo,
      subsystemId: input.subsystem,
    });
    if (cards.length === 0) {
      // Distinguish an unknown subsystem from an empty deck.
      const all = await handle.subsystemCards({ repo: input.repo });
      const sample = all
        .slice(0, 5)
        .map((c) => c.subsystem_id)
        .join(", ");
      return {
        card: null,
        _note:
          `no card for subsystem "${input.subsystem}"` +
          (all.length > 0
            ? `; known subsystem_ids include: ${sample}`
            : "; the deck is empty"),
      };
    }

    const full = cards[0]!;
    const notes: string[] = [];

    if (input.sections === undefined || input.sections.length === 0) {
      return { card: full };
    }

    // Section-prune: always keep the identity/provenance envelope, then add the
    // requested sections. "dissonance" and "intent" map onto specific fields.
    const want = new Set(input.sections);
    const pruned: Partial<SubsystemCard> = {
      card_id: full.card_id,
      subsystem_id: full.subsystem_id,
      repo: full.repo,
      name: full.name,
      n_members: full.n_members,
      spec_basis_summary: full.spec_basis_summary,
      provenance: full.provenance,
      schema_version: full.schema_version,
    };
    if (want.has("intent")) {
      pruned.intent = full.intent;
      pruned.responsibilities = full.responsibilities;
      pruned.non_goals = full.non_goals;
    }
    if (want.has("dissonance")) pruned.intent_dissonance = full.intent_dissonance;
    if (want.has("roles")) pruned.roles = full.roles;
    if (want.has("composition_rules")) pruned.composition_rules = full.composition_rules;
    if (want.has("interface")) pruned.interface = full.interface;
    if (want.has("data_shapes")) pruned.data_shapes = full.data_shapes;
    if (want.has("topology")) pruned.topology = full.topology;
    if (want.has("exemplar_slices")) pruned.exemplar_slices = full.exemplar_slices;
    if (want.has("nl_only_symbols")) pruned.nl_only_symbols = full.nl_only_symbols;
    notes.push(`section-filtered to: ${[...want].sort().join(", ")}`);
    return { card: pruned, _note: notes.join("; ") };
  } finally {
    await handle.close();
  }
}

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

/**
 * Self-describe metadata for the CTKR tools, in the same shape as the core
 * graph/LSP tools in tools.ts. Co-located with the registrations below so
 * `describe_api` can never drift out of sync with what the server actually
 * exposes — adding a tool here and in registerCtkrTools is one edit, two
 * call sites in the same file. tools.ts splices this into TOOL_DESCRIPTIONS.
 */
export const CTKR_TOOL_DESCRIPTIONS: ToolDescription[] = [
  {
    name: "ctkr.motif_search",
    summary:
      "Search frequent typed subgraphs (motifs) mined from the cross-repo corpus, " +
      "optionally joined with L3 labels. Filter by min_support, edge_kinds, " +
      "repo_coverage_min, or a label substring. Sorted by support descending.",
    input_schema: {
      type: "object",
      properties: {
        min_support: { type: "integer", minimum: 1, description: "Minimum occurrence count." },
        edge_kinds: {
          type: "array",
          items: { type: "string", enum: EDGE_KIND_VALUES as unknown as string[] },
          description: "Restrict to motifs containing these edge kinds.",
        },
        repo_coverage_min: { type: "integer", minimum: 1, description: "Min number of repos the motif spans." },
        label: { type: "string", description: "L3 label substring filter." },
        limit: { type: "integer", minimum: 1, maximum: 1000, default: 50 },
      },
    },
  },
  {
    name: "ctkr.nearest_symbols",
    summary:
      "Find the k nearest symbols by structural embedding similarity (cosine). " +
      "Requires either symbol_id or qualified_name. cross_repo_only excludes the " +
      "seed's repo. embedding_kind defaults to 'structural'.",
    input_schema: {
      type: "object",
      properties: {
        symbol_id: { type: "string", description: "16-char hash. Provide this or qualified_name." },
        qualified_name: { type: "string", description: "Provide this or symbol_id." },
        k: { type: "integer", minimum: 1, maximum: 500, default: 10 },
        cross_repo_only: { type: "boolean", default: false },
        embedding_kind: { type: "string", default: "structural" },
      },
    },
  },
  {
    name: "ctkr.pattern_search",
    summary:
      "Search L3-labeled structural patterns from patterns.jsonl with attached " +
      "evidence. Filter by label substring, source_kind ('motif', 'role-cluster', " +
      "'analogy'), min_confidence, or instances_in_repo.",
    input_schema: {
      type: "object",
      properties: {
        label: { type: "string", description: "Label substring filter." },
        source_kind: { type: "string", enum: ["motif", "role-cluster", "analogy"] },
        min_confidence: { type: "number", minimum: 0, maximum: 1 },
        instances_in_repo: { type: "string", description: "Restrict to patterns with evidence in this repo." },
        limit: { type: "integer", minimum: 1, maximum: 1000, default: 50 },
      },
    },
  },
  {
    name: "ctkr.shape_distance",
    summary:
      "Topological (bottleneck H₁ Wasserstein) distance between repos. Either " +
      "repo_a + repo_b for a single value, or repo_a + k_nearest for the top-k " +
      "closest repos. Distance -1 means the pair is absent from the artifact.",
    input_schema: {
      type: "object",
      required: ["repo_a"],
      properties: {
        repo_a: { type: "string" },
        repo_b: { type: "string", description: "Single-pair mode." },
        k_nearest: { type: "integer", minimum: 1, maximum: 200, description: "Top-k mode." },
      },
    },
  },
  {
    name: "ctkr.role_equivalent",
    summary:
      "Find symbols that play the same structural role as the seed, by cosine-KNN " +
      "over hom-profile vectors. Matches on the shape of a symbol's typed-edge " +
      "neighbourhood, independent of name or repo conventions. Requires symbol_id " +
      "or qualified_name; scope disambiguates a name shared across repos; " +
      "cross_repo_only drives the Phase 2a cross-repo predicate.",
    input_schema: {
      type: "object",
      properties: {
        symbol_id: { type: "string", description: "16-char hash. Provide this or qualified_name." },
        qualified_name: { type: "string", description: "Provide this or symbol_id." },
        k: { type: "integer", minimum: 1, maximum: 500, default: 10 },
        scope: { type: "string", description: "Restrict the seed lookup to a single repo." },
        cross_repo_only: { type: "boolean", default: false },
      },
    },
  },
  {
    name: "ctkr.centrality_query",
    summary:
      "Per-symbol centrality scores (pagerank | betweenness | eigenvector) joined " +
      "with spectral cluster assignments. Filter by repo or top_k; sorted by the " +
      "chosen metric descending.",
    input_schema: {
      type: "object",
      required: ["metric"],
      properties: {
        metric: { type: "string", enum: ["pagerank", "betweenness", "eigenvector"] },
        repo: { type: "string" },
        kind: { type: "string", description: "Accepted but not applied in v1." },
        top_k: { type: "integer", minimum: 1, maximum: 10000 },
      },
    },
  },
  {
    name: "ctkr.subsystems",
    summary:
      "Return the subsystem partition of a repo (subsystem-extraction Stage A): " +
      "modules-as-emergent at a team-would-own-this granularity, from a consensus " +
      "Louvain partition over a resolution sweep with a low-weight directory prior. " +
      "Each subsystem carries persistence_score (sweep stability) plus " +
      "boundary-confidence metadata: counts of structural vs locality-placed " +
      "(zero-profile) members and the lowest-confidence boundary symbols (the " +
      "judgment-call assignments). Reads subsystems.parquet / " +
      "subsystem_members.parquet (partition is the `ctkr subsystems` batch runner). " +
      "Filter by repo, min_persistence, or resolution.",
    input_schema: {
      type: "object",
      properties: {
        repo: { type: "string", description: "Restrict to one repo." },
        resolution: {
          type: "number",
          description: "Filter to subsystems cut at this default resolution.",
        },
        min_persistence: {
          type: "number",
          minimum: 0,
          maximum: 1,
          description: "Only subsystems with persistence_score at or above this.",
        },
        boundary_sample: {
          type: "integer",
          minimum: 0,
          maximum: 200,
          default: 5,
          description: "How many lowest-confidence boundary members to return per subsystem.",
        },
      },
    },
  },
  {
    name: "ctkr.interface_of",
    summary:
      "Return a subsystem's interface contract (subsystem-extraction Stage B): " +
      "its boundary morphisms. provides = external->internal crossing edges (the " +
      "API surface; each internal symbol is an export, edge_kind its usage mode); " +
      "consumes = internal->external crossings (the dependency surface, with the " +
      "target subsystem giving the deck's topology). Also returns the rolled-up " +
      "export surface, the data shapes crossing (boundary) or private to " +
      "(internal) the subsystem with per-field read/write flow, and the per-lane " +
      "alphabet_coverage note (whether a thin shapes section is an extractor gap). " +
      "Reads interfaces.parquet / data_shapes.parquet (extraction is the `ctkr " +
      "interfaces` batch runner). Filter by subsystem (subsystem_id, required), " +
      "repo, direction, boundary_shapes_only.",
    input_schema: {
      type: "object",
      required: ["subsystem"],
      properties: {
        subsystem: { type: "string", description: "subsystem_id (from ctkr.subsystems)." },
        repo: { type: "string", description: "Restrict to one repo." },
        direction: {
          type: "string",
          enum: ["provides", "consumes"],
          description: "Return only this side of the contract; omit for both.",
        },
        boundary_shapes_only: {
          type: "boolean",
          description: "Only data shapes that cross the interface (boundary types).",
        },
        limit: { type: "integer", minimum: 1, maximum: 5000, default: 1000 },
      },
    },
  },
  {
    name: "ctkr.composition_rules",
    summary:
      "Return a subsystem's composition algebra (subsystem-extraction Stage C / " +
      "§4.3, Phase 2d scoped): the operations recovered by projecting its actual " +
      "typed call/reference paths onto role classes — the composition-algebra a " +
      "re-implementer needs (not the pieces, but how they combine). op_kind " +
      "'path' = sequential composition (input_roles ∘ … → output_role); 'fan_in' " +
      "= n-ary combination (a target role built from arity distinct source " +
      "roles); 'non_operadic' = a recorded law violation (missing_composite = " +
      "two generators compose at role level but their composite is never " +
      "observed; back_call_cycle = an observed 2-cycle between roles). Boundary " +
      "(protocol) ops — any role public in the T2 interface — carry the order-of-" +
      "operations contract external callers depend on. Reads operads.parquet " +
      "(recovery is the `ctkr operads` batch runner). Scope with subsystem " +
      "(default; the scoped variant), repo, view ('orbit'|'similarity'), op_kind, " +
      "min_support, boundary_only.",
    input_schema: {
      type: "object",
      properties: {
        subsystem: {
          type: "string",
          description: "subsystem_id (from ctkr.subsystems) — the scoped operad.",
        },
        repo: { type: "string", description: "Restrict to one repo." },
        view: {
          type: "string",
          enum: ["orbit", "similarity"],
          description: "Which role quotient the operations were projected through (default similarity).",
        },
        op_kind: {
          type: "string",
          enum: ["path", "fan_in", "non_operadic"],
          description: "Return only this operation family; omit for all.",
        },
        min_support: {
          type: "integer",
          minimum: 1,
          description: "Only operations with at least this many concrete instances.",
        },
        boundary_only: {
          type: "boolean",
          description: "Only boundary (protocol) operations — the external contract.",
        },
        limit: { type: "integer", minimum: 1, maximum: 5000, default: 500 },
      },
    },
  },
  {
    name: "ctkr.subsystem_card",
    summary:
      "Return one subsystem's fused specification card (subsystem-extraction " +
      "§8.1) from the deck — the stack-agnostic re-implementation reference that " +
      "fuses the structural lane (partition, role classes, composition operad, " +
      "interface, data shapes, topology) with the natural-language lane (name, " +
      "intent, per-element descriptions, intent-dissonance findings). Every card " +
      "carries spec_basis_summary (the honest structural-vs-nl-only floor) and " +
      "complete provenance. Reads subsystem_cards.jsonl only — the deck is " +
      "written by the `ctkr extract-spec` batch runner. subsystem (a " +
      "subsystem_id from ctkr.subsystems) selects the card; repo scopes it; " +
      "sections prunes the (large) card to the parts you want (intent, roles, " +
      "composition_rules, interface, data_shapes, topology, exemplar_slices, " +
      "nl_only_symbols, dissonance) — the identity + provenance envelope is " +
      "always kept. Unknown subsystem or an ungenerated deck return card:null " +
      "with a _note.",
    input_schema: {
      type: "object",
      required: ["subsystem"],
      properties: {
        subsystem: {
          type: "string",
          description: "subsystem_id (from ctkr.subsystems) to fetch the card for.",
        },
        repo: { type: "string", description: "Optional repo scope." },
        sections: {
          type: "array",
          items: { type: "string", enum: [...CARD_SECTIONS] },
          description:
            "Prune the card to these sections (identity + provenance always " +
            "kept). Omit for the whole card.",
        },
      },
    },
  },
  {
    name: "ctkr.functor_between",
    summary:
      "Discover how two repos' designs correspond: the maximal partial " +
      "structure-preserving map (functor) between them, with per-correspondence " +
      "fidelity. Reads functors.parquet / functor_edges.parquet (discovery is the " +
      "batch runner's job). direction picks the stored direction(s); min_coverage / " +
      "min_fidelity gate the functor (min_fidelity=1.0 = strict functors only); " +
      "min_pair_fidelity filters mapping rows; min_margin drops coin-flip-tie rows " +
      "(margin below the floor); members_a/members_b scope the mapping to a " +
      "subsystem member-set; exclude_identity drops trivial self-maps for " +
      "single-repo endofunctor queries (repo_a===repo_b). The result surfaces " +
      "ambiguity_mass + n_ambiguous: when ambiguity_mass is high (~0.9 on real " +
      "code) the per-symbol mapping is coin-flip ties and only aggregate metrics " +
      "are trustworthy. Results note alternatives, best-available scores, and " +
      "hom-profile staleness.",
    input_schema: {
      type: "object",
      required: ["repo_a", "repo_b"],
      properties: {
        repo_a: { type: "string", description: "Source repo (domain C_A)." },
        repo_b: { type: "string", description: "Target repo (codomain C_B)." },
        direction: {
          type: "string",
          enum: ["a_to_b", "b_to_a", "both"],
          default: "a_to_b",
          description: "Which stored direction to return; 'both' adds the reverse summary.",
        },
        min_coverage: { type: "number", minimum: 0, maximum: 1, default: 0 },
        min_fidelity: {
          type: "number",
          minimum: 0,
          maximum: 1,
          default: 0,
          description: "1.0 returns only strict (pure) functors.",
        },
        min_pair_fidelity: {
          type: "number",
          minimum: 0,
          maximum: 1,
          default: 0,
          description: "Query-time strictness dial over the mapping rows.",
        },
        min_margin: {
          type: "number",
          minimum: 0,
          maximum: 1,
          default: 0,
          description:
            "Drop mapping rows whose margin < this (coin-flip ties among " +
            "structural lookalikes, MetaCoding-265) — request only resolved maps.",
        },
        limit: { type: "integer", minimum: 1, maximum: 5000, default: 200 },
        members_a: {
          type: "array",
          items: { type: "string" },
          description:
            "Restrict domain (repo_a) mapping rows to these symbol_ids — a " +
            "subsystem/member-set scope (MetaCoding-4ty).",
        },
        members_b: {
          type: "array",
          items: { type: "string" },
          description: "Restrict codomain (repo_b) mapping rows to these symbol_ids.",
        },
        exclude_identity: {
          type: "boolean",
          description:
            "Single-repo endofunctor: drop trivial s↦s rows. Defaults true when " +
            "repo_a === repo_b, false otherwise.",
        },
      },
    },
  },
];

/**
 * Register all ten CTKR tools on the given McpServer.
 * Call this from server.ts after the existing graph tool registrations.
 * Keep the registrations here in sync with CTKR_TOOL_DESCRIPTIONS above.
 */
export function registerCtkrTools(server: McpServer): void {
  server.registerTool(
    "ctkr.motif_search",
    {
      description:
        "Search frequent typed subgraphs (motifs) mined from the cross-repo corpus. " +
        "Returns MotifRow records, optionally joined with L3 labels from patterns.jsonl. " +
        "Filter by min_support (occurrence count), edge_kinds present in the motif, " +
        "repo_coverage_min (number of repos that contain the motif), or a label substring. " +
        "Results are sorted by support descending.",
      inputSchema: MOTIF_SEARCH_SCHEMA,
    },
    async (args) => {
      const rows = await motifSearch({
        min_support: args.min_support,
        edge_kinds: args.edge_kinds as EdgeKind[] | undefined,
        repo_coverage_min: args.repo_coverage_min,
        label: args.label,
        limit: args.limit,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.nearest_symbols",
    {
      description:
        "Find the k nearest symbols by structural embedding similarity (cosine distance). " +
        "Requires either symbol_id (16-char hash) or qualified_name. " +
        "embedding_kind defaults to 'structural' (DeepWalk/GraphSAGE); other values are " +
        "reserved for Phase 4 multi-tier embeddings. " +
        "cross_repo_only=true excludes symbols from the same repo as the seed. " +
        "v1 uses brute-force cosine; HNSW acceleration is a Phase 4 follow-up.",
      inputSchema: NEAREST_SYMBOLS_SCHEMA,
    },
    async (args) => {
      const rows = await nearestSymbols({
        symbol_id: args.symbol_id,
        qualified_name: args.qualified_name,
        k: args.k,
        cross_repo_only: args.cross_repo_only,
        embedding_kind: args.embedding_kind,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.pattern_search",
    {
      description:
        "Search L3-labeled structural patterns from patterns.jsonl with attached evidence. " +
        "Filter by label substring, source_kind ('motif', 'role-cluster', 'analogy'), " +
        "min_confidence (0–1), or instances_in_repo (restrict to patterns with evidence " +
        "in that repo). Returns PatternRow records with an evidence array attached.",
      inputSchema: PATTERN_SEARCH_SCHEMA,
    },
    async (args) => {
      const rows = await patternSearch({
        label: args.label,
        source_kind: args.source_kind,
        min_confidence: args.min_confidence,
        instances_in_repo: args.instances_in_repo,
        limit: args.limit,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.shape_distance",
    {
      description:
        "Query topological (bottleneck H₁ Wasserstein) distance between repos. " +
        "Two modes: " +
        "(1) repo_a + repo_b → single distance value; " +
        "(2) repo_a + k_nearest → top-k closest repos to repo_a, sorted ascending. " +
        "Distance = -1 means the pair is absent from wasserstein_h1.parquet " +
        "(one of the repos may lack a shape_pds entry).",
      inputSchema: SHAPE_DISTANCE_SCHEMA,
    },
    async (args) => {
      const result = await shapeDistance({
        repo_a: args.repo_a,
        repo_b: args.repo_b,
        k_nearest: args.k_nearest,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.role_equivalent",
    {
      description:
        "Find symbols that play the same structural role as the seed, by " +
        "cosine-distance KNN over hom-profile vectors from hom_profiles.parquet. " +
        "The 'categorically honest' same-role query: matches are based on the " +
        "shape of a symbol's typed-edge neighbourhood, independent of its name " +
        "or its repo's naming conventions. Requires either symbol_id (16-char hash) " +
        "or qualified_name. scope (optional) restricts the seed lookup to a single " +
        "repo — useful when a qualified_name appears in multiple repos. " +
        "cross_repo_only=true excludes neighbours in the seed's repo (Phase 2a's " +
        "cross-repo role-equivalence predicate). v1 is brute-force DuckDB cosine; " +
        "HNSW is a future optimisation. Returns at most k rows ordered by " +
        "hom_profile_distance ascending (closest first).",
      inputSchema: ROLE_EQUIVALENT_SCHEMA,
    },
    async (args) => {
      const rows = await roleEquivalent({
        symbol_id: args.symbol_id,
        qualified_name: args.qualified_name,
        k: args.k,
        scope: args.scope,
        cross_repo_only: args.cross_repo_only,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.centrality_query",
    {
      description:
        "Return per-symbol centrality scores (pagerank | betweenness | eigenvector) " +
        "from centrality.parquet, joined with spectral cluster assignments where available. " +
        "Filter by repo or top_k. Results are sorted by the chosen metric descending. " +
        "The kind filter (SymbolKind) is accepted but not applied in v1 — centrality.parquet " +
        "does not carry a kind column.",
      inputSchema: CENTRALITY_QUERY_SCHEMA,
    },
    async (args) => {
      const rows = await centralityQuery({
        repo: args.repo,
        kind: args.kind,
        top_k: args.top_k,
        metric: args.metric,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.subsystems",
    {
      description:
        "Return the subsystem partition of a repo (subsystem-extraction Stage A / " +
        "DECOMPOSE): modules-as-emergent at a team-would-own-this granularity, from " +
        "a consensus Louvain partition over a resolution sweep with a low-weight " +
        "directory prior. Reads subsystems.parquet / subsystem_members.parquet — the " +
        "partition is produced by the `ctkr subsystems` batch runner. Each subsystem " +
        "carries persistence_score (how stably its members co-cluster across the " +
        "sweep) plus boundary-confidence metadata: counts of structural vs " +
        "locality-placed (zero-profile) members and the lowest-confidence boundary " +
        "symbols — the judgment-call assignments a re-implementer must scrutinise. " +
        "Filter by repo, min_persistence (persistence_score floor), or resolution " +
        "(the default resolution the partition was cut at). boundary_sample caps how " +
        "many boundary symbols are returned per subsystem.",
      inputSchema: SUBSYSTEMS_SCHEMA,
    },
    async (args) => {
      const result = await subsystemsQuery({
        repo: args.repo,
        resolution: args.resolution,
        min_persistence: args.min_persistence,
        boundary_sample: args.boundary_sample,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.interface_of",
    {
      description:
        "Return a subsystem's interface contract (subsystem-extraction Stage B / " +
        "§3): the set of morphisms crossing its boundary — which is where a " +
        "subsystem's contract actually lives, since it is written down nowhere. " +
        "provides = external->internal crossing edges (the API surface; each " +
        "internal symbol is an export and edge_kind is its usage mode: " +
        "REFERENCES/CALLS in = invoked, IMPLEMENTS in = extension point, " +
        "TYPE_OF/RETURNS_TYPE in = used as a type, CONSTRUCTS in = instantiated). " +
        "consumes = internal->external crossings (the dependency surface; " +
        "external_subsystem_id gives the deck's subsystem-level topology, null = " +
        "external package). CONTAINS scaffolding is excluded. Also returns " +
        "provides_exports (the rolled-up top-level API surface), " +
        "consumes_subsystems (dependency topology), data_shapes (types crossing " +
        "the interface = boundary, or private = internal, with per-field " +
        "read/write flow so an output contract is distinguishable from an input), " +
        "and the per-lane alphabet_coverage note (so a thin shapes section reads " +
        "as an extractor gap, not an absent data model). Reads interfaces.parquet " +
        "/ data_shapes.parquet only — extraction is the `ctkr interfaces` batch " +
        "runner. Requires subsystem (subsystem_id from ctkr.subsystems); filter " +
        "by repo, direction ('provides'|'consumes'), boundary_shapes_only.",
      inputSchema: INTERFACE_OF_SCHEMA,
    },
    async (args) => {
      const result = await interfaceOf({
        subsystem: args.subsystem,
        repo: args.repo,
        direction: args.direction,
        boundary_shapes_only: args.boundary_shapes_only,
        limit: args.limit,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.composition_rules",
    {
      description:
        "Return a subsystem's composition algebra (subsystem-extraction Stage C " +
        "/ §4.3 — Phase 2d operad recovery, scoped single-repo and per-" +
        "subsystem): the operations recovered by projecting the subsystem's " +
        "actual typed call/reference paths onto its role classes (T3). This is " +
        "the composition-algebra a re-implementer most needs and most lacks — " +
        "not the pieces, but the algebra of how pieces combine. op_kind 'path' = " +
        "sequential composition (input_roles compose to output_role; arity = " +
        "steps); 'fan_in' = an n-ary combination (a target role produced by " +
        "combining arity distinct source roles — the wiring-diagram reading); " +
        "'non_operadic' = a recorded law violation (violation_kind " +
        "'missing_composite' = two generators compose at role level but their " +
        "predicted composite is never actually observed; 'back_call_cycle' = an " +
        "observed 2-cycle between roles — the 'never calls back except through " +
        "Callback' non-law). Violations are bookkept, never discarded. Boundary " +
        "(protocol) operations — is_boundary_op, any role public in the T2 " +
        "interface — carry the order-of-operations contract external callers " +
        "depend on (init-before-use, acquire-then-release), the laws a port " +
        "breaks first and silently; protocol_roles collects them. Every op is " +
        "invariance_tier 'I' (a port must preserve it). Reads operads.parquet " +
        "only — recovery is the `ctkr operads` batch runner. Scope with " +
        "subsystem (subsystem_id from ctkr.subsystems — the scoped variant), " +
        "repo, view ('orbit' = exact-profile classes | 'similarity' = working " +
        "classes, default), op_kind, min_support, boundary_only. Results split " +
        "operations from violations, note truncation, and flag an unknown " +
        "subsystem.",
      inputSchema: COMPOSITION_RULES_SCHEMA,
    },
    async (args) => {
      const result = await compositionRules({
        subsystem: args.subsystem,
        repo: args.repo,
        view: args.view,
        op_kind: args.op_kind,
        min_support: args.min_support,
        boundary_only: args.boundary_only,
        limit: args.limit,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.subsystem_card",
    {
      description:
        "Return one subsystem's fused specification card (subsystem-extraction " +
        "§8.1): the stack-agnostic re-implementation reference fusing the " +
        "structural lane (role classes, composition operad, interface, data " +
        "shapes, topology) with the NL lane (name, intent, descriptions, " +
        "intent-dissonance findings). Carries spec_basis_summary (structural vs " +
        "nl-only floor) + full provenance. Reads subsystem_cards.jsonl only — " +
        "the deck is the `ctkr extract-spec` runner's job. subsystem selects " +
        "the card (a subsystem_id from ctkr.subsystems); repo scopes it; " +
        "sections prunes the large card (intent, roles, composition_rules, " +
        "interface, data_shapes, topology, exemplar_slices, nl_only_symbols, " +
        "dissonance) while always keeping the identity + provenance envelope. " +
        "Unknown subsystem or ungenerated deck return card:null + a _note.",
      inputSchema: SUBSYSTEM_CARD_SCHEMA,
    },
    async (args) => {
      const result = await subsystemCard({
        subsystem: args.subsystem,
        repo: args.repo,
        sections: args.sections,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );

  server.registerTool(
    "ctkr.functor_between",
    {
      description:
        "Discover how two repos' designs correspond: the maximal partial " +
        "structure-preserving map (functor) between them, with per-correspondence " +
        "fidelity. Reads functors.parquet / functor_edges.parquet only — discovery " +
        "is the batch runner's job. " +
        "direction ('a_to_b' | 'b_to_a' | 'both') selects the stored direction; " +
        "'both' also returns the reverse (B→A) summary. " +
        "min_coverage / min_fidelity gate which functor is returned (min_fidelity=1.0 " +
        "returns only strict/pure functors; a −1 no-evidence fidelity always fails a " +
        "positive threshold). min_pair_fidelity filters the returned mapping rows " +
        "(pair_fidelity=null means an isolated pair with no structural evidence — " +
        "never read as 1.0). min_margin drops coin-flip-tie rows (margin below the " +
        "floor). The result carries ambiguity_mass + n_ambiguous (MetaCoding-265): " +
        "a high ambiguity_mass (~0.9 on real code) means the per-symbol mapping is " +
        "near-random ties — treat it as UNRELIABLE and lean on the aggregate " +
        "coverage/fidelity/cycle-consistency instead; per-row is_ambiguous flags " +
        "each coin-flip. members_a/members_b restrict the returned mapping to a " +
        "subsystem member-set (symbol_ids on the repo_a/repo_b side). exclude_identity " +
        "drops trivial s↦s rows for single-repo endofunctor queries (default true when " +
        "repo_a===repo_b). limit caps mapping rows (sorted pair_fidelity desc, then " +
        "similarity desc). When no functor passes the filters the result carries " +
        "functor:null plus a _note giving the best-available scores, unknown-repo " +
        "listing, or a hom-profile staleness flag.",
      inputSchema: FUNCTOR_BETWEEN_SCHEMA,
    },
    async (args) => {
      const result = await functorBetween({
        repo_a: args.repo_a,
        repo_b: args.repo_b,
        direction: args.direction,
        min_coverage: args.min_coverage,
        min_fidelity: args.min_fidelity,
        min_pair_fidelity: args.min_pair_fidelity,
        min_margin: args.min_margin,
        limit: args.limit,
        members_a: args.members_a,
        members_b: args.members_b,
        exclude_identity: args.exclude_identity,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );
}

