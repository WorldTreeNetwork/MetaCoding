// THE WRITE PATH — evidence for MetaCoding-9jt and for the bulk load itself.
//
// Structured as CONTRAST PAIRS per docs/design/iteration-methodology.md: each
// property is stated so that a half which SHOULD differ does differ. A suite
// where every half agrees is as blind as one where nothing can fail.
//
// The headline property is stated as a property, not as "attack N must fail":
//
//   A RE-INDEX OF A TREE MUST YIELD THE SAME GRAPH AS A FRESH INDEX OF THAT
//   SAME TREE.
//
// That subsumes 9jt's specific two lost edges, and it subsumes the whole family
// of "some other file's derived edge did not survive" defects the old
// skip + DETACH DELETE path could produce — including ones nobody has found yet.

import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "./index.ts";
import { GraphBuild } from "./build.ts";
import { EDGE_KIND_VALUES, type Symbol } from "./types.ts";
import { runIndexSession, type IndexIntent } from "../ingest/session.ts";

const BRANCH = "main";

let dataDir: string;
let repoDir: string;
let store: Store;

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "build-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "build-repo-"));
  store = await Store.open(dataDir);
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

function intent(repo: string, overrides: Partial<IndexIntent> = {}): IndexIntent {
  return {
    repo,
    branch: BRANCH,
    targetPath: repoDir,
    commitSha: "a".repeat(40),
    runStamp: new Date().toISOString(),
    wantScip: false,
    ...overrides,
  };
}

/** Every relational edge in a store, as a sorted, comparable list of strings. */
async function edgeList(s: Store, repo: string): Promise<string[]> {
  const out: string[] = [];
  for (const kind of EDGE_KIND_VALUES) {
    const rows = await s.query<{ a: string; b: string }>(
      `MATCH (a:Symbol)-[:${kind}]->(b:Symbol)
       WHERE a.repo = $repo
       RETURN a.qualified_name AS a, b.qualified_name AS b`,
      { repo },
    );
    for (const r of rows) out.push(`${kind} ${r.a} -> ${r.b}`);
  }
  return out.sort();
}

/**
 * The MetaCoding-9jt fixture, verbatim from the bead: a.ts owns two edges whose
 * TARGETS live in b.ts and whose resolution is DEFERRED to the end of the walk
 * (CONSTRUCTS and RETURNS_TYPE, both to `Widget`). a.ts is never edited.
 */
function writeFixture(root: string, greeting: string): void {
  mkdirSync(root, { recursive: true });
  writeFileSync(
    join(root, "b.ts"),
    `export class Base { greet(): string { return ${JSON.stringify(greeting)}; } }\n` +
      `export class Widget { render(): string { return "w"; } }\n`,
    "utf-8",
  );
  writeFileSync(
    join(root, "a.ts"),
    `import { Base, Widget } from "./b";\n` +
      `export class Child extends Base {\n` +
      `  makeOne(): Widget { const w = new Widget(); return w; }\n` +
      `}\n`,
    "utf-8",
  );
}

// ---------------------------------------------------------------------------
// MetaCoding-9jt — the P0. Both halves index the SAME final tree; they differ
// only in whether the store had a previous generation in it.
// ---------------------------------------------------------------------------

