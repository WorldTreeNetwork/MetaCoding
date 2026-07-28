/**
 * Where the farmOS PORT WORKSPACE lives — the tree holding `port_runs/` and
 * `results/` (packs, seals, PACKS.jsonl, the CM-decision registry, builds).
 *
 * The workspace is the TARGET's ledger, not the instrument's, and it is being
 * extracted into its own repo (bead MetaCoding-1gt). Until every consumer is
 * pointed at that repo, MetaCoding keeps the authoritative copy in-tree at
 * `eval/ctkr` — so the default here is exactly today's layout and nothing
 * changes for anyone who sets nothing.
 *
 * Override with `METACODING_PORT_WORKSPACE`: absolute (an extracted workspace
 * repo) or relative to the MetaCoding repo root.
 */
import { isAbsolute, join } from "node:path";

export const PORT_WORKSPACE_ENV = "METACODING_PORT_WORKSPACE";

/** The in-repo workspace location, relative to the repo root. */
export const DEFAULT_PORT_WORKSPACE = "eval/ctkr";

/** Registry paths inside the workspace. Fixed: only the ROOT is configurable. */
export const PORT_GRAPH_RELPATH = "results/feature-kind-graph-data";
export const CM_DECISIONS_RELPATH =
  "port_runs/kernel-9h5.24/build/cm-decisions.jsonl";

/**
 * Resolve the port-workspace root. `env` defaults to the process environment;
 * a blank or unset override yields `<repoRoot>/eval/ctkr`.
 */
export function portWorkspace(
  repoRoot: string,
  env: Record<string, string | undefined> = process.env,
): string {
  const raw = (env[PORT_WORKSPACE_ENV] ?? "").trim();
  if (!raw) return join(repoRoot, DEFAULT_PORT_WORKSPACE);
  return isAbsolute(raw) ? raw : join(repoRoot, raw);
}

/** The bipartite feature×kind graph data dir inside the workspace. */
export function portGraphDir(
  repoRoot: string,
  env?: Record<string, string | undefined>,
): string {
  return join(portWorkspace(repoRoot, env), PORT_GRAPH_RELPATH);
}

/** The bound CM-decision registry inside the workspace. */
export function cmDecisionsPath(
  repoRoot: string,
  env?: Record<string, string | undefined>,
): string {
  return join(portWorkspace(repoRoot, env), CM_DECISIONS_RELPATH);
}
