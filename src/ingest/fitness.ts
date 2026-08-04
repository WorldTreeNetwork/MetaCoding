// Index fitness measurement — root 1 of docs/design/index-fitness.md.
// Supersedes src/cli/index-gate.ts (beads MetaCoding-0sd, 4kg, 5fi, e6z).
//
// THE PROPERTY
// ============
//   A graph whose fitness for (repo, branch, commit) has not been established
//   cannot produce an answer that is indistinguishable from one produced by a
//   graph whose fitness has been.
//
// ROOT 1, WHICH THIS MODULE EXISTS TO FIX
// =======================================
// The previous gate took every measurement from the NEAREST AVAILABLE NUMBER
// rather than from the set its claim was about:
//
//   claim                                  | quantity it actually read
//   ---------------------------------------|------------------------------------
//   "this run produced symbols"            | repo-wide census, history-blind (4kg)
//   "SCIP produced something"              | document count — an empty document
//                                          | is a document (4kg)
//   "the graph covers the repo"            | documents whose path may come from
//                                          | any filesystem (5fi)
//
// Every measurement below names its subject in its own name, and the two
// quantities that were being substituted for each other are computed by two
// different functions and stored in two different fields:
//
//   measureRunContribution  — what THIS SESSION wrote. May legitimately be 0
//                             for a no-op re-index at the SAME commit.
//   measureStoreFitness     — what the STORE holds for (repo, branch), by
//                             whichever run put it there.
//   measureCorrespondence   — how much of the LOCAL SOURCE TREE the store's
//                             files actually correspond to, and at what
//                             granularity that could be established.
//
// Per-run attribution needs NO schema change and NO migration: `Symbol.indexed_at`
// is set from one constant per session, threaded through both lanes, and is not
// COALESCE-protected, so it is always overwritten. Verified directly against a
// live ladybugdb store before this was written:
//   `MATCH (s:Symbol) WHERE s.indexed_at = timestamp($t)` selects exactly the
//   symbols stamped by run $t, composes with `s.source = 'scip'`, and edges
//   attribute through their SOURCE symbol
//   (`MATCH (a)-[r:CALLS]->() WHERE a.indexed_at = timestamp($t)`).
//
// HOW WOULD I FAKE THIS? (asked before shipping)
//   1. "Coast on a previous good run" -> measureRunContribution is scoped to
//      this session's stamp, so a run that wrote nothing reads 0 regardless of
//      how full the store is. Zero is only a FAILURE when the commit advanced
//      (ZERO_CONTRIBUTION_AT_NEW_COMMIT) — a no-op re-index at the same commit
//      into an already-fit store is defensible, and a rule that false-alarms on
//      the most common invocation is a rule people disable.
//   2. "Point 40 vendored documents at a 10-file Go repo" -> correspondence is
//      a set intersection over Symbol.file against the local tree. 5fi's
//      vendor40 fixture intersects in ZERO places at every rung of the ladder
//      and comes out UNMEASURABLE, which is never a pass on its own.
//   3. "Ship an out-of-band container build whose paths are /app/web/..." ->
//      the ladder degrades to SUFFIX and then BASENAME and RECORDS WHICH RUNG
//      IT USED, so --load-scip is not structurally unmeasurable; it is
//      measurable at a weaker granularity, and the granularity is in the record.
//   4. "Make UNMEASURABLE the new escape hatch" -> the weakest joint, named. The
//      ladder exists so it is the FOURTH answer, not the first, and it emits a
//      failure code rather than a pass.
//   5. "Re-ingest yesterday's .scip at a new commit" -> every symbol is
//      re-stamped, so contribution passes with a large number while the graph
//      holds yesterday's facts. STANDING OPEN RED, NOT CLOSED. `hashIndexFile`
//      records the ingested file's path + sha256 + size so a reader can see it —
//      citation, not prevention.
//
// WHAT THIS STILL CANNOT DO — named, not hidden:
//   * It judges PRESENCE, not QUALITY. Correct paths with one bogus edge each
//     read HEALTHY. Presence is cheap to measure; quality needs an oracle.

import { createHash } from "node:crypto";
import { createReadStream, readdirSync, statSync } from "node:fs";
import { basename, extname, join } from "node:path";

