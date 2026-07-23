// Shared port-verify bridge runtime for the wave-1 log family. Each feature's
// build starts this with its OWN declared capability surface; the line protocol
// (one JSON object per line on stdin/stdout, `id` echoed, ok/error/unsupported/
// unanswerable) is the ctkr.oracle.port_adapter contract.
//
// The glossary → store mapping lives here ONCE for the log-family surface:
//   operations: record_log, set_log_status, set_effective_time, archive_asset
//   probes:     log_status, log_count, yield_total, quantity_recorded, asset_active
// plus the protocol-level describe / reset / create_asset / close.
//
// An op outside the feature's declared surface is refused with unsupported:true
// (never guessed): port-verify only reaches it when manifest and bridge
// disagree, which must surface as a declaration problem.

import type { Wave1LogStore, Handle, QuantityInput, LogExtras } from "./store.ts";
import type { LifecycleStatus } from "../../../../../../src/kernel/index.ts";

export interface BridgeConfig {
  port: string;
  operations: readonly string[];
  probes: readonly string[];
  /** fresh world per fixture — fixtures are independent by construction. */
  makeStore: () => Wave1LogStore;
}

interface Request {
  id?: number;
  op: string;
  [k: string]: unknown;
}

export async function runBridge(config: BridgeConfig): Promise<void> {
  let store = config.makeStore();
  const declared = new Set([
    "describe",
    "reset",
    "close",
    "create_asset",
    // Backs a plant_type `given` (MetaCoding plant-type). Like create_asset it
    // is an ungated write surface — the adapter calls it directly, never gated
    // on a glossary term — so it is always available, not listed in describe.
    "create_plant_type_term",
    // Backs a sensor `given` (MetaCoding-ej0) — the same ungated write surface
    // family. create_asset with entity "sensor" routes here too, so either
    // adapter dispatch shape lands on the one sensor birth event.
    "create_sensor_asset",
    ...config.operations,
    ...config.probes,
  ]);

  function handle(req: Request): unknown {
    if (!declared.has(req.op)) {
      throw Object.assign(new Error(`this port does not implement ${req.op}`), {
        unsupported: true,
      });
    }
    switch (req.op) {
      case "describe":
        return { operations: [...config.operations], probes: [...config.probes] };
      case "reset":
        store = config.makeStore();
        return true;
      case "create_asset":
        // A sensor `given` may arrive as create_asset with entity "sensor"
        // (the uniform given-record schema, dispatch on entity) — route it to
        // the sensor birth so its bundle fields are recorded and its probes
        // can recognize the subject as a sensor (MetaCoding-ej0).
        if (String(req.entity ?? "") === "sensor") {
          return handle({ ...req, op: "create_sensor_asset" });
        }
        return store.createAsset({
          entity: String(req.entity ?? ""),
          name: String(req.name ?? ""),
          descriptor: String(req.descriptor ?? "") || undefined,
          sex: String(req.sex ?? "") || undefined,
        });
      case "create_sensor_asset":
        // The bundle fields ride only when STATED (MetaCoding-ej0): wire "" is
        // an unstated key, wire [] an unstated stream list, wire null an
        // unstated public flag — but `public: false` is a stated VALUE and
        // rides (the public-false-is-a-value contrast).
        return store.createSensorAsset({
          name: String(req.name ?? ""),
          ...(Array.isArray(req.data_streams) && req.data_streams.length
            ? { dataStreams: (req.data_streams as unknown[]).map(String) }
            : {}),
          ...(req.private_key ? { privateKey: String(req.private_key) } : {}),
          ...(req.public !== undefined && req.public !== null
            ? { public: Boolean(req.public) }
            : {}),
        });
      case "create_plant_type_term":
        // The planning fields ride only when stated (MetaCoding plant-type):
        // maturity_days/harvest_days as integers, crop_family as a family NAME,
        // companions as an ordered list of plant_type NAMES. An unstated field
        // is left off so the term folds back the recorded absent-value contrast.
        return store.createPlantTypeTerm({
          name: String(req.name ?? ""),
          ...(req.maturity_days !== undefined && req.maturity_days !== null
            ? { maturityDays: Number(req.maturity_days) }
            : {}),
          ...(req.harvest_days !== undefined && req.harvest_days !== null
            ? { harvestDays: Number(req.harvest_days) }
            : {}),
          ...(req.crop_family ? { cropFamily: String(req.crop_family) } : {}),
          ...(req.companions
            ? { companions: (req.companions as unknown[]).map(String) }
            : {}),
        });
      case "record_log": {
        // Wire quantities use the oracle DSL's key names; normalize the
        // MetaCoding-xdt/5ln extensions onto the store's fields (`bundle` ->
        // quantityType, `inventory_asset` handle -> inventoryAssetId).
        const quantities = ((req.quantities ?? []) as Record<string, unknown>[])
          .map((q) => {
            const { bundle, inventory_asset, alias: _alias, test_method, ...rest } = q;
            return {
              ...rest,
              ...(bundle ? { quantityType: String(bundle) } : {}),
              ...(inventory_asset
                ? { inventoryAssetId: inventory_asset as Handle }
                : {}),
              // quantity--test `test_method` (MetaCoding-wgy): the wire delivers
              // at most one method name per quantity; wrap it as a one-name list
              // so labTestMeasurement folds the source's ordered-list shape.
              ...(test_method
                ? { testMethods: [String(test_method)] }
                : {}),
            } as QuantityInput;
          });
        // lab_test bundle fields (MetaCoding-wgy) — top-level on the wire only
        // when stated; absent ones leave the log's field empty (the recorded
        // absent-field contrast the pack scores).
        const labExtras: LogExtras = {};
        if (req.lab_test_type) labExtras.labSampleType = String(req.lab_test_type);
        if (req.lab) labExtras.laboratory = String(req.lab);
        if (req.lab_processed_date) labExtras.labProcessedDate = String(req.lab_processed_date);
        if (req.lab_received_date) labExtras.labReceivedDate = String(req.lab_received_date);
        if (req.soil_texture) labExtras.soilTexture = String(req.soil_texture);
        return store.recordLog({
          kind: String(req.kind),
          name: String(req.name ?? ""),
          status: String(req.status ?? "done") as LifecycleStatus,
          assetIds: (req.assets ?? []) as Handle[],
          quantities,
          ...(Object.keys(labExtras).length ? { extras: labExtras } : {}),
          // The cross-family `equipment` base field (MetaCoding-1cv); absent
          // on the wire from pre-1cv oracles, so default [].
          equipmentIds: (req.equipment ?? []) as Handle[],
        });
      }
      case "set_log_status":
        store.setLogStatus(req.log as Handle, String(req.status) as LifecycleStatus);
        return true;
      case "set_effective_time":
        store.restateEffectiveTime(req.log as Handle, Number(req.effective_time));
        return true;
      case "archive_asset":
        store.archiveAsset(req.asset as Handle);
        return true;
      case "log_status": {
        const s = store.logStatus(req.log as Handle);
        if (s === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return s;
      }
      case "log_count":
        return store.logCount(req.asset as Handle, String(req.kind));
      case "yield_total":
        return store.yieldTotal(req.asset as Handle, String(req.measure), String(req.unit));
      case "quantity_recorded":
        return store.quantityRecorded(req.log as Handle, String(req.measure), String(req.unit));
      case "asset_active":
        return store.assetActive(req.asset as Handle);
      case "equipment_used": {
        const used = store.equipmentUsed(req.log as Handle, req.other as Handle);
        if (used === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return used;
      }
      case "material_type_recorded": {
        const names = store.materialTypeRecorded(req.log as Handle);
        if (names === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return names;
      }
      // --- lab_test bundle-field probes (MetaCoding-wgy) --------------------
      // Scalar readbacks answer "" (a value, not unanswerable) when the log
      // recorded no such field; unanswerable only when the log is unknown or
      // deleted. lab_test_measurement answers [] the same way.
      case "lab_sample_type": {
        const v = store.labSampleType(req.log as Handle);
        if (v === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return v;
      }
      case "laboratory": {
        const v = store.laboratory(req.log as Handle);
        if (v === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return v;
      }
      case "lab_processing_date": {
        const v = store.labProcessingDate(req.log as Handle);
        if (v === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return v;
      }
      case "sample_received_date": {
        const v = store.sampleReceivedDate(req.log as Handle);
        if (v === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return v;
      }
      case "soil_texture": {
        const v = store.soilTexture(req.log as Handle);
        if (v === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return v;
      }
      case "lab_test_measurement": {
        const methods = store.labTestMeasurement(req.log as Handle);
        if (methods === undefined) {
          return { unanswerable: `no log recorded under handle ${String(req.log)}` };
        }
        return methods;
      }
      // --- plant_type term planning-field probes (MetaCoding plant-type) -----
      // Each answers off the MATERIALIZED plant_type term (never an echo of the
      // given-step input): the recorded integer or "" for the day counts, the
      // recorded family NAME or "" for crop_family, the ordered companion NAMES
      // or [] for companion_plants. `undefined` — a subject that is not a
      // plant_type term — is unanswerable, never the empty value.
      case "days_to_maturity": {
        const v = store.daysToMaturity(req.subject as Handle);
        if (v === undefined) {
          return { unanswerable: `no plant_type term recorded under handle ${String(req.subject)}` };
        }
        return v;
      }
      case "days_to_harvest": {
        const v = store.daysToHarvest(req.subject as Handle);
        if (v === undefined) {
          return { unanswerable: `no plant_type term recorded under handle ${String(req.subject)}` };
        }
        return v;
      }
      case "crop_family": {
        const v = store.cropFamily(req.subject as Handle);
        if (v === undefined) {
          return { unanswerable: `no plant_type term recorded under handle ${String(req.subject)}` };
        }
        return v;
      }
      case "companion_plants": {
        const names = store.companionPlants(req.subject as Handle);
        if (names === undefined) {
          return { unanswerable: `no plant_type term recorded under handle ${String(req.subject)}` };
        }
        return names;
      }
      // --- structure kind probe (MetaCoding-xq7) -----------------------------
      // Answers the structure's recorded structure_type machine id off the
      // MATERIALIZED asset birth (entity "structure" through the generic
      // create_asset path — structures need no dedicated create op): the
      // recorded descriptor, or the stated fallback "other" when the structure
      // was born without one. A subject that is not a structure asset is
      // UNANSWERABLE, never "other" and never "". Subject arrives as `subject`
      // (`asset` accepted as the asset-family fallback).
      case "structure_kind": {
        const v = store.structureKind((req.subject ?? req.asset) as Handle);
        if (v === undefined) {
          return { unanswerable: `no structure asset recorded under handle ${String(req.subject ?? req.asset)}` };
        }
        return v;
      }
      // --- sensor bundle-field probes (MetaCoding-ej0) -----------------------
      // Each answers off the MATERIALIZED sensor asset. sensor_data_stream
      // answers the ordered recorded stream NAMES ([] when none stated);
      // sensor_private_key the recorded key verbatim ("" when none);
      // publicly_readable the STATED flag (true/false both values) or "" when
      // no flag was stated. `undefined` — a subject that is not a sensor
      // asset — is unanswerable, never the empty value. The subject arrives as
      // `subject` (the newly-bound-term wire form; `asset` accepted as the
      // asset-family fallback).
      case "sensor_data_stream": {
        const names = store.sensorDataStreams((req.subject ?? req.asset) as Handle);
        if (names === undefined) {
          return { unanswerable: `no sensor asset recorded under handle ${String(req.subject ?? req.asset)}` };
        }
        return names;
      }
      case "sensor_private_key": {
        const v = store.sensorPrivateKey((req.subject ?? req.asset) as Handle);
        if (v === undefined) {
          return { unanswerable: `no sensor asset recorded under handle ${String(req.subject ?? req.asset)}` };
        }
        return v;
      }
      case "publicly_readable": {
        const v = store.publiclyReadable((req.subject ?? req.asset) as Handle);
        if (v === undefined) {
          return { unanswerable: `no sensor asset recorded under handle ${String(req.subject ?? req.asset)}` };
        }
        return v;
      }
      case "close":
        return true;
      default:
        throw Object.assign(new Error(`this port does not implement ${req.op}`), {
          unsupported: true,
        });
    }
  }

  const decoder = new TextDecoder();
  let buffer = "";
  for await (const chunk of Bun.stdin.stream()) {
    buffer += decoder.decode(chunk as Uint8Array, { stream: true });
    let nl: number;
    while ((nl = buffer.indexOf("\n")) >= 0) {
      const line = buffer.slice(0, nl).trim();
      buffer = buffer.slice(nl + 1);
      if (!line) continue;
      let req: Request;
      try {
        req = JSON.parse(line) as Request;
      } catch (err) {
        console.log(JSON.stringify({ ok: false, error: `bad request line: ${err}` }));
        continue;
      }
      try {
        const value = handle(req);
        if (req.op === "close") {
          console.log(JSON.stringify({ id: req.id, ok: true, value: true }));
          process.exit(0);
        }
        if (value !== null && typeof value === "object" && "unanswerable" in value) {
          console.log(
            JSON.stringify({
              id: req.id,
              ok: false,
              unanswerable: true,
              error: (value as { unanswerable: string }).unanswerable,
            }),
          );
          continue;
        }
        console.log(JSON.stringify({ id: req.id, ok: true, value }));
      } catch (err) {
        const e = err as Error & { unsupported?: boolean };
        console.log(
          JSON.stringify({
            id: req.id,
            ok: false,
            error: e.message,
            ...(e.unsupported ? { unsupported: true } : {}),
          }),
        );
      }
    }
  }
}
