/**
 * Independent value-equivalence runner (Stage 3a).
 * Verifier-side, NOT written by the builder. Reads the canonical fixture pack and
 * drives the port's adapter through the documented contract, reporting pass/fail
 * per fixture. Usage:
 *   bun run runFixtures.ts <fixtures.jsonl> <path-to-port/src/oracleAdapter.ts>
 */
import { readFileSync } from "node:fs";

interface QuantitySpec { measure: string; value: number; unit: string; label?: string }
interface GivenStep { entity: string; alias: string; name: string; descriptor?: string }
interface WhenStep {
  action: string; alias?: string; ref?: string; name?: string; kind?: string;
  status?: string; against?: string[]; group?: string; quantities?: QuantitySpec[];
}
interface ThenAssertion {
  assert: string; subject: string; measure?: string; unit?: string; kind?: string;
  group?: string; op?: string; value: unknown;
}
interface Fixture {
  fixture_id: string; title: string; feature?: string;
  given: GivenStep[]; when: WhenStep[]; then: ThenAssertion[];
}

function cmp(op: string, a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") {
    const eps = 1e-9;
    switch (op) {
      case "==": return Math.abs(a - b) < eps;
      case "!=": return Math.abs(a - b) >= eps;
      case ">": return a > b; case ">=": return a >= b;
      case "<": return a < b; case "<=": return a <= b;
    }
  }
  switch (op) {
    case "==": return a === b;
    case "!=": return a !== b;
    default: return false;
  }
}

async function main() {
  const [fixturesPath, adapterPath] = Bun.argv.slice(2);
  if (!fixturesPath || !adapterPath) {
    console.error("usage: bun run runFixtures.ts <fixtures.jsonl> <oracleAdapter.ts>");
    process.exit(2);
  }
  const mod = await import(adapterPath);
  const makeAdapter = mod.makeAdapter as () => any;
  if (typeof makeAdapter !== "function") throw new Error("port does not export makeAdapter()");

  const lines = readFileSync(fixturesPath, "utf8").split("\n").filter((l) => l.trim());
  const results: { id: string; title: string; ok: boolean; detail: string }[] = [];

  for (const line of lines) {
    const fx = JSON.parse(line) as Fixture;
    const a = makeAdapter();
    const H = new Map<string, string>(); // alias -> handle
    let ok = true;
    let detail = "";
    try {
      if (a.open) await a.open();
      for (const g of fx.given) {
        const h = await a.createAsset(g.entity, g.name, g.descriptor ?? "");
        H.set(g.alias, h);
      }
      for (const w of fx.when) {
        if (w.action === "record_log") {
          const assets = (w.against ?? []).map((al) => H.get(al)!);
          const h = await a.recordLog(w.kind ?? "", w.name ?? "", w.status ?? "done", assets, w.quantities ?? []);
          if (w.alias) H.set(w.alias, h);
        } else if (w.action === "set_log_status") {
          await a.setLogStatus(H.get(w.ref!)!, w.status ?? "");
        } else if (w.action === "assign_to_group") {
          await a.assignToGroup(H.get(w.ref!)!, H.get(w.group!)!);
        } else if (w.action === "archive_asset") {
          await a.archiveAsset(H.get(w.ref!)!);
        } else {
          throw new Error(`unknown action ${w.action}`);
        }
      }
      for (const t of fx.then) {
        const subj = H.get(t.subject);
        let got: unknown;
        switch (t.assert) {
          case "yield_total": got = await a.assetYieldTotal(subj, t.measure ?? "", t.unit ?? ""); break;
          case "log_status": got = await a.logStatus(subj); break;
          case "log_count": got = await a.logCount(subj, t.kind ?? ""); break;
          case "asset_active": got = await a.assetActive(subj); break;
          case "group_member": got = await a.groupMember(subj, H.get(t.group!)!); break;
          case "quantity_recorded": got = await a.quantityRecorded(subj, t.measure ?? "", t.unit ?? ""); break;
          default: throw new Error(`unknown assert ${t.assert}`);
        }
        const op = t.op ?? "==";
        if (!cmp(op, got, t.value)) {
          ok = false;
          detail += `[${t.assert} ${t.subject}] got ${JSON.stringify(got)} ${op} ${JSON.stringify(t.value)} FAIL; `;
        }
      }
      if (a.close) await a.close();
    } catch (e) {
      ok = false;
      detail = `EXCEPTION: ${(e as Error).message}`;
    }
    results.push({ id: fx.fixture_id.slice(0, 8), title: fx.title, ok, detail });
  }

  const passed = results.filter((r) => r.ok).length;
  for (const r of results) {
    console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.id}  ${r.title}${r.ok ? "" : "\n      " + r.detail}`);
  }
  console.log(`\n${passed}/${results.length} fixtures passed`);
  console.log(JSON.stringify({ passed, total: results.length, results: results.map((r) => ({ id: r.id, ok: r.ok })) }));
  process.exit(passed === results.length ? 0 : 1);
}
await main();
