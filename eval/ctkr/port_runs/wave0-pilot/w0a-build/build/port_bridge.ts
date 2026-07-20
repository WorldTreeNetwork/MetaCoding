/**
 * port-verify bridge for the w0a Asset Inventory build.
 *
 * `ctkr port-verify` speaks one JSON object per line on stdin and expects one
 * per line on stdout. This file is the ONLY place that knows how the glossary
 * vocabulary of a semantic fixture reaches this port's surface — it is part of
 * the port, not part of the verifier, so a mapping mistake here is a defect of
 * the build's claim about itself and shows up as a declaration problem rather
 * than being buried in a throwaway judging script.
 *
 * WHAT THIS PORT DECLARES (see port.manifest.json — the two must agree exactly
 * or port-verify refuses to run):
 *   operations : record_inventory_adjustment
 *   probes     : stock_on_hand, stock_pair_count
 *
 * WHAT IT DELIBERATELY DOES NOT DECLARE, and why every such assertion must be
 * reported as an unanswerable GAP rather than scored:
 *   - `adjustment_count` — the build exposes no count of the adjustments behind
 *     a balance. `getInventory` returns folded values only.
 *   - `log_status`       — no read of an individual adjustment's lifecycle.
 *   - `set_log_status`   — no confirm/unconfirm verb; appended status is final.
 *   - `set_effective_time` — no restatement verb.
 * Answering any of these here would mean inventing surface the build does not
 * have, which is precisely the failure mode that inflated "24/30".
 *
 * ONE MAPPING JUDGEMENT, stated rather than hidden: `stock_on_hand` for a
 * (measure, unit) pair the projection does not report is answered 0. The
 * projection returns a row only for pairs that have adjustments; "this asset
 * holds nothing of that kind" is what absence means in this build. That reading
 * is the bridge's, and it is written down here so it can be contested.
 *
 * Run: bun run port_bridge.ts   (started automatically by ctkr port-verify)
 */

import {
  makeAssetInventoryAdapter,
  type AdjustmentKind,
  type AssetHandle,
  type AssetInventoryAdapter,
} from "./src/inventory.ts";
import type { LifecycleStatus } from "../../../../../../src/kernel/index.ts";

const OPERATIONS = ["record_inventory_adjustment"] as const;
const PROBES = ["stock_on_hand", "stock_pair_count"] as const;

interface Request {
  id?: number;
  op: string;
  [k: string]: unknown;
}

interface Quantity {
  measure: string;
  value: number;
  unit: string;
  label?: string;
}

/** Fresh world per fixture — fixtures are independent by construction. */
let port: AssetInventoryAdapter = makeAssetInventoryAdapter();
const assets = new Map<string, AssetHandle>();
let assetSeq = 0;

function reset(): void {
  port = makeAssetInventoryAdapter();
  assets.clear();
  assetSeq = 0;
}

function assetOf(handle: unknown): AssetHandle {
  const found = assets.get(String(handle));
  if (!found) throw new Error(`unknown asset handle ${String(handle)}`);
  return found;
}

/** The read instant. Fixtures date events relative to the run, so "now" is what
 *  makes a future-dated adjustment inert — the same reading the source has. */
const readAsOf = (): number => Date.now();

function handle(req: Request): unknown {
  switch (req.op) {
    case "describe":
      return { port: "w0a-asset-inventory", operations: OPERATIONS, probes: PROBES };

    case "reset":
      reset();
      return true;

    case "create_asset": {
      // Every `given` needs an entity. This build's entities are bare kernel
      // ids: it models no entity kinds, names or traits, and the fixture pack's
      // inventory scenarios assert nothing about them.
      const h = port.createAsset();
      const key = `A${++assetSeq}`;
      assets.set(key, h);
      return key;
    }

    case "record_inventory_adjustment": {
      const quantities = (req.quantities ?? []) as Quantity[];
      const targets = (req.assets ?? []) as string[];
      const status = String(req.status || "done") as LifecycleStatus;
      const kind = String(req.adjustment) as AdjustmentKind;
      const occurredAt =
        req.effective_time === null || req.effective_time === undefined
          ? Date.now()
          : Number(req.effective_time);
      let last = "";
      for (const target of targets) {
        for (const q of quantities) {
          last = port.appendInventoryAdjustment(assetOf(target), {
            logStatus: status,
            occurredAt,
            measure: q.measure,
            units: q.unit,
            kind,
            value: q.value,
          });
        }
      }
      return last;
    }

    case "stock_on_hand": {
      const rows = port.getInventory(assetOf(req.asset), readAsOf());
      const row = rows.find(
        (r) => r.measure === String(req.measure) && r.units === String(req.unit),
      );
      // The port models "never adjusted" as the ABSENCE of a row, while farmOS
      // answers a numeric 0.0. Returning 0 here would fabricate a value the port
      // does not hold and score a false PASS on exactly the representational
      // divergence this pack exists to expose. Declare the per-call gap instead:
      // the verifier records it as unanswerable, never as agreement.
      if (!row) {
        return {
          unanswerable:
            "the port reports no holding row for this (measure, unit) pair; " +
            "it does not model an unadjusted holding as a zero quantity",
        };
      }
      return row.value;
    }

    case "stock_pair_count":
      return port.getInventory(assetOf(req.asset), readAsOf()).length;

    case "close":
      return true;

    default:
      // Anything not declared above must be refused loudly. port-verify never
      // asks for an undeclared capability, so reaching here means the manifest
      // and this file disagree — a declaration problem, never a silent zero.
      throw Object.assign(
        new Error(`this port does not implement ${req.op}`),
        { unsupported: true },
      );
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
      // A handler may decline THIS input while still implementing the probe in
      // general (see stock_on_hand). That is a declared per-call gap, never a
      // value — the alternative is fabricating one.
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
          error: e.message ?? String(err),
          ...(e.unsupported ? { unsupported: true } : {}),
        }),
      );
    }
  }
}
