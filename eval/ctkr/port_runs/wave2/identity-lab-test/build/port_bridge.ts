// port-verify bridge for the w2 identity-lab-test build (shared wave-1 bridge
// runtime, imported not vendored).
//
// DECLARED (must match port.manifest.json exactly):
//   operations: record_log, set_log_status, set_effective_time, archive_asset
//   probes:     lab_sample_type, laboratory, lab_test_measurement,
//               lab_processing_date, sample_received_date, soil_texture
//
// All six probes are genuinely served by the shared Wave1LogStore: record_log
// carries the five lab_test bundle fields (lab_test_type, lab, lab_processed_date,
// lab_received_date, soil_texture) onto the log_recorded event's extras and each
// quantity--test's `test_method` onto the quantity, and the probes fold every
// value back off the MATERIALIZED log view — the recorded state, never an echo
// of the fixture input. Four are boundary transcriptions (sample type, two
// dates, soil texture), laboratory is the recorded lab NAME, and
// lab_test_measurement is the ordered test_method names on the first
// quantity--test (the material_type_recorded house form). Nothing is stubbed.
// All six terms are BOUND (pack 066d1701271199f5cec70e0d742000ba), so
// port-verify scores them.

import { runBridge } from "../../../wave1/shared-store/src/bridge.ts";
import { Wave1LogStore } from "../../../wave1/shared-store/src/store.ts";

await runBridge({
  port: "w2-identity-lab-test",
  operations: ["record_log", "set_log_status", "set_effective_time", "archive_asset"],
  probes: [
    "lab_sample_type",
    "laboratory",
    "lab_test_measurement",
    "lab_processing_date",
    "sample_received_date",
    "soil_texture",
  ],
  makeStore: () => new Wave1LogStore({ replicaId: "W2L" }),
});
