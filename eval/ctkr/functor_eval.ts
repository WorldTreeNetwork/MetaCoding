/**
 * eval/ctkr/functor_eval.ts
 *
 * Eval harness for Phase-2b functor discovery (MetaCoding §6 Task 5, §5 + §8.2).
 *
 * Implements the §5 validation suite against the production search
 * (`src/ctkr/functorSearch.ts`) with DEPTH-2 seeds:
 *
 *   1. Rename fork (isomorphism control, must-pass)     — §5.1
 *   2. Edge-dropout calibration                          — §5.2
 *   3. Null model (noise floor, must-pass): degree-matched
 *      rewire + random kind-compatible map + permuted seed — §5.3
 *   4. Cross-framework recall/precision (soft baseline)   — §5.4
 *   5. Determinism / anytime                              — §5.5
 *   6. Cycle consistency G∘F (must-pass on controls)      — §5.6
 *   7. Seed-degradation stress (margin honesty)           — §5.7
 *
 * CI-runnable: fixtures are SYNTHESIZED in-process (no SCIP index, no external
 * corpus, no committed parquet). The synthetic base graph is a small,
 * deterministic multi-module "codebase" whose depth-2 hom-profiles are the
 * exact TS mirror of `ctkr/ctkr/hom_profiles.py` (one Weisfeiler-Leman
 * refinement round, NDIM + NDIM*NDIM dims). The gate that the Task-1 spike
 * cleared on the real ~4.7k-symbol scip corpus at depth 2 (rename_fork
 * correctness 0.987, candidate_recall 0.998, fidelity 0.990) is reproduced
 * here on a controllable fixture.
 *
 * Everything is deterministic (seeded RNG); the harness itself is byte-stable.
 */

import {
  functorSearch,
  kindGroup,
  type FunctorObject,
  type FunctorEdge,
  type FunctorSearchInput,
  type FunctorSearchConfig,
  type FunctorSearchResult,
} from "../../src/ctkr/functorSearch.ts";
import { cosineSimilarity } from "../../src/ctkr/homProfile.ts";

// ---------------------------------------------------------------------------
// Edge-kind dimension ordering — exact mirror of ctkr/ctkr/graph_loader.py
// EDGE_KINDS and hom_profiles.py DIMS (per kind: (kind,"in") then (kind,"out")).
// ---------------------------------------------------------------------------

export const EDGE_KINDS = [
  "CALLS",
  "REFERENCES",
  "EXTENDS",
  "IMPLEMENTS",
  "OVERRIDES",
  "INJECTS",
  "CONTAINS",
  "IMPORTS",
  "ANNOTATES",
  "TYPE_OF",
  "READS_FIELD",
  "WRITES_FIELD",
  "RETURNS_TYPE",
  "CONSTRUCTS",
  "RAISES",
] as const;

const DIMS: [string, "in" | "out"][] = EDGE_KINDS.flatMap(
  (k) => [[k, "in"], [k, "out"]] as [string, "in" | "out"][],
);
const DIM_IDX = new Map<string, number>(DIMS.map((d, i) => [`${d[0]}|${d[1]}`, i]));
export const NDIM = DIMS.length; // 30

// ---------------------------------------------------------------------------
// Deterministic RNG (mulberry32)
// ---------------------------------------------------------------------------

