import { test, expect } from "bun:test";
import { SpineAssetStore, SPINE_ASSET_BUNDLES } from "../src/store.ts";

function fresh() {
  return new SpineAssetStore({ replicaId: "SA" });
}

test("an asset is born active into its bundle and archives monotonically", () => {
  const s = fresh();
  const a = s.createAsset({ bundle: "compost", name: "pile A" });
  expect(s.assetActive(a)).toBe(true);
  expect(s.bundleOf(a)).toBe("compost");
  expect(s.assetName(a)).toBe("pile A");
  s.archiveAsset(a);
  expect(s.assetActive(a)).toBe(false);
  // monotonic: a further archive keeps it inactive, never resurrects
  s.archiveAsset(a);
  expect(s.assetActive(a)).toBe(false);
});

test("assetActive is false for an unknown handle (no created event)", () => {
  const s = fresh();
  expect(s.assetActive(s.mint("asset"))).toBe(false);
  expect(s.isLocation(s.mint("asset"))).toBeUndefined();
});

test("water is the only cluster bundle defaulting is_location/is_fixed true", () => {
  const s = fresh();
  const w = s.createAsset({ bundle: "water", name: "reservoir" });
  expect(s.isLocation(w)).toBe(true);
  expect(s.isFixed(w)).toBe(true);
  for (const b of ["compost", "equipment", "material", "plant", "product", "seed"]) {
    const cfg = SPINE_ASSET_BUNDLES[b]!;
    expect(cfg.isLocationDefault).toBe(false);
    expect(cfg.isFixedDefault).toBe(false);
  }
});

test("a per-asset flag override wins over the bundle default (LocationDefaultValues)", () => {
  const s = fresh();
  // water defaults true/true — override is_location to false on this instance
  const w = s.createAsset({ bundle: "water", name: "tanker truck", isLocation: false, isFixed: false });
  expect(s.isLocation(w)).toBe(false);
  expect(s.isFixed(w)).toBe(false);
  // a compost pile explicitly marked a location
  const c = s.createAsset({ bundle: "compost", name: "windrow", isLocation: true });
  expect(s.isLocation(c)).toBe(true);
  expect(s.isFixed(c)).toBe(false);
});

test("required bundle fields are enforced at creation", () => {
  const s = fresh();
  expect(() => s.createAsset({ bundle: "material", name: "compost tea" })).toThrow(
    /requires field 'material_type'/,
  );
  expect(() => s.createAsset({ bundle: "material", name: "x", fields: { material_type: "" } })).toThrow(
    /requires field 'material_type'/,
  );
  const ok = s.createAsset({ bundle: "material", name: "compost tea", fields: { material_type: "term:soil-amendment" } });
  expect(s.fieldOf(ok, "material_type")).toBe("term:soil-amendment");
});

test("plant requires plant_type (multiple) and carries season as an array", () => {
  const s = fresh();
  expect(() => s.createAsset({ bundle: "plant", name: "row 1" })).toThrow(/requires field 'plant_type'/);
  const p = s.createAsset({
    bundle: "plant",
    name: "row 1",
    fields: { plant_type: ["term:tomato", "term:brandywine"], season: ["term:2026"] },
  });
  expect(s.fieldOf(p, "plant_type")).toEqual(["term:tomato", "term:brandywine"]);
  expect(s.fieldOf(p, "season")).toEqual(["term:2026"]);
});

test("a single-valued required field rejects an array", () => {
  const s = fresh();
  expect(() =>
    s.createAsset({ bundle: "product", name: "jam", fields: { product_type: ["a", "b"] } }),
  ).toThrow(/single-valued/);
});

test("an undeclared field on a bundle is rejected (no silent drop)", () => {
  const s = fresh();
  expect(() =>
    s.createAsset({ bundle: "equipment", name: "tractor", fields: { horsepower: "40" } }),
  ).toThrow(/declares no field 'horsepower'/);
});

test("equipment carries its four optional typed fields", () => {
  const s = fresh();
  const e = s.createAsset({
    bundle: "equipment",
    name: "tractor",
    fields: {
      manufacturer: "Kubota",
      model: "L2501",
      serial_number: "SN-123",
      equipment_type: ["term:tractor"],
    },
  });
  expect(s.fieldOf(e, "manufacturer")).toBe("Kubota");
  expect(s.fieldOf(e, "equipment_type")).toEqual(["term:tractor"]);
  expect(s.fieldOf(e, "model")).toBe("L2501");
});

test("listByBundle returns creation-ordered assets of one bundle only", () => {
  const s = fresh();
  const c1 = s.createAsset({ bundle: "compost", name: "c1" });
  s.createAsset({ bundle: "water", name: "w1" });
  const c2 = s.createAsset({ bundle: "compost", name: "c2" });
  expect(s.listByBundle("compost")).toEqual([c1, c2]);
});

test("an unknown bundle is rejected", () => {
  const s = fresh();
  expect(() => s.createAsset({ bundle: "animal", name: "cow" })).toThrow(/unknown asset bundle/);
});
