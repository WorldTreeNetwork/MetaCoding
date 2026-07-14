/**
 * CTKR Layer-1 artifact loader.
 *
 * Opens a single DuckDB connection over the .metacoding/ctkr/ directory
 * and exposes typed query methods for all Phase 1 MCP tools.
 *
 * Usage:
 *   const h = await openCtkrArtifacts("/path/to/.metacoding");
 *   const motifs = await h.motifs({ minSupport: 10 });
 *   await h.close();
 */

import { DuckDBInstance, type DuckDBConnection } from "@duckdb/node-api";
import { join, isAbsolute } from "node:path";
import type {
  ArtifactManifest,
  CentralityRow,
  DataShapeRow,
  EdgeKind,
  EmbeddingRow,
  EvidenceRow,
  FunctorEdgeRow,
  FunctorRow,
  HomProfileRow,
  InterfaceRow,
  MotifInstanceRow,
  MotifRow,
  NNIndexMeta,
  NNLabelRow,
  OperadRow,
  PatternRow,
  ShapePDRow,
  SpectralClusterRow,
  SubsystemCard,
  SubsystemMemberRow,
  SubsystemRow,
  WassersteinH1Row,
} from "./types.ts";

// ---------------------------------------------------------------------------
// Public interface
// ---------------------------------------------------------------------------

export interface CtkrHandle {
  /** Returns motif rows with optional filters. */
  motifs(opts?: {
    minSupport?: number;
    edgeKinds?: EdgeKind[];
    repoCoverageMin?: number;
    limit?: number;
  }): Promise<MotifRow[]>;

  motifInstances(
    motifId: string,
    opts?: { limit?: number },
  ): Promise<MotifInstanceRow[]>;

  /**
   * Returns discovered functor rows (functors.parquet, Phase 2b) with optional
   * pushdown filters, mirroring `motifs`. One row per directed `(repo_src,
   * repo_dst, config)` run. Ordered by `coverage * fidelity` descending (the
   * MCP tool's "best available" ordering); fidelity `-1` (edgeless / no
   * evidence) sorts to the bottom and is dropped by any `minFidelity > 0`.
   */
  functors(opts?: {
    repoSrc?: string;
    repoDst?: string;
    minCoverage?: number;
    minFidelity?: number;
    limit?: number;
  }): Promise<FunctorRow[]>;

  /**
   * Returns the object↦object correspondence rows for one functor
   * (functor_edges.parquet), mirroring `motifInstances`. Ordered by
   * `pair_fidelity` descending then `similarity` descending; the `-1`
   * (no-evidence) pair-fidelity sentinel sorts last. `minPairFidelity`
   * filters out no-evidence rows when `> -1`.
   */
  functorEdges(
    functorId: string,
    opts?: {
      minPairFidelity?: number;
      minSimilarity?: number;
      limit?: number;
    },
  ): Promise<FunctorEdgeRow[]>;

  embeddings(opts?: { symbolIds?: string[] }): Promise<EmbeddingRow[]>;

  /**
   * KNN query pushed into DuckDB using list_inner_product.
   * Vectors must be L2-normalized (node2vec writes them pre-normalized).
   * Returns at most k rows sorted by cosine distance ascending.
   */
  nearestByVector(opts: {
    seedVec: number[];
    seedId: string;
    k: number;
    seedRepo?: string;
  }): Promise<Array<{ symbol_id: string; qualified_name: string; repo: string; distance: number }>>;

  /** Returns the NNIndexMeta from nn_index/nn_index.meta.json. */
  nnIndexMeta(): Promise<NNIndexMeta>;

  /**
   * Returns label rows mapping ordinal positions to symbol_ids.
   * The nn_index/ does not include a Parquet label file by default —
   * this falls back to reading the symbol_id list from embeddings.parquet
   * in ordinal order if no dedicated labels file is present.
   */
  nnLabels(): Promise<NNLabelRow[]>;

  shapePds(repo?: string): Promise<ShapePDRow[]>;

  wassersteinH1(opts?: {
    repoA?: string;
    repoB?: string;
  }): Promise<WassersteinH1Row[]>;

  centrality(opts?: {
    repo?: string;
    topK?: number;
    metric?: "pagerank" | "betweenness" | "eigenvector";
  }): Promise<CentralityRow[]>;

  spectralClusters(opts?: { repo?: string }): Promise<SpectralClusterRow[]>;

  /**
   * Reads subsystem rows (subsystems.parquet, Stage A). Filter by repo and/or
   * a persistence floor (min co-association across the sweep). Ordered by
   * n_members descending (largest subsystem first).
   */
  subsystems(opts?: {
    repo?: string;
    minPersistence?: number;
  }): Promise<SubsystemRow[]>;

  /**
   * Reads subsystem member rows (subsystem_members.parquet). Filter by repo,
   * a specific subsystem_id, and/or a boundary_confidence floor. Ordered by
   * boundary_confidence descending (interior members first).
   */
  subsystemMembers(opts?: {
    repo?: string;
    subsystemId?: string;
    minBoundaryConfidence?: number;
    limit?: number;
  }): Promise<SubsystemMemberRow[]>;

