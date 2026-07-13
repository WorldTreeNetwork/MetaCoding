/**
 * Unit tests for src/ctkr/functorSearch.ts on hand-built fixture graphs.
 *
 * Covers §6 Task 2 acceptance: known optimum, partiality, kind-blocking,
 * determinism (byte-identical), zero-edge / no-candidate degenerate inputs,
 * margin populated, and anytime-budget honoring.
 */

import { expect, test, describe } from "bun:test";
import {
  functorSearch,
  kindGroup,
  DEFAULT_FUNCTOR_CONFIG,
  type FunctorObject,
  type FunctorEdge,
  type FunctorSearchInput,
} from "./functorSearch.ts";

function obj(id: string, kind: string, vec: number[]): FunctorObject {
  return { id, kind, profileVec: vec };
}
function edge(src: string, dst: string, kind: string): FunctorEdge {
  return { src, dst, kind };
}

/** Map srcId → dstId from a result, for assertions. */
function mapOf(r: ReturnType<typeof functorSearch>): Map<string, string> {
  const m = new Map<string, string>();
  for (const row of r.mapping) m.set(row.srcId, row.dstId);
  return m;
}

// ---------------------------------------------------------------------------
// Known optimum — clean isomorphism (rename fork in miniature)
// ---------------------------------------------------------------------------

describe("known optimum (isomorphic pair)", () => {
  // Distinct orthogonal profiles per role so KNN has a unique twin.
  const srcObjects = [
    obj("a1", "class", [5, 0, 0, 0, 0]),
    obj("a2", "method", [0, 5, 0, 0, 0]),
    obj("a3", "method", [0, 0, 5, 0, 0]),
    obj("a4", "field", [0, 0, 0, 5, 0]),
  ];
  const srcEdges = [
    edge("a1", "a2", "CONTAINS"),
    edge("a1", "a3", "CONTAINS"),
    edge("a2", "a3", "CALLS"),
    edge("a2", "a4", "READS_FIELD"),
  ];
  // b* are an α-rename: identical profiles + identical structure.
  const dstObjects = [
    obj("b1", "class", [5, 0, 0, 0, 0]),
    obj("b2", "method", [0, 5, 0, 0, 0]),
    obj("b3", "method", [0, 0, 5, 0, 0]),
    obj("b4", "field", [0, 0, 0, 5, 0]),
  ];
  const dstEdges = [
    edge("b1", "b2", "CONTAINS"),
    edge("b1", "b3", "CONTAINS"),
    edge("b2", "b3", "CALLS"),
    edge("b2", "b4", "READS_FIELD"),
  ];
  const input: FunctorSearchInput = { srcObjects, dstObjects, srcEdges, dstEdges };

  test("recovers the exact bijection", () => {
    const r = functorSearch(input, { normalize: "none" });
    const m = mapOf(r);
    expect(m.get("a1")).toBe("b1");
    expect(m.get("a2")).toBe("b2");
    expect(m.get("a3")).toBe("b3");
    expect(m.get("a4")).toBe("b4");
  });

  test("coverage 1.0, fidelity 1.0", () => {
    const r = functorSearch(input, { normalize: "none" });
    expect(r.coverage).toBeCloseTo(1.0, 10);
    expect(r.fidelity).toBeCloseTo(1.0, 10);
    expect(r.nMapped).toBe(4);
    expect(r.nEdgesInternal).toBe(4);
    expect(r.nEdgesPreserved).toBe(4);
  });

  test("every mapped pair reports pair_fidelity 1.0 and evidence mass", () => {
    const r = functorSearch(input, { normalize: "none" });
    for (const row of r.mapping) {
      expect(row.pairFidelity).not.toBeNull();
      expect(row.pairFidelity).toBeCloseTo(1.0, 10);
      expect(row.nEdgesIncident).toBeGreaterThan(0);
      expect(row.nEdgesPreserved).toBe(row.nEdgesIncident);
    }
  });
});

// ---------------------------------------------------------------------------
// Partiality — a source with no matchable target stays outside dom(F)
// ---------------------------------------------------------------------------

describe("partiality", () => {
  const input: FunctorSearchInput = {
    srcObjects: [
      obj("a1", "class", [5, 0, 0, 0, 0]),
      obj("a2", "method", [0, 5, 0, 0, 0]),
      // a3 has a signature no target shares → unmatchable
      obj("a3", "method", [0, 0, 0, 0, 9]),
    ],
    dstObjects: [
      obj("b1", "class", [5, 0, 0, 0, 0]),
      obj("b2", "method", [0, 5, 0, 0, 0]),
    ],
    srcEdges: [edge("a1", "a2", "CONTAINS"), edge("a1", "a3", "CONTAINS")],
    dstEdges: [edge("b1", "b2", "CONTAINS")],
  };

  test("unmatchable source is dropped; coverage < 1", () => {
    const r = functorSearch(input, { normalize: "none" });
    const m = mapOf(r);
    expect(m.has("a3")).toBe(false);
    expect(m.get("a1")).toBe("b1");
    expect(m.get("a2")).toBe("b2");
    expect(r.nMapped).toBe(2);
    expect(r.coverage).toBeCloseTo(2 / 3, 10);
  });
});

