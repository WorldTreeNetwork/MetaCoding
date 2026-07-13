/**
 * Tests for the ctkr.functor_between MCP handler (§4 / §6 Task 4).
 *
 * Unlike role-equivalent (which reads a real E2E corpus), this builds a small
 * mixed fixture on disk — functors.parquet + functor_edges.parquet +
 * manifest.json — so every branch is exercised deterministically:
 *   - happy path + mapping, min_pair_fidelity + limit/truncation filters;
 *   - direction: "a_to_b" / "b_to_a" / "both";
 *   - all §4 error / semantic modes: multiple configs, fails-filter,
 *     unknown repo, missing artifact, env unset, staleness;
 *   - min_fidelity=1.0 returns only strict functors from the mixed set.
 */

import { afterAll, afterEach, beforeAll, beforeEach, describe, expect, test } from "bun:test";
import { mkdtemp, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DuckDBInstance } from "@duckdb/node-api";
import { functorBetween } from "./ctkr-tools.ts";

// Column specs mirror FUNCTORS_COLSPEC / FUNCTOR_EDGES_COLSPEC in functorRunner.ts.
const FUNCTORS_COLSPEC: [string, string][] = [
  ["functor_id", "VARCHAR"],
  ["repo_src", "VARCHAR"],
  ["repo_dst", "VARCHAR"],
  ["n_objects_src", "INTEGER"],
  ["n_mapped", "INTEGER"],
  ["coverage", "FLOAT"],
  ["fidelity", "FLOAT"],
  ["n_edges_internal", "INTEGER"],
  ["n_edges_preserved", "INTEGER"],
  ["path_fidelity_2", "FLOAT"],
  ["cycle_consistency", "FLOAT"],
  ["config", "VARCHAR"],
  ["generated_at", "VARCHAR"],
  ["schema_version", "INTEGER"],
];

const FUNCTOR_EDGES_COLSPEC: [string, string][] = [
  ["functor_id", "VARCHAR"],
  ["src_symbol_id", "VARCHAR"],
  ["src_repo", "VARCHAR"],
  ["src_qualified_name", "VARCHAR"],
  ["dst_symbol_id", "VARCHAR"],
  ["dst_repo", "VARCHAR"],
  ["dst_qualified_name", "VARCHAR"],
  ["similarity", "FLOAT"],
  ["margin", "FLOAT"],
  ["pair_fidelity", "FLOAT"],
  ["n_edges_incident", "INTEGER"],
  ["n_edges_preserved", "INTEGER"],
  ["schema_version", "INTEGER"],
];

const MANIFEST_GEN = "2026-07-14T00:00:00Z";
const OLD_GEN = "2026-01-01T00:00:00Z";

const cfg = (stamp: string): string =>
  JSON.stringify({ alpha: 0.3, extraction: "greedy", hom_profiles_generated_at: stamp });