describe("MetaCoding-9jt — a re-index yields the graph a fresh index yields", () => {
  test("editing ONE file's method body does not destroy ANOTHER file's edges", async () => {
    // HALF A — the incremental shape that shipped the defect: index, edit only
    // b.ts's method BODY (no signature, no name, no new symbol), re-index the
    // same data dir.
    writeFixture(repoDir, "hi");
    const first = await runIndexSession(store, dataDir, intent("fx"));
    expect(first.health.status).toBe("HEALTHY");
    const afterFirst = await edgeList(store, "fx");

    writeFixture(repoDir, "hello there");
    const second = await runIndexSession(store, dataDir, intent("fx"));
    expect(second.health.status).toBe("HEALTHY");
    const incremental = await edgeList(store, "fx");

    // HALF B — a fresh store over the byte-identical final tree. This is the
    // oracle: whatever a never-used data dir produces is what the graph is.
    const freshDir = mkdtempSync(join(tmpdir(), "build-fresh-"));
    const freshStore = await Store.open(freshDir);
    let fresh: string[];
    try {
      const r = await runIndexSession(freshStore, freshDir, intent("fx"));
      expect(r.health.status).toBe("HEALTHY");
      fresh = await edgeList(freshStore, "fx");
    } finally {
      await freshStore.close();
      rmSync(freshDir, { recursive: true, force: true });
    }

    // THE PROPERTY.
    expect(incremental).toEqual(fresh);

    // AND THE DISCRIMINATING DETAIL, named so a future regression is legible
    // rather than just "some count moved". These are the exact two edges the
    // bead measured as lost: owned by a.ts, which was never touched, pointing
    // at b.ts, which was.
    expect(incremental).toContain("CONSTRUCTS a.ts::Child::makeOne -> b.ts::Widget");
    expect(incremental).toContain("RETURNS_TYPE a.ts::Child::makeOne -> b.ts::Widget");

    // The fixture must actually be sensitive: if a.ts's deferred edges were not
    // in the first generation either, the halves could agree for the wrong
    // reason and this test would pass over a totally broken extractor.
    expect(afterFirst).toEqual(fresh);
    expect(afterFirst.length).toBeGreaterThan(0);
  }, 120_000);

  test("a DELETED file leaves no orphan symbols behind", async () => {
    // The mirror of the above: the rebuild must SHRINK as well as grow. A
    // build that only ever added would pass every test above.
    writeFixture(repoDir, "hi");
    await runIndexSession(store, dataDir, intent("fx"));
    const before = await edgeList(store, "fx");
    expect(before.some((e) => e.includes("a.ts"))).toBe(true);

    rmSync(join(repoDir, "a.ts"));
    await runIndexSession(store, dataDir, intent("fx"));
    const after = await edgeList(store, "fx");
    expect(after.some((e) => e.includes("a.ts"))).toBe(false);

    const orphans = await store.query<{ c: number | bigint }>(
      `MATCH (s:Symbol) WHERE s.repo = 'fx' AND s.file = 'a.ts' RETURN count(s) AS c`,
    );
    expect(Number(orphans[0]!.c)).toBe(0);
  }, 120_000);
});

// ---------------------------------------------------------------------------
// THE BULK LOAD ITSELF. A COPY through CSV is a new failure surface that the
// row-at-a-time MERGE did not have: escaping, NULL vs "", and endpoints.
// ---------------------------------------------------------------------------

