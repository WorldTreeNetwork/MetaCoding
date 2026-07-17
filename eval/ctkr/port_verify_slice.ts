/**
 * Structural port-verify driver (Stage 3b) for the logs+quantities slice.
 *
 * Two-data-dir adaptation of eval/ctkr/port_verify_experiment.ts:
 *   - SPEC side S  = the farmOS logs subsystem (roles/interfaces/operads +
 *     hom-profiles + edges) from the scoped farmOS data-dir.
 *   - PORT side S' = the whole Bun/TS port (all symbols) from the port data-dir
 *     (indexed with metacoding --scip ts, hom-profiles computed there).
 *
 * Runs verifyPort ON (§6.2 cross-language normalization) and OFF, with optional
 * port_decisions waivers. Emits the punch list + raw and net gate scores.
 *
 * Usage:
 *   bun run port_verify_slice.ts \
 *     --spec-dd <farmos data-dir> --spec-subsystem <ss id> \
 *     --port-dd <port data-dir> \
 *     [--decisions <port_decisions.jsonl>] [--metacoding <repo root>]
 */
import { DuckDBInstance } from "@duckdb/node-api";
import { join } from "node:path";
import { readFileSync, existsSync } from "node:fs";

const vp = await import(new URL("../../src/ctkr/verifyPort.ts", import.meta.url).pathname);
const pd = await import(new URL("../../src/ctkr/portDecisions.ts", import.meta.url).pathname);
const { verifyPort, formatReport, loadNormalization } = vp;

