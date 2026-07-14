/**
 * Runner integration tests (MetaCoding §6 Task 3).
 *
 * Builds a tiny isomorphic repo-pair fixture (base ≅ fork, α-renamed) on disk —
 * export/{nodes,edges}.jsonl + hom_profiles.parquet + manifest.json — runs the
 * functor-discovery runner, and asserts the acceptance criteria:
 *   - output round-trips through CtkrHandle with correct types + column order;
 *   - re-running the same config yields identical functor_ids (determinism +
 *     append-idempotent replace);
 *   - manifest booleans/counts are correct;
 *   - null/no-evidence pair_fidelity is stored as the -1 sentinel.
 */

import { test, expect, beforeEach, afterEach } from "bun:test";
import { mkdtemp, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DuckDBInstance } from "@duckdb/node-api";
import { openCtkrArtifacts } from "./artifacts.ts";
import {
  runFunctorDiscovery,
  computeFunctorId,
  stableStringify,
  FUNCTORS_COLUMN_ORDER,
  FUNCTOR_EDGES_COLUMN_ORDER,
} from "./functorRunner.ts";

let dataDir: string;

// base ≅ fork: same structure, α-renamed ids + qualified names.
// symbols: 1=class, 2=method, 3=field, 4=isolated field (no internal edges).
const PROFILES: Record<string, number[]> = {
  b1: [1, 0, 0, 0], b2: [0, 1, 0, 0], b3: [0, 0, 1, 0], b4: [0, 0, 0, 1],
  f1: [1, 0, 0, 0], f2: [0, 1, 0, 0], f3: [0, 0, 1, 0], f4: [0, 0, 0, 1],
};
const KIND: Record<string, string> = {
  b1: "class", b2: "method", b3: "field", b4: "field",
  f1: "class", f2: "method", f3: "field", f4: "field",
};

async function writeParquet(
  outPath: string,
  colspec: [string, string][],
  rows: Record<string, unknown>[],
): Promise<void> {
  const inst = await DuckDBInstance.create(":memory:");
  const conn = await inst.connect();
  const cols = "{" + colspec.map(([n, t]) => `${n}: '${t}'`).join(", ") + "}";
  const nd = outPath + ".src.ndjson";
  await Bun.write(nd, rows.map((r) => JSON.stringify(r)).join("\n") + "\n");
  await conn.run(
    `COPY (SELECT * FROM read_json('${nd}', format='newline_delimited', columns=${cols})) ` +
      `TO '${outPath}' (FORMAT PARQUET)`,
  );
  conn.closeSync();
}

async function buildFixture(dir: string): Promise<void> {
  const ctkr = join(dir, "ctkr");
  const exportDir = join(ctkr, "export");
  await mkdir(exportDir, { recursive: true });

  // nodes.jsonl — carries the symbol kind the block needs.
  const nodes = Object.keys(KIND).map((id) => ({
    id,
    repo: id.startsWith("b") ? "base" : "fork",
    kind: KIND[id],
    qualified_name: `${id.startsWith("b") ? "base" : "fork"}.${id}`,
  }));
  await Bun.write(exportDir + "/nodes.jsonl", nodes.map((n) => JSON.stringify(n)).join("\n") + "\n");

  // edges.jsonl — identical structure in both repos; symbol 4 is isolated.
  const mkEdges = (p: string) => [
    { src_id: `${p}1`, dst_id: `${p}2`, kind: "CONTAINS" },
    { src_id: `${p}1`, dst_id: `${p}3`, kind: "CONTAINS" },
    { src_id: `${p}2`, dst_id: `${p}3`, kind: "READS_FIELD" },
  ];
  const edges = [...mkEdges("b"), ...mkEdges("f")];
  await Bun.write(exportDir + "/edges.jsonl", edges.map((e) => JSON.stringify(e)).join("\n") + "\n");

  // hom_profiles.parquet
  const profileRows = Object.keys(PROFILES).map((id) => ({
    symbol_id: id,
    repo: id.startsWith("b") ? "base" : "fork",
    qualified_name: `${id.startsWith("b") ? "base" : "fork"}.${id}`,
    profile_vec: PROFILES[id],
    schema_version: 1,
  }));
  await writeParquet(
    join(ctkr, "hom_profiles.parquet"),
    [
      ["symbol_id", "VARCHAR"],
      ["repo", "VARCHAR"],
      ["qualified_name", "VARCHAR"],
      ["profile_vec", "DOUBLE[]"],
      ["schema_version", "INTEGER"],
    ],
    profileRows,
  );

  // manifest.json — depth-2 seeds, hom_profiles present.
  await Bun.write(
    join(ctkr, "manifest.json"),
    JSON.stringify(
      {
        schema_version: 1,
        generated_at: "2026-07-13T00:00:00Z",
        metacoding_data_dir: dir,
        hom_profiles: true,
        profile_depth: 2,
        n_hom_profiles: profileRows.length,
      },
      null,
      2,
    ) + "\n",
  );
}

