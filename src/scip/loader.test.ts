// Tests for the behavior-capturing edge types added by bead MetaCoding-e54:
// READS_FIELD, WRITES_FIELD, RETURNS_TYPE, CONSTRUCTS.
//
// Strategy: build minimal synthetic SCIP Index objects in-memory and pass
// them through a thin test harness that calls the same edge-extraction logic
// as loadScip(), without touching disk or a real Store.  We re-use the
// private helpers indirectly by examining what edges come out of loadScip()
// when fed a synthetic .scip byte payload.
//
// The tests use a lightweight in-memory Store stub that captures every
// addEdge() call so we can assert on edge kinds without a real ladybugdb.

import { test, expect, describe, beforeEach } from "bun:test";

import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";
import { parseScipSymbol, kindOf, phpRealFile } from "./symbol.ts";
import type { Edge, EdgeKind } from "../store/types.ts";

// ---------------------------------------------------------------------------
// Minimal in-memory Store stub — captures edges for assertion.
// ---------------------------------------------------------------------------
interface StubEdge { kind: EdgeKind; src_id: string; dst_id: string }

function makeStubStore(): {
  edges: StubEdge[];
  symbols: string[];
  store: Parameters<typeof import("./loader.ts")["loadScip"]>[0];
} {
  const edges: StubEdge[] = [];
  const symbols: string[] = [];

  const store = {
    async upsertSymbol(s: { id: string }) { symbols.push(s.id); },
    async addEdge(e: { kind: EdgeKind; src_id: string; dst_id: string }) {
      edges.push({ kind: e.kind, src_id: e.src_id, dst_id: e.dst_id });
    },
    async fileHash() { return null; },
    async deleteFileData() {},
    writeTokens() {},
  } as unknown as Parameters<typeof import("./loader.ts")["loadScip"]>[0];

  return { edges, symbols, store };
}

// ---------------------------------------------------------------------------
// Helper: build a minimal serialised SCIP Index with controllable occurrences.
// ---------------------------------------------------------------------------
interface OccSpec {
  symbol: string;
  range: number[];
  enclosing_range?: number[];
  symbol_roles: number;
}
interface SymInfoSpec {
  symbol: string;
  relationships?: Array<{ symbol: string; is_implementation?: boolean; is_type_definition?: boolean }>;
  kind?: number;
}

function buildScipBytes(occurrences: OccSpec[], symInfos: SymInfoSpec[] = []): Uint8Array {
  const occs = occurrences.map((o) =>
    new scip.Occurrence({
      symbol: o.symbol,
      range: o.range,
      enclosing_range: o.enclosing_range ?? [],
      symbol_roles: o.symbol_roles,
    }),
  );

  const infos = symInfos.map(
    (s) =>
      new scip.SymbolInformation({
        symbol: s.symbol,
        kind: s.kind ?? 0,
        relationships: (s.relationships ?? []).map(
          (r) =>
            new scip.Relationship({
              symbol: r.symbol,
              is_implementation: r.is_implementation ?? false,
              is_type_definition: r.is_type_definition ?? false,
              is_reference: false,
            }),
        ),
      }),
  );

  const doc = new scip.Document({
    relative_path: "src/example.ts",
    language: "typescript",
    occurrences: occs,
    symbols: infos,
  });

  const idx = new scip.Index({ documents: [doc] });
  return idx.serialize();
}

// ---------------------------------------------------------------------------
// Import the loader under test.  We need to feed it a real serialised index
// because loadScip() calls readFileSync internally.  We intercept at the
// Store level rather than mocking the file system.
// ---------------------------------------------------------------------------
import { loadScip } from "./loader.ts";
import { writeFileSync, unlinkSync, mkdtempSync } from "node:fs";
import { join } from "node:path";
import { tmpdir } from "node:os";

async function withTmpScip(bytes: Uint8Array, fn: (path: string) => Promise<unknown>): Promise<void> {
  const dir = mkdtempSync(join(tmpdir(), "metacoding-test-"));
  const path = join(dir, "index.scip");
  writeFileSync(path, bytes);
  try {
    await fn(path);
  } finally {
    try { unlinkSync(path); } catch {}
  }
}

