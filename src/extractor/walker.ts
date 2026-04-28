// Directory walker — runs Tree-sitter extractors over every supported file
// in a tree and pumps results into the Store. Incremental: files whose
// content hash matches the previously-stored ast_hash are skipped.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { isAbsolute, join, relative, resolve } from "node:path";

import type { Store } from "../store";
import { fileContentHash } from "./identity";
import { makeParser, type TsParser } from "./parser";
import { extractTypeScript, type ExtractOpts } from "./typescript";

export interface WalkOpts {
  branch?: string;
  excludeDirs?: string[];
}

export interface WalkStats {
  filesScanned: number;
  filesSkipped: number;        // unchanged content hash
  filesUpdated: number;        // re-extracted
  filesDeleted: number;        // not used by indexDirectory; populated by watcher
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
  "coverage",
  ".omc",
  ".metacoding",
];

interface ScannedFile {
  abs: string;
  rel: string;
  grammar: ExtractOpts["grammar"];
}

interface ParserCache {
  typescript: TsParser;
  tsx: TsParser;
}

let cachedParsers: ParserCache | null = null;
async function getParsers(): Promise<ParserCache> {
  if (cachedParsers) return cachedParsers;
  cachedParsers = {
    typescript: await makeParser("typescript"),
    tsx: await makeParser("tsx"),
  };
  return cachedParsers;
}

/** Index every supported file under rootPath, skipping unchanged ones. */
export async function indexDirectory(
  store: Store,
  rootPath: string,
  opts: WalkOpts = {},
): Promise<WalkStats> {
  const t0 = performance.now();
  const branch = opts.branch ?? "main";
  const exclude = new Set([...DEFAULT_EXCLUDE, ...(opts.excludeDirs ?? [])]);

  const files: ScannedFile[] = [];
  walkFs(rootPath, rootPath, exclude, files);

  let symbols = 0;
  let edges = 0;
  let tokens = 0;
  let filesSkipped = 0;
  let filesUpdated = 0;

  for (const f of files) {
    const r = await indexOne(store, rootPath, f, branch);
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

/**
 * Re-index a single file. Caller passes the workspace root so file paths
 * land relative to it (matching what indexDirectory writes).
 */
export async function indexFile(
  store: Store,
  rootPath: string,
  filePath: string,
  opts: WalkOpts = {},
): Promise<{ skipped: boolean; symbols: number; edges: number; tokens: number }> {
  const branch = opts.branch ?? "main";
  const abs = isAbsolute(filePath) ? filePath : resolve(rootPath, filePath);
  const grammar = detectGrammar(abs);
  if (!grammar) return { skipped: true, symbols: 0, edges: 0, tokens: 0 };
  const rel = relative(rootPath, abs);
  return indexOne(store, rootPath, { abs, rel, grammar }, branch);
}

/** Drop a file's data from the store (used by the watcher on `unlink`). */
export async function removeFile(
  store: Store,
  rootPath: string,
  filePath: string,
  opts: WalkOpts = {},
): Promise<void> {
  const branch = opts.branch ?? "main";
  const abs = isAbsolute(filePath) ? filePath : resolve(rootPath, filePath);
  const rel = relative(rootPath, abs);
  await store.deleteFileData(rel, branch);
}

async function indexOne(
  store: Store,
  rootPath: string,
  f: ScannedFile,
  branch: string,
): Promise<{ skipped: boolean; symbols: number; edges: number; tokens: number }> {
  const source = readFileSync(f.abs, "utf-8");
  const newHash = fileContentHash(source);

  const oldHash = await store.fileHash(f.rel, branch);
  if (oldHash === newHash) {
    return { skipped: true, symbols: 0, edges: 0, tokens: 0 };
  }
  if (oldHash) {
    await store.deleteFileData(f.rel, branch);
  }

  const parsers = await getParsers();
  const tree = parsers[f.grammar].parse(source);
  if (!tree) return { skipped: true, symbols: 0, edges: 0, tokens: 0 };

  const result = extractTypeScript(tree, {
    filePath: f.rel,
    grammar: f.grammar,
    branch,
  });

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
    const st = statSync(abs);
    if (st.isDirectory()) {
      walkFs(root, abs, exclude, out);
    } else if (st.isFile()) {
      const grammar = detectGrammar(name);
      if (grammar) out.push({ abs, rel: relative(root, abs), grammar });
    }
  }
}

export function detectGrammar(filename: string): ExtractOpts["grammar"] | null {
  if (filename.endsWith(".d.ts")) return null;
  if (filename.endsWith(".tsx")) return "tsx";
  if (filename.endsWith(".ts")) return "typescript";
  return null;
}