beforeEach(async () => {
  dataDir = await mkdtemp(join(tmpdir(), "functor-runner-"));
  await buildFixture(dataDir);
});

afterEach(async () => {
  await rm(dataDir, { recursive: true, force: true });
});

test("runs discovery and produces both directed functors on the isomorphic pair", async () => {
  const res = await runFunctorDiscovery({ dataDir, pairs: [["base", "fork"]], direction: "both" });
  expect(res.nFunctors).toBe(2);
  expect(res.nFunctorEdges).toBe(8); // 4 mapped objects × 2 directions
  // Perfect isomorphism: full coverage, fidelity, cycle-consistency.
  for (const s of res.summaries) {
    expect(s.coverage).toBeCloseTo(1.0, 5);
    expect(s.fidelity).toBeCloseTo(1.0, 5);
    expect(s.cycleConsistency).toBeCloseTo(1.0, 5);
    expect(s.nMapped).toBe(4);
  }
});

test("output round-trips through CtkrHandle with correct column order + types", async () => {
  await runFunctorDiscovery({ dataDir, pairs: [["base", "fork"]], direction: "both" });
  const h = await openCtkrArtifacts(dataDir);
  try {
    const functors = await h.functors();
    expect(functors.length).toBe(2);
    const ab = functors.find((f) => f.repo_src === "base" && f.repo_dst === "fork")!;
    expect(ab).toBeDefined();
    // types
    expect(typeof ab.functor_id).toBe("string");
    expect(typeof ab.n_objects_src).toBe("number");
    expect(typeof ab.coverage).toBe("number");
    expect(typeof ab.fidelity).toBe("number");
    expect(typeof ab.config).toBe("string");
    expect(ab.n_objects_src).toBe(4);
    expect(ab.n_edges_internal).toBe(3);
    expect(ab.n_edges_preserved).toBe(3);
    // config records the seed profile depth
    expect(JSON.parse(ab.config).profile_depth).toBe(2);
    expect(JSON.parse(ab.config).extraction).toBe("greedy");

    // column order on disk matches the canonical schema tuple
    const inst = await DuckDBInstance.create(":memory:");
    const conn = await inst.connect();
    const r = await conn.runAndReadAll(
      `SELECT * FROM read_parquet('${join(dataDir, "ctkr", "functors.parquet")}') LIMIT 0`,
    );
    expect(r.columnNames()).toEqual(FUNCTORS_COLUMN_ORDER);
    const re = await conn.runAndReadAll(
      `SELECT * FROM read_parquet('${join(dataDir, "ctkr", "functor_edges.parquet")}') LIMIT 0`,
    );
    expect(re.columnNames()).toEqual(FUNCTOR_EDGES_COLUMN_ORDER);
    conn.closeSync();

    const edges = await h.functorEdges(ab.functor_id);
    expect(edges.length).toBe(4);
    for (const e of edges) {
      expect(typeof e.similarity).toBe("number");
      expect(typeof e.margin).toBe("number");
      expect(typeof e.pair_fidelity).toBe("number");
      expect(e.functor_id).toBe(ab.functor_id);
    }
    // the isolated symbol (b4) has no internal incident edges → -1 sentinel
    const isolated = edges.find((e) => e.src_symbol_id === "b4")!;
    expect(isolated).toBeDefined();
    expect(isolated.pair_fidelity).toBe(-1);
    expect(isolated.n_edges_incident).toBe(0);
    // sorted pair_fidelity desc → the -1 row sorts last
    expect(edges[edges.length - 1]!.src_symbol_id).toBe("b4");
  } finally {
    await h.close();
  }
});