const OPTS = {
  branch: "main",
  repo: "test-repo",
  language: "ts" as const,
};

// SCIP symbols used in fixtures.
// Format: <scheme> <manager> <pkg> <version> <descriptors>
const SCIP_FILE     = "scip-typescript npm test-repo HEAD src/";
const SCIP_CLASS    = "scip-typescript npm test-repo HEAD src/ `example.ts`/ MyClass#";
const SCIP_METHOD   = "scip-typescript npm test-repo HEAD src/ `example.ts`/ MyClass# myMethod().";
const SCIP_FIELD    = "scip-typescript npm test-repo HEAD src/ `example.ts`/ MyClass# myField.";
// Top-level functions in SCIP use the term suffix (`.`) without parentheses.
// Functions with distinct signatures use `method` suffix (`().`).
// We use the term form here so kindOf() maps to "function".
const SCIP_FN       = "scip-typescript npm test-repo HEAD src/ `example.ts`/ myFunc.";
const SCIP_TYPE     = "scip-typescript npm test-repo HEAD src/ `example.ts`/ MyType#";
// Constructor uses backtick-quoted name and "+" disambiguator in scip-typescript.
const SCIP_CTOR     = "scip-typescript npm test-repo HEAD src/ `example.ts`/ MyClass# `constructor`(+).";

// Line 0–100 method body enclosing range.
const METHOD_RANGE = [5, 0, 20, 1];

// ---------------------------------------------------------------------------
// Verify our symbol parser agrees on field / method / class kinds.
// ---------------------------------------------------------------------------
describe("symbol kind detection", () => {
  test("SCIP_FIELD resolves to field kind", () => {
    const parsed = parseScipSymbol(SCIP_FIELD);
    expect(parsed).not.toBeNull();
    expect(kindOf(parsed!)).toBe("field");
  });

  test("SCIP_METHOD resolves to method kind", () => {
    const parsed = parseScipSymbol(SCIP_METHOD);
    expect(parsed).not.toBeNull();
    expect(kindOf(parsed!)).toBe("method");
  });

  test("SCIP_CLASS resolves to class kind", () => {
    const parsed = parseScipSymbol(SCIP_CLASS);
    expect(parsed).not.toBeNull();
    expect(kindOf(parsed!)).toBe("class");
  });

  test("SCIP_FN resolves to function kind", () => {
    const parsed = parseScipSymbol(SCIP_FN);
    expect(parsed).not.toBeNull();
    expect(kindOf(parsed!)).toBe("function");
  });
});

