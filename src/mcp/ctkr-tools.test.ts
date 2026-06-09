/**
 * Tests for src/mcp/ctkr-tools.ts — CTKR Phase 1 MCP tool handlers.
 *
 * Uses $ORCHESTRATORS_ROOT/.metacoding/ as test data when present (falling
 * back to ~/projects/Orchestrators/.metacoding/ for backwards-compat).
 * Tests skip with a clear message if the directory is absent.
 */

import { expect, test, describe } from "bun:test";
import { join } from "node:path";
import {
  motifSearch,
  nearestSymbols,
  patternSearch,
  shapeDistance,
  centralityQuery,
} from "./ctkr-tools.ts";

const ORCHESTRATORS_ROOT =
  process.env["ORCHESTRATORS_ROOT"] ??
  join(process.env["HOME"] ?? "/home/dorje", "projects/Orchestrators");
const TEST_DATA_DIR = join(ORCHESTRATORS_ROOT, ".metacoding");

const dataAvailable = await Bun.file(
  join(TEST_DATA_DIR, "ctkr/manifest.json"),
).exists();

// Set the env var so handlers pick up the test corpus.
process.env["METACODING_CTKR_DATA_DIR"] = TEST_DATA_DIR;

// A repo known to exist in the corpus (verified from centrality + wasserstein).
const SAMPLE_REPO = "crewAI";

// ---------------------------------------------------------------------------
// Skip helper
// ---------------------------------------------------------------------------
function maybeSkip(name: string, fn: () => Promise<void>): void {
  test(name, async () => {
    if (!dataAvailable) {
      console.log(
        `SKIP: ${name} — test data not found at ${TEST_DATA_DIR}. ` +
          `Run ctkr commands against Orchestrators to generate artifacts.`,
      );
      return;
    }
    await fn();
  });
}

// ---------------------------------------------------------------------------
// ctkr.motif_search
// ---------------------------------------------------------------------------
describe("motifSearch", () => {
  maybeSkip("returns rows with support >= min_support", async () => {
    const rows = await motifSearch({ min_support: 5, limit: 20 });
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.support).toBeGreaterThanOrEqual(5);
      expect(typeof row.motif_id).toBe("string");
      expect(typeof row.signature).toBe("string");
      expect(Array.isArray(row.repo_coverage)).toBe(true);
      expect(Array.isArray(row.edge_kinds)).toBe(true);
    }
  });

  maybeSkip("results are sorted by support descending", async () => {
    const rows = await motifSearch({ limit: 20 });
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i]!.support).toBeLessThanOrEqual(rows[i - 1]!.support);
    }
  });

  maybeSkip("limit is respected", async () => {
    const rows = await motifSearch({ limit: 3 });
    expect(rows.length).toBeLessThanOrEqual(3);
  });

  maybeSkip("label filter returns only matching labels (or empty)", async () => {
    // We don't know the labels ahead of time, but we can assert that
    // any returned rows have a label containing the needle.
    const needle = "factory";
    const rows = await motifSearch({ label: needle });
    for (const row of rows) {
      expect(row.label?.toLowerCase()).toContain(needle.toLowerCase());
    }
  });

  maybeSkip("edge_kinds filter works", async () => {
    const rows = await motifSearch({ edge_kinds: ["CALLS"], limit: 10 });
    for (const row of rows) {
      // Edge kinds in the row should contain at least one CALLS.
      // (The filter is list_has_any — row.edge_kinds is the motif's edge_kinds array.)
      expect(row.edge_kinds).toContain("CALLS");
    }
  });
});

