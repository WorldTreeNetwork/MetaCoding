/**
 * CTKR Observatory frontend.
 *
 * Territory: the whole-repo typed graph under live dials — edge alphabet,
 * contains/references weights, Louvain resolution (islands), granularity k
 * (role classes), entropy gauges with the entropy-check gates, boundary-
 * confidence seams, and name-blind role-equivalent twins per symbol.
 *
 * The Port: the porting layer's bipartite feature×kind graph — emit/fold
 * edges, status gates, the kernel surface at a tunable degree threshold,
 * the freeze-kernel wave collapse, and the CM decision registry.
 */
import { useEffect, useMemo, useRef, useState } from "react";
import { createRoot } from "react-dom/client";
import Graph from "graphology";
import Sigma from "sigma";
import "./style.css";

// ---------- palette (reference dataviz palette; mode-aware) ----------
const DARK = window.matchMedia("(prefers-color-scheme: dark)").matches;
const CAT = DARK
  ? ["#3987e5", "#008300", "#d55181", "#c98500", "#199e70", "#d95926", "#9085e9", "#e66767"]
  : ["#2a78d6", "#008300", "#e87ba4", "#eda100", "#1baf7a", "#eb6834", "#4a3aa7", "#e34948"];
const OTHER = "#898781";
const EDGE_COLOR = DARK ? "#2c2c2a" : "#e1e0d9";

const EDGE_KINDS = [
  "CALLS", "REFERENCES", "EXTENDS", "IMPLEMENTS", "OVERRIDES", "INJECTS",
  "CONTAINS", "IMPORTS", "ANNOTATES", "TYPE_OF", "READS_FIELD",
  "WRITES_FIELD", "RETURNS_TYPE", "CONSTRUCTS", "RAISES",
];

type NodeRec = { id: string; kind: string; name: string; qn: string; file: string; line: number };
type EdgeRec = { s: string; t: string; k: string; c: number };

// Diverging blue↔red across gray for boundary confidence (1 = solid member,
// 0 = judgment-call seam — the hot end is the interesting end).
function boundaryColor(conf: number): string {
  if (conf >= 0.85) return DARK ? "#3987e5" : "#2a78d6";
  if (conf >= 0.7) return "#86b6ef";
  if (conf >= 0.55) return DARK ? "#383835" : "#f0efec";
  if (conf >= 0.4) return "#ec835a";
  return "#d03b3b";
}

// ---------- data loading ----------
async function getJSON(url: string) {
  const r = await fetch(url);
  if (!r.ok) throw new Error(`${url}: ${r.status}`);
  return r.json();
}

// =====================================================================
// Territory
// =====================================================================

