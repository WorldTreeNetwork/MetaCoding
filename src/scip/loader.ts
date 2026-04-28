// Load a .scip file into a Store.
//
// Strategy:
//   Pass 1 — for every Definition occurrence in every Document, MERGE a
//   Symbol node (source='scip') keyed on our hash of the qualified_name.
//   The qualified_name shape matches the Tree-sitter extractor (file::Class::method)
//   so SCIP wins the lane-reconciliation: same id, same MERGE.
//
//   Pass 2 — for every reference Occurrence, find the *innermost enclosing
//   definition* in the same Document via enclosing_range, and emit a single
//   REFERENCES edge per (caller, callee) pair (deduped in-memory).
//
//   Relationships from SymbolInformation:
//     is_implementation -> IMPLEMENTS edge
//     is_type_definition -> TYPE_OF edge
//   subclass-of (extends) is not a first-class relationship in scip-typescript;
//   when we want it, we'll need a heuristic (LSP overlay) in a later phase.

import { readFileSync } from "node:fs";

import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";

import type { Store } from "../store";
import type { Edge, EdgeKind, Symbol } from "../store/types";
import { symbolId } from "../extractor/identity";
import {
  parseScipSymbol,
  qualifiedNameOf,
  shortNameOf,
  kindOf,
  filePathOf,
} from "./symbol";

export interface LoadScipOpts {
  branch: string;
}

export interface LoadScipStats {
  documents: number;
  symbolsUpserted: number;
  edgesAdded: number;
  externalRefsSkipped: number;
  durationMs: number;
}

interface DefRecord {
  ourId: string;
  scipSymbol: string;
  docPath: string;
  enclosingRange: number[];   // [startLine, startCol, endLine, endCol] (or [startLine, startCol, endLineSameAsStart, endCol] when 3-tuple)
}