// ---------------------------------------------------------------------------
// ctkr.nearest_symbols
// ---------------------------------------------------------------------------
describe("nearestSymbols", () => {
  maybeSkip("returns k rows by qualified_name", async () => {
    // Grab a real qualified_name from the corpus via motifs -> no, use
    // a well-known symbol. We resolve one from the embeddings via
    // motifSearch first to get a real symbol_id.
    // Strategy: use the first embedding we can find via motifSearch's side data.
    // Simpler: import openCtkrArtifacts directly and pick a symbol_id.
    const { openCtkrArtifacts } = await import("../ctkr/artifacts.ts");
    const h = await openCtkrArtifacts(TEST_DATA_DIR);
    const cents = await h.centrality({ repo: SAMPLE_REPO, topK: 1, metric: "pagerank" });
    await h.close();
    expect(cents.length).toBeGreaterThan(0);
    const seed = cents[0]!;

    const rows = await nearestSymbols({ symbol_id: seed.symbol_id, k: 5 });
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThanOrEqual(5);
    for (const row of rows) {
      expect(typeof row.symbol_id).toBe("string");
      expect(typeof row.qualified_name).toBe("string");
      expect(typeof row.repo).toBe("string");
      expect(typeof row.distance).toBe("number");
      expect(row.distance).toBeGreaterThanOrEqual(0);
      expect(row.distance).toBeLessThanOrEqual(2); // cosine distance in [0, 2]
    }
    // Sorted ascending (closest first).
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i]!.distance).toBeGreaterThanOrEqual(rows[i - 1]!.distance);
    }
  });

  maybeSkip("cross_repo_only excludes same-repo results", async () => {
    const { openCtkrArtifacts } = await import("../ctkr/artifacts.ts");
    const h = await openCtkrArtifacts(TEST_DATA_DIR);
    const cents = await h.centrality({ repo: SAMPLE_REPO, topK: 1, metric: "pagerank" });
    await h.close();
    if (cents.length === 0) return;
    const seed = cents[0]!;

    const rows = await nearestSymbols({
      symbol_id: seed.symbol_id,
      k: 10,
      cross_repo_only: true,
    });
    for (const row of rows) {
      expect(row.repo).not.toBe(SAMPLE_REPO);
    }
  });

  maybeSkip("throws if neither symbol_id nor qualified_name given", async () => {
    await expect(nearestSymbols({})).rejects.toThrow();
  });

  maybeSkip("returns empty for unknown symbol_id", async () => {
    const rows = await nearestSymbols({ symbol_id: "DOES_NOT_EXIST_XYZ" });
    expect(rows).toEqual([]);
  });
});

// ---------------------------------------------------------------------------
// ctkr.pattern_search
// ---------------------------------------------------------------------------
describe("patternSearch", () => {
  maybeSkip("returns rows with evidence arrays", async () => {
    const rows = await patternSearch({ limit: 5 });
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(typeof row.pattern_id).toBe("string");
      expect(typeof row.label).toBe("string");
      expect(typeof row.confidence).toBe("number");
      expect(row.confidence).toBeGreaterThanOrEqual(0);
      expect(row.confidence).toBeLessThanOrEqual(1);
      expect(Array.isArray(row.evidence)).toBe(true);
    }
  });

  maybeSkip("min_confidence filter holds", async () => {
    const rows = await patternSearch({ min_confidence: 0.5, limit: 20 });
    for (const row of rows) {
      expect(row.confidence).toBeGreaterThanOrEqual(0.5);
    }
  });

  maybeSkip("source_kind filter works", async () => {
    const rows = await patternSearch({ source_kind: "motif", limit: 10 });
    for (const row of rows) {
      expect(row.source_kind).toBe("motif");
    }
  });

  maybeSkip("instances_in_repo filter returns patterns with evidence in repo", async () => {
    const rows = await patternSearch({
      instances_in_repo: SAMPLE_REPO,
      limit: 5,
    });
    for (const row of rows) {
      const reposInEvidence = row.evidence.map((e) => e.repo);
      expect(reposInEvidence).toContain(SAMPLE_REPO);
    }
  });
});

