// Directory walker — runs Tree-sitter extractors over every supported file
// in a tree and pumps results into the Store.

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative } from "node:path";

import type { Store } from "../store";
import { makeParser } from "./parser";
import { extractTypeScript, type ExtractOpts } from "./typescript";

export interface WalkOpts {
  branch?: string;
  excludeDirs?: string[];
}

export interface WalkStats {
  filesScanned: number;
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

  const parsers = {
    typescript: await makeParser("typescript"),
    tsx: await makeParser("tsx"),
  };

  let symbols = 0;
  let edges = 0;
  let tokens = 0;

  for (const f of files) {
    const source = readFileSync(f.abs, "utf-8");
    const parser = parsers[f.grammar];
    const tree = parser.parse(source);
    if (!tree) continue;

    const result = extractTypeScript(tree, {
      filePath: f.rel,
      grammar: f.grammar,
      branch,
    });

    for (const sym of result.symbols) await store.upsertSymbol(sym);
    for (const edge of result.edges) await store.addEdge(edge);
    store.writeTokens(result.tokens);

    symbols += result.symbols.length;
    edges += result.edges.length;
    tokens += result.tokens.length;
    tree.delete();
  }

  return {
    filesScanned: files.length,
    symbols,
    edges,
    tokens,
    durationMs: performance.now() - t0,
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

function detectGrammar(filename: string): ExtractOpts["grammar"] | null {
  if (filename.endsWith(".d.ts")) return null;
  if (filename.endsWith(".tsx")) return "tsx";
  if (filename.endsWith(".ts")) return "typescript";
  return null;
}
