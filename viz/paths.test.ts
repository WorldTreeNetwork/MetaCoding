import { describe, expect, test } from "bun:test";
import { existsSync } from "node:fs";
import { join } from "node:path";

import {
  CM_DECISIONS_RELPATH,
  PORT_GRAPH_RELPATH,
  PORT_WORKSPACE_ENV,
  cmDecisionsPath,
  portGraphDir,
  portWorkspace,
} from "./paths";

const ROOT = join(import.meta.dir, "..");

describe("port workspace resolution", () => {
  test("unset env keeps today's in-repo layout — and it exists", () => {
    expect(portWorkspace(ROOT, {})).toBe(join(ROOT, "eval/ctkr"));
    // The default must not merely be spelled right: MetaCoding still holds the
    // authoritative workspace copy, so the paths must actually resolve.
    expect(existsSync(cmDecisionsPath(ROOT, {}))).toBe(true);
    expect(existsSync(portGraphDir(ROOT, {}))).toBe(true);
  });

  test("a blank override is treated as unset, not as the repo root", () => {
    expect(portWorkspace(ROOT, { [PORT_WORKSPACE_ENV]: "   " })).toBe(
      join(ROOT, "eval/ctkr"),
    );
  });

  test("an absolute override is honoured for BOTH artifacts", () => {
    const env = { [PORT_WORKSPACE_ENV]: "/srv/farmos-port" };
    expect(portWorkspace(ROOT, env)).toBe("/srv/farmos-port");
    expect(cmDecisionsPath(ROOT, env)).toBe(
      join("/srv/farmos-port", CM_DECISIONS_RELPATH),
    );
    expect(portGraphDir(ROOT, env)).toBe(
      join("/srv/farmos-port", PORT_GRAPH_RELPATH),
    );
  });

  test("a relative override resolves against the repo root", () => {
    const env = { [PORT_WORKSPACE_ENV]: "../farmos-port" };
    expect(portWorkspace(ROOT, env)).toBe(join(ROOT, "../farmos-port"));
    expect(cmDecisionsPath(ROOT, env)).toBe(
      join(ROOT, "../farmos-port", CM_DECISIONS_RELPATH),
    );
  });

  test("the registry path INSIDE the workspace is not configurable", () => {
    // Only the root moves. A port author who could also move the registry
    // within it would be back to pointing the resolver at their own file.
    expect(CM_DECISIONS_RELPATH).toBe(
      "port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
    );
  });
});