function coerce(v: unknown): unknown {
  if (typeof v === "bigint") return Number(v);
  if (v && typeof v === "object" && "items" in (v as Record<string, unknown>)) {
    return (v as { items: unknown[] }).items.map(coerce);
  }
  return v;
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

async function main() {
  const argv = Bun.argv.slice(2);
  const arg = (n: string, d?: string) => { const i = argv.indexOf(`--${n}`); return i >= 0 ? argv[i + 1] : d; };
  const specDD = arg("spec-dd")!;
  const specPrefix = arg("spec-subsystem")!;
  const portDD = arg("port-dd")!;
  const decisionsPath = arg("decisions");
  const view = (arg("view", "similarity") as "similarity" | "orbit");

  const inst = await DuckDBInstance.create(":memory:");
  const conn = await inst.connect();
  const q = async (sql: string): Promise<Record<string, unknown>[]> => {
    const r = await conn.runAndReadAll(sql);
    const names = r.columnNames();
    return r.getRows().map((row) => { const o: Record<string, unknown> = {}; names.forEach((n, i) => (o[n] = coerce(row[i]))); return o; });
  };
  const specCtkr = join(specDD, "ctkr");
  const portCtkr = join(portDD, "ctkr");
  const PS = (f: string) => `read_parquet('${join(specCtkr, f)}')`;
  const PP = (f: string) => `read_parquet('${join(portCtkr, f)}')`;

  // resolve spec subsystem id
  const subs = await q(`SELECT subsystem_id FROM ${PS("subsystems.parquet")}`);
  const specId = String(subs.find((s) => String(s.subsystem_id).startsWith(specPrefix))!.subsystem_id);

  // spec members
  const specMembers = new Set((await q(`SELECT symbol_id FROM ${PS("subsystem_members.parquet")} WHERE subsystem_id='${specId}'`)).map((r) => String(r.symbol_id)));

  // hom-profiles per side
  const specProf = new Map<string, number[]>();
  for (const r of await q(`SELECT symbol_id, profile_vec FROM ${PS("hom_profiles.parquet")}`)) specProf.set(String(r.symbol_id), (r.profile_vec as number[]).map(Number));
  const portProf = new Map<string, number[]>();
  for (const r of await q(`SELECT symbol_id, profile_vec FROM ${PP("hom_profiles.parquet")}`)) portProf.set(String(r.symbol_id), (r.profile_vec as number[]).map(Number));

  // node meta per side
  const meta = async (ctkrDir: string) => {
    const m = new Map<string, { kind: string; lang: string; qn: string }>();
    for await (const line of readLines(join(ctkrDir, "export", "nodes.jsonl"))) {
      const r = JSON.parse(line);
      m.set(r.id, { kind: r.kind ?? "unknown", lang: r.language ?? "", qn: r.qualified_name ?? "" });
    }
    return m;
  };
  const specMeta = await meta(specCtkr);
  const portMeta = await meta(portCtkr);
  // port members = every port symbol that has a profile + meta
  const portMembers = new Set([...portProf.keys()].filter((id) => portMeta.has(id)));

  // edges per side (member-internal)
  const specEdges: { src: string; dst: string; kind: string }[] = [];
  for await (const line of readLines(join(specCtkr, "export", "edges.jsonl"))) {
    const r = JSON.parse(line); const e = { src: r.src_id, dst: r.dst_id, kind: r.kind };
    if (specMembers.has(e.src) && specMembers.has(e.dst)) specEdges.push(e);
  }
  const portEdges: { src: string; dst: string; kind: string }[] = [];
  for await (const line of readLines(join(portCtkr, "export", "edges.jsonl"))) {
    const r = JSON.parse(line); const e = { src: r.src_id, dst: r.dst_id, kind: r.kind };
    if (portMembers.has(e.src) && portMembers.has(e.dst)) portEdges.push(e);
  }

  const sideObjects = (members: Set<string>, prof: Map<string, number[]>, m: Map<string, any>) => {
    const out: any[] = [];
    for (const id of members) { const pv = prof.get(id); const nm = m.get(id); if (!pv || !nm) continue; out.push({ id, kind: nm.kind, profileVec: pv }); }
    return out;
  };
  const specObjects = sideObjects(specMembers, specProf, specMeta);
  const portObjects = sideObjects(portMembers, portProf, portMeta);
  const seedableSpec = new Set(specObjects.map((o) => o.id));
  const seedablePort = new Set(portObjects.map((o) => o.id));
  const qnMap = (ids: Set<string>, m: Map<string, any>) => new Map([...ids].map((id) => [id, m.get(id)?.qn ?? id]));
  const domLang = (ids: Set<string>, m: Map<string, any>) => {
    const c: Record<string, number> = {}; for (const id of ids) { const l = m.get(id)?.lang; if (l) c[l] = (c[l] ?? 0) + 1; }
    return Object.entries(c).sort((a, b) => b[1] - a[1])[0]?.[0] ?? "";
  };

  // spec roles / provides / ops
  const pres = await q(`SELECT role_id, members, interface_participation, exemplar_symbol_id, exemplar_qualified_name, cardinality FROM ${PS("presentations.parquet")} WHERE subsystem_id='${specId}' AND view='${view}'`);
  const roles = pres.map((r) => {
    const members = (r.members as string[]).map(String);
    const qn = specMeta.get(String(r.exemplar_symbol_id))?.qn;
    return { roleId: String(r.role_id), label: qn ? qn.split("::").pop() : String(r.role_id).slice(0, 10), members,
      interfaceParticipation: (r.interface_participation as string[]).map(String), exemplarSymbolId: String(r.exemplar_symbol_id),
      exemplarQualifiedName: String(r.exemplar_qualified_name ?? qn ?? ""), cardinality: Number(r.cardinality), invarianceTier: "I",
      isIsolated: members.every((mm) => !seedableSpec.has(mm)) };
  });
  const ifaceRows = await q(`SELECT internal_symbol_id, internal_qualified_name, edge_kind FROM ${PS("interfaces.parquet")} WHERE subsystem_id='${specId}' AND direction='provides'`);
  const provMap = new Map<string, any>();
  for (const r of ifaceRows) { const id = String(r.internal_symbol_id); let p = provMap.get(id); if (!p) provMap.set(id, (p = { internalSymbolId: id, internalQualifiedName: String(r.internal_qualified_name ?? ""), usageModes: [] })); if (!p.usageModes.includes(String(r.edge_kind))) p.usageModes.push(String(r.edge_kind)); }
  const provides = [...provMap.values()];
  const opRows = await q(`SELECT operation_id, op_kind, input_roles, output_role, edge_kinds, is_boundary_op, exemplar_paths FROM ${PS("operads.parquet")} WHERE subsystem_id='${specId}' AND view='${view}' AND op_kind != 'non_operadic'`);
  const ops = opRows.map((r) => ({ operationId: String(r.operation_id), opKind: String(r.op_kind), inputRoles: (r.input_roles as string[]).map(String), outputRole: String(r.output_role), edgeKinds: (r.edge_kinds as string[]).map(String), isBoundaryOp: Boolean(r.is_boundary_op), invarianceTier: "I", exemplarPaths: (r.exemplar_paths as string[] ?? []).map(String) }));

  const spec = { subsystemId: specId, repo: "farmos", name: "logs", view, roles, provides, ops };
  const source = { objects: specObjects, edges: specEdges, memberSet: seedableSpec, qualifiedNames: qnMap(specMembers, specMeta), language: domLang(specMembers, specMeta) };
  const port = { objects: portObjects, edges: portEdges, memberSet: seedablePort, qualifiedNames: qnMap(portMembers, portMeta), language: domLang(portMembers, portMeta) };

  const decisions = decisionsPath && existsSync(decisionsPath) ? pd.loadPortDecisions(decisionsPath) : [];

  console.log(`spec S = ${specId} (${source.language}, ${specObjects.length} seedable / ${specMembers.size} members, ${specEdges.length} internal edges, ${roles.length} roles, ${provides.length} provides, ${ops.length} ops)`);
  console.log(`port S' = TS port (${port.language}, ${portObjects.length} seedable / ${portMembers.size} members, ${portEdges.length} internal edges)`);
  console.log(`decisions loaded: ${decisions.length}\n`);

  const off = verifyPort({ spec, source, port, normalization: null, decisions });
  const on = verifyPort({ spec, source, port, normalization: loadNormalization(), decisions });

  console.log("========== NORMALIZATION OFF ==========");
  console.log(formatReport(off));
  console.log("\n========== NORMALIZATION ON (§6.2) ==========");
  console.log(formatReport(on));
  conn.closeSync();
}
await main();