// Mixed functor set across repos alpha / beta / gamma.
//   F1 alpha→beta  strict     cov .90 fid 1.00   (chosen over F2)
//   F2 alpha→beta  partial    cov .95 fid 0.80   (alternative config)
//   F3 beta→alpha  partial    cov .80 fid 0.70   (reverse-direction row)
//   F4 alpha→gamma partial    cov .60 fid 0.50   (fails min_fidelity=1.0)
//   F5 gamma→beta  strict/STALE cov .70 fid 1.00 (older hom-profile stamp)
const FUNCTORS: Record<string, unknown>[] = [
  {
    functor_id: "f:strict_ab", repo_src: "alpha", repo_dst: "beta",
    n_objects_src: 10, n_mapped: 9, coverage: 0.9, fidelity: 1.0,
    n_edges_internal: 8, n_edges_preserved: 8, path_fidelity_2: -1,
    cycle_consistency: 0.95, config: cfg(MANIFEST_GEN), generated_at: MANIFEST_GEN, schema_version: 1,
  },
  {
    functor_id: "f:alt_ab", repo_src: "alpha", repo_dst: "beta",
    n_objects_src: 10, n_mapped: 10, coverage: 0.95, fidelity: 0.8,
    n_edges_internal: 10, n_edges_preserved: 8, path_fidelity_2: -1,
    cycle_consistency: 0.5, config: cfg(MANIFEST_GEN), generated_at: MANIFEST_GEN, schema_version: 1,
  },
  {
    functor_id: "f:rev_ba", repo_src: "beta", repo_dst: "alpha",
    n_objects_src: 12, n_mapped: 9, coverage: 0.8, fidelity: 0.7,
    n_edges_internal: 10, n_edges_preserved: 7, path_fidelity_2: -1,
    cycle_consistency: 0.6, config: cfg(MANIFEST_GEN), generated_at: MANIFEST_GEN, schema_version: 1,
  },
  {
    functor_id: "f:partial_ag", repo_src: "alpha", repo_dst: "gamma",
    n_objects_src: 10, n_mapped: 6, coverage: 0.6, fidelity: 0.5,
    n_edges_internal: 6, n_edges_preserved: 3, path_fidelity_2: -1,
    cycle_consistency: 0.3, config: cfg(MANIFEST_GEN), generated_at: MANIFEST_GEN, schema_version: 1,
  },
  {
    functor_id: "f:stale_gb", repo_src: "gamma", repo_dst: "beta",
    n_objects_src: 8, n_mapped: 6, coverage: 0.7, fidelity: 1.0,
    n_edges_internal: 5, n_edges_preserved: 5, path_fidelity_2: -1,
    cycle_consistency: 0.9, config: cfg(OLD_GEN), generated_at: OLD_GEN, schema_version: 1,
  },
];

