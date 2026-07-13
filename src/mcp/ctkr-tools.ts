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
  EdgeKind,
  EvidenceRow,
  FunctorRow,
  MotifRow,
  PatternRow,
  SpectralClusterRow,
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
  truncated: boolean;
  /** Explanatory landscape note (alternatives, best-available, staleness, …). */
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

const FUNCTOR_BETWEEN_SCHEMA = {
  repo_a: z.string().min(1),
  repo_b: z.string().min(1),
  direction: z.enum(["a_to_b", "b_to_a", "both"]).optional(),
  min_coverage: z.number().min(0).max(1).optional(),
  min_fidelity: z.number().min(0).max(1).optional(),
  min_pair_fidelity: z.number().min(0).max(1).optional(),
  limit: z.number().int().min(1).max(5000).optional(),
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
  limit?: number;
}): Promise<FunctorBetweenResult> {
  const direction = input.direction ?? "a_to_b";
  const minCoverage = input.min_coverage ?? 0;
  const minFidelity = input.min_fidelity ?? 0;
  const minPairFidelity = input.min_pair_fidelity ?? 0;
  const limit = input.limit ?? 200;

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
      const edgeOpts: { minPairFidelity?: number; limit: number } = {
        limit: limit + 1,
      };
      if (minPairFidelity > 0) edgeOpts.minPairFidelity = minPairFidelity;
      const edges = await handle.functorEdges(chosen.functor_id, edgeOpts);
      truncated = edges.length > limit;
      mapping = edges.slice(0, limit).map((e) => ({
        src_symbol_id: e.src_symbol_id,
        src_qualified_name: e.src_qualified_name,
        dst_symbol_id: e.dst_symbol_id,
        dst_qualified_name: e.dst_qualified_name,
        similarity: e.similarity,
        margin: e.margin,
        pair_fidelity: e.pair_fidelity === -1 ? null : e.pair_fidelity,
      }));
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

    const result: FunctorBetweenResult = { functor, mapping, truncated };

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
    name: "ctkr.functor_between",
    summary:
      "Discover how two repos' designs correspond: the maximal partial " +
      "structure-preserving map (functor) between them, with per-correspondence " +
      "fidelity. Reads functors.parquet / functor_edges.parquet (discovery is the " +
      "batch runner's job). direction picks the stored direction(s); min_coverage / " +
      "min_fidelity gate the functor (min_fidelity=1.0 = strict functors only); " +
      "min_pair_fidelity filters mapping rows; results note alternatives, " +
      "best-available scores, and hom-profile staleness.",
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
        limit: { type: "integer", minimum: 1, maximum: 5000, default: 200 },
      },
    },
  },
];

/**
 * Register all seven CTKR tools on the given McpServer.
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
        "never read as 1.0). limit caps mapping rows (sorted pair_fidelity desc, then " +
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
        limit: args.limit,
      });
      return { content: [{ type: "text", text: JSON.stringify(result, null, 2) }] };
    },
  );
}

