// The productivity gate for `metacoding index` — bead MetaCoding-0sd.
//
// THE PROPERTY THIS ENFORCES
// ==========================
//   An index run may report success only if the STORE it wrote actually holds,
//   for the repo it just indexed, the structural content that run claimed to
//   produce: every lane that was asked to run completed, a non-trivial share of
//   the repo's source files was covered, and — when SCIP was requested — the
//   store holds symbols AND non-zero relational edges for that repo.
//   Anything less is a FAILURE OF THE RUN, not a warning on stderr.
//
// It is deliberately stated as a property of the OUTCOME rather than as a block
// on one known-bad input. The motivating instance (MetaCoding-0sd) was
// `metacoding index <ory/fosite> --scip` exiting 0 with a completely empty
// graph: fosite is a Go repo that ships package.json + tsconfig.json, so
// detectScipLanguages() picked scip-typescript, which failed with "no files got
// indexed"; the failure was caught, logged, and the run reported success.
// `resolveScipWanted` guarded indexer AVAILABILITY; availability was never the
// risk. Special-casing "Go repo with a package.json" would close that instance
// and leave the family alive — wrong indexer selected, indexer binary silently
// failing, a detected language with no extractor, an empty repo, a lane that
// dies while a sibling lane succeeds. The family is what this gate is about.
//
// It is the second time this failure has been paid for: MetaCoding-hy6.16 ran a
// full 41-row re-scoring pass over a graph with CALLS = 0 and REFERENCES = 0 and
// mistook the empty result for a real one.
//
// HOW WOULD I FAKE THIS? (asked before shipping — docs/design/iteration-methodology.md)
// ------------------------------------------------------------------------------
//   1. "Index ONE trivial file out of 273 and pass a `> 0` threshold."
//      Answered by COVERAGE: the run must cover at least `minCoverage` of the
//      repo's source files (default 10%). One file of 273 is 0.4% and fails.
//      A bare `> 0` check would wave it through, which is why there isn't one.
//   2. "A multi-language repo where one lane succeeds and another silently dies."
//      Answered by LANE_FAILED: a lane that throws is now fatal for the WHOLE
//      run, and every lane's outcome is reported, not just the first. Previously
//      the throw was swallowed by a `catch` that printed one stderr line.
//   3. "Are '0 files scanned' and 'files scanned but 0 symbols' distinguishable?"
//      They are separate codes with separate messages (NO_FILES_SCANNED vs
//      NO_SYMBOLS), because they have different causes: nothing to index vs an
//      extractor/loader that produced nothing from what it read.
//   4. "Report success from the run's own accumulators while the store is empty."
//      Answered by reading the STORE after the run (`storeCensus`) rather than
//      trusting the counters the indexer returned. A loader that silently drops
//      every upsert still fails the gate.
//   5. "...and the mirror of (4): coast on a PREVIOUS good run's symbols while
//      this run produced nothing." The store census cannot tell the two apart —
//      it sees a populated graph either way. Answered by NO_SCIP_DOCUMENTS,
//      which checks THIS run's SCIP lanes emitted documents, independently of
//      what the store holds.
//
// WHAT IT STILL CANNOT DO — named, not hidden:
//   * It judges PRESENCE, not QUALITY. A run that produces plentiful but wrong
//     edges passes. Correctness of edges is the loader's tests' job.
//   * `minCoverage` is a threshold, and any threshold can be sat just above.
//     A run covering 11% of a repo passes; that is a deliberate trade against
//     false alarms on genuinely partial languages, and it is visible in the
//     JSON summary (`gate.coverage`) of every run.
//   * A repo written entirely in a language absent from SOURCE_EXTS has an
//     empty denominator; then the gate falls back to symbols-in-store, which is
//     still enough to catch the empty-graph family.

import { readdirSync, statSync } from "node:fs";
import { extname, join } from "node:path";

import type { Store } from "../store";
import { EDGE_KIND_VALUES, type EdgeKind } from "../store/types.ts";
import { DEFAULT_EXCLUDE_DIRS } from "../extractor/walker.ts";

/** Default minimum share of a repo's source files a successful run must cover. */
export const DEFAULT_MIN_COVERAGE = 0.1;

/**
 * Extensions counted as "source" for the coverage denominator. Deliberately
 * WIDER than the set metacoding can index: the whole point is to notice a repo
 * whose real language no lane can see (fosite's 262 `.go` files). Adding a
 * language here makes the gate stricter, never weaker.
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

/** The outcome of one indexing lane within a single `index` run. */
export interface LaneOutcome {
  /** Human label, e.g. "tree-sitter", "scip:typescript", "scip:load-scip". */
  lane: string;
  /** False when the lane threw. A failed lane fails the run. */
  ok: boolean;
  /** Error message when `ok` is false. */
  error?: string;
  /** Files/documents this lane looked at (walker filesScanned, SCIP documents). */
  files: number;
}

