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
//     HEALTHY. THIS IS OPEN, NOT SOLVED (MetaCoding-qv0). session.ts is the only
//     ticketed ingest entry, but `Store.upsertSymbol` / `Store.addEdge` are
//     public on the exported `src/store` barrel and take no ticket — measured,
//     16 bare upserts grew a slice 12 -> 28 while its record still read
//     fitness 12. Three rounds of guarding a door to a shared mutable store
//     each found a lower door; docs/design/graph-as-cache.md removes the door
//     instead (sealed immutable entries, key recomputed by the reader).
//   * "A RUNNING marker that cries wolf": a crash during finalization leaves
//     RUNNING on a good graph and users learn to ignore it. The record therefore
//     carries pid + heartbeat so a reader can tell "running now" from
//     "abandoned" (`isAbandonedRun`). This is a real ongoing cost, named.
//   * "Re-ingest yesterday's .scip at a new commit": every symbol is re-stamped
//     with this run's indexed_at, so per-run contribution passes with a large
//     number while the graph holds yesterday's facts. STANDING OPEN RED. The
//     record carries the ingested index's path + sha256 + size so a reader can
//     SEE it — citation, not prevention. And the citation is only worth
//     anything if it can be COMPARED (MetaCoding-19g), which is why finalized
//     records are appended to `index_health_history` and each record carries the
//     previous run's identities: one overwritten row per slice made the
//     "visible to a reader" claim true only for a reader who had recorded the
//     previous value out of band.

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
   * The index identities the PREVIOUS finalized record carried, so the current
   * record can be compared against it WITHOUT a reader having written the
   * previous value down out of band (bead MetaCoding-19g).
   */
  prev_index_identities?: IndexIdentity[];
  /**
   * Whether the graph was shown to still BE the tree at finalize time. Absent
   * on records written before MetaCoding-c03, and absent MEANS UNVERIFIED.
   */
  freshness?: FreshnessBlock | null;
  index_identities: IndexIdentity[];
  /**
   * THE TOOLCHAIN THE TREE-SITTER LANE PARSED WITH (bead MetaCoding-1j5, under
   * MetaCoding-0bm).
   *
   * `index_identities` above records the identity of every PRE-BUILT index this
   * run consumed. The tree-sitter lane consumes no file — it consumes GRAMMARS,
   * and their identity is `toolchainDigest()` over the loader's registry. That
   * digest was computed in production from the day 9880f18 landed and reached
   * nothing but `console.log`: walker.ts called it "recorded", and a reader who
   * opened the store afterwards could not recover which grammar produced its
   * facts. Same channel, same purpose, the other lane.
   *
   * OPTIONAL, and absent MEANS UNRECORDED — records written before 1j5, and the
   * RUNNING record, which is written before the walk that measures it. It is
   * never a claim that the toolchain was empty; `toolchainDigest()` refuses
   * that case at the source rather than writing a null here.
   */
  toolchain_digest?: string | null;
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

// `index_health` is the CURRENT verdict per slice — one row, overwritten.
// `index_health_history` is the APPEND-ONLY log of finalized verdicts, and it
// exists because of bead MetaCoding-19g: the standing open red (re-ingesting
// yesterday's .scip at a new commit) was defended with CITATION — "index
// identities make the repetition visible to a reader COMPARING TWO RUNS" — and
// with one overwritten row there was no second run to compare against. The
// identical sha256 that proves the repetition was only visible to someone who
// had written the previous value down out of band, which is not a property of
// the system. Recorded but not comparable is not a mitigation.
//
// Only FINALIZED records are appended: a RUNNING row is rewritten every
// heartbeat, and a log of heartbeats would bury the thing it exists to show.
const SCHEMA = `
CREATE TABLE IF NOT EXISTS index_health (
  repo    TEXT NOT NULL,
  branch  TEXT NOT NULL,
  status  TEXT NOT NULL,
  updated_at TEXT NOT NULL,
  record  TEXT NOT NULL,
  PRIMARY KEY (repo, branch)
);
CREATE TABLE IF NOT EXISTS index_health_history (
  id      INTEGER PRIMARY KEY AUTOINCREMENT,
  repo    TEXT NOT NULL,
  branch  TEXT NOT NULL,
  status  TEXT NOT NULL,
  written_at TEXT NOT NULL,
  record  TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS index_health_history_slice
  ON index_health_history (repo, branch, id);
`;

