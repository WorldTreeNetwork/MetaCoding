// The persisted index-health record — bead MetaCoding-ae5, root 2 of
// docs/design/index-fitness.md.
//
// THE PROPERTY THIS EXISTS FOR
// ===========================
//   A graph whose fitness for (repo, branch, commit) has not been established
//   cannot produce an answer that is indistinguishable from one produced by a
//   graph whose fitness HAS been.
//
// The old gate's judgement lived in a process exit code and nowhere else, so
// `status`, `serve`, `describe_api`, the MCP graph tools, the CTKR tools and the
// eval harness could not know that the last run was killed or refused. A
// SIGKILLed ingest leaves symbols and zero edges — the MetaCoding-hy6.16 shape —
// and everything downstream called it "Indexed".
//
// So the verdict becomes a STATE, written beside the graph:
//
//   * on entry to an index session, a RUNNING row is written;
//   * on clean exit it is finalized to HEALTHY / REFUSED / OVERRIDDEN;
//   * a process that DIES never finalizes, so the row says RUNNING forever and
//     every reader sees it. ae5 is closed BY CONSTRUCTION, not by detection.
//
// **An ABSENT file (or an absent row) is UNKNOWN, never HEALTHY.** That is the
// whole migration story, and it is the honest reading of every store indexed
// before this shipped — including production farmOS.
//
// WHY A SEPARATE SQLite FILE, not the graph
// -----------------------------------------
// This is metadata ABOUT the graph, not part of it: putting it in the graph
// means an ingest that corrupts the graph also loses the record that says so.
// SQLite additionally gives real transactions, which the ladybugdb Store does
// not expose. This module is a deliberate, documented exception to
// docs/design/storage-integration.md's "store/index.ts is the only module that
// imports bun:sqlite" rule — it is inside the store package for exactly that
// reason.
//
// HOW WOULD I FAKE THIS?
//   * "Write around the session": any direct Store.upsertSymbol leaves a stale
//     HEALTHY. That is why src/ingest/session.ts is the only exported ingest
//     entry point, and why src/ingest/seam.test.ts fails the suite if another
//     module in src/ imports the raw primitives.
//   * "A RUNNING marker that cries wolf": a crash during finalization leaves
//     RUNNING on a good graph and users learn to ignore it. The record therefore
//     carries pid + heartbeat so a reader can tell "running now" from
//     "abandoned" (`isAbandonedRun`). This is a real ongoing cost, named.
//   * "Re-ingest yesterday's .scip at a new commit": every symbol is re-stamped
//     with this run's indexed_at, so per-run contribution passes with a large
//     number while the graph holds yesterday's facts. STANDING OPEN RED. The
//     record carries the ingested index's path + sha256 + size so a reader can
//     SEE it — citation, not prevention.

import { existsSync, mkdirSync } from "node:fs";
import { join } from "node:path";

import { Database as SqliteDb } from "bun:sqlite";

/** File name of the health DB, beside `graph.lbug` in the data dir. */
export const HEALTH_DB_FILE = "index-health.sqlite";

/**
 * The fitness of a store's slice for one (repo, branch).
 *
 * UNKNOWN     — no record. Never treated as healthy.
 * RUNNING     — a session started and has not finalized (live, or died).
 * HEALTHY     — a session finalized with no failures.
 * REFUSED     — a session finalized with failures and no override.
 * OVERRIDDEN  — a session finalized with failures that an operator waived.
 */
export type IndexHealthStatus =
  | "UNKNOWN"
  | "RUNNING"
  | "HEALTHY"
  | "REFUSED"
  | "OVERRIDDEN";

/** A count of what some SET of symbols and their outgoing edges amounts to. */
export interface CensusBlock {
  symbols: number;
  relationalEdges: number;
  edgesByKind: Record<string, number>;
}

/** THIS RUN's contribution — a census plus the store-visible SCIP share. */
export interface ContributionBlock extends CensusBlock {
  /** Symbols this run stamped whose `source` is 'scip'. */
  scipSymbols: number;
}

/** Which rung of the granularity ladder the correspondence measure landed on. */
export type CorrespondenceLevel = "exact" | "suffix" | "basename" | "unmeasurable";

/**
 * How much of the local source tree the graph actually corresponds to, and at
 * what granularity that could be established. `unmeasurable` NEVER counts as a
 * pass on its own.
 */
export interface CorrespondenceBlock {
  level: CorrespondenceLevel;
  /** Source files with a corresponding indexed file at `level`. */
  matched: number;
  /** Local source-file denominator (censusSourceFiles). */
  sourceFiles: number;
  /** Distinct `Symbol.file` values in the store for this (repo, branch). */
  indexedFiles: number;
  /** matched / sourceFiles, or null when unmeasurable / denominator 0. */
  ratio: number | null;
  /** Why, when level is `unmeasurable`. */
  reason?: string;
}