export function rng(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** Fisher-Yates shuffle in place, deterministic given `rand`. */
function shuffle<T>(arr: T[], rand: () => number): T[] {
  for (let i = arr.length - 1; i > 0; i--) {
    const j = Math.floor(rand() * (i + 1));
    [arr[i], arr[j]] = [arr[j]!, arr[i]!];
  }
  return arr;
}

// ---------------------------------------------------------------------------
// Synthetic graph model
// ---------------------------------------------------------------------------

export interface SynthObject {
  id: string;
  kind: string;
  /** optional cross-framework role label (§5.4 ground truth). */
  role?: string;
}

export interface SynthGraph {
  objects: SynthObject[];
  edges: FunctorEdge[];
}

/**
 * Build a small, deterministic multi-module "codebase" graph. Structure is
 * deliberately asymmetric (varying method counts, an EXTENDS class chain, a
 * call hub) so depth-2 profiles are highly discriminative — mostly singleton
 * automorphism orbits — WITH one intentional symmetric orbit (three
 * interchangeable accessor methods) so the automorphism-aware correctness
 * machinery (§5.1) is genuinely exercised (exact-match < orbit-correct).
 *
 * Every symbol carries at least one incident edge, so there are no
 * zero-profile isolates dragging coverage down (the real-corpus 22.7% ceiling
 * is a corpus property, not an algorithm limit — see 2hop-findings.md).
 */
export function buildBaseGraph(modules = 10): SynthGraph {
  const objects: SynthObject[] = [];
  const edges: FunctorEdge[] = [];
  const add = (id: string, kind: string, role?: string) =>
    objects.push({ id, kind, role });

  // Two interfaces every class implements one of (asymmetric split).
  add("I0", "interface");
  add("I1", "interface");

  const classIds: string[] = [];
  for (let i = 0; i < modules; i++) {
    const cls = `C${i}`;
    classIds.push(cls);
    add(cls, "class");
    // vary method count 2..5 by module (asymmetry)
    const nMethods = 2 + (i % 4);
    const methods: string[] = [];
    for (let j = 0; j < nMethods; j++) {
      const m = `C${i}.m${j}`;
      methods.push(m);
      add(m, "method");
      edges.push({ src: cls, dst: m, kind: "CONTAINS" });
    }
    const field = `C${i}.f`;
    add(field, "field");
    edges.push({ src: cls, dst: field, kind: "CONTAINS" });

    // method call chain (varying length → asymmetric depth-2 signature)
    for (let j = 0; j + 1 < methods.length; j++) {
      edges.push({ src: methods[j]!, dst: methods[j + 1]!, kind: "CALLS" });
    }
    // field access: first method reads, last writes (+ per-module extra writers)
    edges.push({ src: methods[0]!, dst: field, kind: "READS_FIELD" });
    edges.push({ src: methods[methods.length - 1]!, dst: field, kind: "WRITES_FIELD" });
    for (let w = 0; w < i % 3; w++) {
      edges.push({ src: methods[w % methods.length]!, dst: field, kind: "WRITES_FIELD" });
    }

    // class hierarchy chain: C_i EXTENDS C_{i-1} (position in chain is a
    // strong depth-2 discriminator).
    if (i > 0) edges.push({ src: cls, dst: `C${i - 1}`, kind: "EXTENDS" });
    // interface split
    edges.push({ src: cls, dst: `I${i % 2}`, kind: "IMPLEMENTS" });
    // call hub: every module's entry method calls module 0's entry method →
    // gives C0.m0 a distinctive high CALLS:in profile.
    if (i > 0) edges.push({ src: methods[0]!, dst: "C0.m0", kind: "CALLS" });
    // constructs: entry method constructs its own class (RETURNS_TYPE too)
    edges.push({ src: methods[0]!, dst: cls, kind: "CONSTRUCTS" });
    edges.push({ src: methods[methods.length - 1]!, dst: cls, kind: "RETURNS_TYPE" });
  }

  // Deliberate automorphism orbit: three interchangeable accessor methods on
  // C0, each with an identical edge pattern (CONTAINS:in from C0, READS_FIELD
  // to C0.f). A name-blind matcher cannot — and should not — distinguish them.
  for (let a = 0; a < 3; a++) {
    const acc = `C0.acc${a}`;
    add(acc, "method");
    edges.push({ src: "C0", dst: acc, kind: "CONTAINS" });
    edges.push({ src: acc, dst: "C0.f", kind: "READS_FIELD" });
  }

  return { objects, edges };
}

// ---------------------------------------------------------------------------
// Depth-2 hom-profiles — exact TS mirror of hom_profiles.py depth=2
// ---------------------------------------------------------------------------

/**
 * Compute the depth-2 hom-profile vector for every object: the 1-hop typed
 * in/out count vector (NDIM dims) concatenated with, per (kind,dir) block, the
 * MEAN 1-hop vector of neighbors reached via that block (NDIM*NDIM dims). This
 * is one Weisfeiler-Leman refinement round — the lever that clears the gate
 * (2hop-findings.md). Byte-for-byte the same scheme as the Python writer.
 */
export function computeDepth2Profiles(g: SynthGraph): Map<string, number[]> {
  const ids = g.objects.map((o) => o.id);
  const oneHop = new Map<string, number[]>();
  for (const id of ids) oneHop.set(id, new Array(NDIM).fill(0));

  for (const e of g.edges) {
    const outIdx = DIM_IDX.get(`${e.kind}|out`);
    const inIdx = DIM_IDX.get(`${e.kind}|in`);
    if (outIdx !== undefined && oneHop.has(e.src)) oneHop.get(e.src)![outIdx]!++;
    if (inIdx !== undefined && oneHop.has(e.dst)) oneHop.get(e.dst)![inIdx]!++;
  }

  // block sums + counts per (kind,dir)
  const nbrSum = new Map<string, number[]>();
  const nbrCnt = new Map<string, number[]>();
  for (const id of ids) {
    nbrSum.set(id, new Array(NDIM * NDIM).fill(0));
    nbrCnt.set(id, new Array(NDIM).fill(0));
  }
  for (const e of g.edges) {
    const od = DIM_IDX.get(`${e.kind}|out`);
    const idm = DIM_IDX.get(`${e.kind}|in`);
    // src reaches dst via OUT block
    if (od !== undefined && nbrSum.has(e.src) && oneHop.has(e.dst)) {
      const block = nbrSum.get(e.src)!;
      const base = od * NDIM;
      const pd = oneHop.get(e.dst)!;
      for (let j = 0; j < NDIM; j++) block[base + j]! += pd[j]!;
      nbrCnt.get(e.src)![od]!++;
    }
    // dst reaches src via IN block
    if (idm !== undefined && nbrSum.has(e.dst) && oneHop.has(e.src)) {
      const block = nbrSum.get(e.dst)!;
      const base = idm * NDIM;
      const ps = oneHop.get(e.src)!;
      for (let j = 0; j < NDIM; j++) block[base + j]! += ps[j]!;
      nbrCnt.get(e.dst)![idm]!++;
    }
  }

  const out = new Map<string, number[]>();
  for (const id of ids) {
    const vec = [...oneHop.get(id)!];
    const sums = nbrSum.get(id)!;
    const cnts = nbrCnt.get(id)!;
    for (let d = 0; d < NDIM; d++) {
      const c = cnts[d]!;
      const base = d * NDIM;
      if (c > 0) {
        const inv = 1 / c;
        for (let j = 0; j < NDIM; j++) vec.push(sums[base + j]! * inv);
      } else {
        for (let j = 0; j < NDIM; j++) vec.push(0);
      }
    }
    out.set(id, vec);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Automorphism orbits — one color-refinement round (matches spike harness)
// ---------------------------------------------------------------------------

/**
 * Approximate each object's automorphism orbit as the spike does (§5.1):
 * color0 = kind + hash(depth-2 profile); orbit signature = color0 plus the
 * sorted multiset of (kind, dir, neighbor color0). Two objects with the same
 * orbit signature are name-blind-indistinguishable and a swap between them is
 * NOT an error.
 */
export function orbitSignatures(
  g: SynthGraph,
  profiles: Map<string, number[]>,
): Map<string, string> {
  const kindOf = new Map(g.objects.map((o) => [o.id, o.kind]));
  const color0 = new Map<string, string>();
  for (const o of g.objects) {
    color0.set(o.id, `${o.kind}#${profiles.get(o.id)!.join(",")}`);
  }
  // adjacency (both directions)
  const adj = new Map<string, { kind: string; dir: number; other: string }[]>();
  for (const o of g.objects) adj.set(o.id, []);
  for (const e of g.edges) {
    if (adj.has(e.src)) adj.get(e.src)!.push({ kind: e.kind, dir: 0, other: e.dst });
    if (adj.has(e.dst)) adj.get(e.dst)!.push({ kind: e.kind, dir: 1, other: e.src });
  }
  const orbit = new Map<string, string>();
  for (const o of g.objects) {
    const parts = adj
      .get(o.id)!
      .map((e) => `${e.kind}:${e.dir}:${color0.get(e.other) ?? "x"}`)
      .sort();
    orbit.set(o.id, `${color0.get(o.id)}||${parts.join(";")}`);
  }
  void kindOf;
  return orbit;
}

// ---------------------------------------------------------------------------
// Transforms
// ---------------------------------------------------------------------------

/**
 * α-rename fork: identical structure, every id replaced by a fresh id. Returns
 * the fork graph and the ground-truth bijection base-id → fork-id.
 */
export function renameFork(g: SynthGraph): {
  fork: SynthGraph;
  trueMap: Map<string, string>;
} {
  const trueMap = new Map<string, string>();
  for (const o of g.objects) trueMap.set(o.id, `fk::${o.id}`);
  const fork: SynthGraph = {
    objects: g.objects.map((o) => ({ id: trueMap.get(o.id)!, kind: o.kind, role: o.role })),
    edges: g.edges.map((e) => ({
      src: trueMap.get(e.src)!,
      dst: trueMap.get(e.dst)!,
      kind: e.kind,
    })),
  };
  return { fork, trueMap };
}

/** Edge-dropout fork: rename fork with a random fraction `p` of edges deleted. */
export function dropoutFork(
  g: SynthGraph,
  p: number,
  seed: number,
): { fork: SynthGraph; trueMap: Map<string, string> } {
  const { fork, trueMap } = renameFork(g);
  const rand = rng(seed);
  const kept = fork.edges.filter(() => rand() >= p);
  return { fork: { objects: fork.objects, edges: kept }, trueMap };
}

/**
 * Degree-matched edge-rewire null (§5.3a): per edge kind, preserve every
 * node's in/out degree exactly but re-pair sources to destinations at random,
 * destroying higher-order structure. Ids are kept (so it is B with its wiring
 * shuffled).
 */
export function degreeMatchedRewire(g: SynthGraph, seed: number): SynthGraph {
  const rand = rng(seed);
  const byKind = new Map<string, FunctorEdge[]>();
  for (const e of g.edges) {
    if (!byKind.has(e.kind)) byKind.set(e.kind, []);
    byKind.get(e.kind)!.push(e);
  }
  const out: FunctorEdge[] = [];
  for (const kind of [...byKind.keys()].sort()) {
    const es = byKind.get(kind)!;
    const srcs = es.map((e) => e.src);
    const dsts = shuffle(es.map((e) => e.dst), rand);
    for (let i = 0; i < srcs.length; i++) {
      out.push({ src: srcs[i]!, dst: dsts[i]!, kind });
    }
  }
  return { objects: g.objects, edges: out };
}

/**
 * Random kind-compatible injective map (§5.3b): assign each src object to a
 * distinct dst object of the same kind-group, uniformly at random. Used to
 * score a meaningless map directly.
 */
export function randomKindCompatibleMap(
  src: SynthGraph,
  dst: SynthGraph,
  seed: number,
): Map<string, string> {
  const rand = rng(seed);
  const dstByGroup = new Map<string, string[]>();
  for (const o of dst.objects) {
    const g = kindGroup(o.kind);
    if (!dstByGroup.has(g)) dstByGroup.set(g, []);
    dstByGroup.get(g)!.push(o.id);
  }
  for (const arr of dstByGroup.values()) shuffle(arr, rand);
  const cursor = new Map<string, number>();
  const map = new Map<string, string>();
  for (const o of [...src.objects].sort((a, b) => (a.id < b.id ? -1 : 1))) {
    const g = kindGroup(o.kind);
    const pool = dstByGroup.get(g);
    if (!pool) continue;
    const i = cursor.get(g) ?? 0;
    if (i < pool.length) {
      map.set(o.id, pool[i]!);
      cursor.set(g, i + 1);
    }
  }
  return map;
}

/**
 * Permuted-seed null (§5.3c): shuffle the profile vectors among kind-compatible
 * objects, keeping the real graph. Isolates how much of the result is carried
 * by structure (propagation) vs. by seeds.
 */
export function permuteSeedProfiles(
  g: SynthGraph,
  profiles: Map<string, number[]>,
  seed: number,
): Map<string, number[]> {
  const rand = rng(seed);
  const byGroup = new Map<string, string[]>();
  for (const o of g.objects) {
    const gg = kindGroup(o.kind);
    if (!byGroup.has(gg)) byGroup.set(gg, []);
    byGroup.get(gg)!.push(o.id);
  }
  const out = new Map<string, number[]>();
  for (const ids of byGroup.values()) {
    const shuffled = shuffle([...ids], rand);
    for (let i = 0; i < ids.length; i++) {
      out.set(ids[i]!, profiles.get(shuffled[i]!)!);
    }
  }
  return out;
}

/**
 * Seed-degradation (§5.7): collapse a fraction `q` of profiles onto their
 * nearest same-kind-group neighbor, mimicking the measured ~16% near-
 * indistinguishable mass. Returns a fresh profile map.
 */
export function degradeSeeds(
  g: SynthGraph,
  profiles: Map<string, number[]>,
  q: number,
  seed: number,
): Map<string, number[]> {
  const rand = rng(seed);
  const out = new Map(profiles);
  const byGroup = new Map<string, SynthObject[]>();
  for (const o of g.objects) {
    const gg = kindGroup(o.kind);
    if (!byGroup.has(gg)) byGroup.set(gg, []);
    byGroup.get(gg)!.push(o);
  }
  for (const o of [...g.objects].sort((a, b) => (a.id < b.id ? -1 : 1))) {
    if (rand() >= q) continue;
    const pool = byGroup.get(kindGroup(o.kind))!;
    const v = profiles.get(o.id)!;
    let best = -1;
    let bestSim = -1;
    for (let j = 0; j < pool.length; j++) {
      const m = pool[j]!;
      if (m.id === o.id) continue;
      const c = cosineSimilarity(v, profiles.get(m.id)!);
      if (c > bestSim) {
        bestSim = c;
        best = j;
      }
    }
    if (best >= 0) out.set(o.id, [...profiles.get(pool[best]!.id)!]);
  }
  return out;
}

// ---------------------------------------------------------------------------
// Search-input assembly + direct scoring helpers
// ---------------------------------------------------------------------------

export function toFunctorObjects(
  g: SynthGraph,
  profiles: Map<string, number[]>,
): FunctorObject[] {
  return g.objects.map((o) => ({ id: o.id, kind: o.kind, profileVec: profiles.get(o.id)! }));
}

export function buildSearchInput(
  srcG: SynthGraph,
  srcP: Map<string, number[]>,
  dstG: SynthGraph,
  dstP: Map<string, number[]>,
): FunctorSearchInput {
  return {
    srcObjects: toFunctorObjects(srcG, srcP),
    srcEdges: srcG.edges,
    dstObjects: toFunctorObjects(dstG, dstP),
    dstEdges: dstG.edges,
  };
}

/**
 * Fidelity of an arbitrary object↦object map, computed directly (used for the
 * null-model random map, which functorSearch does not produce): fraction of
 * internal src edges whose same-kind witness exists in dst under the map.
 */
export function computeMapFidelity(
  srcG: SynthGraph,
  dstG: SynthGraph,
  map: Map<string, string>,
): { fidelity: number; internal: number; preserved: number } {
  const dstEdgeSet = new Set(dstG.edges.map((e) => `${e.src}|${e.kind}|${e.dst}`));
  const dom = new Set(map.keys());
  const srcIds = new Set(srcG.objects.map((o) => o.id));
  const seen = new Set<string>();
  let internal = 0;
  let preserved = 0;
  for (const e of srcG.edges) {
    if (!srcIds.has(e.src) || !srcIds.has(e.dst)) continue;
    if (!dom.has(e.src) || !dom.has(e.dst)) continue;
    const dk = `${e.src}|${e.kind}|${e.dst}`;
    if (seen.has(dk)) continue;
    seen.add(dk);
    internal++;
    if (dstEdgeSet.has(`${map.get(e.src)}|${e.kind}|${map.get(e.dst)}`)) preserved++;
  }
  return { fidelity: internal > 0 ? preserved / internal : -1, internal, preserved };
}

// ---------------------------------------------------------------------------
// Correctness scoring against a ground-truth bijection (orbit-aware, §5.1)
// ---------------------------------------------------------------------------

export interface CorrectnessResult {
  scored: number;
  exactMatch: number;
  orbitCorrect: number;
  /** margin honesty (§5.7): mean margin for correct vs wrong, spearman. */
  meanMarginCorrect: number;
  meanMarginWrong: number;
  marginCorrectnessSpearman: number;
}

export function scoreCorrectness(
  result: FunctorSearchResult,
  trueMap: Map<string, string>,
  forkObjectIds: Set<string>,
  forkOrbit: Map<string, string>,
): CorrectnessResult {
  let scored = 0;
  let exact = 0;
  let orbit = 0;
  const marginArr: number[] = [];
  const correctArr: number[] = [];
  const mCorrect: number[] = [];
  const mWrong: number[] = [];
  for (const m of result.mapping) {
    const tw = trueMap.get(m.srcId);
    if (!tw || !forkObjectIds.has(tw)) continue;
    scored++;
    if (m.dstId === tw) exact++;
    const ok = forkOrbit.get(m.dstId) === forkOrbit.get(tw);
    if (ok) orbit++;
    marginArr.push(m.margin);
    correctArr.push(ok ? 1 : 0);
    (ok ? mCorrect : mWrong).push(m.margin);
  }
  const mean = (a: number[]) => (a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0);
  return {
    scored,
    exactMatch: scored ? exact / scored : 0,
    orbitCorrect: scored ? orbit / scored : 0,
    meanMarginCorrect: mean(mCorrect),
    meanMarginWrong: mean(mWrong),
    marginCorrectnessSpearman: spearman(marginArr, correctArr),
  };
}

export function spearman(x: number[], y: number[]): number {
  const n = x.length;
  if (n < 2) return 0;
  const rank = (arr: number[]): number[] => {
    const idx = arr.map((v, i) => [v, i] as [number, number]).sort((a, b) => a[0] - b[0]);
    const r = new Array<number>(n);
    let i = 0;
    while (i < n) {
      let j = i;
      while (j + 1 < n && idx[j + 1]![0] === idx[i]![0]) j++;
      const avg = (i + j) / 2;
      for (let k = i; k <= j; k++) r[idx[k]![1]] = avg;
      i = j + 1;
    }
    return r;
  };
  const rx = rank(x);
  const ry = rank(y);
  const mx = rx.reduce((a, b) => a + b, 0) / n;
  const my = ry.reduce((a, b) => a + b, 0) / n;
  let num = 0;
  let dx = 0;
  let dy = 0;
  for (let i = 0; i < n; i++) {
    const a = rx[i]! - mx;
    const b = ry[i]! - my;
    num += a * b;
    dx += a * a;
    dy += b * b;
  }
  return dx === 0 || dy === 0 ? 0 : num / Math.sqrt(dx * dy);
}

// ---------------------------------------------------------------------------
// Control runners
// ---------------------------------------------------------------------------

const HIGH_SIGNAL_CFG: Partial<FunctorSearchConfig> = { normalize: "none" };

export interface RenameForkMetrics {
  coverage: number;
  fidelity: number;
  orbitCorrectness: number;
  exactMatch: number;
  orbitVsExactGap: number;
  cycleConsistency: number;
  nMapped: number;
  nObjects: number;
  ambiguityRate: number;
  elapsedMs: number;
}

/** §5.1 rename fork + §5.6 cycle consistency in one pass (both directions). */
export function runRenameFork(base: SynthGraph): RenameForkMetrics {
  const baseP = computeDepth2Profiles(base);
  const { fork, trueMap } = renameFork(base);
  const forkP = computeDepth2Profiles(fork);
  const forkIds = new Set(fork.objects.map((o) => o.id));
  const forkOrbit = orbitSignatures(fork, forkP);

  const t0 = Date.now();
  const fwd = functorSearch(buildSearchInput(base, baseP, fork, forkP), HIGH_SIGNAL_CFG);
  const rev = functorSearch(buildSearchInput(fork, forkP, base, baseP), HIGH_SIGNAL_CFG);
  const elapsedMs = Date.now() - t0;

  const corr = scoreCorrectness(fwd, trueMap, forkIds, forkOrbit);

  // cycle consistency G(F(s)) = s
  const g = new Map<string, string>();
  for (const m of rev.mapping) g.set(m.srcId, m.dstId);
  let cyc = 0;
  for (const m of fwd.mapping) if (g.get(m.dstId) === m.srcId) cyc++;
  const cycleConsistency = fwd.mapping.length ? cyc / fwd.mapping.length : 0;

  return {
    coverage: fwd.coverage,
    fidelity: fwd.fidelity,
    orbitCorrectness: corr.orbitCorrect,
    exactMatch: corr.exactMatch,
    orbitVsExactGap: corr.orbitCorrect - corr.exactMatch,
    cycleConsistency,
    nMapped: fwd.nMapped,
    nObjects: fwd.nObjectsSrc,
    ambiguityRate: fwd.ambiguityRate,
    elapsedMs,
  };
}

export interface AutomorphismDemoMetrics {
  orbitCorrectness: number;
  exactMatch: number;
  /** > 0 proves the WL/orbit machinery rescued a within-orbit swap that
   *  name-blind exact-match scoring would (wrongly) count as an error. */
  orbitVsExactGap: number;
  orbitSize: number;
}

/**
 * Automorphism-awareness demonstrator (§5.1 / §8.2). Builds a graph with a
 * genuine k-member structural orbit whose rename fork REVERSES the members'
 * id order, so greedy (lexicographic tie-break) maps each source to an
 * orbit-mate that is NOT its exact twin. Exact-match scoring then reports
 * errors the matcher did not make; orbit-aware scoring (one color-refinement
 * round) correctly counts them right — the gap is the machinery's value.
 */
export function runAutomorphismDemo(orbitSize = 4): AutomorphismDemoMetrics {
  // A container class C with `orbitSize` interchangeable accessor methods, all
  // reading the same field — a true automorphism orbit.
  const objects: SynthObject[] = [
    { id: "C", kind: "class" },
    { id: "C.f", kind: "field" },
  ];
  const edges: FunctorEdge[] = [];
  for (let a = 0; a < orbitSize; a++) {
    objects.push({ id: `C.acc${a}`, kind: "method" });
    edges.push({ src: "C", dst: `C.acc${a}`, kind: "CONTAINS" });
    edges.push({ src: `C.acc${a}`, dst: "C.f", kind: "READS_FIELD" });
  }
  const base: SynthGraph = { objects, edges };
  const baseP = computeDepth2Profiles(base);

  // Fork: reverse the accessor id order so the exact twin is NOT the greedy
  // lexicographic pick, but every candidate is still orbit-correct.
  const trueMap = new Map<string, string>();
  trueMap.set("C", "fk::C");
  trueMap.set("C.f", "fk::C.f");
  for (let a = 0; a < orbitSize; a++) {
    trueMap.set(`C.acc${a}`, `fk::C.acc${orbitSize - 1 - a}`);
  }
  const fork: SynthGraph = {
    objects: base.objects.map((o) => ({ id: trueMap.get(o.id)!, kind: o.kind })),
    edges: base.edges.map((e) => ({ src: trueMap.get(e.src)!, dst: trueMap.get(e.dst)!, kind: e.kind })),
  };
  const forkP = computeDepth2Profiles(fork);
  const forkIds = new Set(fork.objects.map((o) => o.id));
  const forkOrbit = orbitSignatures(fork, forkP);

  const res = functorSearch(buildSearchInput(base, baseP, fork, forkP), HIGH_SIGNAL_CFG);
  const corr = scoreCorrectness(res, trueMap, forkIds, forkOrbit);
  return {
    orbitCorrectness: corr.orbitCorrect,
    exactMatch: corr.exactMatch,
    orbitVsExactGap: corr.orbitCorrect - corr.exactMatch,
    orbitSize,
  };
}

export interface DropoutPoint {
  p: number;
  coverage: number;
  fidelity: number;
  orbitCorrectness: number;
  nMapped: number;
}

/** §5.2 edge-dropout calibration across p ∈ {0.05, 0.15, 0.30}. */
export function runDropout(base: SynthGraph, ps = [0.05, 0.15, 0.3]): DropoutPoint[] {
  const baseP = computeDepth2Profiles(base);
  const out: DropoutPoint[] = [];
  for (const p of ps) {
    const { fork, trueMap } = dropoutFork(base, p, 0xd0 + Math.round(p * 100));
    const forkP = computeDepth2Profiles(fork);
    const forkIds = new Set(fork.objects.map((o) => o.id));
    const forkOrbit = orbitSignatures(fork, forkP);
    const res = functorSearch(buildSearchInput(base, baseP, fork, forkP), HIGH_SIGNAL_CFG);
    const corr = scoreCorrectness(res, trueMap, forkIds, forkOrbit);
    out.push({
      p,
      coverage: res.coverage,
      fidelity: res.fidelity,
      orbitCorrectness: corr.orbitCorrect,
      nMapped: res.nMapped,
    });
  }
  return out;
}

export interface NullModelMetrics {
  realFidelity: number;
  realCoverage: number;
  rewireFidelity: number;
  randomMapFidelity: number;
  permutedSeedFidelity: number;
  permutedSeedCoverage: number;
  liftOverRewire: number;
  liftOverRandomMap: number;
}

/** §5.3 null model — fidelity as LIFT over degree-matched rewire + random map
 *  + permuted-seed control. */
export function runNullModel(base: SynthGraph): NullModelMetrics {
  const baseP = computeDepth2Profiles(base);
  const { fork } = renameFork(base);
  const forkP = computeDepth2Profiles(fork);

  // real functor A → fork
  const real = functorSearch(buildSearchInput(base, baseP, fork, forkP), HIGH_SIGNAL_CFG);

  // (a) degree-matched edge-rewired fork
  const rewired = degreeMatchedRewire(fork, 0x5eed);
  const rewiredP = computeDepth2Profiles(rewired);
  const rewireRes = functorSearch(
    buildSearchInput(base, baseP, rewired, rewiredP),
    HIGH_SIGNAL_CFG,
  );

  // (b) random kind-compatible object map scored directly
  const randMap = randomKindCompatibleMap(base, fork, 0xbeef);
  const randFid = computeMapFidelity(base, fork, randMap);

  // (c) permuted-seed control — real graphs, shuffled seeds
  const permP = permuteSeedProfiles(base, baseP, 0xf00d);
  const permForkP = permuteSeedProfiles(fork, forkP, 0xf11d);
  const permRes = functorSearch(
    buildSearchInput(base, permP, fork, permForkP),
    HIGH_SIGNAL_CFG,
  );

  const realFid = real.fidelity;
  const rewireFid = Math.max(0, rewireRes.fidelity);
  const randFidV = Math.max(0, randFid.fidelity);
  return {
    realFidelity: realFid,
    realCoverage: real.coverage,
    rewireFidelity: rewireRes.fidelity,
    randomMapFidelity: randFid.fidelity,
    permutedSeedFidelity: permRes.fidelity,
    permutedSeedCoverage: permRes.coverage,
    liftOverRewire: realFid - rewireFid,
    liftOverRandomMap: realFid - randFidV,
  };
}

export interface SeedDegradationPoint {
  q: number;
  orbitCorrectness: number;
  meanMarginCorrect: number;
  meanMarginWrong: number;
  marginCorrectnessSpearman: number;
}

/** §5.7 seed-degradation stress across q ∈ {0.1, 0.2, 0.3}. */
export function runSeedDegradation(
  base: SynthGraph,
  qs = [0.1, 0.2, 0.3],
): SeedDegradationPoint[] {
  const baseP = computeDepth2Profiles(base);
  const { fork, trueMap } = renameFork(base);
  const forkP = computeDepth2Profiles(fork);
  const forkIds = new Set(fork.objects.map((o) => o.id));
  const forkOrbit = orbitSignatures(fork, forkP);
  const out: SeedDegradationPoint[] = [];
  for (const q of qs) {
    const degP = degradeSeeds(base, baseP, q, 0xa0 + Math.round(q * 100));
    const res = functorSearch(buildSearchInput(base, degP, fork, forkP), HIGH_SIGNAL_CFG);
    const corr = scoreCorrectness(res, trueMap, forkIds, forkOrbit);
    out.push({
      q,
      orbitCorrectness: corr.orbitCorrect,
      meanMarginCorrect: corr.meanMarginCorrect,
      meanMarginWrong: corr.meanMarginWrong,
      marginCorrectnessSpearman: corr.marginCorrectnessSpearman,
    });
  }
  return out;
}

export interface DeterminismMetrics {
  byteIdentical: boolean;
  halvedBudgetSubset: boolean;
}

/** §5.5 determinism + anytime. */
export function runDeterminism(base: SynthGraph): DeterminismMetrics {
  const baseP = computeDepth2Profiles(base);
  const { fork } = renameFork(base);
  const forkP = computeDepth2Profiles(fork);
  const input = buildSearchInput(base, baseP, fork, forkP);
  const r1 = functorSearch(input, HIGH_SIGNAL_CFG);
  const r2 = functorSearch(input, HIGH_SIGNAL_CFG);
  const byteIdentical =
    JSON.stringify(r1.mapping) === JSON.stringify(r2.mapping) &&
    r1.coverage === r2.coverage &&
    r1.fidelity === r2.fidelity;
  const full = functorSearch(input, HIGH_SIGNAL_CFG);
  const zero = functorSearch(input, { ...HIGH_SIGNAL_CFG, budgetMs: 0 });
  return { byteIdentical, halvedBudgetSubset: zero.nMapped <= full.nMapped };
}

// ---------------------------------------------------------------------------
// §5.4 Cross-framework recall/precision (synthetic analog of the 9-cluster GT)
// ---------------------------------------------------------------------------

/**
 * Build a "framework" that shares a common role skeleton (agent, orchestrator,
 * tool, memory, task) but with framework-specific extra structure, distinct
 * ids, and a per-framework perturbation. Analogous — NOT isomorphic — to the
 * real cross-framework corpus, so recall is expected to be partial (soft
 * baseline, §5.4). Each role-bearing symbol is labeled for ground truth.
 */
export function buildFramework(name: string, variant: number): SynthGraph {
  const objects: SynthObject[] = [];
  const edges: FunctorEdge[] = [];
  const id = (s: string) => `${name}::${s}`;
  const add = (s: string, kind: string, role?: string) =>
    objects.push({ id: id(s), kind, role });
  const E = (s: string, d: string, k: string) => edges.push({ src: id(s), dst: id(d), kind: k });

  // Per-framework structural divergence — same roles, genuinely different
  // wiring, so frameworks are ANALOGOUS not isomorphic (the real cross-repo
  // case). `own` = which edge kind encodes "owns"; `memOwner` = who owns
  // Memory; variant 3 splits the orchestrator into a manager + a router.
  const own = (["CONTAINS", "REFERENCES", "INJECTS", "CONTAINS"] as const)[variant % 4]!;
  const memOwnedByOrch = variant % 2 === 1;

  // Core role skeleton
  add("Agent", "class", "agent");
  add("Orchestrator", "class", "orchestrator");
  add("Tool", "class", "tool");
  add("Memory", "class", "memory");
  add("Task", "class", "task");
  add("Agent.run", "method");
  add("Agent.callTool", "method");
  add("Orchestrator.dispatch", "method");
  add("Tool.execute", "method");
  add("Memory.read", "method");
  add("Memory.write", "method");
  add("Task.state", "field");

  E("Orchestrator", "Agent", "REFERENCES");
  E("Orchestrator", "Orchestrator.dispatch", "CONTAINS");
  E("Orchestrator.dispatch", "Agent.run", "CALLS");
  E("Agent", "Agent.run", "CONTAINS");
  E("Agent", "Agent.callTool", "CONTAINS");
  E("Agent.run", "Agent.callTool", "CALLS");
  E("Agent.callTool", "Tool.execute", "CALLS");
  E("Agent", "Tool", own); // ownership edge kind varies per framework
  E("Tool", "Tool.execute", "CONTAINS");
  E("Memory", "Memory.read", "CONTAINS");
  E("Memory", "Memory.write", "CONTAINS");
  E("Task", "Task.state", "CONTAINS");
  E("Orchestrator", "Task", "CONSTRUCTS");
  E("Agent.run", "Task", "RETURNS_TYPE");

  // Memory ownership + access wiring diverges per framework.
  if (memOwnedByOrch) {
    E("Orchestrator", "Memory", own);
    E("Orchestrator.dispatch", "Memory.read", "CALLS");
    E("Orchestrator.dispatch", "Memory.write", "CALLS");
  } else {
    E("Agent", "Memory", "TYPE_OF");
    E("Agent.run", "Memory.read", "CALLS");
    E("Agent.run", "Memory.write", "CALLS");
  }

  // variant 3: split orchestration into manager + router (role stays on the
  // primary coordinator, but the extra class perturbs neighbourhoods).
  if (variant % 4 === 3) {
    add("Router", "class");
    add("Router.route", "method");
    E("Router", "Router.route", "CONTAINS");
    E("Orchestrator", "Router", "REFERENCES");
    E("Router.route", "Agent.run", "CALLS");
  }

  // Framework-specific helper structure (further profile divergence).
  const extra = 2 + variant;
  for (let i = 0; i < extra; i++) {
    add(`Helper${i}`, "class");
    E(`Helper${i}`, "Agent", "REFERENCES");
    if (i % 2 === variant % 2) E("Agent", `Helper${i}`, "REFERENCES");
    if (i === 0) E(`Helper${i}`, "Tool", own);
  }
  return { objects, edges };
}

export interface CrossFrameworkMetrics {
  pairCount: number;
  gtPairs: number;
  recalled: number;
  recall: number;
  mappedRoleBearing: number;
  correctRole: number;
  precision: number;
  perPair: {
    a: string;
    b: string;
    gt: number;
    recalled: number;
    coverage: number;
    fidelity: number;
  }[];
}

/**
 * §5.4 cross-framework baseline: run discovery between every framework pair and
 * measure (recall) how many same-role symbol pairs land in the mapping and
 * (precision) of the role-bearing pairs mapped, how many are same-role. Soft
 * signal — reported as the tracked baseline, not gated.
 */
export function runCrossFramework(nFrameworks = 4): CrossFrameworkMetrics {
  const frameworks: { name: string; g: SynthGraph; p: Map<string, number[]> }[] = [];
  for (let i = 0; i < nFrameworks; i++) {
    const name = `fw${i}`;
    const g = buildFramework(name, i);
    frameworks.push({ name, g, p: computeDepth2Profiles(g) });
  }
  const roleOf = (g: SynthGraph): Map<string, string> => {
    const m = new Map<string, string>();
    for (const o of g.objects) if (o.role) m.set(o.id, o.role);
    return m;
  };

  let gtPairs = 0;
  let recalled = 0;
  let mappedRoleBearing = 0;
  let correctRole = 0;
  const perPair: CrossFrameworkMetrics["perPair"] = [];

  for (let i = 0; i < frameworks.length; i++) {
    for (let j = 0; j < frameworks.length; j++) {
      if (i === j) continue;
      const A = frameworks[i]!;
      const B = frameworks[j]!;
      const roleA = roleOf(A.g);
      const roleB = roleOf(B.g);
      // ground-truth same-role pairs (each role appears once per framework)
      const bByRole = new Map<string, string>();
      for (const [id, r] of roleB) bByRole.set(r, id);
      let pairGt = 0;
      let pairRec = 0;
      for (const [, r] of roleA) if (bByRole.has(r)) pairGt++;
      gtPairs += pairGt;

      // cross-framework pairs are BORDERLINE → adaptive normalization on
      const res = functorSearch(
        buildSearchInput(A.g, A.p, B.g, B.p),
        { normalize: "adaptive" },
      );
      const fMap = new Map(res.mapping.map((m) => [m.srcId, m.dstId]));
      for (const [aid, r] of roleA) {
        const mapped = fMap.get(aid);
        if (mapped === undefined) continue;
        if (roleB.has(mapped)) {
          mappedRoleBearing++;
          if (roleB.get(mapped) === r) correctRole++;
        }
        if (bByRole.get(r) === mapped) {
          pairRec++;
        }
      }
      recalled += pairRec;
      perPair.push({
        a: A.name,
        b: B.name,
        gt: pairGt,
        recalled: pairRec,
        coverage: res.coverage,
        fidelity: res.fidelity,
      });
    }
  }

  return {
    pairCount: perPair.length,
    gtPairs,
    recalled,
    recall: gtPairs ? recalled / gtPairs : 0,
    mappedRoleBearing,
    correctRole,
    precision: mappedRoleBearing ? correctRole / mappedRoleBearing : 0,
    perPair,
  };
}
