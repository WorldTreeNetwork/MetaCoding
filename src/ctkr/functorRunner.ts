/**
 * Functor-discovery runner (Phase 2b, MetaCoding §6 Task 3).
 *
 * Batch CLI that discovers approximate functors between repo pairs and emits
 * the two Phase-2b artifacts described in docs/design/ct-functor-discovery.md
 * §3:
 *
 *   .metacoding/ctkr/functors.parquet        — one FunctorRow per directed pair
 *   .metacoding/ctkr/functor_edges.parquet   — one FunctorEdgeRow per object↦object
 *
 * then updates `manifest.json` (functors / functor_edges booleans + counts).
 *
 * Data seams (per the Task-1 spike, docs/notes/functor-spike/README.md):
 *   - object hom-profiles come from `hom_profiles.parquet` via `CtkrHandle`
 *     (DEPTH-2 seeds — `ctkr hom-profiles --depth 2`; the depth is read from the
 *     manifest and recorded in each functor's `config`);
 *   - typed edges + symbol kinds come from the `metacoding export` JSONL lane
 *     (`<data_dir>/ctkr/export/{nodes,edges}.jsonl`), the lane the spike proved
 *     sufficient (no new Python export artifact needed).
 *
 * Determinism (§2.2): `functorSearch` is byte-deterministic, and `functor_id`
 * is content-addressed over `(repo_src, repo_dst, config-for-id, mapping
 * digest)` — so re-running the same config over the same corpus reproduces
 * identical `functor_id`s and rows (append-idempotent: matching ids are
 * replaced, new configs append).
 *
 * TS owns Phase 2 (MetaCoding-p4b); the canonical row schema lives in
 * ctkr/ctkr/schema.py (FunctorRow / FunctorEdgeRow) with codegen'd TS mirrors.
 */

