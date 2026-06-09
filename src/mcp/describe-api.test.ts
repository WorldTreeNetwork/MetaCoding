/**
 * Drift guard for describe_api — the self-describe surface agent harnesses
 * query to discover what the MetaCoding MCP server can do.
 *
 * The failure mode this catches: a tool is registered on the live server
 * (server.ts / ctkr-tools.ts) but never added to TOOL_DESCRIPTIONS, so
 * harnesses that rely on describe_api can't see it. That silently happened
 * to all six ctkr.* tools before this guard existed.
 *
 * Strategy: scrape every `registerTool("name", ...)` literal out of the two
 * source files, and assert the set matches the names describeApi() reports.
 */

import { expect, test } from "bun:test";
import { join } from "node:path";
import { describeApi } from "./tools.ts";

const HERE = import.meta.dir;

async function registeredToolNames(file: string): Promise<string[]> {
  const src = await Bun.file(join(HERE, file)).text();
  // Matches: server.registerTool(\n    "name",  — quote style is consistent.
  const re = /registerTool\(\s*["']([^"']+)["']/g;
  const names: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = re.exec(src)) !== null) names.push(m[1]!);
  return names;
}

test("describe_api lists every registered tool (no drift)", async () => {
  const registered = new Set([
    ...(await registeredToolNames("server.ts")),
    ...(await registeredToolNames("ctkr-tools.ts")),
  ]);
  // describe_api registers itself in server.ts but is the self-describe entry,
  // not a separately-described tool — it is present in TOOL_DESCRIPTIONS too,
  // so no special-casing needed here.

  const described = new Set(describeApi().tools.map((t) => t.name));

  const missing = [...registered].filter((n) => !described.has(n));
  expect(missing).toEqual([]);
});

test("describe_api exposes all six ctkr.* tools", () => {
  const described = new Set(describeApi().tools.map((t) => t.name));
  for (const name of [
    "ctkr.motif_search",
    "ctkr.nearest_symbols",
    "ctkr.pattern_search",
    "ctkr.shape_distance",
    "ctkr.role_equivalent",
    "ctkr.centrality_query",
  ]) {
    expect(described.has(name)).toBe(true);
  }
});