export async function loadScip(
  store: Store,
  scipPath: string,
  opts: LoadScipOpts,
): Promise<LoadScipStats> {
  const t0 = performance.now();
  const bytes = readFileSync(scipPath);
  const idx = scip.Index.deserialize(bytes);

  // ----- Pass 1: upsert all defined Symbols -----
  const defByScip = new Map<string, DefRecord>();
  let symbolsUpserted = 0;

  // SymbolInformation map per document (for kind hint and relationships).
  for (const doc of idx.documents) {
    const infoBySymbol = new Map<string, scip.SymbolInformation>();
    for (const info of doc.symbols) infoBySymbol.set(info.symbol, info);

    for (const occ of doc.occurrences) {
      if (!(occ.symbol_roles & scip.SymbolRole.Definition)) continue;
      const parsed = parseScipSymbol(occ.symbol);
      if (!parsed || parsed.isLocal) continue;
      const qn = qualifiedNameOf(parsed);
      const id = symbolId("ts", qn);

      const info = infoBySymbol.get(occ.symbol);
      const sym: Symbol = {
        id,
        kind: kindOf(parsed, info?.kind),
        language: "ts",
        qualified_name: qn,
        short_name: shortNameOf(parsed),
        file: doc.relative_path,
        line: occ.range[0] ?? 0,
        col: occ.range[1] ?? 0,
        end_line: occ.range[2] ?? occ.range[0] ?? 0,
        end_col: occ.range[3] ?? occ.range[1] ?? 0,
        signature: null,
        visibility: null,
        is_abstract: false,
        is_static: false,
        ast_hash: null,
        branch: opts.branch,
        source: "scip",
      };
      await store.upsertSymbol(sym);
      symbolsUpserted++;

      defByScip.set(occ.symbol, {
        ourId: id,
        scipSymbol: occ.symbol,
        docPath: doc.relative_path,
        enclosingRange:
          occ.enclosing_range && occ.enclosing_range.length > 0
            ? occ.enclosing_range
            : occ.range,
      });
    }
  }

  // ----- Pass 2: edges -----
  const edgePairs = new Set<string>();   // de-dup (kind|src|dst)
  const edgesQueued: Edge[] = [];
  let externalRefsSkipped = 0;

  const enqueue = (kind: EdgeKind, srcId: string, dstId: string): void => {
    if (srcId === dstId) return;
    const k = `${kind}|${srcId}|${dstId}`;
    if (edgePairs.has(k)) return;
    edgePairs.add(k);
    edgesQueued.push({ kind, src_id: srcId, dst_id: dstId });
  };

  // 2a — relationships (IMPLEMENTS, TYPE_OF) from SymbolInformation.
  for (const doc of idx.documents) {
    for (const info of doc.symbols) {
      const srcDef = defByScip.get(info.symbol);
      if (!srcDef) continue;
      for (const rel of info.relationships) {
        const tgtDef = defByScip.get(rel.symbol);
        const dstId = tgtDef?.ourId ?? symbolId("ts", externalQn(rel.symbol));
        if (rel.is_implementation) enqueue("IMPLEMENTS", srcDef.ourId, dstId);
        if (rel.is_type_definition) enqueue("TYPE_OF", srcDef.ourId, dstId);
      }
    }
  }

  // 2b — references: each non-Definition Occurrence becomes a REFERENCES edge
  // from its innermost-enclosing definition in the same document to the target.
  for (const doc of idx.documents) {
    // Pre-compute defs in this document, sorted with the most-specific
    // (smallest enclosing range) first, so the first containment hit wins.
    const docDefs: { sym: string; range: number[]; ourId: string }[] = [];
    for (const occ of doc.occurrences) {
      if (!(occ.symbol_roles & scip.SymbolRole.Definition)) continue;
      const def = defByScip.get(occ.symbol);
      if (!def) continue;
      docDefs.push({
        sym: occ.symbol,
        range: occ.enclosing_range && occ.enclosing_range.length > 0
          ? occ.enclosing_range
          : occ.range,
        ourId: def.ourId,
      });
    }
    docDefs.sort((a, b) => rangeArea(a.range) - rangeArea(b.range));

    for (const occ of doc.occurrences) {
      if (occ.symbol_roles & scip.SymbolRole.Definition) continue;
      const targetDef = defByScip.get(occ.symbol);
      if (!targetDef) {
        externalRefsSkipped++;
        continue;
      }
      const caller = docDefs.find((d) => rangeContains(d.range, occ.range));
      if (!caller) continue;
      enqueue("REFERENCES", caller.ourId, targetDef.ourId);
    }
  }

  // Flush edges to the Store.
  for (const e of edgesQueued) await store.addEdge(e);

  return {
    documents: idx.documents.length,
    symbolsUpserted,
    edgesAdded: edgesQueued.length,
    externalRefsSkipped,
    durationMs: performance.now() - t0,
  };
}

// SCIP ranges are [startLine, startCol, endCol] (3-tuple, same line)
// or [startLine, startCol, endLine, endCol] (4-tuple).
function expand(range: number[]): { sl: number; sc: number; el: number; ec: number } {
  if (range.length === 3) return { sl: range[0]!, sc: range[1]!, el: range[0]!, ec: range[2]! };
  return { sl: range[0]!, sc: range[1]!, el: range[2]!, ec: range[3]! };
}

function rangeArea(range: number[]): number {
  const r = expand(range);
  // Approximate "size" by line span; finer-grained ordering not needed.
  return (r.el - r.sl) * 1_000_000 + (r.ec - r.sc);
}

function rangeContains(outer: number[], inner: number[]): boolean {
  const o = expand(outer);
  const i = expand(inner);
  if (i.sl < o.sl) return false;
  if (i.sl === o.sl && i.sc < o.sc) return false;
  if (i.el > o.el) return false;
  if (i.el === o.el && i.ec > o.ec) return false;
  return true;
}

function externalQn(scipSymbol: string): string {
  // For symbols we don't have a definition for (cross-package references),
  // hash the SCIP symbol string itself so the edge has a stable target id.
  // The target node may not exist in our graph; that's expected — the agent
  // can still see "this symbol references something external".
  return `external::${scipSymbol}`;
}