// ---------------------------------------------------------------------------
// Kind blocking — identical profile across incompatible kinds is not matched
// ---------------------------------------------------------------------------

describe("kind blocking", () => {
  test("class is never matched to a method with an identical profile", () => {
    const input: FunctorSearchInput = {
      srcObjects: [obj("a_class", "class", [1, 1, 0])],
      // identical profile but a METHOD → different kind group → blocked
      dstObjects: [obj("b_method", "method", [1, 1, 0])],
      srcEdges: [],
      dstEdges: [],
    };
    const r = functorSearch(input, { normalize: "none" });
    expect(r.nMapped).toBe(0);
    expect(r.coverage).toBe(0);
  });

  test("kindGroup buckets", () => {
    expect(kindGroup("class")).toBe(kindGroup("interface"));
    expect(kindGroup("function")).toBe(kindGroup("method"));
    expect(kindGroup("field")).toBe("field");
    expect(kindGroup("class")).not.toBe(kindGroup("method"));
  });
});

// ---------------------------------------------------------------------------
// Determinism — byte-identical output, including under ties
// ---------------------------------------------------------------------------

describe("determinism", () => {
  // Two identical target twins force a tie the matcher must break stably.
  const input: FunctorSearchInput = {
    srcObjects: [
      obj("a1", "class", [3, 0, 0]),
      obj("a2", "method", [0, 3, 0]),
    ],
    dstObjects: [
      obj("b1", "class", [3, 0, 0]),
      obj("bm_z", "method", [0, 3, 0]),
      obj("bm_a", "method", [0, 3, 0]), // identical twin of bm_z
    ],
    srcEdges: [edge("a1", "a2", "CONTAINS")],
    dstEdges: [edge("b1", "bm_z", "CONTAINS"), edge("b1", "bm_a", "CONTAINS")],
  };

  test("two runs produce byte-identical JSON", () => {
    const r1 = functorSearch(input, { normalize: "none" });
    const r2 = functorSearch(input, { normalize: "none" });
    expect(JSON.stringify(r1.mapping)).toBe(JSON.stringify(r2.mapping));
    expect(r1.coverage).toBe(r2.coverage);
    expect(r1.fidelity).toBe(r2.fidelity);
  });

  test("tie broken lexicographically (bm_a before bm_z)", () => {
    const r = functorSearch(input, { normalize: "none" });
    expect(mapOf(r).get("a2")).toBe("bm_a");
  });
});

// ---------------------------------------------------------------------------
// Margin — populated, 1.0 for a lone candidate, low under near-ties
// ---------------------------------------------------------------------------

