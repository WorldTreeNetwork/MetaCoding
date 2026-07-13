// `metacoding export <out-dir>` — dump the graph to JSONL so the
// Python ctkr/ side can load it without linking against
// @ladybugdb/core. Writes <out-dir>/nodes.jsonl and
// <out-dir>/edges.jsonl plus a small manifest with counts.
//
// Implementation note: we issue one Cypher MATCH per edge kind so we
// can attach the kind label (RETURN type(r) is supported by ladybugdb's
// Cypher dialect but varies by version — issuing per-kind queries
// keeps this stable across forks).

import { mkdirSync, writeFileSync } from "node:fs";
import { open as fsOpen } from "node:fs/promises";
import { join, resolve } from "node:path";

import { Store } from "../store";
import type { EdgeKind } from "../store/types";

const PLAIN_EDGE_KINDS: EdgeKind[] = [
  "EXTENDS",
  "IMPLEMENTS",
  "OVERRIDES",
  "INJECTS",
  "CONTAINS",
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

const COUNTED_EDGE_KINDS: EdgeKind[] = ["CALLS", "REFERENCES"];

const PAGE_SIZE = 50_000;

interface ExportOpts {
  dataDir: string;
  outDir: string;
}

export async function runExport(opts: ExportOpts): Promise<{
  nodes: number;
  edges: number;
  outDir: string;
}> {
  const outDir = resolve(opts.outDir);
  mkdirSync(outDir, { recursive: true });

  const store = await Store.open(resolve(opts.dataDir));
  try {
    const nodesCount = await dumpNodes(store, join(outDir, "nodes.jsonl"));
    const edgesCount = await dumpEdges(store, join(outDir, "edges.jsonl"));
    const manifest = {
      generated_at: new Date().toISOString(),
      data_dir: resolve(opts.dataDir),
      nodes: nodesCount,
      edges: edgesCount,
      node_columns: [
        "id",
        "kind",
        "language",
        "repo",
        "qualified_name",
        "short_name",
        "file",
        "line",
        "col",
        "end_line",
        "end_col",
        "signature",
        "visibility",
        "is_abstract",
        "is_static",
        "ast_hash",
        "branch",
        "source",
      ],
      edge_columns: ["src_id", "dst_id", "kind", "count"],
    };
    writeFileSync(join(outDir, "manifest.json"), JSON.stringify(manifest, null, 2));
    return { nodes: nodesCount, edges: edgesCount, outDir };
  } finally {
    await store.close();
  }
}

async function dumpNodes(store: Store, outPath: string): Promise<number> {
  const fh = await fsOpen(outPath, "w");
  let total = 0;
  try {
    let offset = 0;
    for (;;) {
      const rows = await store.query(
        `MATCH (s:Symbol)
         RETURN s.id AS id,
                s.kind AS kind,
                s.language AS language,
                s.repo AS repo,
                s.qualified_name AS qualified_name,
                s.short_name AS short_name,
                s.file AS file,
                s.line AS line,
                s.col AS col,
                s.end_line AS end_line,
                s.end_col AS end_col,
                s.signature AS signature,
                s.visibility AS visibility,
                s.is_abstract AS is_abstract,
                s.is_static AS is_static,
                s.ast_hash AS ast_hash,
                s.branch AS branch,
                s.source AS source
         SKIP ${offset} LIMIT ${PAGE_SIZE}`,
      );
      if (rows.length === 0) break;
      const lines = rows.map((r) => JSON.stringify(r)).join("\n") + "\n";
      await fh.write(lines);
      total += rows.length;
      if (rows.length < PAGE_SIZE) break;
      offset += rows.length;
      process.stderr.write(`[export] nodes ${total}...\r`);
    }
    process.stderr.write(`[export] nodes ${total} done\n`);
    return total;
  } finally {
    await fh.close();
  }
}

async function dumpEdges(store: Store, outPath: string): Promise<number> {
  const fh = await fsOpen(outPath, "w");
  let total = 0;
  try {
    for (const kind of PLAIN_EDGE_KINDS) {
      total += await dumpEdgeKind(store, fh, kind, false);
    }
    for (const kind of COUNTED_EDGE_KINDS) {
      total += await dumpEdgeKind(store, fh, kind, true);
    }
    process.stderr.write(`[export] edges ${total} total\n`);
    return total;
  } finally {
    await fh.close();
  }
}

async function dumpEdgeKind(
  store: Store,
  // @ts-expect-error — typed via the result of fsOpen
  fh,
  kind: EdgeKind,
  hasCount: boolean,
): Promise<number> {
  let offset = 0;
  let n = 0;
  for (;;) {
    const cypher = hasCount
      ? `MATCH (a:Symbol)-[r:${kind}]->(b:Symbol)
         RETURN a.id AS src_id, b.id AS dst_id, r.count AS count
         SKIP ${offset} LIMIT ${PAGE_SIZE}`
      : `MATCH (a:Symbol)-[:${kind}]->(b:Symbol)
         RETURN a.id AS src_id, b.id AS dst_id
         SKIP ${offset} LIMIT ${PAGE_SIZE}`;
    const rows = await store.query<Record<string, unknown>>(cypher);
    if (rows.length === 0) break;
    const lines =
      rows
        .map((r) => {
          const out: Record<string, unknown> = {
            src_id: r.src_id,
            dst_id: r.dst_id,
            kind,
          };
          if (hasCount) out.count = r.count ?? null;
          return JSON.stringify(out);
        })
        .join("\n") + "\n";
    await fh.write(lines);
    n += rows.length;
    if (rows.length < PAGE_SIZE) break;
    offset += rows.length;
    process.stderr.write(`[export] edges:${kind} ${n}...\r`);
  }
  process.stderr.write(`[export] edges:${kind} ${n} done\n`);
  return n;
}
