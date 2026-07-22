import { test, expect } from "bun:test";
import { makeCompostAdapter } from "../src/compost.ts";
import { SpineAssetStore } from "../../shared-store/src/store.ts";

function setup() {
  const store = new SpineAssetStore({ replicaId: "compost" });
  return { store, port: makeCompostAdapter(store) };
}

test("compost asset is born active with no bundle fields", () => {
  const { port, store } = setup();
  const a = port.createCompost("windrow 1");
  expect(port.isActive(a)).toBe(true);
  expect(store.bundleOf(a)).toBe("compost");
  // compost declares no farm_location flags → defaults false/false
  expect(store.isLocation(a)).toBe(false);
  expect(store.isFixed(a)).toBe(false);
});

test("archive flips active off; listCompost tracks births", () => {
  const { port } = setup();
  const a = port.createCompost("pile A");
  const b = port.createCompost("pile B");
  port.archive(a);
  expect(port.isActive(a)).toBe(false);
  expect(port.isActive(b)).toBe(true);
  expect(port.listCompost()).toEqual([a, b]);
});
