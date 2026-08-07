// THE BUILD BUFFER — the whole-tree write path.
//
// WHY THIS EXISTS (bead MetaCoding-9jt, a P0 that shipped).
// ========================================================
// The old whole-tree path wrote row-at-a-time into a MUTABLE store and skipped
// files whose content hash was unchanged. Both halves of that are defects, and
// they are the same defect:
//
//   * CORRECTNESS. Cross-file edges (CONSTRUCTS, RETURNS_TYPE, …) are resolved
//     at the END of the walk against a SymbolResolver populated BY the walk.
//     A skipped file never enters the resolver, so a candidate pointing at it
//     is dropped as unresolvable — silently. Meanwhile `deleteFileData` on the
//     one CHANGED file DETACH-DELETEs edges OWNED BY OTHER FILES that point
//     into it. Net: edit one file's method body, re-index, and edges belonging
//     to files you never touched disappear and never come back. Measured on a
//     two-file fixture: fresh 14 edges, incremental 12, both HEALTHY.
//
//   * COST. Mutation-in-place is what FORCES `MERGE`-per-row, and MERGE-per-row
//     is the whole cost of indexing. Measured on this repo (92 files):
//         parse + extract .......................    269 ms
//         resolve 6,815 cross-file candidates ...      2 ms
//         the same content through MERGE/CREATE .. 76,020 ms
//         the same content through COPY .........    231 ms
//     The "90-second rebuild" is ~1 second of work behind a bad write path.
//
// So a whole-tree index does not update a graph. It BUILDS one: extract every
// file, resolve against the complete symbol set, then replace the slice in a
// single bulk load. Correctness and cost land on the same answer, which is the
// signal docs/design/iteration-methodology.md says to trust.
//
// This is also the mechanism docs/design/graph-as-cache.md needs: an entry is
// built whole and swapped in, never edited in place. It is NOT yet the sealed,
// keyed entry that design describes — there is no manifest and no recomputed
// key here (bead MetaCoding-ev9). This is the write path that makes those
// affordable.
//
// NOT the watch path. `metacoding watch` still writes per-file into a live
// Store, and the cross-file defect above still applies to it. graph-as-cache
// names that outcome deliberately: watch is a mutable scratch entry.

import { randomUUID } from "node:crypto";
import { mkdirSync, rmSync, writeFileSync } from "node:fs";
import { join } from "node:path";

import type { Store } from "./index.ts";
import type { Edge, EdgeKind, Symbol, TokenRow } from "./types";

/**
 * The write surface a lane needs. `Store` satisfies it structurally, and so
 * does `GraphBuild` — which is what lets `indexDirectory` and `loadScip` feed a
 * buffer instead of a database with no change to their bodies.
 */
export interface GraphWriter {
  readonly dataDir: string;
  upsertSymbol(s: Symbol, opts?: { preserveStructural?: boolean }): Promise<void>;
  addEdge(e: Edge): Promise<void>;
  writeTokens(rows: TokenRow[]): void;
}

/** What a flush actually did. Every number here is REPORTED, never thresholded. */
export interface FlushStats {
  /** Symbols COPYed in. */
  symbols: number;
  /** Edges COPYed in. */
  edges: number;
  tokens: number;
  /**
   * Edges dropped because an endpoint id was in neither the built slice nor the
   * surviving store. The old `addEdge` MATCH-CREATE dropped these SILENTLY —
   * a non-zero count here is a fact that used to be invisible.
   */
  edgesDropped: number;
  /** Symbols in the replaced slice that were DETACH DELETEd. */
  symbolsReplaced: number;
  /**
   * Built symbols NOT written because that id already existed outside the
   * replaced slice (per-commit-identity runs, shared boundary nodes). Their
   * existing row is left alone.
   */
  symbolsPreexisting: number;
  flushMs: number;
}

/** The five fields the SCIP lane must not clobber — see Store.upsertSymbol. */
const STRUCTURAL_FIELDS = [
  "signature", "visibility", "is_abstract", "is_static", "ast_hash",
] as const;

/**
 * Symbol columns that are `string` (never null) in src/store/types.ts. A CSV
 * COPY cannot distinguish an empty string from NULL — quoted `""` reads back as
 * NULL, measured — so for exactly these columns a NULL after COPY means "" and
 * is normalized back. Boundary nodes rely on this: they carry `file: ""` and
 * `branch: ""`.
 *
 * Deliberately NOT applied to the nullable columns (signature, visibility,
 * ast_hash, repo_commit_sha, partition): there "" and NULL are equivalent for
 * every consumer, and inventing "" for a genuine NULL would be worse.
 *
 * `id` and `repo` are excluded for different reasons and both are safe: `id` is
 * the primary key (ladybugdb refuses to SET it at all, and an empty one could
 * never have been written), and `repo` is this normalization's own scope key —
 * an empty repo would not match the WHERE, and no build has one, since it
 * defaults to the indexed directory's basename.
 */