// F1 mapping — 4 rows with a spread of pair_fidelity incl. a −1 no-evidence row.
const EDGES: Record<string, unknown>[] = [
  {
    functor_id: "f:strict_ab", src_symbol_id: "a1", src_repo: "alpha", src_qualified_name: "alpha.A1",
    dst_symbol_id: "b1", dst_repo: "beta", dst_qualified_name: "beta.B1",
    similarity: 0.99, margin: 0.5, pair_fidelity: 1.0, n_edges_incident: 4, n_edges_preserved: 4, schema_version: 1,
  },
  {
    functor_id: "f:strict_ab", src_symbol_id: "a2", src_repo: "alpha", src_qualified_name: "alpha.A2",
    dst_symbol_id: "b2", dst_repo: "beta", dst_qualified_name: "beta.B2",
    similarity: 0.90, margin: 0.2, pair_fidelity: 0.5, n_edges_incident: 2, n_edges_preserved: 1, schema_version: 1,
  },
  {
    functor_id: "f:strict_ab", src_symbol_id: "a3", src_repo: "alpha", src_qualified_name: "alpha.A3",
    dst_symbol_id: "b3", dst_repo: "beta", dst_qualified_name: "beta.B3",
    similarity: 0.80, margin: 0.01, pair_fidelity: 0.0, n_edges_incident: 3, n_edges_preserved: 0, schema_version: 1,
  },
  {
    functor_id: "f:strict_ab", src_symbol_id: "a4", src_repo: "alpha", src_qualified_name: "alpha.A4",
    dst_symbol_id: "b4", dst_repo: "beta", dst_qualified_name: "beta.B4",
    similarity: 0.70, margin: 1.0, pair_fidelity: -1, n_edges_incident: 0, n_edges_preserved: 0, schema_version: 1,
  },
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

async function buildFixture(dir: string): Promise<void> {
  const ctkr = join(dir, "ctkr");
  await mkdir(ctkr, { recursive: true });
  await writeParquet(join(ctkr, "functors.parquet"), FUNCTORS_COLSPEC, FUNCTORS);
  await writeParquet(join(ctkr, "functor_edges.parquet"), FUNCTOR_EDGES_COLSPEC, EDGES);
  await Bun.write(
    join(ctkr, "manifest.json"),
    JSON.stringify(
      {
        schema_version: 1,
        generated_at: MANIFEST_GEN,
        metacoding_data_dir: dir,
        hom_profiles: true,
        profile_depth: 2,
        functors: true,
        functor_edges: true,
        n_functors: FUNCTORS.length,
        n_functor_edges: EDGES.length,
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
  dataDir = await mkdtemp(join(tmpdir(), "functor-between-"));
  await buildFixture(dataDir);
  process.env["METACODING_CTKR_DATA_DIR"] = dataDir;
});

afterAll(async () => {
  if (originalEnv === undefined) delete process.env["METACODING_CTKR_DATA_DIR"];
  else process.env["METACODING_CTKR_DATA_DIR"] = originalEnv;
  await rm(dataDir, { recursive: true, force: true });
});

describe("functorBetween", () => {
  test("happy path: returns the best functor + full mapping for a_to_b", async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "beta" });
    expect(res.functor).not.toBeNull();
    // best by coverage×fidelity: strict (0.9) beats alt (0.76)
    expect(res.functor!.functor_id).toBe("f:strict_ab");
    expect(res.functor!.fidelity).toBeCloseTo(1.0, 5);
    expect(res.functor!.coverage).toBeCloseTo(0.9, 5);
    expect(res.functor!.repo_src).toBe("alpha");
    expect(res.functor!.repo_dst).toBe("beta");
    // path_fidelity_2 is −1 (not computed) → omitted
    expect(res.functor!.path_fidelity_2).toBeUndefined();
    // reverse only for direction:"both"
    expect(res.reverse).toBeUndefined();
    // mapping: 4 rows, sorted pair_fidelity desc, −1 → null and sorts last
    expect(res.mapping.length).toBe(4);
    expect(res.mapping[0]!.pair_fidelity).toBeCloseTo(1.0, 5);
    expect(res.mapping[res.mapping.length - 1]!.src_symbol_id).toBe("a4");
    expect(res.mapping[res.mapping.length - 1]!.pair_fidelity).toBeNull();
    expect(res.truncated).toBe(false);
    // exactly one alternative config note
    expect(res._note).toContain("1 alternative config");
  });

  test("mapping rows expose margin and denormalized names", async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "beta" });
    const top = res.mapping[0]!;
    expect(top.src_symbol_id).toBe("a1");
    expect(top.src_qualified_name).toBe("alpha.A1");
    expect(top.dst_qualified_name).toBe("beta.B1");
    expect(typeof top.margin).toBe("number");
    expect(typeof top.similarity).toBe("number");
  });

  test("min_pair_fidelity filters mapping rows (drops no-evidence + low pairs)", async () => {
    const res = await functorBetween({
      repo_a: "alpha", repo_b: "beta", min_pair_fidelity: 0.6,
    });
    expect(res.mapping.length).toBe(1);
    expect(res.mapping[0]!.src_symbol_id).toBe("a1");
    expect(res.mapping.every((m) => m.pair_fidelity !== null && m.pair_fidelity >= 0.6)).toBe(true);
  });

  test("limit truncates mapping rows and sets truncated", async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "beta", limit: 2 });
    expect(res.mapping.length).toBe(2);
    expect(res.truncated).toBe(true);
    // still the top-2 by pair_fidelity
    expect(res.mapping[0]!.src_symbol_id).toBe("a1");
    expect(res.mapping[1]!.src_symbol_id).toBe("a2");
  });

  test("direction b_to_a returns the reverse-stored functor as primary", async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "beta", direction: "b_to_a" });
    expect(res.functor).not.toBeNull();
    expect(res.functor!.functor_id).toBe("f:rev_ba");
    expect(res.functor!.repo_src).toBe("beta");
    expect(res.functor!.repo_dst).toBe("alpha");
    expect(res.reverse).toBeUndefined();
  });

  test('direction "both" adds the reverse summary', async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "beta", direction: "both" });
    expect(res.functor!.functor_id).toBe("f:strict_ab"); // primary a→b
    expect(res.reverse).not.toBeNull();
    expect(res.reverse!.functor_id).toBe("f:rev_ba"); // reverse b→a
    // primary mapping only
    expect(res.mapping.length).toBe(4);
  });

  test('direction "both" reports null reverse when the reverse pair is absent', async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "gamma", direction: "both" });
    expect(res.functor!.functor_id).toBe("f:partial_ag");
    expect(res.reverse).toBeNull();
    expect(res._note).toContain("no reverse functor gamma→alpha");
  });

  // --- §4 semantics & error modes ---

  test("min_fidelity=1.0 returns only strict functors from the mixed fixture", async () => {
    // alpha→beta has a strict config → returned.
    const strict = await functorBetween({ repo_a: "alpha", repo_b: "beta", min_fidelity: 1.0 });
    expect(strict.functor).not.toBeNull();
    expect(strict.functor!.fidelity).toBe(1.0);
    // the alternative (0.8) is filtered out → no alternative-config note.
    expect(strict._note ?? "").not.toContain("alternative config");

    // alpha→gamma's best fidelity is 0.5 → no strict functor → functor:null.
    const partial = await functorBetween({ repo_a: "alpha", repo_b: "gamma", min_fidelity: 1.0 });
    expect(partial.functor).toBeNull();
    expect(partial._note).toContain("best available");
    expect(partial._note).toContain("fidelity=0.50");
  });

  test("pair present but below min_coverage → functor:null with best-available note", async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "gamma", min_coverage: 0.95 });
    expect(res.functor).toBeNull();
    expect(res.mapping).toEqual([]);
    expect(res._note).toContain("min_coverage=0.95");
    expect(res._note).toContain("coverage=0.60");
  });

  test("multiple configs: returns max coverage×fidelity, notes the alternative count", async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "beta" });
    expect(res.functor!.functor_id).toBe("f:strict_ab");
    expect(res._note).toContain("1 alternative config");
  });

  test("unknown repo → functor:null listing available repos", async () => {
    const res = await functorBetween({ repo_a: "nope", repo_b: "beta" });
    expect(res.functor).toBeNull();
    expect(res._note).toContain("unknown repo");
    expect(res._note).toContain("nope");
    expect(res._note).toContain("available repos");
    expect(res._note).toContain("alpha");
  });

  test("known repos but ordered pair never discovered → explanatory note", async () => {
    // beta→gamma is absent, but both repos appear elsewhere.
    const res = await functorBetween({ repo_a: "beta", repo_b: "gamma" });
    expect(res.functor).toBeNull();
    expect(res._note).toContain("no functor computed for beta→gamma");
  });

  test("staleness: older hom-profile stamp is flagged in _note", async () => {
    const res = await functorBetween({ repo_a: "gamma", repo_b: "beta" });
    expect(res.functor!.functor_id).toBe("f:stale_gb");
    expect(res._note).toContain("older hom-profile generation");
  });

  test("non-stale functor carries no staleness note", async () => {
    const res = await functorBetween({ repo_a: "alpha", repo_b: "beta" });
    expect(res._note ?? "").not.toContain("older hom-profile generation");
  });
});

