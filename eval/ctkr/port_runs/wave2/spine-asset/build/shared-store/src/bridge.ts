// Shared port-verify bridge runtime for the wave-2 asset-bundle spine. Each
// bundle's build starts this with its OWN declared capability surface; the line
// protocol (one JSON object per line on stdin/stdout, `id` echoed,
// ok/error/unsupported/unanswerable) is the ctkr.oracle.port_adapter contract,
// identical to the wave-1 shared bridge.
//
// The glossary → store mapping lives here ONCE for the asset-bundle surface:
//   operations: create_asset, archive_asset
//   probes:     asset_active, asset_bundle, is_location, is_fixed, asset_field
//
// An op outside the bundle's declared surface is refused with unsupported:true
// (never guessed): port-verify only reaches it when manifest and bridge
// disagree, which must surface as a declaration problem.

import type { SpineAssetStore, Handle } from "./store.ts";

export interface BridgeConfig {
  port: string;
  /** the fixed bundle this port creates assets into. */
  bundle: string;
  operations: readonly string[];
  probes: readonly string[];
  makeStore: () => SpineAssetStore;
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
        return { bundle: config.bundle, operations: [...config.operations], probes: [...config.probes] };
      case "reset":
        store = config.makeStore();
        return true;
      case "create_asset":
        return store.createAsset({
          bundle: config.bundle,
          name: String(req.name ?? ""),
          isLocation: req.is_location === undefined ? undefined : Boolean(req.is_location),
          isFixed: req.is_fixed === undefined ? undefined : Boolean(req.is_fixed),
          fields: (req.fields ?? undefined) as
            | Record<string, string | readonly string[] | undefined>
            | undefined,
        });
      case "archive_asset":
        store.archiveAsset(req.asset as Handle);
        return true;
      case "asset_active":
        return store.assetActive(req.asset as Handle);
      case "asset_bundle": {
        const b = store.bundleOf(req.asset as Handle);
        if (b === undefined) {
          return { unanswerable: `no asset created under handle ${String(req.asset)}` };
        }
        return b;
      }
      case "is_location": {
        const v = store.isLocation(req.asset as Handle);
        if (v === undefined) {
          return { unanswerable: `no asset created under handle ${String(req.asset)}` };
        }
        return v;
      }
      case "is_fixed": {
        const v = store.isFixed(req.asset as Handle);
        if (v === undefined) {
          return { unanswerable: `no asset created under handle ${String(req.asset)}` };
        }
        return v;
      }
      case "asset_field": {
        const v = store.fieldOf(req.asset as Handle, String(req.field));
        if (v === undefined) {
          return { unanswerable: `field ${String(req.field)} unset on ${String(req.asset)}` };
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
