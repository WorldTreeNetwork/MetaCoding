// CLI entry point.
//
//   metacoding index <path> [--data-dir <dir>] [--branch <name>]
//   metacoding serve [--data-dir <dir>]
//   metacoding query <cypher> [--data-dir <dir>]

import { resolve } from "node:path";

import { Store } from "../store";
import { indexDirectory } from "../extractor";
import { serveMcp } from "../mcp/server";

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
  metacoding index <path> [--data-dir <dir>] [--branch <name>]
  metacoding serve         [--data-dir <dir>]
  metacoding query <cypher> [--data-dir <dir>]

Defaults:
  --data-dir   .metacoding
  --branch     main`);
  process.exit(2);
}

async function cmdIndex(args: ParsedArgs): Promise<void> {
  const target = args.positional[0];
  if (!target) usage();
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  const branch = args.flags["branch"] ?? "main";

  const store = await Store.open(dataDir);
  try {
    const stats = await indexDirectory(store, resolve(target), { branch });
    console.log(JSON.stringify({ dataDir, branch, ...stats }, null, 2));
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

async function cmdServe(args: ParsedArgs): Promise<void> {
  const dataDir = resolve(args.flags["data-dir"] ?? DEFAULT_DATA_DIR);
  await serveMcp({ dataDir });
}

async function main(): Promise<void> {
  const args = parseArgs(process.argv.slice(2));
  switch (args.cmd) {
    case "index":
      return cmdIndex(args);
    case "query":
      return cmdQuery(args);
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

main()
  .then(() => {
    // index/query exit naturally; serve keeps stdio open until signal.
    if (process.argv[2] !== "serve") process.exit(0);
  })
  .catch((err) => {
    console.error("metacoding:", err?.message ?? err);
    process.exit(1);
  });