/** Census of the source files physically present in the indexed tree. */
export interface SourceCensus {
  total: number;
  /** File count per extension, descending — used to name what was missed. */
  byExt: Record<string, number>;
}

/** What the store actually holds for (repo, branch) AFTER the run. */
export interface StoreCensus {
  symbols: number;
  edgesByKind: Record<string, number>;
  /** Sum over RELATIONAL_EDGE_KINDS. */
  relationalEdges: number;
}

export interface GateInput {
  repo: string;
  targetPath: string;
  lanes: LaneOutcome[];
  source: SourceCensus;
  store: StoreCensus;
  /** True when this run was supposed to produce a SCIP graph (--scip or --load-scip). */
  scipRequested: boolean;
  minCoverage?: number;
}

export interface GateFailure {
  code:
    | "LANE_FAILED"
    | "NO_FILES_SCANNED"
    | "NO_SYMBOLS"
    | "NO_SCIP_DOCUMENTS"
    | "NO_RELATIONAL_EDGES"
    | "LOW_COVERAGE";
  message: string;
}

export interface GateResult {
  ok: boolean;
  failures: GateFailure[];
  /** filesCovered / source.total, clamped to [0,1]; null when denominator is 0. */
  coverage: number | null;
  filesCovered: number;
  sourceFiles: number;
  symbols: number;
  relationalEdges: number;
  edgesByKind: Record<string, number>;
}

/**
 * Count source files in the tree, using the same exclusions as the walker
 * (node_modules, dist, dot-directories, …) so the denominator matches what any
 * lane could plausibly have indexed.
 */
export function censusSourceFiles(root: string): SourceCensus {
  const exclude = new Set(DEFAULT_EXCLUDE_DIRS);
  const byExt: Record<string, number> = {};
  let total = 0;

  const walk = (dir: string, depth: number): void => {
    if (depth > 24) return;
    let names: string[];
    try { names = readdirSync(dir); } catch { return; }
    for (const name of names) {
      if (exclude.has(name)) continue;
      if (name.startsWith(".")) continue;
      const abs = join(dir, name);
      let st;
      try { st = statSync(abs); } catch { continue; }
      if (st.isDirectory()) { walk(abs, depth + 1); continue; }
      if (!st.isFile()) continue;
      const ext = extname(name).toLowerCase();
      if (!SOURCE_EXTS.has(ext)) continue;
      byExt[ext] = (byExt[ext] ?? 0) + 1;
      total++;
    }
  };
  walk(root, 0);
  return { total, byExt };
}

/**
 * Read what the store holds for (repo, branch): symbol count and edge count BY
 * TYPE. This is the load-bearing measurement — the gate never trusts the
 * indexer's own accumulators, because an accumulator can be non-zero while
 * nothing reached the graph.
 */
export async function storeCensus(
  store: Store,
  repo: string,
  branch: string,
): Promise<StoreCensus> {
  const symRows = await store.query<{ c: number | bigint }>(
    `MATCH (s:Symbol) WHERE s.repo = $repo AND s.branch = $branch
     RETURN count(s) AS c`,
    { repo, branch },
  );
  const symbols = Number(symRows[0]?.c ?? 0);

  const edgesByKind: Record<string, number> = {};
  let relationalEdges = 0;
  for (const kind of EDGE_KIND_VALUES) {
    // Edge REL tables are per-kind, so the label can't be parameterized. `kind`
    // comes from the frozen EDGE_KIND_VALUES tuple, never from user input.
    // Scoped by the SOURCE symbol's (repo, branch) — same scope as the symbol
    // count above, so a populated sibling branch can't vouch for this one.
    // (External boundary nodes only ever appear as targets, so they are not
    // excluded by the branch filter on `a`.)
    const rows = await store.query<{ c: number | bigint }>(
      `MATCH (a:Symbol)-[r:${kind}]->(:Symbol)
       WHERE a.repo = $repo AND a.branch = $branch
       RETURN count(r) AS c`,
      { repo, branch },
    );
    const n = Number(rows[0]?.c ?? 0);
    edgesByKind[kind] = n;
    if (RELATIONAL_EDGE_KINDS.includes(kind)) relationalEdges += n;
  }
  return { symbols, edgesByKind, relationalEdges };
}

