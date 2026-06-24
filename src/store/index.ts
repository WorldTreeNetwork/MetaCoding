// The single swap-boundary for the graph + FTS store.
// Per docs/design/storage-integration.md: this is the only module that
// imports @ladybugdb/core or bun:sqlite. Everything else goes through Store.

import { mkdirSync, existsSync } from "node:fs";
import { join } from "node:path";

import { Database as LbugDb, Connection } from "@ladybugdb/core";
import { Database as SqliteDb } from "bun:sqlite";

import { ensureGraphSchema, ensureFtsSchema } from "./schema";
import type { Edge, Symbol, TokenRow } from "./types";

/** One repo's slice of a store summary — counts + provenance, no git. */
export interface RepoSnapshot {
  repo: string;
  repo_commit_sha: string | null;
  indexed_at: string | null; // ISO-8601 string; stringified defensively
  symbols: number;
}

/** A pure, git-free snapshot of what a store currently holds. */
export interface StoreSummary {
  dataDir: string;
  symbols: number; // total Symbol node count
  indexed: boolean; // symbols > 0
  repos: RepoSnapshot[];
}

/**
 * Coerce a ladybugdb temporal value (Date | {…} temporal | number | string |
 * null) into an ISO-8601 string, or null. Never throws.
 */
function toIsoStringOrNull(v: unknown): string | null {
  if (v === null || v === undefined) return null;
  try {
    if (v instanceof Date) return v.toISOString();
    if (typeof v === "number") return new Date(v).toISOString();
    if (typeof v === "string") return v;
    // Temporal-object shape (e.g. { year, month, day, ... }) or anything else:
    // try Date(...) on its string form, else fall back to JSON/String.
    const asDate = new Date(v as never);
    if (!Number.isNaN(asDate.getTime())) return asDate.toISOString();
    return String(v);
  } catch {
    return null;
  }
}

/**
 * True when an error from the ladybugdb/Connection constructor is the
 * single-writer file-lock failure (another serve/watch holds the store).
 */
function isLockError(err: unknown): boolean {
  const msg = (err instanceof Error ? err.message : String(err)).toLowerCase();
  return (
    msg.includes("lock") &&
    (msg.includes("graph.lbug") ||
      msg.includes("set lock") ||
      msg.includes("could not set lock"))
  );
}

export class Store {
  private constructor(
    private readonly graphDb: LbugDb,
    private readonly graphConn: Connection,
    private readonly fts: SqliteDb,
    readonly dataDir: string,
    /** True when opened read-only — coexists with a live writer (see
     *  scripts/spike-lock.ts); writes will throw at the engine. */
    readonly readOnly: boolean,
  ) {}

  /**
   * Open the store. By default this is the single read-WRITE owner and takes
   * ladybugdb's exclusive lock (only one writer at a time).
   *
   * Pass `{ readOnly: true }` for a reader (serve / query / status). ladybugdb's
   * exclusive lock excludes only OTHER WRITERS — a read-only handle coexists
   * with a running `metacoding index` on the same dir, both directions (matrix
   * proven in scripts/spike-lock.ts). A read-only handle is snapshot-pinned at
   * open time: it sees the last checkpoint, and a full reopen is required to
   * advance (scripts/spike-refresh.ts). Short-lived callers (query/status) get
   * this for free by reopening each invocation; serve reflects its startup
   * snapshot until restarted (reopen-on-refresh tracked separately).
   */
  static async open(
    dataDir: string,
    opts?: { readOnly?: boolean },
  ): Promise<Store> {
    mkdirSync(dataDir, { recursive: true });
    const graphPath = join(dataDir, "graph.lbug");
    const ftsPath = join(dataDir, "tokens.fts.sqlite");

    if (opts?.readOnly) {
      return Store.openReadOnly(dataDir, graphPath, ftsPath);
    }

    let graphDb: LbugDb;
    let graphConn: Connection;
    try {
      graphDb = new LbugDb(graphPath);
      graphConn = new Connection(graphDb);
    } catch (err) {
      // ladybugdb is single-writer. A running `metacoding serve`/`watch`
      // holds the store, so the constructor throws a raw lock IO error.
      // Rethrow with an actionable message, preserving the original cause.
      if (isLockError(err)) {
        throw new Error(
          `metacoding: store at ${dataDir} is locked by another process — ` +
            `a 'metacoding serve' or 'watch' is probably running on this repo. ` +
            `Stop it before indexing/querying.`,
          { cause: err },
        );
      }
      throw err;
    }
    const fts = new SqliteDb(ftsPath);

    await ensureGraphSchema(graphConn);
    ensureFtsSchema(fts);

    return new Store(graphDb, graphConn, fts, dataDir, false);
  }

