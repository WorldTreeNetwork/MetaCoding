// THROWAWAY SPIKE HARNESS — Steps 0-4 of ct-functor-discovery.md §2.2
// Measures: candidate_recall (gate), rename_fork_correctness (gate, automorphism-aware),
// ambiguity_rate, saturation. Decides greedy-vs-Hungarian, pins defaults.
// Run: bun harness.ts <base-datadir> <fork-datadir> [--qprefix app/] [--degrade q]
// NOT production code.

import { readFileSync } from "node:fs";

// ---------------- config / defaults under test ----------------
const DEFAULTS = {
  k_seed: 10,
  k_wide: 25,
  tau_seed: 0.30,      // max cosine DISTANCE for a candidate
  delta_flat: 0.05,
  delta_rel: 0.05,
  alpha: 0.3,
  rounds: 8,
  beta: 0.25,
  eps_prune: 0.05,
  delta_amb: 0.02,
  conv_tol: 1e-3,
};

const args = process.argv.slice(2);
const baseDir = args[0];
const forkDir = args[1];
function flag(name: string, def: string): string {
  const i = args.indexOf(name);
  return i >= 0 ? args[i + 1] : def;
}
// ground-truth qn transform base->fork. Default: src/ -> lib/ (the path rename),
// identity otherwise. Overridable as --rename FROM:TO (prefix swap).
const RENAME = flag("--rename", "src/:lib/");
const [RFROM, RTO] = RENAME.split(":");
function qnTransform(qn: string): string { return qn.startsWith(RFROM) ? RTO + qn.slice(RFROM.length) : qn; }
const DEGRADE = parseFloat(flag("--degrade", "0")); // fraction of base profiles collapsed onto a neighbor
const K_SEED = parseInt(flag("--k_seed", String(DEFAULTS.k_seed)));
const ALPHA = parseFloat(flag("--alpha", String(DEFAULTS.alpha)));
const ROUNDS = parseInt(flag("--rounds", String(DEFAULTS.rounds)));
const BETA = parseFloat(flag("--beta", String(DEFAULTS.beta)));
const TAU = parseFloat(flag("--tau", String(DEFAULTS.tau_seed)));
const NORMALIZE = flag("--normalize", "sinkhorn"); // sinkhorn | none
const SEED = parseInt(flag("--seed", "42"));
const BLOCK = flag("--block", "fixedk"); // fixedk | relcut
const DELTA_REL = parseFloat(flag("--delta_rel", "0.02"));
const CAP = parseInt(flag("--cap", "400"));

// ---------------- types ----------------
interface Node { id: string; qn: string; kind: string; vec: Float64Array; }
type Dir = 0 | 1; // 0=out, 1=in
interface Edge { kind: string; }

