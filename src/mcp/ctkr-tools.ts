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
 * variable (the path to .metacoding/); falls back to the Orchestrators corpus
 * at ~/projects/Orchestrators/.metacoding.
 *
 * server.ts calls registerCtkrTools(server) to wire these into the MCP server.
 */

import { join } from "node:path";
import { z } from "zod";
import type { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { openCtkrArtifacts } from "../ctkr/artifacts.ts";
import { EDGE_KIND_VALUES } from "../store/types.ts";
import type {
  CentralityRow,
  EdgeKind,
  EvidenceRow,
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

// ---------------------------------------------------------------------------
// Registration
// ---------------------------------------------------------------------------

/**
 * Register all five CTKR Phase 1 tools on the given McpServer.
 * Call this from server.ts after the existing graph tool registrations.
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
}

