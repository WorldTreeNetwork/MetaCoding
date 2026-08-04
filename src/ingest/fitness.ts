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
//   measureGraphFreshness    — whether the files the STORE holds still match the
//                              bytes on disk. This is the only quantity that can
//                              say "the graph IS the tree at this commit", and
//                              contribution cannot be substituted for it.
//
// Per-run attribution needs NO schema change and NO migration: `Symbol.indexed_at`
// is set from one constant per session, threaded through both lanes, and is not
// COALESCE-protected, so it is always overwritten *by any lane that writes the
// symbol*. Verified directly against a live ladybugdb store:
//   `MATCH (s:Symbol) WHERE s.indexed_at = timestamp($t)` selects exactly the
//   symbols stamped by run $t, composes with `s.source = 'scip'`, and edges
//   attribute through their SOURCE symbol
//   (`MATCH (a)-[r:CALLS]->() WHERE a.indexed_at = timestamp($t)`).
//
// CORRECTION (bead MetaCoding-c03). This module used to say `indexed_at` "is
// always overwritten", and rule (4) used to say the SCIP measure "never
// false-alarms on a no-op re-index, because an idempotent MERGE still re-stamps
// indexed_at". THE STORE HALF IS TRUE AND THE LANE HALF IS FALSE: the walker
// stamps each file Symbol's `ast_hash` with the content hash "so the next pass
// can skip when content is unchanged" (src/extractor/walker.ts), and A SKIPPED
// FILE NEVER CALLS upsertSymbol AT ALL. Measured by a fresh judge: run 1 over 6
// .ts files stamps 24 symbols; run 2 at a NEW commit that touched only README.md
// re-stamps NOTHING (contribution 0, every symbol still carrying run 1's stamp)
// and was REFUSED [ZERO_CONTRIBUTION_AT_NEW_COMMIT] on a graph that was correct
// and complete; run 3 with one real edit splits the stamps 20/4, which is what
// proves run 2's zero was the SKIP and not a measurement artifact. The old
// verification quoted above probed the STORE, not a RE-RUN of the lane — an
// observation that could not have come out any other way.
//
// The `--scip` path masked it (the loader re-ingests every document), so the
// break is on the tree-sitter-only path: `metacoding index <path>` without
// --scip, on any commit that touches no indexed source file (docs, CI config,
// lockfiles, images, or any language no lane indexes).
//
// HOW WOULD I FAKE THIS? (asked before shipping)
//   1. "Coast on a previous good run" -> measureRunContribution is scoped to
//      this session's stamp, so a run that wrote nothing reads 0 regardless of
//      how full the store is. Zero is only a FAILURE when the commit advanced
//      (ZERO_CONTRIBUTION_AT_NEW_COMMIT) AND the graph could not be shown to
//      still BE the tree (measureGraphFreshness) — a no-op re-index at the same
//      commit into an already-fit store is defensible, and a rule that
//      false-alarms on the most common invocation is a rule people disable.
//   1b. "Use freshness as the new escape hatch" -> it can only ever DISARM a
//      rule that was going to fire anyway; nothing passes because of it that a
//      productive run would not already have passed. It is never a substitute
//      for contribution, it is computed over the STORE's own file rows rather
//      than any lane accumulator, and a store that verified NOTHING (checked 0)
//      does not qualify. A single fresh file cannot vouch for the tree: every
//      stored file that exists on disk must match, or the run stays refused.
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
import { createReadStream, readFileSync, readdirSync, statSync } from "node:fs";
import { basename, extname, join } from "node:path";

