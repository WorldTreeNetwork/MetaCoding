// Directory walker — runs Tree-sitter extractors over every supported file
// in a tree and pumps results into the Store. Incremental: files whose
// content hash matches the previously-stored ast_hash are skipped.
//
// Multi-repo: callers pass `repo` (defaults to the basename of the
// indexed root). Symbol ids include repo so cross-repo names don't clash.
//
// Multi-language dispatch: `.ts` / `.tsx` -> TypeScript extractor;
// `.py` -> Python extractor; `.php` -> PHP extractor.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, isAbsolute, join, relative, resolve } from "node:path";

import type { Store } from "../store";
import type { Edge, Symbol } from "../store/types";
import {
  extractEdgeCandidates,
  SymbolResolver,
  type EdgeCandidate,
} from "./edges";
import { fileContentHash, symbolId } from "./identity";
import { makeParser, type TsParser } from "./parser";
import { extractTypeScript, type ExtractOpts as TsExtractOpts } from "./typescript";
import { extractPython, type ExtractPyOpts } from "./python";
import { extractPhp, type ExtractPhpOpts } from "./php";

type Grammar = "typescript" | "tsx" | "python" | "php";

export interface WalkOpts {
  branch?: string;
  repo?: string;
  excludeDirs?: string[];
  /** git rev-parse HEAD at the moment the index was started; null when not in a git repo. */
  repo_commit_sha?: string | null;
  /** ISO-8601 timestamp (UTC) at the moment the index was started. */
  indexed_at?: string | null;
  /** When true, fold repo_commit_sha into Symbol.id so multiple commits coexist
   *  in one DB. Default false (existing overwrite behaviour). bead MetaCoding-izn. */
  perCommitIdentity?: boolean;
}

export interface WalkStats {
  filesScanned: number;
  filesSkipped: number;
  filesUpdated: number;
  filesDeleted: number;
  symbols: number;
  edges: number;
  tokens: number;
  durationMs: number;
}

const DEFAULT_EXCLUDE = [
  "node_modules",
  ".git",
  "dist",
  "out",
  "build",
  "coverage",
  ".omc",
  ".metacoding",
  "__pycache__",
  ".venv",
  "venv",
  ".pytest_cache",
  ".mypy_cache",
  ".ruff_cache",
  ".tox",
  "site-packages",
];

interface ScannedFile {
  abs: string;
  rel: string;
  grammar: Grammar;
}

interface ParserCache {
  typescript: TsParser;
  tsx: TsParser;
  python: TsParser;
  php: TsParser;
}

let cachedParsers: ParserCache | null = null;
async function getParsers(): Promise<ParserCache> {
  if (cachedParsers) return cachedParsers;
  cachedParsers = {
    typescript: await makeParser("typescript"),
    tsx: await makeParser("tsx"),
    python: await makeParser("python"),
    php: await makeParser("php"),
  };
  return cachedParsers;
}

export async function indexDirectory(
  store: Store,
  rootPath: string,
  opts: WalkOpts = {},
): Promise<WalkStats> {
  const t0 = performance.now();
  const branch = opts.branch ?? "main";
  const repo = opts.repo ?? basename(resolve(rootPath));
  const exclude = new Set([...DEFAULT_EXCLUDE, ...(opts.excludeDirs ?? [])]);

  const files: ScannedFile[] = [];
  walkFs(rootPath, rootPath, exclude, files);

  let symbols = 0;
  let edges = 0;
  let tokens = 0;
  let filesSkipped = 0;
  let filesUpdated = 0;

  // Cross-file edge resolution (MetaCoding-3s5). Collected per-file during the
  // main pass, then resolved against an in-memory index of *all* symbols seen
  // in this directory walk so cross-file `new Foo()` finds Foo's class node.
  const resolver = new SymbolResolver();
  const pendingCandidates: EdgeCandidate[] = [];

  for (const f of files) {
    const r = await indexOne(
      store, f, repo, branch,
      opts.repo_commit_sha, opts.indexed_at, opts.perCommitIdentity,
      resolver, pendingCandidates,
    );
    if (r.skipped) filesSkipped++;
    else {
      filesUpdated++;
      symbols += r.symbols;
      edges += r.edges;
      tokens += r.tokens;
    }
  }

  // Resolve and flush the deferred behavior-edges (WRITES_FIELD, CONSTRUCTS,
  // RETURNS_TYPE). Dangling refs (target name not in the repo) are dropped.
  edges += await flushCandidates(store, pendingCandidates, resolver, repo);

  return {
    filesScanned: files.length,
    filesSkipped,
    filesUpdated,
    filesDeleted: 0,
    symbols,
    edges,
    tokens,
    durationMs: performance.now() - t0,
  };
}