  /**
   * Reads interface (boundary-morphism) rows (interfaces.parquet, Stage B).
   * Filter by repo, subsystem_id, and/or direction ("provides" | "consumes").
   * Ordered by direction, then edge_count descending (the strongest crossings
   * first).
   */
  interfaces(opts?: {
    repo?: string;
    subsystemId?: string;
    direction?: "provides" | "consumes";
    limit?: number;
  }): Promise<InterfaceRow[]>;

  /**
   * Reads data-shape rows (data_shapes.parquet, Stage B). Filter by repo,
   * subsystem_id, and/or boundaryOnly (only types that cross the interface).
   * Ordered by boundary (crossing types first), then type then field.
   */
  dataShapes(opts?: {
    repo?: string;
    subsystemId?: string;
    boundaryOnly?: boolean;
    limit?: number;
  }): Promise<DataShapeRow[]>;

  /**
   * Reads operad (composition-law) rows (operads.parquet, Stage C / §4.3, T4).
   * Filter by repo, subsystem_id, view ("orbit" | "similarity"), op_kind
   * ("path" | "fan_in" | "non_operadic"), a support floor, and/or boundaryOnly
   * (only protocol ops). Ordered by is_boundary_op desc (protocol ops first),
   * then support desc (the strongest laws first), then operation_id.
   */
  operads(opts?: {
    repo?: string;
    subsystemId?: string;
    view?: "orbit" | "similarity";
    opKind?: "path" | "fan_in" | "non_operadic";
    minSupport?: number;
    boundaryOnly?: boolean;
    limit?: number;
  }): Promise<OperadRow[]>;

  /**
   * Reads rows from hom_profiles.parquet. Filters by symbol IDs and/or
   * repo. Profiles come back at maximal precision (raw integer counts);
   * callers re-normalise / discretize at query time via the helpers in
   * ./homProfile.ts.
   */
  homProfiles(opts?: {
    symbolIds?: string[];
    repo?: string;
    qualifiedName?: string;
    limit?: number;
  }): Promise<HomProfileRow[]>;

  /**
   * Look up a single hom-profile by symbol_id. Returns null when the
   * symbol isn't in the artifact (e.g. it was filtered at write time
   * via --kinds-filter).
   */
  homProfileBySymbolId(symbolId: string): Promise<HomProfileRow | null>;

  /**
   * K-nearest hom-profiles to ``seedId`` by cosine distance over the raw
   * count vectors. v1 is a brute-force DuckDB scan via list_cosine_distance —
   * adequate for the ~200k-symbol corpus; swap in HNSW later if needed.
   *
   * Returns at most k rows ordered by distance ascending (closest first).
   * The seed row itself is excluded. Pass ``differentRepoOnly`` to restrict
   * matches to a different repo from the seed — the cross-repo "same role"
   * predicate Phase 2a is built on.
   */
  homProfilesKnn(opts: {
    seedId: string;
    k: number;
    differentRepoOnly?: boolean;
    sameRepoOnly?: boolean;
  }): Promise<
    Array<{
      symbol_id: string;
      qualified_name: string;
      repo: string;
      distance: number;
    }>
  >;

  /** L3 — reads from patterns.jsonl (not Parquet). */
  patterns(opts?: {
    sourceKind?: string;
    minConfidence?: number;
    label?: string;
  }): Promise<PatternRow[]>;

  /** L3 — reads from evidence.jsonl (not Parquet). */
  evidence(patternId: string): Promise<EvidenceRow[]>;

  /**
   * Stage E — reads the fused spec deck from subsystem_cards.jsonl (not
   * Parquet). Filter by repo and/or a specific subsystem_id. Ordered by
   * n_members descending (the largest subsystem's card first).
   */
  subsystemCards(opts?: {
    repo?: string;
    subsystemId?: string;
  }): Promise<SubsystemCard[]>;

  /**
   * Returns the distinct set of pattern_ids that have at least one evidence
   * row with the given repo. Used to avoid N+1 queries in instances_in_repo.
   */
  patternIdsWithEvidenceInRepo(repo: string): Promise<Set<string>>;

  manifest(): Promise<ArtifactManifest>;
  close(): Promise<void>;
}

// ---------------------------------------------------------------------------
// Factory
// ---------------------------------------------------------------------------

/**
 * Opens a CtkrHandle backed by a single DuckDB in-memory instance.
 *
 * @param dataDir  Path to the `.metacoding/` directory.
 *                 Must be an absolute path with no `..` segments.
 *                 Artifact paths are resolved as `dataDir/ctkr/<file>`.
 */
export async function openCtkrArtifacts(
  dataDir: string,
): Promise<CtkrHandle> {
  // Validate path: must be absolute and must not contain path traversal.
  if (!isAbsolute(dataDir)) {
    throw new Error(
      `openCtkrArtifacts: dataDir must be an absolute path, got: ${dataDir}`,
    );
  }
  if (dataDir.split("/").includes("..")) {
    throw new Error(
      `openCtkrArtifacts: dataDir must not contain ".." segments, got: ${dataDir}`,
    );
  }

  const ctkrDir = join(dataDir, "ctkr");
  // Use the module-level cache so multiple handles in the same process share
  // one DuckDB in-memory instance. Calling closeSync() on a cached instance
  // corrupts the native global state (DuckDB bug in ≤1.5.3), so close() only
  // disconnects the connection; the cached instance lives for the process.
  const instance = await DuckDBInstance.fromCache(":memory:");
  const conn = await instance.connect();
  return new CtkrHandleImpl(ctkrDir, conn);
}