import type { Store } from "../store";
import { EDGE_KIND_VALUES, type EdgeKind } from "../store/types.ts";
import { DEFAULT_EXCLUDE_DIRS } from "../extractor/walker.ts";
import type {
  CensusBlock,
  ContributionBlock,
  CorrespondenceBlock,
  CorrespondenceLevel,
  IndexIdentity,
  LaneRecord,
} from "../store/health.ts";

/** Default minimum correspondence between the graph and the local source tree. */
export const DEFAULT_MIN_COVERAGE = 0.1;

/**
 * Extensions counted as "source" for the correspondence denominator.
 * Deliberately WIDER than the set metacoding can index: the whole point is to
 * notice a repo whose real language no lane can see (fosite's 262 `.go` files).
 * Adding a language here makes the measure stricter, never weaker.
 */
const SOURCE_EXTS = new Set([
  ".ts", ".tsx", ".mts", ".cts", ".js", ".jsx", ".mjs", ".cjs",
  ".py", ".php", ".phtml", ".go", ".rs", ".rb", ".java", ".kt", ".kts",
  ".cs", ".swift", ".scala", ".c", ".h", ".cc", ".cpp", ".hpp", ".m", ".mm",
  ".ex", ".exs", ".erl", ".hs", ".ml", ".clj", ".lua", ".dart", ".zig",
]);

/**
 * Edge kinds that carry actual relational meaning. CONTAINS is excluded on
 * purpose: a file-contains-class graph can be complete and still say nothing
 * about behaviour, and it is exactly what a dead SCIP lane leaves behind when
 * the tree-sitter lane runs alone.
 */
const RELATIONAL_EDGE_KINDS: readonly EdgeKind[] = EDGE_KIND_VALUES.filter(
  (k) => k !== "CONTAINS",
);

/** Census of the source files physically present in the indexed tree. */
export interface SourceCensus {
  total: number;
  /** File count per extension, descending — used to name what was missed. */
  byExt: Record<string, number>;
  /** Repo-relative paths, POSIX-normalized. The correspondence denominator SET. */
  files: string[];
}

/** THIS SESSION's contribution, scoped by the run stamp on Symbol.indexed_at. */
export type RunContribution = ContributionBlock;

export type FailureCode =
  | "LANE_FAILED"
  | "NO_FILES_SCANNED"
  | "NO_SYMBOLS"
  | "NO_SCIP_SYMBOLS_THIS_RUN"
  | "NO_RELATIONAL_EDGES"
  | "ZERO_CONTRIBUTION_AT_NEW_COMMIT"
  | "LOW_CORRESPONDENCE"
  | "UNMEASURABLE_CORRESPONDENCE";

export interface GateFailure {
  code: FailureCode;
  message: string;
}

export interface GateInput {
  repo: string;
  targetPath: string;
  lanes: LaneRecord[];
  source: SourceCensus;
  /** What THIS RUN wrote (measured in the store, scoped by run stamp). */
  contribution: RunContribution;
  /** What the STORE holds for (repo, branch), by whichever run put it there. */
  fitness: CensusBlock;
  correspondence: CorrespondenceBlock;
  /** True when this run was supposed to produce a SCIP graph (--scip or --load-scip). */
  scipRequested: boolean;
  /** The commit this run claims. */
  commitSha: string | null;
  /** The commit the last FINALIZED record claimed, if any. */
  prevCommitSha: string | null;
  minCoverage?: number;
}

export interface GateResult {
  ok: boolean;
  failures: GateFailure[];
  /** True when this run claims a different commit than the last finalized record. */
  commitAdvanced: boolean;
  contribution: RunContribution;
  fitness: CensusBlock;
  correspondence: CorrespondenceBlock;
  filesScannedByLanes: number;
}

// ---------------------------------------------------------------------------
// Measurements — each one named for the SET its claim is about
// ---------------------------------------------------------------------------

/**
 * Count source files in the tree, using the same exclusions as the walker
 * (node_modules, dist, dot-directories, …) so the denominator matches what any
 * lane could plausibly have indexed. Returns the PATHS as well as the count:
 * correspondence is a set intersection, not a ratio of two unrelated counts.
 */