// ---------------------------------------------------------------------------
// ctkr.shape_distance
// ---------------------------------------------------------------------------
describe("shapeDistance", () => {
  maybeSkip("point query returns a single distance object", async () => {
    // Find two repos that have entries in wasserstein_h1 via the handle.
    const { openCtkrArtifacts } = await import("../ctkr/artifacts.ts");
    const h = await openCtkrArtifacts(TEST_DATA_DIR);
    const rows = await h.wassersteinH1({ repoA: SAMPLE_REPO });
    await h.close();
    if (rows.length === 0) {
      console.log("SKIP shape_distance point query — no rows for SAMPLE_REPO");
      return;
    }
    const other = rows[0]!.repo_a === SAMPLE_REPO ? rows[0]!.repo_b : rows[0]!.repo_a;

    const result = await shapeDistance({ repo_a: SAMPLE_REPO, repo_b: other });
    expect(typeof (result as { distance: number }).distance).toBe("number");
    expect((result as { distance: number }).distance).toBeGreaterThanOrEqual(0);
  });

  maybeSkip("k_nearest returns array sorted ascending", async () => {
    const result = await shapeDistance({ repo_a: SAMPLE_REPO, k_nearest: 5 });
    expect(Array.isArray(result)).toBe(true);
    const arr = result as Array<{ repo_a: string; repo_b: string; distance: number }>;
    expect(arr.length).toBeLessThanOrEqual(5);
    for (const row of arr) {
      expect(row.repo_a).toBe(SAMPLE_REPO);
      expect(typeof row.repo_b).toBe("string");
      expect(typeof row.distance).toBe("number");
    }
    // Sorted ascending.
    for (let i = 1; i < arr.length; i++) {
      expect(arr[i]!.distance).toBeGreaterThanOrEqual(arr[i - 1]!.distance);
    }
  });

  maybeSkip("unknown pair returns distance null", async () => {
    const result = await shapeDistance({
      repo_a: SAMPLE_REPO,
      repo_b: "REPO_THAT_DOES_NOT_EXIST_IN_CORPUS",
    });
    expect((result as { distance: number | null }).distance).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// ctkr.centrality_query
// ---------------------------------------------------------------------------
describe("centralityQuery", () => {
  maybeSkip("returns rows sorted by pagerank desc", async () => {
    const rows = await centralityQuery({
      repo: SAMPLE_REPO,
      metric: "pagerank",
      top_k: 10,
    });
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(typeof row.symbol_id).toBe("string");
      expect(typeof row.qualified_name).toBe("string");
      expect(typeof row.score).toBe("number");
      expect(row.score).toBeGreaterThanOrEqual(0);
    }
    // Descending sort.
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i]!.score).toBeLessThanOrEqual(rows[i - 1]!.score);
    }
  });

  maybeSkip("betweenness metric sorts correctly", async () => {
    const rows = await centralityQuery({ metric: "betweenness", top_k: 5 });
    expect(rows.length).toBeLessThanOrEqual(5);
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i]!.score).toBeLessThanOrEqual(rows[i - 1]!.score);
    }
  });

  maybeSkip("eigenvector metric sorts correctly", async () => {
    const rows = await centralityQuery({ metric: "eigenvector", top_k: 5 });
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i]!.score).toBeLessThanOrEqual(rows[i - 1]!.score);
    }
  });

  maybeSkip("cluster fields present when spectral_clusters exist", async () => {
    const rows = await centralityQuery({
      repo: SAMPLE_REPO,
      metric: "pagerank",
      top_k: 20,
    });
    // At least some rows should have cluster_id (spectral_clusters.parquet exists).
    const hasCluster = rows.some((r) => r.cluster_id !== undefined);
    expect(hasCluster).toBe(true);
  });

  maybeSkip("top_k is respected", async () => {
    const rows = await centralityQuery({ metric: "pagerank", top_k: 3 });
    expect(rows.length).toBeLessThanOrEqual(3);
  });
});