import { DuckDBInstance, type DuckDBConnection } from "@duckdb/node-api";
import { join, isAbsolute } from "node:path";
import { rename, unlink, mkdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import { openCtkrArtifacts, type CtkrHandle } from "./artifacts.ts";
import type { ArtifactManifest, FunctorRow, FunctorEdgeRow } from "./types.ts";
import {
  functorSearch,
  DEFAULT_FUNCTOR_CONFIG,
  type FunctorObject,
  type FunctorEdge,
  type FunctorSearchConfig,
  type FunctorSearchResult,
} from "./functorSearch.ts";

/** L1 schema version — mirror of ctkr/ctkr/schema.py SCHEMA_VERSION. */
const SCHEMA_VERSION = 1;

// ---------------------------------------------------------------------------
// Column specs (name → DuckDB type; ORDER is the on-disk column order and must
// match FUNCTORS_COLUMNS / FUNCTOR_EDGES_COLUMNS in ctkr/ctkr/schema.py).
// ---------------------------------------------------------------------------

const FUNCTORS_COLSPEC: [string, string][] = [
  ["functor_id", "VARCHAR"],
  ["repo_src", "VARCHAR"],
  ["repo_dst", "VARCHAR"],
  ["n_objects_src", "INTEGER"],
  ["n_mapped", "INTEGER"],
  ["coverage", "FLOAT"],
  ["fidelity", "FLOAT"],
  ["n_edges_internal", "INTEGER"],
  ["n_edges_preserved", "INTEGER"],
  ["path_fidelity_2", "FLOAT"],
  ["cycle_consistency", "FLOAT"],
  ["ambiguity_mass", "FLOAT"],
  ["config", "VARCHAR"],
  ["generated_at", "VARCHAR"],
  ["schema_version", "INTEGER"],
];

const FUNCTOR_EDGES_COLSPEC: [string, string][] = [
  ["functor_id", "VARCHAR"],
  ["src_symbol_id", "VARCHAR"],
  ["src_repo", "VARCHAR"],
  ["src_qualified_name", "VARCHAR"],
  ["dst_symbol_id", "VARCHAR"],
  ["dst_repo", "VARCHAR"],
  ["dst_qualified_name", "VARCHAR"],
  ["similarity", "FLOAT"],
  ["margin", "FLOAT"],
  ["is_ambiguous", "BOOLEAN"],
  ["pair_fidelity", "FLOAT"],
  ["n_edges_incident", "INTEGER"],
  ["n_edges_preserved", "INTEGER"],
  ["schema_version", "INTEGER"],
];

/** Canonical on-disk column order (mirror of schema.py *_COLUMNS tuples). */
export const FUNCTORS_COLUMN_ORDER: string[] = FUNCTORS_COLSPEC.map(([n]) => n);
export const FUNCTOR_EDGES_COLUMN_ORDER: string[] = FUNCTOR_EDGES_COLSPEC.map(([n]) => n);

// ---------------------------------------------------------------------------
// Deterministic content-addressing
// ---------------------------------------------------------------------------

/** Canonical JSON with recursively sorted object keys (stable across runs). */
export function stableStringify(value: unknown): string {
  return JSON.stringify(sortKeys(value));
}

function sortKeys(v: unknown): unknown {
  if (Array.isArray(v)) return v.map(sortKeys);
  if (v !== null && typeof v === "object") {
    const out: Record<string, unknown> = {};
    for (const k of Object.keys(v as Record<string, unknown>).sort()) {
      out[k] = sortKeys((v as Record<string, unknown>)[k]);
    }
    return out;
  }
  return v;
}

function blake(input: string): string {
  const h = new Bun.CryptoHasher("blake2b256");
  h.update(input);
  return h.digest("hex");
}

/**
 * Content-addressed functor id: blake2b256 over (repo_src, repo_dst, the
 * deterministic config inputs, and a digest of the accepted mapping). The
 * `budget_exhausted` runtime flag is excluded from the id (it is a wall-clock
 * outcome, not a config input; the mapping digest already captures any
 * budget-induced difference in the result).
 */
export function computeFunctorId(
  repoSrc: string,
  repoDst: string,
  configForId: Record<string, unknown>,
  mapping: { srcId: string; dstId: string }[],
): string {
  const digestInput = [...mapping]
    .map((m) => `${m.srcId}>${m.dstId}`)
    .sort()
    .join("\n");
  const mappingDigest = blake(digestInput);
  const idInput = stableStringify([
    repoSrc,
    repoDst,
    configForId,
    mappingDigest,
  ]);
  return "f:" + blake(idInput).slice(0, 32);
}

// ---------------------------------------------------------------------------
// Parquet writing via DuckDB-Node (read_json → COPY)
// ---------------------------------------------------------------------------

/**
 * Write `rows` to `outPath` as Parquet using the given column spec, merging
 * with any pre-existing rows: rows whose `functor_id` appears in the new batch
 * are replaced, all others are preserved (append-idempotent per §3.3). Column
 * order and types are pinned by `colspec`.
 */
async function writeMergedParquet(
  conn: DuckDBConnection,
  outPath: string,
  colspec: [string, string][],
  rows: Record<string, unknown>[],
  scratchDir: string,
): Promise<void> {
  const columnsClause =
    "{" + colspec.map(([n, t]) => `${n}: '${t}'`).join(", ") + "}";
  const ndjsonPath = join(scratchDir, `._functor_write_${blake(outPath).slice(0, 12)}.ndjson`);
  const body = rows.map((r) => JSON.stringify(r)).join("\n") + (rows.length ? "\n" : "");
  await Bun.write(ndjsonPath, body);

  const tmpParquet = outPath + ".tmp";
  const newScan = `read_json('${ndjsonPath}', format='newline_delimited', columns=${columnsClause})`;

  let selectExpr: string;
  if (existsSync(outPath)) {
    // Keep existing rows whose functor_id is NOT being rewritten, then append
    // the new batch. UNION ALL BY NAME aligns columns by name defensively.
    selectExpr =
      `SELECT * FROM ${newScan} ` +
      `UNION ALL BY NAME ` +
      `SELECT * FROM read_parquet('${outPath}') ` +
      `WHERE functor_id NOT IN (SELECT functor_id FROM ${newScan})`;
  } else {
    selectExpr = `SELECT * FROM ${newScan}`;
  }

  await conn.run(
    `COPY (${selectExpr}) TO '${tmpParquet}' (FORMAT PARQUET)`,
  );
  await rename(tmpParquet, outPath);
  await unlink(ndjsonPath).catch(() => {});
}

// ---------------------------------------------------------------------------
// Graph-export JSONL loading (nodes + edges)
// ---------------------------------------------------------------------------

interface NodeMeta {
  repo: string;
  kind: string;
  qualified_name: string;
}

async function* iterJsonl(path: string): AsyncGenerator<Record<string, unknown>> {
  const stream = Bun.file(path).stream();
  const decoder = new TextDecoder();
  let buf = "";
  for await (const chunk of stream) {
    buf += decoder.decode(chunk, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) yield JSON.parse(line);
    }
  }
  const tail = buf.trim();
  if (tail) yield JSON.parse(tail);
}