export function censusSourceFiles(root: string): SourceCensus {
  const exclude = new Set(DEFAULT_EXCLUDE_DIRS);
  const byExt: Record<string, number> = {};
  const files: string[] = [];

  const walk = (dir: string, rel: string, depth: number): void => {
    if (depth > 24) return;
    let names: string[];
    try { names = readdirSync(dir); } catch { return; }
    for (const name of names) {
      if (exclude.has(name)) continue;
      if (name.startsWith(".")) continue;
      const abs = join(dir, name);
      const relPath = rel === "" ? name : `${rel}/${name}`;
      let st;
      try { st = statSync(abs); } catch { continue; }
      if (st.isDirectory()) { walk(abs, relPath, depth + 1); continue; }
      if (!st.isFile()) continue;
      const ext = extname(name).toLowerCase();
      if (!SOURCE_EXTS.has(ext)) continue;
      byExt[ext] = (byExt[ext] ?? 0) + 1;
      files.push(relPath);
    }
  };
  walk(root, "", 0);
  return { total: files.length, byExt, files };
}

/** Shared edge/symbol counting core. `extra` is an additional WHERE clause on `s`/`a`. */
async function censusWithFilter(
  store: Store,
  params: Record<string, unknown>,
  symbolWhere: string,
  edgeWhere: string,
): Promise<CensusBlock> {
  const symRows = await store.query<{ c: number | bigint }>(
    `MATCH (s:Symbol) WHERE ${symbolWhere} RETURN count(s) AS c`,
    params,
  );
  const symbols = Number(symRows[0]?.c ?? 0);

  const edgesByKind: Record<string, number> = {};
  let relationalEdges = 0;
  for (const kind of EDGE_KIND_VALUES) {
    // Edge REL tables are per-kind, so the label can't be parameterized. `kind`
    // comes from the frozen EDGE_KIND_VALUES tuple, never from user input.
    const rows = await store.query<{ c: number | bigint }>(
      `MATCH (a:Symbol)-[r:${kind}]->(:Symbol) WHERE ${edgeWhere} RETURN count(r) AS c`,
      params,
    );
    const n = Number(rows[0]?.c ?? 0);
    edgesByKind[kind] = n;
    if (RELATIONAL_EDGE_KINDS.includes(kind)) relationalEdges += n;
  }
  return { symbols, edgesByKind, relationalEdges };
}

/**
 * What the STORE holds for (repo, branch) — the store's FITNESS, regardless of
 * which run established it.
 *
 * Scoped by the SOURCE symbol's (repo, branch), the same scope as the symbol
 * count, so a populated sibling repo or branch in a shared corpus cannot vouch
 * for this slice. (External boundary nodes only ever appear as targets, so the
 * filter on `a` does not exclude them.)
 */
export async function measureStoreFitness(
  store: Store,
  repo: string,
  branch: string,
): Promise<CensusBlock> {
  return censusWithFilter(
    store,
    { repo, branch },
    `s.repo = $repo AND s.branch = $branch`,
    `a.repo = $repo AND a.branch = $branch`,
  );
}

/**
 * What THIS SESSION wrote — scoped by the run stamp on `Symbol.indexed_at`,
 * which every lane sets from one constant per run. Edges attribute through
 * their source symbol.
 *
 * This is the quantity the old gate did not have and substituted a repo-wide
 * census for (MetaCoding-4kg). It is NEVER used as a proxy for fitness, and
 * fitness is never used as a proxy for it.
 */
export async function measureRunContribution(
  store: Store,
  repo: string,
  branch: string,
  runStamp: string,
): Promise<RunContribution> {
  const params = { repo, branch, stamp: runStamp };
  const scoped = `s.repo = $repo AND s.branch = $branch AND s.indexed_at = timestamp($stamp)`;
  const edgeScoped = `a.repo = $repo AND a.branch = $branch AND a.indexed_at = timestamp($stamp)`;
  const block = await censusWithFilter(store, params, scoped, edgeScoped);
  const scipRows = await store.query<{ c: number | bigint }>(
    `MATCH (s:Symbol) WHERE ${scoped} AND s.source = 'scip' RETURN count(s) AS c`,
    params,
  );
  return { ...block, scipSymbols: Number(scipRows[0]?.c ?? 0) };
}

/** POSIX-normalize a path for set comparison: strip "./", collapse "\\" to "/". */
function normPath(p: string): string {
  let s = p.replace(/\\/g, "/");
  while (s.startsWith("./")) s = s.slice(2);
  while (s.startsWith("/")) s = s.slice(1);
  return s;
}

