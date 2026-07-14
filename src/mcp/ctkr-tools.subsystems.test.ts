/**
 * Tests for the ctkr.subsystems MCP handler (subsystem-extraction §2.4 / §8.2).
 *
 * Builds a small on-disk fixture — subsystems.parquet + subsystem_members.parquet
 * + manifest.json — so every branch runs deterministically without an external
 * corpus:
 *   - happy path: subsystems returned largest-first with boundary metadata;
 *   - boundary-confidence aggregation (structural vs locality counts, mean);
 *   - boundary_symbols are the lowest-confidence members, capped by sample;
 *   - repo / min_persistence / resolution filters;
 *   - resolution mismatch and empty-repo notes;
 *   - missing artifact + env-unset error modes.
 */

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtemp, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DuckDBInstance } from "@duckdb/node-api";
import { subsystemsQuery } from "./ctkr-tools.ts";

const SUBSYSTEMS_COLSPEC: [string, string][] = [
  ["subsystem_id", "VARCHAR"],
  ["repo", "VARCHAR"],
  ["n_members", "INTEGER"],
  ["resolution", "DOUBLE"],
  ["persistence_score", "DOUBLE"],
  ["config", "VARCHAR"],
  ["generated_at", "VARCHAR"],
  ["schema_version", "INTEGER"],
];

const MEMBERS_COLSPEC: [string, string][] = [
  ["subsystem_id", "VARCHAR"],
  ["symbol_id", "VARCHAR"],
  ["repo", "VARCHAR"],
  ["qualified_name", "VARCHAR"],
  ["boundary_confidence", "DOUBLE"],
  ["placement", "VARCHAR"],
  ["schema_version", "INTEGER"],
];

const GEN = "2026-07-14T00:00:00Z";
const CONFIG = JSON.stringify({ default_resolution: 0.5, seed: 42 });

// Two subsystems in repo "R" (one big, one small) + one in repo "S".
const SUBSYSTEMS: Record<string, unknown>[] = [
  { subsystem_id: "ss:big", repo: "R", n_members: 4, resolution: 0.5, persistence_score: 0.6, config: CONFIG, generated_at: GEN, schema_version: 1 },
  { subsystem_id: "ss:small", repo: "R", n_members: 2, resolution: 0.5, persistence_score: 1.0, config: CONFIG, generated_at: GEN, schema_version: 1 },
  { subsystem_id: "ss:other", repo: "S", n_members: 2, resolution: 0.5, persistence_score: 0.9, config: CONFIG, generated_at: GEN, schema_version: 1 },
];

const MEMBERS: Record<string, unknown>[] = [
  // ss:big — 3 structural + 1 locality; boundary_confidence spread.
  { subsystem_id: "ss:big", symbol_id: "b1", repo: "R", qualified_name: "R.b1", boundary_confidence: 0.95, placement: "structural", schema_version: 1 },
  { subsystem_id: "ss:big", symbol_id: "b2", repo: "R", qualified_name: "R.b2", boundary_confidence: 0.80, placement: "structural", schema_version: 1 },
  { subsystem_id: "ss:big", symbol_id: "b3", repo: "R", qualified_name: "R.b3", boundary_confidence: 0.30, placement: "structural", schema_version: 1 },
  { subsystem_id: "ss:big", symbol_id: "b4", repo: "R", qualified_name: "R.b4", boundary_confidence: 0.10, placement: "locality", schema_version: 1 },
  // ss:small — both interior.
  { subsystem_id: "ss:small", symbol_id: "s1", repo: "R", qualified_name: "R.s1", boundary_confidence: 1.0, placement: "structural", schema_version: 1 },
  { subsystem_id: "ss:small", symbol_id: "s2", repo: "R", qualified_name: "R.s2", boundary_confidence: 1.0, placement: "structural", schema_version: 1 },
  // ss:other in repo S.
  { subsystem_id: "ss:other", symbol_id: "o1", repo: "S", qualified_name: "S.o1", boundary_confidence: 0.9, placement: "structural", schema_version: 1 },
  { subsystem_id: "ss:other", symbol_id: "o2", repo: "S", qualified_name: "S.o2", boundary_confidence: 0.5, placement: "locality", schema_version: 1 },
];

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

async function buildFixture(dir: string, opts?: { subsystems?: boolean }): Promise<void> {
  const ctkr = join(dir, "ctkr");
  await mkdir(ctkr, { recursive: true });
  const present = opts?.subsystems ?? true;
  if (present) {
    await writeParquet(join(ctkr, "subsystems.parquet"), SUBSYSTEMS_COLSPEC, SUBSYSTEMS);
    await writeParquet(join(ctkr, "subsystem_members.parquet"), MEMBERS_COLSPEC, MEMBERS);
  }
  await Bun.write(
    join(ctkr, "manifest.json"),
    JSON.stringify(
      {
        schema_version: 1,
        generated_at: GEN,
        metacoding_data_dir: dir,
        subsystems: present,
        subsystem_members: present,
        n_subsystems: present ? SUBSYSTEMS.length : 0,
      },
      null,
      2,
    ) + "\n",
  );
}

