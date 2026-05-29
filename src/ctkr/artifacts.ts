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
  EdgeKind,
  EmbeddingRow,
  EvidenceRow,
  MotifInstanceRow,
  MotifRow,
  NNIndexMeta,
  NNLabelRow,
  PatternRow,
  ShapePDRow,
  SpectralClusterRow,
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

  /** L3 — reads from patterns.jsonl (not Parquet). */
  patterns(opts?: {
    sourceKind?: string;
    minConfidence?: number;
    label?: string;
  }): Promise<PatternRow[]>;

  /** L3 — reads from evidence.jsonl (not Parquet). */
  evidence(patternId: string): Promise<EvidenceRow[]>;

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
  EdgeKind,
  EmbeddingRow,
  EvidenceRow,
  MotifInstanceRow,
  MotifRow,
  NNIndexMeta,
  NNLabelRow,
  PatternRow,
  ShapePDRow,
  SpectralClusterRow,
  WassersteinH1Row,
} from "./types.ts";
