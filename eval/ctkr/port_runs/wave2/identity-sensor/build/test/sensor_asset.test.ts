// Identity-tier tests for the sensor port (MetaCoding-ej0). The oracle-observed
// shape (pack 44ecd9bff969): three bundle fields carried ON a sensor ASSET read
// back off the sensor itself — the ordered data stream NAMES ([] when none),
// the private key verbatim ('' when none), and the public flag where false is
// a stated VALUE and unstated reads '' — plus asset_active over the sensor's
// handle. Plus the port-only invariants the recording cannot state: fields are
// independent, distinct sensors keep their own values, archive applies to the
// sensor handle, and a subject that is not a sensor asset (a plain asset, a
// log, a plant_type term, an unknown handle) is unanswerable, never the empty
// value.
//
// These tests are NOT load-bearing — a fresh reader re-runs them and re-derives
// against the pack. They read the MATERIALIZED sensor state, never a
// caller-held input echo.

import { test, expect } from "bun:test";
import { Wave1LogStore } from "../../../../wave1/shared-store/src/store.ts";

function setup() {
  return new Wave1LogStore({ replicaId: "W2S" });
}

test("a sensor instantiated bare is an active asset", () => {
  const store = setup();
  const s = store.createSensorAsset({ name: "w4a-Greenhouse Probe" });
  expect(store.assetActive(s)).toBe(true);
});

test("an archived sensor reports inactive — the asset lifecycle applies to the sensor handle", () => {
  const store = setup();
  const s = store.createSensorAsset({ name: "w4a-Retired Probe" });
  store.archiveAsset(s);
  expect(store.assetActive(s)).toBe(false);
  // archiving touches lifecycle only: the bundle fields still read back.
  expect(store.sensorDataStreams(s)).toEqual([]);
  expect(store.sensorPrivateKey(s)).toBe("");
});

test("data streams read back in RECORDED order, not name order (B before A)", () => {
  const store = setup();
  const s = store.createSensorAsset({
    name: "w4a-Soil Station",
    dataStreams: ["w4a-Stream-B", "w4a-Stream-A"],
  });
  expect(store.sensorDataStreams(s)).toEqual(["w4a-Stream-B", "w4a-Stream-A"]);
});

test("data streams: single, empty, and duplicate names all read back verbatim", () => {
  const store = setup();
  const single = store.createSensorAsset({ name: "w4a-Weather Mast", dataStreams: ["w4a-Wind Speed"] });
  const none = store.createSensorAsset({ name: "w4a-Streamless Node" });
  // The source field is a multi-valued reference list; the port records the
  // delivered names verbatim — it neither sorts nor dedups.
  const dup = store.createSensorAsset({ name: "w4a-Echo Node", dataStreams: ["w4a-Twice", "w4a-Twice"] });
  expect(store.sensorDataStreams(single)).toEqual(["w4a-Wind Speed"]);
  expect(store.sensorDataStreams(none)).toEqual([]);
  expect(store.sensorDataStreams(dup)).toEqual(["w4a-Twice", "w4a-Twice"]);
});

test("two sensors naming the same stream name each report their own recorded copy", () => {
  const store = setup();
  const s1 = store.createSensorAsset({ name: "w4a-North Meter", dataStreams: ["w4a-Shared Flow"] });
  const s2 = store.createSensorAsset({ name: "w4a-South Meter", dataStreams: ["w4a-Shared Flow"] });
  expect(store.sensorDataStreams(s1)).toEqual(["w4a-Shared Flow"]);
  expect(store.sensorDataStreams(s2)).toEqual(["w4a-Shared Flow"]);
});

test("two sensors recording different private keys each report their own; an unstated key reads ''", () => {
  const store = setup();
  const s1 = store.createSensorAsset({ name: "w4a-Keyed Alpha", privateKey: "w4a-key-alpha-0001" });
  const s2 = store.createSensorAsset({ name: "w4a-Keyed Beta", privateKey: "w4a-key-beta-0002" });
  const s3 = store.createSensorAsset({ name: "w4a-Keyless" });
  expect(store.sensorPrivateKey(s1)).toBe("w4a-key-alpha-0001");
  expect(store.sensorPrivateKey(s2)).toBe("w4a-key-beta-0002");
  expect(store.sensorPrivateKey(s3)).toBe("");
});

