/**
 * Where the farmOS PORT WORKSPACE lives — the tree holding `port_runs/` and
 * `results/` (packs, seals, PACKS.jsonl, the CM-decision registry, builds).
 *
 * The workspace is the TARGET's ledger, not the instrument's, and it is being
 * extracted into its own repo (bead MetaCoding-1gt). A workspace DECLARES itself
 * with a `port.toml` at its root, and this module walks up from the working
 * directory to find it — the way `git` finds `.git`. The Python half does the
 * same thing in `ctkr/ctkr/workspace.py`; the manifest is the single description
 * both read.
 *
 * This replaced a `METACODING_PORT_WORKSPACE` environment variable. It was the
 * eighth path-ish knob in a system whose actual problem was that a port had no
 * identity — see docs/design/instrument-lens-source.md. The ledger has now moved
 * out of this repo, so a run with no manifest above it searches for the sibling
 * workspace repo and fails with a named remedy if it is not cloned.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";

/** The manifest filename, at the workspace root. */
export const MANIFEST_NAME = "port.toml";

/**
 * Where an EXTRACTED workspace is looked for, relative to the instrument repo
 * root — the mirror of `ctkr.workspace.WORKSPACE_SEARCH_PATH`. Both repos are
 * checked out as siblings; the farmOS ledger lives at
 * github.com/WorldTreeNetwork/FarmOS2 and is cloned beside MetaCoding.
 *
 * A SEARCH PATH, not configuration: an ordered list of places to look, each
 * confirmed by a manifest, degrading to a named error. Deliberately not an env
 * var — see the header for why the last one was deleted.
 */
export const WORKSPACE_SEARCH_PATH = ["../farmos-port"] as const;

/**
 * Registry paths inside the workspace. Fixed on purpose: only the ROOT is
 * discovered. A port author who can move the CM-decision registry within its
 * workspace is citing sanctions from a file they just wrote, which is the
 * self-certification the Python side's INVARIANT 2 exists to refuse — so no
 * manifest key names either of these.
 */
export const PORT_GRAPH_RELPATH = "results/feature-kind-graph-data";
export const CM_DECISIONS_RELPATH =
  "port_runs/kernel-9h5.24/build/cm-decisions.jsonl";

export interface PortManifest {
  root: string;
  name: string;
  /** The commit the ledger's evidence was recorded against. */
  sourcePin: string;
  sourcePath: string | null;
  /** True when the workspace was assumed (no manifest), not declared. */
  implicit: boolean;
}

/** Walk up from `start` looking for a `port.toml`. */
export function findManifest(start: string = process.cwd()): string | null {
  let dir = resolve(start);
  for (;;) {
    const candidate = join(dir, MANIFEST_NAME);
    if (existsSync(candidate)) return candidate;
    const parent = dirname(dir);
    if (parent === dir) return null;
    dir = parent;
  }
}

/** Read a manifest. Throws with the path when it cannot be parsed. */
export function loadManifest(manifest: string): PortManifest {
  let data: Record<string, any>;
  try {
    data = Bun.TOML.parse(readFileSync(manifest, "utf8")) as Record<string, any>;
  } catch (err) {
    throw new Error(`${manifest}: cannot read the port manifest — ${err}`);
  }
  const root = dirname(manifest);
  const rawPath = data.source?.path;
  return {
    root,
    name: String(data.port?.name ?? ""),
    sourcePin: String(data.source?.pin ?? ""),
    sourcePath: rawPath
      ? isAbsolute(String(rawPath))
        ? String(rawPath)
        : resolve(root, String(rawPath))
      : null,
    implicit: false,
  };
}

/** First place on the search path that actually carries a manifest. */
export function defaultWorkspace(repoRoot: string): string | null {
  for (const rel of WORKSPACE_SEARCH_PATH) {
    const candidate = resolve(repoRoot, rel);
    if (existsSync(join(candidate, MANIFEST_NAME))) return candidate;
  }
  return null;
}

export function discoverWorkspace(
  repoRoot: string,
  start: string = process.cwd(),
): PortManifest {
  const manifest = findManifest(start);
  if (manifest) return loadManifest(manifest);

  // Found by search rather than from cwd: read the manifest so the pin and
  // source travel, but keep implicit=true, because the ROOT was assumed.
  const searched = defaultWorkspace(repoRoot);
  if (searched) return { ...loadManifest(join(searched, MANIFEST_NAME)), implicit: true };

  throw new Error(
    `no ${MANIFEST_NAME} found above ${start}, and no workspace on the search ` +
      `path ${WORKSPACE_SEARCH_PATH.join(", ")} relative to ${repoRoot}. The farmOS ` +
      `ledger is a separate repo: clone github.com/WorldTreeNetwork/FarmOS2 beside ` +
      `this one.`,
  );
}

/** Resolve the port-workspace root. */
export function portWorkspace(repoRoot: string, start?: string): string {
  return discoverWorkspace(repoRoot, start).root;
}

/** The bipartite feature×kind graph data dir inside the workspace. */
export function portGraphDir(repoRoot: string, start?: string): string {
  return join(portWorkspace(repoRoot, start), PORT_GRAPH_RELPATH);
}

/** The bound CM-decision registry inside the workspace. */
export function cmDecisionsPath(repoRoot: string, start?: string): string {
  return join(portWorkspace(repoRoot, start), CM_DECISIONS_RELPATH);
}
