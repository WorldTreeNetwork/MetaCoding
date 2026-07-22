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

import type { Wave1LogStore, Handle, QuantityInput } from "./store.ts";
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
        const quantities = (req.quantities ?? []) as QuantityInput[];
        return store.recordLog({
          kind: String(req.kind),
          name: String(req.name ?? ""),
          status: String(req.status ?? "done") as LifecycleStatus,
          assetIds: (req.assets ?? []) as Handle[],
          quantities,
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