/**
 * Handle on the health DB. Open read-write only from a session; readers use
 * `readIndexHealth` / `readAllIndexHealth`, which never create the file.
 */
export class IndexHealthStore {
  private constructor(private readonly db: SqliteDb, readonly dataDir: string) {}

  /**
   * How long a blocked connection waits for the lock before giving up.
   *
   * BEAD MetaCoding-byf. bun:sqlite's default busy timeout is ZERO, so a reader
   * that arrived while a writer held the lock did not wait — it threw
   * SQLITE_BUSY on the spot. Under the full suite that made `bun test` red
   * roughly half the time at readIndexHealth, and `bun test` is the ONLY
   * enforcing surface this repo has (docs/design/enforceability.md: no CI, no
   * git hooks). A gate that is red for reasons unrelated to the property it
   * guards is a gate whose reds get waved through, which is worse than no gate:
   * it trains the reader to ignore the colour.
   *
   * SQLITE_BUSY does not mean "the data is bad", it means "come back". Zero was
   * an answer of "never", not a measurement of contention.
   */
  static readonly BUSY_TIMEOUT_MS = 5000;

  static open(dataDir: string): IndexHealthStore {
    mkdirSync(dataDir, { recursive: true });
    const db = new SqliteDb(join(dataDir, HEALTH_DB_FILE));
    // WAL before the schema: readers and one writer then proceed concurrently
    // instead of excluding each other. Set on the WRITER because changing the
    // journal mode needs write access.
    db.exec(`PRAGMA journal_mode=WAL;`);
    db.exec(`PRAGMA busy_timeout=${IndexHealthStore.BUSY_TIMEOUT_MS};`);
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
    // The reader half of MetaCoding-byf. A read-only connection cannot change
    // the journal mode, but it CAN agree to wait.
    db.exec(`PRAGMA busy_timeout=${IndexHealthStore.BUSY_TIMEOUT_MS};`);
    return new IndexHealthStore(db, dataDir);
  }

  write(rec: IndexHealthRecord): void {
    const now = new Date().toISOString();
    // The append-only half, FIRST: if the two writes ever diverge, a history row
    // with no current row is a reader's problem, and a current row with no
    // history row is the ungrounded citation 19g is about.
    if (rec.status !== "RUNNING") {
      this.db
        .prepare(
          `INSERT INTO index_health_history (repo, branch, status, written_at, record)
           VALUES (?, ?, ?, ?, ?)`,
        )
        .run(rec.repo, rec.branch, rec.status, now, JSON.stringify(rec));
    }
    this.db
      .prepare(
        `INSERT INTO index_health (repo, branch, status, updated_at, record)
         VALUES (?, ?, ?, ?, ?)
         ON CONFLICT(repo, branch) DO UPDATE SET
           status = excluded.status,
           updated_at = excluded.updated_at,
           record = excluded.record`,
      )
      .run(rec.repo, rec.branch, rec.status, now, JSON.stringify(rec));
  }

