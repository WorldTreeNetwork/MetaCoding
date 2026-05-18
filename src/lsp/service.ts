// LSP service — lazy single-language client per workspace.
// v0: TypeScript only via typescript-language-server. Multi-language is a
// language-id → registry mapping that fans out lazily; trivial extension.

import { existsSync } from "node:fs";
import { createRequire } from "node:module";
import { basename, dirname, join, resolve } from "node:path";

import { LspClient } from "./client";

const require_ = createRequire(import.meta.url);

function findPackageBin(pkg: string, bin: string): string | null {
  let dir: string;
  try { dir = dirname(require_.resolve(`${pkg}/package.json`)); } catch { return null; }
  while (dir !== "/" && basename(dir) !== "node_modules") dir = dirname(dir);
  if (basename(dir) !== "node_modules") return null;
  const p = join(dir, ".bin", bin);
  return existsSync(p) ? p : null;
}

export interface LspServiceOpts {
  rootDir: string;
  /** Pipe LSP stderr through (debugging). */
  verbose?: boolean;
}

export class LspService {
  private tsClient: LspClient | null = null;
  private tsInitPromise: Promise<LspClient> | null = null;

  constructor(private readonly opts: LspServiceOpts) {}

  /** Lazy init — first call pays the warmup cost. */
  async typescript(): Promise<LspClient> {
    if (this.tsClient) return this.tsClient;
    if (this.tsInitPromise) return this.tsInitPromise;

    const cwdBin = join(
      process.cwd(),
      "node_modules",
      ".bin",
      "typescript-language-server",
    );
    const pkgBin = findPackageBin("typescript-language-server", "typescript-language-server");
    const command = existsSync(cwdBin)
      ? cwdBin
      : (pkgBin ?? "typescript-language-server");

    this.tsInitPromise = (async () => {
      const c = await LspClient.spawn({
        rootDir: resolve(this.opts.rootDir),
        command,
        args: ["--stdio"],
        verbose: this.opts.verbose,
      });
      await c.initialize();
      this.tsClient = c;
      return c;
    })();
    return this.tsInitPromise;
  }

  /** Pick the right client for a file extension. v0: only TS/JS family. */
  async forFile(absPath: string): Promise<LspClient | null> {
    if (/\.(tsx?|jsx?|mts|cts|mjs|cjs)$/.test(absPath)) {
      return this.typescript();
    }
    return null;
  }

  async shutdown(): Promise<void> {
    if (this.tsClient) {
      await this.tsClient.shutdown();
      this.tsClient = null;
    }
  }
}