/** Resolve the export dir the way ctkr.graph_loader.resolve_paths does. */
export function resolveExportDir(dataDir: string): string {
  const primary = join(dataDir, "ctkr", "export");
  if (existsSync(join(primary, "nodes.jsonl")) && existsSync(join(primary, "edges.jsonl"))) {
    return primary;
  }
  if (existsSync(join(dataDir, "nodes.jsonl")) && existsSync(join(dataDir, "edges.jsonl"))) {
    return dataDir;
  }
  throw new Error(
    `functorRunner: could not find nodes.jsonl + edges.jsonl under ${primary} or ${dataDir}. ` +
      `Run \`metacoding export <out-dir> --data-dir ${dataDir}\` first.`,
  );
}

// ---------------------------------------------------------------------------
// Per-repo input assembly
// ---------------------------------------------------------------------------

interface RepoInput {
  objects: FunctorObject[];
  edges: FunctorEdge[];
  /** symbol_id → { repo, qualified_name } for denormalized edge rows. */
  meta: Map<string, { repo: string; qualified_name: string }>;
}

/**
 * Build the per-repo search inputs for the given repos: objects (hom-profile
 * rows joined to their symbol kind from nodes.jsonl) and internal typed edges
 * (edges.jsonl restricted to edges whose both endpoints are objects).
 */
async function buildRepoInputs(
  handle: CtkrHandle,
  exportDir: string,
  repos: Set<string>,
): Promise<Map<string, RepoInput>> {
  // 1. node kinds/repos for the target repos.
  const nodeMeta = new Map<string, NodeMeta>();
  for await (const rec of iterJsonl(join(exportDir, "nodes.jsonl"))) {
    const repo = rec["repo"] as string | undefined;
    if (repo === undefined || !repos.has(repo)) continue;
    nodeMeta.set(rec["id"] as string, {
      repo,
      kind: (rec["kind"] as string) ?? "unknown",
      qualified_name: (rec["qualified_name"] as string) ?? "",
    });
  }

  // 2. objects per repo from hom_profiles (the O(C_R) definition).
  const out = new Map<string, RepoInput>();
  for (const repo of repos) {
    const profiles = await handle.homProfiles({ repo });
    const objects: FunctorObject[] = [];
    const meta = new Map<string, { repo: string; qualified_name: string }>();
    for (const p of profiles) {
      const nm = nodeMeta.get(p.symbol_id);
      objects.push({
        id: p.symbol_id,
        kind: nm?.kind ?? "unknown",
        profileVec: p.profile_vec,
      });
      meta.set(p.symbol_id, {
        repo: p.repo,
        qualified_name: p.qualified_name,
      });
    }
    out.set(repo, { objects, edges: [], meta });
  }

  // 3. edges — one pass, dispatched to the owning repo (both endpoints must be
  //    objects of the same repo; cross-repo edges are not category morphisms).
  const objIdsByRepo = new Map<string, Set<string>>();
  for (const [repo, ri] of out) {
    objIdsByRepo.set(repo, new Set(ri.objects.map((o) => o.id)));
  }
  for await (const rec of iterJsonl(join(exportDir, "edges.jsonl"))) {
    const src = rec["src_id"] as string;
    const dst = rec["dst_id"] as string;
    const kind = rec["kind"] as string;
    for (const [repo, ids] of objIdsByRepo) {
      if (ids.has(src) && ids.has(dst)) {
        out.get(repo)!.edges.push({ src, dst, kind });
        break;
      }
    }
  }

  return out;
}

