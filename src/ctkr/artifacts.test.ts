/**
 * Tests for src/ctkr/artifacts.ts — CTKR Layer-1 artifact loader.
 *
 * Uses ~/projects/Orchestrators/.metacoding/ as test data if it exists.
 * All tests are skipped with a clear message if the directory is absent.
 */

import { expect, test, describe, beforeAll, afterAll } from "bun:test";
import { join } from "node:path";
import { openCtkrArtifacts, type CtkrHandle } from "./artifacts.ts";

const TEST_DATA_DIR = join(
  process.env["HOME"] ?? "/home/dorje",
  "projects/Orchestrators/.metacoding",
);

// Check once at module load time whether test data is available.
const dataAvailable = await Bun.file(
  join(TEST_DATA_DIR, "ctkr/manifest.json"),
).exists();

// A real repo present in the test data (crewAI is in the centrality parquet).
const SAMPLE_REPO = "crewAI";

// ---------------------------------------------------------------------------
// Skip helper — wraps each test body so it's a no-op when data is absent.
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
// Suite
// ---------------------------------------------------------------------------
describe("CtkrHandle", () => {
  let handle: CtkrHandle;

  beforeAll(async () => {
    if (!dataAvailable) return;
    handle = await openCtkrArtifacts(TEST_DATA_DIR);
  });

  afterAll(async () => {
    if (!dataAvailable) return;
    await handle.close();
  });

  // ---- manifest ----

  maybeSkip("manifest() returns a valid ArtifactManifest", async () => {
    const mf = await handle.manifest();
    expect(typeof mf.schema_version).toBe("number");
    expect(typeof mf.generated_at).toBe("string");
    expect(typeof mf.metacoding_data_dir).toBe("string");
    expect(typeof mf.n_symbols).toBe("number");
    expect(mf.n_symbols).toBeGreaterThan(0);
    expect(mf.motifs).toBe(true);
    expect(mf.centrality).toBe(true);
    expect(mf.embeddings).toBe(true);
  });

  // ---- motifs ----

  maybeSkip("motifs({ minSupport: 10 }) returns rows", async () => {
    const rows = await handle.motifs({ minSupport: 10 });
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.support).toBeGreaterThanOrEqual(10);
      expect(typeof row.motif_id).toBe("string");
      expect(typeof row.signature).toBe("string");
      expect(Array.isArray(row.repo_coverage)).toBe(true);
      expect(Array.isArray(row.edge_kinds)).toBe(true);
    }
    // Should be sorted descending by support.
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i]!.support).toBeLessThanOrEqual(rows[i - 1]!.support);
    }
  });

  maybeSkip("motifs({ limit: 5 }) returns at most 5 rows", async () => {
    const rows = await handle.motifs({ limit: 5 });
    expect(rows.length).toBeLessThanOrEqual(5);
  });

  maybeSkip("motifInstances() returns rows for a real motif_id", async () => {
    const motifs = await handle.motifs({ limit: 1 });
    expect(motifs.length).toBeGreaterThan(0);
    const motifId = motifs[0]!.motif_id;
    const instances = await handle.motifInstances(motifId, { limit: 10 });
    expect(instances.length).toBeGreaterThan(0);
    for (const inst of instances) {
      expect(inst.motif_id).toBe(motifId);
      expect(typeof inst.symbol_id).toBe("string");
      expect(typeof inst.repo).toBe("string");
      expect(typeof inst.file).toBe("string");
      expect(inst.line).toBeGreaterThan(0);
    }
  });

  // ---- centrality ----

  maybeSkip(
    "centrality({ repo, topK: 5, metric: pagerank }) returns 5 rows sorted by pagerank desc",
    async () => {
      const rows = await handle.centrality({
        repo: SAMPLE_REPO,
        topK: 5,
        metric: "pagerank",
      });
      expect(rows.length).toBe(5);
      for (const row of rows) {
        expect(row.repo).toBe(SAMPLE_REPO);
        expect(typeof row.symbol_id).toBe("string");
        expect(typeof row.pagerank).toBe("number");
        expect(row.pagerank).toBeGreaterThanOrEqual(0);
      }
      // Verify descending sort.
      for (let i = 1; i < rows.length; i++) {
        expect(rows[i]!.pagerank).toBeLessThanOrEqual(rows[i - 1]!.pagerank);
      }
    },
  );

  maybeSkip(
    "centrality({ topK: 3, metric: betweenness }) returns 3 rows",
    async () => {
      const rows = await handle.centrality({ topK: 3, metric: "betweenness" });
      expect(rows.length).toBe(3);
      for (let i = 1; i < rows.length; i++) {
        expect(rows[i]!.betweenness).toBeLessThanOrEqual(
          rows[i - 1]!.betweenness,
        );
      }
    },
  );

  // ---- spectralClusters ----

  maybeSkip("spectralClusters({ repo }) returns rows", async () => {
    const rows = await handle.spectralClusters({ repo: SAMPLE_REPO });
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.repo).toBe(SAMPLE_REPO);
      expect(typeof row.cluster_id).toBe("number");
      expect(row.cluster_size).toBeGreaterThan(0);
    }
  });

  // ---- embeddings ----

  maybeSkip("embeddings({ symbolIds }) returns matching rows", async () => {
    // Grab a couple of symbol_ids from centrality.
    const cents = await handle.centrality({
      repo: SAMPLE_REPO,
      topK: 2,
      metric: "pagerank",
    });
    const ids = cents.map((c) => c.symbol_id);
    const rows = await handle.embeddings({ symbolIds: ids });
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(ids).toContain(row.symbol_id);
      expect(Array.isArray(row.vec)).toBe(true);
      expect(row.vec.length).toBeGreaterThan(0);
    }
  });

  // ---- shape ----

  maybeSkip("shapePds() returns rows", async () => {
    const rows = await handle.shapePds(SAMPLE_REPO);
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(row.repo).toBe(SAMPLE_REPO);
      expect(typeof row.dim).toBe("number");
      expect(Array.isArray(row.birth)).toBe(true);
      expect(Array.isArray(row.death)).toBe(true);
      expect(row.birth.length).toBe(row.death.length);
    }
  });

  maybeSkip("wassersteinH1() returns rows", async () => {
    const rows = await handle.wassersteinH1({ repoA: SAMPLE_REPO });
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      // Should be the canonical upper-triangle order.
      expect(row.repo_a < row.repo_b).toBe(true);
      expect(typeof row.distance).toBe("number");
      expect(row.distance).toBeGreaterThanOrEqual(0);
    }
  });

  // ---- nnIndexMeta ----

  maybeSkip("nnIndexMeta() returns valid metadata", async () => {
    const meta = await handle.nnIndexMeta();
    expect(["faiss", "hnswlib"]).toContain(meta.backend);
    expect(["cosine", "l2", "ip"]).toContain(meta.metric);
    expect(meta.embedding_dim).toBeGreaterThan(0);
    expect(meta.n_symbols).toBeGreaterThan(0);
    expect(typeof meta.built_at).toBe("string");
  });

  // ---- nnLabels ----

  maybeSkip("nnLabels() returns rows with ordinal + symbol_id", async () => {
    const rows = await handle.nnLabels();
    expect(rows.length).toBeGreaterThan(0);
    expect(typeof rows[0]!.ordinal).toBe("number");
    expect(typeof rows[0]!.symbol_id).toBe("string");
  });

  // ---- L3: patterns ----

  maybeSkip("patterns() returns rows from patterns.jsonl", async () => {
    const rows = await handle.patterns();
    expect(rows.length).toBeGreaterThan(0);
    for (const row of rows) {
      expect(typeof row.pattern_id).toBe("string");
      expect(typeof row.label).toBe("string");
      expect(typeof row.confidence).toBe("number");
      expect(row.confidence).toBeGreaterThanOrEqual(0);
      expect(row.confidence).toBeLessThanOrEqual(1);
      expect(typeof row.llm_model).toBe("string");
      expect(typeof row.prompt_version).toBe("string");
    }
  });

  maybeSkip(
    "patterns({ minConfidence: 0.8 }) returns only high-confidence rows",
    async () => {
      const rows = await handle.patterns({ minConfidence: 0.8 });
      for (const row of rows) {
        expect(row.confidence).toBeGreaterThanOrEqual(0.8);
      }
    },
  );

  // ---- L3: evidence ----

  maybeSkip("evidence() returns rows for a real pattern_id", async () => {
    const patterns = await handle.patterns({ minConfidence: 0 });
    if (patterns.length === 0) {
      console.log("SKIP evidence test — no patterns found");
      return;
    }
    const patternId = patterns[0]!.pattern_id;
    const rows = await handle.evidence(patternId);
    // May be zero if evidence retrieval hasn't run, but should not throw.
    expect(Array.isArray(rows)).toBe(true);
    for (const row of rows) {
      expect(row.pattern_id).toBe(patternId);
      expect(typeof row.repo).toBe("string");
      expect(typeof row.file).toBe("string");
      expect(typeof row.snippet).toBe("string");
      expect(typeof row.line_range.start).toBe("number");
      expect(typeof row.line_range.end).toBe("number");
    }
  });

  // ---- close ----

  maybeSkip("close() resolves cleanly", async () => {
    // Create a separate handle so we don't close the shared one.
    const h = await openCtkrArtifacts(TEST_DATA_DIR);
    await expect(h.close()).resolves.toBeUndefined();
  });
});
