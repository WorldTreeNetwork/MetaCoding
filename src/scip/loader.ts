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
  repo: string;
  /** Maps the SCIP scheme/file-extension to one of our `language` codes. */
  language?: "ts" | "py";
  /** git rev-parse HEAD at index time; null when not in a git repo. */
  repo_commit_sha?: string | null;
  /** ISO-8601 timestamp (UTC) at the moment the index was started. */
  indexed_at?: string | null;
  /** When true, fold repo_commit_sha into Symbol.id for locally-defined
   *  symbols. External SCIP refs (externalQn at line 139) are NEVER sha-scoped
   *  — they're invariant across branches. bead MetaCoding-izn. */
  perCommitIdentity?: boolean;
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
      const lang = opts.language ?? guessLanguageFromQn(qn);
      const idSha = opts.perCommitIdentity ? opts.repo_commit_sha ?? undefined : undefined;
      const id = symbolId(lang, opts.repo, qn, idSha);

      const info = infoBySymbol.get(occ.symbol);
      const sym: Symbol = {
        id,
        kind: kindOf(parsed, info?.kind),
        language: lang,
        repo: opts.repo,
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
        repo_commit_sha: opts.repo_commit_sha ?? null,
        indexed_at: opts.indexed_at ?? null,
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

  // Build a kind-lookup map so pass-2b can check field/type kinds without
  // re-parsing the SCIP symbol string.  Keyed on the SCIP symbol string.
  const kindByScip = new Map<string, string>();
  for (const [scipSym, def] of defByScip) {
    // We stored ourId; recover the kind from the DefRecord via defByScip.
    // Re-parse the symbol to get the kind — cheaper than a round-trip to DB.
    const parsed = parseScipSymbol(scipSym);
    if (parsed) kindByScip.set(scipSym, kindOf(parsed));
  }

  // 2a — relationships (IMPLEMENTS, TYPE_OF, RETURNS_TYPE) from SymbolInformation.
  //
  // RETURNS_TYPE: when `is_type_definition` is set AND the *source* symbol is a
  // function or method, SCIP is saying "this symbol is defined as a type — its
  // return type is <rel.symbol>".  We emit RETURNS_TYPE in that case rather than
  // TYPE_OF to keep the two edge kinds semantically separate.
  for (const doc of idx.documents) {
    for (const info of doc.symbols) {
      const srcDef = defByScip.get(info.symbol);
      if (!srcDef) continue;
      const srcKind = kindByScip.get(info.symbol) ?? "";
      for (const rel of info.relationships) {
        const tgtDef = defByScip.get(rel.symbol);
        const dstId = tgtDef?.ourId
          ?? symbolId(opts.language ?? "ts", opts.repo, externalQn(rel.symbol));
        if (rel.is_implementation) enqueue("IMPLEMENTS", srcDef.ourId, dstId);
        if (rel.is_type_definition) {
          if (srcKind === "function" || srcKind === "method") {
            // Source is a callable — treat the related type as its return type.
            enqueue("RETURNS_TYPE", srcDef.ourId, dstId);
          } else {
            enqueue("TYPE_OF", srcDef.ourId, dstId);
          }
        }
      }
    }
  }

  // 2b — references: each non-Definition Occurrence becomes one or more edges
  // from its innermost-enclosing definition in the same document to the target.
  //
  // Edge selection:
  //   WriteAccess + target is field  → WRITES_FIELD
  //   ReadAccess  + target is field  → READS_FIELD
  //   No access flags + target is constructor (type suffix) → CONSTRUCTS
  //   Otherwise                      → REFERENCES
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

      const targetKind = kindByScip.get(occ.symbol) ?? "";
      const isWrite = !!(occ.symbol_roles & scip.SymbolRole.WriteAccess);
      const isRead  = !!(occ.symbol_roles & scip.SymbolRole.ReadAccess);

      if (targetKind === "field" && isWrite) {
        enqueue("WRITES_FIELD", caller.ourId, targetDef.ourId);
      } else if (targetKind === "field" && isRead) {
        enqueue("READS_FIELD", caller.ourId, targetDef.ourId);
      } else if (isConstructorSymbol(occ.symbol) && !isRead && !isWrite) {
        enqueue("CONSTRUCTS", caller.ourId, targetDef.ourId);
      } else {
        enqueue("REFERENCES", caller.ourId, targetDef.ourId);
      }
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

function guessLanguageFromQn(qn: string): "ts" | "py" {
  return /\.(py|pyi)(::|$)/.test(qn) ? "py" : "ts";
}

// Detect whether a SCIP symbol string refers to a constructor.
// In scip-typescript, constructors appear as method descriptors whose
// disambiguator is "+" (e.g., `... ClassName#`constructor`(+).`).
// In scip-python, `__init__` methods serve as constructors.
// We also treat an occurrence whose *last meaningful descriptor* is a
// `type` suffix (class definition symbol) as a CONSTRUCTS target — this
// handles `new Foo()` resolved to the class symbol when no explicit
// constructor is emitted.
function isConstructorSymbol(scipSymbol: string): boolean {
  // Fast path: check common constructor patterns before full parse.
  if (
    /`constructor`\(\+\)\./.test(scipSymbol) ||  // scip-typescript constructor
    /__init__\(\)\./.test(scipSymbol)             // scip-python __init__
  ) {
    return true;
  }
  // Structural check: if the last meaningful descriptor is a `type` suffix
  // (class), a reference to it without read/write flags is construction.
  const parsed = parseScipSymbol(scipSymbol);
  if (!parsed || parsed.isLocal) return false;
  const meaningful = parsed.descriptors.filter(
    (d) => d.suffix !== "type_parameter" && d.suffix !== "parameter",
  );
  const last = meaningful[meaningful.length - 1];
  return last?.suffix === "type";
}