  /**
   * Read-only open. A read-only handle can't create schema, and neither
   * ladybugdb nor SQLite can open a never-created store read-only — so if
   * nothing has indexed this dir yet, bootstrap an empty schema once via a
   * brief read-write open. We gate that bootstrap on the graph file's
   * existence: a running indexer creates graph.lbug immediately, so an existing
   * file means "attach read-only" (coexisting with the live writer) and we
   * never contend for the write lock.
   */
  private static async openReadOnly(
    dataDir: string,
    graphPath: string,
    ftsPath: string,
  ): Promise<Store> {
    if (!existsSync(graphPath) || !existsSync(ftsPath)) {
      try {
        const boot = await Store.open(dataDir); // RW create + ensure schema
        await boot.close();
      } catch (err) {
        // If a writer is mid-create it holds the lock and the schema will
        // exist momentarily; fall through to the read-only open. Any other
        // failure is fatal.
        if (!isLockError(err)) throw err;
      }
    }

    const graphDb = new LbugDb(graphPath, undefined, undefined, true);
    const graphConn = new Connection(graphDb);
    const fts = new SqliteDb(ftsPath, { readonly: true });

    return new Store(graphDb, graphConn, fts, dataDir, true);
  }

  /**
   * Pure store read: total Symbol count plus per-repo provenance. No git, no
   * process spawning. The single source of truth for "is this graph indexed?".
   */
  async summary(): Promise<StoreSummary> {
    const totalRows = await this.query<{ c: number | bigint }>(
      `MATCH (n:Symbol) RETURN count(n) AS c`,
    );
    const symbols = Number(totalRows[0]?.c ?? 0);

    const repoRows = await this.query<{
      repo: string | null;
      sha: string | null;
      symbols: number | bigint;
      indexed_at: unknown;
    }>(
      `MATCH (n:Symbol)
       RETURN n.repo AS repo, n.repo_commit_sha AS sha,
              count(n) AS symbols, max(n.indexed_at) AS indexed_at`,
    );

    const repos: RepoSnapshot[] = repoRows.map((r) => ({
      repo: r.repo ?? "",
      repo_commit_sha: r.sha ?? null,
      indexed_at: toIsoStringOrNull(r.indexed_at),
      symbols: Number(r.symbols ?? 0),
    }));

    return {
      dataDir: this.dataDir,
      symbols,
      indexed: symbols > 0,
      repos,
    };
  }

  async close(): Promise<void> {
    this.fts.close();
    await this.graphConn.close();
    await this.graphDb.close();
  }

  async query<T = Record<string, unknown>>(
    cypher: string,
    params?: Record<string, unknown>,
  ): Promise<T[]> {
    // ladybugdb's Connection has two paths:
    //   - query(statement)                — no parameters, statement-only.
    //   - prepare(statement) -> execute(stmt, params) — parameterized.
    // We branch here so callers see one uniform method.
    let qr;
    if (params && Object.keys(params).length > 0) {
      const stmt = await this.graphConn.prepare(cypher);
      if (!stmt.isSuccess()) {
        throw new Error(`prepare failed: ${stmt.getErrorMessage()}\n${cypher}`);
      }
      qr = await this.graphConn.execute(stmt, params);
    } else {
      qr = await this.graphConn.query(cypher);
    }
    try {
      return (await qr.getAll()) as T[];
    } finally {
      await qr.close();
    }
  }