/** Every path-suffix of `p` at a segment boundary, including `p` itself. */
function pathSuffixes(p: string): string[] {
  const parts = p.split("/");
  const out: string[] = [];
  for (let i = 0; i < parts.length; i++) out.push(parts.slice(i).join("/"));
  return out;
}

/** The distinct `Symbol.file` values the store holds for (repo, branch). */
export async function indexedFilePaths(
  store: Store,
  repo: string,
  branch: string,
): Promise<string[]> {
  const rows = await store.query<{ f: string | null }>(
    `MATCH (s:Symbol) WHERE s.repo = $repo AND s.branch = $branch
     RETURN DISTINCT s.file AS f`,
    { repo, branch },
  );
  const out: string[] = [];
  for (const r of rows) {
    if (typeof r.f === "string" && r.f.length > 0) out.push(normPath(r.f));
  }
  return out;
}

/**
 * CORRESPONDENCE, replacing the old `coverage`.
 *
 * The old measure compared a SCIP DOCUMENT COUNT (numerator, paths from any
 * filesystem) with the LOCAL SOURCE FILE COUNT (denominator) — two different
 * sets, so it read 100% with zero repo files indexed (MetaCoding-5fi). This is
 * a set INTERSECTION over `Symbol.file` against the local tree.
 *
 * The granularity LADDER, because a legitimate out-of-band build (farmOS in
 * Docker, scip-php without the PSR-4 sidecar) has a container prefix on every
 * path and would otherwise be indistinguishable from a vendored-dependency
 * index:
 *
 *   1. exact     — repo-relative path equality
 *   2. suffix    — an indexed path ENDS WITH the source path (survives /app/web/)
 *   3. basename  — file names correspond (survives an arbitrary prefix)
 *   4. unmeasurable(reason)
 *
 * The FIRST rung that intersects at all wins, and the rung used is recorded.
 * Basename correspondence distinguishes farmOS-in-Docker (every
 * `farm_animal.module` appears in both sets) from a vendored index (no basename
 * corresponds anywhere). `unmeasurable` is a real outcome and NEVER a pass.
 */
export async function measureCorrespondence(
  store: Store,
  repo: string,
  branch: string,
  source: SourceCensus,
): Promise<CorrespondenceBlock> {
  const indexed = await indexedFilePaths(store, repo, branch);
  const base = { sourceFiles: source.total, indexedFiles: indexed.length };

  if (source.total === 0) {
    return {
      ...base, level: "unmeasurable", matched: 0, ratio: null,
      reason:
        "the tree contains no files with a known source extension, so there is " +
        "nothing for the graph to correspond TO. Fitness rests entirely on the " +
        "symbol and relational-edge measures.",
    };
  }
  if (indexed.length === 0) {
    return {
      ...base, level: "unmeasurable", matched: 0, ratio: null,
      reason: `the store holds no files at all for ${repo}@${branch}.`,
    };
  }

  const src = source.files.map(normPath);

  // 1. exact
  const exact = new Set(indexed);
  let matched = src.filter((f) => exact.has(f)).length;
  if (matched > 0) return finish("exact", matched);

  // 2. suffix — an indexed path ends with the source path at a segment boundary
  const suffixes = new Set<string>();
  for (const p of indexed) for (const s of pathSuffixes(p)) suffixes.add(s);
  matched = src.filter((f) => suffixes.has(f)).length;
  if (matched > 0) return finish("suffix", matched);

  // 3. basename
  const bases = new Set(indexed.map((p) => basename(p)));
  matched = src.filter((f) => bases.has(basename(f))).length;
  if (matched > 0) return finish("basename", matched);

  // 4. unmeasurable
  return {
    ...base, level: "unmeasurable", matched: 0, ratio: null,
    reason:
      `none of the ${indexed.length} indexed file path(s) correspond to any of ` +
      `the ${source.total} local source file(s) by path, path-suffix, or even ` +
      `basename. The graph is about some OTHER tree (vendored dependencies, a ` +
      `different repo, or a stale index).`,
  };

  function finish(level: CorrespondenceLevel, m: number): CorrespondenceBlock {
    return { ...base, level, matched: m, ratio: Math.min(1, m / source.total) };
  }
}

/**
 * Identity of an ingested pre-built index file: path + sha256 + size.
 *
 * This does NOT close the open red it exists for — re-ingesting yesterday's
 * `.scip` at a new commit still re-stamps every symbol, so contribution reads
 * large while the graph holds yesterday's facts. Recording the hash makes that
 * VISIBLE TO A READER comparing two runs. Citation, not prevention.
 */
