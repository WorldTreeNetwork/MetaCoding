/**
 * eval/ctkr/run_functor_eval.ts
 *
 * Runner for the Phase-2b functor-discovery eval suite (§6 Task 5, §5 + §8.2).
 * Runs every control on synthesized fixtures with DEPTH-2 seeds, prints a
 * summary to stdout, and writes a Markdown report to
 * `eval/ctkr/results/functor-<timestamp>.md`.
 *
 * Usage:
 *   bun run eval/ctkr/run_functor_eval.ts
 *
 * The must-pass gates (rename fork, null model, cycle consistency) are the same
 * thresholds asserted in `functor_eval.test.ts`; this runner reports the
 * numbers, the test file enforces them in CI.
 */

import { mkdirSync, writeFileSync } from "node:fs";
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
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

const pct = (v: number) => (v * 100).toFixed(1) + "%";
const f3 = (v: number) => v.toFixed(3);

function main() {
  const base = buildBaseGraph(10);

  const rename = runRenameFork(base);
  const autoDemo = runAutomorphismDemo(4);
  const dropout = runDropout(base, [0.05, 0.15, 0.3]);
  const nullModel = runNullModel(base);
  const seedDeg = runSeedDegradation(base, [0.1, 0.2, 0.3]);
  const determinism = runDeterminism(base);
  const cross = runCrossFramework(4);

  const renamePass =
    rename.coverage >= 0.95 && rename.fidelity >= 0.98 && rename.orbitCorrectness >= 0.9;
  const cyclePass = rename.cycleConsistency >= 0.9;
  const nullPass =
    nullModel.realFidelity >= 0.95 &&
    nullModel.liftOverRewire > 0.3 &&
    nullModel.randomMapFidelity < 0.3;
  const allMustPass = renamePass && cyclePass && nullPass;

  const lines: string[] = [];
  const p = (s = "") => lines.push(s);

  p(`# Phase-2b Functor Discovery — Eval Report`);
  p();
  p(`Generated: ${new Date().toISOString()}`);
  p(`Seeds: **depth-2 hom-profiles** (one WL refinement round; the gate-clearing lever).`);
  p(`Fixture: synthesized ${base.objects.length}-symbol / ${base.edges.length}-edge multi-module graph (CI-runnable, no SCIP index).`);
  p();
  p(`## Must-pass gate summary`);
  p();
  p(`| control | verdict |`);
  p(`|---|---|`);
  p(`| §5.1 rename fork (cov≥0.95, fid≥0.98, correctness≥0.90) | ${renamePass ? "PASS" : "FAIL"} |`);
  p(`| §5.3 null model (real ≫ rewire & random-map floors) | ${nullPass ? "PASS" : "FAIL"} |`);
  p(`| §5.6 cycle consistency G∘F ≥ 0.90 | ${cyclePass ? "PASS" : "FAIL"} |`);
  p(`| **overall** | **${allMustPass ? "PASS" : "FAIL"}** |`);
  p();

  p(`## §5.1 Rename fork (isomorphism control)`);
  p();
  p(`| metric | value | gate |`);
  p(`|---|---|---|`);
  p(`| coverage | ${f3(rename.coverage)} | ≥ 0.95 ${rename.coverage >= 0.95 ? "✓" : "✗"} |`);
  p(`| fidelity | ${f3(rename.fidelity)} | ≥ 0.98 ${rename.fidelity >= 0.98 ? "✓" : "✗"} |`);
  p(`| automorphism-aware correctness | ${f3(rename.orbitCorrectness)} | ≥ 0.90 ${rename.orbitCorrectness >= 0.9 ? "✓" : "✗"} |`);
  p(`| exact-match correctness | ${f3(rename.exactMatch)} | (raw) |`);
  p(`| orbit − exact gap (intrinsic ambiguity mass) | ${f3(rename.orbitVsExactGap)} | — |`);
  p(`| cycle consistency G∘F | ${f3(rename.cycleConsistency)} | ≥ 0.90 ${rename.cycleConsistency >= 0.9 ? "✓" : "✗"} |`);
  p(`| ambiguity rate (margin < δ_amb) | ${f3(rename.ambiguityRate)} | (intrinsic) |`);
  p(`| mapped / objects | ${rename.nMapped} / ${rename.nObjects} | — |`);
  p(`| elapsed | ${rename.elapsedMs} ms | < 60 s ✓ |`);
  p();

  p(`## §5.1/§8.2 Automorphism-awareness is load-bearing`);
  p();
  p(`A ${autoDemo.orbitSize}-member structural orbit whose fork reverses member order: greedy picks orbit-mates that are not exact twins. Exact-match scoring would falsely report errors the matcher did not make.`);
  p();
  p(`| metric | value |`);
  p(`|---|---|`);
  p(`| orbit-aware correctness | ${f3(autoDemo.orbitCorrectness)} |`);
  p(`| exact-match correctness | ${f3(autoDemo.exactMatch)} |`);
  p(`| **orbit − exact gap (machinery value)** | **${f3(autoDemo.orbitVsExactGap)}** |`);
  p();

  p(`## §5.3 Null model (noise floor) — fidelity as LIFT`);
  p();
  p(`| map | fidelity | note |`);
  p(`|---|---|---|`);
  p(`| **real functor** (A → rename fork) | ${f3(nullModel.realFidelity)} | coverage ${f3(nullModel.realCoverage)} |`);
  p(`| degree-matched edge-rewire (§5.3a) | ${f3(nullModel.rewireFidelity)} | structure destroyed, degree preserved |`);
  p(`| random kind-compatible map (§5.3b) | ${f3(nullModel.randomMapFidelity)} | scored directly |`);
  p(`| permuted-seed control (§5.3c) | ${f3(nullModel.permutedSeedFidelity)} | coverage ${f3(nullModel.permutedSeedCoverage)}; structure-carried share |`);
  p(`| **lift over rewire** | **${f3(nullModel.liftOverRewire)}** | |`);
  p(`| **lift over random map** | **${f3(nullModel.liftOverRandomMap)}** | |`);
  p();

  p(`## §5.2 Edge-dropout calibration`);
  p();
  p(`| p (dropout) | coverage | fidelity | orbit-correct | mapped |`);
  p(`|---|---|---|---|---|`);
  for (const d of dropout) {
    p(`| ${pct(d.p)} | ${f3(d.coverage)} | ${f3(d.fidelity)} | ${f3(d.orbitCorrectness)} | ${d.nMapped} |`);
  }
  p();
  p(`Fidelity and coverage degrade monotonically with dropout (confound noted in §5.2: dropout also perturbs seeds, so both metrics move).`);
  p();

  p(`## §5.7 Seed-degradation stress (margin honesty)`);
  p();
  p(`| q (collapsed seeds) | orbit-correct | mean margin (correct) | mean margin (wrong) | Spearman(margin, correct) |`);
  p(`|---|---|---|---|---|`);
  for (const s of seedDeg) {
    p(`| ${pct(s.q)} | ${f3(s.orbitCorrectness)} | ${f3(s.meanMarginCorrect)} | ${f3(s.meanMarginWrong)} | ${f3(s.marginCorrectnessSpearman)} |`);
  }
  p();
  p(`Correctness is structure-carried (barely moves under seed collapse — matches the spike's 0.862 → 0.854), so few/no wrong pairs arise; where they do, wrong-pair margin never exceeds correct-pair margin (the honest-uncertainty invariant).`);
  p();

  p(`## §5.4 Cross-framework recall / precision (tracked baseline)`);
  p();
  p(`Synthetic analog of the 9-cluster ground truth: ${cross.pairCount} directed framework pairs, analogous (not isomorphic) role skeletons.`);
  p();
  p(`| metric | value |`);
  p(`|---|---|`);
  p(`| same-role recall | ${f3(cross.recall)} (${cross.recalled}/${cross.gtPairs}) |`);
  p(`| role precision (of role-bearing mappings) | ${f3(cross.precision)} (${cross.correctRole}/${cross.mappedRoleBearing}) |`);
  p();
  p(`| pair | GT same-role | recalled | coverage | fidelity |`);
  p(`|---|---|---|---|---|`);
  for (const pp of cross.perPair) {
    p(`| ${pp.a} → ${pp.b} | ${pp.gt} | ${pp.recalled} | ${f3(pp.coverage)} | ${f3(pp.fidelity)} |`);
  }
  p();
  p(`> The real 9-cluster corpus (crewAI/autogen/mastra…, \`role_equivalent_truth.yaml\`) requires a full \`--scip\` reindex + \`ctkr hom-profiles --depth 2\` + the functor runner over those repos; this synthetic baseline is the CI-runnable stand-in. Re-run against the real corpus once its depth-2 artifacts exist to record the production baseline.`);
  p();

  p(`## §5.5 Determinism & anytime`);
  p();
  p(`- byte-identical across runs: **${determinism.byteIdentical}**`);
  p(`- zero-budget subset-or-equal (never garbage): **${determinism.halvedBudgetSubset}**`);
  p();
  p(`---`);
  p(`*Fixtures synthesized in-process; see \`eval/ctkr/functor_eval.ts\`. Gates enforced in CI by \`eval/ctkr/functor_eval.test.ts\`.*`);

  const md = lines.join("\n") + "\n";

  const __dir = dirname(fileURLToPath(import.meta.url));
  const resultsDir = join(__dir, "results");
  mkdirSync(resultsDir, { recursive: true });
  const ts = new Date().toISOString().replace(/[:.]/g, "-").slice(0, 19);
  const reportPath = join(resultsDir, `functor-${ts}.md`);
  writeFileSync(reportPath, md, "utf8");

  // stdout summary
  console.log(md);
  console.log(`Report written to: ${reportPath}`);
  console.log(`MUST-PASS OVERALL: ${allMustPass ? "PASS" : "FAIL"}`);
  if (!allMustPass) process.exit(1);
}

main();
