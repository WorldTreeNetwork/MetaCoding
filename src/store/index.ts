// The single swap-boundary for the graph + FTS store.
// Per docs/design/storage-integration.md: this is the only module that
// imports @ladybugdb/core or bun:sqlite. Everything else goes through Store.

import { mkdirSync } from "node:fs";
import { join } from "node:path";

import { Database as LbugDb, Connection } from "@ladybugdb/core";
import { Database as SqliteDb } from "bun:sqlite";

import { ensureGraphSchema, ensureFtsSchema } from "./schema";
import type { Edge, Symbol, TokenRow } from "./types";

export class Store {
  private constructor(
    private readonly graphDb: LbugDb,
    private readonly graphConn: Connection,
    private readonly fts: SqliteDb,
    readonly dataDir: string,
  ) {}

  static async open(dataDir: string): Promise<Store> {
    mkdirSync(dataDir, { recursive: true });
    const graphPath = join(dataDir, "graph.lbug");
    const ftsPath = join(dataDir, "tokens.fts.sqlite");

    const graphDb = new LbugDb(graphPath);
    const graphConn = new Connection(graphDb);
    const fts = new SqliteDb(ftsPath);

    await ensureGraphSchema(graphConn);
    ensureFtsSchema(fts);

    return new Store(graphDb, graphConn, fts, dataDir);
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
    await this.query(
      `MERGE (n:Symbol {id: $id})
       SET n.kind = $kind,
           n.language = $language,
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
           n.source = $source`,
      s as unknown as Record<string, unknown>,
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
      `INSERT INTO tokens(text, kind, file, line, col, symbol_id)
       VALUES (?, ?, ?, ?, ?, ?)`,
    );
    const tx = this.fts.transaction((rs: TokenRow[]) => {
      for (const r of rs) {
        ins.run(r.text, r.kind, r.file, r.line, r.col, r.symbol_id);
      }
    });
    tx(rows);
  }

  searchTokens(query: string, limit = 50): TokenRow[] {
    const stmt = this.fts.prepare(
      `SELECT text, kind, file, line, col, symbol_id
       FROM tokens
       WHERE tokens MATCH ?
       LIMIT ?`,
    );
    return stmt.all(query, limit) as unknown as TokenRow[];
  }
}

export type { Symbol, Edge, TokenRow } from "./types";
