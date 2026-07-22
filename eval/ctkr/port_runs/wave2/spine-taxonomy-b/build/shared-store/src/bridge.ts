// Shared port-verify bridge runtime for the wave-2 taxonomy-vocabulary family.
// Each feature's build starts this with its OWN vid pinned and its OWN declared
// capability surface; the line protocol (one JSON object per line on stdin/stdout,
// `id` echoed, ok/error/unsupported/unanswerable) is the ctkr.oracle.port_adapter
// contract, identical to the wave-1 shared bridge.
//
// The glossary → store mapping lives here ONCE for the vocabulary surface. Every
// term operation/probe is implicitly scoped to the feature's pinned `vocab`, so a
// port for `season` cannot read or write `product_type` terms. An op outside the
// feature's declared surface is refused with unsupported:true (never guessed).

import { TaxonomyVocabStore, type Handle } from "./store.ts";

export interface BridgeConfig {
  port: string;
  /** the single vocabulary vid this port serves (product_type | season | ...). */
  vocab: string;
  operations: readonly string[];
  probes: readonly string[];
  /** fresh world per fixture — fixtures are independent by construction. */
  makeStore: () => TaxonomyVocabStore;
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
        return {
          vocab: config.vocab,
          operations: [...config.operations],
          probes: [...config.probes],
        };
      case "reset":
        store = config.makeStore();
        return true;
      case "create_term":
        return store.createTerm({
          vocab: config.vocab,
          name: String(req.name ?? ""),
          description:
            req.description === undefined || req.description === null
              ? undefined
              : String(req.description),
          weight: req.weight === undefined ? undefined : Number(req.weight),
        });
      case "rename_term":
        store.renameTerm(req.term as Handle, String(req.name ?? ""));
        return true;
      case "set_term_description":
        store.setTermDescription(
          req.term as Handle,
          req.description === undefined || req.description === null
            ? undefined
            : String(req.description),
        );
        return true;
      case "set_term_weight":
        store.setTermWeight(req.term as Handle, Number(req.weight));
        return true;
      case "delete_term":
        store.deleteTerm(req.term as Handle);
        return true;
      case "term_name": {
        const n = store.termName(req.term as Handle);
        if (n === undefined) {
          return { unanswerable: `no live term under handle ${String(req.term)}` };
        }
        return n;
      }
      case "term_description": {
        const v = store.termView(req.term as Handle);
        if (v === undefined) {
          return { unanswerable: `no live term under handle ${String(req.term)}` };
        }
        return v.description ?? null;
      }
      case "term_weight": {
        const w = store.termWeight(req.term as Handle);
        if (w === undefined) {
          return { unanswerable: `no live term under handle ${String(req.term)}` };
        }
        return w;
      }
      case "term_count":
        return store.termCount(config.vocab);
      case "list_terms":
        // Drupal default term order (weight asc, name asc); ids only.
        return store.listTerms(config.vocab).map((t) => t.termId);
      case "vocabulary_name": {
        const name = store.vocabularyName(config.vocab);
        if (name === undefined) {
          return { unanswerable: `no vocabulary registered under vid ${config.vocab}` };
        }
        return name;
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