// deterministic RNG (mulberry32)
function rng(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0; a = (a + 0x6D2B79F5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

// ---------------- load ----------------
function loadProfiles(dir: string): Map<string, Node> {
  const m = new Map<string, Node>();
  const txt = readFileSync(`${dir}/ctkr/profiles.jsonl`, "utf8");
  for (const line of txt.split("\n")) {
    if (!line.trim()) continue;
    const o = JSON.parse(line);
    if (o.kind === "file") continue; // hom-profile filter already excludes; guard
    m.set(o.symbol_id, { id: o.symbol_id, qn: o.qualified_name, kind: o.kind, vec: Float64Array.from(o.profile_vec) });
  }
  return m;
}

function loadEdges(dir: string, objs: Map<string, Node>) {
  // adjacency: per source id -> list of {kind, dir, other}. Only internal (both endpoints objects).
  const adj = new Map<string, { kind: string; dir: Dir; other: string }[]>();
  const kindFreq = new Map<string, number>();
  let nInternal = 0;
  const txt = readFileSync(`${dir}/ctkr/export/edges.jsonl`, "utf8");
  for (const line of txt.split("\n")) {
    if (!line.trim()) continue;
    const e = JSON.parse(line);
    if (!objs.has(e.src_id) || !objs.has(e.dst_id)) continue; // internal only
    nInternal++;
    kindFreq.set(e.kind, (kindFreq.get(e.kind) || 0) + 1);
    // out edge from src
    if (!adj.has(e.src_id)) adj.set(e.src_id, []);
    adj.get(e.src_id)!.push({ kind: e.kind, dir: 0, other: e.dst_id });
    // in edge to dst
    if (!adj.has(e.dst_id)) adj.set(e.dst_id, []);
    adj.get(e.dst_id)!.push({ kind: e.kind, dir: 1, other: e.src_id });
  }
  // determinism: sort each adjacency list by (kind, dir, other)
  for (const [, lst] of adj) lst.sort((a, b) => a.kind < b.kind ? -1 : a.kind > b.kind ? 1 : a.dir - b.dir || (a.other < b.other ? -1 : a.other > b.other ? 1 : 0));
  return { adj, kindFreq, nInternal };
}

// target-side edge existence: for fork, set of "t|kind|dir|t2" for O(1) witness lookup
function buildEdgeSet(adj: Map<string, { kind: string; dir: Dir; other: string }[]>): Set<string> {
  const s = new Set<string>();
  for (const [src, lst] of adj) for (const e of lst) s.add(`${src}|${e.kind}|${e.dir}|${e.other}`);
  return s;
}

// ---------------- kind blocking ----------------
function kindGroup(k: string): string {
  if (k === "function" || k === "method") return "callable";
  if (k === "class" || k === "interface" || k === "type_alias") return "type";
  if (k === "field") return "field";
  return "other:" + k;
}

// ---------------- cosine ----------------
function norm(v: Float64Array): number { let s = 0; for (let i = 0; i < v.length; i++) s += v[i] * v[i]; return Math.sqrt(s); }
function cosine(a: Float64Array, an: number, b: Float64Array, bn: number): number {
  if (an === 0 || bn === 0) return 0;
  let d = 0; for (let i = 0; i < a.length; i++) d += a[i] * b[i];
  const c = d / (an * bn); return c < 0 ? 0 : c > 1 ? 1 : c;
}

function main() {
  const t0 = Date.now();
  const base = loadProfiles(baseDir);
  const fork = loadProfiles(forkDir);
  const baseE = loadEdges(baseDir, base);
  const forkE = loadEdges(forkDir, fork);
  const forkEdgeSet = buildEdgeSet(forkE.adj);

  // ---------- fork automorphism-orbit signatures (one WL / color-refinement round) ----------
  // color0 = kind + profile hash; orbit sig = (color0, sorted (kind,dir,neighbor color0)).
  const vecHash = (v: Float64Array) => v.join(",");
  const forkColor0 = new Map<string, string>();
  for (const [id, n] of fork) forkColor0.set(id, n.kind + "#" + vecHash(n.vec));
  const forkOrbit = new Map<string, string>();
  for (const [id] of fork) {
    const nbrs = forkE.adj.get(id) || [];
    const parts = nbrs.map(e => `${e.kind}:${e.dir}:${forkColor0.get(e.other) ?? "x"}`).sort();
    forkOrbit.set(id, forkColor0.get(id) + "||" + parts.join(";"));
  }
  // orbit -> member fork ids (for orbit-aware recall)
  const orbitMembers = new Map<string, Set<string>>();
  for (const [id, o] of forkOrbit) { if (!orbitMembers.has(o)) orbitMembers.set(o, new Set()); orbitMembers.get(o)!.add(id); }

  // ground-truth bijection base -> fork via qn prefix
  const forkByQn = new Map<string, string>();
  for (const [, n] of fork) forkByQn.set(n.qn, n.id);
  const trueTwin = new Map<string, string>(); // baseId -> forkId
  for (const [bid, bn] of base) {
    const fid = forkByQn.get(qnTransform(bn.qn));
    if (fid) trueTwin.set(bid, fid);
  }

  // ---------- optional seed degradation (§5.7 BORDERLINE simulation) ----------
  // Collapse a fraction q of base profiles onto their nearest same-group neighbor's vector.
  const rand = rng(SEED);
  if (DEGRADE > 0) {
    const ids = [...base.keys()].sort();
    const byGroup = new Map<string, Node[]>();
    for (const id of ids) { const n = base.get(id)!; const g = kindGroup(n.kind); if (!byGroup.has(g)) byGroup.set(g, []); byGroup.get(g)!.push(n); }
    for (const id of ids) {
      if (rand() >= DEGRADE) continue;
      const n = base.get(id)!;
      const pool = byGroup.get(kindGroup(n.kind))!;
      const nn = norm(n.vec);
      let best = -1, bestSim = -1;
      for (let j = 0; j < pool.length; j++) { const m = pool[j]; if (m.id === id) continue; const c = cosine(n.vec, nn, m.vec, norm(m.vec)); if (c > bestSim) { bestSim = c; best = j; } }
      if (best >= 0) n.vec = Float64Array.from(pool[best].vec); // collapse onto neighbor
    }
  }

  const baseNorms = new Map<string, number>(); for (const [id, n] of base) baseNorms.set(id, norm(n.vec));
  const forkNorms = new Map<string, number>(); for (const [id, n] of fork) forkNorms.set(id, norm(n.vec));

  // bucket fork by kind-group for blocking
  const forkByGroup = new Map<string, Node[]>();
  for (const [, n] of fork) { const g = kindGroup(n.kind); if (!forkByGroup.has(g)) forkByGroup.set(g, []); forkByGroup.get(g)!.push(n); }
  for (const [, l] of forkByGroup) l.sort((a, b) => a.id < b.id ? -1 : 1);

  // ---------- Step 1: candidate blocking (KNN) ----------
  const cand = new Map<string, { t: string; sim: number }[]>();
  const seedMargin = new Map<string, number>();
  const baseIds = [...base.keys()].sort();
  for (const sid of baseIds) {
    const s = base.get(sid)!;
    const pool = forkByGroup.get(kindGroup(s.kind)) || [];
    const sn = baseNorms.get(sid)!;
    const scored: { t: string; sim: number }[] = [];
    for (const t of pool) {
      const c = cosine(s.vec, sn, t.vec, forkNorms.get(t.id)!);
      const dist = 1 - c;
      if (dist <= TAU) scored.push({ t: t.id, sim: c });
    }
    // sort by sim desc, tie-break by id for determinism
    scored.sort((a, b) => b.sim - a.sim || (a.t < b.t ? -1 : 1));
    let top: { t: string; sim: number }[];
    if (BLOCK === "relcut") {
      // §2.2 prescribed relative cut: keep every candidate within delta_rel of the best,
      // i.e. the WHOLE max-similarity tied block, capped at CAP to bound propagation cost.
      const cut = scored.length ? scored[0].sim - DELTA_REL : 0;
      top = scored.filter(c => c.sim >= cut).slice(0, CAP);
      if (top.length < K_SEED) top = scored.slice(0, K_SEED); // floor
    } else {
      // fixed-k with flat-region adaptive widening
      let k = K_SEED;
      if (scored.length > K_SEED) {
        const flat = scored[0].sim - scored[Math.min(K_SEED, scored.length) - 1].sim;
        if (flat < DEFAULTS.delta_flat) k = DEFAULTS.k_wide;
      }
      top = scored.slice(0, k);
    }
    cand.set(sid, top);
    // seed margin m(s) = d(2)-d(1) = sim(1)-sim(2)
    seedMargin.set(sid, top.length >= 2 ? top[0].sim - top[1].sim : (top.length === 1 ? 1.0 : 0));
  }

  // ---------- candidate_recall (THE GATE) ----------
  // Separate the honest partiality frontier: symbols with a zero profile vector have
  // NO structural signature and cannot be blocked by any name-blind method. Report
  // recall both over all GT pairs and over structurally-signalled (non-zero) pairs.
  let gtEligible = 0, recovered = 0, noCand = 0;
  let gtNonzero = 0, recoveredNonzero = 0, zeroProfile = 0;
  let recoveredOrbit = 0, recoveredOrbitNonzero = 0;
  for (const sid of baseIds) {
    const tw = trueTwin.get(sid);
    if (!tw) continue;
    if (!fork.has(tw)) continue;
    gtEligible++;
    const c = cand.get(sid)!;
    const hit = c.some(x => x.t === tw);
    // orbit-aware: some candidate lies in the true twin's automorphism orbit
    const twOrbit = forkOrbit.get(tw);
    const hitOrbit = c.some(x => forkOrbit.get(x.t) === twOrbit);
    if (c.length === 0) noCand++;
    if (hit) recovered++;
    if (hitOrbit) recoveredOrbit++;
    const nz = baseNorms.get(sid)! > 0;
    if (!nz) zeroProfile++;
    if (nz) { gtNonzero++; if (hit) recoveredNonzero++; if (hitOrbit) recoveredOrbitNonzero++; }
  }
  const candidate_recall = gtEligible ? recovered / gtEligible : 0;
  const candidate_recall_nonzero = gtNonzero ? recoveredNonzero / gtNonzero : 0;
  const candidate_recall_orbit = gtEligible ? recoveredOrbit / gtEligible : 0;
  const candidate_recall_orbit_nonzero = gtNonzero ? recoveredOrbitNonzero / gtNonzero : 0;

  // ---------- Step 2: similarity flooding ----------
  // kind-discriminativeness weights w_k ∝ 1/log(2+freq_k), normalized to mean 1
  const kindW = new Map<string, number>();
  { let tot = 0, cnt = 0; for (const [k, f] of baseE.kindFreq) { const w = 1 / Math.log(2 + f); kindW.set(k, w); tot += w; cnt++; } const mean = tot / Math.max(1, cnt); for (const [k, w] of kindW) kindW.set(k, w / mean); }

  // flatten candidate pairs into arrays for the iteration
  // sigma stored in a Map keyed "sid|tid"
  const key = (s: string, t: string) => `${s}|${t}`;
  const sigma0 = new Map<string, number>();
  let sigma = new Map<string, number>();
  for (const sid of baseIds) for (const c of cand.get(sid)!) { sigma0.set(key(sid, c.t), c.sim); sigma.set(key(sid, c.t), c.sim); }

  // helper: does fork have edge t --kind,dir--> t2 ?
  const witness = (t: string, kind: string, dir: Dir, t2: string) => forkEdgeSet.has(`${t}|${kind}|${dir}|${t2}`);

  // fast index: forkAdjByKD[t]["kind|dir"] = list of fork neighbors (bounds inner loop by fork degree, not cand size)
  const forkAdjByKD = new Map<string, Map<string, string[]>>();
  for (const [t, lst] of forkE.adj) { const mm = new Map<string, string[]>(); for (const e of lst) { const kk = `${e.kind}|${e.dir}`; if (!mm.has(kk)) mm.set(kk, []); mm.get(kk)!.push(e.other); } forkAdjByKD.set(t, mm); }
  // candidate membership sets per source
  const candSet = new Map<string, Set<string>>();
  for (const sid of baseIds) candSet.set(sid, new Set(cand.get(sid)!.map(c => c.t)));

  let converged = false, roundsRun = 0;
  for (let r = 0; r < ROUNDS; r++) {
    roundsRun = r + 1;
    const next = new Map<string, number>();
    let maxDelta = 0;
    for (const sid of baseIds) {
      const cs = cand.get(sid)!;
      if (cs.length === 0) continue;
      const nbrs = baseE.adj.get(sid) || [];
      const degN = nbrs.length; // |N(s)| counts every typed edge (conservative bias)
      const m = seedMargin.get(sid)!;
      const alphaEff = ALPHA * (0.5 + 0.5 * Math.min(1, m / DEFAULTS.delta_flat));
      for (const c of cs) {
        const t = c.t;
        let acc = 0;
        if (degN > 0) {
          for (const e of nbrs) {
            const w = kindW.get(e.kind) ?? 1;
            const cprimeSet = candSet.get(e.other);
            if (!cprimeSet || cprimeSet.size === 0) continue; // contributes 0
            // fork neighbors of t along same (kind,dir); intersect with cand(s') — bounded by fork degree
            const fnbrs = forkAdjByKD.get(t)?.get(`${e.kind}|${e.dir}`);
            if (!fnbrs) continue;
            let best = 0;
            for (const t2 of fnbrs) {
              if (cprimeSet.has(t2)) {
                const sv = sigma.get(key(e.other, t2)) ?? 0;
                if (sv > best) best = sv;
              }
            }
            acc += w * best;
          }
          acc /= degN;
        }
        const val = alphaEff * sigma0.get(key(sid, t))! + (1 - ALPHA) * acc;
        next.set(key(sid, t), val);
        const d = Math.abs(val - (sigma.get(key(sid, t)) ?? 0));
        if (d > maxDelta) maxDelta = d;
      }
    }
    // ---- competitive normalization (Sinkhorn-style) on a COPY (keep pre-norm as evidence) ----
    let norm = next;
    if (NORMALIZE === "sinkhorn") {
      norm = new Map(next);
      // source-side L1
      for (const sid of baseIds) {
        const cs = cand.get(sid)!; let s = 0; for (const c of cs) s += norm.get(key(sid, c.t)) ?? 0;
        if (s > 0) for (const c of cs) norm.set(key(sid, c.t), (norm.get(key(sid, c.t)) ?? 0) / s);
      }
      // target-side L1
      const byTarget = new Map<string, string[]>();
      for (const sid of baseIds) for (const c of cand.get(sid)!) { if (!byTarget.has(c.t)) byTarget.set(c.t, []); byTarget.get(c.t)!.push(sid); }
      for (const [t, srcs] of byTarget) { let s = 0; for (const sc of srcs) s += norm.get(key(sc, t)) ?? 0; if (s > 0) for (const sc of srcs) norm.set(key(sc, t), (norm.get(key(sc, t)) ?? 0) / s); }
    }
    sigma = norm; // dynamics use normalized; but we keep next (pre-norm) for emission at the end
    // stash pre-norm converged values
    for (const [k, v] of next) sigma0PostRound.set(k, v);
    if (maxDelta < DEFAULTS.conv_tol) { converged = true; break; }
  }

  // arc-consistency prune (post-hoc, single pass) — drop low sigma / weak witness support
  // (applied to the emission/extraction candidate set)
  const survive = new Map<string, { t: string; sig: number; pre: number }[]>();
  for (const sid of baseIds) {
    const cs = cand.get(sid)!;
    const nbrs = baseE.adj.get(sid) || [];
    const deg = nbrs.length;
    const need = Math.ceil(BETA * deg);
    const kept: { t: string; sig: number; pre: number }[] = [];
    for (const c of cs) {
      const sg = sigma.get(key(sid, c.t)) ?? 0;
      if (sg < DEFAULTS.eps_prune / Math.max(1, cs.length)) continue; // eps scaled since sinkhorn shrinks magnitudes
      // witness support count (fast: fork neighbors of c.t intersect cand(s'))
      let supported = 0;
      for (const e of nbrs) {
        const cprimeSet = candSet.get(e.other); if (!cprimeSet) continue;
        const fnbrs = forkAdjByKD.get(c.t)?.get(`${e.kind}|${e.dir}`);
        if (fnbrs && fnbrs.some(t2 => cprimeSet.has(t2))) supported++;
      }
      if (deg > 0 && supported < need) continue;
      kept.push({ t: c.t, sig: sg, pre: sigma0PostRound.get(key(sid, c.t)) ?? c.sim });
    }
    if (kept.length === 0 && cs.length > 0) {
      // keep best to allow partiality-but-not-total-drop; recorded
      const best = cs.map(c => ({ t: c.t, sig: sigma.get(key(sid, c.t)) ?? 0, pre: sigma0PostRound.get(key(sid, c.t)) ?? c.sim })).sort((a, b) => b.sig - a.sig)[0];
      // only keep if above absolute floor
      if (best && best.sig > 0) kept.push(best);
    }
    survive.set(sid, kept);
  }

  // ---------- Step 3: greedy extraction ----------
  // sort all surviving pairs by PRE-normalization converged sigma desc (the emitted
  // evidence per §2.2 hardening 1), tie-break lex for determinism.
  const allPairs: { s: string; t: string; sig: number }[] = [];
  for (const sid of baseIds) for (const c of survive.get(sid)!) allPairs.push({ s: sid, t: c.t, sig: c.pre });
  allPairs.sort((a, b) => b.sig - a.sig || (a.s < b.s ? -1 : a.s > b.s ? 1 : (a.t < b.t ? -1 : a.t > b.t ? 1 : 0)));
  const claimedS = new Set<string>(), claimedT = new Set<string>();
  const mapping = new Map<string, { t: string; sig: number; margin: number }>();
  for (const p of allPairs) {
    if (claimedS.has(p.s) || claimedT.has(p.t)) continue;
    // margin = sig - best unaccepted alt for same source among survivors (pre-norm)
    const alts = survive.get(p.s)!.filter(c => c.t !== p.t).map(c => c.pre);
    const bestAlt = alts.length ? Math.max(...alts) : -1;
    const margin = bestAlt < 0 ? 1.0 : p.sig - bestAlt;
    mapping.set(p.s, { t: p.t, sig: p.sig, margin });
    claimedS.add(p.s); claimedT.add(p.t);
  }

  // ---------- ambiguity rate ----------
  let lowMargin = 0;
  for (const [, v] of mapping) if (v.margin < DEFAULTS.delta_amb) lowMargin++;
  const ambiguity_rate = mapping.size ? lowMargin / mapping.size : 0;

  // ---------- Step 4: fidelity + rename_fork_correctness ----------
  // (fork orbit signatures computed once near the top and reused here)
  let exact = 0, orbitCorrect = 0, scored = 0;
  let edgesInternal = 0, edgesPreserved = 0;
  const dom = new Set([...mapping.keys()]);
  const marginCorrect: number[] = [], marginWrong: number[] = [];
  const marginArr: number[] = [], correctArr: number[] = [];
  for (const [sid, v] of mapping) {
    const tw = trueTwin.get(sid);
    if (tw && fork.has(tw)) {
      scored++;
      if (v.t === tw) exact++;
      const ok = forkOrbit.get(v.t) === forkOrbit.get(tw);
      if (ok) orbitCorrect++;
      (ok ? marginCorrect : marginWrong).push(v.margin);
      marginArr.push(v.margin); correctArr.push(ok ? 1 : 0);
    }
  }
  const rename_fork_correctness = scored ? orbitCorrect / scored : 0;
  const exact_match = scored ? exact / scored : 0;
  const mean = (a: number[]) => a.length ? a.reduce((x, y) => x + y, 0) / a.length : 0;
  // §5.7 honest-signal check: correct pairs should carry higher margin than wrong ones,
  // and margin should correlate with correctness (point-biserial ~ spearman on 0/1).
  const margin_honesty = {
    mean_margin_correct: mean(marginCorrect), mean_margin_wrong: mean(marginWrong),
    margin_correctness_spearman: spearmanCorr(marginArr, correctArr),
  };

  // functor fidelity: internal edges of base with both endpoints in dom(F), preserved iff witness in fork
  const Fmap = new Map<string, string>(); for (const [s, v] of mapping) Fmap.set(s, v.t);
  const seenEdge = new Set<string>();
  for (const [sid, lst] of baseE.adj) {
    if (!dom.has(sid)) continue;
    for (const e of lst) {
      if (e.dir !== 0) continue; // count each undirected edge once via out-direction
      if (!dom.has(e.other)) continue;
      const ek = `${sid}|${e.kind}|${e.other}`; if (seenEdge.has(ek)) continue; seenEdge.add(ek);
      edgesInternal++;
      if (witness(Fmap.get(sid)!, e.kind, 0, Fmap.get(e.other)!)) edgesPreserved++;
    }
  }
  const fidelity = edgesInternal ? edgesPreserved / edgesInternal : -1;
  const coverage = base.size ? mapping.size / base.size : 0;

  // ---------- saturation: rank corr of converged (pre-norm) sigma vs sigma0 over accepted ----------
  const paired: { a: number; b: number }[] = [];
  for (const [sid, v] of mapping) { const c0 = cand.get(sid)!.find(c => c.t === v.t); if (c0) paired.push({ a: c0.sim, b: v.sig }); }
  const spearman = spearmanCorr(paired.map(p => p.a), paired.map(p => p.b));

  // ---------- Hungarian vs greedy comparison (per connected component) ----------
  const hung = hungarianCompare(survive, trueTwin, fork, forkOrbit, base);

  const elapsed = (Date.now() - t0) / 1000;
  const out = {
    params: { K_SEED, ALPHA, ROUNDS, BETA, TAU, NORMALIZE, DEGRADE, SEED, BLOCK, DELTA_REL, CAP },
    corpus: {
      base_objects: base.size, fork_objects: fork.size,
      base_internal_edges: baseE.nInternal, fork_internal_edges: forkE.nInternal,
      gt_bijection_pairs: gtEligible, base_no_candidate: noCand,
      gt_nonzero_profile: gtNonzero, zero_profile_gt: zeroProfile,
    },
    candidate_recall,
    candidate_recall_nonzero,
    candidate_recall_orbit,
    candidate_recall_orbit_nonzero,
    rename_fork_correctness, exact_match,
    orbit_vs_exact_gap: rename_fork_correctness - exact_match,
    ambiguity_rate,
    coverage, fidelity, edges_internal: edgesInternal, edges_preserved: edgesPreserved,
    saturation_spearman_sigma_vs_sigma0: spearman,
    margin_honesty,
    rounds_run: roundsRun, converged,
    mapping_size: mapping.size,
    greedy_vs_hungarian: hung,
    elapsed_s: elapsed,
  };
  console.log(JSON.stringify(out, null, 2));
}

// stash for pre-normalization converged sigma
const sigma0PostRound = new Map<string, number>();

function spearmanCorr(x: number[], y: number[]): number {
  const n = x.length; if (n < 2) return 1;
  const rank = (arr: number[]) => { const idx = arr.map((v, i) => [v, i] as [number, number]).sort((a, b) => a[0] - b[0]); const r = new Array(n); let i = 0; while (i < n) { let j = i; while (j + 1 < n && idx[j + 1][0] === idx[i][0]) j++; const avg = (i + j) / 2; for (let k = i; k <= j; k++) r[idx[k][1]] = avg; i = j + 1; } return r; };
  const rx = rank(x), ry = rank(y);
  const mx = rx.reduce((a, b) => a + b, 0) / n, my = ry.reduce((a, b) => a + b, 0) / n;
  let num = 0, dx = 0, dy = 0;
  for (let i = 0; i < n; i++) { const a = rx[i] - mx, b = ry[i] - my; num += a * b; dx += a * a; dy += b * b; }
  return dx === 0 || dy === 0 ? 1 : num / Math.sqrt(dx * dy);
}

// Per-connected-component: compare greedy vs exact max-weight (Hungarian) on ORBIT correctness.
function hungarianCompare(
  survive: Map<string, { t: string; sig: number; pre: number }[]>,
  trueTwin: Map<string, string>, fork: Map<string, Node>, forkOrbit: Map<string, string>, base: Map<string, Node>
) {
  // build bipartite graph, find connected components
  const adjS = survive;
  const tToS = new Map<string, string[]>();
  for (const [s, lst] of adjS) for (const c of lst) { if (!tToS.has(c.t)) tToS.set(c.t, []); tToS.get(c.t)!.push(s); }
  const seenS = new Set<string>();
  let greedyCorrect = 0, hungCorrect = 0, scored = 0, greedyWeight = 0, hungWeight = 0, ncomp = 0, maxComp = 0, lowMarginComps = 0;
  const sids = [...adjS.keys()].sort();
  for (const start of sids) {
    if (seenS.has(start) || adjS.get(start)!.length === 0) continue;
    // BFS component
    const compS: string[] = [], compT = new Set<string>();
    const stack = [start]; seenS.add(start);
    while (stack.length) {
      const s = stack.pop()!; compS.push(s);
      for (const c of adjS.get(s)!) { if (!compT.has(c.t)) { compT.add(c.t); for (const s2 of (tToS.get(c.t) || [])) if (!seenS.has(s2)) { seenS.add(s2); stack.push(s2); } } }
    }
    ncomp++; if (compS.length > maxComp) maxComp = compS.length;
    const Ts = [...compT].sort();
    const tIdx = new Map(Ts.map((t, i) => [t, i]));
    // greedy within component
    const pairs: { s: string; t: string; w: number }[] = [];
    for (const s of compS) for (const c of adjS.get(s)!) pairs.push({ s, t: c.t, w: c.pre });
    pairs.sort((a, b) => b.w - a.w || (a.s < b.s ? -1 : 1) || (a.t < b.t ? -1 : 1));
    const gS = new Set<string>(), gT = new Set<string>(); const gMap = new Map<string, string>();
    for (const p of pairs) { if (gS.has(p.s) || gT.has(p.t)) continue; gMap.set(p.s, p.t); gS.add(p.s); gT.add(p.t); }
    // hungarian (max weight) — only for small components; else reuse greedy
    let hMap: Map<string, string>;
    if (compS.length <= 60 && Ts.length <= 60) hMap = hungarianMaxWeight(compS, Ts, tIdx, adjS);
    else hMap = gMap;
    // score both on orbit correctness over gt pairs in component
    let compLowMargin = false;
    for (const s of compS) {
      const tw = trueTwin.get(s);
      if (!tw || !fork.has(tw)) continue;
      scored++;
      const g = gMap.get(s), h = hMap.get(s);
      if (g && forkOrbit.get(g) === forkOrbit.get(tw)) greedyCorrect++;
      if (h && forkOrbit.get(h) === forkOrbit.get(tw)) hungCorrect++;
      if (g) greedyWeight += (adjS.get(s)!.find(c => c.t === g)?.pre ?? 0);
      if (h) hungWeight += (adjS.get(s)!.find(c => c.t === h)?.pre ?? 0);
    }
    if (compS.length > 1) { /* multi-node comps are where ties matter */ }
  }
  return {
    n_components: ncomp, max_component_size: maxComp,
    greedy_orbit_correct: scored ? greedyCorrect / scored : 0,
    hungarian_orbit_correct: scored ? hungCorrect / scored : 0,
    greedy_total_weight: greedyWeight, hungarian_total_weight: hungWeight,
    weight_gap: hungWeight - greedyWeight,
    scored_pairs: scored,
  };
}

// simple Hungarian for max-weight bipartite matching (dense, small n). Returns s->t map.
function hungarianMaxWeight(
  S: string[], T: string[], tIdx: Map<string, number>,
  adjS: Map<string, { t: string; sig: number; pre: number }[]>
): Map<string, string> {
  const n = S.length, m = T.length;
  const size = Math.max(n, m);
  const NEG = -1e9;
  // cost matrix as MINIMIZATION of negative weight
  const w: number[][] = Array.from({ length: size }, () => new Array(size).fill(0));
  for (let i = 0; i < n; i++) for (const c of adjS.get(S[i])!) { const j = tIdx.get(c.t)!; w[i][j] = c.pre; }
  // convert to cost = maxW - w
  let maxW = 0; for (let i = 0; i < size; i++) for (let j = 0; j < size; j++) if (w[i][j] > maxW) maxW = w[i][j];
  const cost: number[][] = Array.from({ length: size }, (_, i) => Array.from({ length: size }, (_, j) => maxW - w[i][j]));
  // Hungarian O(n^3) (Jonker-ish via potentials)
  const u = new Array(size + 1).fill(0), v = new Array(size + 1).fill(0), p = new Array(size + 1).fill(0), way = new Array(size + 1).fill(0);
  for (let i = 1; i <= size; i++) {
    p[0] = i; let j0 = 0;
    const minv = new Array(size + 1).fill(Infinity); const used = new Array(size + 1).fill(false);
    do {
      used[j0] = true; const i0 = p[j0]; let delta = Infinity, j1 = -1;
      for (let j = 1; j <= size; j++) if (!used[j]) { const cur = cost[i0 - 1][j - 1] - u[i0] - v[j]; if (cur < minv[j]) { minv[j] = cur; way[j] = j0; } if (minv[j] < delta) { delta = minv[j]; j1 = j; } }
      for (let j = 0; j <= size; j++) if (used[j]) { u[p[j]] += delta; v[j] -= delta; } else minv[j] -= delta;
      j0 = j1;
    } while (p[j0] !== 0);
    do { const j1 = way[j0]; p[j0] = p[j1]; j0 = j1; } while (j0);
  }
  const res = new Map<string, string>();
  for (let j = 1; j <= size; j++) { const i = p[j]; if (i >= 1 && i <= n && j <= m) { const si = S[i - 1]; const tj = T[j - 1]; if (adjS.get(si)!.some(c => c.t === tj)) res.set(si, tj); } }
  return res;
}

main();