export async function indexFile(
  store: Store,
  rootPath: string,
  filePath: string,
  opts: WalkOpts = {},
): Promise<{ skipped: boolean; symbols: number; edges: number; tokens: number }> {
  const branch = opts.branch ?? "main";
  const repo = opts.repo ?? basename(resolve(rootPath));
  const abs = isAbsolute(filePath) ? filePath : resolve(rootPath, filePath);
  const grammar = detectGrammar(abs);
  if (!grammar) return { skipped: true, symbols: 0, edges: 0, tokens: 0 };
  const rel = relative(rootPath, abs);
  // For single-file indexing (watch mode), we resolve edge candidates against
  // a resolver hydrated with this file's own symbols PLUS a best-effort lookup
  // against symbols already in the store for the same repo. Cross-file targets
  // from other-file writes/constructs are best resolved in the directory pass.
  //
  // Perf (MetaCoding-zq2): rather than materialize the ENTIRE per-repo symbol
  // table on every single-file save, we run the extract pass FIRST to collect
  // this file's edge candidates, then hydrate the resolver only for the
  // `short_name`s those candidates can actually resolve against. A candidate
  // whose target short_name is absent from the store can never resolve, so
  // omitting it from the hydrate changes no edge — it's a pure scoping win.
  const resolver = new SymbolResolver();
  const pending: EdgeCandidate[] = [];
  const r = await indexOne(
    store, { abs, rel, grammar }, repo, branch,
    opts.repo_commit_sha, opts.indexed_at, opts.perCommitIdentity,
    resolver, pending,
  );
  // Hydrate only the short_names the pending candidates reference. Empty set
  // (no behavior edges in this file) skips the store query entirely.
  const neededNames = collectCandidateShortNames(pending);
  if (neededNames.length > 0) {
    await hydrateResolverFromStore(store, resolver, repo, branch, neededNames);
  }
  const flushed = await flushCandidates(store, pending, resolver, repo);
  return { ...r, edges: r.edges + flushed };
}

export async function removeFile(
  store: Store,
  rootPath: string,
  filePath: string,
  opts: WalkOpts = {},
): Promise<void> {
  const branch = opts.branch ?? "main";
  const repo = opts.repo ?? basename(resolve(rootPath));
  const abs = isAbsolute(filePath) ? filePath : resolve(rootPath, filePath);
  const rel = relative(rootPath, abs);
  await store.deleteFileData(repo, rel, branch);
}

