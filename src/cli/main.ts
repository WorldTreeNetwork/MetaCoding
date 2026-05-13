// CLI entry point.
//
//   metacoding index <path> [--data-dir <dir>] [--branch <name>]
//   metacoding serve [--data-dir <dir>]
//   metacoding query <cypher> [--data-dir <dir>]

import { existsSync, readdirSync, statSync } from "node:fs";
import { basename, join, resolve } from "node:path";

import { Store } from "../store";
import { indexDirectory, watch } from "../extractor";
import { serveMcp } from "../mcp/server";
import { runScip, loadScip, type ScipLanguage } from "../scip";
import { currentGitBranch } from "./branch";
import { runExport } from "./export";

const DEFAULT_DATA_DIR = ".metacoding";

interface ParsedArgs {
  cmd: string;
  positional: string[];
  flags: Record<string, string>;
}

function parseArgs(argv: string[]): ParsedArgs {
  const cmd = argv[0] ?? "";
  const rest = argv.slice(1);
  const positional: string[] = [];
  const flags: Record<string, string> = {};
  for (let i = 0; i < rest.length; i++) {
    const tok = rest[i]!;
    if (tok.startsWith("--")) {
      const next = rest[i + 1];
      if (next !== undefined && !next.startsWith("--")) {
        flags[tok.slice(2)] = next;
        i++;
      } else {
        flags[tok.slice(2)] = "true";
      }
    } else {
      positional.push(tok);
    }
  }
  return { cmd, positional, flags };
}

function usage(): never {
  console.error(`metacoding 0.1.0 — local-first code-graph DB

Usage:
  metacoding index <path>      [--data-dir <dir>] [--repo <name>] [--branch <name>] [--scip]
  metacoding index-all <parent>[--data-dir <dir>] [--branch <name>] [--scip]
  metacoding watch <path>      [--data-dir <dir>] [--repo <name>] [--branch <name>]
  metacoding serve             [--data-dir <dir>] [--workspace <path>]
  metacoding query <cypher>    [--data-dir <dir>]
  metacoding export <out-dir>  [--data-dir <dir>]

Flags:
  --scip        run SCIP indexers (TS + Python, whichever is present)
                after the Tree-sitter pass to layer in resolved-symbol
                edges (CALLS / REFERENCES / IMPLEMENTS).
  --repo        repo identifier tagged onto every Symbol/edge/token
                (defaults to the basename of the indexed path).
  --workspace   workspace root the LSP attaches to (defaults to cwd).

Defaults:
  --data-dir    .metacoding
  --repo        basename of the indexed path
  --branch      auto-detected from .git/HEAD (fallback "main")
  --workspace   .

index-all walks every direct subdirectory of <parent> and runs 'index'
for each, tagging --repo with the subdirectory's name.`);
  process.exit(2);
}

async function cmdIndex(args: ParsedArgs): Promise<void> {
  const target = args.positional[0];
  if (!target) usage();
  const targetAbs = resolve(target);
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  const branch = args.flags["branch"] ?? currentGitBranch(targetAbs);
  const repo = args.flags["repo"] ?? basename(targetAbs);
  const wantScip = args.flags["scip"] === "true";

  const store = await Store.open(dataDir);
  try {
    const r = await indexOneRepo(store, targetAbs, { repo, branch, wantScip });
    console.log(JSON.stringify({ dataDir, repo, branch, ...r }, null, 2));
  } finally {
    await store.close();
  }
}

async function cmdIndexAll(args: ParsedArgs): Promise<void> {
  const parent = args.positional[0];
  if (!parent) usage();
  const parentAbs = resolve(parent);
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  const branch = args.flags["branch"] ?? "main";
  const wantScip = args.flags["scip"] === "true";

  if (!existsSync(parentAbs)) {
    console.error(`metacoding: ${parentAbs} does not exist`);
    process.exit(1);
  }

  const subdirs = readdirSync(parentAbs)
    .filter((n) => !n.startsWith(".") && n !== "node_modules")
    .map((n) => join(parentAbs, n))
    .filter((p) => {
      try { return statSync(p).isDirectory(); } catch { return false; }
    });

  const store = await Store.open(dataDir);
  const results: Record<string, unknown>[] = [];
  try {
    for (const subdir of subdirs) {
      const repo = basename(subdir);
      const subBranch = args.flags["branch"] ?? currentGitBranch(subdir) ?? branch;
      const t0 = performance.now();
      try {
        const r = await indexOneRepo(store, subdir, {
          repo,
          branch: subBranch,
          wantScip,
        });
        results.push({
          repo,
          branch: subBranch,
          ok: true,
          durationMs: Math.round(performance.now() - t0),
          ...r,
        });
        console.error(
          `[index-all] ${repo}: ${r.treeSitter.filesUpdated}/${r.treeSitter.filesScanned} files, ` +
          `${r.treeSitter.symbols}+${r.scip?.symbolsUpserted ?? 0} symbols, ` +
          `${Math.round(performance.now() - t0)}ms`,
        );
      } catch (e) {
        results.push({
          repo,
          branch: subBranch,
          ok: false,
          error: (e as Error).message,
        });
        console.error(`[index-all] ${repo}: FAILED — ${(e as Error).message.slice(0, 200)}`);
      }
    }
  } finally {
    await store.close();
  }
  console.log(JSON.stringify({ dataDir, repos: results }, null, 2));
}

