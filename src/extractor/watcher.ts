// Watch mode — initial index, then re-index on file changes via chokidar.
//
// v0 scope:
//  - Initial walk (incremental: skips files whose content hash matches).
//  - On change/add: re-index just that file (delete-then-insert via the
//    same indexFile path used by the directory walker).
//  - On unlink: detach-delete that file's symbols/tokens.
//
// Out of scope (deferred):
//  - Reverse-dep closure: when file A changes, also re-index files that
//    referenced A's symbols. For now we rely on the user re-running a
//    full pass when cross-file edges drift.
//  - LSP didChange notifications. The LSP service is owned by `serve`
//    and reads files fresh; the watcher only updates the graph + FTS.

import { resolve } from "node:path";

import chokidar, { type FSWatcher } from "chokidar";

import type { Store } from "../store";
import { indexDirectory, indexFile, removeFile, type WalkOpts } from "./walker";

export interface WatchOpts extends WalkOpts {
  /** Called every time a file event has been processed; useful for tests. */
  onProcessed?: (event: "change" | "add" | "unlink", relPath: string) => void;
}

export interface WatchHandle {
  /** Stops the watcher. Resolves once chokidar has closed. */
  close(): Promise<void>;
  /** Resolves when the next-pending event has been processed (test aid). */
  drain(): Promise<void>;
}

const DEFAULT_IGNORED = [
  /(^|[\\/])\.git([\\/]|$)/,
  /(^|[\\/])\.omc([\\/]|$)/,
  /(^|[\\/])\.metacoding([\\/]|$)/,
  /(^|[\\/])node_modules([\\/]|$)/,
  /(^|[\\/])dist([\\/]|$)/,
  /(^|[\\/])out([\\/]|$)/,
  /(^|[\\/])coverage([\\/]|$)/,
];

export async function watch(
  store: Store,
  rootPath: string,
  opts: WatchOpts = {},
): Promise<WatchHandle> {
  const root = resolve(rootPath);

  // Initial pass — fast on a warm cache because of the ast_hash skip path.
  await indexDirectory(store, root, opts);

  // Serialize file events through this queue so two saves in quick
  // succession don't race the same Store wrapper.
  let chain: Promise<void> = Promise.resolve();
  const enqueue = (work: () => Promise<void>): Promise<void> => {
    chain = chain.then(work, work);
    return chain;
  };

  const watcher: FSWatcher = chokidar.watch(root, {
    ignored: DEFAULT_IGNORED,
    ignoreInitial: true,
    persistent: true,
  });

  // Don't return until chokidar has finished its initial scan; otherwise
  // events fired immediately after we hand back the handle can be lost.
  await new Promise<void>((resolve, reject) => {
    let settled = false;
    const onReady = () => { if (!settled) { settled = true; resolve(); } };
    const onError = (e: unknown) => { if (!settled) { settled = true; reject(e); } };
    watcher.once("ready", onReady);
    watcher.once("error", onError);
  });

  watcher.on("change", (path: string) => {
    enqueue(async () => {
      await indexFile(store, root, path, opts);
      opts.onProcessed?.("change", path);
    });
  });
  watcher.on("add", (path: string) => {
    enqueue(async () => {
      await indexFile(store, root, path, opts);
      opts.onProcessed?.("add", path);
    });
  });
  watcher.on("unlink", (path: string) => {
    enqueue(async () => {
      await removeFile(store, root, path, opts);
      opts.onProcessed?.("unlink", path);
    });
  });

  return {
    async close() {
      await watcher.close();
      await chain;
    },
    async drain() {
      await chain;
    },
  };
}