export async function hashIndexFile(path: string): Promise<IndexIdentity> {
  const size = statSync(path).size;
  const hash = createHash("sha256");
  await new Promise<void>((res, rej) => {
    createReadStream(path)
      .on("data", (c) => hash.update(c))
      .on("end", () => res())
      .on("error", rej);
  });
  return { path, sha256: hash.digest("hex"), size };
}

// ---------------------------------------------------------------------------
// The verdict
// ---------------------------------------------------------------------------

/** Pure evaluation of the property. Every input is a measurement. */
export function evaluateIndexOutcome(input: GateInput): GateResult {
  const minCoverage = input.minCoverage ?? DEFAULT_MIN_COVERAGE;
  const failures: GateFailure[] = [];
  const filesScannedByLanes = input.lanes.reduce((m, l) => Math.max(m, l.files), 0);
  const commitAdvanced =
    input.commitSha !== null &&
    input.prevCommitSha !== null &&
    input.commitSha !== input.prevCommitSha;

  // (1) A lane that died fails the run, even when a sibling lane succeeded.
  for (const lane of input.lanes) {
    if (lane.ok) continue;
    failures.push({
      code: "LANE_FAILED",
      message:
        `lane '${lane.lane}' failed: ${lane.error ?? "unknown error"}\n` +
        `    A failed lane leaves a graph missing whatever that lane would have\n` +
        `    contributed. Previously this was logged and ignored.`,
    });
  }

  // (2) Did any lane READ anything? This claim is about the LANES, so a lane
  //     accumulator is the correct subject to measure — unlike every claim below.
  if (filesScannedByLanes === 0) {
    failures.push({
      code: "NO_FILES_SCANNED",
      message:
        `no lane read a single file (${input.source.total} source file(s) present` +
        `${describeTopExts(input.source)}).\n` +
        `    Every lane scanned 0 files, so the graph for '${input.repo}' cannot\n` +
        `    contain anything this run produced.`,
    });
  }

  // (3) Does the STORE hold anything for this slice? Subject: the store.
  if (input.fitness.symbols === 0) {
    failures.push({
      code: "NO_SYMBOLS",
      message:
        `the store holds 0 symbols for repo '${input.repo}' after the run\n` +
        `    (${filesScannedByLanes} file(s) were read by some lane).\n` +
        `    Files went in and nothing came out.`,
    });
  }

  // (4) Did THIS RUN's SCIP lanes put anything in the STORE? Subject: this run.
  //     The old gate counted DOCUMENTS here, and an empty document is a
  //     document (MetaCoding-4kg). This counts store-visible symbols stamped
  //     with this run's id whose source is 'scip'. It never false-alarms on a
  //     no-op re-index, because an idempotent MERGE still re-stamps indexed_at.
  if (input.scipRequested && input.contribution.scipSymbols === 0) {
    failures.push({
      code: "NO_SCIP_SYMBOLS_THIS_RUN",
      message:
        `SCIP was requested but no SCIP lane wrote a single STORE-VISIBLE symbol\n` +
        `    this run (lanes: ${input.lanes.map((l) => l.lane).join(", ") || "none ran"}).\n` +
        `    Measured by this run's stamp on Symbol.indexed_at, so a previous good\n` +
        `    run's symbols cannot vouch for it, and an empty document cannot pass\n` +
        `    as a document.`,
    });
  }

  // (5) SCIP was asked for; a graph with no relational edges is not one.
  if (input.scipRequested && input.fitness.relationalEdges === 0) {
    failures.push({
      code: "NO_RELATIONAL_EDGES",
      message:
        `SCIP was requested but the store holds 0 relational edges for repo` +
        ` '${input.repo}'\n` +
        `    (CALLS ${input.fitness.edgesByKind["CALLS"] ?? 0}, REFERENCES ` +
        `${input.fitness.edgesByKind["REFERENCES"] ?? 0}, IMPLEMENTS ` +
        `${input.fitness.edgesByKind["IMPLEMENTS"] ?? 0}).\n` +
        `    This is the MetaCoding-hy6.16 shape: a graph that answers every\n` +
        `    query with an empty result and looks like a real one.`,
    });
  }

  // (6) The CORRECTED MetaCoding-4kg. A zero-contribution re-index at the SAME
  //     commit into an already-fit store is DEFENSIBLE — the store genuinely is
  //     fit, and a rule that false-alarms on the most common invocation is a
  //     rule people disable. What is NOT defensible is claiming to ADVANCE to a
  //     new commit while contributing nothing: fitness was established at W, the
  //     run says X, and everything downstream believes it is looking at X.
  if (commitAdvanced && input.contribution.symbols === 0) {
    failures.push({
      code: "ZERO_CONTRIBUTION_AT_NEW_COMMIT",
      message:
        `this run claims commit ${short(input.commitSha)} but the last established\n` +
        `    record claims ${short(input.prevCommitSha)}, and the run wrote 0 symbols.\n` +
        `    The store still holds the graph of ${short(input.prevCommitSha)} while every\n` +
        `    reader would now believe it holds ${short(input.commitSha)}.`,
    });
  }

  // (7) CORRESPONDENCE, not coverage: a set intersection over Symbol.file.
  const c = input.correspondence;
  if (c.level === "unmeasurable" && c.sourceFiles > 0) {
    failures.push({
      code: "UNMEASURABLE_CORRESPONDENCE",
      message:
        `the graph's correspondence to the local tree could not be established at\n` +
        `    ANY granularity (exact path, path suffix, basename): ${c.reason}\n` +
        `    UNMEASURABLE is never a pass on its own.`,
    });
  } else if (c.ratio !== null && c.ratio < minCoverage) {
    failures.push({
      code: "LOW_CORRESPONDENCE",
      message:
        `only ${c.matched}/${c.sourceFiles} local source file(s) correspond to an ` +
        `indexed file at '${c.level}' granularity ` +
        `(${(c.ratio * 100).toFixed(1)}%, floor ${(minCoverage * 100).toFixed(0)}%)` +
        `${describeTopExts(input.source)}.\n` +
        `    A graph over a sliver of the repo answers structural questions as\n` +
        `    confidently as a complete one, and wrongly.`,
    });
  }

  return {
    ok: failures.length === 0,
    failures,
    commitAdvanced,
    contribution: input.contribution,
    fitness: input.fitness,
    correspondence: c,
    filesScannedByLanes,
  };
}

