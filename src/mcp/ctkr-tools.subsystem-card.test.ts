/**
 * Tests for the ctkr.subsystem_card MCP handler (subsystem-extraction §8.1 / §8.2, T5).
 *
 * Builds an on-disk fixture — subsystem_cards.jsonl + manifest.json — so every
 * branch runs deterministically without an external corpus or LLM:
 *   - whole-card fetch by subsystem_id (+ repo scope);
 *   - section pruning (identity + provenance always kept);
 *   - unknown-subsystem note;
 *   - missing-deck error mode (manifest.subsystem_cards=false).
 */

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { mkdtemp, rm, mkdir, writeFile } from "node:fs/promises";
import { tmpdir } from "node:os";
import { join } from "node:path";
import { subsystemCard } from "./ctkr-tools.ts";
import type { SubsystemCard } from "../ctkr/types.ts";

function makeCard(over: Partial<SubsystemCard>): SubsystemCard {
  return {
    card_id: "card:aaa",
    subsystem_id: "ss:A",
    repo: "R",
    name: "Alpha Subsystem",
    intent: "Does the alpha job.",
    responsibilities: ["do a"],
    non_goals: [],
    spec_basis_summary: { structural: 0.8, nl_only: 0.2 },
    intent_dissonance: [
      { kind: "name_incoherence", evidence: "names diverge", source: "structural" },
    ],
    roles: [
      {
        role_id: "role:1", view: "similarity", label: "Validator",
        description: "validates", cardinality: 3, members: ["s1", "s2", "s3"],
        exemplar_symbol: "s1", exemplar_qualified_name: "a::s1", profile_depth: 1,
        granularity: "cos>=0.9", interface_participation: ["provides"],
        invariance_tier: "I", intent_dissonance: null,
      },
    ],
    composition_rules: [
      {
        operation_id: "op:1", label: "validate-then-emit", description: "…",
        op_kind: "path", arity: 1, input_roles: ["role:1"], output_role: "role:2",
        edge_kinds: ["CALLS"], support: 12, is_boundary_op: true,
        law_notes: { associative_observed: true, violations: 0, violation_kind: "" },
        exemplar_paths: ["a -> b"], invariance_tier: "I",
      },
    ],
    interface: {
      provides: [
        {
          symbol: "PublicApi", symbol_id: "s8", role_id: "role:1",
          usage_modes: ["CALLS"], contract: "callers may…", n_external_callers: 5,
        },
      ],
      consumes: [],
    },
    data_shapes: [
      {
        type: "Config", type_symbol_id: "s9", boundary: true, meaning: "config",
        fields: [{ name: "id", type: "str", flow: "in" }],
        invariance_tier: "I", alphabet_coverage_note: "ok",
      },
    ],
    topology: {
      n_members: 5, internal_edge_histogram: { CALLS: 2 }, h1_summary: null,
      cycles: 0, interface_degree: { in: 1, out: 0 },
    },
    exemplar_slices: [
      { purpose: "role:Validator exemplar", symbol_id: "s1", file: "a.py",
        line_start: 1, line_end: 3, code: "def s1(): ..." },
    ],
    nl_only_symbols: [
      { symbol_id: "s4", qualified_name: "a::CONST", file: "a.py",
        placement: "locality", spec_basis: "nl-only", description: "a constant table" },
    ],
    n_members: 5,
    provenance: {
      generated_at: "2026-07-14T00:00:00Z", schema_version: 1, partition_config: {},
      llm_model: "claude-haiku-4-5-20251001", llm_temperature: 0.0,
      prompt_version: "spec-labeler:v1", hom_profiles_generated_at: "2026-07-14T00:00:00Z",
      indexed_with_scip: true,
    },
    schema_version: 1,
    ...over,
  };
}

let dataDir = "";
let emptyDir = "";
let originalEnv: string | undefined;

