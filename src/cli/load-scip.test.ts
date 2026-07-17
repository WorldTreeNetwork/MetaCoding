// Tests for the pre-built SCIP ingest path wired into the CLI `index` command
// (--load-scip / --scip-language / --scip-psr4). bead MetaCoding-i00 follow-up.
//
// Root cause this guards against: before this wiring, the CLI `index --scip`
// path could ONLY run an in-process indexer (detectScipLanguages: TS/Python
// only; runScipPhp indexes a bare repo) and had NO way to ingest an
// externally-built full-site scip-php index — so the farmOS→Drupal boundary
// edges (REFERENCES/CALLS, bead MetaCoding-i00) computed by loadScip never
// reached any CLI-built graph. The measurement harness produced 4,374 boundary
// edges by calling loadScip directly; the product CLI produced zero. These
// tests exercise the extracted ingest helpers so the two can never diverge.

import { test, expect, describe } from "bun:test";
import { writeFileSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";
import { normalizeScipLang, ingestPrebuiltScip } from "./main.ts";
import { symbolId } from "../extractor/identity.ts";
import type { EdgeKind } from "../store/types.ts";

const DEF = scip.SymbolRole.Definition;

interface StubEdge { kind: EdgeKind; src_id: string; dst_id: string }
function makeStubStore(): {
  edges: StubEdge[];
  symbols: { id: string; language: string; qualified_name: string; file: string }[];
  store: any;
} {
  const edges: StubEdge[] = [];
  const symbols: { id: string; language: string; qualified_name: string; file: string }[] = [];
  const store = {
    async upsertSymbol(s: any) {
      symbols.push({ id: s.id, language: s.language, qualified_name: s.qualified_name, file: s.file });
    },
    async addEdge(e: any) { edges.push({ kind: e.kind, src_id: e.src_id, dst_id: e.dst_id }); },
    async fileHash() { return null; },
    async deleteFileData() {},
    writeTokens() {},
  };
  return { edges, symbols, store };
}

function writeTmpScip(bytes: Uint8Array): string {
  const dir = mkdtempSync(join(tmpdir(), "metacoding-loadscip-test-"));
  const p = join(dir, "index.scip");
  writeFileSync(p, bytes);
  return p;
}

// A synthetic full-site-shaped scip-php index: a farmOS Asset class + save()
// method, whose body calls into an out-of-index Drupal-core method. This is the
// exact shape that yields boundary REFERENCES + CALLS edges.
function farmSiteScipBytes(): Uint8Array {
  const FARM = "scip-php composer drupal/farm 1.0.0";
  const CORE = "scip-php composer drupal/core 11.0.0";
  const doc = new scip.Document({
    relative_path: "Drupal/farm_asset/Entity/Asset.php",
    language: "php",
    occurrences: [
      new scip.Occurrence({ symbol: `${FARM} Drupal/farm_asset/Entity/Asset#`, range: [1, 6, 1, 11], symbol_roles: DEF }),
      new scip.Occurrence({ symbol: `${FARM} Drupal/farm_asset/Entity/Asset#save().`, range: [5, 10, 5, 14], symbol_roles: DEF }),
      // Out-of-index Drupal-core method reference inside save()'s body.
      new scip.Occurrence({ symbol: `${CORE} Drupal/Core/Entity/ContentEntityBase#save().`, range: [6, 8, 6, 12], symbol_roles: 0 }),
    ],
    symbols: [],
  });
  return new scip.Index({ documents: [doc] }).serialize();
}

describe("normalizeScipLang", () => {
  test("accepts ts / typescript / py / python / php (case-insensitive)", () => {
    expect(normalizeScipLang("ts")).toBe("ts");
    expect(normalizeScipLang("typescript")).toBe("ts");
    expect(normalizeScipLang("TypeScript")).toBe("ts");
    expect(normalizeScipLang("py")).toBe("py");
    expect(normalizeScipLang("python")).toBe("py");
    expect(normalizeScipLang("php")).toBe("php");
    expect(normalizeScipLang("PHP")).toBe("php");
  });

  test("throws on an unknown language token", () => {
    expect(() => normalizeScipLang("ruby")).toThrow(/unknown --scip-language/);
  });
});

describe("ingestPrebuiltScip — CLI --load-scip path", () => {
  test("php index yields the farmOS→Drupal boundary REFERENCES + CALLS edges", async () => {
    const { edges, symbols, store } = makeStubStore();
    const scipPath = writeTmpScip(farmSiteScipBytes());

    const stats = await ingestPrebuiltScip(store, scipPath, {
      repo: "farmos",
      branch: "main",
      scipLanguage: "php",
    });

    const boundaryId = symbolId("external", "farmos", "external::ContentEntityBase");
    expect(symbols.some((s) => s.id === boundaryId && s.language === "external")).toBe(true);
    expect(edges.filter((e) => e.kind === "REFERENCES" && e.dst_id === boundaryId).length).toBe(1);
    expect(edges.filter((e) => e.kind === "CALLS" && e.dst_id === boundaryId).length).toBe(1);
    expect(stats.externalBoundaryEdges).toBe(1);
    // farmOS defs are tagged as php, proving the language override routed correctly.
    expect(symbols.some((s) => s.language === "php")).toBe(true);
  });

  test("defaults language to php when scipLanguage is omitted", async () => {
    const { edges, store } = makeStubStore();
    const scipPath = writeTmpScip(farmSiteScipBytes());
    const stats = await ingestPrebuiltScip(store, scipPath, { repo: "farmos", branch: "main" });
    expect(stats.externalBoundaryEdges).toBe(1);
    expect(edges.some((e) => e.kind === "CALLS")).toBe(true);
  });

  test("honors the PHP PSR-4 sidecar to recover real file paths", async () => {
    const { symbols, store } = makeStubStore();
    const scipPath = writeTmpScip(farmSiteScipBytes());
    await ingestPrebuiltScip(store, scipPath, {
      repo: "farmos",
      branch: "main",
      scipLanguage: "php",
      phpPsr4Map: { "Drupal\\farm_asset\\": "modules/asset/src/" },
    });
    // With the PSR-4 map, the Asset class file is recovered under the mapped
    // dir (elided /src/ root restored), not the namespace-derived relative_path.
    const asset = symbols.find((s) => s.qualified_name.endsWith("::Asset"));
    expect(asset?.file).toBe("modules/asset/src/Entity/Asset.php");
  });

  test("throws a clear error when the index file is missing", async () => {
    const { store } = makeStubStore();
    await expect(
      ingestPrebuiltScip(store, "/no/such/index.scip", { repo: "farmos", branch: "main" }),
    ).rejects.toThrow(/index file not found/);
  });
});
