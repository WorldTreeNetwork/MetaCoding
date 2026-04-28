// Schema definitions for graph (ladybugdb) and FTS (SQLite FTS5).
// Idempotent: safe to call on every Store.open().

import type { Connection } from "@ladybugdb/core";
import type { Database as SqliteDb } from "bun:sqlite";

import type { EdgeKind } from "./types";

const PLAIN_EDGES: EdgeKind[] = [
  "CONTAINS",
  "EXTENDS",
  "IMPLEMENTS",
  "OVERRIDES",
  "INJECTS",
  "IMPORTS",
  "ANNOTATES",
  "TYPE_OF",
];

const COUNTED_EDGES: EdgeKind[] = ["CALLS", "REFERENCES"];

const NODE_DDL = `
CREATE NODE TABLE Symbol (
  id STRING,
  kind STRING,
  language STRING,
  qualified_name STRING,
  short_name STRING,
  file STRING,
  line INT64,
  col INT64,
  end_line INT64,
  end_col INT64,
  signature STRING,
  visibility STRING,
  is_abstract BOOLEAN,
  is_static BOOLEAN,
  ast_hash STRING,
  branch STRING,
  source STRING,
  PRIMARY KEY (id)
);
`;

export async function ensureGraphSchema(conn: Connection): Promise<void> {
  await execIgnoreExists(conn, NODE_DDL);
  for (const kind of PLAIN_EDGES) {
    await execIgnoreExists(
      conn,
      `CREATE REL TABLE ${kind} (FROM Symbol TO Symbol);`,
    );
  }
  for (const kind of COUNTED_EDGES) {
    await execIgnoreExists(
      conn,
      `CREATE REL TABLE ${kind} (FROM Symbol TO Symbol, count INT64);`,
    );
  }
}

async function execIgnoreExists(conn: Connection, ddl: string): Promise<void> {
  try {
    const qr = await conn.query(ddl);
    await qr.close();
  } catch (err) {
    const msg = String((err as Error).message ?? err);
    if (/already exists/i.test(msg)) return;
    throw err;
  }
}

export function ensureFtsSchema(fts: SqliteDb): void {
  fts.exec(`PRAGMA journal_mode=WAL;`);
  fts.exec(`PRAGMA synchronous=NORMAL;`);
  fts.exec(`
    CREATE VIRTUAL TABLE IF NOT EXISTS tokens USING fts5(
      text,
      kind UNINDEXED,
      file UNINDEXED,
      line UNINDEXED,
      col UNINDEXED,
      symbol_id UNINDEXED,
      tokenize='trigram'
    );
  `);
}