// ---------------------------------------------------------------------------
// WRITES_FIELD
// ---------------------------------------------------------------------------
describe("WRITES_FIELD edge", () => {
  test("WriteAccess occurrence on a field emits WRITES_FIELD", async () => {
    const bytes = buildScipBytes([
      // Definition: method
      { symbol: SCIP_METHOD, range: METHOD_RANGE, symbol_roles: scip.SymbolRole.Definition },
      // Definition: field
      { symbol: SCIP_FIELD, range: [2, 2, 2, 10], symbol_roles: scip.SymbolRole.Definition },
      // WriteAccess occurrence of the field inside the method body
      {
        symbol: SCIP_FIELD,
        range: [10, 4, 10, 11],
        enclosing_range: METHOD_RANGE,
        symbol_roles: scip.SymbolRole.WriteAccess,
      },
    ]);

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    const writeEdges = edges.filter((e) => e.kind === "WRITES_FIELD");
    expect(writeEdges.length).toBeGreaterThan(0);
    // No REFERENCES edge for the same (method→field) pair.
    const refEdges = edges.filter(
      (e) => e.kind === "REFERENCES" &&
        writeEdges.some((w) => w.src_id === e.src_id && w.dst_id === e.dst_id),
    );
    expect(refEdges.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// READS_FIELD
// ---------------------------------------------------------------------------
describe("READS_FIELD edge", () => {
  test("ReadAccess occurrence on a field emits READS_FIELD", async () => {
    const bytes = buildScipBytes([
      { symbol: SCIP_METHOD, range: METHOD_RANGE, symbol_roles: scip.SymbolRole.Definition },
      { symbol: SCIP_FIELD, range: [2, 2, 2, 10], symbol_roles: scip.SymbolRole.Definition },
      {
        symbol: SCIP_FIELD,
        range: [12, 4, 12, 11],
        enclosing_range: METHOD_RANGE,
        symbol_roles: scip.SymbolRole.ReadAccess,
      },
    ]);

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    const readEdges = edges.filter((e) => e.kind === "READS_FIELD");
    expect(readEdges.length).toBeGreaterThan(0);
    // No REFERENCES edge for the same pair.
    const refEdges = edges.filter(
      (e) => e.kind === "REFERENCES" &&
        readEdges.some((r) => r.src_id === e.src_id && r.dst_id === e.dst_id),
    );
    expect(refEdges.length).toBe(0);
  });

  test("unadorned (no ReadAccess/WriteAccess) occurrence on a field falls back to REFERENCES", async () => {
    const bytes = buildScipBytes([
      { symbol: SCIP_METHOD, range: METHOD_RANGE, symbol_roles: scip.SymbolRole.Definition },
      { symbol: SCIP_FIELD, range: [2, 2, 2, 10], symbol_roles: scip.SymbolRole.Definition },
      // No ReadAccess / WriteAccess flags — plain reference.
      {
        symbol: SCIP_FIELD,
        range: [12, 4, 12, 11],
        enclosing_range: METHOD_RANGE,
        symbol_roles: 0,
      },
    ]);

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    // Should be REFERENCES, not READS_FIELD.
    const refEdges = edges.filter((e) => e.kind === "REFERENCES");
    expect(refEdges.length).toBeGreaterThan(0);
    expect(edges.filter((e) => e.kind === "READS_FIELD").length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// RETURNS_TYPE
// ---------------------------------------------------------------------------
describe("RETURNS_TYPE edge", () => {
  test("is_type_definition relationship on a method emits RETURNS_TYPE", async () => {
    const bytes = buildScipBytes(
      [
        { symbol: SCIP_METHOD, range: METHOD_RANGE, symbol_roles: scip.SymbolRole.Definition },
        { symbol: SCIP_TYPE, range: [30, 0, 30, 10], symbol_roles: scip.SymbolRole.Definition },
      ],
      [
        {
          symbol: SCIP_METHOD,
          relationships: [{ symbol: SCIP_TYPE, is_type_definition: true }],
        },
      ],
    );

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    const rtEdges = edges.filter((e) => e.kind === "RETURNS_TYPE");
    expect(rtEdges.length).toBeGreaterThan(0);
    // Must NOT also emit TYPE_OF for the same pair.
    const typeOfEdges = edges.filter(
      (e) => e.kind === "TYPE_OF" &&
        rtEdges.some((r) => r.src_id === e.src_id && r.dst_id === e.dst_id),
    );
    expect(typeOfEdges.length).toBe(0);
  });

  test("is_type_definition relationship on a non-callable emits TYPE_OF, not RETURNS_TYPE", async () => {
    // SCIP_FIELD is a field (kind='field'), so is_type_definition → TYPE_OF.
    const bytes = buildScipBytes(
      [
        { symbol: SCIP_FIELD, range: [2, 2, 2, 10], symbol_roles: scip.SymbolRole.Definition },
        { symbol: SCIP_TYPE, range: [30, 0, 30, 10], symbol_roles: scip.SymbolRole.Definition },
      ],
      [
        {
          symbol: SCIP_FIELD,
          relationships: [{ symbol: SCIP_TYPE, is_type_definition: true }],
        },
      ],
    );

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    expect(edges.filter((e) => e.kind === "TYPE_OF").length).toBeGreaterThan(0);
    expect(edges.filter((e) => e.kind === "RETURNS_TYPE").length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// CONSTRUCTS
// ---------------------------------------------------------------------------
describe("CONSTRUCTS edge", () => {
  test("reference to a constructor symbol emits CONSTRUCTS", async () => {
    const bytes = buildScipBytes([
      { symbol: SCIP_FN, range: [0, 0, 25, 1], symbol_roles: scip.SymbolRole.Definition },
      { symbol: SCIP_CTOR, range: [50, 0, 50, 15], symbol_roles: scip.SymbolRole.Definition },
      // Plain (no ReadAccess/WriteAccess) occurrence of the constructor inside FN.
      {
        symbol: SCIP_CTOR,
        range: [10, 2, 10, 14],
        enclosing_range: [0, 0, 25, 1],
        symbol_roles: 0,
      },
    ]);

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    const ctorEdges = edges.filter((e) => e.kind === "CONSTRUCTS");
    expect(ctorEdges.length).toBeGreaterThan(0);
  });

  test("reference to a class symbol (not constructor method) also emits CONSTRUCTS", async () => {
    // When scip-typescript resolves `new Foo()` to the class type symbol (not
    // a dedicated constructor method), the occurrence points to SCIP_CLASS
    // which has a `type` suffix — isConstructorSymbol() returns true.
    const bytes = buildScipBytes([
      { symbol: SCIP_FN, range: [0, 0, 25, 1], symbol_roles: scip.SymbolRole.Definition },
      { symbol: SCIP_CLASS, range: [30, 0, 35, 1], symbol_roles: scip.SymbolRole.Definition },
      {
        symbol: SCIP_CLASS,
        range: [10, 2, 10, 9],
        enclosing_range: [0, 0, 25, 1],
        symbol_roles: 0,
      },
    ]);

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    const ctorEdges = edges.filter((e) => e.kind === "CONSTRUCTS");
    expect(ctorEdges.length).toBeGreaterThan(0);
  });

  test("plain REFERENCES not emitted for CONSTRUCTS pair", async () => {
    const bytes = buildScipBytes([
      { symbol: SCIP_FN, range: [0, 0, 25, 1], symbol_roles: scip.SymbolRole.Definition },
      { symbol: SCIP_CTOR, range: [50, 0, 50, 15], symbol_roles: scip.SymbolRole.Definition },
      {
        symbol: SCIP_CTOR,
        range: [10, 2, 10, 14],
        enclosing_range: [0, 0, 25, 1],
        symbol_roles: 0,
      },
    ]);

    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));

    const ctorEdges = edges.filter((e) => e.kind === "CONSTRUCTS");
    const refEdges = edges.filter(
      (e) => e.kind === "REFERENCES" &&
        ctorEdges.some((c) => c.src_id === e.src_id && c.dst_id === e.dst_id),
    );
    expect(ctorEdges.length).toBeGreaterThan(0);
    expect(refEdges.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// PHP (scip-php) reconciliation.
//
// scip-php differs from scip-typescript in two ways the loader must handle:
//   1. Symbols are named by PHP FQN, not file path (`App/Demo#tweak().`), so
//      the file comes from Document.relative_path and qualified_name is rebuilt
//      as `<file>::Class::member` to match the Tree-sitter lane.
//   2. It emits NO enclosing_range, so reference->caller attribution falls back
//      to nearest-preceding-container-by-start-position.
// ---------------------------------------------------------------------------
function buildPhpScipBytes(relPath: string, occurrences: OccSpec[]): Uint8Array {
  const doc = new scip.Document({
    relative_path: relPath,
    language: "php",
    occurrences: occurrences.map((o) => new scip.Occurrence({
      symbol: o.symbol,
      range: o.range,
      enclosing_range: o.enclosing_range ?? [],
      symbol_roles: o.symbol_roles,
    })),
    symbols: [],
  });
  return new scip.Index({ documents: [doc] }).serialize();
}

const PHP_OPTS = { branch: "main", repo: "test-repo", language: "php" as const };
const P = "scip-php composer fixture/app 1.0.0";
const DEF = scip.SymbolRole.Definition;

describe("PHP scip-php reconciliation", () => {
  test("qualified_name rebuilt as <file>::Class::member from FQN + doc path", async () => {
    const captured: { id: string; qn: string; short: string; kind: string }[] = [];
    const store = {
      async upsertSymbol(s: any) { captured.push({ id: s.id, qn: s.qualified_name, short: s.short_name, kind: s.kind }); },
      async addEdge() {}, async fileHash() { return null; },
      async deleteFileData() {}, writeTokens() {},
    } as unknown as Parameters<typeof loadScip>[0];

    const bytes = buildPhpScipBytes("src/Demo.php", [
      { symbol: `${P} App/Demo#`, range: [3, 6, 3, 10], symbol_roles: DEF },
      { symbol: `${P} App/Demo#tweak().`, range: [5, 20, 5, 25], symbol_roles: DEF },
      { symbol: `${P} App/Demo#$name.`, range: [4, 12, 4, 17], symbol_roles: DEF },
    ]);
    await withTmpScip(bytes, (p) => loadScip(store, p, PHP_OPTS));

    const byQn = new Map(captured.map((c) => [c.qn, c]));
    expect(byQn.get("src/Demo.php::Demo")?.kind).toBe("class");
    expect(byQn.get("src/Demo.php::Demo::tweak")?.kind).toBe("method");
    // Field: leading `$` stripped to match the Tree-sitter lane.
    expect(byQn.get("src/Demo.php::Demo::name")?.kind).toBe("field");
    expect(byQn.get("src/Demo.php::Demo::name")?.short).toBe("name");
  });

  test("reference attributed to nearest preceding container (no enclosing_range)", async () => {
    const { edges, store } = makeStubStore();
    // Two methods; a reference inside go()'s body targets run(). With no
    // enclosing_range, the ref at line 12 must attribute to go() (starts L11),
    // not run() (starts L6) — nearest-preceding container wins.
    const bytes = buildPhpScipBytes("src/Demo.php", [
      { symbol: `${P} App/Demo#`, range: [1, 6, 1, 10], symbol_roles: DEF },
      { symbol: `${P} App/Demo#run().`, range: [6, 20, 6, 23], symbol_roles: DEF },
      { symbol: `${P} App/Demo#go().`, range: [11, 20, 11, 22], symbol_roles: DEF },
      { symbol: `${P} App/Demo#run().`, range: [12, 15, 12, 18], symbol_roles: 0 },
    ]);
    await withTmpScip(bytes, (p) => loadScip(store, p, PHP_OPTS));

    const refs = edges.filter((e) => e.kind === "REFERENCES");
    expect(refs.length).toBe(1);
    // src should be go(), dst should be run().
    // (We can't see qns here, but distinct ids prove attribution happened.)
    expect(refs[0]!.src_id).not.toBe(refs[0]!.dst_id);
  });
});

describe("phpRealFile — recover real path from FQN + PSR-4 map", () => {
  const PSR4 = {
    "Drupal\\asset\\": "modules/core/asset/src/",
    "Drupal\\Tests\\asset\\": "modules/core/asset/tests/src/",
    "Drupal\\farm_id_tag\\": "modules/core/id_tag/src/",
  };
  const parse = (raw: string) => parseScipSymbol(raw)!;

  test("class in a sub-namespace maps through the elided /src/ root", () => {
    const sym = parse("scip-php composer x 1 Drupal/asset/Entity/Asset#");
    expect(phpRealFile(sym, PSR4)).toBe("modules/core/asset/src/Entity/Asset.php");
  });

  test("method inherits its class's file", () => {
    const sym = parse("scip-php composer x 1 Drupal/asset/Entity/Asset#getName().");
    expect(phpRealFile(sym, PSR4)).toBe("modules/core/asset/src/Entity/Asset.php");
  });

  test("class at the namespace root (no remainder)", () => {
    const sym = parse("scip-php composer x 1 Drupal/farm_id_tag/FarmIdTagHelper#");
    expect(phpRealFile(sym, PSR4)).toBe("modules/core/id_tag/src/FarmIdTagHelper.php");
  });

  test("longest-prefix wins (Tests\\asset over asset)", () => {
    const sym = parse("scip-php composer x 1 Drupal/Tests/asset/Functional/AssetCRUDTest#");
    expect(phpRealFile(sym, PSR4)).toBe("modules/core/asset/tests/src/Functional/AssetCRUDTest.php");
  });

  test("returns null when no prefix matches (falls back to relative_path)", () => {
    const sym = parse("scip-php composer x 1 Symfony/Component/Foo#");
    expect(phpRealFile(sym, PSR4)).toBeNull();
  });
});
