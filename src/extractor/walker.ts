// Directory walker — runs Tree-sitter extractors over every supported file
// in a tree and pumps results into the Store. Incremental: files whose
// content hash matches the previously-stored ast_hash are skipped.
//
// Multi-repo: callers pass `repo` (defaults to the basename of the
// indexed root). Symbol ids include repo so cross-repo names don't clash.
//
// Multi-language dispatch: `.ts` / `.tsx` -> TypeScript extractor;
// `.py` -> Python extractor.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { basename, isAbsolute, join, relative, resolve } from "node:path";

import type { Store } from "../store";
import { fileContentHash } from "./identity";
import { makeParser, type TsParser } from "./parser";
import { extractTypeScript, type ExtractOpts as TsExtractOpts } from "./typescript";
import { extractPython, type ExtractPyOpts } from "./python";

type Grammar = "typescript" | "tsx" | "python";

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
}

let cachedParsers: ParserCache | null = null;
async function getParsers(): Promise<ParserCache> {
  if (cachedParsers) return cachedParsers;
  cachedParsers = {
    typescript: await makeParser("typescript"),
    tsx: await makeParser("tsx"),
    python: await makeParser("python"),
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

  for (const f of files) {
    const r = await indexOne(
      store, f, repo, branch,
      opts.repo_commit_sha, opts.indexed_at, opts.perCommitIdentity,
    );
    if (r.skipped) filesSkipped++;
    else {
      filesUpdated++;
      symbols += r.symbols;
      edges += r.edges;
      tokens += r.tokens;
    }
  }

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
  return indexOne(
    store, { abs, rel, grammar }, repo, branch,
    opts.repo_commit_sha, opts.indexed_at, opts.perCommitIdentity,
  );
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

  tree.delete();
  return {
    skipped: false,
    symbols: result.symbols.length,
    edges: result.edges.length,
    tokens: result.tokens.length,
  };
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
  return null;
}