interface IndexOneOpts {
  repo: string;
  branch: string;
  wantScip: boolean;
}

interface IndexOneResult {
  treeSitter: Awaited<ReturnType<typeof indexDirectory>>;
  scip?: Record<string, unknown>;
}

async function indexOneRepo(
  store: Store,
  targetAbs: string,
  opts: IndexOneOpts,
): Promise<IndexOneResult> {
  const tsStats = await indexDirectory(store, targetAbs, {
    branch: opts.branch,
    repo: opts.repo,
  });
  const out: IndexOneResult = { treeSitter: tsStats };

  if (opts.wantScip) {
    const scipLangs = detectScipLanguages(targetAbs);
    const accum = { documents: 0, symbolsUpserted: 0, edgesAdded: 0, externalRefsSkipped: 0, indexerDurationMs: 0 };
    for (const lang of scipLangs) {
      try {
        const { scipPath, durationMs } = await runScip({
          language: lang,
          targetRepo: targetAbs,
          output: join(targetAbs, `index.${lang}.scip`),
          projectName: opts.repo,
          projectVersion: opts.branch,
        });
        const stats = await loadScip(store, scipPath, {
          branch: opts.branch,
          repo: opts.repo,
          language: lang === "typescript" ? "ts" : "py",
        });
        accum.documents += stats.documents;
        accum.symbolsUpserted += stats.symbolsUpserted;
        accum.edgesAdded += stats.edgesAdded;
        accum.externalRefsSkipped += stats.externalRefsSkipped;
        accum.indexerDurationMs += durationMs;
      } catch (e) {
        console.error(`scip-${lang} failed: ${(e as Error).message.slice(0, 200)}`);
      }
    }
    out.scip = accum;
  }
  return out;
}

function detectScipLanguages(repoPath: string): ScipLanguage[] {
  const langs: ScipLanguage[] = [];
  if (hasFileExt(repoPath, /\.(ts|tsx|mts|cts)$/, 6) ||
      existsSync(join(repoPath, "tsconfig.json")) ||
      existsSync(join(repoPath, "package.json"))) {
    langs.push("typescript");
  }
  if (hasFileExt(repoPath, /\.py$/, 6) ||
      existsSync(join(repoPath, "pyproject.toml")) ||
      existsSync(join(repoPath, "setup.py"))) {
    langs.push("python");
  }
  return langs;
}

function hasFileExt(dir: string, pattern: RegExp, maxDepth: number): boolean {
  if (maxDepth <= 0) return false;
  try {
    for (const entry of readdirSync(dir)) {
      if (entry.startsWith(".") || entry === "node_modules") continue;
      const p = join(dir, entry);
      let st;
      try { st = statSync(p); } catch { continue; }
      if (st.isFile() && pattern.test(entry)) return true;
      if (st.isDirectory() && hasFileExt(p, pattern, maxDepth - 1)) return true;
    }
  } catch { /* permission/race */ }
  return false;
}

async function cmdQuery(args: ParsedArgs): Promise<void> {
  const cypher = args.positional[0];
  if (!cypher) usage();
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);

  const store = await Store.open(dataDir);
  try {
    const rows = await store.query(cypher);
    console.log(JSON.stringify(rows, null, 2));
  } finally {
    await store.close();
  }
}

async function cmdWatch(args: ParsedArgs): Promise<void> {
  const target = args.positional[0];
  if (!target) usage();
  const root = resolve(target);
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  const branch = args.flags["branch"] ?? currentGitBranch(root);
  const repo = args.flags["repo"] ?? basename(root);

  const store = await Store.open(dataDir);
  const handle = await watch(store, root, {
    branch,
    repo,
    onProcessed: (event, path) => {
      const at = new Date().toISOString().slice(11, 19);
      console.log(`${at} ${event.padEnd(6)} ${path}`);
    },
  });
  console.log(`watching ${root} on branch ${branch}; data dir ${dataDir}`);
  console.log("press Ctrl-C to stop");

  const shutdown = async () => {
    try { await handle.close(); } catch {}
    try { await store.close(); } catch {}
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}

async function cmdServe(args: ParsedArgs): Promise<void> {
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  const workspace = resolve(args.flags["workspace"] ?? ".");
  await serveMcp({ dataDir, workspace });
}

async function cmdExport(args: ParsedArgs): Promise<void> {
  const outDir = args.positional[0];
  if (!outDir) usage();
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  const r = await runExport({ dataDir, outDir });
  console.log(JSON.stringify(r, null, 2));
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  switch (args.cmd) {
    case "index":
      return cmdIndex(args);
    case "index-all":
      return cmdIndexAll(args);
    case "query":
      return cmdQuery(args);
    case "watch":
      return cmdWatch(args);
    case "serve":
      return cmdServe(args);
    case "export":
      return cmdExport(args);
    case "--help":
    case "-h":
    case "help":
    case "":
      usage();
    default:
      console.error(`unknown command: ${args.cmd}`);
      usage();
  }
}

const KEEP_ALIVE = new Set(["serve", "watch"]);

main()
  .then(() => {
    // Long-lived commands (serve, watch) own their own lifecycle.
    if (!KEEP_ALIVE.has(process.argv[2] ?? "")) process.exit(0);
  })
  .catch((err) => {
    console.error("metacoding:", err?.message ?? err);
    process.exit(1);
  });