// ---------------------------------------------------------------------------
// Implementation
// ---------------------------------------------------------------------------

/**
 * Convert a DuckDB result set to plain objects keyed by column name.
 * DuckDB's node-api returns bigint for INTEGER/BIGINT columns; we coerce
 * them to number since our row types use number throughout.
 */
function toObjects(
  result: Awaited<ReturnType<DuckDBConnection["runAndReadAll"]>>,
): Record<string, unknown>[] {
  const names = result.columnNames();
  const rows = result.getRows();
  return rows.map((row) => {
    const obj: Record<string, unknown> = {};
    for (let i = 0; i < names.length; i++) {
      const name = names[i]!;
      const val = row[i];
      obj[name] = coerceValue(val);
    }
    return obj;
  });
}

/** Recursively coerce DuckDB value types to plain JS values.
 *
 * DuckDB's node-api returns specialized objects for complex types:
 * - BIGINT/INTEGER → bigint  (coerce to number)
 * - LIST/ARRAY     → DuckDBListValue { items: unknown[] }
 * - STRUCT/JSON    → DuckDBStructValue { entries: Record<string, unknown> }
 *
 * Assumption: the Parquet schemas under .metacoding/ctkr/ only contain
 * primitives (string, int, float, bool), LIST<primitive>, and STRUCT<primitive>.
 * Types this function does NOT explicitly handle (BLOB, TIMESTAMP, BIT,
 * UUID, INTERVAL, DECIMAL, etc.) will fall through to the plain-object path
 * and be coerced field-by-field, which is wrong for non-struct values. If a
 * new artifact ever uses one of those types, add an explicit branch here.
 */
function coerceValue(v: unknown): unknown {
  if (typeof v === "bigint") return Number(v);
  if (Array.isArray(v)) return v.map(coerceValue);
  if (v !== null && typeof v === "object") {
    // DuckDBListValue: { items: unknown[] }
    if ("items" in v && Array.isArray((v as Record<string, unknown>)["items"])) {
      return ((v as Record<string, unknown>)["items"] as unknown[]).map(coerceValue);
    }
    // DuckDBStructValue: { entries: Record<string, unknown> }
    if ("entries" in v && typeof (v as Record<string, unknown>)["entries"] === "object") {
      const entries = (v as Record<string, unknown>)["entries"] as Record<string, unknown>;
      const out: Record<string, unknown> = {};
      for (const [k, val] of Object.entries(entries)) {
        out[k] = coerceValue(val);
      }
      return out;
    }
    // Plain object (e.g. already-decoded JSON).
    const out: Record<string, unknown> = {};
    for (const [k, val] of Object.entries(v as Record<string, unknown>)) {
      out[k] = coerceValue(val);
    }
    return out;
  }
  return v;
}

class CtkrHandleImpl implements CtkrHandle {
  constructor(
    private readonly ctkrDir: string,
    private readonly conn: DuckDBConnection,
  ) {}

  private path(file: string): string {
    return join(this.ctkrDir, file);
  }

  /**
   * Checks presence flags in manifest.json and throws a clear error
   * if the requested artifact is marked absent.
   */
  private async requireArtifact(flag: keyof ArtifactManifest): Promise<void> {
    const mf = await this.manifest();
    if (!mf[flag]) {
      throw new Error(
        `Artifact "${String(flag)}" is not present in the CTKR directory ` +
          `(manifest at ${this.path("manifest.json")} says ${String(flag)}=false). ` +
          `Re-run the appropriate ctkr sub-command to generate it.`,
      );
    }
  }

  async manifest(): Promise<ArtifactManifest> {
    const text = await Bun.file(this.path("manifest.json")).text();
    return JSON.parse(text) as ArtifactManifest;
  }

  async motifs(opts?: {
    minSupport?: number;
    edgeKinds?: EdgeKind[];
    repoCoverageMin?: number;
    limit?: number;
  }): Promise<MotifRow[]> {
    await this.requireArtifact("motifs");

    const clauses: string[] = [];
    const params: Record<string, string | number> = {};

    if (opts?.minSupport !== undefined) {
      clauses.push(`support >= ${opts.minSupport}`);
    }

    if (opts?.repoCoverageMin !== undefined) {
      clauses.push(`len(repo_coverage) >= ${opts.repoCoverageMin}`);
    }

    if (opts?.edgeKinds !== undefined && opts.edgeKinds.length > 0) {
      // Filter rows where edge_kinds array contains at least one of the
      // requested kinds. Build parameterized list using $ek0, $ek1, ...
      // DuckDB: list_has_any(edge_kinds, [$ek0, $ek1, ...])
      const paramNames = opts.edgeKinds.map((k, i) => {
        const name = `ek${i}`;
        params[name] = k;
        return `$${name}`;
      });
      clauses.push(`list_has_any(edge_kinds, [${paramNames.join(", ")}])`);
    }

    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const limitClause =
      opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";

    // Path is always server-controlled (ctkrDir validated at open time) — not user input.
    const sql = `SELECT * FROM read_parquet('${this.path("motifs.parquet")}') ${where} ORDER BY support DESC ${limitClause}`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as MotifRow[];
  }