test("re-run with same config yields identical functor_id (deterministic + idempotent)", async () => {
  const r1 = await runFunctorDiscovery({ dataDir, pairs: [["base", "fork"]], direction: "both" });
  const r2 = await runFunctorDiscovery({ dataDir, pairs: [["base", "fork"]], direction: "both" });
  expect([...r2.functorIds].sort()).toEqual([...r1.functorIds].sort());
  // idempotent replace — not doubled.
  expect(r2.nFunctors).toBe(2);
  expect(r2.nFunctorEdges).toBe(8);
});

test("manifest booleans + counts are updated", async () => {
  await runFunctorDiscovery({ dataDir, pairs: [["base", "fork"]], direction: "both" });
  const mf = JSON.parse(await Bun.file(join(dataDir, "ctkr", "manifest.json")).text());
  expect(mf.functors).toBe(true);
  expect(mf.functor_edges).toBe(true);
  expect(mf.n_functors).toBe(2);
  expect(mf.n_functor_edges).toBe(8);
  // pre-existing manifest fields survive the merge
  expect(mf.hom_profiles).toBe(true);
  expect(mf.profile_depth).toBe(2);
});

test("functors() pushdown filters apply", async () => {
  await runFunctorDiscovery({ dataDir, pairs: [["base", "fork"]], direction: "both" });
  const h = await openCtkrArtifacts(dataDir);
  try {
    expect((await h.functors({ minFidelity: 1.0 })).length).toBe(2);
    expect((await h.functors({ minFidelity: 1.01 })).length).toBe(0);
    const onlyAB = await h.functors({ repoSrc: "base", repoDst: "fork" });
    expect(onlyAB.length).toBe(1);
    expect(onlyAB[0]!.repo_src).toBe("base");
    // functorEdges minPairFidelity drops the -1 (no-evidence) row.
    const id = onlyAB[0]!.functor_id;
    const withEvidence = await h.functorEdges(id, { minPairFidelity: 0 });
    expect(withEvidence.every((e) => e.pair_fidelity >= 0)).toBe(true);
    expect(withEvidence.length).toBe(3); // b1,b2,b3 have evidence; b4 dropped
  } finally {
    await h.close();
  }
});

test("single-direction run leaves cycle_consistency undefined (-1)", async () => {
  const res = await runFunctorDiscovery({ dataDir, pairs: [["base", "fork"]], direction: "a_to_b" });
  expect(res.nFunctors).toBe(1);
  expect(res.summaries[0]!.cycleConsistency).toBe(-1);
});

// ---------------------------------------------------------------------------
// MetaCoding-4ty — member-set restriction + single-repo endofunctor mode
// ---------------------------------------------------------------------------

test("member-restricted run maps only in-set symbols, with a distinct functor_id", async () => {
  const full = await runFunctorDiscovery({
    dataDir, pairs: [["base", "fork"]], direction: "a_to_b",
  });
  const restricted = await runFunctorDiscovery({
    dataDir, pairs: [["base", "fork"]], direction: "a_to_b",
    members: { base: ["b1", "b2"], fork: ["f1", "f2"] },
  });
  // Restriction changes the correspondence → a different content-addressed id.
  expect(restricted.functorIds[0]).not.toBe(full.functorIds[0]);

  const h = await openCtkrArtifacts(dataDir);
  try {
    const f = (await h.functors()).find((x) => x.functor_id === restricted.functorIds[0])!;
    expect(f).toBeDefined();
    expect(f.n_objects_src).toBe(2); // only b1,b2 in the domain
    // config records the 4ty provenance
    const cfg = JSON.parse(f.config);
    expect(cfg.exclude_identity).toBe(false);
    expect(typeof cfg.src_members_digest).toBe("string");
    expect(cfg.src_members_digest.length).toBeGreaterThan(0);
    const edges = await h.functorEdges(f.functor_id);
    for (const e of edges) {
      expect(["b1", "b2"]).toContain(e.src_symbol_id);
      expect(["f1", "f2"]).toContain(e.dst_symbol_id);
    }
  } finally {
    await h.close();
  }
});