let dataDir: string;
let originalEnv: string | undefined;

beforeAll(async () => {
  originalEnv = process.env["METACODING_CTKR_DATA_DIR"];
  dataDir = await mkdtemp(join(tmpdir(), "subsystems-"));
  await buildFixture(dataDir);
  process.env["METACODING_CTKR_DATA_DIR"] = dataDir;
});

afterAll(async () => {
  if (originalEnv === undefined) delete process.env["METACODING_CTKR_DATA_DIR"];
  else process.env["METACODING_CTKR_DATA_DIR"] = originalEnv;
  await rm(dataDir, { recursive: true, force: true });
});

describe("subsystemsQuery", () => {
  test("returns subsystems largest-first with boundary metadata", async () => {
    const res = await subsystemsQuery({ repo: "R" });
    expect(res.subsystems.map((s) => s.subsystem_id)).toEqual(["ss:big", "ss:small"]);
    const big = res.subsystems[0]!;
    expect(big.n_members).toBe(4);
    expect(big.n_locality).toBe(1);
    expect(big.n_structural).toBe(3);
    // mean of 0.95, 0.80, 0.30, 0.10 = 0.5375
    expect(big.mean_boundary_confidence).toBeCloseTo(0.5375, 4);
    expect(res.config).toBe(CONFIG);
  });

  test("boundary_symbols are the lowest-confidence members, ascending", async () => {
    const res = await subsystemsQuery({ repo: "R", boundary_sample: 2 });
    const big = res.subsystems.find((s) => s.subsystem_id === "ss:big")!;
    expect(big.boundary_symbols.map((b) => b.symbol_id)).toEqual(["b4", "b3"]);
    expect(big.boundary_symbols[0]!.boundary_confidence).toBe(0.1);
    expect(big.boundary_symbols[0]!.placement).toBe("locality");
  });

  test("min_persistence filters subsystems by persistence_score", async () => {
    const res = await subsystemsQuery({ repo: "R", min_persistence: 0.9 });
    expect(res.subsystems.map((s) => s.subsystem_id)).toEqual(["ss:small"]);
  });

  test("repo filter scopes to one repo", async () => {
    const res = await subsystemsQuery({ repo: "S" });
    expect(res.subsystems).toHaveLength(1);
    expect(res.subsystems[0]!.subsystem_id).toBe("ss:other");
    expect(res.subsystems[0]!.n_locality).toBe(1);
  });

  test("resolution mismatch yields empty + explanatory note", async () => {
    const res = await subsystemsQuery({ repo: "R", resolution: 1.7 });
    expect(res.subsystems).toHaveLength(0);
    expect(res._note).toContain("resolution=1.7");
  });

  test("matching resolution passes through", async () => {
    const res = await subsystemsQuery({ repo: "R", resolution: 0.5 });
    expect(res.subsystems.length).toBe(2);
  });

  test("unknown repo yields empty + note", async () => {
    const res = await subsystemsQuery({ repo: "nope" });
    expect(res.subsystems).toHaveLength(0);
    expect(res._note).toContain("nope");
  });
});

describe("subsystemsQuery error modes", () => {
  test("missing artifact throws a clear error", async () => {
    const saved = process.env["METACODING_CTKR_DATA_DIR"];
    const emptyDir = await mkdtemp(join(tmpdir(), "subsystems-empty-"));
    await buildFixture(emptyDir, { subsystems: false });
    process.env["METACODING_CTKR_DATA_DIR"] = emptyDir;
    try {
      await expect(subsystemsQuery({ repo: "R" })).rejects.toThrow(/subsystems/);
    } finally {
      if (saved === undefined) delete process.env["METACODING_CTKR_DATA_DIR"];
      else process.env["METACODING_CTKR_DATA_DIR"] = saved;
      await rm(emptyDir, { recursive: true, force: true });
    }
  });

  test("METACODING_CTKR_DATA_DIR unset → throws", async () => {
    const saved = process.env["METACODING_CTKR_DATA_DIR"];
    delete process.env["METACODING_CTKR_DATA_DIR"];
    try {
      await expect(subsystemsQuery({})).rejects.toThrow(/METACODING_CTKR_DATA_DIR/);
    } finally {
      process.env["METACODING_CTKR_DATA_DIR"] = saved;
    }
  });
});
