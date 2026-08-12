// scripts/smoke-ladybug.ts
//
// One-shot validation that @ladybugdb/core works under Bun on this machine.
// Mirrors the spike from:
//   ~/projects/Dreamball/docs/decisions/2026-04-21-ladybugdb-selection.md
//
// What we want to confirm:
//   1. The module loads and exposes Database/Connection/QueryResult.
//   2. We can open a .lbug file, create a node table, insert, and MATCH.
//   3. Storage files persist on disk.
//   4. With Mitigation 1 (explicit close) + Mitigation 2 (process.exit(0))
//      applied, the Bun napi-finalizer crash does not surface.
//
// Run with: bun run scripts/smoke-ladybug.ts
// Exit codes: 0 = pass, non-zero = fail.

import { rmSync, existsSync } from "node:fs";
import { Database, Connection, VERSION, STORAGE_VERSION } from "@ladybugdb/core";
import { beginRun, type Floor } from "../src/testkit/floors.ts";

// Every check is COUNTED (src/testkit/floors.ts): the count is derived from
// the calls that run, so a deleted assertion is visible instead of silent.
const run = beginRun("ladybug");

const FLOORS: Floor[] = [
  {
    min: 3,
    measuredAs: "checks",
    why: "counted from the source: 3 assertion sites - trivial RETURN, CONTAINS round-trip, storage file on disk",
  },
];

const DB_PATH = "./tmp-smoke.lbug";

async function query<T>(conn: Connection, cypher: string, params?: unknown): Promise<T[]> {
  const qr = await conn.query(cypher, params as never);
  try {
    return (await qr.getAll()) as T[];
  } finally {
    await qr.close();
  }
}

function cleanup(): void {
  for (const f of [DB_PATH, `${DB_PATH}.wal`]) {
    if (existsSync(f)) rmSync(f, { recursive: true, force: true });
  }
}

async function main(): Promise<void> {
  cleanup();

  console.log(`ladybug VERSION=${VERSION} STORAGE_VERSION=${STORAGE_VERSION}`);

  const db = new Database(DB_PATH);
  const conn = new Connection(db);

  try {
    // 1. Trivial RETURN
    const ones = await query<{ x: number }>(conn, "RETURN 1 AS x;");
    run.check("RETURN 1 round-trips", ones[0]?.x === 1, `got ${JSON.stringify(ones)}`);

    // 2. Create a node table
    await query(
      conn,
      "CREATE NODE TABLE Symbol(id STRING, kind STRING, qualified_name STRING, PRIMARY KEY(id));"
    );

    // 3. Insert two nodes
    await query(
      conn,
      "CREATE (:Symbol {id: 'a', kind: 'class', qualified_name: 'com.x.A'});"
    );
    await query(
      conn,
      "CREATE (:Symbol {id: 'b', kind: 'method', qualified_name: 'com.x.A.m'});"
    );

    // 4. Create a relation table and an edge
    await query(conn, "CREATE REL TABLE CONTAINS(FROM Symbol TO Symbol);");
    await query(
      conn,
      "MATCH (a:Symbol {id:'a'}), (b:Symbol {id:'b'}) CREATE (a)-[:CONTAINS]->(b);"
    );

    // 5. Round-trip query
    const rows = await query<{ id: string; child_id: string }>(
      conn,
      "MATCH (a:Symbol)-[:CONTAINS]->(b:Symbol) RETURN a.id AS id, b.id AS child_id;"
    );
    run.check(
      "CONTAINS edge round-trips a->b",
      rows.length === 1 && rows[0]?.id === "a" && rows[0]?.child_id === "b",
      `got ${JSON.stringify(rows)}`,
    );

    // 6. Confirm files landed
    run.check(`${DB_PATH} landed on disk`, existsSync(DB_PATH), "missing");

    run.finish(FLOORS);
  } finally {
    // Mitigation 1: explicit close in reverse order of construction.
    await conn.close();
    await db.close();
    cleanup();
  }
}

main()
  .then(() => {
    // Mitigation 2: belt-and-braces exit. Skips Bun's napi finalizer pass.
    process.exit(0);
  })
  .catch((err) => {
    console.error("SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