  async motifInstances(
    motifId: string,
    opts?: { limit?: number },
  ): Promise<MotifInstanceRow[]> {
    await this.requireArtifact("motif_instances");

    const limitClause =
      opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    const sql = `SELECT * FROM read_parquet('${this.path("motif_instances.parquet")}') WHERE motif_id = $motif_id ${limitClause}`;
    const result = await this.conn.runAndReadAll(sql, { motif_id: motifId });
    return toObjects(result) as unknown as MotifInstanceRow[];
  }

  async functors(opts?: {
    repoSrc?: string;
    repoDst?: string;
    minCoverage?: number;
    minFidelity?: number;
    limit?: number;
  }): Promise<FunctorRow[]> {
    await this.requireArtifact("functors");

    const clauses: string[] = [];
    const params: Record<string, string> = {};

    if (opts?.repoSrc !== undefined) {
      clauses.push(`repo_src = $repo_src`);
      params["repo_src"] = opts.repoSrc;
    }
    if (opts?.repoDst !== undefined) {
      clauses.push(`repo_dst = $repo_dst`);
      params["repo_dst"] = opts.repoDst;
    }
    if (opts?.minCoverage !== undefined) {
      clauses.push(`coverage >= ${opts.minCoverage}`);
    }
    if (opts?.minFidelity !== undefined) {
      // A `-1` fidelity (edgeless / no evidence) must fail any `minFidelity > 0`.
      clauses.push(`fidelity >= ${opts.minFidelity}`);
    }

    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const limitClause = opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    // Path is server-controlled (ctkrDir validated at open time) — not user input.
    const sql =
      `SELECT * FROM read_parquet('${this.path("functors.parquet")}') ${where} ` +
      `ORDER BY coverage * fidelity DESC, functor_id ${limitClause}`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as FunctorRow[];
  }

  async functorEdges(
    functorId: string,
    opts?: {
      minPairFidelity?: number;
      minSimilarity?: number;
      minMargin?: number;
      limit?: number;
    },
  ): Promise<FunctorEdgeRow[]> {
    await this.requireArtifact("functor_edges");

    const clauses: string[] = [`functor_id = $functor_id`];
    const params: Record<string, string> = { functor_id: functorId };

    if (opts?.minPairFidelity !== undefined) {
      clauses.push(`pair_fidelity >= ${opts.minPairFidelity}`);
    }
    if (opts?.minSimilarity !== undefined) {
      clauses.push(`similarity >= ${opts.minSimilarity}`);
    }
    // MetaCoding-265: margin gate — drop coin-flip ties whose margin is below the
    // caller's confidence floor, so an agent can request only resolved mappings.
    if (opts?.minMargin !== undefined) {
      clauses.push(`margin >= ${opts.minMargin}`);
    }

    const limitClause = opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    const sql =
      `SELECT * FROM read_parquet('${this.path("functor_edges.parquet")}') ` +
      `WHERE ${clauses.join(" AND ")} ` +
      `ORDER BY pair_fidelity DESC, similarity DESC, src_symbol_id ${limitClause}`;
    const result = await this.conn.runAndReadAll(sql, params);
    return toObjects(result) as unknown as FunctorEdgeRow[];
  }

  async embeddings(opts?: {
    symbolIds?: string[];
  }): Promise<EmbeddingRow[]> {
    await this.requireArtifact("embeddings");

    let sql: string;
    let params: Record<string, string> | undefined;

    if (opts?.symbolIds !== undefined && opts.symbolIds.length > 0) {
      // Parameterize each symbol_id as $sid0, $sid1, ...
      const paramEntries: Record<string, string> = {};
      const paramNames = opts.symbolIds.map((id, i) => {
        const name = `sid${i}`;
        paramEntries[name] = id;
        return `$${name}`;
      });
      sql = `SELECT * FROM read_parquet('${this.path("embeddings.parquet")}') WHERE symbol_id IN (${paramNames.join(", ")})`;
      params = paramEntries;
    } else {
      sql = `SELECT * FROM read_parquet('${this.path("embeddings.parquet")}')`;
    }

    const result = await this.conn.runAndReadAll(sql, params);
    return toObjects(result) as unknown as EmbeddingRow[];
  }