// ---------------------------------------------------------------------------
// Config assembly
// ---------------------------------------------------------------------------

/**
 * The stored `config` blob: the search knobs (spike-pinned defaults) plus the
 * runtime metadata the design (§3.1) records — extraction strategy, kind
 * weights, whether Sinkhorn actually fired, whether the budget was exhausted,
 * the hom-profile generation timestamp (staleness), and the seed profile depth.
 */
function buildConfigBlob(
  cfg: FunctorSearchConfig,
  res: FunctorSearchResult,
  homProfilesGeneratedAt: string,
  profileDepth: number,
  restriction: FunctorRestriction,
): Record<string, unknown> {
  return {
    k_seed: cfg.kSeed,
    k_wide: cfg.kWide,
    delta_flat: cfg.deltaFlat,
    delta_rel: cfg.deltaRel,
    tau_seed: cfg.tauSeed,
    cap: cfg.cap,
    alpha: cfg.alpha,
    rounds: cfg.rounds,
    beta: cfg.beta,
    epsilon_prune: cfg.epsPrune,
    f_min: cfg.fMin,
    delta_amb: cfg.deltaAmb,
    // Honest-acceptance gate (MetaCoding-265). Folded into the config blob (and
    // therefore into the content-addressed functor_id, since config-for-id keeps
    // it) so a gated run is addressable distinctly from an ungated one.
    commit_min_margin: cfg.commitMinMargin,
    kind_weights: res.kindWeights,
    normalize: cfg.normalize,
    normalization_applied: res.normalizationApplied,
    extraction: "greedy",
    // MetaCoding-4ty provenance — folded into the functor id (via config-for-id)
    // so scoped / endofunctor runs are addressable distinctly from whole-repo ones.
    exclude_identity: cfg.excludeIdentity,
    src_members_digest: restriction.srcDigest,
    dst_members_digest: restriction.dstDigest,
    budget_exhausted: res.budgetExhausted,
    hom_profiles_generated_at: homProfilesGeneratedAt,
    profile_depth: profileDepth,
  };
}

/** Member-restriction provenance for one directed search. */
interface FunctorRestriction {
  srcMembers: ReadonlySet<string> | null;
  dstMembers: ReadonlySet<string> | null;
  /** blake2b digest of the sorted src member ids, or "" when unrestricted. */
  srcDigest: string;
  /** blake2b digest of the sorted dst member ids, or "" when unrestricted. */
  dstDigest: string;
}

/** Deterministic digest of a member set (sorted ids); "" when unrestricted. */
function memberDigest(members: ReadonlySet<string> | null): string {
  if (members === null) return "";
  return blake([...members].sort().join("\n"));
}

/** Resolve a repo's optional member restriction into a set + its digest. */
function resolveRestriction(
  srcMembers: ReadonlySet<string> | null,
  dstMembers: ReadonlySet<string> | null,
): FunctorRestriction {
  return {
    srcMembers,
    dstMembers,
    srcDigest: memberDigest(srcMembers),
    dstDigest: memberDigest(dstMembers),
  };
}

// ---------------------------------------------------------------------------
// Cycle consistency (§1 / §5.6) — G(F(s)) === s over the two stored directions
// ---------------------------------------------------------------------------