const NEVER_NULL_STRING_COLUMNS = [
  "kind", "language", "qualified_name", "short_name",
  "file", "branch", "source",
] as const;

/**
 * The COPY dialect, stated in full and never inferred.
 *
 * `parallel=false` is required because a quoted field may contain a newline —
 * the parallel reader rejects those outright.
 *
 * `escape`/`quote`/`delim` are explicit because ladybugdb SNIFFS the dialect
 * from a sample when they are omitted, and the sniff is not stable across file
 * sizes. Measured: the identical escaping round-tripped on six hand-written
 * fixture rows and then rejected the real 21,282-row file at line 8,274, on a
 * `type_alias` whose SCIP name is literally `"just-types"0`. A fixture-sized
 * file agreed with us about the dialect; a production-sized one guessed
 * differently. State it.
 */
const CSV_DIALECT = String.raw`(header=false, parallel=false, escape='\\', quote='"', delim=',')`;

type Cell = string | number | boolean | null | undefined;

/**
 * Quote one CSV field for ladybugdb's reader, which uses `"` as quote and `\`
 * as escape. Verified round-trip on commas, embedded quotes, LF, CRLF,
 * backslashes, tabs and non-ASCII.
 */
function csvCell(v: Cell): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return String(v);
  return '"' + v.replaceAll("\\", "\\\\").replaceAll('"', '\\"') + '"';
}

function csvRow(cells: Cell[]): string {
  return cells.map(csvCell).join(",") + "\n";
}

/** Single-quote a path for interpolation into a COPY statement. */
function sqlPath(p: string): string {
  return p.replaceAll("'", "''");
}

/**
 * An in-memory graph slice. Accumulates everything a build produces, then
 * replaces the (repo, branch) slice in one bulk load.
 */
export class GraphBuild implements GraphWriter {
  private readonly symbols = new Map<string, Symbol>();
  private readonly edges: Edge[] = [];
  private readonly tokens: TokenRow[] = [];

  constructor(
    readonly dataDir: string,
    private readonly scope: {
      repo: string;
      branch: string;
      /** When set, the replaced slice is narrowed to this commit (bead izn). */
      commitSha?: string | null;
      perCommitIdentity?: boolean;
    },
  ) {}

  get symbolCount(): number { return this.symbols.size; }
  get edgeCount(): number { return this.edges.length; }
  get tokenCount(): number { return this.tokens.length; }

  /**
   * Buffered upsert. Mirrors Store.upsertSymbol's semantics exactly, including
   * `preserveStructural`: the SCIP lane must not overwrite the five structural
   * fields tree-sitter filled in, and COALESCE(existing, new) in Cypher is
   * "keep the existing value when it is already set" — which in the buffer is a
   * field-wise merge against whatever the earlier lane wrote.
   */
  // eslint-disable-next-line @typescript-eslint/require-await
  async upsertSymbol(s: Symbol, opts?: { preserveStructural?: boolean }): Promise<void> {
    const prior = this.symbols.get(s.id);
    if (!prior) {
      this.symbols.set(s.id, { ...s });
      return;
    }
    const merged: Symbol = { ...prior, ...s };
    if (opts?.preserveStructural) {
      for (const f of STRUCTURAL_FIELDS) {
        const kept = prior[f];
        if (kept !== null && kept !== undefined) {
          (merged as unknown as Record<string, unknown>)[f] = kept;
        }
      }
    }
    this.symbols.set(s.id, merged);
  }

  // eslint-disable-next-line @typescript-eslint/require-await
  async addEdge(e: Edge): Promise<void> {
    // Not deduped: `Store.addEdge` used CREATE, so parallel edges of the same
    // kind were representable and some counts depend on it. The buffer must not
    // quietly change what the graph holds while it is changing how it is written.
    this.edges.push({ ...e });
  }

  writeTokens(rows: TokenRow[]): void {
    for (const r of rows) this.tokens.push(r);
  }

