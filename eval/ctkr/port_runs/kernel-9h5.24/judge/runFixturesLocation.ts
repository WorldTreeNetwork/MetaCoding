#!/usr/bin/env bun
/**
 * Independent value-equivalence runner (JUDGE-side, m11 location/movement feature).
 * NOT written by either builder. Reads the observed fixture pack and drives a
 * port's adapter through the documented contract, reporting pass/fail per fixture.
 *
 *   bun run runFixtures.ts <FIXTURES.jsonl> <path-to-port/src/oracleAdapter.ts>
 *
 * "now" for a read = the largest movement timestamp in the scenario; an
 * assertion may override with its own `at` (query-as-of).
 */
import { readFileSync } from "node:fs";

interface Given { alias: string; entity: string; is_location?: boolean; is_fixed?: boolean; intrinsic_geometry?: string }
interface When {
  action: string; alias?: string; ref?: string; status?: string;
  assets?: string[]; locations?: string[]; t?: number; geometry?: string;
}
interface Then {
  assert: string; subject: string; at?: number; location?: string; asset?: string;
  op?: string; value: unknown;
}
interface Fixture { fixture_id: string; title: string; non_obvious?: boolean; given: Given[]; when: When[]; then: Then[] }

function eqValue(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
  return a === b;
}

async function main() {
  const [fixturesPath, adapterPath] = Bun.argv.slice(2);
  if (!fixturesPath || !adapterPath) {
    console.error("usage: bun run runFixtures.ts <FIXTURES.jsonl> <oracleAdapter.ts>");
    process.exit(2);
  }
  const mod = await import(adapterPath);
  const makeAdapter = mod.makeAdapter as () => any;
  if (typeof makeAdapter !== "function") throw new Error("port does not export makeAdapter()");

  const lines = readFileSync(fixturesPath, "utf8").split("\n").filter((l) => l.trim());
  const results: { id: string; title: string; non_obvious: boolean; ok: boolean; detail: string }[] = [];

  for (const line of lines) {
    const fx = JSON.parse(line) as Fixture;
    const a = makeAdapter();
    const H = new Map<string, string>(); // alias -> handle
    let ok = true;
    let detail = "";
    try {
      if (a.open) await a.open();

      for (const g of fx.given) {
        const h = await a.createAsset({
          entity: g.entity, name: g.alias,
          isLocation: g.is_location ?? false,
          isFixed: g.is_fixed ?? false,
          intrinsicGeometry: g.intrinsic_geometry,
        });
        H.set(g.alias, h);
      }

      let nowTs = 0;
      for (const w of fx.when) if (typeof w.t === "number") nowTs = Math.max(nowTs, w.t);

      for (const w of fx.when) {
        if (w.action === "move") {
          const h = await a.recordMovement({
            name: "move",
            assets: (w.assets ?? []).map((al) => H.get(al)!),
            locations: (w.locations ?? []).map((al) => H.get(al)!),
            status: w.status ?? "done",
            timestamp: w.t ?? 0,
            geometry: w.geometry,
          });
          if (w.alias) H.set(w.alias, h);
        } else if (w.action === "set_status") {
          await a.setLogStatus(H.get(w.ref!)!, w.status ?? "");
        } else {
          throw new Error(`unknown action ${w.action}`);
        }
      }

      for (const t of fx.then) {
        const subj = H.get(t.subject)!;
        const at = t.at ?? nowTs;
        let got: unknown;
        switch (t.assert) {
          case "current_location_count": {
            const locs = await a.currentLocations(subj, at); got = (locs as string[]).length; break;
          }
          case "is_at_location": {
            const locs = await a.currentLocations(subj, at);
            got = (locs as string[]).includes(H.get(t.location!)!); break;
          }
          case "has_location": got = await a.hasLocation(subj, at); break;
          case "current_geometry": got = await a.currentGeometry(subj, at); break;
          case "has_geometry": got = await a.hasGeometry(subj, at); break;
          case "is_fixed": got = await a.isFixed(subj); break;
          case "is_location": got = await a.isLocation(subj); break;
          case "assets_at_location_count": {
            const assets = await a.assetsAtLocation(subj, at); got = (assets as string[]).length; break;
          }
          case "location_contains": {
            const assets = await a.assetsAtLocation(subj, at);
            got = (assets as string[]).includes(H.get(t.asset!)!); break;
          }
          default: throw new Error(`unknown assert ${t.assert}`);
        }
        if (!eqValue(got, t.value)) {
          ok = false;
          const tag = t.location ? `->${t.location}` : t.asset ? `<-${t.asset}` : "";
          detail += `[${t.assert} ${t.subject}${tag}${t.at !== undefined ? "@" + t.at : ""}] got ${JSON.stringify(got)} != ${JSON.stringify(t.value)}; `;
        }
      }
      if (a.close) await a.close();
    } catch (e) {
      ok = false;
      detail = `EXCEPTION: ${(e as Error).message}`;
    }
    results.push({ id: fx.fixture_id.slice(0, 8), title: fx.title, non_obvious: !!fx.non_obvious, ok, detail });
  }

  const passed = results.filter((r) => r.ok).length;
  for (const r of results) {
    console.log(`${r.ok ? "PASS" : "FAIL"}  ${r.id}  ${r.non_obvious ? "[NON-OBV] " : "          "}${r.title}${r.ok ? "" : "\n      " + r.detail}`);
  }
  console.log(`\n${passed}/${results.length} fixtures passed`);
  console.log(JSON.stringify({ passed, total: results.length, results: results.map((r) => ({ id: r.id, ok: r.ok, non_obvious: r.non_obvious })) }));
  process.exit(passed === results.length ? 0 : 1);
}
await main();
