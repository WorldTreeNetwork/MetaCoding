/**
 * Tests for the ctkr.interface_of MCP handler (subsystem-extraction §3 / §8.2).
 *
 * Builds an on-disk fixture — interfaces.parquet + data_shapes.parquet +
 * manifest.json (with an alphabet_coverage note) — so every branch runs
 * deterministically without an external corpus:
 *   - provides / consumes rows + rolled-up export + dependency topology;
 *   - direction filter;
 *   - boundary vs internal data shapes + boundary_shapes_only;
 *   - alphabet_coverage surfaced from the manifest;
 *   - unknown-subsystem note + missing-artifact error mode.
 */

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtemp, rm, mkdir } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { DuckDBInstance } from "@duckdb/node-api";
import { interfaceOf } from "./ctkr-tools.ts";

const IFACE_COLSPEC: [string, string][] = [
  ["subsystem_id", "VARCHAR"],
  ["repo", "VARCHAR"],
  ["direction", "VARCHAR"],
  ["edge_kind", "VARCHAR"],
  ["edge_count", "INTEGER"],
  ["internal_symbol_id", "VARCHAR"],
  ["internal_qualified_name", "VARCHAR"],
  ["internal_export_symbol_id", "VARCHAR"],
  ["internal_export_qualified_name", "VARCHAR"],
  ["external_symbol_id", "VARCHAR"],
  ["external_qualified_name", "VARCHAR"],
  ["external_subsystem_id", "VARCHAR"],
  ["schema_version", "INTEGER"],
];

const SHAPE_COLSPEC: [string, string][] = [
  ["subsystem_id", "VARCHAR"],
  ["repo", "VARCHAR"],
  ["type_symbol_id", "VARCHAR"],
  ["type_qualified_name", "VARCHAR"],
  ["boundary", "BOOLEAN"],
  ["field_symbol_id", "VARCHAR"],
  ["field_name", "VARCHAR"],
  ["field_type", "VARCHAR"],
  ["read_by_internal", "BOOLEAN"],
  ["read_by_external", "BOOLEAN"],
  ["written_by_internal", "BOOLEAN"],
  ["written_by_external", "BOOLEAN"],
  ["constructed_by", "VARCHAR[]"],
  ["schema_version", "INTEGER"],
];

function iface(o: Partial<Record<string, unknown>>): Record<string, unknown> {
  return {
    subsystem_id: "ss:A", repo: "R", direction: "provides", edge_kind: "REFERENCES",
    edge_count: 1, internal_symbol_id: "x", internal_qualified_name: "a/svc.ts::x",
    internal_export_symbol_id: "x", internal_export_qualified_name: "a/svc.ts::x",
    external_symbol_id: "y", external_qualified_name: "b/main.ts::y",
    external_subsystem_id: "ss:B", schema_version: 1, ...o,
  };
}

const INTERFACES: Record<string, unknown>[] = [
  // ss:A provides — apiFn (top-level) + AConfig::x (nested → rolls to AConfig).
  iface({ edge_kind: "REFERENCES", edge_count: 3, internal_symbol_id: "apiFn",
    internal_qualified_name: "a/svc.ts::apiFn", internal_export_symbol_id: "apiFn",
    internal_export_qualified_name: "a/svc.ts::apiFn" }),
  iface({ edge_kind: "READS_FIELD", edge_count: 1, internal_symbol_id: "acx",
    internal_qualified_name: "a/svc.ts::AConfig::x", internal_export_symbol_id: "AConfig",
    internal_export_qualified_name: "a/svc.ts::AConfig" }),
  // ss:B consumes — into A, plus one external-package dependency (null subsystem).
  iface({ subsystem_id: "ss:B", direction: "consumes", edge_kind: "REFERENCES", edge_count: 3,
    internal_symbol_id: "bMain", internal_qualified_name: "b/main.ts::bMain",
    internal_export_symbol_id: "bMain", internal_export_qualified_name: "b/main.ts::bMain",
    external_symbol_id: "apiFn", external_qualified_name: "a/svc.ts::apiFn",
    external_subsystem_id: "ss:A" }),
  iface({ subsystem_id: "ss:B", direction: "consumes", edge_kind: "REFERENCES", edge_count: 1,
    internal_symbol_id: "bMain", internal_qualified_name: "b/main.ts::bMain",
    internal_export_symbol_id: "bMain", internal_export_qualified_name: "b/main.ts::bMain",
    external_symbol_id: "libX", external_qualified_name: "lib::X",
    external_subsystem_id: null }),
];

function shape(o: Partial<Record<string, unknown>>): Record<string, unknown> {
  return {
    subsystem_id: "ss:A", repo: "R", type_symbol_id: "T", type_qualified_name: "a/svc.ts::T",
    boundary: false, field_symbol_id: null, field_name: null, field_type: null,
    read_by_internal: false, read_by_external: false, written_by_internal: false,
    written_by_external: false, constructed_by: [], schema_version: 1, ...o,
  };
}

const SHAPES: Record<string, unknown>[] = [
  // AConfig — boundary type; field x is an output contract.
  shape({ type_symbol_id: "AConfig", type_qualified_name: "a/svc.ts::AConfig", boundary: true,
    field_symbol_id: "acx", field_name: "x", field_type: "a/svc.ts::AInternal",
    read_by_external: true, written_by_internal: true, constructed_by: ["b/main.ts::bMain"] }),
  // AInternal — private/internal type.
  shape({ type_symbol_id: "AInternal", type_qualified_name: "a/svc.ts::AInternal", boundary: false,
    field_symbol_id: "aif", field_name: "f", read_by_internal: true }),
];