  async nearestByVector(opts: {
    seedVec: number[];
    seedId: string;
    k: number;
    seedRepo?: string;
  }): Promise<Array<{ symbol_id: string; qualified_name: string; repo: string; distance: number }>> {
    await this.requireArtifact("embeddings");

    // The seed vector is server-generated (read from our own parquet) — safe to inline.
    // list_inner_product on L2-normalized vectors = cosine similarity.
    const vecLiteral = `[${opts.seedVec.join(", ")}]::FLOAT[]`;
    const repoClause = opts.seedRepo !== undefined ? `AND repo != $seed_repo` : "";

    // list_cosine_distance = 1 - cosine_similarity, always in [0, 2].
    // Works on non-normalized vectors unlike list_inner_product.
    const sql =
      `SELECT symbol_id, qualified_name, repo, ` +
      `list_cosine_distance(vec::FLOAT[], ${vecLiteral}) AS distance ` +
      `FROM read_parquet('${this.path("embeddings.parquet")}') ` +
      `WHERE symbol_id != $seed_id ${repoClause} ` +
      `ORDER BY distance ASC ` +
      `LIMIT ${opts.k}`;

    const params: Record<string, string> = { seed_id: opts.seedId };
    if (opts.seedRepo !== undefined) params["seed_repo"] = opts.seedRepo;

    const result = await this.conn.runAndReadAll(sql, params);
    const names = result.columnNames();
    const rows = result.getRows();
    return rows.map((row) => {
      const obj: Record<string, unknown> = {};
      for (let i = 0; i < names.length; i++) {
        const v = row[i];
        obj[names[i]!] = typeof v === "bigint" ? Number(v) : v;
      }
      return {
        symbol_id: obj["symbol_id"] as string,
        qualified_name: obj["qualified_name"] as string,
        repo: obj["repo"] as string,
        distance: obj["distance"] as number,
      };
    });
  }

  async nnIndexMeta(): Promise<NNIndexMeta> {
    await this.requireArtifact("nn_index");
    const metaPath = this.path("nn_index/nn_index.meta.json");
    const text = await Bun.file(metaPath).text();
    return JSON.parse(text) as NNIndexMeta;
  }

  async nnLabels(): Promise<NNLabelRow[]> {
    await this.requireArtifact("nn_index");

    // Check if a dedicated labels parquet exists; fall back to embeddings ordinal order.
    const labelsPath = this.path("nn_index/nn_labels.parquet");
    const labelsFile = Bun.file(labelsPath);

    if (await labelsFile.exists()) {
      const sql = `SELECT rowid AS ordinal, symbol_id FROM read_parquet('${labelsPath}') ORDER BY rowid`;
      const result = await this.conn.runAndReadAll(sql);
      return toObjects(result) as unknown as NNLabelRow[];
    }

    // Fallback: derive ordinal from embeddings.parquet row order.
    await this.requireArtifact("embeddings");
    const sql = `SELECT row_number() OVER () - 1 AS ordinal, symbol_id FROM read_parquet('${this.path("embeddings.parquet")}')`;
    const result = await this.conn.runAndReadAll(sql);
    return toObjects(result) as unknown as NNLabelRow[];
  }

  async shapePds(repo?: string): Promise<ShapePDRow[]> {
    await this.requireArtifact("shape_pds");

    let sql: string;
    let params: Record<string, string> | undefined;

    if (repo !== undefined) {
      sql = `SELECT * FROM read_parquet('${this.path("shape_pds.parquet")}') WHERE repo = $repo ORDER BY repo, dim`;
      params = { repo };
    } else {
      sql = `SELECT * FROM read_parquet('${this.path("shape_pds.parquet")}') ORDER BY repo, dim`;
    }

    const result = await this.conn.runAndReadAll(sql, params);
    return toObjects(result) as unknown as ShapePDRow[];
  }

  async wassersteinH1(opts?: {
    repoA?: string;
    repoB?: string;
  }): Promise<WassersteinH1Row[]> {
    await this.requireArtifact("wasserstein_h1");

    const clauses: string[] = [];
    const params: Record<string, string> = {};

    if (opts?.repoA !== undefined) {
      clauses.push(`(repo_a = $repo_a OR repo_b = $repo_a)`);
      params["repo_a"] = opts.repoA;
    }
    if (opts?.repoB !== undefined) {
      clauses.push(`(repo_a = $repo_b OR repo_b = $repo_b)`);
      params["repo_b"] = opts.repoB;
    }

    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const sql = `SELECT * FROM read_parquet('${this.path("wasserstein_h1.parquet")}') ${where} ORDER BY distance`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as WassersteinH1Row[];
  }

  async centrality(opts?: {
    repo?: string;
    topK?: number;
    metric?: "pagerank" | "betweenness" | "eigenvector";
  }): Promise<CentralityRow[]> {
    await this.requireArtifact("centrality");

    const metric = opts?.metric ?? "pagerank";
    // metric is constrained to a TS union — not user-controlled string, safe to interpolate.
    let sql: string;
    let params: Record<string, string> | undefined;

    if (opts?.repo !== undefined) {
      const limitClause =
        opts?.topK !== undefined ? `LIMIT ${opts.topK}` : "";
      sql = `SELECT * FROM read_parquet('${this.path("centrality.parquet")}') WHERE repo = $repo ORDER BY ${metric} DESC ${limitClause}`;
      params = { repo: opts.repo };
    } else {
      const limitClause =
        opts?.topK !== undefined ? `LIMIT ${opts.topK}` : "";
      sql = `SELECT * FROM read_parquet('${this.path("centrality.parquet")}') ORDER BY ${metric} DESC ${limitClause}`;
    }

    const result = await this.conn.runAndReadAll(sql, params);
    return toObjects(result) as unknown as CentralityRow[];
  }