test("publicly_readable: true and false are STATED values; an unstated flag reads '' — false !== ''", () => {
  const store = setup();
  const open = store.createSensorAsset({ name: "w4a-Open Gauge", public: true });
  const closed = store.createSensorAsset({ name: "w4a-Closed Gauge", public: false });
  const unstated = store.createSensorAsset({ name: "w4a-Unstated Gauge" });
  expect(store.publiclyReadable(open)).toBe(true);
  expect(store.publiclyReadable(closed)).toBe(false);
  expect(store.publiclyReadable(unstated)).toBe("");
  // The discriminating contrast: a recorded false is not the absent value.
  expect(store.publiclyReadable(closed)).not.toBe("");
  expect(store.publiclyReadable(closed)).not.toBe(store.publiclyReadable(unstated));
});

test("a sensor carrying all three fields reports each independently (the full-kit fixture)", () => {
  const store = setup();
  const s = store.createSensorAsset({
    name: "w4a-Full Kit",
    dataStreams: ["w4a-Moisture", "w4a-Temperature"],
    privateKey: "w4a-key-fullkit-0003",
    public: true,
  });
  expect(store.sensorDataStreams(s)).toEqual(["w4a-Moisture", "w4a-Temperature"]);
  expect(store.sensorPrivateKey(s)).toBe("w4a-key-fullkit-0003");
  expect(store.publiclyReadable(s)).toBe(true);
  expect(store.assetActive(s)).toBe(true);
});

test("a subject that is not a sensor asset is unanswerable, never the empty value", () => {
  const store = setup();
  // A plain asset handle: real, an asset even — but not a sensor.
  const asset = store.createAsset({ entity: "land", name: "Panel Plot" });
  expect(store.sensorDataStreams(asset)).toBeUndefined();
  expect(store.sensorPrivateKey(asset)).toBeUndefined();
  expect(store.publiclyReadable(asset)).toBeUndefined();
  // A log handle.
  const log = store.recordLog({ kind: "activity", name: "Field work", status: "done", assetIds: [asset], quantities: [] });
  expect(store.sensorDataStreams(log)).toBeUndefined();
  expect(store.publiclyReadable(log)).toBeUndefined();
  // A plant_type TERM handle — the neighbor identity's subject kind.
  const term = store.createPlantTypeTerm({ name: "w3a-Tomato" });
  expect(store.sensorPrivateKey(term)).toBeUndefined();
  expect(store.sensorDataStreams(term)).toBeUndefined();
  // A ghost handle never minted as a sensor.
  const ghost = store.mint("asset");
  expect(store.sensorDataStreams(ghost)).toBeUndefined();
  expect(store.sensorPrivateKey(ghost)).toBeUndefined();
  expect(store.publiclyReadable(ghost)).toBeUndefined();
});

test("distinct sensors are distinct handles (no cross-sensor bleed)", () => {
  const store = setup();
  const a = store.createSensorAsset({
    name: "w4a-A",
    dataStreams: ["w4a-Flow-A"],
    privateKey: "w4a-key-a",
    public: true,
  });
  const b = store.createSensorAsset({ name: "w4a-B" });
  expect(a).not.toBe(b);
  // b stated nothing — it must not inherit a's values.
  expect(store.sensorDataStreams(b)).toEqual([]);
  expect(store.sensorPrivateKey(b)).toBe("");
  expect(store.publiclyReadable(b)).toBe("");
  // a is unchanged by b's birth.
  expect(store.sensorDataStreams(a)).toEqual(["w4a-Flow-A"]);
  expect(store.sensorPrivateKey(a)).toBe("w4a-key-a");
  expect(store.publiclyReadable(a)).toBe(true);
});

test("the readback is materialized state, not an input-object echo: a mutated caller array does not change the recorded streams", () => {
  const store = setup();
  const streams = ["w4a-Stream-B", "w4a-Stream-A"];
  const s = store.createSensorAsset({ name: "w4a-Snapshot", dataStreams: streams });
  streams.push("w4a-Intruder");
  streams[0] = "w4a-Mutated";
  expect(store.sensorDataStreams(s)).toEqual(["w4a-Stream-B", "w4a-Stream-A"]);
});

test("a sensor never contributes to the log-family folds (isLog:false — how a fake sensor-as-log would be caught)", () => {
  const store = setup();
  const s = store.createSensorAsset({ name: "w4a-Not-A-Log" });
  // The sensor birth is not a log_recorded: it never inflates logCount, and a
  // log referencing the sensor handle counts as the sensor's log, not vice versa.
  expect(store.logCount(s, "activity")).toBe(0);
  store.recordLog({ kind: "activity", name: "Calibrate", status: "done", assetIds: [s], quantities: [] });
  expect(store.logCount(s, "activity")).toBe(1);
  // And the log's handle is still not a sensor.
  expect(store.allLogs().length).toBe(1);
});
