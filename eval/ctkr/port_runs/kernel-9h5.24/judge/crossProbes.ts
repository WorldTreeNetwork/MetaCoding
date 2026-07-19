// JUDGE-AUTHORED cross-feature probes (MetaCoding-9h5.16).
//
// These are NOT from either fixture pack and NOT new oracle observations. Each
// is a MECHANICAL DERIVATION from semantics already observed in the two packs,
// re-applied to ONE shared composed store to test the composition property the
// isolated runs never touched: that both adapters are thin views over the SAME
// event log / asset model / id space. Expected values are derived by hand from
// the packs' own rules (labeled per-probe), not recorded from live farmOS.
//
// Run: bun run judge/crossProbes.ts
import { createComposedStore } from "../build/src/index";

type Check = { name: string; got: unknown; want: unknown; ok: boolean };
const probes: { id: string; title: string; basis: string; checks: Check[] }[] = [];

function eq(a: unknown, b: unknown): boolean {
  if (typeof a === "number" && typeof b === "number") return Math.abs(a - b) < 1e-9;
  if (Array.isArray(a) && Array.isArray(b)) return a.length === b.length && a.every((x, i) => x === b[i]);
  return a === b;
}
function check(checks: Check[], name: string, got: unknown, want: unknown) {
  checks.push({ name, got, want, ok: eq(got, want) });
}