  async spectralClusters(opts?: {
    repo?: string;
  }): Promise<SpectralClusterRow[]> {
    await this.requireArtifact("spectral_clusters");

    let sql: string;
    let params: Record<string, string> | undefined;

    if (opts?.repo !== undefined) {
      sql = `SELECT * FROM read_parquet('${this.path("spectral_clusters.parquet")}') WHERE repo = $repo ORDER BY repo, cluster_id`;
      params = { repo: opts.repo };
    } else {
      sql = `SELECT * FROM read_parquet('${this.path("spectral_clusters.parquet")}') ORDER BY repo, cluster_id`;
    }

    const result = await this.conn.runAndReadAll(sql, params);
    return toObjects(result) as unknown as SpectralClusterRow[];
  }

  async subsystems(opts?: {
    repo?: string;
    minPersistence?: number;
  }): Promise<SubsystemRow[]> {
    await this.requireArtifact("subsystems");

    const clauses: string[] = [];
    const params: Record<string, string> = {};
    if (opts?.repo !== undefined) {
      clauses.push(`repo = $repo`);
      params["repo"] = opts.repo;
    }
    if (opts?.minPersistence !== undefined) {
      clauses.push(`persistence_score >= ${opts.minPersistence}`);
    }
    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const sql = `SELECT * FROM read_parquet('${this.path("subsystems.parquet")}') ${where} ORDER BY n_members DESC, subsystem_id`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as SubsystemRow[];
  }

  async subsystemMembers(opts?: {
    repo?: string;
    subsystemId?: string;
    minBoundaryConfidence?: number;
    limit?: number;
  }): Promise<SubsystemMemberRow[]> {
    await this.requireArtifact("subsystem_members");

    const clauses: string[] = [];
    const params: Record<string, string> = {};
    if (opts?.repo !== undefined) {
      clauses.push(`repo = $repo`);
      params["repo"] = opts.repo;
    }
    if (opts?.subsystemId !== undefined) {
      clauses.push(`subsystem_id = $subsystem_id`);
      params["subsystem_id"] = opts.subsystemId;
    }
    if (opts?.minBoundaryConfidence !== undefined) {
      clauses.push(`boundary_confidence >= ${opts.minBoundaryConfidence}`);
    }
    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const limitClause = opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    const sql =
      `SELECT * FROM read_parquet('${this.path("subsystem_members.parquet")}') ${where} ` +
      `ORDER BY boundary_confidence DESC, symbol_id ${limitClause}`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as SubsystemMemberRow[];
  }

  async interfaces(opts?: {
    repo?: string;
    subsystemId?: string;
    direction?: "provides" | "consumes";
    limit?: number;
  }): Promise<InterfaceRow[]> {
    await this.requireArtifact("interfaces");

    const clauses: string[] = [];
    const params: Record<string, string> = {};
    if (opts?.repo !== undefined) {
      clauses.push(`repo = $repo`);
      params["repo"] = opts.repo;
    }
    if (opts?.subsystemId !== undefined) {
      clauses.push(`subsystem_id = $subsystem_id`);
      params["subsystem_id"] = opts.subsystemId;
    }
    if (opts?.direction !== undefined) {
      // direction is a TS union — safe to compare via a bound param.
      clauses.push(`direction = $direction`);
      params["direction"] = opts.direction;
    }
    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const limitClause = opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    const sql =
      `SELECT * FROM read_parquet('${this.path("interfaces.parquet")}') ${where} ` +
      `ORDER BY direction, edge_count DESC, internal_symbol_id, external_symbol_id ${limitClause}`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as InterfaceRow[];
  }

  async dataShapes(opts?: {
    repo?: string;
    subsystemId?: string;
    boundaryOnly?: boolean;
    limit?: number;
  }): Promise<DataShapeRow[]> {
    await this.requireArtifact("data_shapes");

    const clauses: string[] = [];
    const params: Record<string, string> = {};
    if (opts?.repo !== undefined) {
      clauses.push(`repo = $repo`);
      params["repo"] = opts.repo;
    }
    if (opts?.subsystemId !== undefined) {
      clauses.push(`subsystem_id = $subsystem_id`);
      params["subsystem_id"] = opts.subsystemId;
    }
    if (opts?.boundaryOnly) {
      clauses.push(`boundary = true`);
    }
    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const limitClause = opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    const sql =
      `SELECT * FROM read_parquet('${this.path("data_shapes.parquet")}') ${where} ` +
      `ORDER BY boundary DESC, type_qualified_name, field_name NULLS FIRST ${limitClause}`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as DataShapeRow[];
  }