/** Pure evaluation of the property. Every input is a measurement. */
export function evaluateIndexOutcome(input: GateInput): GateResult {
  const minCoverage = input.minCoverage ?? DEFAULT_MIN_COVERAGE;
  const failures: GateFailure[] = [];

  const filesCovered = input.lanes.reduce((m, l) => Math.max(m, l.files), 0);
  const coverage =
    input.source.total > 0
      ? Math.min(1, filesCovered / input.source.total)
      : null;

  // (1) A lane that died fails the run, even when a sibling lane succeeded.
  for (const lane of input.lanes) {
    if (lane.ok) continue;
    failures.push({
      code: "LANE_FAILED",
      message:
        `lane '${lane.lane}' failed: ${lane.error ?? "unknown error"}\n` +
        `    A failed lane leaves a graph that is missing whatever that lane\n` +
        `    would have contributed. Previously this was logged and ignored.`,
    });
  }

  // (2) vs (3): nothing to read, or nothing came out of what was read.
  //     Different causes, different messages — kept distinguishable on purpose.
  if (filesCovered === 0) {
    failures.push({
      code: "NO_FILES_SCANNED",
      message:
        `no lane indexed a single file (${input.source.total} source files present` +
        `${describeTopExts(input.source)}).\n` +
        `    Every lane scanned 0 files, so the graph for '${input.repo}' cannot\n` +
        `    contain anything this run produced.`,
    });
  } else if (input.store.symbols === 0) {
    failures.push({
      code: "NO_SYMBOLS",
      message:
        `${filesCovered} file(s) were indexed but the store holds 0 symbols for` +
        ` repo '${input.repo}'.\n` +
        `    Files were read and nothing came out of them.`,
    });
  }

  // (3b) The store census reads the WHOLE store for this repo, which may still
  //      hold a PREVIOUS good run's content. So a SCIP lane that runs, exits
  //      clean and emits nothing would coast on stale symbols. Check the run's
  //      own SCIP output too: requested SCIP must have produced documents.
  if (input.scipRequested) {
    const scipLanes = input.lanes.filter((l) => l.lane.startsWith("scip:"));
    const scipDocs = scipLanes.reduce((n, l) => n + l.files, 0);
    if (scipDocs === 0) {
      failures.push({
        code: "NO_SCIP_DOCUMENTS",
        message:
          `SCIP was requested but no SCIP lane produced a single document ` +
          `(lanes: ${scipLanes.map((l) => l.lane).join(", ") || "none ran"}).\n` +
          `    Checked separately from the store because the store can still hold\n` +
          `    a previous run's symbols — which would make THIS run look productive.`,
      });
    }
  }

  // (4) SCIP was asked for; a graph with no relational edges is not one.
  if (input.scipRequested && input.store.relationalEdges === 0) {
    failures.push({
      code: "NO_RELATIONAL_EDGES",
      message:
        `SCIP was requested but the store holds 0 relational edges for repo` +
        ` '${input.repo}'\n` +
        `    (CALLS ${input.store.edgesByKind["CALLS"] ?? 0}, REFERENCES ` +
        `${input.store.edgesByKind["REFERENCES"] ?? 0}, IMPLEMENTS ` +
        `${input.store.edgesByKind["IMPLEMENTS"] ?? 0}).\n` +
        `    This is the MetaCoding-hy6.16 shape: a graph that answers every\n` +
        `    query with an empty result and looks like a real one.`,
    });
  }

  // (5) Covered *something*, but so little that the graph misrepresents the repo.
  if (
    coverage !== null &&
    filesCovered > 0 &&
    coverage < minCoverage
  ) {
    failures.push({
      code: "LOW_COVERAGE",
      message:
        `only ${filesCovered}/${input.source.total} source files were indexed ` +
        `(${(coverage * 100).toFixed(1)}%, floor ${(minCoverage * 100).toFixed(0)}%)` +
        `${describeTopExts(input.source)}.\n` +
        `    A graph over a sliver of the repo answers structural questions as\n` +
        `    confidently as a complete one, and wrongly.`,
    });
  }

  return {
    ok: failures.length === 0,
    failures,
    coverage,
    filesCovered,
    sourceFiles: input.source.total,
    symbols: input.store.symbols,
    relationalEdges: input.store.relationalEdges,
    edgesByKind: input.store.edgesByKind,
  };
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
  const lines = [
    `metacoding: INDEX FAILED — the run produced an unusable graph for '${repo}'.`,
    `  target: ${target}`,
    ...r.failures.map((f) => `  [${f.code}] ${f.message}`),
    `  measured in the store: ${r.symbols} symbols, ${r.relationalEdges} relational edges` +
      ` (CALLS ${r.edgesByKind["CALLS"] ?? 0} / REFERENCES ${r.edgesByKind["REFERENCES"] ?? 0}` +
      ` / IMPLEMENTS ${r.edgesByKind["IMPLEMENTS"] ?? 0}); ` +
      `${r.filesCovered}/${r.sourceFiles} source files covered.`,
    `  Exit code is non-zero BY DESIGN (bead MetaCoding-0sd): a run that reports`,
    `  success here is indistinguishable from a real index to everything downstream.`,
    `  If an empty or partial graph is genuinely what you want, re-run with`,
    `  --allow-empty-index (and/or --min-coverage <0..1>) to record that choice.`,
  ];
  return lines.join("\n");
}
