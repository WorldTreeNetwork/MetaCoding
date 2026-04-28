// Drive scip-typescript as a subprocess to generate a .scip file.
//
// Uses the binary shipped by @sourcegraph/scip-typescript at
// node_modules/.bin/scip-typescript.

import { resolve, join } from "node:path";
import { existsSync } from "node:fs";

export interface RunScipOpts {
  targetRepo: string;        // path to the repo to index
  output?: string;            // path for the .scip file (default: <targetRepo>/index.scip)
  inferTsconfig?: boolean;    // pass --infer-tsconfig if no tsconfig.json
}

export interface RunScipResult {
  scipPath: string;
  durationMs: number;
}

export async function runScipTypescript(opts: RunScipOpts): Promise<RunScipResult> {
  const t0 = performance.now();
  const targetRepo = resolve(opts.targetRepo);
  const outPath = resolve(opts.output ?? join(targetRepo, "index.scip"));

  // Resolve the binary; prefer the local node_modules so users get a
  // deterministic version pinned to their package.json.
  const localBin = join(
    process.cwd(),
    "node_modules",
    ".bin",
    "scip-typescript",
  );
  const bin = existsSync(localBin) ? localBin : "scip-typescript";

  const args = [
    "index",
    "--cwd", targetRepo,
    "--output", outPath,
    "--no-progress-bar",
  ];
  if (opts.inferTsconfig ?? !existsSync(join(targetRepo, "tsconfig.json"))) {
    args.push("--infer-tsconfig");
  }

  const proc = Bun.spawn([bin, ...args], {
    stdout: "pipe",
    stderr: "pipe",
  });

  const [stdout, stderr, exitCode] = await Promise.all([
    new Response(proc.stdout).text(),
    new Response(proc.stderr).text(),
    proc.exited,
  ]);

  if (exitCode !== 0) {
    throw new Error(
      `scip-typescript exited ${exitCode}\nstdout:\n${stdout}\nstderr:\n${stderr}`,
    );
  }
  if (!existsSync(outPath)) {
    throw new Error(`scip-typescript reported success but ${outPath} not found`);
  }

  return { scipPath: outPath, durationMs: performance.now() - t0 };
}