function TerritoryView() {
  const containerRef = useRef<HTMLDivElement>(null);
  const sigmaRef = useRef<Sigma | null>(null);
  const graphRef = useRef<Graph | null>(null);
  const workerRef = useRef<Worker | null>(null);
  const reqRef = useRef(0);

  const [status, setStatus] = useState("loading graph…");
  const [nodesById, setNodesById] = useState<Map<string, NodeRec> | null>(null);
  const [membership, setMembership] = useState<Map<string, { s: string; conf: number }> | null>(null);
  const [ssNames, setSsNames] = useState<Map<string, string>>(new Map());

  // dials
  const [alphabet, setAlphabet] = useState<Set<string>>(new Set(EDGE_KINDS));
  const [resolution, setResolution] = useState(0.5);
  const [granularity, setGranularity] = useState(4);
  const [containsWeight, setContainsWeight] = useState(1.0);
  const [referencesWeight, setReferencesWeight] = useState(0.5);
  const [colorMode, setColorMode] = useState<"island" | "role" | "kind" | "boundary">("island");

  // computed
  const [communities, setCommunities] = useState<Record<string, number>>({});
  const [communitySizes, setCommunitySizes] = useState<{ rank: number; n: number }[]>([]);
  const [roles, setRoles] = useState<Record<string, number>>({});
  const [nRoleClasses, setNRoleClasses] = useState(0);
  const [curve, setCurve] = useState<{ k: number; H: number; top5: number; nClasses: number }[]>([]);
  const [computeMs, setComputeMs] = useState(0);
  const [edgeKindCounts, setEdgeKindCounts] = useState<Record<string, number>>({});

  // selection
  const [selected, setSelected] = useState<NodeRec | null>(null);
  const [twins, setTwins] = useState<{ id: string; sim: number; margin: number }[] | null>(null);
  const [search, setSearch] = useState("");

  function select(rec: NodeRec | null) {
    setSelected(rec);
    setTwins(null);
    if (rec) {
      workerRef.current?.postMessage({ type: "twins", id: rec.id });
      const s = sigmaRef.current;
      const d = s?.getNodeDisplayData(rec.id);
      if (s && d) {
        s.getCamera().animate(
          { x: d.x, y: d.y, ratio: Math.min(s.getCamera().ratio, 0.25) },
          { duration: 500 },
        );
      }
    }
  }

  // refs mirroring state for the sigma reducers (avoid re-instantiating sigma)
  const styleRef = useRef({ colorMode, communities, roles, alphabet, membership, selected });
  styleRef.current = { colorMode, communities, roles, alphabet, membership, selected };
  const selectRef = useRef(select);
  selectRef.current = select;

  useEffect(() => {
    let dead = false;
    (async () => {
      const [graphData, layout, profiles, subsystems] = await Promise.all([
        getJSON("/api/graph"),
        getJSON("/api/layout"),
        getJSON("/api/profiles"),
        getJSON("/api/subsystems"),
      ]);
      if (dead) return;
      setStatus("building scene…");

      const byId = new Map<string, NodeRec>(graphData.nodes.map((n: NodeRec) => [n.id, n]));
      setNodesById(byId);
      const mem = new Map<string, { s: string; conf: number }>();
      for (const m of subsystems.members) mem.set(m.id, { s: m.s, conf: m.conf });
      setMembership(mem);
      setSsNames(new Map(subsystems.subsystems.map((s: any) => [s.id, s.name])));

      const counts: Record<string, number> = {};
      for (const e of graphData.edges as EdgeRec[]) counts[e.k] = (counts[e.k] ?? 0) + 1;
      setEdgeKindCounts(counts);

      // sigma graph
      const g = new Graph({ multi: true });
      const degree = new Map<string, number>();
      for (const e of graphData.edges as EdgeRec[]) {
        degree.set(e.s, (degree.get(e.s) ?? 0) + 1);
        degree.set(e.t, (degree.get(e.t) ?? 0) + 1);
      }
      for (const n of graphData.nodes as NodeRec[]) {
        const p = layout[n.id] ?? [0, 0];
        g.addNode(n.id, {
          x: p[0],
          y: p[1],
          size: Math.max(1.2, Math.sqrt(degree.get(n.id) ?? 1) * 0.85),
          label: n.name,
        });
      }
      for (const e of graphData.edges as EdgeRec[]) {
        if (g.hasNode(e.s) && g.hasNode(e.t)) g.addEdge(e.s, e.t, { k: e.k });
      }
      graphRef.current = g;

      const sigma = new Sigma(g, containerRef.current!, {
        labelRenderedSizeThreshold: 7,
        labelColor: { color: DARK ? "#c3c2b7" : "#52514e" },
        defaultEdgeColor: EDGE_COLOR,
        nodeReducer: (id, attrs) => {
          const st = styleRef.current;
          let color = OTHER;
          if (st.colorMode === "island") {
            const c = st.communities[id];
            color = c !== undefined && c < 8 ? CAT[c] : OTHER;
          } else if (st.colorMode === "role") {
            const c = st.roles[id];
            color = c !== undefined && c < 8 ? CAT[c] : OTHER;
          } else if (st.colorMode === "kind") {
            const n = byId.get(id as string);
            const i = n ? NODE_KIND_ORDER.indexOf(n.kind) : -1;
            color = i >= 0 && i < 8 ? CAT[i] : OTHER;
          } else if (st.colorMode === "boundary") {
            const m = st.membership?.get(id as string);
            color = m ? boundaryColor(m.conf) : DARK ? "#383835" : "#f0efec";
          }
          const isSel = st.selected?.id === id;
          return {
            ...attrs,
            color,
            zIndex: isSel ? 2 : 0,
            size: isSel ? (attrs.size as number) * 1.8 : attrs.size,
            highlighted: isSel,
          };
        },
        edgeReducer: (edge, attrs) => {
          const st = styleRef.current;
          const k = graphRef.current!.getEdgeAttribute(edge, "k") as string;
          if (!st.alphabet.has(k)) return { ...attrs, hidden: true };
          return { ...attrs, color: EDGE_COLOR, size: 0.4 };
        },
      });
      sigma.on("clickNode", ({ node }) => selectRef.current(byId.get(node) ?? null));
      sigma.on("clickStage", () => setSelected(null));
      sigmaRef.current = sigma;

      // worker
      const w = new Worker("/worker.js", { type: "module" });
      workerRef.current = w;
      w.onmessage = (ev) => {
        const m = ev.data;
        if (m.type === "ready") {
          setStatus("");
          requestCompute();
        } else if (m.type === "computed") {
          if (m.req !== reqRef.current) return; // stale
          setCommunities(m.communities);
          setCommunitySizes(m.communitySizes);
          setRoles(m.roles);
          setNRoleClasses(m.nRoleClasses);
          setCurve(m.curve);
          setComputeMs(m.ms);
          setStatus("");
          sigmaRef.current?.refresh();
        } else if (m.type === "twins") {
          setTwins(m.twins);
        }
      };
      w.postMessage({
        type: "init",
        profiles,
        edges: graphData.edges,
        nodeIds: (graphData.nodes as NodeRec[]).map((n) => n.id),
      });
      setStatus("computing islands…");
    })().catch((e) => setStatus(`error: ${e.message}`));
    return () => {
      dead = true;
      sigmaRef.current?.kill();
      workerRef.current?.terminate();
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // recompute (debounced) when dials move
  const dialsKey = `${[...alphabet].sort().join("|")}~${resolution}~${granularity}~${containsWeight}~${referencesWeight}`;
  function requestCompute() {
    const req = ++reqRef.current;
    setStatus("computing…");
    workerRef.current?.postMessage({
      type: "compute",
      req,
      alphabet: [...alphabet],
      resolution,
      k: granularity,
      containsWeight,
      referencesWeight,
    });
  }
  useEffect(() => {
    if (!workerRef.current) return;
    const t = setTimeout(requestCompute, 180);
    return () => clearTimeout(t);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [dialsKey]);

  // repaint on color-mode / selection change
  useEffect(() => {
    sigmaRef.current?.refresh();
  }, [colorMode, selected, communities, roles]);

  const current = curve.find((c) => c.k === granularity);
  const verdict =
    current == null
      ? null
      : current.H >= 4 && current.top5 < 0.5
        ? "proceed"
        : current.H < 4 || current.top5 > 0.7
          ? "blocked"
          : "caution";

  const islandLegend = useMemo(() => {
    const total = communitySizes.reduce((a, b) => a + b.n, 0);
    const top = communitySizes.slice(0, 8);
    const rest = total - top.reduce((a, b) => a + b.n, 0);
    return { top, rest };
  }, [communitySizes]);

  const searchHits = useMemo(() => {
    if (!search.trim() || !nodesById) return [];
    const q = search.trim().toLowerCase();
    const hits: NodeRec[] = [];
    for (const n of nodesById.values()) {
      if (n.name.toLowerCase().includes(q) || n.qn.toLowerCase().includes(q)) {
        hits.push(n);
        if (hits.length >= 20) break;
      }
    }
    return hits.sort((a, b) => a.name.length - b.name.length);
  }, [search, nodesById]);

  const selMembership = selected && membership?.get(selected.id);

  return (
    <div className="territory">
      <aside className="controls">
        <h3>Edge alphabet</h3>
        <div className="kinds">
          {EDGE_KINDS.filter((k) => edgeKindCounts[k]).map((k) => (
            <button
              key={k}
              className={alphabet.has(k) ? "on" : ""}
              onClick={() => {
                const next = new Set(alphabet);
                next.has(k) ? next.delete(k) : next.add(k);
                setAlphabet(next);
              }}
            >
              {k}
              <span className="n">{edgeKindCounts[k]}</span>
            </button>
          ))}
        </div>

        <h3>Island dials</h3>
        <div className="dial">
          <label>
            Louvain resolution <output>{resolution.toFixed(2)}</output>
          </label>
          <input
            type="range" min={0.3} max={2} step={0.05} value={resolution}
            onChange={(e) => setResolution(Number(e.target.value))}
          />
          <div className="hint">low → few big islands · high → many small ones</div>
        </div>
        <div className="dial">
          <label>
            CONTAINS weight <output>{containsWeight.toFixed(1)}</output>
          </label>
          <input
            type="range" min={0} max={2} step={0.1} value={containsWeight}
            onChange={(e) => setContainsWeight(Number(e.target.value))}
          />
        </div>
        <div className="dial">
          <label>
            REFERENCES weight <output>{referencesWeight.toFixed(1)}</output>
          </label>
          <input
            type="range" min={0} max={2} step={0.1} value={referencesWeight}
            onChange={(e) => setReferencesWeight(Number(e.target.value))}
          />
          <div className="hint">structure vs usage: which force shapes the islands</div>
        </div>

        <h3>Role granularity</h3>
        <div className="dial">
          <label>
            k (profile buckets) <output>{granularity}</output>
          </label>
          <input
            type="range" min={1} max={12} step={1} value={granularity}
            onChange={(e) => setGranularity(Number(e.target.value))}
          />
          <div className="hint">
            slide the rate–distortion curve: coarse roles ↔ fine fingerprints
          </div>
        </div>

        <h3>Color by</h3>
        <div className="colorby">
          {(["island", "role", "kind", "boundary"] as const).map((m) => (
            <button key={m} className={colorMode === m ? "active" : ""} onClick={() => setColorMode(m)}>
              {m === "boundary" ? "boundary conf." : m}
            </button>
          ))}
        </div>

        <h3>Entropy check</h3>
        {current && (
          <>
            <div className="gauge">
              <div className="glabel">
                <span>Shannon entropy</span>
                <b>{current.H.toFixed(2)} bits</b>
              </div>
              <div className="track">
                <div className="fill" style={{ width: `${Math.min(100, (current.H / 8) * 100)}%` }} />
                <div className="gate" style={{ left: "50%" }} title="gate: ≥ 4.0 bits" />
              </div>
              <div className="gatelabel">gate at 4.0 bits</div>
            </div>
            <div className="gauge">
              <div className="glabel">
                <span>Top-5 profile coverage</span>
                <b>{(current.top5 * 100).toFixed(1)}%</b>
              </div>
              <div className="track">
                <div className="fill" style={{ width: `${current.top5 * 100}%` }} />
                <div className="gate" style={{ left: "50%" }} title="proceed < 50%" />
                <div className="gate" style={{ left: "70%" }} title="blocked > 70%" />
              </div>
              <div className="gatelabel">proceed &lt; 50% · blocked &gt; 70%</div>
            </div>
            <div className={`verdict ${verdict}`}>{verdict?.toUpperCase()}</div>
            <div className="gatelabel" style={{ marginTop: 6 }}>
              {nRoleClasses.toLocaleString()} role classes at k={granularity}
              {computeMs > 0 && ` · ${computeMs.toFixed(0)} ms`}
            </div>
          </>
        )}

        <h3>Rate–distortion curve</h3>
        <RateCurve curve={curve} k={granularity} onPick={setGranularity} />
      </aside>

      <div className="stage">
        <div ref={containerRef} className="sigma-container" />
        {status && <div className="status">{status}</div>}
        <div className="legend">
          {colorMode === "island" && (
            <>
              {islandLegend.top.map((c) => (
                <div className="row" key={c.rank}>
                  <span className="swatch" style={{ background: CAT[c.rank] }} />
                  island {c.rank + 1}
                  <span className="n">{c.n.toLocaleString()}</span>
                </div>
              ))}
              {islandLegend.rest > 0 && (
                <div className="row">
                  <span className="swatch" style={{ background: OTHER }} />
                  other ({Math.max(0, communitySizes.length - 8)} islands)
                  <span className="n">{islandLegend.rest.toLocaleString()}</span>
                </div>
              )}
            </>
          )}
          {colorMode === "role" && (
            <>
              <div className="row">top 8 role classes by population; gray = long tail</div>
              {CAT.map((c, i) => (
                <div className="row" key={i}>
                  <span className="swatch" style={{ background: c }} />
                  role class {i + 1}
                </div>
              ))}
            </>
          )}
          {colorMode === "kind" && (
            <>
              {NODE_KIND_ORDER.slice(0, 8).map((k, i) => (
                <div className="row" key={k}>
                  <span className="swatch" style={{ background: CAT[i] }} />
                  {k}
                </div>
              ))}
            </>
          )}
          {colorMode === "boundary" && (
            <>
              <div className="row">
                <span className="swatch" style={{ background: boundaryColor(1) }} />
                solid member (confidence ≈ 1)
              </div>
              <div className="row">
                <span className="swatch" style={{ background: boundaryColor(0.6) }} />
                mid
              </div>
              <div className="row">
                <span className="swatch" style={{ background: boundaryColor(0.2) }} />
                judgment-call seam (low confidence)
              </div>
              <div className="row">canonical 12-subsystem run · resolution sweep 0.3–2.0</div>
            </>
          )}
        </div>
      </div>

      <aside className="inspector">
        <h3>Find symbol</h3>
        <input
          className="searchbox"
          placeholder="search by name…"
          value={search}
          onChange={(e) => setSearch(e.target.value)}
        />
        {searchHits.length > 0 && (
          <div className="searchhits">
            {searchHits.map((n) => (
              <div key={n.id} className="twin" onClick={() => { select(n); setSearch(""); }}>
                <div className="name">{n.name}</div>
                <div className="meta">{n.kind} · {n.file}</div>
              </div>
            ))}
          </div>
        )}

        <h3>Symbol</h3>
        {!selected && <div className="empty">Click a node (or search above) to inspect it and find its name-blind twins.</div>}
        {selected && (
          <div className="sym">
            <div className="name">{selected.name}</div>
            <div style={{ margin: "4px 0" }}>
              <span className="kindchip">{selected.kind}</span>
              {selMembership && (
                <span className="kindchip" title={`boundary confidence ${selMembership.conf.toFixed(2)}`}>
                  {ssNames.get(selMembership.s) ?? selMembership.s} · {selMembership.conf.toFixed(2)}
                </span>
              )}
            </div>
            <div className="meta">{selected.file}:{selected.line}</div>
            <div className="meta">{selected.qn}</div>

            <h3>Role-equivalent twins</h3>
            {!twins && <div className="empty">searching…</div>}
            {twins && twins.length === 0 && <div className="empty">no profile for this symbol</div>}
            {twins?.map((t) => {
              const rec = nodesById?.get(t.id);
              const ambiguous = t.margin < 0.01;
              return (
                <div
                  key={t.id}
                  className={`twin${ambiguous ? " ambiguous" : ""}`}
                  onClick={() => rec && select(rec)}
                >
                  <div className="name">
                    {rec?.name ?? t.id} {ambiguous && <span className="amb">⚠ coin-flip tie</span>}
                  </div>
                  <div className="meta">
                    {rec?.file} · cos {t.sim.toFixed(3)} · margin {t.margin.toFixed(3)}
                  </div>
                  <div className="simbar">
                    <i style={{ width: `${t.sim * 100}%` }} />
                  </div>
                </div>
              );
            })}
          </div>
        )}
      </aside>
    </div>
  );
}

const NODE_KIND_ORDER = ["field", "function", "method", "type_alias", "class", "file", "interface", "module"];

function RateCurve({
  curve, k, onPick,
}: {
  curve: { k: number; H: number; nClasses: number }[];
  k: number;
  onPick: (k: number) => void;
}) {
  if (!curve.length) return null;
  const W = 236, H_ = 110, padL = 30, padB = 20, padT = 8, padR = 6;
  const maxH = Math.max(...curve.map((c) => c.H), 4.5);
  const x = (kk: number) => padL + ((kk - 1) / 11) * (W - padL - padR);
  const y = (h: number) => padT + (1 - h / maxH) * (H_ - padT - padB);
  const path = curve.map((c, i) => `${i ? "L" : "M"}${x(c.k).toFixed(1)},${y(c.H).toFixed(1)}`).join("");
  const cur = curve.find((c) => c.k === k)!;
  return (
    <div className="curve">
      <svg width={W} height={H_} role="img" aria-label="Entropy in bits versus granularity k">
        {[0, 2, 4, 6, 8].filter((h) => h <= maxH).map((h) => (
          <g key={h}>
            <line x1={padL} x2={W - padR} y1={y(h)} y2={y(h)}
              stroke={h === 4 ? "var(--text-secondary)" : "var(--grid)"}
              strokeDasharray={h === 4 ? "3 3" : undefined} strokeWidth={1} />
            <text x={padL - 5} y={y(h) + 3.5} textAnchor="end" fontSize={9.5} fill="var(--muted)">{h}</text>
          </g>
        ))}
        {curve.map((c) => (
          <rect key={c.k} x={x(c.k) - 9} y={padT} width={18} height={H_ - padT - padB}
            fill="transparent" style={{ cursor: "pointer" }} onClick={() => onPick(c.k)} />
        ))}
        <path d={path} fill="none" stroke="var(--series-1)" strokeWidth={2} pointerEvents="none" />
        <circle cx={x(k)} cy={y(cur.H)} r={4.5} fill="var(--series-1)"
          stroke="var(--surface-1)" strokeWidth={2} pointerEvents="none" />
        {curve.filter((c) => c.k === 1 || c.k === 12 || c.k === k).map((c) => (
          <text key={c.k} x={x(c.k)} y={H_ - 6} textAnchor="middle" fontSize={9.5}
            fill={c.k === k ? "var(--text-primary)" : "var(--muted)"}
            fontWeight={c.k === k ? 650 : 400}>
            k={c.k}
          </text>
        ))}
        <text x={x(cur.k)} y={y(cur.H) - 8} textAnchor="middle" fontSize={9.5} fill="var(--text-secondary)">
          {cur.nClasses.toLocaleString()} classes
        </text>
      </svg>
    </div>
  );
}

// =====================================================================
// The Port
// =====================================================================

type KindEdge = {
  feature: string; kind: string; role: "emit" | "fold";
  status_gated: boolean; provenance: string; via: string[];
};

function PortView() {
  const [data, setData] = useState<any>(null);
  const [err, setErr] = useState("");
  const [threshold, setThreshold] = useState(2);
  const [frozen, setFrozen] = useState(false);
  const [showProjected, setShowProjected] = useState(false);
  const [openDecision, setOpenDecision] = useState<number | null>(null);

  useEffect(() => {
    getJSON("/api/port").then(setData).catch((e) => setErr(e.message));
  }, []);

  if (err) return <div className="port"><div className="panel">failed to load: {err}</div></div>;
  if (!data) return <div className="port"><div className="panel">loading…</div></div>;

  const graph = showProjected && data.projected ? data.projected : data.real;
  const features: string[] = graph.features;
  const kinds: string[] = graph.kinds;
  const edges: KindEdge[] = graph.edges;

  // Kernel surface at the current threshold: cross-feature degree ≥ threshold.
  const featuresPerKind = new Map<string, Set<string>>();
  for (const e of edges) {
    if (!featuresPerKind.has(e.kind)) featuresPerKind.set(e.kind, new Set());
    featuresPerKind.get(e.kind)!.add(e.feature);
  }
  const kernel = new Set(
    kinds.filter((k) => (featuresPerKind.get(k)?.size ?? 0) >= threshold),
  );

  // Waves: union-find features sharing any non-frozen kind.
  const frozenSet = frozen ? kernel : new Set<string>();
  const parent = new Map<string, string>(features.map((f) => [f, f]));
  const find = (a: string): string => {
    while (parent.get(a) !== a) {
      parent.set(a, parent.get(parent.get(a)!)!);
      a = parent.get(a)!;
    }
    return a;
  };
  for (const [kind, fs] of featuresPerKind) {
    if (frozenSet.has(kind)) continue;
    const arr = [...fs];
    for (let i = 1; i < arr.length; i++) parent.set(find(arr[i]), find(arr[0]));
  }
  const waveMap = new Map<string, string[]>();
  for (const f of features) {
    const r = find(f);
    if (!waveMap.has(r)) waveMap.set(r, []);
    waveMap.get(r)!.push(f);
  }
  const waves = [...waveMap.values()].sort((a, b) => b.length - a.length);

  // layout
  const fx = 30, kx = 430, rowH = 56, headerY = 34;
  const fy = (i: number) => headerY + 40 + i * (rowH + 36);
  const ky = (i: number) => headerY + i * rowH;
  const svgH = Math.max(fy(features.length - 1), ky(kinds.length - 1)) + 70;
  const emitColor = "var(--series-1)", foldColor = "var(--series-6)";

  return (
    <div className="port">
      <div className="cols">
        <div className="panel" style={{ flex: "1 1 560px", minWidth: 520 }}>
          <h2>Bipartite feature × event-kind graph</h2>
          <div className="sub">
            extracted name-blind from the composed build's store.ts · emit = writes the kind ·
            fold = reads it back · diamonds = kernel surface (cross-feature degree ≥ {threshold})
          </div>
          <svg width="100%" viewBox={`0 0 640 ${svgH}`} style={{ maxWidth: 720 }}>
            <text x={fx} y={headerY - 12} fontSize={11} fill="var(--muted)" fontWeight={650}>FEATURES</text>
            <text x={kx} y={headerY - 12} fontSize={11} fill="var(--muted)" fontWeight={650}>EVENT KINDS</text>
            {edges.map((e, i) => {
              const fi = features.indexOf(e.feature);
              const kI = kinds.indexOf(e.kind);
              if (fi < 0 || kI < 0) return null;
              const y1 = fy(fi) + (e.role === "emit" ? -6 : 6);
              const y2 = ky(kI) + (e.role === "emit" ? -4 : 4);
              const x1 = fx + 170, x2 = kx - 12;
              const projected = e.provenance !== "extracted";
              const mx = (x1 + x2) / 2;
              return (
                <g key={i}>
                  <path
                    d={`M${x1},${y1} C${mx},${y1} ${mx},${y2} ${x2},${y2}`}
                    fill="none"
                    stroke={e.role === "emit" ? emitColor : foldColor}
                    strokeWidth={2}
                    strokeDasharray={projected ? "2 5" : e.role === "fold" ? "6 4" : undefined}
                    opacity={projected ? 0.45 : 0.85}
                  >
                    <title>
                      {`${e.feature} —${e.role}→ ${e.kind}${e.status_gated ? " (status-gated)" : ""}${projected ? " [PROJECTED — not extracted]" : ""}\nvia: ${e.via.join(", ")}`}
                    </title>
                  </path>
                  {e.status_gated && (
                    <circle cx={mx} cy={(y1 + y2) / 2} r={5} fill="var(--surface-1)"
                      stroke="var(--status-warning)" strokeWidth={2}>
                      <title>status-gated: this fold consults the status contract</title>
                    </circle>
                  )}
                </g>
              );
            })}
            {features.map((f, i) => (
              <g key={f}>
                <rect x={fx} y={fy(i) - 20} width={170} height={40} rx={9}
                  fill="var(--page)" stroke="var(--baseline)" />
                <text x={fx + 85} y={fy(i) + 4} textAnchor="middle" fontSize={12.5}
                  fontWeight={650} fill="var(--text-primary)">{f}</text>
              </g>
            ))}
            {kinds.map((k, i) => {
              const isKernel = kernel.has(k);
              const y = ky(i);
              return (
                <g key={k}>
                  {isKernel ? (
                    <rect x={kx - 8} y={y - 8} width={16} height={16} rx={3}
                      transform={`rotate(45 ${kx} ${y})`}
                      fill="var(--series-7)" opacity={0.9}>
                      <title>kernel kind — freeze before fan-out</title>
                    </rect>
                  ) : (
                    <circle cx={kx} cy={y} r={6} fill="var(--muted)" opacity={0.75} />
                  )}
                  <text x={kx + 16} y={y + 4} fontSize={12}
                    fontWeight={isKernel ? 650 : 400}
                    fill={isKernel ? "var(--text-primary)" : "var(--text-secondary)"}>
                    {k}
                  </text>
                  <text x={kx + 16} y={y + 17} fontSize={10} fill="var(--muted)">
                    {(featuresPerKind.get(k)?.size ?? 0)} feature{(featuresPerKind.get(k)?.size ?? 0) === 1 ? "" : "s"}
                    {isKernel ? " · kernel" : ""}
                  </text>
                </g>
              );
            })}
          </svg>
          <div className="bip-legend">
            <span className="item"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke={emitColor} strokeWidth="2" /></svg> emit</span>
            <span className="item"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke={foldColor} strokeWidth="2" strokeDasharray="6 4" /></svg> fold</span>
            <span className="item"><svg width="12" height="12"><circle cx="6" cy="6" r="4" fill="var(--surface-1)" stroke="var(--status-warning)" strokeWidth="2" /></svg> status-gated</span>
            <span className="item"><svg width="12" height="12"><rect x="2" y="2" width="8" height="8" rx="2" transform="rotate(45 6 6)" fill="var(--series-7)" /></svg> kernel kind</span>
            {showProjected && (
              <span className="item"><svg width="22" height="6"><line x1="0" y1="3" x2="22" y2="3" stroke={emitColor} strokeWidth="2" strokeDasharray="2 5" opacity="0.5" /></svg> projected (forecast, not extracted)</span>
            )}
          </div>
        </div>

        <div style={{ flex: "1 1 340px", minWidth: 320, display: "flex", flexDirection: "column", gap: 18 }}>
          <div className="panel">
            <h2>Dials</h2>
            <div className="dial">
              <label>
                Kernel degree threshold <output>≥ {threshold}</output>
              </label>
              <input type="range" min={1} max={4} step={1} value={threshold}
                onChange={(e) => setThreshold(Number(e.target.value))} />
              <div className="hint">a kind used by this many features belongs to the shared kernel</div>
            </div>
            <label className="toggle" style={{ marginTop: 4 }}>
              <input type="checkbox" checked={frozen} onChange={(e) => setFrozen(e.target.checked)} />
              Freeze kernel ({kernel.size} kind{kernel.size === 1 ? "" : "s"})
            </label>
            {data.projected && (
              <label className="toggle" style={{ marginTop: 10 }}>
                <input type="checkbox" checked={showProjected}
                  onChange={(e) => setShowProjected(e.target.checked)} />
                Show projected graph (forecast)
              </label>
            )}
          </div>

          <div className="panel">
            <h2>Fan-out waves</h2>
            <div className="sub">
              features sharing an unfrozen kind must build together; freeze the kernel and watch them decouple
            </div>
            <div className="waves">
              {waves.map((w, i) => (
                <div className="wave" key={i}
                  style={w.length === 1 ? { borderColor: "var(--status-good)", borderStyle: "solid" } : undefined}>
                  <span className="wlabel">wave {i + 1}</span>
                  {w.map((f) => <span className="featchip" key={f}>{f}</span>)}
                  {w.length === 1 && <span className="sharenote" style={{ color: "var(--good-text)" }}>parallel ✓</span>}
                </div>
              ))}
            </div>
            <div className="sharenote" style={{ marginTop: 8 }}>
              {frozen
                ? `kernel frozen: ${[...kernel].join(", ") || "—"} — remaining coupling only through unfrozen kinds`
                : "kernel live: every shared kind couples its features into one serialized wave"}
            </div>
          </div>

          <div className="panel">
            <h2>CM decision registry</h2>
            <div className="sub">kernel element 5 · bound on observed evidence (v1.3)</div>
            {data.decisions.map((d: any, i: number) => (
              <div className="decision" key={i}>
                <div className="drow" onClick={() => setOpenDecision(openDecision === i ? null : i)}>
                  <span className="inv">{d.invariant}</span>
                  <span className="schip">{d.sensitivity}</span>
                  <span className={`statuschip ${d.status}`}>{d.status}</span>
                </div>
                {openDecision === i && (
                  <div className="body">
                    <div><b>choice:</b> {d.menuChoice}</div>
                    {d.convergenceKey && <div><b>convergence:</b> <code>{d.convergenceKey}</code></div>}
                    {d.rationale && <div style={{ marginTop: 4 }}>{d.rationale}</div>}
                  </div>
                )}
              </div>
            ))}
            {data.decisions.length === 0 && <div className="empty">no registry found</div>}
          </div>
        </div>
      </div>
    </div>
  );
}

// =====================================================================

function App() {
  const [tab, setTab] = useState<"territory" | "port">("territory");
  return (
    <div className="app">
      <header className="bar">
        <h1>CTKR Observatory</h1>
        <span className="sub">the graph, its islands, and the dials that carve them</span>
        <nav className="tabs">
          <button className={tab === "territory" ? "active" : ""} onClick={() => setTab("territory")}>
            Territory
          </button>
          <button className={tab === "port" ? "active" : ""} onClick={() => setTab("port")}>
            The Port
          </button>
        </nav>
      </header>
      <div className="main">
        {tab === "territory" ? <TerritoryView /> : <PortView />}
      </div>
    </div>
  );
}

createRoot(document.getElementById("root")!).render(<App />);
