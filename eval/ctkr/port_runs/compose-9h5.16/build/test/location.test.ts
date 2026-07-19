// Fixture-driven suite for the location+movement feature
// (FIXTURES_LOCATION.jsonl), exercised through createComposedStore().location
// — the LocationAdapter, whose only spec is ADAPTER_SIGNATURES_LOCATION.md
// plus these fixtures.

import { describe, expect, test } from "bun:test";
import { readFileSync } from "node:fs";
import { createComposedStore } from "../src/index";
import type { LocationAdapter, Handle } from "../src/types";

interface GivenSpec {
  alias: string;
  entity: string;
  is_location?: boolean;
  is_fixed?: boolean;
  intrinsic_geometry?: string;
}

interface WhenSpec {
  action: string;
  assets?: string[];
  locations?: string[];
  status?: string;
  t?: number;
  geometry?: string;
}

interface ThenSpec {
  assert: string;
  subject: string;
  value: unknown;
  location?: string;
  at?: number;
  asset?: string;
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

async function runFixture(adapter: LocationAdapter, fx: Fixture) {
  const handles = new Map<string, Handle>();

  for (const g of fx.given) {
    const h = await adapter.createAsset({
      entity: g.entity,
      name: g.alias,
      isLocation: g.is_location,
      isFixed: g.is_fixed,
      intrinsicGeometry: g.intrinsic_geometry,
    });
    handles.set(g.alias, h);
  }

  let maxT = 0;
  for (const w of fx.when) {
    if (w.action === "move") {
      maxT = Math.max(maxT, w.t ?? 0);
      await adapter.recordMovement({
        assets: w.assets!.map((a) => handles.get(a)!),
        locations: w.locations!.map((l) => handles.get(l)!),
        status: w.status!,
        timestamp: w.t!,
        geometry: w.geometry,
      });
    } else {
      throw new Error(`unknown action ${w.action}`);
    }
  }

  for (const t of fx.then) {
    const subject = handles.get(t.subject)!;
    const at = t.at ?? maxT;
    let actual: unknown;
    switch (t.assert) {
      case "is_at_location": {
        const locs = await adapter.currentLocations(subject, at);
        actual = locs.includes(handles.get(t.location!)!);
        break;
      }
      case "current_location_count":
        actual = (await adapter.currentLocations(subject, at)).length;
        break;
      case "has_location":
        actual = await adapter.hasLocation(subject, at);
        break;
      case "is_location":
        actual = await adapter.isLocation(subject);
        break;
      case "is_fixed":
        actual = await adapter.isFixed(subject);
        break;
      case "current_geometry":
        actual = await adapter.currentGeometry(subject, at);
        break;
      case "has_geometry":
        actual = await adapter.hasGeometry(subject, at);
        break;
      case "location_contains": {
        const assets = await adapter.assetsAtLocation(subject, at);
        actual = assets.includes(handles.get(t.asset!)!);
        break;
      }
      case "assets_at_location_count":
        actual = (await adapter.assetsAtLocation(subject, at)).length;
        break;
      default:
        throw new Error(`unknown assert ${t.assert}`);
    }
    expect(actual).toEqual(t.value);
  }
}

const fixtures = loadFixtures(`${import.meta.dir}/../inputs/FIXTURES_LOCATION.jsonl`);

describe("location adapter fixtures", () => {
  for (const fx of fixtures) {
    test(`${fx.title} [${fx.fixture_id}]`, async () => {
      const { location } = createComposedStore();
      await runFixture(location, fx);
    });
  }
});

describe("composed store sharing (location side)", () => {
  test("an asset created via location is referenceable via logs", async () => {
    const { logs, location } = createComposedStore();
    const cow = await location.createAsset({ entity: "animal", name: "Bessie" });
    expect(await logs.assetActive(cow)).toBe(true);
    await logs.archiveAsset(cow);
    expect(await logs.assetActive(cow)).toBe(false);
  });
});