describe("the CSV bulk load round-trips what a MERGE would have written", () => {
  function sym(over: Partial<Symbol> & { id: string }): Symbol {
    return {
      kind: "function", language: "ts", repo: "csv",
      qualified_name: over.id, short_name: over.id,
      file: "x.ts", line: 1, col: 0, end_line: 1, end_col: 1,
      signature: null, visibility: null, is_abstract: false, is_static: false,
      ast_hash: null, branch: BRANCH, source: "tree_sitter",
      ...over,
    };
  }

  test("commas, quotes, newlines, backslashes and non-ASCII survive verbatim", async () => {
    const nasty: Record<string, string> = {
      comma: "fn(a, b): void",
      quote: 'fn(x: "literal"): void',
      newline: "fn(\n  a: number,\n): void",
      crlf: "fn(\r\n): void",
      backslash: 'path\\to\\thing and \\" together',
      unicode: "λ ✓ 中文\ttab",
      empty: "",
    };
    const build = new GraphBuild(dataDir, { repo: "csv", branch: BRANCH });
    for (const [id, signature] of Object.entries(nasty)) {
      await build.upsertSymbol(sym({ id, signature }));
    }
    const stats = await build.flush(store);
    expect(stats.symbols).toBe(Object.keys(nasty).length);

    for (const [id, signature] of Object.entries(nasty)) {
      const rows = await store.query<{ s: string | null }>(
        `MATCH (n:Symbol {id: $id}) RETURN n.signature AS s`,
        { id },
      );
      // "" is the one value CSV cannot carry: it reads back as NULL, and
      // `signature` is a nullable column so it is left that way deliberately.
      // Every other byte must survive exactly.
      expect(rows[0]!.s).toBe(signature === "" ? null : signature);
    }
  });

  test("a NEVER-NULL string column keeps its empty string; a nullable one does not", async () => {
    // Boundary nodes (src/extractor/walker.ts, ensureBoundaryNode) carry
    // `file: ""` and `branch: ""`, and code queries on `branch = ''`. If CSV's
    // NULL-for-empty leaked into those columns, every boundary node would fall
    // out of every branch-scoped query. The contrast is the point: the SAME
    // empty string is restored in one column and left NULL in the other.
    const build = new GraphBuild(dataDir, { repo: "csv", branch: BRANCH });
    await build.upsertSymbol(sym({ id: "boundary", file: "", branch: "", signature: "" }));
    await build.flush(store);

    const rows = await store.query<{ f: string | null; b: string | null; s: string | null }>(
      `MATCH (n:Symbol {id: 'boundary'}) RETURN n.file AS f, n.branch AS b, n.signature AS s`,
    );
    expect(rows[0]!.f).toBe("");     // never-null column: restored
    expect(rows[0]!.b).toBe("");     // never-null column: restored
    expect(rows[0]!.s).toBeNull();   // nullable column: left alone
  });

  test("an edge to a missing endpoint is DROPPED and COUNTED, not silently lost", async () => {
    // The old MATCH-CREATE dropped exactly these edges and reported nothing.
    // COPY cannot even tolerate them — it aborts the whole load — so they must
    // be filtered. The improvement is not the filtering, it is the count.
    const build = new GraphBuild(dataDir, { repo: "csv", branch: BRANCH });
    await build.upsertSymbol(sym({ id: "src" }));
    await build.upsertSymbol(sym({ id: "dst" }));
    await build.addEdge({ kind: "CALLS", src_id: "src", dst_id: "dst" });
    await build.addEdge({ kind: "CALLS", src_id: "src", dst_id: "nowhere" });
    const stats = await build.flush(store);

    expect(stats.edges).toBe(1);
    expect(stats.edgesDropped).toBe(1);   // the fact that used to be invisible
    const rows = await store.query<{ c: number | bigint }>(
      `MATCH (:Symbol)-[r:CALLS]->(:Symbol) RETURN count(r) AS c`,
    );
    expect(Number(rows[0]!.c)).toBe(1);
  });

  test("the SCIP lane's structural fields are preserved in the buffer, as in the graph", async () => {
    // Store.upsertSymbol used COALESCE so SCIP could not clobber the five
    // fields tree-sitter fills in. That merge now happens in memory, and it
    // must behave identically — including the case that makes it non-trivial:
    // `is_abstract: false` is a VALUE, not an absence, and must be preserved.
    const build = new GraphBuild(dataDir, { repo: "csv", branch: BRANCH });
    await build.upsertSymbol(sym({
      id: "m", signature: "from tree-sitter", visibility: "private",
      is_abstract: false, ast_hash: "hash-ts",
    }));
    await build.upsertSymbol(
      sym({ id: "m", kind: "method", signature: null, visibility: null, ast_hash: null }),
      { preserveStructural: true },
    );
    await build.flush(store);

    const rows = await store.query<{
      k: string; s: string | null; v: string | null; h: string | null;
    }>(
      `MATCH (n:Symbol {id: 'm'})
       RETURN n.kind AS k, n.signature AS s, n.visibility AS v, n.ast_hash AS h`,
    );
    expect(rows[0]!.s).toBe("from tree-sitter");   // preserved
    expect(rows[0]!.v).toBe("private");            // preserved
    expect(rows[0]!.h).toBe("hash-ts");            // preserved
    expect(rows[0]!.k).toBe("method");             // SCIP-authoritative: overwritten

    // CONTRAST — without preserveStructural the same second write DOES clobber,
    // which is what makes the assertion above a measurement and not a tautology.
    const build2 = new GraphBuild(dataDir, { repo: "csv2", branch: BRANCH });
    await build2.upsertSymbol(sym({ id: "m2", repo: "csv2", signature: "from tree-sitter" }));
    await build2.upsertSymbol(sym({ id: "m2", repo: "csv2", signature: null }));
    await build2.flush(store);
    const rows2 = await store.query<{ s: string | null }>(
      `MATCH (n:Symbol {id: 'm2'}) RETURN n.signature AS s`,
    );
    expect(rows2[0]!.s).toBeNull();
  });

  test("a flush replaces ONLY its own slice", async () => {
    // The store is genuinely multi-repo — the live farmos-port store holds
    // farmos-src@3fe0ce7 alongside farmos-port@main — so a rebuild that
    // replaced more than its slice would be a data-loss bug strictly worse
    // than the one this module fixes.
    const other = new GraphBuild(dataDir, { repo: "keepme", branch: BRANCH });
    await other.upsertSymbol(sym({ id: "keep-1", repo: "keepme" }));
    await other.flush(store);

    const mine = new GraphBuild(dataDir, { repo: "csv", branch: BRANCH });
    await mine.upsertSymbol(sym({ id: "mine-1" }));
    await mine.flush(store);

    const rows = await store.query<{ c: number | bigint }>(
      `MATCH (s:Symbol) WHERE s.repo = 'keepme' RETURN count(s) AS c`,
    );
    expect(Number(rows[0]!.c)).toBe(1);

    // ...and rebuilding "csv" a second time still leaves "keepme" alone while
    // replacing its own rows rather than duplicating them.
    const again = new GraphBuild(dataDir, { repo: "csv", branch: BRANCH });
    await again.upsertSymbol(sym({ id: "mine-1" }));
    const stats = await again.flush(store);
    expect(stats.symbolsReplaced).toBe(1);
    const csvRows = await store.query<{ c: number | bigint }>(
      `MATCH (s:Symbol) WHERE s.repo = 'csv' RETURN count(s) AS c`,
    );
    expect(Number(csvRows[0]!.c)).toBe(1);
  });
});
