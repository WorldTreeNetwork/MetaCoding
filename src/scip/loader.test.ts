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
import { parseScipSymbol, kindOf } from "./symbol.ts";
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
// Constructor symbol shape verified against real scip-typescript v0.4.0 output:
// the name is backtick-quoted AND angle-bracketed (`<constructor>`) with an
// empty disambiguator (`()`). See the "isConstructorSymbol (real scip shapes)"
// regression tests below for the captured real-world strings.
const SCIP_CTOR     = "scip-typescript npm test-repo HEAD src/ `example.ts`/ MyClass# `<constructor>`().";

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
// Regression: isConstructorSymbol must match REAL scip-typescript / scip-python
// output. The symbol strings below were captured by running the real indexers
// (scip-typescript v0.4.0, scip-python v0.6.6) against a class with an explicit
// constructor / __init__ and decoding the resulting index.scip. See bead
// MetaCoding-gc5 item #8. The earlier fast-path regex required `` `constructor`(+). ``
// which never appears in real output (the real name is `<constructor>` with an
// empty disambiguator), so CONSTRUCTS detection relied entirely on the
// structural class-symbol fallback. These tests pin the real shapes.
// ---------------------------------------------------------------------------
describe("isConstructorSymbol (real scip shapes)", () => {
  // Exact strings emitted by the real indexers (spaces stripped between the
  // file-path namespace and the type descriptor mirror real output; the
  // synthetic SCIP_* constants above keep the space-padded form our parser
  // also tolerates — both round-trip through parseScipSymbol identically).
  const REAL_TS_CTOR =
    "scip-typescript npm ctor-fixture 1.0.0 src/`example.ts`/MyClass#`<constructor>`().";
  const REAL_TS_OVERLOADED_CTOR =
    "scip-typescript npm ctor-fixture 1.0.0 src/`example.ts`/Multi#`<constructor>`().";
  const REAL_PY_INIT =
    "scip-python python py-fixture 1.0.0 example/MyClass#__init__().";
  const REAL_TS_PLAIN_METHOD =
    "scip-typescript npm ctor-fixture 1.0.0 src/`example.ts`/MyClass#getX().";

  // We exercise isConstructorSymbol() through its only consumer (the CONSTRUCTS
  // edge path) since it is module-private. A plain (no read/write role)
  // occurrence of a constructor symbol enclosed by a function definition must
  // produce a CONSTRUCTS edge; a plain occurrence of a non-constructor method
  // must not.
  async function constructsEdgesFor(refSymbol: string): Promise<StubEdge[]> {
    const bytes = buildScipBytes([
      { symbol: SCIP_FN, range: [0, 0, 25, 1], symbol_roles: scip.SymbolRole.Definition },
      { symbol: refSymbol, range: [50, 0, 50, 30], symbol_roles: scip.SymbolRole.Definition },
      {
        symbol: refSymbol,
        range: [10, 2, 10, 20],
        enclosing_range: [0, 0, 25, 1],
        symbol_roles: 0,
      },
    ]);
    const { edges, store } = makeStubStore();
    await withTmpScip(bytes, (p) => loadScip(store, p, OPTS));
    return edges.filter((e) => e.kind === "CONSTRUCTS");
  }

  test("matches real scip-typescript `<constructor>`() symbol", async () => {
    expect((await constructsEdgesFor(REAL_TS_CTOR)).length).toBeGreaterThan(0);
  });

  test("matches real scip-typescript overloaded constructor", async () => {
    expect((await constructsEdgesFor(REAL_TS_OVERLOADED_CTOR)).length).toBeGreaterThan(0);
  });

  test("matches real scip-python __init__() symbol", async () => {
    expect((await constructsEdgesFor(REAL_PY_INIT)).length).toBeGreaterThan(0);
  });

  test("rejects a plain (non-constructor) method symbol", async () => {
    // getX() is a method whose last descriptor is `method`, not `type`, and the
    // name is not a constructor — no CONSTRUCTS edge should be emitted.
    expect((await constructsEdgesFor(REAL_TS_PLAIN_METHOD)).length).toBe(0);
  });
});