function cycleConsistency(
  fMapping: FunctorSearchResult["mapping"],
  gMapping: FunctorSearchResult["mapping"] | null,
): number {
  if (gMapping === null) return -1;
  const g = new Map<string, string>();
  for (const m of gMapping) g.set(m.srcId, m.dstId);
  if (fMapping.length === 0) return -1;
  let ok = 0;
  for (const m of fMapping) {
    if (g.get(m.dstId) === m.srcId) ok++;
  }
  return ok / fMapping.length;
}

// ---------------------------------------------------------------------------
// Row assembly
// ---------------------------------------------------------------------------

function buildRows(
  repoSrc: string,
  repoDst: string,
  res: FunctorSearchResult,
  cycle: number,
  configBlob: Record<string, unknown>,
  srcMeta: Map<string, { repo: string; qualified_name: string }>,
  dstMeta: Map<string, { repo: string; qualified_name: string }>,
  generatedAt: string,
): { functor: FunctorRow; edges: FunctorEdgeRow[]; functorId: string } {
  // config-for-id excludes the wall-clock-dependent budget flag and the
  // hom-profile staleness stamp (both are metadata, not search determinants —
  // the mapping digest already captures any real difference in the result).
  const configForId = { ...configBlob };
  delete configForId["budget_exhausted"];
  delete configForId["hom_profiles_generated_at"];
  const functorId = computeFunctorId(
    repoSrc,
    repoDst,
    configForId,
    res.mapping.map((m) => ({ srcId: m.srcId, dstId: m.dstId })),
  );

  const functor: FunctorRow = {
    functor_id: functorId,
    repo_src: repoSrc,
    repo_dst: repoDst,
    n_objects_src: res.nObjectsSrc,
    n_mapped: res.nMapped,
    coverage: res.coverage,
    fidelity: res.fidelity,
    n_edges_internal: res.nEdgesInternal,
    n_edges_preserved: res.nEdgesPreserved,
    path_fidelity_2: -1, // not computed by v1 search (§3.1); sentinel
    cycle_consistency: cycle,
    ambiguity_mass: res.ambiguityMass, // MetaCoding-265: coin-flip-tie fraction
    config: stableStringify(configBlob),
    generated_at: generatedAt,
    schema_version: SCHEMA_VERSION,
  };

  const edges: FunctorEdgeRow[] = res.mapping.map((m) => ({
    functor_id: functorId,
    src_symbol_id: m.srcId,
    src_repo: srcMeta.get(m.srcId)?.repo ?? repoSrc,
    src_qualified_name: srcMeta.get(m.srcId)?.qualified_name ?? "",
    dst_symbol_id: m.dstId,
    dst_repo: dstMeta.get(m.dstId)?.repo ?? repoDst,
    dst_qualified_name: dstMeta.get(m.dstId)?.qualified_name ?? "",
    similarity: m.similarity,
    margin: m.margin,
    is_ambiguous: m.isAmbiguous, // MetaCoding-265: near-tie coin-flip flag
    // null (isolated pair, no evidence) → -1 sentinel on disk (§1.3).
    pair_fidelity: m.pairFidelity === null ? -1 : m.pairFidelity,
    n_edges_incident: m.nEdgesIncident,
    n_edges_preserved: m.nEdgesPreserved,
    schema_version: SCHEMA_VERSION,
  }));

  return { functor, edges, functorId };
}

// ---------------------------------------------------------------------------
// Manifest update
// ---------------------------------------------------------------------------