async function main() {
  // ---- CP1: ONE asset identity, read by BOTH projections; sharing both directions ----
  // Basis: logs pack 74303d7d (harvest→yield 5) + location pack 95de1fa8 (done move→at location).
  {
    const checks: Check[] = [];
    const { logs, location } = createComposedStore();
    // asset created via LOGS adapter, then MOVED via LOCATION adapter (logs->location sharing)
    const field = await location.createAsset({ entity: "land", name: "F", isLocation: true });
    const cow = logs.createAsset("animal", "Bessie");            // minted by logs adapter
    await logs.recordLog("harvest", "h", "done", [cow], [{ measure: "weight", value: 5, unit: "kilogram" }]);
    await location.recordMovement({ assets: [cow], locations: [field], status: "done", timestamp: 10 });
    check(checks, "logs.assetYieldTotal(cow) == 5", await logs.assetYieldTotal(cow, "weight", "kilogram"), 5);
    check(checks, "location.currentLocations(cow)==[field]", await location.currentLocations(cow, 10), [field]);
    // asset created via LOCATION adapter, then HARVESTED via LOGS adapter (location->logs sharing)
    const bed = await location.createAsset({ entity: "land", name: "Bed" });
    await logs.recordLog("harvest", "h2", "done", [bed], [{ measure: "weight", value: 3, unit: "kilogram" }]);
    check(checks, "logs.assetYieldTotal(bed) == 3 (loc-minted asset)", await logs.assetYieldTotal(bed, "weight", "kilogram"), 3);
    check(checks, "logs.assetActive(field) == true (loc-minted asset visible to logs)", await logs.assetActive(field), true);
    check(checks, "cow handle distinct from field handle (one id space)", cow !== field, true);
    probes.push({ id: "CP1", title: "One asset identity read by both projections (both directions)", basis: "logs 74303d7d + location 95de1fa8", checks });
  }

  // ---- CP2: kind-filtered logs projections are isolated over the shared log ----
  // Basis: logs pack fba4a962 (logCount isolated by kind) + 03e4dd80 (yield across kinds).
  // Also probes the builder's choice: does a movement count in logCount-by-kind?
  {
    const checks: Check[] = [];
    const { logs, location } = createComposedStore();
    const cow = logs.createAsset("animal", "c");
    const loc = await location.createAsset({ entity: "land", name: "L", isLocation: true });
    await logs.recordLog("harvest", "h", "done", [cow], [{ measure: "weight", value: 5, unit: "kilogram" }]);
    await location.recordMovement({ assets: [cow], locations: [loc], status: "done", timestamp: 10 });
    check(checks, "logCount(cow,'harvest') == 1 (movement does not inflate)", await logs.logCount(cow, "harvest"), 1);
    check(checks, "yieldTotal(cow) == 5 (movement carries no quantity)", await logs.assetYieldTotal(cow, "weight", "kilogram"), 5);
    // Report-only signal (not a pass/fail gate): whether movement appears as a log kind.
    const asMovement = await logs.logCount(cow, "movement");
    const asActivity = await logs.logCount(cow, "activity");
    check(checks, "logCount(cow,'movement') [design signal: builder excludes movements] == 0", asMovement, 0);
    check(checks, "logCount(cow,'activity') == 0", asActivity, 0);
    probes.push({ id: "CP2", title: "Kind-filtered projections isolated; movement NOT counted as a log", basis: "logs fba4a962/03e4dd80 (movement-as-log is a builder design choice)", checks });
  }

  // ---- CP3: archive affects logs' assetActive AND leaves location history readable ----
  // Basis: logs pack 680138d8 (archived retains yield/log history) extended by analogy
  // to the shared log's location projection.
  {
    const checks: Check[] = [];
    const { logs, location } = createComposedStore();
    const loc = await location.createAsset({ entity: "land", name: "L", isLocation: true });
    const cow = await location.createAsset({ entity: "animal", name: "c" });
    await location.recordMovement({ assets: [cow], locations: [loc], status: "done", timestamp: 10 });
    await logs.recordLog("harvest", "h", "done", [cow], [{ measure: "weight", value: 5, unit: "kilogram" }]);
    logs.archiveAsset(cow);
    check(checks, "logs.assetActive(cow) == false after archive", await logs.assetActive(cow), false);
    check(checks, "location.currentLocations(cow) still == [loc] (history retained)", await location.currentLocations(cow, 10), [loc]);
    check(checks, "logs.yieldTotal(cow) still == 5 (history retained)", await logs.assetYieldTotal(cow, "weight", "kilogram"), 5);
    check(checks, "location.assetsAtLocation(loc) still contains cow", (await location.assetsAtLocation(loc, 10)).includes(cow), true);
    probes.push({ id: "CP3", title: "Archive flips assetActive but location & yield history remain readable", basis: "logs 680138d8 extended to the shared log", checks });
  }

  // ---- CP4: two independent latest-wins folds over ONE log don't interfere ----
  // Basis: logs ce015be4 (group reassignment latest-wins) + location 885eecc6 (assetsAtLocation latest-wins).
  {
    const checks: Check[] = [];
    const { logs, location } = createComposedStore();
    const g1 = logs.createAsset("group", "G1");
    const g2 = logs.createAsset("group", "G2");
    const locA = await location.createAsset({ entity: "land", name: "A", isLocation: true });
    const locB = await location.createAsset({ entity: "land", name: "B", isLocation: true });
    const cow = logs.createAsset("animal", "c");
    // interleave the two features' events on the SAME log
    logs.assignToGroup(cow, g1);
    await location.recordMovement({ assets: [cow], locations: [locA], status: "done", timestamp: 10 });
    logs.assignToGroup(cow, g2);
    await location.recordMovement({ assets: [cow], locations: [locB], status: "done", timestamp: 20 });
    check(checks, "groupMember(cow,g2) == true (latest group wins)", await logs.groupMember(cow, g2), true);
    check(checks, "groupMember(cow,g1) == false (prior revoked)", await logs.groupMember(cow, g1), false);
    check(checks, "currentLocations(cow) == [locB] (latest move wins)", await location.currentLocations(cow, 20), [locB]);
    check(checks, "assetsAtLocation(locA) does NOT contain cow", (await location.assetsAtLocation(locA, 20)).includes(cow), false);
    check(checks, "assetsAtLocation(locB) contains cow", (await location.assetsAtLocation(locB, 20)).includes(cow), true);
    probes.push({ id: "CP4", title: "Group latest-wins and location latest-wins coexist on one interleaved log", basis: "logs ce015be4 + location 885eecc6", checks });
  }

  // ---- CP5: ONE tie-break scheme (timestamp, seq) serves both latest-wins reads ----
  // Basis: location 43a074ca (same-timestamp move → later-recorded wins) + logs ce015be4
  // (assignToGroup has no domain timestamp → insertion order wins). Both must reduce to
  // the same (timestamp,seq) comparator in ONE store.
  {
    const checks: Check[] = [];
    const { logs, location } = createComposedStore();
    const locA = await location.createAsset({ entity: "land", name: "A", isLocation: true });
    const locB = await location.createAsset({ entity: "land", name: "B", isLocation: true });
    const g1 = logs.createAsset("group", "G1");
    const g2 = logs.createAsset("group", "G2");
    const cow = logs.createAsset("animal", "c");
    // same-timestamp movements: later-recorded (higher seq) must win
    await location.recordMovement({ assets: [cow], locations: [locA], status: "done", timestamp: 10 });
    await location.recordMovement({ assets: [cow], locations: [locB], status: "done", timestamp: 10 });
    check(checks, "same-ts move: currentLocations == [locB] (seq tie-break)", await location.currentLocations(cow, 10), [locB]);
    // un-timestamped group mutations: insertion order (seq) must win
    logs.assignToGroup(cow, g1);
    logs.assignToGroup(cow, g2);
    check(checks, "un-ts group: member g2 (seq order)", await logs.groupMember(cow, g2), true);
    check(checks, "un-ts group: not member g1", await logs.groupMember(cow, g1), false);
    probes.push({ id: "CP5", title: "One (timestamp,seq) comparator drives both timestamped and un-timestamped latest-wins", basis: "location 43a074ca + logs ce015be4", checks });
  }

  // ---- report ----
  let allOk = true;
  for (const p of probes) {
    const pOk = p.checks.every((c) => c.ok);
    allOk = allOk && pOk;
    console.log(`${pOk ? "PASS" : "FAIL"}  ${p.id}  ${p.title}`);
    console.log(`        basis: ${p.basis}`);
    for (const c of p.checks) {
      console.log(`        ${c.ok ? "ok " : "XX "}${c.name}${c.ok ? "" : `  got ${JSON.stringify(c.got)} want ${JSON.stringify(c.want)}`}`);
    }
  }
  const passed = probes.filter((p) => p.checks.every((c) => c.ok)).length;
  console.log(`\n${passed}/${probes.length} cross-probes passed`);
  console.log(JSON.stringify({ passed, total: probes.length, probes: probes.map((p) => ({ id: p.id, ok: p.checks.every((c) => c.ok) })) }));
  process.exit(allOk ? 0 : 1);
}
await main();