  /**
   * Replace this slice in `store` with what was built.
   *
   * 1. DETACH DELETE the slice being rebuilt.
   * 2. COPY the built symbols, skipping ids that survived step 1 elsewhere.
   * 3. COPY the built edges, dropping (and COUNTING) any whose endpoint is absent.
   * 4. Rewrite the repo's FTS tokens.
   *
   * Not atomic against SIGKILL: a death mid-flush leaves a partial slice. The
   * index session's RUNNING record is what makes that visible (MetaCoding-ae5)
   * — turning this into an atomic swap is the sealing work in MetaCoding-ev9.
   */
  async flush(store: Store): Promise<FlushStats> {
    const t0 = performance.now();
    const tmp = join(this.dataDir, `.build-${randomUUID()}`);
    mkdirSync(tmp, { recursive: true });
    try {
      const symbolsReplaced = await this.deleteSlice(store);

      // Everything still in the store for this repo AFTER the delete: other
      // commits' rows under per-commit identity, and boundary nodes we chose
      // not to delete. Both are legitimate edge endpoints and both would make
      // a COPY fail on a duplicate primary key.
      const surviving = new Set(
        (
          await store.query<{ id: string }>(
            `MATCH (s:Symbol) WHERE s.repo = $repo RETURN s.id AS id`,
            { repo: this.scope.repo },
          )
        ).map((r) => r.id),
      );

      const columns = await symbolColumns(store);
      const toWrite: Symbol[] = [];
      let symbolsPreexisting = 0;
      // THE PROPERTY THIS ENFORCES (found by a fresh judge, 2026-08-07):
      //
      //   the set `deleteSlice` removes must be a SUPERSET of the ids this
      //   build is about to write.
      //
      // Skipping an id because it already exists is only safe when the delete
      // was supposed to leave it — and the only such ids are the repo's shared
      // BOUNDARY NODES under per-commit identity, which are deliberately not
      // sha-scoped and deliberately not deleted (see deleteSlice).
      //
      // Anything else surviving means the delete did not cover this build's
      // own output, and skipping it writes the 9jt failure shape back into the
      // module that exists to close it: measured on the shipped CLI with
      // `--per-commit-identity` against a NON-GIT directory, where
      // `getRepoCommitSha` is null, `s.repo_commit_sha = $sha` is never true
      // for NULL so the delete removed nothing, and `identity.ts` does not fold
      // a null sha into the id so every id repeated. Three runs: 6 edges where
      // a fresh index gives 2, every symbol skipped, HEALTHY every time — and
      // renaming a method left the OLD name in the graph permanently.
      //
      // So it REFUSES instead of skipping. A partial flush is recoverable; a
      // silently stale HEALTHY graph is what cost this project weeks.
      const unexpected: string[] = [];
      for (const s of this.symbols.values()) {
        if (surviving.has(s.id)) {
          if (s.language === "external") { symbolsPreexisting++; continue; }
          unexpected.push(s.id);
          continue;
        }
        toWrite.push(s);
      }
      if (unexpected.length > 0) {
        throw new Error(
          `metacoding: refusing to flush — ${unexpected.length} symbol(s) this build ` +
          `produced already exist and were NOT removed by the slice delete, so ` +
          `writing would leave stale rows behind forever. This means the delete's ` +
          `scope does not cover the build's output. First: ${unexpected.slice(0, 3).join(", ")}` +
          (this.scope.perCommitIdentity && !this.scope.commitSha
            ? "\n  CAUSE: --per-commit-identity with no commit sha. Symbol ids are " +
              "only sha-scoped when a sha exists, and the slice delete matches on " +
              "repo_commit_sha, which never matches NULL. Index a git repo, or drop " +
              "--per-commit-identity."
            : ""),
        );
      }

      if (toWrite.length > 0) {
        const path = join(tmp, "symbols.csv");
        let csv = "";
        for (const s of toWrite) csv += csvRow(columns.map((c) => symbolCell(s, c)));
        writeFileSync(path, csv);
        await store.query(`COPY Symbol FROM '${sqlPath(path)}' ${CSV_DIALECT};`);
        await this.normalizeEmptyStrings(store);
      }

      const known = new Set<string>(surviving);
      for (const s of toWrite) known.add(s.id);
      const { written, dropped } = await this.copyEdges(store, tmp, known);

      const tokens = this.flushTokens(store);

      return {
        symbols: toWrite.length,
        edges: written,
        tokens,
        edgesDropped: dropped,
        symbolsReplaced,
        symbolsPreexisting,
        flushMs: performance.now() - t0,
      };
    } finally {
      // METACODING_KEEP_BUILD_CSV leaves the staged CSVs on disk. A COPY that
      // rejects a row names a line number in a file that no longer exists,
      // which makes the one class of bug this path can have — an escaping case
      // real code produces and a fixture did not — unusually hard to see.
      if (!process.env.METACODING_KEEP_BUILD_CSV) {
        rmSync(tmp, { recursive: true, force: true });
      }
    }
  }

