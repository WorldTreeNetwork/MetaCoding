// Fixture-driven suite for the logs+quantities feature (FIXTURES_LOGS.jsonl),
// exercised through createComposedStore().logs — the OracleAdapter runner
// contract described in ADAPTER_CONTRACT_LOGS.md.

import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { createComposedStore } from "../src/index";
import type { OracleAdapter, Handle, QuantitySpec } from "../src/types";

interface GivenSpec {
  entity: string;
  alias: string;
  name: string;
  descriptor?: string;
}

interface WhenSpec {
  action: string;
  alias?: string;
  ref?: string;
  name?: string;
  kind?: string;
  status?: string;
  against?: string[];
  group?: string;
  quantities?: QuantitySpec[];
}

interface ThenSpec {
  assert: string;
  subject: string;
  measure?: string;
  unit?: string;
  kind?: string;
  group?: string;
  op: string;
  value: unknown;
}

interface Fixture {
  fixture_id: string;
  title: string;
  given: GivenSpec[];
  when: WhenSpec[];
  then: ThenSpec[];
}

function loadFixtures(path: string): Fixture[] {
  return readFileSync(path, "utf-8")
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean)
    .map((l) => JSON.parse(l));
}

async function runFixture(adapter: OracleAdapter, fx: Fixture) {
  const handles = new Map<string, Handle>();

  for (const g of fx.given) {
    const h = await adapter.createAsset(g.entity, g.name, g.descriptor);
    handles.set(g.alias, h);
  }

  for (const w of fx.when) {
    switch (w.action) {
      case "record_log": {
        const h = await adapter.recordLog(
          w.kind!,
          w.name ?? "",
          w.status!,
          (w.against ?? []).map((a) => handles.get(a)!),
          w.quantities ?? [],
        );
        if (w.alias) handles.set(w.alias, h);
        break;
      }
      case "set_log_status":
        await adapter.setLogStatus(handles.get(w.ref!)!, w.status!);
        break;
      case "assign_to_group":
        await adapter.assignToGroup(handles.get(w.ref!)!, handles.get(w.group!)!);
        break;
      case "archive_asset":
        await adapter.archiveAsset(handles.get(w.ref!)!);
        break;
      default:
        throw new Error(`unknown action ${w.action}`);
    }
  }

  for (const t of fx.then) {
    const subject = handles.get(t.subject)!;
    let actual: unknown;
    switch (t.assert) {
      case "yield_total":
        actual = await adapter.assetYieldTotal(subject, t.measure!, t.unit!);
        break;
      case "log_status":
        actual = await adapter.logStatus(subject);
        break;
      case "log_count":
        actual = await adapter.logCount(subject, t.kind!);
        break;
      case "asset_active":
        actual = await adapter.assetActive(subject);
        break;
      case "group_member":
        actual = await adapter.groupMember(subject, handles.get(t.group!)!);
        break;
      case "quantity_recorded":
        actual = await adapter.quantityRecorded(subject, t.measure!, t.unit!);
        break;
      default:
        throw new Error(`unknown assert ${t.assert}`);
    }

    if (typeof t.value === "number") {
      expect(actual as number).toBeCloseTo(t.value, 9);
    } else {
      expect(actual).toBe(t.value);
    }
  }
}

const fixtures = loadFixtures(`${import.meta.dir}/../inputs/FIXTURES_LOGS.jsonl`);

describe("logs adapter fixtures", () => {
  for (const fx of fixtures) {
    test(`${fx.title} [${fx.fixture_id}]`, async () => {
      const { logs } = createComposedStore();
      await runFixture(logs, fx);
    });
  }
});

describe("composed store sharing", () => {
  test("an asset created via logs is referenceable via location", async () => {
    const { logs, location } = createComposedStore();
    const land = await logs.createAsset("land", "Shared Field", "");
    expect(await location.isLocation(land)).toBe(false);
    expect(await location.isFixed(land)).toBe(false);
    expect(await location.hasLocation(land, 0)).toBe(false);
  });

  test("two separate createComposedStore() calls are independent", async () => {
    const a = createComposedStore();
    const b = createComposedStore();
    const h1 = await a.logs.createAsset("land", "F1", "");
    const h2 = await b.logs.createAsset("land", "F2", "");
    // Independent stores mint independently; both start counting from 1, so
    // b's asset must not resolve as active state shared with a's log.
    await a.logs.archiveAsset(h1);
    expect(await a.logs.assetActive(h1)).toBe(false);
    expect(await b.logs.assetActive(h2)).toBe(true);
  });
});