async function indexOne(
  store: Store,
  f: ScannedFile,
  repo: string,
  branch: string,
  repo_commit_sha?: string | null,
  indexed_at?: string | null,
  perCommitIdentity?: boolean,
  resolver?: SymbolResolver,
  pendingCandidates?: EdgeCandidate[],
): Promise<{ skipped: boolean; symbols: number; edges: number; tokens: number }> {
  const source = readFileSync(f.abs, "utf-8");
  const newHash = fileContentHash(source);

  // In per-commit-identity mode every commit produces its own row family
  // (Symbol.id is sha-scoped), so the (repo, file, branch) cache key is
  // ambiguous — skip the incremental cache and the cross-commit wipe.
  if (!perCommitIdentity) {
    const oldHash = await store.fileHash(repo, f.rel, branch);
    if (oldHash === newHash) {
      return { skipped: true, symbols: 0, edges: 0, tokens: 0 };
    }
    if (oldHash) {
      await store.deleteFileData(repo, f.rel, branch);
    }
  }

  const parsers = await getParsers();
  const tree = parsers[f.grammar].parse(source);
  if (!tree) return { skipped: true, symbols: 0, edges: 0, tokens: 0 };

  let result;
  if (f.grammar === "python") {
    const eo: ExtractPyOpts = {
      filePath: f.rel, branch, repo, repo_commit_sha, indexed_at, perCommitIdentity,
    };
    result = extractPython(tree, eo);
  } else if (f.grammar === "php") {
    const eo: ExtractPhpOpts = {
      filePath: f.rel, branch, repo, repo_commit_sha, indexed_at, perCommitIdentity,
    };
    result = extractPhp(tree, eo);
  } else {
    const eo: TsExtractOpts = {
      filePath: f.rel, grammar: f.grammar, branch, repo, repo_commit_sha, indexed_at, perCommitIdentity,
    };
    result = extractTypeScript(tree, eo);
  }

  // Stamp the file Symbol's ast_hash with the content hash so the next
  // pass can skip when content is unchanged.
  for (const sym of result.symbols) {
    if (sym.kind === "file" && sym.file === f.rel) sym.ast_hash = newHash;
  }

  for (const sym of result.symbols) await store.upsertSymbol(sym);
  for (const edge of result.edges) await store.addEdge(edge);
  store.writeTokens(result.tokens);

  // Behavior-edge pass (MetaCoding-3s5). Feed every extracted symbol into the
  // resolver, then collect WRITES_FIELD / CONSTRUCTS / RETURNS_TYPE candidates.
  // Targets are resolved later (end of directory walk) when all repo symbols
  // are in the index — supports cross-file `new Foo()` etc.
  //
  if (resolver && pendingCandidates) {
    for (const sym of result.symbols) resolver.add(sym);
    const edgeLang = f.grammar === "python" ? "py" : f.grammar === "php" ? "php" : "ts";
    const er = extractEdgeCandidates(tree, {
      language: edgeLang,
      filePath: f.rel,
      symbols: result.symbols,
    });
    for (const c of er.candidates) pendingCandidates.push(c);
  }

  tree.delete();
  return {
    skipped: false,
    symbols: result.symbols.length,
    edges: result.edges.length,
    tokens: result.tokens.length,
  };
}

/**
 * Resolve every pending edge candidate against the symbol index, dedupe by
 * (kind, src, dst), and add to the store. Returns the count of edges flushed.
 *
 * Dropped candidates (target not in repo) are counted in the returned summary.
 */
async function flushCandidates(
  store: Store,
  candidates: EdgeCandidate[],
  resolver: SymbolResolver,
  repo: string,
): Promise<number> {
  if (candidates.length === 0) return 0;
  const dedupe = new Set<string>();
  const boundaryUpserted = new Set<string>();
  let flushed = 0;
  for (const c of candidates) {
    let dst = resolver.resolve(c.target, repo);
    if (!dst && c.target.externalFallback) {
      // No in-repo definition — keep the edge by pointing at a name-keyed
      // boundary node (e.g. Drupal's ContentEntityBase). All references to the
      // same name collapse to one node, which is exactly the role-cluster
      // signal we want. Boundary nodes use language "external" so their ids
      // never collide with real symbols. bead MetaCoding-1xd.
      dst = await ensureBoundaryNode(store, repo, c.target, boundaryUpserted);
    }
    if (!dst) continue;
    if (dst === c.src_id) continue;   // self-edges are noise
    const key = `${c.kind}|${c.src_id}|${dst}`;
    if (dedupe.has(key)) continue;
    dedupe.add(key);
    const edge: Edge = { kind: c.kind, src_id: c.src_id, dst_id: dst };
    await store.addEdge(edge);
    flushed++;
  }
  return flushed;
}

/**
 * Ensure a name-keyed boundary Symbol exists for an unresolved external target
 * (e.g. a base class defined outside the repo) and return its id. Idempotent
 * within a flush via `seen`; upsertSymbol is itself a MERGE so repeated calls
 * across flushes are harmless. Boundary nodes use language "external" and carry
 * no file/position — they exist only as shared edge targets. bead MetaCoding-1xd.
 */