  /**
   * Drop the slice this build replaces.
   *
   * Scope is (repo, branch), plus the repo's boundary nodes — which carry
   * `branch: ""` and are re-derived by every build (src/extractor/walker.ts,
   * ensureBoundaryNode). Under per-commit identity the slice narrows to the one
   * commit and boundary nodes are left ALONE, because DETACH DELETEing a shared
   * boundary node would destroy other commits' edges into it — which is the
   * very defect this module exists to fix, one level up.
   */
  private async deleteSlice(store: Store): Promise<number> {
    const perCommit = this.scope.perCommitIdentity === true;
    const params: Record<string, unknown> = {
      repo: this.scope.repo,
      branch: this.scope.branch,
    };
    let where = `s.repo = $repo AND s.branch = $branch`;
    if (perCommit) {
      // Narrow to this commit's row family; leave every other commit standing.
      params.sha = this.scope.commitSha ?? null;
      where += ` AND s.repo_commit_sha = $sha`;
    } else {
      // A build owns the repo's boundary nodes and rebuilds all of them.
      where = `s.repo = $repo AND (s.branch = $branch OR s.branch = '' OR s.branch IS NULL)`;
    }
    const counted = await store.query<{ c: number | bigint }>(
      `MATCH (s:Symbol) WHERE ${where} RETURN count(s) AS c`,
      params,
    );
    const n = Number(counted[0]?.c ?? 0);
    if (n > 0) {
      await store.query(`MATCH (s:Symbol) WHERE ${where} DETACH DELETE s`, params);
    }
    return n;
  }

  /**
   * CSV cannot carry an empty string — `""` reads back as NULL (measured). For
   * the columns typed `string` that means "", so put it back. Scoped by repo,
   * which is itself never empty and therefore survives the round trip.
   */
  private async normalizeEmptyStrings(store: Store): Promise<void> {
    for (const col of NEVER_NULL_STRING_COLUMNS) {
      await store.query(
        `MATCH (s:Symbol) WHERE s.repo = $repo AND s.${col} IS NULL SET s.${col} = ''`,
        { repo: this.scope.repo },
      );
    }
  }

  /**
   * COPY the built edges, one file per kind.
   *
   * An edge whose endpoint id is unknown is DROPPED and COUNTED. It has to be
   * dropped — `COPY` on a rel table throws "Unable to find primary key value"
   * and would abort the whole load — but the count is the improvement: the old
   * MATCH-CREATE dropped exactly the same edges and said nothing.
   */
  private async copyEdges(
    store: Store,
    tmp: string,
    known: Set<string>,
  ): Promise<{ written: number; dropped: number }> {
    const byKind = new Map<EdgeKind, Edge[]>();
    let dropped = 0;
    for (const e of this.edges) {
      if (!known.has(e.src_id) || !known.has(e.dst_id)) { dropped++; continue; }
      let bucket = byKind.get(e.kind);
      if (!bucket) { bucket = []; byKind.set(e.kind, bucket); }
      bucket.push(e);
    }

    let written = 0;
    for (const [kind, list] of byKind) {
      // Column order is (FROM, TO, …declared properties), per CALL table_info.
      const props = await relProperties(store, kind);
      let csv = "";
      for (const e of list) {
        csv += csvRow([
          e.src_id,
          e.dst_id,
          ...props.map((p) => (p === "count" ? (e.count ?? 1) : p === "provenance" ? (e.provenance ?? null) : null)),
        ]);
      }
      const path = join(tmp, `edges.${kind}.csv`);
      writeFileSync(path, csv);
      await store.query(`COPY ${kind} FROM '${sqlPath(path)}' ${CSV_DIALECT};`);
      written += list.length;
    }
    return { written, dropped };
  }

  /** Replace this repo's FTS rows. Plain SQLite; a transaction is already fast. */
  private flushTokens(store: Store): number {
    store.deleteRepoTokens(this.scope.repo);
    store.writeTokens(this.tokens);
    return this.tokens.length;
  }
}

/** Authoritative Symbol column order, read from the live table. */
async function symbolColumns(store: Store): Promise<string[]> {
  const rows = await store.query<Record<string, unknown>>(
    `CALL table_info('Symbol') RETURN *`,
  );
  return rows.map((r) => String(r.name));
}

const relPropCache = new Map<string, string[]>();
async function relProperties(store: Store, kind: EdgeKind): Promise<string[]> {
  const cached = relPropCache.get(kind);
  if (cached) return cached;
  const rows = await store.query<Record<string, unknown>>(
    `CALL table_info('${kind}') RETURN *`,
  );
  const props = rows.map((r) => String(r.name));
  relPropCache.set(kind, props);
  return props;
}

/** One Symbol field as a CSV cell, by column name. */
function symbolCell(s: Symbol, column: string): Cell {
  const v = (s as unknown as Record<string, unknown>)[column];
  if (v === undefined || v === null) return null;
  if (typeof v === "boolean" || typeof v === "number" || typeof v === "string") return v;
  return String(v);
}
