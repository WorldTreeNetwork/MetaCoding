import { test, expect } from "bun:test";
import { makeEquipmentAdapter } from "../src/equipment.ts";
import { SpineAssetStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new SpineAssetStore({ replicaId: "equip" });
  return { store, port: makeEquipmentAdapter(store) };
}

test("equipment carries its four optional typed fields; all absent is valid", () => {
  const { port, store } = setup();
  const bare = port.createEquipment("mystery tool");
  expect(port.isActive(bare)).toBe(true);
  expect(port.manufacturerOf(bare)).toBeUndefined();
  expect(port.equipmentTypesOf(bare)).toEqual([]);

  const tractor = port.createEquipment("tractor", {
    manufacturer: "Kubota",
    model: "L2501",
    serialNumber: "SN-1",
    equipmentType: ["term:tractor", "term:diesel"],
  });
  expect(port.manufacturerOf(tractor)).toBe("Kubota");
  expect(port.modelOf(tractor)).toBe("L2501");
  expect(port.serialNumberOf(tractor)).toBe("SN-1");
  expect(port.equipmentTypesOf(tractor)).toEqual(["term:tractor", "term:diesel"]);
  expect(store.isLocation(tractor)).toBe(false);
});

test("equipment archives on the shared spine", () => {
  const { port } = setup();
  const a = port.createEquipment("drill");
  port.archive(a);
  expect(port.isActive(a)).toBe(false);
});
