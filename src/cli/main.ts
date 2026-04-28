// CLI entry point.
//
//   metacoding index <path> [--data-dir <dir>] [--branch <name>]
//   metacoding serve [--data-dir <dir>]
//   metacoding query <cypher> [--data-dir <dir>]

import { resolve } from "node:path";

import { Store } from "../store";
import { indexDirectory, watch } from "../extractor";
import { serveMcp } from "../mcp/server";
import { runScipTypescript, loadScip } from "../scip";
import { currentGitBranch } from "./branch";

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
  metacoding index <path> [--data-dir <dir>] [--branch <name>] [--scip]
  metacoding watch <path> [--data-dir <dir>] [--branch <name>]
  metacoding serve         [--data-dir <dir>] [--workspace <path>]
  metacoding query <cypher> [--data-dir <dir>]

Flags:
  --scip        run scip-typescript after the Tree-sitter pass to layer
                in resolved-symbol edges (CALLS/REFERENCES/IMPLEMENTS).
  --workspace   workspace root the LSP attaches to (defaults to cwd).

Defaults:
  --data-dir    .metacoding
  --branch      auto-detected from .git/HEAD (fallback "main")
  --workspace   .`);
  process.exit(2);
}

async function cmdIndex(args: ParsedArgs): Promise<void> {
  const target = args.positional[0];
  if (!target) usage();
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  const branch = args.flags["branch"] ?? currentGitBranch(resolve(target));
  const runScip = args.flags["scip"] === "true";

  const store = await Store.open(dataDir);
  try {
    const tsStats = await indexDirectory(store, resolve(target), { branch });
    const result: Record<string, unknown> = { dataDir, branch, treeSitter: tsStats };

    if (runScip) {
      const { scipPath, durationMs: scipRunMs } = await runScipTypescript({
        targetRepo: resolve(target),
      });
      const scipStats = await loadScip(store, scipPath, { branch });
      result["scip"] = { ...scipStats, indexerDurationMs: scipRunMs };
    }

    console.log(JSON.stringify(result, null, 2));
  } finally {
    await store.close();
  }
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

  const store = await Store.open(dataDir);
  const handle = await watch(store, root, {
    branch,
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

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  switch (args.cmd) {
    case "index":
      return cmdIndex(args);
    case "query":
      return cmdQuery(args);
    case "watch":
      return cmdWatch(args);
    case "serve":
      return cmdServe(args);
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