async function ensureBoundaryNode(
  store: Store,
  repo: string,
  target: { kinds: string[]; shortName: string },
  seen: Set<string>,
): Promise<string> {
  const qn = `external::${target.shortName}`;
  const id = symbolId("external", repo, qn);
  if (seen.has(id)) return id;
  seen.add(id);
  const sym: Symbol = {
    id,
    kind: (target.kinds[0] as Symbol["kind"]) ?? "class",
    language: "external",
    repo,
    qualified_name: qn,
    short_name: target.shortName,
    file: "",
    line: 0, col: 0, end_line: 0, end_col: 0,
    signature: null,
    visibility: null,
    is_abstract: false,
    is_static: false,
    ast_hash: null,
    branch: "",
    source: "tree_sitter",
    repo_commit_sha: null,
    indexed_at: null,
  };
  await store.upsertSymbol(sym);
  return id;
}

/**
 * Collect the distinct target `short_name`s referenced by a batch of pending
 * edge candidates. Used to scope the watch-mode resolver hydrate (MetaCoding-zq2)
 * so we only pull store symbols that a candidate could actually resolve against.
 */
function collectCandidateShortNames(candidates: EdgeCandidate[]): string[] {
  const names = new Set<string>();
  for (const c of candidates) names.add(c.target.shortName);
  return [...names];
}

/**
 * Populate a SymbolResolver from symbols already in the store for a given
 * (repo, branch). Used by single-file indexing (watch mode) so cross-file
 * targets from already-indexed files can still resolve.
 *
 * `names` scopes the hydrate to symbols whose `short_name` is in the list
 * (MetaCoding-zq2 perf): materializing the full per-repo symbol table on every
 * save is hundreds of ms + tens of MB for large repos, and only symbols whose
 * short_name a pending candidate references can ever resolve anyway. Callers
 * MUST pass a non-empty list — an empty list would match nothing, so skip the
 * call entirely in that case.
 */
async function hydrateResolverFromStore(
  store: Store,
  resolver: SymbolResolver,
  repo: string,
  branch: string,
  names: string[],
): Promise<void> {
  if (names.length === 0) return;
  type Row = { id: string; repo: string; kind: string; short_name: string; qualified_name: string };
  const rows = await store.query<Row>(
    `MATCH (s:Symbol)
     WHERE s.repo = $repo AND s.branch = $branch AND s.short_name IN $names
     RETURN s.id AS id, s.repo AS repo, s.kind AS kind,
            s.short_name AS short_name, s.qualified_name AS qualified_name`,
    { repo, branch, names },
  );
  for (const r of rows) {
    resolver.add({
      id: r.id,
      kind: r.kind as Symbol["kind"],
      language: "ts",
      repo: r.repo,
      qualified_name: r.qualified_name,
      short_name: r.short_name,
      file: "",
      line: 0,
      col: 0,
      end_line: 0,
      end_col: 0,
      signature: null,
      visibility: null,
      is_abstract: false,
      is_static: false,
      ast_hash: null,
      branch,
      source: "tree_sitter",
    });
  }
}

function walkFs(
  root: string,
  dir: string,
  exclude: Set<string>,
  out: ScannedFile[],
): void {
  for (const name of readdirSync(dir)) {
    if (exclude.has(name)) continue;
    const abs = join(dir, name);
    let st;
    try { st = statSync(abs); } catch { continue; }
    if (st.isDirectory()) {
      walkFs(root, abs, exclude, out);
    } else if (st.isFile()) {
      const grammar = detectGrammar(name);
      if (grammar) out.push({ abs, rel: relative(root, abs), grammar });
    }
  }
}

export function detectGrammar(filename: string): Grammar | null {
  if (filename.endsWith(".d.ts")) return null;
  if (filename.endsWith(".tsx")) return "tsx";
  if (filename.endsWith(".ts")) return "typescript";
  if (filename.endsWith(".py")) return "python";
  // PHP, plus the extensionless-`<?php` file types Drupal uses (farmOS and
  // other Drupal codebases put real PHP in .module/.install/.theme/etc.).
  if (
    filename.endsWith(".php") ||
    filename.endsWith(".phtml") ||
    filename.endsWith(".inc") ||
    filename.endsWith(".module") ||
    filename.endsWith(".install") ||
    filename.endsWith(".theme") ||
    filename.endsWith(".profile") ||
    filename.endsWith(".engine")
  ) {
    return "php";
  }
  return null;
}