describe("functorBetween error modes (isolated env)", () => {
  test("METACODING_CTKR_DATA_DIR unset → throws", async () => {
    const saved = process.env["METACODING_CTKR_DATA_DIR"];
    delete process.env["METACODING_CTKR_DATA_DIR"];
    try {
      await expect(functorBetween({ repo_a: "alpha", repo_b: "beta" })).rejects.toThrow(
        /METACODING_CTKR_DATA_DIR/,
      );
    } finally {
      process.env["METACODING_CTKR_DATA_DIR"] = saved;
    }
  });

  describe("missing functor artifacts", () => {
    let emptyDir: string;
    let saved: string | undefined;

    beforeEach(async () => {
      saved = process.env["METACODING_CTKR_DATA_DIR"];
      emptyDir = await mkdtemp(join(tmpdir(), "functor-between-empty-"));
      const ctkr = join(emptyDir, "ctkr");
      await mkdir(ctkr, { recursive: true });
      await Bun.write(
        join(ctkr, "manifest.json"),
        JSON.stringify({ schema_version: 1, generated_at: MANIFEST_GEN, functors: false }, null, 2) + "\n",
      );
      process.env["METACODING_CTKR_DATA_DIR"] = emptyDir;
    });

    afterEach(async () => {
      if (saved === undefined) delete process.env["METACODING_CTKR_DATA_DIR"];
      else process.env["METACODING_CTKR_DATA_DIR"] = saved;
      await rm(emptyDir, { recursive: true, force: true });
    });

    test("functors.parquet absent → throws the runner-specific message", async () => {
      await expect(functorBetween({ repo_a: "alpha", repo_b: "beta" })).rejects.toThrow(
        /functor artifacts not found in .* — run the functor discovery runner first/,
      );
    });
  });
});