  async upsertSymbol(s: Symbol): Promise<void> {
    // The four temporal/partition columns (indexed_at, repo_commit_sha,
    // repo_commit_date, partition) are NULLable post Orchestrators-2ez.
    // Pass-through write — when undefined the column stays NULL.
    const payload: Record<string, unknown> = { ...s };
    if (payload.indexed_at === undefined) payload.indexed_at = null;
    if (payload.repo_commit_sha === undefined) payload.repo_commit_sha = null;
    if (payload.repo_commit_date === undefined) payload.repo_commit_date = null;
    if (payload.partition === undefined) payload.partition = null;
    await this.query(
      `MERGE (n:Symbol {id: $id})
       SET n.kind = $kind,
           n.language = $language,
           n.repo = $repo,
           n.qualified_name = $qualified_name,
           n.short_name = $short_name,
           n.file = $file,
           n.line = $line,
           n.col = $col,
           n.end_line = $end_line,
           n.end_col = $end_col,
           n.signature = $signature,
           n.visibility = $visibility,
           n.is_abstract = $is_abstract,
           n.is_static = $is_static,
           n.ast_hash = $ast_hash,
           n.branch = $branch,
           n.source = $source,
           n.indexed_at = CASE WHEN $indexed_at IS NULL THEN NULL ELSE timestamp($indexed_at) END,
           n.repo_commit_sha = $repo_commit_sha,
           n.repo_commit_date = CASE WHEN $repo_commit_date IS NULL THEN NULL ELSE timestamp($repo_commit_date) END,
           n.partition = $partition`,
      payload,
    );
  }

  async addEdge(e: Edge): Promise<void> {
    // Edge kind is interpolated; callers must pass an EdgeKind member, never user input.
    await this.query(
      `MATCH (a:Symbol {id: $src}), (b:Symbol {id: $dst})
       CREATE (a)-[:${e.kind}]->(b)`,
      { src: e.src_id, dst: e.dst_id },
    );
  }

  writeTokens(rows: TokenRow[]): void {
    if (rows.length === 0) return;
    const ins = this.fts.prepare(
      `INSERT INTO tokens(text, kind, repo, file, line, col, symbol_id, repo_commit_sha)
       VALUES (?, ?, ?, ?, ?, ?, ?, ?)`,
    );
    const tx = this.fts.transaction((rs: TokenRow[]) => {
      for (const r of rs) {
        ins.run(
          r.text, r.kind, r.repo, r.file, r.line, r.col, r.symbol_id,
          r.repo_commit_sha ?? null,
        );
      }
    });
    tx(rows);
  }

  searchTokens(
    query: string,
    limit = 50,
    repo?: string,
    repo_commit_sha?: string,
  ): TokenRow[] {
    const clauses = ["tokens MATCH ?"];
    const params: unknown[] = [query];
    if (repo !== undefined) {
      clauses.push("repo = ?");
      params.push(repo);
    }
    if (repo_commit_sha !== undefined) {
      clauses.push("repo_commit_sha = ?");
      params.push(repo_commit_sha);
    }
    params.push(limit);
    const sql =
      `SELECT text, kind, repo, file, line, col, symbol_id, repo_commit_sha ` +
      `FROM tokens WHERE ${clauses.join(" AND ")} LIMIT ?`;
    return this.fts.prepare(sql).all(...params as never[]) as unknown as TokenRow[];
  }

  // ----- incremental indexing primitives -----

  /** The previously-recorded content hash for this (repo, file, branch), or null. */
  async fileHash(repo: string, file: string, branch: string): Promise<string | null> {
    const rows = await this.query<{ h: string | null }>(
      `MATCH (f:Symbol)
       WHERE f.kind = 'file' AND f.repo = $repo AND f.file = $file AND f.branch = $branch
       RETURN f.ast_hash AS h`,
      { repo, file, branch },
    );
    return rows[0]?.h ?? null;
  }

  /**
   * Drop every Symbol/edge/token belonging to (repo, file, branch). Called
   * before a re-extraction when the content hash has changed, and on
   * file deletions in watch mode.
   */
  async deleteFileData(repo: string, file: string, branch: string): Promise<void> {
    await this.query(
      `MATCH (s:Symbol)
       WHERE s.repo = $repo AND s.file = $file AND s.branch = $branch
       DETACH DELETE s`,
      { repo, file, branch },
    );
    this.fts.prepare(`DELETE FROM tokens WHERE repo = ? AND file = ?`).run(repo, file);
  }
}

export type { Symbol, Edge, TokenRow } from "./types";