function short(sha: string | null): string {
  return sha ? sha.slice(0, 7) : "(none)";
}

function describeTopExts(source: SourceCensus): string {
  const top = Object.entries(source.byExt)
    .sort((a, b) => b[1] - a[1])
    .slice(0, 3)
    .map(([ext, n]) => `${n} ${ext}`);
  return top.length > 0 ? ` — dominant: ${top.join(", ")}` : "";
}

/** Render the failure block printed to stderr before a non-zero exit. */
export function formatGateFailure(repo: string, target: string, r: GateResult): string {
  const c = r.correspondence;
  return [
    `metacoding: INDEX REFUSED — the run produced an unusable graph for '${repo}'.`,
    `  target: ${target}`,
    ...r.failures.map((f) => `  [${f.code}] ${f.message}`),
    `  this run's CONTRIBUTION: ${r.contribution.symbols} symbols ` +
      `(${r.contribution.scipSymbols} from SCIP), ${r.contribution.relationalEdges} relational edges.`,
    `  the STORE's FITNESS:     ${r.fitness.symbols} symbols, ${r.fitness.relationalEdges} relational edges` +
      ` (CALLS ${r.fitness.edgesByKind["CALLS"] ?? 0} / REFERENCES ${r.fitness.edgesByKind["REFERENCES"] ?? 0}` +
      ` / IMPLEMENTS ${r.fitness.edgesByKind["IMPLEMENTS"] ?? 0}).`,
    `  CORRESPONDENCE: ${c.matched}/${c.sourceFiles} source files at '${c.level}' granularity` +
      `${c.ratio === null ? "" : ` (${(c.ratio * 100).toFixed(1)}%)`}.`,
    `  The verdict is PERSISTED beside the graph (index-health.sqlite) as REFUSED,`,
    `  so every reader sees it — the exit code is a VIEW of that fact, not the fact.`,
    `  If a degraded graph is genuinely what you want, re-run with`,
    `  --allow-empty-index (and/or --min-coverage <0..1>) to record that choice`,
    `  as OVERRIDDEN, with the flag and value, visible at read time forever.`,
  ].join("\n");
}
