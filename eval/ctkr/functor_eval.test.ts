/**
 * eval/ctkr/functor_eval.test.ts
 *
 * CI gate for the Phase-2b functor-discovery eval suite (§6 Task 5, §5 + §8.2).
 * Runs the synthesized-fixture controls under `bun test` and asserts the
 * must-pass thresholds the Task-1 spike cleared on the real scip corpus at
 * DEPTH-2 (rename-fork correctness 0.987 / fidelity 0.990, candidate recall
 * 0.998; §5.1, §5.3, §5.6). No SCIP index, no external corpus — everything is
 * generated and scored in-process and deterministically.
 *
 * Must-pass gates (§6 Task 5 acceptance):
 *   - Control 1 rename fork:  coverage ≥ 0.95, fidelity ≥ 0.98,
 *                             automorphism-aware correctness ≥ 0.90
 *   - Control 3 null model:   real fidelity ≫ degree-matched-rewire and
 *                             random-kind-compatible-map floors (positive lift)
 *   - Control 6 cycle-consistency G∘F ≥ 0.90 on the rename fork
 * Tracked (not gated): dropout calibration, seed-degradation margin honesty,
 *   cross-framework recall/precision baseline, determinism/anytime.
 */

import { expect, test, describe } from "bun:test";
import {
  buildBaseGraph,
  runRenameFork,
  runAutomorphismDemo,
  runDropout,
  runNullModel,
  runSeedDegradation,
  runDeterminism,
  runCrossFramework,
} from "./functor_eval.ts";

const base = buildBaseGraph(10);

describe("§5.1 rename fork (isomorphism control — MUST PASS)", () => {
  const m = runRenameFork(base);

  test("coverage ≥ 0.95", () => {
    expect(m.coverage).toBeGreaterThanOrEqual(0.95);
  });
  test("fidelity ≥ 0.98", () => {
    expect(m.fidelity).toBeGreaterThanOrEqual(0.98);
  });
  test("automorphism-aware correctness ≥ 0.90", () => {
    expect(m.orbitCorrectness).toBeGreaterThanOrEqual(0.9);
  });
  test("no zero-profile isolates in the fixture (coverage is a real 1.0)", () => {
    expect(m.nMapped).toBe(m.nObjects);
  });
});

describe("§5.1/§8.2 automorphism-awareness is load-bearing", () => {
  const d = runAutomorphismDemo(4);

  test("within-orbit swaps are scored correct (orbit ≥ 0.90)", () => {
    expect(d.orbitCorrectness).toBeGreaterThanOrEqual(0.9);
  });
  test("exact-match scoring would falsely fail (orbit > exact)", () => {
    // proves the WL/color-refinement round rescues real errors exact-match
    // scoring would report — the machinery is not a no-op.
    expect(d.orbitVsExactGap).toBeGreaterThan(0);
    expect(d.exactMatch).toBeLessThan(1);
  });
});

describe("§5.6 cycle consistency G∘F (MUST PASS on control)", () => {
  const m = runRenameFork(base);
  test("cycle consistency ≥ 0.90", () => {
    expect(m.cycleConsistency).toBeGreaterThanOrEqual(0.9);
  });
});

describe("§5.3 null model (noise floor — MUST PASS)", () => {
  const n = runNullModel(base);

  test("real fidelity is high (≥ 0.95)", () => {
    expect(n.realFidelity).toBeGreaterThanOrEqual(0.95);
  });
  test("degree-matched-rewire floor is well below real (lift > 0.3)", () => {
    expect(n.liftOverRewire).toBeGreaterThan(0.3);
    expect(n.rewireFidelity).toBeLessThan(n.realFidelity);
  });
  test("random kind-compatible map is near-zero fidelity (< 0.30)", () => {
    expect(n.randomMapFidelity).toBeLessThan(0.3);
    expect(n.liftOverRandomMap).toBeGreaterThan(0.5);
  });
  test("permuted-seed control reported (structure carries a share of the map)", () => {
    // §5.3c: not gated, but must be finite and non-negative — records how much
    // of the result survives seed destruction (propagation doing the work).
    expect(n.permutedSeedFidelity).toBeGreaterThanOrEqual(0);
    expect(n.permutedSeedFidelity).toBeLessThanOrEqual(1);
  });
});

describe("§5.2 edge-dropout calibration (tracked)", () => {
  const pts = runDropout(base, [0.05, 0.15, 0.3]);

  test("three dropout points computed without error", () => {
    expect(pts).toHaveLength(3);
    for (const pt of pts) {
      expect(pt.fidelity).toBeGreaterThan(0);
      expect(pt.fidelity).toBeLessThanOrEqual(1);
    }
  });
  test("coverage degrades gracefully as dropout rises", () => {
    expect(pts[0]!.coverage).toBeGreaterThanOrEqual(pts[2]!.coverage);
  });
  test("fidelity tracks downward with dropout", () => {
    expect(pts[0]!.fidelity).toBeGreaterThan(pts[2]!.fidelity);
  });
});

describe("§5.7 seed-degradation stress (tracked)", () => {
  const pts = runSeedDegradation(base, [0.1, 0.2, 0.3]);

  test("three degradation points computed", () => {
    expect(pts).toHaveLength(3);
  });
  test("correctness degrades gracefully (stays ≥ 0.80 — structure-carried)", () => {
    // reproduces the spike finding: the map is structure-carried, so seed
    // collapse barely moves correctness (0.862 → 0.854 on the real corpus).
    for (const pt of pts) expect(pt.orbitCorrectness).toBeGreaterThanOrEqual(0.8);
  });
  test("margin is honest: correct pairs never carry less margin than wrong", () => {
    // §5.7 invariant — the matcher may be wrong, not confidently wrong. Where
    // wrong pairs exist, their mean margin must not exceed the correct pairs'.
    for (const pt of pts) {
      if (pt.meanMarginWrong > 0) {
        expect(pt.meanMarginCorrect).toBeGreaterThanOrEqual(pt.meanMarginWrong);
      }
    }
  });
});

describe("§5.5 determinism & anytime", () => {
  const d = runDeterminism(base);
  test("byte-identical across runs", () => {
    expect(d.byteIdentical).toBe(true);
  });
  test("zero budget never yields more than the full run (subset-or-equal)", () => {
    expect(d.halvedBudgetSubset).toBe(true);
  });
});

describe("§5.4 cross-framework baseline (soft signal — reported)", () => {
  const c = runCrossFramework(4);

  test("recall is a non-trivial baseline (> 0.30, analogous-not-isomorphic)", () => {
    // NOT a gate — frameworks are analogous, so recall is expected partial.
    // The number is the tracked baseline the sharper-seed re-run improves on.
    expect(c.recall).toBeGreaterThan(0.3);
    expect(c.recall).toBeLessThanOrEqual(1);
  });
  test("precision on role-bearing mappings is sane (≥ 0.50)", () => {
    expect(c.precision).toBeGreaterThanOrEqual(0.5);
  });
  test("every framework pair produced a mapping", () => {
    expect(c.pairCount).toBe(12); // 4 frameworks, both directions
    expect(c.gtPairs).toBeGreaterThan(0);
  });
});
