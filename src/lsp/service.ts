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

/** Thrown by forFile()/php() when a required language server isn't installed. */
export class LspServerNotInstalledError extends Error {
  constructor(pkg: string, installHint: string) {
    super(
      `PHP language server ('${pkg}') is not installed.\n` +
        `Install it with one of:\n` +
        `  bun add -D ${pkg}\n` +
        `  ${installHint}`,
    );
    this.name = "LspServerNotInstalledError";
  }
}

/** Resolve a package's bin, checking cwd node_modules/.bin first (matches how
 *  bun installs project deps), then package resolution (works for nested
 *  installs / monorepos). Returns null if the package isn't reachable. */
function resolveBin(pkg: string, bin: string): string | null {
  const cwdBin = join(process.cwd(), "node_modules", ".bin", bin);
  if (existsSync(cwdBin)) return cwdBin;
  return findPackageBin(pkg, bin);
}

export class LspService {
  private tsClient: LspClient | null = null;
  private tsInitPromise: Promise<LspClient> | null = null;
  private phpClient: LspClient | null = null;
  private phpInitPromise: Promise<LspClient> | null = null;

  constructor(private readonly opts: LspServiceOpts) {}

  /** Lazy init — first call pays the warmup cost. */
  async typescript(): Promise<LspClient> {
    if (this.tsClient) return this.tsClient;
    if (this.tsInitPromise) return this.tsInitPromise;

    const command = resolveBin("typescript-language-server", "typescript-language-server")
      ?? "typescript-language-server";

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

  /** Lazy init — first call pays the warmup cost.
   *  Intelephense (npm-installable PHP language server). If it isn't
   *  reachable via node_modules or the global PATH, throws
   *  LspServerNotInstalledError with install instructions rather than
   *  letting the spawn fail with an opaque ENOENT. */
  async php(): Promise<LspClient> {
    if (this.phpClient) return this.phpClient;
    if (this.phpInitPromise) return this.phpInitPromise;

    const command = resolveBin("intelephense", "intelephense");
    if (!command) {
      throw new LspServerNotInstalledError("intelephense", "bunx intelephense --stdio");
    }

    this.phpInitPromise = (async () => {
      const c = await LspClient.spawn({
        rootDir: resolve(this.opts.rootDir),
        command,
        args: ["--stdio"],
        verbose: this.opts.verbose,
      });
      await c.initialize();
      this.phpClient = c;
      return c;
    })();
    return this.phpInitPromise;
  }

  /** Pick the right client for a file extension. v0: TS/JS family + PHP. */
  async forFile(absPath: string): Promise<LspClient | null> {
    if (/\.(tsx?|jsx?|mts|cts|mjs|cjs)$/.test(absPath)) {
      return this.typescript();
    }
    if (/\.php$/.test(absPath)) {
      return this.php();
    }
    return null;
  }

  async shutdown(): Promise<void> {
    if (this.tsClient) {
      await this.tsClient.shutdown();
      this.tsClient = null;
    }
    if (this.phpClient) {
      await this.phpClient.shutdown();
      this.phpClient = null;
    }
  }
}