async function updateManifest(
  conn: DuckDBConnection,
  ctkrDir: string,
): Promise<{ nFunctors: number; nFunctorEdges: number }> {
  const manifestPath = join(ctkrDir, "manifest.json");
  const functorsPath = join(ctkrDir, "functors.parquet");
  const edgesPath = join(ctkrDir, "functor_edges.parquet");

  const countRows = async (p: string): Promise<number> => {
    if (!existsSync(p)) return 0;
    const r = await conn.runAndReadAll(
      `SELECT count(*) AS n FROM read_parquet('${p}')`,
    );
    const v = r.getRows()[0]![0];
    return typeof v === "bigint" ? Number(v) : (v as number);
  };

  const nFunctors = await countRows(functorsPath);
  const nFunctorEdges = await countRows(edgesPath);

  let manifest: Partial<ArtifactManifest> & Record<string, unknown> = {};
  if (existsSync(manifestPath)) {
    manifest = JSON.parse(await Bun.file(manifestPath).text());
  } else {
    manifest = {
      schema_version: SCHEMA_VERSION,
      metacoding_data_dir: ctkrDir,
    };
  }
  manifest["functors"] = nFunctors > 0;
  manifest["functor_edges"] = nFunctorEdges > 0;
  manifest["n_functors"] = nFunctors;
  manifest["n_functor_edges"] = nFunctorEdges;
  // Do NOT clobber an existing `generated_at`: it is the shared per-artifact
  // generation stamp other writers set (and the runner reads back as the
  // hom-profile staleness stamp). Only set it when creating a fresh manifest.
  if (manifest["generated_at"] === undefined) {
    manifest["generated_at"] = new Date().toISOString();
  }

  await Bun.write(manifestPath, JSON.stringify(manifest, null, 2) + "\n");
  return { nFunctors, nFunctorEdges };
}

// ---------------------------------------------------------------------------
// Orchestration
// ---------------------------------------------------------------------------

export type Direction = "a_to_b" | "b_to_a" | "both";

export interface RunFunctorDiscoveryOptions {
  /** Absolute path to the `.metacoding/` directory. */
  dataDir: string;
  /**
   * Repo pairs `[repoA, repoB]`. A self-pair `[R, R]` runs SINGLE-REPO
   * ENDOFUNCTOR discovery `F : R → R` (MetaCoding-4ty): unless overridden by
   * `excludeIdentity`, the trivial diagonal is dropped so internal isomorphic
   * subsystems surface instead of the identity.
   */
  pairs: [string, string][];
  /** Which directions to store per pair. Default `"both"`. */
  direction?: Direction;
  /** Search config overrides on top of the spike-pinned defaults. */
  config?: Partial<FunctorSearchConfig>;
  /**
   * MEMBER-SET RESTRICTION (MetaCoding-4ty, §5.6). Per-repo object-set filter:
   * `repo → allowed symbol_ids`. When a repo appears on either side of a pair
   * and has an entry here, its domain/codomain is scoped to that set (a
   * subsystem). Absent = the whole repo. The restriction is folded into the
   * functor's content-addressed `config` (member digest) so a scoped run gets a
   * distinct `functor_id` from the whole-repo run.
   */
  members?: Record<string, string[]>;
  /**
   * Endofunctor diagonal exclusion override. Default (undefined): auto — `true`
   * for self-pairs (`repoA === repoB`), `false` for distinct repos. Set
   * explicitly to force the mode either way.
   */
  excludeIdentity?: boolean;
}

export interface RunFunctorDiscoveryResult {
  functorIds: string[];
  nFunctors: number;
  nFunctorEdges: number;
  /** Per-directed-pair summary (for logging / tests). */
  summaries: {
    repoSrc: string;
    repoDst: string;
    functorId: string;
    coverage: number;
    fidelity: number;
    cycleConsistency: number;
    nMapped: number;
  }[];
}

/**
 * Run functor discovery over the requested repo pairs and write/merge the two
 * artifacts + manifest. Returns the emitted functor ids and counts.
 */
