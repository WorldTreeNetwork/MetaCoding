#!/usr/bin/env bun
// CLI entry point. Not the bin shim — see src/cli/bin.ts. Invoking this
// file directly works in dev (where a local node_modules has the native
// binary already linked) but bypasses the global-install fixup.
//
//   metacoding index <path> [--data-dir <dir>] [--branch <name>]
//   metacoding serve [--data-dir <dir>]
//   metacoding query <cypher> [--data-dir <dir>]

import { cpSync, existsSync, mkdirSync, readdirSync, realpathSync, statSync } from "node:fs";
import { homedir } from "node:os";
import { basename, join, resolve } from "node:path";

import { Store } from "../store";
import { indexDirectory, watch } from "../extractor";
import { serveMcp } from "../mcp/server";
import { runScip, loadScip, resolveScipBin, type ScipLanguage } from "../scip";
import { currentGitBranch } from "./branch";
import { resolveDataDir } from "./data-dir";
import { runExport } from "./export";
import { runDoctor } from "./doctor";

/**
 * Run `git rev-parse HEAD` against `repoPath`.
 * Returns the 40-char SHA on success, or null if the directory is not a git
 * repo, has no commits yet, or git is unavailable. Never throws.
 */
async function getRepoCommitSha(repoPath: string): Promise<string | null> {
  try {
    const result = await Bun.$`git -C ${repoPath} rev-parse HEAD`.quiet();
    return result.stdout.toString().trim() || null;
  } catch {
    return null;
  }
}

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
  console.error(`metacoding 0.1.4 — local-first code-graph DB

Usage:
  metacoding index <path>      [--data-dir <dir>] [--repo <name>] [--branch <name>] [--scip] [--per-commit-identity]
  metacoding index-all <parent>[--data-dir <dir>] [--branch <name>] [--scip] [--per-commit-identity]
  metacoding watch <path>      [--data-dir <dir>] [--repo <name>] [--branch <name>] [--per-commit-identity]
  metacoding serve             [--data-dir <dir>] [--workspace <path>]
  metacoding query <cypher>    [--data-dir <dir>]
  metacoding export <out-dir>  [--data-dir <dir>]
  metacoding doctor
  metacoding install-skill     [--dir <skills-root>]

Flags:
  --scip [true|false]
                Force SCIP indexers on or off. Default: auto-detect. SCIP
                delivers CALLS / REFERENCES / IMPLEMENTS edges (required for
                CTKR Phase 2+ categorical analysis); the tree-sitter lane
                alone cannot populate them. The indexers ship bundled with
                metacoding, so a normal install already has them. To override
                with your own (e.g. on PATH for other tools):
                  bun add -g @sourcegraph/scip-typescript @sourcegraph/scip-python
  --repo        repo identifier tagged onto every Symbol/edge/token
                (defaults to the basename of the indexed path).
  --workspace   workspace root the LSP attaches to (defaults to cwd).
  --per-commit-identity
                fold repo_commit_sha into Symbol.id so multiple commits
                coexist in one DB (default off; overwrite semantics).
                External SCIP refs are never sha-scoped.

Defaults:
  --data-dir    ./.metacoding if it exists (legacy), else
                $XDG_DATA_HOME/metacoding/<repo-id>/ (default
                ~/.local/share/metacoding/<repo-id>/). repo-id is
                derived from remote.origin.url or the repo's
                git-common-dir so worktrees share one store.
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
  const dataDir = await resolveDataDir(targetAbs, args.flags["data-dir"]);
  const branch = args.flags["branch"] ?? currentGitBranch(targetAbs);
  const repo = args.flags["repo"] ?? basename(targetAbs);
  const wantScip = resolveScipWanted(args.flags["scip"]);
  const perCommitIdentity = args.flags["per-commit-identity"] === "true";
  const repo_commit_sha = await getRepoCommitSha(targetAbs);
  const indexed_at = new Date().toISOString();

  const store = await Store.open(dataDir);
  try {
    const r = await indexOneRepo(store, targetAbs, {
      repo, branch, wantScip, repo_commit_sha, indexed_at, perCommitIdentity,
    });
    console.log(JSON.stringify({ dataDir, repo, branch, ...r }, null, 2));
  } finally {
    await store.close();
  }
}

async function cmdIndexAll(args: ParsedArgs): Promise<void> {
  const parent = args.positional[0];
  if (!parent) usage();
  const parentAbs = resolve(parent);
  const dataDir = await resolveDataDir(parentAbs, args.flags["data-dir"]);
  const branch = args.flags["branch"] ?? "main";
  const wantScip = resolveScipWanted(args.flags["scip"]);
  const perCommitIdentity = args.flags["per-commit-identity"] === "true";

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
        const repo_commit_sha = await getRepoCommitSha(subdir);
        const indexed_at = new Date().toISOString();
        const r = await indexOneRepo(store, subdir, {
          repo,
          branch: subBranch,
          wantScip,
          repo_commit_sha,
          indexed_at,
          perCommitIdentity,
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
  repo_commit_sha?: string | null;
  indexed_at?: string | null;
  /** When true, fold repo_commit_sha into Symbol.id so multiple commits
   *  coexist in one DB. bead MetaCoding-izn. */
  perCommitIdentity?: boolean;
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
    repo_commit_sha: opts.repo_commit_sha,
    indexed_at: opts.indexed_at,
    perCommitIdentity: opts.perCommitIdentity,
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
          repo_commit_sha: opts.repo_commit_sha,
          indexed_at: opts.indexed_at,
          perCommitIdentity: opts.perCommitIdentity,
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

function haveScipBinary(name: string): boolean {
  // Single source of truth shared with runScip: local repo dep, then
  // metacoding's bundled @sourcegraph/scip-* copy, then PATH. Using the
  // same resolver means --scip detection can't claim "missing" for a
  // binary runScip would actually have found (e.g. the bundled one in a
  // global `bun add -g @identikey/metacoding` install).
  return resolveScipBin(name) !== null;
}

function haveScipBinaries(): { typescript: boolean; python: boolean; any: boolean } {
  const ts = haveScipBinary("scip-typescript");
  const py = haveScipBinary("scip-python");
  return { typescript: ts, python: py, any: ts || py };
}

function resolveScipWanted(flag: string | undefined): boolean {
  const have = haveScipBinaries();
  if (flag === "false") return false;
  if (flag === "true") {
    if (!have.any) {
      console.error(
        "metacoding: --scip requested but neither scip-typescript nor " +
          "scip-python could be resolved (bundled copy, local dep, or PATH).\n" +
          "  They normally ship with metacoding; if missing, install via:\n" +
          "    bun add -g @sourcegraph/scip-typescript @sourcegraph/scip-python",
      );
      process.exit(1);
    }
    return true;
  }
  if (have.any) return true;
  console.warn(
    "metacoding: SCIP indexers not detected — running tree-sitter only.\n" +
      "  They normally ship bundled with metacoding; if missing, for full\n" +
      "  CALLS/REFERENCES/IMPLEMENTS edges (needed for CTKR Phase 2+) install:\n" +
      "    bun add -g @sourcegraph/scip-typescript @sourcegraph/scip-python\n" +
      "  Pass --scip false to suppress this warning.",
  );
  return false;
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
  const dataDir = await resolveDataDir(process.cwd(), args.flags["data-dir"]);

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
  const dataDir = await resolveDataDir(root, args.flags["data-dir"]);
  const branch = args.flags["branch"] ?? currentGitBranch(root);
  const repo = args.flags["repo"] ?? basename(root);
  // Compute sha once at watch-start. Rows written during a watch session
  // reflect the commit that was HEAD when watching began (acceptable for v0).
  const repo_commit_sha = await getRepoCommitSha(root);
  const indexed_at = new Date().toISOString();
  const perCommitIdentity = args.flags["per-commit-identity"] === "true";

  const store = await Store.open(dataDir);
  const handle = await watch(store, root, {
    branch,
    repo,
    repo_commit_sha,
    indexed_at,
    perCommitIdentity,
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
  const workspace = resolve(args.flags["workspace"] ?? ".");
  const dataDir = await resolveDataDir(workspace, args.flags["data-dir"]);
  await serveMcp({ dataDir, workspace });
}

async function cmdExport(args: ParsedArgs): Promise<void> {
  const outDir = args.positional[0];
  if (!outDir) usage();
  const dataDir = await resolveDataDir(process.cwd(), args.flags["data-dir"]);
  const r = await runExport({ dataDir, outDir });
  console.log(JSON.stringify(r, null, 2));
}

async function cmdInstallSkill(args: ParsedArgs): Promise<void> {
  // The /metacoding skill ships inside the package at
  // .claude/skills/metacoding/. import.meta.dir is .../src/cli, so the
  // package root is two levels up.
  const src = resolve(import.meta.dir, "../../.claude/skills/metacoding");
  if (!existsSync(join(src, "SKILL.md"))) {
    console.error(`metacoding: skill source not found at ${src}`);
    process.exit(1);
  }
  // Default target is the Claude Code personal skills dir; --dir lets you
  // target any harness's skills root (e.g. a Hermes category dir).
  const baseDir = args.flags["dir"] ?? join(homedir(), ".claude", "skills");
  const dest = join(baseDir, "metacoding");
  // If dest already resolves to src (e.g. a dev symlink into the repo), a
  // recursive copy onto itself would throw — treat it as already installed.
  if (existsSync(dest) && realpathSync(dest) === realpathSync(src)) {
    console.log(`metacoding: /metacoding skill already present at ${dest}`);
    return;
  }
  mkdirSync(baseDir, { recursive: true });
  // Copy (not symlink): when run via `bunx`, src lives in a cache dir that
  // may be pruned. A copy is self-contained; re-run install-skill to update.
  cpSync(src, dest, { recursive: true });
  console.log(`metacoding: installed /metacoding skill -> ${dest}`);
  console.log("Reload skills (restart the agent) to pick it up.");
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  switch (args.cmd) {
    case "doctor":
      return runDoctor(args);
    case "install-skill":
      return cmdInstallSkill(args);
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
