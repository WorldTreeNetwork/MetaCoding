/**
 * Observatory compute worker — the dials' engine.
 *
 * Mirrors the Python ctkr semantics so what you feel here is what the
 * pipeline does:
 *  - Islands: Louvain over the selected edge alphabet with the
 *    contains/references weights (ctkr/ctkr/subsystems.py).
 *  - Roles: L1-normalize the hom-profile restricted to the enabled
 *    alphabet, quantize at granularity k, same key = same role
 *    (ctkr/ctkr/label_roles.py).
 *  - Entropy: H = -Σ p·log2 p over the role-key distribution + top-5
 *    coverage, gates at 4.0 bits / 50% / 70%
 *    (ctkr/ctkr/commands/entropy_check.py).
 *  - Twins: name-blind cosine KNN over hom-profiles with the ambiguity
 *    margin surfaced (src/mcp/ctkr-tools.ts role_equivalent).
 */
/// <reference lib="webworker" />
import Graph from "graphology";
import louvain from "graphology-communities-louvain";

declare const self: DedicatedWorkerGlobalScope;

type Edge = { s: string; t: string; k: string; c: number };

let ids: string[] = [];
let idIdx = new Map<string, number>();
let vecs: Float64Array = new Float64Array(0);
let ndim = 30;
let dims: string[] = [];
let edges: Edge[] = [];
let nodeIds: string[] = [];

function buildRoleKeys(alphabetDims: number[], k: number): string[] {
  const keys = new Array<string>(ids.length);
  const buf = new Array<number>(alphabetDims.length);
  for (let i = 0; i < ids.length; i++) {
    const base = i * ndim;
    let sum = 0;
    for (let d = 0; d < alphabetDims.length; d++) {
      const v = vecs[base + alphabetDims[d]!]!;
      buf[d] = v;
      sum += v;
    }
    if (sum === 0) {
      keys[i] = "∅";
      continue;
    }
    let key = "";
    for (let d = 0; d < alphabetDims.length; d++) {
      key += Math.round((buf[d]! / sum) * k) + ",";
    }
    keys[i] = key;
  }
  return keys;
}

function entropyOf(keys: string[]): { H: number; top5: number; nClasses: number } {
  const counts = new Map<string, number>();
  for (const key of keys) counts.set(key, (counts.get(key) ?? 0) + 1);
  const n = keys.length;
  let H = 0;
  for (const c of counts.values()) {
    const p = c / n;
    H -= p * Math.log2(p);
  }
  const sorted = [...counts.values()].sort((a, b) => b - a);
  const top5 = sorted.slice(0, 5).reduce((a, b) => a + b, 0) / n;
  return { H, top5, nClasses: counts.size };
}

