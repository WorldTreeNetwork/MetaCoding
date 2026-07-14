/**
 * eval/ctkr/port_verify_experiment.ts
 *
 * The §6 ungated port-verification experiment (ct-subsystem-extraction.md §7, T6
 * acceptance clause 2): run ONE real TS↔Python subsystem pair through the port
 * verifier and report the §6.2 normalization ON/OFF delta.
 *
 * MetaCoding indexes both its TS Phase-2 machinery (`src/`) and its Python L1/L3
 * lane (`ctkr/`) as ONE repo, so a TS subsystem and a Python subsystem inside it
 * are the natural cross-language pair. We treat the TS subsystem's extracted spec
 * (roles + interface + composition laws) as `S` and score the Python subsystem as
 * a "port" `S'` — member-set-restricted functor discovery (MetaCoding-4ty
 * endofunctor mode: one repo, two disjoint member sets), with the §6.2
 * normalization applied at seed time when on.
 *
 * This is deliberately UNGATED (§6.3 / §7.2: the cross-language bias is measured
 * here, not asserted). The output is the on/off delta on every §7 gate — the
 * instrument that answers whether cross-language edge-alphabet normalization
 * helps. Seeds are the shipped self-index hom-profiles (depth-1, dim 30); the
 * gated rename-fork acceptance (verifyPort.test.ts) uses proper depth-2 seeds.
 *
 * Recipe (§8.2 open decision (c): verify_port starts as a recipe over
 * functor_between, promoted to an MCP tool once the punch-list format stabilizes):
 *
 *   bun run eval/ctkr/port_verify_experiment.ts \
 *     --data-dir <.metacoding dir> \
 *     --spec-subsystem <id-prefix>   # the extracted-spec side S (default TS src/ctkr)
 *     --port-subsystem <id-prefix>   # the re-implementation S'  (default PY ctkr)
 *     [--view similarity|orbit] [--out results/<name>.md]
 */

import { DuckDBInstance } from "@duckdb/node-api";
import { join } from "node:path";
import {
  verifyPort,
  formatReport,
  loadNormalization,
  type SubsystemSpec,
  type SpecRole,
  type SpecProvide,
  type SpecOp,
  type SideGraph,
  type PortVerificationReport,
} from "../../src/ctkr/verifyPort.ts";
import type { FunctorObject, FunctorEdge } from "../../src/ctkr/functorSearch.ts";

// --- list-aware coercion (mirror of artifacts.ts coerceValue for our needs) ---
function coerce(v: unknown): unknown {
  if (typeof v === "bigint") return Number(v);
  if (v && typeof v === "object" && "items" in (v as Record<string, unknown>)) {
    return (v as { items: unknown[] }).items.map(coerce);
  }
  return v;
}