describe("margin column", () => {
  test("lone candidate → margin 1.0", () => {
    const input: FunctorSearchInput = {
      srcObjects: [obj("a1", "method", [1, 2, 3])],
      dstObjects: [obj("b1", "method", [1, 2, 3])],
      srcEdges: [],
      dstEdges: [],
    };
    const r = functorSearch(input, { normalize: "none" });
    expect(r.mapping).toHaveLength(1);
    expect(r.mapping[0]!.margin).toBeCloseTo(1.0, 10);
  });

  test("near-tie among twins → low margin, flagged as ambiguous", () => {
    const input: FunctorSearchInput = {
      srcObjects: [obj("a1", "method", [1, 1, 1])],
      dstObjects: [
        obj("b1", "method", [1, 1, 1]),
        obj("b2", "method", [1, 1, 1]),
      ],
      srcEdges: [],
      dstEdges: [],
    };
    const r = functorSearch(input, { normalize: "none" });
    expect(r.mapping).toHaveLength(1);
    expect(r.mapping[0]!.margin).toBeLessThan(DEFAULT_FUNCTOR_CONFIG.deltaAmb);
    expect(r.ambiguityRate).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// Degenerate inputs — zero-edge and no-candidate must not throw
// ---------------------------------------------------------------------------

describe("degenerate inputs", () => {
  test("zero-edge graph: fidelity -1, pair_fidelity null, seeds still map", () => {
    const input: FunctorSearchInput = {
      srcObjects: [obj("a1", "method", [1, 0]), obj("a2", "class", [0, 1])],
      dstObjects: [obj("b1", "method", [1, 0]), obj("b2", "class", [0, 1])],
      srcEdges: [],
      dstEdges: [],
    };
    const r = functorSearch(input, { normalize: "none" });
    expect(r.fidelity).toBe(-1);
    expect(r.nEdgesInternal).toBe(0);
    expect(r.nMapped).toBe(2);
    for (const row of r.mapping) {
      expect(row.pairFidelity).toBeNull();
      expect(row.nEdgesIncident).toBe(0);
    }
  });

  test("no-candidate: all-zero profiles → empty mapping, no throw", () => {
    const input: FunctorSearchInput = {
      srcObjects: [obj("a1", "method", [0, 0, 0]), obj("a2", "class", [0, 0, 0])],
      dstObjects: [obj("b1", "method", [0, 0, 0])],
      srcEdges: [edge("a1", "a2", "CALLS")],
      dstEdges: [],
    };
    const r = functorSearch(input, { normalize: "none" });
    expect(r.nMapped).toBe(0);
    expect(r.coverage).toBe(0);
    expect(r.fidelity).toBe(-1);
    expect(r.mapping).toEqual([]);
  });

  test("empty input: no throw, empty result", () => {
    const r = functorSearch(
      { srcObjects: [], dstObjects: [], srcEdges: [], dstEdges: [] },
      { normalize: "none" },
    );
    expect(r.nObjectsSrc).toBe(0);
    expect(r.coverage).toBe(0);
    expect(r.nMapped).toBe(0);
  });

  test("edges referencing absent objects are ignored (internal-only)", () => {
    const input: FunctorSearchInput = {
      srcObjects: [obj("a1", "method", [1, 0]), obj("a2", "method", [0, 1])],
      dstObjects: [obj("b1", "method", [1, 0]), obj("b2", "method", [0, 1])],
      // ghost endpoint "x" — must not blow up nor count as internal
      srcEdges: [edge("a1", "x", "CALLS"), edge("a1", "a2", "CALLS")],
      dstEdges: [edge("b1", "b2", "CALLS")],
    };
    const r = functorSearch(input, { normalize: "none" });
    expect(r.nEdgesInternal).toBe(1);
    expect(r.fidelity).toBeCloseTo(1.0, 10);
  });
});

// ---------------------------------------------------------------------------
// Anytime budget — zero budget still returns a valid seed-based result
// ---------------------------------------------------------------------------

describe("anytime budget", () => {
  const input: FunctorSearchInput = {
    srcObjects: [obj("a1", "class", [5, 0]), obj("a2", "method", [0, 5])],
    dstObjects: [obj("b1", "class", [5, 0]), obj("b2", "method", [0, 5])],
    srcEdges: [edge("a1", "a2", "CONTAINS")],
    dstEdges: [edge("b1", "b2", "CONTAINS")],
  };

  test("budgetMs=0 exits early, flags budget, still returns valid mapping", () => {
    const r = functorSearch(input, { normalize: "none", budgetMs: 0 });
    expect(r.budgetExhausted).toBe(true);
    expect(r.roundsRun).toBe(0);
    // seeds alone already recover the clean isomorphism here
    expect(mapOf(r).get("a1")).toBe("b1");
    expect(mapOf(r).get("a2")).toBe("b2");
  });

  test("halved budget never yields garbage (subset-or-equal quality)", () => {
    const full = functorSearch(input, { normalize: "none" });
    const zero = functorSearch(input, { normalize: "none", budgetMs: 0 });
    expect(zero.nMapped).toBeLessThanOrEqual(full.nMapped);
  });
});

// ---------------------------------------------------------------------------
// Propagation earns its keep — structure resolves a profile ambiguity
// ---------------------------------------------------------------------------

describe("propagation uses structure", () => {
  // a2 and a3 share a profile (ambiguous by seed), but their neighbourhoods
  // differ: a2 is called by a1, a3 calls a4. Flooding + injective extraction
  // must still produce a consistent one-to-one map (no hub collapse).
  const input: FunctorSearchInput = {
    srcObjects: [
      obj("a1", "method", [9, 0, 0]),
      obj("a2", "method", [0, 5, 0]),
      obj("a3", "method", [0, 5, 0]),
      obj("a4", "method", [0, 0, 9]),
    ],
    dstObjects: [
      obj("b1", "method", [9, 0, 0]),
      obj("b2", "method", [0, 5, 0]),
      obj("b3", "method", [0, 5, 0]),
      obj("b4", "method", [0, 0, 9]),
    ],
    srcEdges: [edge("a1", "a2", "CALLS"), edge("a3", "a4", "CALLS")],
    dstEdges: [edge("b1", "b2", "CALLS"), edge("b3", "b4", "CALLS")],
  };

  test("injective map, full coverage, perfect fidelity", () => {
    const r = functorSearch(input, { normalize: "none" });
    expect(r.nMapped).toBe(4);
    // injectivity: distinct targets
    const targets = new Set(r.mapping.map((m) => m.dstId));
    expect(targets.size).toBe(4);
    expect(r.fidelity).toBeCloseTo(1.0, 10);
  });
});
