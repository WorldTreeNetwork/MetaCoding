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
 * identity — see docs/design/instrument-lens-source.md. Until the ledger
 * physically moves, a run with no manifest above it falls back to today's in-repo
 * `eval/ctkr`, so nothing changes for anyone who does nothing.
 */
import { existsSync, readFileSync } from "node:fs";
import { dirname, isAbsolute, join, resolve } from "node:path";

/** The manifest filename, at the workspace root. */
export const MANIFEST_NAME = "port.toml";

/** The in-repo workspace location, relative to the repo root. */
export const DEFAULT_PORT_WORKSPACE = "eval/ctkr";

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

/**
 * The workspace in effect: a discovered manifest wins, else the in-repo
 * fallback, flagged `implicit` so a caller can tell declared from guessed.
 */
export function discoverWorkspace(
  repoRoot: string,
  start: string = process.cwd(),
): PortManifest {
  const manifest = findManifest(start);
  if (manifest) return loadManifest(manifest);
  return {
    root: join(repoRoot, DEFAULT_PORT_WORKSPACE),
    name: "",
    sourcePin: "",
    sourcePath: null,
    implicit: true,
  };
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
