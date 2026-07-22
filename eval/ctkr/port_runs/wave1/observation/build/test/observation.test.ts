import { test, expect } from "bun:test";
import { makeObservationAdapter, OBSERVATION_KINDS } from "../src/observation.ts";
import { Wave1LogStore } from "../../../shared-store/src/store.ts";

const NOW = Date.now();

function setup() {
  const store = new Wave1LogStore({ replicaId: "W1B", extraKinds: OBSERVATION_KINDS });
  const port = makeObservationAdapter(store);
  const actor = store.mint("actor");
  const bed = store.createAsset({ entity: "planting", name: "bed" });
  return { store, port, actor, bed };
}

test("selection is consumed exactly once; the query returns its assets, a reuse throws", () => {
  const { port, actor, bed } = setup();
  const sel = port.startObservationAddSelection(actor, [bed]);
  const query = port.confirmObservationAddSelection(actor, sel);
  expect(port.getConfirmedObservationAssetQuery(query, Date.now())).toEqual([bed]);
  expect(() => port.confirmObservationAddSelection(actor, sel)).toThrow(/already consumed/);
});

test("an unknown asset query reads as the empty list (payload no longer available)", () => {
  const { port, store } = setup();
  expect(port.getConfirmedObservationAssetQuery(store.mint("aq"), NOW)).toEqual([]);
});

test("recordObservation preserves the raw submitted asset list exactly", () => {
  const { port, store, bed } = setup();
  const ghost = store.mint("asset"); // never created — raw list is NOT replaced
  const q = port.mintQuantityRevision({ measure: "temperature", value: 21, unit: "celsius" });
  const obs = port.recordObservation([bed, ghost], [q], "done", NOW - 20_000);
  const snap = port.getObservation(obs, NOW)!;
  expect(snap.assetIds).toEqual([bed, ghost]);
  expect(snap.quantityRevisions.length).toBe(1);
  expect(snap.status).toBe("done");
});

test("create forms prepopulate from the raw query; edit forms never do", () => {
  const { port, bed } = setup();
  expect(port.getObservationAssetPrepopulation("create", [bed], NOW)).toEqual([bed]);
  expect(port.getObservationAssetPrepopulation("edit", [bed], NOW)).toEqual([]);
});

test("cloning mints distinct quantities: deleting a source quantity leaves the clone whole", () => {
  const { port, store, bed } = setup();
  const q = port.mintQuantityRevision({ measure: "weight", value: 4, unit: "kilograms" });
  const src = port.recordObservation([bed], [q], "done", NOW - 20_000);
  const clone = port.cloneObservation(src, NOW - 10_000);
  const srcQty = port.getObservation(src, NOW)!.quantityRevisions[0]!;
  const cloneQty = port.getObservation(clone, NOW)!.quantityRevisions[0]!;
  expect(cloneQty).not.toBe(srcQty);
  port.recordQuantityDeletion(srcQty, NOW - 5_000);
  expect(port.getObservation(src, NOW)!.quantityRevisions).toEqual([]);
  expect(port.getObservation(clone, NOW)!.quantityRevisions).toEqual([cloneQty]);
});

test("quantity deletion adds a revision carrying the deleted quantity id", () => {
  const { port, bed } = setup();
  const q1 = port.mintQuantityRevision({ measure: "weight", value: 5, unit: "kilograms" });
  const q2 = port.mintQuantityRevision({ measure: "weight", value: 3, unit: "pounds" });
  const obs = port.recordObservation([bed], [q1, q2], "done", NOW - 20_000);
  const [qty1] = port.getObservation(obs, NOW)!.quantityRevisions;
  port.recordQuantityDeletion(qty1!, NOW - 1_000);
  const revs = port.listObservationRevisions(obs, Date.now());
  expect(revs.length).toBe(2);
  expect(revs[1]!.message).toContain(String(qty1));
  expect(revs[1]!.quantityRevisions.length).toBe(1);
});

test("observation deletion cascades to every referenced quantity", () => {
  const { port, store, bed } = setup();
  const q = port.mintQuantityRevision({ measure: "weight", value: 2, unit: "kilograms" });
  const obs = port.recordObservation([bed], [q], "done", NOW - 20_000);
  const qty = port.getObservation(obs, NOW)!.quantityRevisions[0]!;
  port.recordObservationDeletion(obs, NOW - 1_000);
  expect(port.getObservation(obs, NOW)).toBeNull();
  expect(store.isQuantityDeleted(qty)).toBe(true);
  expect(store.yieldTotal(bed, "weight", "kilograms")).toBe(0);
});

test("list/first for an asset follow ascending (effectiveTime, HLC) and respect asOf", () => {
  const { port, bed } = setup();
  const late = port.recordObservation([bed], [], "done", NOW - 5_000);
  const early = port.recordObservation([bed], [], "done", NOW - 50_000);
  const future = port.recordObservation([bed], [], "done", NOW + 86_400_000);
  expect(port.listObservationsForAsset(bed, NOW)).toEqual([early, late]);
  expect(port.getFirstObservationForAsset(bed, NOW)).toBe(early);
  expect(port.listObservationsForAsset(bed, NOW + 2 * 86_400_000)).toEqual([early, late, future]);
});

test("a quantity-less observation is valid and folds to zero", () => {
  const { port, store, bed } = setup();
  const obs = port.recordObservation([bed], [], "done", NOW - 10_000);
  expect(port.getObservation(obs, NOW)).not.toBeNull();
  expect(store.yieldTotal(bed, "weight", "kilograms")).toBe(0);
  expect(store.logCount(bed, "observation")).toBe(1);
});

test("default quantity type is null (no configuration source in this surface)", () => {
  const { port } = setup();
  expect(port.getDefaultQuantityType(NOW)).toBeNull();
});
