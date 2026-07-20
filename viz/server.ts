/**
 * CTKR Observatory — local visualization server.
 *
 * Serves the interactive explorer over the artifacts in .metacoding/ctkr/:
 *   /api/graph      nodes + edges from the JSONL export
 *   /api/layout     cached ForceAtlas2 positions (computed once, ~a minute cold)
 *   /api/profiles   30-dim hom-profile vectors (entropy / roles / twins)
 *   /api/subsystems canonical Louvain subsystems + boundary_confidence overlay
 *   /api/port       porting bipartite feature×kind graph + CM decision registry
 *
 * Run: bun viz/server.ts   (then open http://localhost:4177)
 * Reads production data read-only; the only write is the layout cache
 * .metacoding/viz-layout.json.
 */
import { parquetReadObjects, asyncBufferFromFile } from "hyparquet";
import { compressors } from "hyparquet-compressors";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import index from "./index.html";
import { join } from "node:path";

const ROOT = join(import.meta.dir, "..");
const DATA = join(ROOT, ".metacoding");
const CTKR = join(DATA, "ctkr");
const EXPORT = join(CTKR, "export");
const PORT_GRAPH = join(ROOT, "eval/ctkr/results/feature-kind-graph-data");
const CM_DECISIONS = join(
  ROOT,
  "eval/ctkr/port_runs/kernel-9h5.24/build/cm-decisions.jsonl",
);
const LAYOUT_CACHE = join(DATA, "viz-layout.json");

async function readJsonl(path: string): Promise<any[]> {
  const text = await Bun.file(path).text();
  const rows: any[] = [];
  for (const line of text.split("\n")) {
    const t = line.trim();
    if (!t || t.startsWith("//")) continue;
    rows.push(JSON.parse(t));
  }
  return rows;
}

async function readParquet(path: string): Promise<any[]> {
  const file = await asyncBufferFromFile(path);
  return parquetReadObjects({ file, compressors });
}

// Lazily built, cached JSON payload per route.
const cache = new Map<string, Promise<unknown>>();
function memo<T>(key: string, build: () => Promise<T>): Promise<T> {
  let p = cache.get(key) as Promise<T> | undefined;
  if (!p) {
    p = build();
    p.catch(() => cache.delete(key));
    cache.set(key, p);
  }
  return p;
}
async function cached(key: string, build: () => Promise<unknown>): Promise<Response> {
  const data = await memo(key, build);
  return new Response(JSON.stringify(data), {
    headers: { "content-type": "application/json" },
  });
}

async function buildGraph() {
  const nodes = (await readJsonl(join(EXPORT, "nodes.jsonl"))).map((n) => ({
    id: n.id,
    kind: n.kind,
    name: n.short_name,
    qn: n.qualified_name,
    file: n.file,
    line: n.line,
  }));
  const edges = (await readJsonl(join(EXPORT, "edges.jsonl"))).map((e) => ({
    s: e.src_id,
    t: e.dst_id,
    k: e.kind,
    c: e.count ?? 1,
  }));
  return { nodes, edges };
}

async function buildLayout() {
  const cacheFile = Bun.file(LAYOUT_CACHE);
  if (await cacheFile.exists()) return cacheFile.json();

  console.log("[layout] cold start: running ForceAtlas2 over the full graph…");
  const { nodes, edges } = await memo("graph", buildGraph);
  const g = new Graph({ multi: true });
  for (const n of nodes) {
    // Deterministic seed positions from the id hash so reruns are stable.
    const h = parseInt(n.id.slice(0, 8), 16);
    g.addNode(n.id, {
      x: Math.cos(h % 6283 / 1000) * (1 + (h % 97)),
      y: Math.sin(h % 6283 / 1000) * (1 + (h % 89)),
    });
  }
  for (const e of edges) {
    if (g.hasNode(e.s) && g.hasNode(e.t)) {
      // CONTAINS is the skeleton; give it more pull than reference noise.
      const w = e.k === "CONTAINS" ? 2 : e.k === "REFERENCES" ? 0.5 : 1;
      g.addEdge(e.s, e.t, { weight: w });
    }
  }
  const t0 = performance.now();
  const positions = forceAtlas2(g, {
    iterations: 400,
    settings: {
      ...forceAtlas2.inferSettings(g),
      edgeWeightInfluence: 1,
      barnesHutOptimize: true,
    },
  });
  console.log(
    `[layout] done in ${((performance.now() - t0) / 1000).toFixed(1)}s — cached to ${LAYOUT_CACHE}`,
  );
  const compact: Record<string, [number, number]> = {};
  for (const [id, p] of Object.entries(positions))
    compact[id] = [Math.round(p.x * 100) / 100, Math.round(p.y * 100) / 100];
  await Bun.write(LAYOUT_CACHE, JSON.stringify(compact));
  return compact;
}

async function buildProfiles() {
  const rows = await readParquet(join(CTKR, "hom_profiles.parquet"));
  const ids: string[] = [];
  const vecs: number[] = [];
  for (const r of rows) {
    ids.push(r.symbol_id);
    for (const v of r.profile_vec) vecs.push(Number(v));
  }
  // Dim labels mirror ctkr/ctkr/hom_profiles.py DIMS: per kind, "in" then "out".
  const EDGE_KINDS = [
    "CALLS", "REFERENCES", "EXTENDS", "IMPLEMENTS", "OVERRIDES", "INJECTS",
    "CONTAINS", "IMPORTS", "ANNOTATES", "TYPE_OF", "READS_FIELD",
    "WRITES_FIELD", "RETURNS_TYPE", "CONSTRUCTS", "RAISES",
  ];
  const dims = EDGE_KINDS.flatMap((k) => [`${k}:in`, `${k}:out`]);
  return { ids, dims, ndim: dims.length, vecs };
}

async function buildSubsystems() {
  const [subsystems, members, cards] = await Promise.all([
    readParquet(join(CTKR, "subsystems.parquet")),
    readParquet(join(CTKR, "subsystem_members.parquet")),
    readJsonl(join(CTKR, "subsystem_cards.jsonl")),
  ]);
  const nameById = new Map(cards.map((c) => [c.subsystem_id, c.name]));
  return {
    subsystems: subsystems.map((s) => ({
      id: s.subsystem_id,
      name: nameById.get(s.subsystem_id) ?? s.subsystem_id,
      n: Number(s.n_members),
      resolution: s.resolution,
      persistence: s.persistence_score,
    })),
    members: members.map((m) => ({
      s: m.subsystem_id,
      id: m.symbol_id,
      conf: m.boundary_confidence,
      placement: m.placement,
    })),
  };
}

async function buildPort() {
  const [real, projected, decisions] = await Promise.all([
    Bun.file(join(PORT_GRAPH, "graph_real.json")).json(),
    Bun.file(join(PORT_GRAPH, "graph_projected.json"))
      .json()
      .catch(() => null),
    readJsonl(CM_DECISIONS).catch(() => []),
  ]);
  return { real, projected, decisions };
}

const server = Bun.serve({
  port: 4177,
  idleTimeout: 120,
  routes: {
    "/": index,
    "/api/graph": () => cached("graph", buildGraph),
    "/api/layout": () => cached("layout", buildLayout),
    "/api/profiles": () => cached("profiles", buildProfiles),
    "/api/subsystems": () => cached("subsystems", buildSubsystems),
    "/api/port": () => cached("port", buildPort),
  },
  development: { hmr: true, console: true },
});

console.log(`CTKR Observatory → http://localhost:${server.port}`);
console.log(`Reading production data (read-only): ${DATA}`);