  /**
   * Finalized records for one slice, NEWEST FIRST. This is what makes the
   * index-identity citation comparable: `history[1]` is the run the current
   * record must be compared against, and it is in the store rather than in
   * someone's notes.
   */
  history(repo: string, branch: string, limit = 20): IndexHealthRecord[] {
    const rows = this.db
      .prepare(
        `SELECT record FROM index_health_history
         WHERE repo = ? AND branch = ? ORDER BY id DESC LIMIT ?`,
      )
      .all(repo, branch, limit) as { record: string }[];
    return rows.map((r) => JSON.parse(r.record) as IndexHealthRecord);
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

  /**
   * The concurrency settings this connection actually carries.
   *
   * PUBLISHED, not assumed (bead MetaCoding-byf). The two pragmas above are the
   * whole fix, and a pragma that silently failed to apply looks exactly like one
   * that did — the DB keeps working and only goes wrong under contention, which
   * is the shape that made this flake survive as long as it did. So the settings
   * are readable, and src/ingest/session.test.ts asserts them.
   */
  concurrency(): { journalMode: string; busyTimeoutMs: number } {
    const j = this.db.prepare(`PRAGMA journal_mode`).get() as { journal_mode: string };
    const b = this.db.prepare(`PRAGMA busy_timeout`).get() as { timeout: number };
    return { journalMode: j.journal_mode, busyTimeoutMs: b.timeout };
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

/**
 * Finalized records for one slice, newest first; empty when the DB is absent
 * (or predates MetaCoding-19g, which is the honest reading — a store with no
 * history has nothing to compare, and says so rather than implying agreement).
 */
export function readIndexHealthHistory(
  dataDir: string,
  repo: string,
  branch: string,
  limit = 20,
): IndexHealthRecord[] {
  const h = IndexHealthStore.openExisting(dataDir);
  if (!h) return [];
  try {
    return h.history(repo, branch, limit);
  } catch {
    return []; // a health DB written before the history table existed
  } finally {
    h.close();
  }
}

/**
 * "This run ingested the SAME index file as the previous run" — the sentence
 * open red #2 wants a reader to see, derived from data the store now KEEPS
 * (bead MetaCoding-19g). Null when there is nothing to compare or nothing
 * repeated.
 *
 * This does NOT close the open red: re-ingesting yesterday's `.scip` at a new
 * commit still passes the contribution measure. It makes the citation
 * COMPARABLE, which is all it was ever claimed to be.
 */
export function describeIndexRepetition(rec: IndexHealthRecord | null | undefined): string | null {
  if (!rec) return null;
  const prev = rec.prev_index_identities ?? [];
  const now = rec.index_identities ?? [];
  if (prev.length === 0 || now.length === 0) return null;
  const prevShas = new Set(prev.map((i) => i.sha256));
  const repeated = now.filter((i) => prevShas.has(i.sha256));
  if (repeated.length === 0) return null;
  const same = rec.prev_commit_sha !== null && rec.prev_commit_sha === rec.commit_sha;
  return (
    `ingested the SAME index file as the previous run ` +
    `(${repeated.map((i) => `${i.path} sha ${i.sha256.slice(0, 8)}`).join(", ")})` +
    (same
      ? ` at the same commit.`
      : ` at a NEW commit (${rec.prev_commit_sha?.slice(0, 7) ?? "(none)"} -> ` +
        `${rec.commit_sha?.slice(0, 7) ?? "(none)"}): the graph may hold the ` +
        `PREVIOUS commit's facts while the record claims this one ` +
        `(docs/design/index-fitness.md, open red #2).`)
  );
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
  const repeat = describeIndexRepetition(rec);
  const repeatTxt = repeat ? `\n    ⚠ ${repeat}` : "";
  if (status === "OVERRIDDEN") {
    return (
      `${repo}@${branch}: fitness OVERRIDDEN by ${rec?.override?.flag}=${rec?.override?.value} — ` +
      `the run failed [${(rec?.failures ?? []).map((f) => f.code).join(", ")}] and an operator ` +
      `waived it${corrTxt}.${repeatTxt}`
    );
  }
  return (
    `${repo}@${branch}: fitness HEALTHY (run ${rec?.run_id}, commit ${rec?.commit_sha?.slice(0, 7) ?? "(none)"}` +
    `, ${rec?.fitness?.symbols ?? 0} symbols / ${rec?.fitness?.relationalEdges ?? 0} relational edges` +
    `${corrTxt}).${repeatTxt}`
  );
}