import type { Store } from "../store";
import { EDGE_KIND_VALUES, type EdgeKind } from "../store/types.ts";
import { DEFAULT_EXCLUDE_DIRS } from "../extractor/walker.ts";
import { fileContentHash } from "../extractor/identity.ts";
import type {
  CensusBlock,
  ContributionBlock,
  CorrespondenceBlock,
  CorrespondenceLevel,
  FreshnessBlock,
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
  | "ZERO_CONTRIBUTION_AT_UNKNOWN_COMMIT"
  | "LOW_CORRESPONDENCE"
  | "BASENAME_ONLY_CORRESPONDENCE"
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
  /**
   * Whether the graph can be shown to still BE the tree. ABSENT MEANS
   * UNVERIFIED, never "fine": an input that cannot say is treated exactly like
   * one that says no.
   */
  freshness?: FreshnessBlock;
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
  /**
   * True when a previous record named a commit and THIS run cannot name one, so
   * advancement can be neither established nor ruled out. Degrades SAFE.
   */
  commitUncertain: boolean;
  /** True when the graph was shown to still be the tree (see FreshnessBlock). */
  verifiedCurrent: boolean;
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

/**
 * GRAPH FRESHNESS — does the store still hold the bytes that are on disk?
 *
 * The subject of this claim is NEITHER the run NOR the store's size: it is the
 * agreement between the graph and the tree. It exists because contribution
 * cannot answer it (MetaCoding-c03): the walker skips a file whose content hash
 * matches the stored `ast_hash`, and a skipped file is never re-written, so a
 * commit that touched no indexed source file contributes ZERO to a graph that is
 * completely correct.
 *
 * Measured from the STORE's own file rows, never from a lane accumulator — the
 * lane's `filesSkipped` counts an unparseable file as skipped too, and root 1's
 * whole lesson is that the nearest available number is not the subject.
 *
 * `absent` (a stored file that is not on disk) is REPORTED and not counted as
 * stale: SCIP documents carry container-prefixed paths that will never resolve
 * locally, and treating those as staleness would refuse farmOS forever. A
 * deleted-but-still-indexed file therefore shows up here as a number a reader
 * can see, not as a verdict.
 */
export type { FreshnessBlock };

export async function measureGraphFreshness(
  store: Store,
  repo: string,
  branch: string,
  rootPath: string,
): Promise<FreshnessBlock> {
  const rows = await store.query<{ f: string | null; h: string | null }>(
    `MATCH (s:Symbol)
     WHERE s.kind = 'file' AND s.repo = $repo AND s.branch = $branch
     RETURN DISTINCT s.file AS f, s.ast_hash AS h`,
    { repo, branch },
  );
  // Per-commit-identity mode gives one file row PER COMMIT, so a path can carry
  // several hashes; the file is fresh if ANY stored row matches what is on disk.
  const byFile = new Map<string, Set<string>>();
  for (const r of rows) {
    if (typeof r.f !== "string" || r.f.length === 0) continue;
    if (typeof r.h !== "string" || r.h.length === 0) continue;
    const key = normPath(r.f);
    let set = byFile.get(key);
    if (!set) { set = new Set(); byFile.set(key, set); }
    set.add(r.h);
  }

  let checked = 0, fresh = 0, stale = 0, absent = 0;
  const staleExamples: string[] = [];
  for (const [rel, hashes] of byFile) {
    const abs = join(rootPath, rel);
    let content: string;
    try {
      if (!statSync(abs).isFile()) { absent++; continue; }
      content = readFileSync(abs, "utf-8");
    } catch {
      absent++;
      continue;
    }
    checked++;
    if (hashes.has(fileContentHash(content))) fresh++;
    else {
      stale++;
      if (staleExamples.length < 5) staleExamples.push(rel);
    }
  }
  return { checked, fresh, stale, absent, staleExamples };
}

/**
 * True when the graph can be shown to still BE the tree: something was compared
 * and nothing had drifted. A store that verified nothing does NOT qualify — an
 * unverifiable graph is not a verified one.
 */
export function isGraphVerifiedCurrent(f: FreshnessBlock | undefined): boolean {
  return f !== undefined && f.checked > 0 && f.stale === 0;
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
 *   3. basename  — file NAMES correspond (survives an arbitrary prefix)
 *   4. unmeasurable(reason)
 *
 * The FIRST rung that intersects at all wins, and the rung used is recorded.
 * `unmeasurable` is a real outcome and NEVER a pass.
 *
 * WHAT BASENAME CORRESPONDENCE IS WORTH (bead MetaCoding-5fi, re-opened)
 * ---------------------------------------------------------------------
 * The set-intersection fix holds at the exact and suffix rungs. At the BASENAME
 * rung it reproduced 5fi's literal headline. Measured by a fresh judge: a local
 * tree of 6 `.go` files (`detectGrammar('.go')` is null, so the tree-sitter lane
 * contributes nothing — the fosite shape) plus a `.scip` describing
 * `vendor/github.com/other/project/…`, sharing ONLY basenames, came out
 * `{ level: 'basename', matched: 6, ratio: 1 }` -> HEALTHY, with ZERO local
 * files in the graph.
 *
 * The old defence was that 5fi's `vendor40` fixture "intersects in ZERO places
 * at every rung" — but that is a property of that fixture's invented filenames,
 * not of vendoring. Real vendored trees are COPIES of upstream repos, where
 * `client.go` / `config.go` / `index.ts` collisions are the norm.
 *
 * So: a basename match is evidence that two trees use the same FILE NAMES. It is
 * not evidence that they are the same tree, and nothing measurable from paths
 * alone can promote it into one. It therefore does not earn a `ratio` — the
 * quantity that means "this share of the tree is in the graph" — and it emits
 * `BASENAME_ONLY_CORRESPONDENCE`, which like `UNMEASURABLE` is never a pass on
 * its own and must be waived deliberately (recorded OVERRIDDEN, visible at read
 * time forever).
 *
 * The rung is KEPT, and keeping it is the point: it is what makes the case
 * legible in the record ("the names correspond and nothing else does") instead
 * of collapsing into `unmeasurable`. Nothing that legitimately needs an
 * out-of-band build is harmed — a container-prefixed index (farmOS in Docker,
 * `/app/web/…`) lands on SUFFIX, and any run whose tree-sitter lane indexed the
 * local files at all lands on EXACT. Only a graph that shares nothing with this
 * tree but file names is refused.
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

  // Rungs 1 and 2 are PATH evidence: the indexed path contains the local path.
  // The suffix set contains every path in full, so a suffix match is a superset
  // of an exact match and `pathMatched` is the honest count at either rung —
  // taking only the first rung's count would UNDER-report a build that indexed
  // some files locally and some through a container prefix.
  const exact = new Set(indexed);
  const exactMatched = src.filter((f) => exact.has(f)).length;
  const suffixes = new Set<string>();
  for (const p of indexed) for (const s of pathSuffixes(p)) suffixes.add(s);
  const pathMatched = src.filter((f) => suffixes.has(f)).length;
  if (pathMatched > 0) return finish(exactMatched > 0 ? "exact" : "suffix", pathMatched);

  // Rung 3 is NAME evidence only, and it does not earn a ratio (MetaCoding-5fi).
  const bases = new Set(indexed.map((p) => basename(p)));
  const nameMatched = src.filter((f) => bases.has(basename(f))).length;
  if (nameMatched > 0) {
    return {
      ...base, level: "basename", matched: nameMatched, ratio: null,
      reason:
        `${nameMatched}/${source.total} local source file(s) share a FILE NAME with ` +
        `an indexed file, but NOT ONE indexed path contains a local path (not even ` +
        `as a suffix). Same names are not the same tree: a vendored copy of an ` +
        `upstream repo collides on client.go / config.go / index.ts by default. ` +
        `The graph may be of some other tree entirely.`,
    };
  }

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
 * large while the graph holds yesterday's facts. Citation, not prevention.
 *
 * CORRECTION (bead MetaCoding-19g): this used to say recording the hash makes
 * the repetition "visible to a reader COMPARING TWO RUNS", and there was no
 * second run to compare against — the health table is one row per (repo,
 * branch) with DO UPDATE, so writing day 2 destroyed day 1, and the identical
 * sha256 was visible only to someone who had written the previous value down
 * out of band. A citation that cannot be compared is not a mitigation. Finalized
 * records are now appended to `index_health_history`, each record carries the
 * PREVIOUS run's identities in `prev_index_identities`, and
 * `describeIndexRepetition` turns that into the sentence the open red wants a
 * reader to see. Comparable citation. Still not prevention.
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
  // A run with NO commit sha at all cannot be compared against the previous
  // record's, so the commit rule COULD NOT FIRE and the degradation was
  // PERMISSIVE: the one case where we know least got the most lenient reading.
  // It degrades SAFE instead — "may have advanced" — and the same escape
  // applies, so a legitimate no-op re-index of an unchanged non-git tree still
  // passes on the strength of the graph matching the tree.
  // (`commitSha = ""` already counted as advancement, which is the safe side.)
  const commitUncertain = input.commitSha === null && input.prevCommitSha !== null;
  const verifiedCurrent = isGraphVerifiedCurrent(input.freshness);

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
  //     with this run's id whose source is 'scip'.
  //
  //     THE CORRECTED CLAIM (MetaCoding-c03). This used to say it "never
  //     false-alarms on a no-op re-index, because an idempotent MERGE still
  //     re-stamps indexed_at". Re-stamping is a property of the STORE's write
  //     path, not of a run: a lane that SKIPS a file never calls upsertSymbol,
  //     so nothing is merged and nothing is re-stamped. What makes this
  //     particular rule safe is narrower and worth saying exactly: the SCIP
  //     loader has no skip-unchanged path — it re-ingests every document of the
  //     index it is given — so a run that requested SCIP and stamped no SCIP
  //     symbol really did fail to produce one. The tree-sitter lane DOES skip,
  //     which is what broke rule (6) below until freshness was measured.
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
  //
  //     WHAT ZERO CONTRIBUTION DOES *NOT* MEAN (MetaCoding-c03): the walker
  //     SKIPS a file whose content hash still matches the stored one, and a
  //     skipped file is never re-written, so a docs-only commit contributes zero
  //     to a graph that is correct and complete. Measured: run 2 at a new commit
  //     touching only README.md re-stamped nothing and was REFUSED. The fix is
  //     not to relax the rule but to ask the RIGHT question — is the graph still
  //     the tree? — of the quantity that can answer it. Freshness only ever
  //     DISARMS this rule; it can never make anything else pass.
  if (
    (commitAdvanced || commitUncertain) &&
    input.contribution.symbols === 0 &&
    !verifiedCurrent
  ) {
    const f = input.freshness;
    const why = f === undefined
      ? `and freshness was not measured, so the graph cannot be shown to be this tree`
      : f.checked === 0
        ? `and NOT ONE of the files the store holds could be compared against the ` +
          `tree (${f.absent} stored file(s) are not on disk), so the graph cannot ` +
          `be shown to be this tree`
        : `and ${f.stale}/${f.checked} of the files the store holds have CHANGED on ` +
          `disk since the graph was built (${f.staleExamples.join(", ")}${
            f.stale > f.staleExamples.length ? ", …" : ""})`;
    failures.push(
      commitAdvanced
        ? {
            code: "ZERO_CONTRIBUTION_AT_NEW_COMMIT",
            message:
              `this run claims commit ${short(input.commitSha)} but the last established\n` +
              `    record claims ${short(input.prevCommitSha)}, and the run wrote 0 symbols\n` +
              `    ${why}.\n` +
              `    The store still holds the graph of ${short(input.prevCommitSha)} while every\n` +
              `    reader would now believe it holds ${short(input.commitSha)}.`,
          }
        : {
            code: "ZERO_CONTRIBUTION_AT_UNKNOWN_COMMIT",
            message:
              `this run names NO commit while the last established record claims\n` +
              `    ${short(input.prevCommitSha)}, and the run wrote 0 symbols ${why}.\n` +
              `    Whether the tree advanced can be neither established nor ruled out, so\n` +
              `    this degrades to the SAFE reading rather than the permissive one: an\n` +
              `    unnameable commit is not a licence to assume the graph is current.`,
          },
    );
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
  } else if (c.level === "basename" && c.sourceFiles > 0) {
    failures.push({
      code: "BASENAME_ONLY_CORRESPONDENCE",
      message:
        `the graph corresponds to this tree by FILE NAME ONLY: ${c.reason}\n` +
        `    A name match is evidence that two trees use the same file names, not\n` +
        `    that they are the same tree — and measured from paths, nothing can tell\n` +
        `    those apart (MetaCoding-5fi: 6 vendored '.go' files scored ratio 1.0 and\n` +
        `    HEALTHY with zero local files in the graph). A container-prefixed build\n` +
        `    lands on SUFFIX and is unaffected; this rung is never a pass on its own.\n` +
        `    If the graph really is this tree, waive it with --allow-empty-index and\n` +
        `    the waiver is in the record forever.`,
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
    commitUncertain,
    verifiedCurrent,
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
