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
  // Behavior-capturing edges (bead MetaCoding-e54).
  "READS_FIELD",
  "WRITES_FIELD",
  "RETURNS_TYPE",
  "CONSTRUCTS",
  // Exception-flow edge (bead MetaCoding-ijo).
  "RAISES",
];

const COUNTED_EDGES: EdgeKind[] = ["CALLS", "REFERENCES"];

const NODE_DDL = `
CREATE NODE TABLE Symbol (
  id STRING,
  kind STRING,
  language STRING,
  repo STRING,
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
  indexed_at TIMESTAMP,
  repo_commit_sha STRING,
  repo_commit_date TIMESTAMP,
  partition STRING,
  PRIMARY KEY (id)
);
`;

// Columns added after the v1 NODE_DDL shipped. Applied as additive
// ALTERs so existing databases pick them up without a rebuild. New
// databases get them via NODE_DDL above and these ALTERs no-op.
//
// Issue: Orchestrators-2ez. Purpose: support self-evolving harness
// contamination detection (drift_detection.py) — see
// docs/research/self-evolving-harnesses/hypotheses/h5-eval-contamination.
const ADDITIVE_COLUMNS: Array<{ name: string; type: string }> = [
  { name: "indexed_at", type: "TIMESTAMP" },
  { name: "repo_commit_sha", type: "STRING" },
  { name: "repo_commit_date", type: "TIMESTAMP" },
  { name: "partition", type: "STRING" },
];

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
  for (const col of ADDITIVE_COLUMNS) {
    await execIgnoreExists(
      conn,
      `ALTER TABLE Symbol ADD ${col.name} ${col.type};`,
    );
  }
}

async function execIgnoreExists(conn: Connection, ddl: string): Promise<void> {
  try {
    const qr = await conn.query(ddl);
    await qr.close();
  } catch (err) {
    const msg = String((err as Error).message ?? err);
    // ladybugdb reports duplicate-column on ALTER as both
    // "already exists" and "duplicate property" depending on version.
    if (
      /already exists|duplicate property|exists in table|already has property/i.test(
        msg,
      )
    )
      return;
    throw err;
  }
}

export function ensureFtsSchema(fts: SqliteDb): void {
  fts.exec(`PRAGMA journal_mode=WAL;`);
  fts.exec(`PRAGMA synchronous=NORMAL;`);

  // FTS5 cannot ALTER ADD COLUMN, so when the existing table is missing the
  // repo_commit_sha column (bead MetaCoding-pon), drop and recreate it.
  // Tokens are fully regeneratable by re-running the indexer; losing them
  // here is acceptable for pre-1.0.
  const cols = fts
    .prepare(`PRAGMA table_info('tokens')`)
    .all() as Array<{ name: string }>;
  if (cols.length > 0) {
    const hasSha = cols.some((c) => c.name === "repo_commit_sha");
    if (!hasSha) {
      fts.exec(`DROP TABLE tokens`);
    }
  }

  fts.exec(`
    CREATE VIRTUAL TABLE IF NOT EXISTS tokens USING fts5(
      text,
      kind UNINDEXED,
      repo UNINDEXED,
      file UNINDEXED,
      line UNINDEXED,
      col UNINDEXED,
      symbol_id UNINDEXED,
      repo_commit_sha UNINDEXED,
      tokenize='trigram'
    );
  `);
}