export async function runFunctorDiscovery(
  opts: RunFunctorDiscoveryOptions,
): Promise<RunFunctorDiscoveryResult> {
  if (!isAbsolute(opts.dataDir)) {
    throw new Error(`runFunctorDiscovery: dataDir must be absolute, got ${opts.dataDir}`);
  }
  const dataDir = opts.dataDir;
  const ctkrDir = join(dataDir, "ctkr");
  await mkdir(ctkrDir, { recursive: true });
  const direction: Direction = opts.direction ?? "both";
  const cfg: FunctorSearchConfig = { ...DEFAULT_FUNCTOR_CONFIG, ...opts.config };

  const exportDir = resolveExportDir(dataDir);
  const handle = await openCtkrArtifacts(dataDir);

  // Seed profile depth + hom-profile generation stamp from the manifest.
  const manifest = await handle.manifest();
  const profileDepth = (manifest.profile_depth as number | undefined) ?? 1;
  const homProfilesGeneratedAt =
    (manifest.generated_at as string | undefined) ?? new Date().toISOString();
  if (profileDepth !== 2) {
    process.stderr.write(
      `[functorRunner] WARNING: seed profile_depth=${profileDepth} (expected 2). ` +
        `2-hop seeds are what clear the discovery gate (docs/notes/functor-spike/2hop-findings.md). ` +
        `Re-run \`ctkr hom-profiles --depth 2\` for gate-quality results.\n`,
    );
  }

  // Assemble per-repo inputs for every repo referenced by the pairs.
  const repos = new Set<string>();
  for (const [a, b] of opts.pairs) {
    repos.add(a);
    repos.add(b);
  }
  const repoInputs = await buildRepoInputs(handle, exportDir, repos);
  for (const repo of repos) {
    const ri = repoInputs.get(repo);
    if (!ri || ri.objects.length === 0) {
      throw new Error(
        `functorRunner: repo "${repo}" has no hom-profile objects — check it is indexed and ` +
          `\`ctkr hom-profiles\` has run (and appears in nodes.jsonl).`,
      );
    }
  }

  // Per-repo member restrictions (MetaCoding-4ty): repo → allowed symbol ids.
  const memberSets = new Map<string, ReadonlySet<string>>();
  if (opts.members) {
    for (const [repo, ids] of Object.entries(opts.members)) {
      memberSets.set(repo, new Set(ids));
    }
  }

  const generatedAt = new Date().toISOString();
  const functorRows: FunctorRow[] = [];
  const edgeRows: FunctorEdgeRow[] = [];
  const summaries: RunFunctorDiscoveryResult["summaries"] = [];

  for (const [a, b] of opts.pairs) {
    const ra = repoInputs.get(a)!;
    const rb = repoInputs.get(b)!;

    // Both directions are computed whenever cycle-consistency is wanted; a→b is
    // stored for a_to_b/both, b→a for b_to_a/both.
    const needAB = direction === "a_to_b" || direction === "both";
    const needBA = direction === "b_to_a" || direction === "both";

    // Endofunctor auto-detection: exclude the diagonal for self-pairs unless the
    // caller forces the mode. Distinct repos never self-map.
    const excludeIdentity = opts.excludeIdentity ?? a === b;
    const cfgPair: FunctorSearchConfig = { ...cfg, excludeIdentity };

    const membersA = memberSets.get(a) ?? null;
    const membersB = memberSets.get(b) ?? null;
    const restrAB = resolveRestriction(membersA, membersB);
    const restrBA = resolveRestriction(membersB, membersA);

    const resAB = functorSearch(
      {
        srcObjects: ra.objects, srcEdges: ra.edges,
        dstObjects: rb.objects, dstEdges: rb.edges,
        srcMembers: membersA, dstMembers: membersB,
      },
      cfgPair,
    );
    const resBA = functorSearch(
      {
        srcObjects: rb.objects, srcEdges: rb.edges,
        dstObjects: ra.objects, dstEdges: ra.edges,
        srcMembers: membersB, dstMembers: membersA,
      },
      cfgPair,
    );

    if (needAB) {
      const cyc = direction === "both" ? cycleConsistency(resAB.mapping, resBA.mapping) : -1;
      const blob = buildConfigBlob(cfgPair, resAB, homProfilesGeneratedAt, profileDepth, restrAB);
      const { functor, edges } = buildRows(a, b, resAB, cyc, blob, ra.meta, rb.meta, generatedAt);
      functorRows.push(functor);
      edgeRows.push(...edges);
      summaries.push({
        repoSrc: a, repoDst: b, functorId: functor.functor_id,
        coverage: functor.coverage, fidelity: functor.fidelity,
        cycleConsistency: functor.cycle_consistency, nMapped: functor.n_mapped,
      });
    }
    if (needBA) {
      const cyc = direction === "both" ? cycleConsistency(resBA.mapping, resAB.mapping) : -1;
      const blob = buildConfigBlob(cfgPair, resBA, homProfilesGeneratedAt, profileDepth, restrBA);
      const { functor, edges } = buildRows(b, a, resBA, cyc, blob, rb.meta, ra.meta, generatedAt);
      functorRows.push(functor);
      edgeRows.push(...edges);
      summaries.push({
        repoSrc: b, repoDst: a, functorId: functor.functor_id,
        coverage: functor.coverage, fidelity: functor.fidelity,
        cycleConsistency: functor.cycle_consistency, nMapped: functor.n_mapped,
      });
    }
  }

  await handle.close();

  // Write both artifacts via a dedicated (non-cached) DuckDB instance so the
  // COPY writes don't touch the shared read-side in-memory cache.
  const instance = await DuckDBInstance.create(":memory:");
  const conn = await instance.connect();
  try {
    await writeMergedParquet(
      conn,
      join(ctkrDir, "functors.parquet"),
      FUNCTORS_COLSPEC,
      functorRows as unknown as Record<string, unknown>[],
      ctkrDir,
    );
    await writeMergedParquet(
      conn,
      join(ctkrDir, "functor_edges.parquet"),
      FUNCTOR_EDGES_COLSPEC,
      edgeRows as unknown as Record<string, unknown>[],
      ctkrDir,
    );
    const { nFunctors, nFunctorEdges } = await updateManifest(conn, ctkrDir);
    return {
      functorIds: functorRows.map((f) => f.functor_id),
      nFunctors,
      nFunctorEdges,
      summaries,
    };
  } finally {
    conn.closeSync();
  }
}