self.onmessage = (ev: MessageEvent) => {
  const msg = ev.data;

  if (msg.type === "init") {
    ids = msg.profiles.ids;
    dims = msg.profiles.dims;
    ndim = msg.profiles.ndim;
    vecs = new Float64Array(msg.profiles.vecs);
    idIdx = new Map(ids.map((id, i) => [id, i]));
    edges = msg.edges;
    nodeIds = msg.nodeIds;
    self.postMessage({ type: "ready" });
    return;
  }

  if (msg.type === "compute") {
    const t0 = performance.now();
    const alphabet: Set<string> = new Set(msg.alphabet);
    const { containsWeight, referencesWeight, resolution, k } = msg;

    // --- Islands: Louvain on the enabled alphabet ---
    const g = new Graph({ type: "undirected", multi: false });
    for (const id of nodeIds) g.addNode(id);
    for (const e of edges) {
      if (!alphabet.has(e.k)) continue;
      const w =
        e.k === "CONTAINS"
          ? containsWeight
          : e.k === "REFERENCES"
            ? referencesWeight
            : 1;
      if (w <= 0) continue;
      if (e.s === e.t) continue;
      if (g.hasEdge(e.s, e.t)) {
        g.updateEdgeAttribute(e.s, e.t, "weight", (x: number) => x + w);
      } else {
        g.addEdge(e.s, e.t, { weight: w });
      }
    }
    const partition: Record<string, number> = louvain(g, {
      resolution,
      getEdgeWeight: "weight",
      rng: mulberry32(42),
    });

    // Rank communities by size; stable palette assignment downstream.
    const commSizes = new Map<number, number>();
    for (const id of nodeIds) {
      const c = partition[id];
      commSizes.set(c, (commSizes.get(c) ?? 0) + 1);
    }
    const rank = new Map<number, number>();
    [...commSizes.entries()]
      .sort((a, b) => b[1] - a[1])
      .forEach(([c], i) => rank.set(c, i));
    const communities: Record<string, number> = {};
    for (const id of nodeIds) communities[id] = rank.get(partition[id])!;
    const communitySizes = [...commSizes.entries()]
      .map(([c, n]) => ({ rank: rank.get(c)!, n }))
      .sort((a, b) => a.rank - b.rank);

    // --- Roles + entropy curve over the same alphabet ---
    const alphabetDims: number[] = [];
    dims.forEach((label, i) => {
      if (alphabet.has(label.split(":")[0])) alphabetDims.push(i);
    });
    const curve: { k: number; H: number; top5: number; nClasses: number }[] = [];
    let rolesAtK: string[] = [];
    for (let kk = 1; kk <= 12; kk++) {
      const keys = buildRoleKeys(alphabetDims, kk);
      curve.push({ k: kk, ...entropyOf(keys) });
      if (kk === k) rolesAtK = keys;
    }
    // Map role keys to frequency-ranked class indices.
    const roleCounts = new Map<string, number>();
    for (const key of rolesAtK) roleCounts.set(key, (roleCounts.get(key) ?? 0) + 1);
    const roleRank = new Map<string, number>();
    [...roleCounts.entries()]
      .sort((a, b) => b[1] - a[1])
      .forEach(([key], i) => roleRank.set(key, i));
    const roles: Record<string, number> = {};
    for (let i = 0; i < ids.length; i++) roles[ids[i]] = roleRank.get(rolesAtK[i])!;

    self.postMessage({
      type: "computed",
      communities,
      communitySizes,
      roles,
      nRoleClasses: roleCounts.size,
      curve,
      ms: performance.now() - t0,
      req: msg.req,
    });
    return;
  }

  if (msg.type === "twins") {
    const i = idIdx.get(msg.id);
    if (i === undefined) {
      self.postMessage({ type: "twins", id: msg.id, twins: [] });
      return;
    }
    const base = i * ndim;
    let qnorm = 0;
    for (let d = 0; d < ndim; d++) qnorm += vecs[base + d] ** 2;
    qnorm = Math.sqrt(qnorm);
    const sims: { id: string; sim: number }[] = [];
    if (qnorm > 0) {
      for (let j = 0; j < ids.length; j++) {
        if (j === i) continue;
        const b2 = j * ndim;
        let dot = 0;
        let n2 = 0;
        for (let d = 0; d < ndim; d++) {
          dot += vecs[base + d] * vecs[b2 + d];
          n2 += vecs[b2 + d] ** 2;
        }
        if (n2 === 0) continue;
        sims.push({ id: ids[j], sim: dot / (qnorm * Math.sqrt(n2)) });
      }
      sims.sort((a, b) => b.sim - a.sim);
    }
    const top = sims.slice(0, 10);
    // Ambiguity honesty: a twin whose margin over the next candidate is
    // <0.01 is a coin-flip tie, not a correspondence (functorSearch.ts).
    const twins = top.map((t, idx) => ({
      ...t,
      margin: idx + 1 < sims.length ? t.sim - sims[idx + 1].sim : 1,
    }));
    self.postMessage({ type: "twins", id: msg.id, twins });
  }
};

// Deterministic RNG so the resolution dial replays identically (seed 42,
// mirroring the Python side's fixed seed).
function mulberry32(seed: number) {
  let a = seed >>> 0;
  return () => {
    a |= 0;
    a = (a + 0x6d2b79f5) | 0;
    let t = Math.imul(a ^ (a >>> 15), 1 | a);
    t = (t + Math.imul(t ^ (t >>> 7), 61 | t)) ^ t;
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}
