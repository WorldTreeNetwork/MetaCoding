import { describe, expect, test } from "bun:test";
import { existsSync, mkdirSync, mkdtempSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import {
  CM_DECISIONS_RELPATH,
  MANIFEST_NAME,
  PORT_GRAPH_RELPATH,
  cmDecisionsPath,
  defaultWorkspace,
  discoverWorkspace,
  findManifest,
  portGraphDir,
  portWorkspace,
} from "./paths";

const ROOT = join(import.meta.dir, "..");

/** A workspace that DECLARES itself, in a tree with no manifest above it. */
function declaredWorkspace(body = '[port]\nname = "testport"\n'): string {
  const base = mkdtempSync(join(tmpdir(), "portws-"));
  const ws = join(base, "farmos-port");
  mkdirSync(ws, { recursive: true });
  writeFileSync(join(ws, MANIFEST_NAME), body);
  return ws;
}

describe("port workspace resolution", () => {
  test("with no manifest above it, the search path finds the sibling repo", () => {
    const nowhere = mkdtempSync(join(tmpdir(), "nomanifest-"));
    expect(findManifest(nowhere)).toBeNull();

    const searched = defaultWorkspace(ROOT);
    expect(searched).not.toBeNull();
    expect(portWorkspace(ROOT, nowhere)).toBe(searched!);
    // Not merely spelled right: the ledger must actually be there. These paths
    // resolving is what makes the sibling checkout a real dependency rather than
    // a hopeful string.
    expect(existsSync(cmDecisionsPath(ROOT, nowhere))).toBe(true);
    expect(existsSync(portGraphDir(ROOT, nowhere))).toBe(true);
  });

  test("an assumed workspace says so, a declared one does not", () => {
    const nowhere = mkdtempSync(join(tmpdir(), "nomanifest-"));
    // Found by search: the root was assumed, so implicit — but the pin travels.
    const searched = discoverWorkspace(ROOT, nowhere);
    expect(searched.implicit).toBe(true);
    expect(searched.sourcePin).toBeTruthy();
    expect(discoverWorkspace(ROOT, declaredWorkspace()).implicit).toBe(false);
  });

  test("a declared manifest wins for BOTH artifacts", () => {
    const ws = declaredWorkspace();
    expect(portWorkspace(ROOT, ws)).toBe(ws);
    expect(cmDecisionsPath(ROOT, ws)).toBe(join(ws, CM_DECISIONS_RELPATH));
    expect(portGraphDir(ROOT, ws)).toBe(join(ws, PORT_GRAPH_RELPATH));
  });

  test("a manifest in a parent is found from a subdirectory", () => {
    const ws = declaredWorkspace();
    const deep = join(ws, "port_runs", "wave2", "spine-asset");
    mkdirSync(deep, { recursive: true });
    expect(portWorkspace(ROOT, deep)).toBe(ws);
  });

  test("the manifest carries the source pin", () => {
    const pin = "3fe0ce7e23de807be9b8bc97a211ce934327db39";
    const ws = declaredWorkspace(
      `[port]\nname = "farmos"\n[source]\npath = "../farmos-src"\npin = "${pin}"\n`,
    );
    const found = discoverWorkspace(ROOT, ws);
    expect(found.sourcePin).toBe(pin);
    expect(found.sourcePath).toBe(join(ws, "..", "farmos-src"));
  });

  test("the registry path INSIDE the workspace is not configurable", () => {
    // Only the root moves. A port author who could also move the registry
    // within it would be back to pointing the resolver at their own file, so a
    // manifest that names one is ignored rather than honoured.
    const ws = declaredWorkspace(
      '[port]\nname = "x"\n[ledger]\ndecisions = "i-wrote-this.jsonl"\n',
    );
    expect(CM_DECISIONS_RELPATH).toBe(
      "port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
    );
    expect(cmDecisionsPath(ROOT, ws)).toBe(join(ws, CM_DECISIONS_RELPATH));
  });
});