// ---------------------------------------------------------------------------
// CLI
// ---------------------------------------------------------------------------

function parseArgs(argv: string[]): RunFunctorDiscoveryOptions {
  let dataDir: string | undefined;
  let pairsArg: string | undefined;
  let direction: Direction = "both";
  for (let i = 0; i < argv.length; i++) {
    const a = argv[i]!;
    if (a === "--data-dir") dataDir = argv[++i];
    else if (a === "--pairs") pairsArg = argv[++i];
    else if (a === "--direction") direction = argv[++i] as Direction;
  }
  if (!dataDir) throw new Error("functorRunner: --data-dir <path> is required");
  if (!pairsArg) throw new Error("functorRunner: --pairs A:B,C:D is required");
  const pairs: [string, string][] = pairsArg.split(",").map((p) => {
    const [a, b] = p.split(":");
    if (!a || !b) throw new Error(`functorRunner: bad pair "${p}" (expected repoA:repoB)`);
    return [a, b];
  });
  return { dataDir, pairs, direction };
}

if (import.meta.main) {
  const opts = parseArgs(Bun.argv.slice(2));
  const res = await runFunctorDiscovery(opts);
  process.stderr.write(
    `[functorRunner] wrote ${res.nFunctors} functor rows, ${res.nFunctorEdges} edge rows\n`,
  );
  for (const s of res.summaries) {
    process.stderr.write(
      `  ${s.repoSrc} → ${s.repoDst}  cov=${s.coverage.toFixed(3)} fid=${s.fidelity.toFixed(3)} ` +
        `cyc=${s.cycleConsistency.toFixed(3)} mapped=${s.nMapped}  ${s.functorId}\n`,
    );
  }
}