async function main() {
  const argv = Bun.argv.slice(2);
  const arg = (name: string, def?: string): string | undefined => {
    const i = argv.indexOf(`--${name}`);
    return i >= 0 ? argv[i + 1] : def;
  };
  const dataDir = arg("data-dir");
  if (!dataDir) throw new Error("--data-dir <.metacoding dir> is required");
  const specPrefix = arg("spec-subsystem", "ss:7bd32e1")!; // TS src/ctkr
  const portPrefix = arg("port-subsystem", "ss:4c95bb4")!; // PY ctkr
  const view = (arg("view", "similarity") as "similarity" | "orbit");
  const outPath = arg("out");

  const ctkr = join(dataDir, "ctkr");
  const inst = await DuckDBInstance.create(":memory:");
  const conn = await inst.connect();
  const q = async (sql: string): Promise<Record<string, unknown>[]> => {
    const r = await conn.runAndReadAll(sql);
    const names = r.columnNames();
    return r.getRows().map((row) => {
      const o: Record<string, unknown> = {};
      names.forEach((n, i) => (o[n] = coerce(row[i])));
      return o;
    });
  };
  const P = (f: string) => `read_parquet('${join(ctkr, f)}')`;

  // resolve full subsystem ids from prefixes.
  const subs = await q(`SELECT subsystem_id, n_members FROM ${P("subsystems.parquet")}`);
  const resolve = (pfx: string): string => {
    const hit = subs.find((s) => String(s.subsystem_id).startsWith(pfx));
    if (!hit) throw new Error(`no subsystem matching prefix ${pfx}`);
    return String(hit.subsystem_id);
  };
  const specId = resolve(specPrefix);
  const portId = resolve(portPrefix);

  // member sets.
  const memberRows = async (sid: string) =>
    (await q(`SELECT symbol_id FROM ${P("subsystem_members.parquet")} WHERE subsystem_id='${sid}'`)).map(
      (r) => String(r.symbol_id),
    );
  const specMembers = new Set(await memberRows(specId));
  const portMembers = new Set(await memberRows(portId));

  // hom-profiles (whole repo) → id → profile vec.
  const profiles = new Map<string, number[]>();
  for (const r of await q(`SELECT symbol_id, profile_vec FROM ${P("hom_profiles.parquet")}`)) {
    profiles.set(String(r.symbol_id), (r.profile_vec as number[]).map(Number));
  }

  // nodes.jsonl → id → {kind, language, qualified_name}
  const nodeMeta = new Map<string, { kind: string; lang: string; qn: string }>();
  for await (const line of readLines(join(ctkr, "export", "nodes.jsonl"))) {
    const r = JSON.parse(line);
    nodeMeta.set(r.id, { kind: r.kind ?? "unknown", lang: r.language ?? "", qn: r.qualified_name ?? "" });
  }

  // edges.jsonl → all typed edges; keep per-side member-internal (so the §6.2
  // reweight marginal reflects each subsystem's own language-shaped edge mix).
  const specEdges: FunctorEdge[] = [];
  const portEdges: FunctorEdge[] = [];
  for await (const line of readLines(join(ctkr, "export", "edges.jsonl"))) {
    const r = JSON.parse(line);
    const e = { src: r.src_id as string, dst: r.dst_id as string, kind: r.kind as string };
    if (specMembers.has(e.src) && specMembers.has(e.dst)) specEdges.push(e);
    if (portMembers.has(e.src) && portMembers.has(e.dst)) portEdges.push(e);
  }

  // side graphs: only members that carry a hom-profile (seedable objects).
  const sideObjects = (members: Set<string>): FunctorObject[] => {
    const out: FunctorObject[] = [];
    for (const id of members) {
      const pv = profiles.get(id);
      const nm = nodeMeta.get(id);
      if (!pv || !nm) continue;
      out.push({ id, kind: nm.kind, profileVec: pv });
    }
    return out;
  };
  const specObjects = sideObjects(specMembers);
  const portObjects = sideObjects(portMembers);
  const seedableSpec = new Set(specObjects.map((o) => o.id));
  const seedablePort = new Set(portObjects.map((o) => o.id));
  const qnMap = (ids: Set<string>) => new Map([...ids].map((id) => [id, nodeMeta.get(id)?.qn ?? id]));

  const domLang = (members: Set<string>): string => {
    const c: Record<string, number> = {};
    for (const id of members) {
      const l = nodeMeta.get(id)?.lang;
      if (l) c[l] = (c[l] ?? 0) + 1;
    }
    return Object.entries(c).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
  };

  // --- extracted spec of the TS subsystem S ---
  const pres = await q(
    `SELECT role_id, members, interface_participation, exemplar_symbol_id, exemplar_qualified_name, cardinality FROM ${P("presentations.parquet")} WHERE subsystem_id='${specId}' AND view='${view}'`,
  );
  const roles: SpecRole[] = pres.map((r) => {
    const members = (r.members as string[]).map(String);
    const qn = nodeMeta.get(String(r.exemplar_symbol_id))?.qn;
    return {
      roleId: String(r.role_id),
      label: qn ? qn.split("::").pop() : String(r.role_id).slice(0, 10),
      members,
      interfaceParticipation: (r.interface_participation as string[]).map(String),
      exemplarSymbolId: String(r.exemplar_symbol_id),
      exemplarQualifiedName: String(r.exemplar_qualified_name ?? qn ?? ""),
      cardinality: Number(r.cardinality),
      invarianceTier: "I",
      // the single "isolated" (zero-profile) class per view is nl-only — §2.3.
      isIsolated: members.every((m) => !seedableSpec.has(m)),
    };
  });

  const ifaceRows = await q(
    `SELECT internal_symbol_id, internal_qualified_name, edge_kind FROM ${P("interfaces.parquet")} WHERE subsystem_id='${specId}' AND direction='provides'`,
  );
  const provMap = new Map<string, SpecProvide>();
  for (const r of ifaceRows) {
    const id = String(r.internal_symbol_id);
    let p = provMap.get(id);
    if (!p) provMap.set(id, (p = { internalSymbolId: id, internalQualifiedName: String(r.internal_qualified_name ?? ""), usageModes: [] }));
    if (!p.usageModes.includes(String(r.edge_kind))) p.usageModes.push(String(r.edge_kind));
  }
  const provides = [...provMap.values()];

  const opRows = await q(
    `SELECT operation_id, op_kind, input_roles, output_role, edge_kinds, is_boundary_op, exemplar_paths FROM ${P("operads.parquet")} WHERE subsystem_id='${specId}' AND view='${view}' AND op_kind != 'non_operadic'`,
  );
  const ops: SpecOp[] = opRows.map((r) => ({
    operationId: String(r.operation_id),
    opKind: String(r.op_kind) as SpecOp["opKind"],
    inputRoles: (r.input_roles as string[]).map(String),
    outputRole: String(r.output_role),
    edgeKinds: (r.edge_kinds as string[]).map(String),
    isBoundaryOp: Boolean(r.is_boundary_op),
    invarianceTier: "I",
    exemplarPaths: (r.exemplar_paths as string[]).map(String),
  }));

  const spec: SubsystemSpec = {
    subsystemId: specId,
    repo: "MetaCoding",
    name: `TS ${specPrefix}`,
    view,
    roles,
    provides,
    ops,
  };
  const source: SideGraph = {
    objects: specObjects,
    edges: specEdges,
    memberSet: seedableSpec,
    qualifiedNames: qnMap(specMembers),
    language: domLang(specMembers),
  };
  const port: SideGraph = {
    objects: portObjects,
    edges: portEdges,
    memberSet: seedablePort,
    qualifiedNames: qnMap(portMembers),
    language: domLang(portMembers),
  };

  const cfg = { normalize: "none" as const }; // isolate the §6.2 on/off effect
  const off = verifyPort({ spec, source, port, normalization: null, config: cfg });
  const on = verifyPort({ spec, source, port, normalization: loadNormalization(), config: cfg });

  const md = renderExperiment({ specId, portId, view, source, port, roles, provides, ops, off, on });
  process.stdout.write(md + "\n");
  if (outPath) {
    await Bun.write(join("eval/ctkr", outPath), md + "\n");
    process.stderr.write(`\n[wrote ${join("eval/ctkr", outPath)}]\n`);
  }
  conn.closeSync();
}

