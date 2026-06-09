// Drive a SCIP indexer as a subprocess and return the produced .scip file.
//
// Currently supports:
//   - typescript  (scip-typescript, npm @sourcegraph/scip-typescript)
//   - python      (scip-python,     npm @sourcegraph/scip-python)
//
// Both share the same SCIP protobuf output shape, so the loader doesn't
// care which indexer produced the file.

import { resolve, join, dirname, basename } from "node:path";
import { existsSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { createRequire } from "node:module";

const require_ = createRequire(import.meta.url);

function findPackageBin(pkg: string, bin: string): string | null {
  let dir: string;
  try { dir = dirname(require_.resolve(`${pkg}/package.json`)); } catch { return null; }
  while (dir !== "/" && basename(dir) !== "node_modules") dir = dirname(dir);
  if (basename(dir) !== "node_modules") return null;
  const p = join(dir, ".bin", bin);
  return existsSync(p) ? p : null;
}

const PKG_FOR_BIN: Record<string, string> = {
  "scip-typescript": "@sourcegraph/scip-typescript",
  "scip-python": "@sourcegraph/scip-python",
};

/**
 * Resolve a SCIP indexer binary, in priority order:
 *   1. the target repo's own ./node_modules/.bin (a local dev-dep install),
 *   2. metacoding's bundled copy (the @sourcegraph/scip-* packages are
 *      dependencies, so a global `bun add -g @identikey/metacoding` ships
 *      them — findPackageBin locates them in metacoding's node_modules),
 *   3. anything on PATH.
 * Returns the absolute path, or null if none of the three resolve.
 *
 * This is the single source of truth for "can we run SCIP?" — both runScip
 * (execution) and the CLI's --scip auto-detect import it, so detection can
 * never disagree with what actually runs.
 */
export function resolveScipBin(binary: string): string | null {
  const cwdBin = join(process.cwd(), "node_modules", ".bin", binary);
  if (existsSync(cwdBin)) return cwdBin;
  const pkg = PKG_FOR_BIN[binary];
  const pkgBin = pkg ? findPackageBin(pkg, binary) : null;
  if (pkgBin) return pkgBin;
  return Bun.which(binary);
}

export type ScipLanguage = "typescript" | "python";

export interface RunScipOpts {
  language: ScipLanguage;
  targetRepo: string;        // path to the repo to index
  output?: string;            // path for the .scip file (default: <targetRepo>/index.scip)
  inferTsconfig?: boolean;    // pass --infer-tsconfig if no tsconfig.json (TS only)
  projectName?: string;       // python only: --project-name (defaults to "metacoding-target")
  projectVersion?: string;    // python only: --project-version (defaults to "HEAD")
}

export interface RunScipResult {
  scipPath: string;
  durationMs: number;
}

interface IndexerSpec {
  binary: string;
  args(opts: RunScipOpts, outPath: string): string[];
}

const INDEXERS: Record<ScipLanguage, IndexerSpec> = {
  typescript: {
    binary: "scip-typescript",
    args(opts, outPath) {
      const a = [
        "index",
        "--cwd", resolve(opts.targetRepo),
        "--output", outPath,
        "--no-progress-bar",
      ];
      if (opts.inferTsconfig ?? !existsSync(join(resolve(opts.targetRepo), "tsconfig.json"))) {
        a.push("--infer-tsconfig");
      }
      return a;
    },
  },
  python: {
    // scip-python is a Node binary built on Pyright. `index` indexes all
    // reachable Python under --cwd; no positional path argument.
    //
    // Two non-obvious requirements:
    //   --environment <json>     scip-python otherwise tries to enumerate
    //     installed packages via `pip` for cross-package symbol resolution.
    //     Most modern Python setups (uv, no pip on PATH) make that fail
    //     fatally. We supply an empty env so it skips that step; we lose
    //     cross-package resolution but keep all project-local symbols.
    //   --project-name / --project-version
    //     scip-python's symbol-string builder NPE's when these are unset.
    //     We pass the repo name and a hard-coded HEAD placeholder.
    binary: "scip-python",
    args(opts, outPath) {
      return [
        "index",
        "--project-name", opts.projectName ?? "metacoding-target",
        "--project-version", opts.projectVersion ?? "HEAD",
        "--environment", ensureEmptyEnvJson(),
        "--cwd", resolve(opts.targetRepo),
        "--output", outPath,
        "--quiet",
      ];
    },
  },
};

let cachedEmptyEnvPath: string | null = null;
function ensureEmptyEnvJson(): string {
  if (cachedEmptyEnvPath && existsSync(cachedEmptyEnvPath)) return cachedEmptyEnvPath;
  const path = join(tmpdir(), "metacoding-scip-python-empty-env.json");
  if (!existsSync(path)) writeFileSync(path, "[]\n", "utf-8");
  cachedEmptyEnvPath = path;
  return path;
}

export async function runScip(opts: RunScipOpts): Promise<RunScipResult> {
  const t0 = performance.now();
  const targetRepo = resolve(opts.targetRepo);
  const outPath = resolve(opts.output ?? join(targetRepo, "index.scip"));
  const spec = INDEXERS[opts.language];

  const bin = resolveScipBin(spec.binary) ?? spec.binary;
  const args = spec.args(opts, outPath);

  const proc = Bun.spawn([bin, ...args], { stdout: "pipe", stderr: "pipe" });
  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);

  if (exitCode !== 0) {
    throw new Error(
      `${spec.binary} exited ${exitCode}\nstdout:\n${stdout}\nstderr:\n${stderr}`,
    );
  }
  if (!existsSync(outPath)) {
    throw new Error(`${spec.binary} reported success but ${outPath} not found`);
  }

  return { scipPath: outPath, durationMs: performance.now() - t0 };
}

// Back-compat alias for the original TypeScript-only callers.
export async function runScipTypescript(
  opts: Omit<RunScipOpts, "language">,
): Promise<RunScipResult> {
  return runScip({ ...opts, language: "typescript" });
}