/**
 * Whether the graph still holds the bytes that are on disk (bead
 * MetaCoding-c03). Measured over the store's own file rows, never over a lane
 * accumulator. `absent` (a stored path with no counterpart on disk — container
 * prefixes, deletions) is reported and NOT counted as staleness.
 */
export interface FreshnessBlock {
  checked: number;
  fresh: number;
  stale: number;
  absent: number;
  staleExamples: string[];
}

/** Identity of an ingested pre-built index file — citation for open red #2. */
export interface IndexIdentity {
  path: string;
  sha256: string;
  size: number;
}

/** One lane's outcome within a session. */
export interface LaneRecord {
  lane: string;
  ok: boolean;
  error?: string;
  /** Files/documents the lane looked at. NOT a measure of what reached the store. */
  files: number;
}

export interface HealthFailure {
  code: string;
  message: string;
}

/** The persisted fact. One current row per (repo, branch). */
export interface IndexHealthRecord {
  repo: string;
  branch: string;
  status: IndexHealthStatus;
  /** Unique per session — the same value stamped onto Symbol.indexed_at. */
  run_id: string;
  /** Commit this run claimed to index. */
  commit_sha: string | null;
  /** Commit the PREVIOUS finalized record claimed, if any. */
  prev_commit_sha: string | null;
  started_at: string;
  finished_at: string | null;
  pid: number | null;
  /** Last liveness stamp written by the running session. */
  heartbeat_at: string | null;
  failures: HealthFailure[];
  lanes: LaneRecord[];
  /**
   * THIS RUN's contribution — symbols this session stamped, and edges out of
   * them. May legitimately be zero for a no-op re-index at the same commit.
   * NEVER substituted for `fitness`.
   */
  contribution: ContributionBlock | null;
  /**
   * THE STORE's fitness for (repo, branch) after the run, whichever run
   * established it. NEVER substituted for `contribution`.
   */
  fitness: CensusBlock | null;
  correspondence: CorrespondenceBlock | null;
  /**
   * Whether the graph was shown to still BE the tree at finalize time. Absent
   * on records written before MetaCoding-c03, and absent MEANS UNVERIFIED.
   */
  freshness?: FreshnessBlock | null;
  index_identities: IndexIdentity[];
  /** Set when an operator flag waived a failure. Visible at read time forever. */
  override: { flag: string; value: string } | null;
  /** True while a `metacoding watch` owns this slice (incremental writes). */
  watching?: boolean;
}

/** Fitness is ESTABLISHED only by a finalized clean run or an explicit waiver. */
export function isFitnessEstablished(status: IndexHealthStatus): boolean {
  return status === "HEALTHY" || status === "OVERRIDDEN";
}

/** The record's status, with the absent record read honestly as UNKNOWN. */
export function statusOf(rec: IndexHealthRecord | null | undefined): IndexHealthStatus {
  return rec?.status ?? "UNKNOWN";
}

/**
 * True when a RUNNING row's owning process is gone — "abandoned", not "running
 * now". Without this the RUNNING marker cries wolf and users learn to ignore it
 * (fake-it #5 in the design). A record with no pid cannot be distinguished, and
 * is reported as still running rather than guessed at.
 */
export function isAbandonedRun(rec: IndexHealthRecord | null | undefined): boolean {
  if (!rec || rec.status !== "RUNNING") return false;
  if (rec.pid === null || rec.pid === undefined) return false;
  try {
    process.kill(rec.pid, 0);
    return false; // signal delivered: the process is alive
  } catch (e) {
    // ESRCH = no such process. EPERM = alive but not ours.
    return (e as NodeJS.ErrnoException).code === "ESRCH";
  }
}

const SCHEMA = `
CREATE TABLE IF NOT EXISTS index_health (
  repo    TEXT NOT NULL,
  branch  TEXT NOT NULL,
  status  TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  record  TEXT NOT NULL,
  PRIMARY KEY (repo, branch)
);
`;

/**
 * Handle on the health DB. Open read-write only from a session; readers use
 * `readIndexHealth` / `readAllIndexHealth`, which never create the file.
 */
export class IndexHealthStore {
  private constructor(private readonly db: SqliteDb, readonly dataDir: string) {}

  static open(dataDir: string): IndexHealthStore {
    mkdirSync(dataDir, { recursive: true });
    const db = new SqliteDb(join(dataDir, HEALTH_DB_FILE));
    db.exec(SCHEMA);
    return new IndexHealthStore(db, dataDir);
  }