function renderExperiment(x: {
  specId: string; portId: string; view: string;
  source: SideGraph; port: SideGraph;
  roles: SpecRole[]; provides: SpecProvide[]; ops: SpecOp[];
  off: PortVerificationReport; on: PortVerificationReport;
}): string {
  const g = (r: PortVerificationReport) => r.gates;
  const row = (name: string, k: keyof ReturnType<typeof g>) => {
    const a = g(x.off)[k].score, b = g(x.on)[k].score;
    const d = b - a;
    const sign = d > 0.0005 ? "▲" : d < -0.0005 ? "▼" : "·";
    return `| ${name} | ${(a * 100).toFixed(1)}% | ${(b * 100).toFixed(1)}% | ${sign} ${(d * 100 >= 0 ? "+" : "")}${(d * 100).toFixed(1)} pts |`;
  };
  return [
    `# Port-verification §6 experiment — cross-language TS↔Python`,
    ``,
    `- **spec (S)** = \`${x.specId}\` (${x.source.language}, ${x.source.objects.length} seedable members)`,
    `- **port (S')** = \`${x.portId}\` (${x.port.language}, ${x.port.objects.length} seedable members)`,
    `- role view = \`${x.view}\`  ·  ${x.roles.length} roles · ${x.provides.length} provided exports · ${x.ops.length} composition ops`,
    `- seeds = self-index hom-profiles (depth-1, dim 30); §6.2 normalization applied at seed time when ON`,
    `- **ungated** (§6.3 / §7.2): this measures the cross-language bias, it does not assert a port passes.`,
    ``,
    `## Normalization ON/OFF delta`,
    ``,
    `| §7 gate | OFF | ON (§6.2) | delta |`,
    `|---|---|---|---|`,
    row("role coverage", "roleCoverage"),
    row("interface preservation", "interfacePreservation"),
    row("composition preservation", "compositionPreservation"),
    row("fidelity", "fidelity"),
    row("cycle consistency", "cycleConsistency"),
    ``,
    `- forward functor: OFF mapped ${x.off.functor.nMapped}/${x.off.functor.nObjectsSrc}; ON mapped ${x.on.functor.nMapped}/${x.on.functor.nObjectsSrc}`,
    `- punch list length: OFF ${x.off.punchList.length}, ON ${x.on.punchList.length}`,
    ``,
    `## Punch list — normalization ON (first 12)`,
    "```",
    formatReport({ ...x.on, punchList: x.on.punchList.slice(0, 12) }),
    "```",
  ].join("\n");
}

async function* readLines(path: string): AsyncGenerator<string> {
  const stream = Bun.file(path).stream();
  const dec = new TextDecoder();
  let buf = "";
  for await (const chunk of stream) {
    buf += dec.decode(chunk, { stream: true });
    let nl: number;
    while ((nl = buf.indexOf("\n")) >= 0) {
      const line = buf.slice(0, nl).trim();
      buf = buf.slice(nl + 1);
      if (line) yield line;
    }
  }
  if (buf.trim()) yield buf.trim();
}

await main();