beforeAll(async () => {
  dataDir = await mkdtemp(join(tmpdir(), "ctkr-card-"));
  const ctkr = join(dataDir, "ctkr");
  await mkdir(ctkr, { recursive: true });
  const cards = [
    makeCard({ card_id: "card:aaa", subsystem_id: "ss:A", repo: "R", n_members: 5 }),
    makeCard({ card_id: "card:bbb", subsystem_id: "ss:B", repo: "R", name: "Beta", n_members: 9 }),
  ];
  await writeFile(
    join(ctkr, "subsystem_cards.jsonl"),
    cards.map((c) => JSON.stringify(c)).join("\n") + "\n",
  );
  await writeFile(
    join(ctkr, "manifest.json"),
    JSON.stringify({
      schema_version: 1, generated_at: "2026-07-14T00:00:00Z",
      metacoding_data_dir: dataDir, subsystem_cards: true, n_subsystem_cards: 2,
    }),
  );

  emptyDir = await mkdtemp(join(tmpdir(), "ctkr-card-empty-"));
  await mkdir(join(emptyDir, "ctkr"), { recursive: true });
  await writeFile(
    join(emptyDir, "ctkr", "manifest.json"),
    JSON.stringify({ schema_version: 1, generated_at: "x", metacoding_data_dir: emptyDir, subsystem_cards: false }),
  );

  originalEnv = process.env["METACODING_CTKR_DATA_DIR"];
  process.env["METACODING_CTKR_DATA_DIR"] = dataDir;
});

afterAll(async () => {
  if (originalEnv === undefined) delete process.env["METACODING_CTKR_DATA_DIR"];
  else process.env["METACODING_CTKR_DATA_DIR"] = originalEnv;
  if (dataDir) await rm(dataDir, { recursive: true, force: true });
  if (emptyDir) await rm(emptyDir, { recursive: true, force: true });
});

describe("ctkr.subsystem_card", () => {
  test("whole card by subsystem_id", async () => {
    const r = await subsystemCard({ subsystem: "ss:A" });
    expect(r.card).not.toBeNull();
    expect(r.card!.subsystem_id).toBe("ss:A");
    expect(r.card!.roles!.length).toBe(1);
    expect(r.card!.interface!.provides[0]!.symbol).toBe("PublicApi");
    expect(r.card!.provenance!.prompt_version).toBe("spec-labeler:v1");
    expect(r.card!.spec_basis_summary!.structural).toBe(0.8);
  });

  test("section pruning keeps identity + provenance envelope only", async () => {
    const r = await subsystemCard({ subsystem: "ss:A", sections: ["roles"] });
    expect(r.card!.roles!.length).toBe(1);
    // Non-requested heavy sections are omitted…
    expect(r.card!.composition_rules).toBeUndefined();
    expect(r.card!.data_shapes).toBeUndefined();
    expect(r.card!.intent).toBeUndefined();
    // …but the envelope is always present.
    expect(r.card!.card_id).toBe("card:aaa");
    expect(r.card!.spec_basis_summary!.structural).toBe(0.8);
    expect(r.card!.provenance!.llm_model).toBeTruthy();
    expect(r._note).toContain("roles");
  });

  test("dissonance + intent sections map onto the right fields", async () => {
    const r = await subsystemCard({ subsystem: "ss:A", sections: ["dissonance", "intent"] });
    expect(r.card!.intent_dissonance!.length).toBe(1);
    expect(r.card!.intent).toBe("Does the alpha job.");
    expect(r.card!.responsibilities!.length).toBe(1);
    expect(r.card!.roles).toBeUndefined();
  });

  test("repo scope + n_members ordering", async () => {
    const r = await subsystemCard({ subsystem: "ss:B", repo: "R" });
    expect(r.card!.name).toBe("Beta");
  });

  test("unknown subsystem → card:null + note", async () => {
    const r = await subsystemCard({ subsystem: "ss:NOPE" });
    expect(r.card).toBeNull();
    expect(r._note).toContain("no card for subsystem");
  });

  test("missing deck → throws actionable error", async () => {
    const saved = process.env["METACODING_CTKR_DATA_DIR"];
    process.env["METACODING_CTKR_DATA_DIR"] = emptyDir;
    try {
      await expect(subsystemCard({ subsystem: "ss:A" })).rejects.toThrow(/extract-spec/);
    } finally {
      process.env["METACODING_CTKR_DATA_DIR"] = saved;
    }
  });
});