  /**
   * Open read-only WITHOUT creating the file. Returns null when no health DB
   * exists — which the caller must read as UNKNOWN, never as HEALTHY.
   */
  static openExisting(dataDir: string): IndexHealthStore | null {
    const path = join(dataDir, HEALTH_DB_FILE);
    if (!existsSync(path)) return null;
    const db = new SqliteDb(path, { readonly: true });
    return new IndexHealthStore(db, dataDir);
  }

  write(rec: IndexHealthRecord): void {
    this.db
      .prepare(
        `INSERT INTO index_health (repo, branch, status, updated_at, record)
         VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(repo, branch) DO UPDATE SET
           status = excluded.status,
           updated_at = excluded.updated_at,
           record = excluded.record`,
      )
      .run(rec.repo, rec.branch, rec.status, new Date().toISOString(), JSON.stringify(rec));
  }

  read(repo: string, branch: string): IndexHealthRecord | null {
    const row = this.db
      .prepare(`SELECT record FROM index_health WHERE repo = ? AND branch = ?`)
      .get(repo, branch) as { record: string } | null;
    if (!row) return null;
    return JSON.parse(row.record) as IndexHealthRecord;
  }

  readAll(): IndexHealthRecord[] {
    const rows = this.db
      .prepare(`SELECT record FROM index_health ORDER BY repo, branch`)
      .all() as { record: string }[];
    return rows.map((r) => JSON.parse(r.record) as IndexHealthRecord);
  }

  close(): void {
    this.db.close();
  }
}

/**
 * Read one (repo, branch)'s health without creating anything. `null` means
 * UNKNOWN: either no health DB exists beside this graph (a store indexed before
 * this shipped) or no session ever ran for that slice.
 */
export function readIndexHealth(
  dataDir: string,
  repo: string,
  branch: string,
): IndexHealthRecord | null {
  const h = IndexHealthStore.openExisting(dataDir);
  if (!h) return null;
  try {
    return h.read(repo, branch);
  } finally {
    h.close();
  }
}

/** Every recorded (repo, branch) health row; empty when the DB is absent. */
export function readAllIndexHealth(dataDir: string): IndexHealthRecord[] {
  const h = IndexHealthStore.openExisting(dataDir);
  if (!h) return [];
  try {
    return h.readAll();
  } finally {
    h.close();
  }
}

/** One-line human summary, used by status / serve / describe_api. */
export function formatHealthLine(rec: IndexHealthRecord | null, repo: string, branch: string): string {
  const status = statusOf(rec);
  if (status === "UNKNOWN") {
    return (
      `${repo}@${branch}: fitness UNKNOWN — no index-health record beside this graph. ` +
      `Results from it are not established. Fix: metacoding index <path> --scip`
    );
  }
  if (status === "RUNNING") {
    const abandoned = isAbandonedRun(rec);
    return abandoned
      ? `${repo}@${branch}: fitness UNESTABLISHED — an index run (pid ${rec?.pid}) started ` +
        `${rec?.started_at} and DIED without finalizing. The graph may be half-written ` +
        `(the loader writes symbols before edges). Fix: re-run metacoding index <path> --scip`
      : `${repo}@${branch}: an index run (pid ${rec?.pid}) is IN PROGRESS since ${rec?.started_at} — ` +
        `fitness is not established until it finalizes.`;
  }
  if (status === "REFUSED") {
    return (
      `${repo}@${branch}: fitness REFUSED — the last index run finished but its graph was ` +
      `unusable [${(rec?.failures ?? []).map((f) => f.code).join(", ")}]. ` +
      `Fix: re-run metacoding index <path> --scip`
    );
  }
  const corr = rec?.correspondence;
  const corrTxt = corr
    ? `, correspondence ${corr.level}${corr.ratio === null ? "" : ` ${(corr.ratio * 100).toFixed(0)}%`}`
    : "";
  if (status === "OVERRIDDEN") {
    return (
      `${repo}@${branch}: fitness OVERRIDDEN by ${rec?.override?.flag}=${rec?.override?.value} — ` +
      `the run failed [${(rec?.failures ?? []).map((f) => f.code).join(", ")}] and an operator ` +
      `waived it${corrTxt}.`
    );
  }
  return (
    `${repo}@${branch}: fitness HEALTHY (run ${rec?.run_id}, commit ${rec?.commit_sha?.slice(0, 7) ?? "(none)"}` +
    `, ${rec?.fitness?.symbols ?? 0} symbols / ${rec?.fitness?.relationalEdges ?? 0} relational edges` +
    `${corrTxt}).`
  );
}
