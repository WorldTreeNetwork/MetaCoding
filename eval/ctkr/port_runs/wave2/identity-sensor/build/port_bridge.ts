// port-verify bridge for the w2 identity-sensor build (shared wave-1 store
// runtime, imported not vendored).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: (none — a sensor carries no glossary write action; the `given`
//               write surface create_sensor_asset is ungated, like
//               create_asset / create_plant_type_term, so it is not a
//               declared operation. archive never appears in this pack's
//               flows, so archive_asset is not declared either.)
//   probes:     asset_active, sensor_data_stream, sensor_private_key,
//               publicly_readable
//
// A sensor IS an ASSET (farm_sensor asset--sensor) — asset_active answers on
// its handle through the shared asset lifecycle fold — but it births through
// its OWN event (sensor_asset_created) carrying the three bundle fields, so a
// sensor probe can refuse a non-sensor subject (unanswerable, never an empty
// value). sensor_data_stream folds back the ORDERED recorded stream NAMES
// (recorded order, not name order; [] when none). sensor_private_key folds the
// recorded key verbatim ("" when none). publicly_readable folds the STATED
// flag — false is a value distinct from unstated, which reads "". Nothing is
// stubbed. All values fold off MATERIALIZED store state, never an input echo.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-identity-sensor",
  operations: [],
  probes: [
    "asset_active",
    "sensor_data_stream",
    "sensor_private_key",
    "publicly_readable",
  ],
  makeStore: () => new Wave1LogStore({ replicaId: "W2S" }),
});
