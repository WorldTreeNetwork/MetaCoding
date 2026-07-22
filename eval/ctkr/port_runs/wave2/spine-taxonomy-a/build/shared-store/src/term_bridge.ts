// Shared port-verify bridge runtime for the wave-2 spine-taxonomy-a term family.
// Each vocabulary's build starts this with its OWN declared capability surface,
// bound to a fixed vocabulary. The line protocol (one JSON object per line on
// stdin/stdout, `id` echoed, ok/error/unsupported/unanswerable) is the
// ctkr.oracle.port_adapter contract, identical in shape to the wave-1 bridge.
//
// The glossary → store mapping for the taxonomy-term surface lives here ONCE:
//   operations: create_term, update_term, delete_term
//   probes:     term_name, term_parent, term_status, term_weight,
//               term_vocabulary, term_depth, term_children, list_terms
// plus the protocol-level describe / reset / close.
//
// An op outside the feature's declared surface is refused with unsupported:true
// (never guessed): port-verify only reaches it when manifest and bridge disagree,
// which must surface as a declaration problem.

import { TaxonomyTermStore, type Handle, type Vocabulary, type TermPatch } from "./term_store.ts";

export interface BridgeConfig {
  port: string;
  vocabulary: Vocabulary;
  operations: readonly string[];
  probes: readonly string[];
  /** fresh world per fixture — fixtures are independent by construction. */
  makeStore: () => TaxonomyTermStore;
}

interface Request {
  id?: number;
  op: string;
  [k: string]: unknown;
}

/** Build a TermPatch from request fields, including only the keys present. */
function patchFrom(req: Request): TermPatch {
  const patch: TermPatch = {};
  if ("name" in req) patch.name = String(req.name);
  if ("parent" in req) patch.parent = (req.parent ?? null) as Handle | null;
  if ("description" in req) patch.description = String(req.description);
  if ("weight" in req) patch.weight = Number(req.weight);
  if ("status" in req) patch.status = Boolean(req.status);
  return patch;
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
          vocabulary: config.vocabulary,
          operations: [...config.operations],
          probes: [...config.probes],
        };
      case "reset":
        store = config.makeStore();
        return true;
      case "create_term":
        return store.createTerm(config.vocabulary, {
          name: String(req.name ?? ""),
          parent: (req.parent ?? null) as Handle | null,
          description: "description" in req ? String(req.description) : undefined,
          weight: "weight" in req ? Number(req.weight) : undefined,
          status: "status" in req ? Boolean(req.status) : undefined,
        });
      case "update_term":
        store.updateTerm(req.term as Handle, patchFrom(req));
        return true;
      case "delete_term":
        store.deleteTerm(req.term as Handle);
        return true;
      case "term_name": {
        const v = store.termView(req.term as Handle);
        return v ? v.name : { unanswerable: `no live term under handle ${String(req.term)}` };
      }
      case "term_parent": {
        const v = store.termView(req.term as Handle);
        return v ? v.parent : { unanswerable: `no live term under handle ${String(req.term)}` };
      }
      case "term_status": {
        const v = store.termView(req.term as Handle);
        return v ? v.status : { unanswerable: `no live term under handle ${String(req.term)}` };
      }
      case "term_weight": {
        const v = store.termView(req.term as Handle);
        return v ? v.weight : { unanswerable: `no live term under handle ${String(req.term)}` };
      }
      case "term_vocabulary": {
        const v = store.termView(req.term as Handle);
        return v ? v.vocabulary : { unanswerable: `no live term under handle ${String(req.term)}` };
      }
      case "term_depth": {
        const v = store.termView(req.term as Handle);
        return v ? store.depthOf(req.term as Handle) : { unanswerable: `no live term under handle ${String(req.term)}` };
      }
      case "term_children":
        return store.childrenOf(req.term as Handle).map((v) => v.termId);
      case "list_terms":
        return store
          .termsInVocabulary(config.vocabulary, { activeOnly: Boolean(req.active_only) })
          .map((v) => v.termId);
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