const ALPHABET = {
  R: {
    data_edge_kinds: { TYPE_OF: 1, RETURNS_TYPE: 0, CONSTRUCTS: 1, READS_FIELD: 2, WRITES_FIELD: 1 },
    scip_fraction: 0.8, thin: false,
    note: "data alphabet ok: 4/5 data-edge kinds present; scip_fraction=0.8.",
  },
};

async function writeParquet(
  outPath: string, colspec: [string, string][], rows: Record<string, unknown>[],
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

async function buildFixture(dir: string, opts?: { interfaces?: boolean }): Promise<void> {
  const ctkr = join(dir, "ctkr");
  await mkdir(ctkr, { recursive: true });
  const present = opts?.interfaces ?? true;
  if (present) {
    await writeParquet(join(ctkr, "interfaces.parquet"), IFACE_COLSPEC, INTERFACES);
    await writeParquet(join(ctkr, "data_shapes.parquet"), SHAPE_COLSPEC, SHAPES);
  }
  await Bun.write(
    join(ctkr, "manifest.json"),
    JSON.stringify(
      {
        schema_version: 1, generated_at: "2026-07-14T00:00:00Z", metacoding_data_dir: dir,
        interfaces: present, data_shapes: present,
        n_interfaces: present ? INTERFACES.length : 0,
        n_data_shapes: present ? SHAPES.length : 0,
        alphabet_coverage: present ? ALPHABET : null,
      },
      null, 2,
    ) + "\n",
  );
}

let dataDir: string;
let originalEnv: string | undefined;

beforeAll(async () => {
  originalEnv = process.env["METACODING_CTKR_DATA_DIR"];
  dataDir = await mkdtemp(join(tmpdir(), "interface-of-"));
  await buildFixture(dataDir);
  process.env["METACODING_CTKR_DATA_DIR"] = dataDir;
});

afterAll(async () => {
  if (originalEnv === undefined) delete process.env["METACODING_CTKR_DATA_DIR"];
  else process.env["METACODING_CTKR_DATA_DIR"] = originalEnv;
  await rm(dataDir, { recursive: true, force: true });
});

describe("interfaceOf", () => {
  test("provides side: rows + rolled-up export surface", async () => {
    const res = await interfaceOf({ subsystem: "ss:A" });
    expect(res.provides.length).toBe(2);
    expect(res.consumes.length).toBe(0);
    // apiFn (top-level) and AConfig (rolled up from AConfig::x)
    expect(res.provides_exports).toEqual(["a/svc.ts::AConfig", "a/svc.ts::apiFn"]);
    // strongest crossing first (edge_count DESC within provides)
    expect(res.provides[0]!.internal_symbol_id).toBe("apiFn");
    expect(res.repo).toBe("R");
  });

  test("consumes side: dependency topology (subsystems + external package)", async () => {
    const res = await interfaceOf({ subsystem: "ss:B" });
    expect(res.consumes.length).toBe(2);
    expect(res.provides.length).toBe(0);
    expect(res.consumes_subsystems).toEqual(["(external)", "ss:A"]);
  });

  test("direction filter returns only the requested side", async () => {
    const res = await interfaceOf({ subsystem: "ss:B", direction: "consumes" });
    expect(res.consumes.length).toBe(2);
    expect(res.provides.length).toBe(0);
  });

  test("data shapes: boundary vs internal split", async () => {
    const res = await interfaceOf({ subsystem: "ss:A" });
    expect(res.n_boundary_shapes).toBe(1);
    expect(res.n_internal_shapes).toBe(1);
    const acx = res.data_shapes.find((s) => s.field_name === "x")!;
    expect(acx.boundary).toBe(true);
    // output contract: written internally, read externally
    expect(acx.written_by_internal).toBe(true);
    expect(acx.read_by_external).toBe(true);
    expect(acx.constructed_by).toEqual(["b/main.ts::bMain"]);
  });

  test("boundary_shapes_only drops internal types", async () => {
    const res = await interfaceOf({ subsystem: "ss:A", boundary_shapes_only: true });
    expect(res.n_internal_shapes).toBe(0);
    expect(res.data_shapes.every((s) => s.boundary)).toBe(true);
  });

  test("alphabet_coverage note surfaced for the subsystem's repo lane", async () => {
    const res = await interfaceOf({ subsystem: "ss:A" });
    expect(res.alphabet_coverage).not.toBeNull();
    expect(String(res.alphabet_coverage!["note"])).toContain("data-edge kinds");
  });

  test("unknown subsystem yields a note listing known ids", async () => {
    const res = await interfaceOf({ subsystem: "ss:nope" });
    expect(res.provides.length).toBe(0);
    expect(res.consumes.length).toBe(0);
    expect(res._note).toContain("unknown subsystem");
    expect(res._note).toContain("ss:A");
  });
});

describe("interfaceOf error modes", () => {
  test("missing artifact throws a clear, actionable error", async () => {
    const saved = process.env["METACODING_CTKR_DATA_DIR"];
    const emptyDir = await mkdtemp(join(tmpdir(), "interface-of-empty-"));
    await buildFixture(emptyDir, { interfaces: false });
    process.env["METACODING_CTKR_DATA_DIR"] = emptyDir;
    try {
      await expect(interfaceOf({ subsystem: "ss:A" })).rejects.toThrow(/ctkr interfaces/);
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
      await expect(interfaceOf({ subsystem: "ss:A" })).rejects.toThrow(/METACODING_CTKR_DATA_DIR/);
    } finally {
      process.env["METACODING_CTKR_DATA_DIR"] = saved;
    }
  });
});
