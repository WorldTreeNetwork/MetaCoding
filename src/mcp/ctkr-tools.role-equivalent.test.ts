/**
 * Tests for the ctkr.role_equivalent MCP handler (MetaCoding-23q.3).
 *
 * Uses /tmp/metacoding-scip as the test corpus because hom_profiles.parquet
 * is generated there by ralph-session E2E runs. Skips cleanly when the
 * artifact is absent.
 */

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { roleEquivalent } from "./ctkr-tools.ts";

const TEST_DATA_DIR = "/tmp/metacoding-scip";
const dataAvailable = await Bun.file(
  `${TEST_DATA_DIR}/ctkr/hom_profiles.parquet`,
).exists();

let originalEnv: string | undefined;

beforeAll(() => {
  originalEnv = process.env["METACODING_CTKR_DATA_DIR"];
  process.env["METACODING_CTKR_DATA_DIR"] = TEST_DATA_DIR;
});

afterAll(() => {
  if (originalEnv === undefined) {
    delete process.env["METACODING_CTKR_DATA_DIR"];
  } else {
    process.env["METACODING_CTKR_DATA_DIR"] = originalEnv;
  }
});

function maybeSkip(name: string, fn: () => Promise<void>): void {
  test(name, async () => {
    if (!dataAvailable) {
      console.log(
        `SKIP: ${name} — ${TEST_DATA_DIR}/ctkr/hom_profiles.parquet not found. ` +
          `Run: uv run python -m ctkr hom-profiles --data-dir ${TEST_DATA_DIR}`,
      );
      return;
    }
    await fn();
  });
}

describe("roleEquivalent", () => {
  maybeSkip("returns k rows by symbol_id, sorted ascending by distance", async () => {
    // Resolve a seed with non-zero edges (some symbols are isolates).
    const { openCtkrArtifacts } = await import("../ctkr/artifacts.ts");
    const h = await openCtkrArtifacts(TEST_DATA_DIR);
    const seedRows = await h.homProfiles({ limit: 1000 });
    await h.close();
    const seed = seedRows.find((r) => r.profile_vec.some((c) => c > 0))!;
    expect(seed).toBeDefined();

    const rows = await roleEquivalent({ symbol_id: seed.symbol_id, k: 5 });

    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThanOrEqual(5);
    for (const r of rows) {
      expect(typeof r.symbol_id).toBe("string");
      expect(typeof r.qualified_name).toBe("string");
      expect(typeof r.repo).toBe("string");
      expect(typeof r.hom_profile_distance).toBe("number");
      expect(r.hom_profile_distance).toBeGreaterThanOrEqual(0);
      expect(r.hom_profile_distance).toBeLessThanOrEqual(2 + 1e-9);
      expect(r.symbol_id).not.toBe(seed.symbol_id);
    }
    for (let i = 1; i < rows.length; i++) {
      expect(rows[i]!.hom_profile_distance).toBeGreaterThanOrEqual(
        rows[i - 1]!.hom_profile_distance,
      );
    }
  });

  maybeSkip("returns k rows by qualified_name", async () => {
    const { openCtkrArtifacts } = await import("../ctkr/artifacts.ts");
    const h = await openCtkrArtifacts(TEST_DATA_DIR);
    const seedRows = await h.homProfiles({ limit: 1000 });
    await h.close();
    const seed = seedRows.find(
      (r) => r.qualified_name.length > 0 && r.profile_vec.some((c) => c > 0),
    )!;
    expect(seed).toBeDefined();

    const rows = await roleEquivalent({
      qualified_name: seed.qualified_name,
      scope: seed.repo,
      k: 3,
    });
    expect(rows.length).toBeGreaterThan(0);
    expect(rows.length).toBeLessThanOrEqual(3);
  });

  maybeSkip("cross_repo_only excludes seed's repo", async () => {
    const { openCtkrArtifacts } = await import("../ctkr/artifacts.ts");
    const h = await openCtkrArtifacts(TEST_DATA_DIR);
    const seedRows = await h.homProfiles({ limit: 1000 });
    await h.close();
    const seed = seedRows.find((r) => r.profile_vec.some((c) => c > 0))!;

    const rows = await roleEquivalent({
      symbol_id: seed.symbol_id,
      k: 10,
      cross_repo_only: true,
    });
    for (const r of rows) {
      expect(r.repo).not.toBe(seed.repo);
    }
  });

  maybeSkip("throws when neither symbol_id nor qualified_name given", async () => {
    await expect(roleEquivalent({})).rejects.toThrow(/required/);
  });

  maybeSkip("returns empty for unknown symbol_id", async () => {
    const rows = await roleEquivalent({ symbol_id: "DOES_NOT_EXIST_XYZ" });
    expect(rows).toEqual([]);
  });

  maybeSkip(
    "scope restricts seed lookup to the named repo (qualified_name disambiguator)",
    async () => {
      const { openCtkrArtifacts } = await import("../ctkr/artifacts.ts");
      const h = await openCtkrArtifacts(TEST_DATA_DIR);
      const sample = (await h.homProfiles({ limit: 50 }))[0]!;
      await h.close();
      // Wrong scope → empty.
      const rows = await roleEquivalent({
        qualified_name: sample.qualified_name,
        scope: "definitely-not-a-real-repo",
      });
      expect(rows).toEqual([]);
    },
  );
});