  async operads(opts?: {
    repo?: string;
    subsystemId?: string;
    view?: "orbit" | "similarity";
    opKind?: "path" | "fan_in" | "non_operadic";
    minSupport?: number;
    boundaryOnly?: boolean;
    limit?: number;
  }): Promise<OperadRow[]> {
    await this.requireArtifact("operads");

    const clauses: string[] = [];
    const params: Record<string, string> = {};
    if (opts?.repo !== undefined) {
      clauses.push(`repo = $repo`);
      params["repo"] = opts.repo;
    }
    if (opts?.subsystemId !== undefined) {
      clauses.push(`subsystem_id = $subsystem_id`);
      params["subsystem_id"] = opts.subsystemId;
    }
    if (opts?.view !== undefined) {
      // view is a TS union — safe to compare via a bound param.
      clauses.push(`view = $view`);
      params["view"] = opts.view;
    }
    if (opts?.opKind !== undefined) {
      clauses.push(`op_kind = $op_kind`);
      params["op_kind"] = opts.opKind;
    }
    if (opts?.minSupport !== undefined) {
      clauses.push(`support >= ${opts.minSupport}`);
    }
    if (opts?.boundaryOnly) {
      clauses.push(`is_boundary_op = true`);
    }
    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const limitClause = opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    const sql =
      `SELECT * FROM read_parquet('${this.path("operads.parquet")}') ${where} ` +
      `ORDER BY is_boundary_op DESC, support DESC, operation_id ${limitClause}`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as OperadRow[];
  }

  async homProfiles(opts?: {
    symbolIds?: string[];
    repo?: string;
    qualifiedName?: string;
    limit?: number;
  }): Promise<HomProfileRow[]> {
    await this.requireArtifact("hom_profiles");

    const clauses: string[] = [];
    const params: Record<string, string> = {};

    if (opts?.symbolIds !== undefined && opts.symbolIds.length > 0) {
      const paramNames = opts.symbolIds.map((id, i) => {
        const name = `sid${i}`;
        params[name] = id;
        return `$${name}`;
      });
      clauses.push(`symbol_id IN (${paramNames.join(", ")})`);
    }
    if (opts?.repo !== undefined) {
      clauses.push(`repo = $repo`);
      params["repo"] = opts.repo;
    }
    if (opts?.qualifiedName !== undefined) {
      clauses.push(`qualified_name = $qualified_name`);
      params["qualified_name"] = opts.qualifiedName;
    }

    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const limitClause = opts?.limit !== undefined ? `LIMIT ${opts.limit}` : "";
    const sql = `SELECT * FROM read_parquet('${this.path("hom_profiles.parquet")}') ${where} ${limitClause}`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as HomProfileRow[];
  }

  async homProfileBySymbolId(symbolId: string): Promise<HomProfileRow | null> {
    const rows = await this.homProfiles({ symbolIds: [symbolId] });
    return rows[0] ?? null;
  }

  async homProfilesKnn(opts: {
    seedId: string;
    k: number;
    differentRepoOnly?: boolean;
    sameRepoOnly?: boolean;
  }): Promise<
    Array<{
      symbol_id: string;
      qualified_name: string;
      repo: string;
      distance: number;
    }>
  > {
    await this.requireArtifact("hom_profiles");
    if (opts.differentRepoOnly && opts.sameRepoOnly) {
      throw new Error(
        "homProfilesKnn: differentRepoOnly and sameRepoOnly are mutually exclusive",
      );
    }

    const parquetPath = this.path("hom_profiles.parquet");
    // Pulling the seed row first lets us inline the vector literal in the
    // outer scan — avoids DuckDB list-parameter encoding gymnastics and
    // mirrors how nearestByVector handles its seed.
    const seedSql =
      `SELECT profile_vec, repo FROM read_parquet('${parquetPath}') ` +
      `WHERE symbol_id = $seed_id LIMIT 1`;
    const seedResult = await this.conn.runAndReadAll(seedSql, {
      seed_id: opts.seedId,
    });
    const seedRows = seedResult.getRows();
    if (seedRows.length === 0) {
      throw new Error(
        `homProfilesKnn: seed symbol_id "${opts.seedId}" not found in ${parquetPath}`,
      );
    }
    const seedRow = seedRows[0]!;
    const rawVec = coerceValue(seedRow[0]) as number[];
    const seedRepo = seedRow[1] as string;
    const vecLiteral = `[${rawVec.join(", ")}]::FLOAT[]`;

    const params: Record<string, string> = { seed_id: opts.seedId };
    const clauses = [`symbol_id != $seed_id`];
    if (opts.differentRepoOnly) {
      clauses.push(`repo != $seed_repo`);
      params["seed_repo"] = seedRepo;
    } else if (opts.sameRepoOnly) {
      clauses.push(`repo = $seed_repo`);
      params["seed_repo"] = seedRepo;
    }

    // DuckDB's list_cosine_distance requires both sides to be the same
    // float type; cast UInt32 lists to FLOAT[] for the dot product.
    const sql =
      `SELECT symbol_id, qualified_name, repo, ` +
      `list_cosine_distance(profile_vec::FLOAT[], ${vecLiteral}) AS distance ` +
      `FROM read_parquet('${parquetPath}') ` +
      `WHERE ${clauses.join(" AND ")} ` +
      `ORDER BY distance ASC ` +
      `LIMIT ${opts.k}`;

    const result = await this.conn.runAndReadAll(sql, params);
    const names = result.columnNames();
    const rows = result.getRows();
    return rows.map((row) => {
      const obj: Record<string, unknown> = {};
      for (let i = 0; i < names.length; i++) {
        const v = row[i];
        obj[names[i]!] = typeof v === "bigint" ? Number(v) : v;
      }
      return {
        symbol_id: obj["symbol_id"] as string,
        qualified_name: obj["qualified_name"] as string,
        repo: obj["repo"] as string,
        distance: obj["distance"] as number,
      };
    });
  }