test("single-repo endofunctor finds cross-module map, not the identity", async () => {
  const dir = await mkdtemp(join(tmpdir(), "functor-endo-"));
  try {
    const ctkr = join(dir, "ctkr");
    const exportDir = join(ctkr, "export");
    await mkdir(exportDir, { recursive: true });

    // One repo "mono" with two isomorphic modules X and Y (cross-module twins).
    const KINDS: Record<string, string> = {
      x_c: "class", x_m: "method", x_f: "field",
      y_c: "class", y_m: "method", y_f: "field",
    };
    const VECS: Record<string, number[]> = {
      x_c: [3, 0, 0], x_m: [0, 3, 0], x_f: [0, 0, 3],
      y_c: [3, 0, 0], y_m: [0, 3, 0], y_f: [0, 0, 3],
    };
    const nodes = Object.keys(KINDS).map((id) => ({
      id, repo: "mono", kind: KINDS[id], qualified_name: `mono.${id}`,
    }));
    await Bun.write(exportDir + "/nodes.jsonl", nodes.map((n) => JSON.stringify(n)).join("\n") + "\n");
    const edges = [
      { src_id: "x_c", dst_id: "x_m", kind: "CONTAINS" },
      { src_id: "x_m", dst_id: "x_f", kind: "READS_FIELD" },
      { src_id: "y_c", dst_id: "y_m", kind: "CONTAINS" },
      { src_id: "y_m", dst_id: "y_f", kind: "READS_FIELD" },
    ];
    await Bun.write(exportDir + "/edges.jsonl", edges.map((e) => JSON.stringify(e)).join("\n") + "\n");
    await writeParquet(
      join(ctkr, "hom_profiles.parquet"),
      [
        ["symbol_id", "VARCHAR"], ["repo", "VARCHAR"], ["qualified_name", "VARCHAR"],
        ["profile_vec", "DOUBLE[]"], ["schema_version", "INTEGER"],
      ],
      Object.keys(VECS).map((id) => ({
        symbol_id: id, repo: "mono", qualified_name: `mono.${id}`,
        profile_vec: VECS[id], schema_version: 1,
      })),
    );
    await Bun.write(
      join(ctkr, "manifest.json"),
      JSON.stringify({
        schema_version: 1, generated_at: "2026-07-14T00:00:00Z",
        metacoding_data_dir: dir, hom_profiles: true, profile_depth: 2, n_hom_profiles: 6,
      }, null, 2) + "\n",
    );

    // Self-pair → endofunctor mode auto-enabled (excludeIdentity defaults true).
    const res = await runFunctorDiscovery({
      dataDir: dir, pairs: [["mono", "mono"]], direction: "a_to_b",
    });
    expect(res.summaries[0]!.nMapped).toBe(6);

    const h = await openCtkrArtifacts(dir);
    try {
      const f = (await h.functors())[0]!;
      expect(JSON.parse(f.config).exclude_identity).toBe(true);
      const es = await h.functorEdges(f.functor_id);
      const m = new Map(es.map((e) => [e.src_symbol_id, e.dst_symbol_id]));
      // NOT the identity: every symbol maps to its cross-module twin
      for (const e of es) expect(e.src_symbol_id).not.toBe(e.dst_symbol_id);
      expect(m.get("x_c")).toBe("y_c");
      expect(m.get("x_m")).toBe("y_m");
      expect(m.get("y_f")).toBe("x_f");
    } finally {
      await h.close();
    }
  } finally {
    await rm(dir, { recursive: true, force: true });
  }
});

test("computeFunctorId is stable and mapping-sensitive", () => {
  const cfg = { alpha: 0.3 };
  const m1 = [{ srcId: "a", dstId: "x" }, { srcId: "b", dstId: "y" }];
  const m2 = [{ srcId: "b", dstId: "y" }, { srcId: "a", dstId: "x" }];
  // order-insensitive over the mapping set
  expect(computeFunctorId("A", "B", cfg, m1)).toBe(computeFunctorId("A", "B", cfg, m2));
  // sensitive to mapping content
  const m3 = [{ srcId: "a", dstId: "z" }, { srcId: "b", dstId: "y" }];
  expect(computeFunctorId("A", "B", cfg, m1)).not.toBe(computeFunctorId("A", "B", cfg, m3));
  // sensitive to repo pair
  expect(computeFunctorId("A", "B", cfg, m1)).not.toBe(computeFunctorId("B", "A", cfg, m1));
});

test("stableStringify sorts keys recursively", () => {
  expect(stableStringify({ b: 1, a: { d: 2, c: 3 } })).toBe('{"a":{"c":3,"d":2},"b":1}');
});
