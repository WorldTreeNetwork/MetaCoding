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
        return store.createAsset({
          entity: String(req.entity ?? ""),
          name: String(req.name ?? ""),
          descriptor: String(req.descriptor ?? "") || undefined,
          sex: String(req.sex ?? "") || undefined,
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