  async patterns(opts?: {
    sourceKind?: string;
    minConfidence?: number;
    label?: string;
  }): Promise<PatternRow[]> {
    const patternsPath = this.path("patterns.jsonl");
    const f = Bun.file(patternsPath);
    if (!(await f.exists())) {
      throw new Error(
        `L3 artifact not found: ${patternsPath}. Run the ctkr labeler to produce it.`,
      );
    }

    const clauses: string[] = [];
    const params: Record<string, string | number> = {};

    if (opts?.sourceKind !== undefined) {
      clauses.push(`source_kind = $source_kind`);
      params["source_kind"] = opts.sourceKind;
    }
    if (opts?.minConfidence !== undefined) {
      clauses.push(`confidence >= ${opts.minConfidence}`);
    }
    if (opts?.label !== undefined) {
      clauses.push(`label = $label`);
      params["label"] = opts.label;
    }

    const where = clauses.length > 0 ? `WHERE ${clauses.join(" AND ")}` : "";
    const sql = `SELECT * FROM read_json_auto('${patternsPath}') ${where} ORDER BY confidence DESC`;
    const result = await this.conn.runAndReadAll(
      sql,
      Object.keys(params).length > 0 ? params : undefined,
    );
    return toObjects(result) as unknown as PatternRow[];
  }

  async evidence(patternId: string): Promise<EvidenceRow[]> {
    const evidencePath = this.path("evidence.jsonl");
    const f = Bun.file(evidencePath);
    if (!(await f.exists())) {
      throw new Error(
        `L3 artifact not found: ${evidencePath}. Run the ctkr evidence retriever to produce it.`,
      );
    }

    const sql = `SELECT * FROM read_json_auto('${evidencePath}') WHERE pattern_id = $pattern_id`;
    const result = await this.conn.runAndReadAll(sql, { pattern_id: patternId });
    return toObjects(result) as unknown as EvidenceRow[];
  }

  async subsystemCards(opts?: {
    repo?: string;
    subsystemId?: string;
  }): Promise<SubsystemCard[]> {
    // The card is deeply nested JSON; parse the JSONL line-by-line to preserve
    // structure faithfully rather than flattening through DuckDB. The deck is
    // one card per subsystem — small enough to read whole and filter in JS.
    const deckPath = this.path("subsystem_cards.jsonl");
    const f = Bun.file(deckPath);
    if (!(await f.exists())) {
      throw new Error(
        `Spec deck not found: ${deckPath}. Run \`ctkr extract-spec\` to generate it.`,
      );
    }
    const text = await f.text();
    const cards: SubsystemCard[] = [];
    for (const line of text.split("\n")) {
      const trimmed = line.trim();
      if (!trimmed) continue;
      const card = JSON.parse(trimmed) as SubsystemCard;
      if (opts?.repo !== undefined && card.repo !== opts.repo) continue;
      if (opts?.subsystemId !== undefined && card.subsystem_id !== opts.subsystemId)
        continue;
      cards.push(card);
    }
    cards.sort((a, b) => b.n_members - a.n_members || a.card_id.localeCompare(b.card_id));
    return cards;
  }

  async patternIdsWithEvidenceInRepo(repo: string): Promise<Set<string>> {
    const evidencePath = this.path("evidence.jsonl");
    const f = Bun.file(evidencePath);
    if (!(await f.exists())) {
      return new Set();
    }

    const sql = `SELECT DISTINCT pattern_id FROM read_json_auto('${evidencePath}') WHERE repo = $repo`;
    const result = await this.conn.runAndReadAll(sql, { repo });
    const rows = result.getRows();
    return new Set(rows.map((r) => r[0] as string));
  }

  async close(): Promise<void> {
    // Only disconnect — the DuckDBInstance is shared via fromCache() and must
    // not be closed (doing so corrupts native state for subsequent handles).
    this.conn.closeSync();
  }
}

// Re-export row types for convenience so consumers can import from one place.
export type {
  ArtifactManifest,
  CentralityRow,
  DataShapeRow,
  EdgeKind,
  EmbeddingRow,
  EvidenceRow,
  FunctorEdgeRow,
  FunctorRow,
  HomProfileRow,
  InterfaceRow,
  MotifInstanceRow,
  MotifRow,
  NNIndexMeta,
  NNLabelRow,
  OperadRow,
  PatternRow,
  ShapePDRow,
  SpectralClusterRow,
  SubsystemCard,
  SubsystemMemberRow,
  SubsystemRow,
  WassersteinH1Row,
} from "./types.ts";
