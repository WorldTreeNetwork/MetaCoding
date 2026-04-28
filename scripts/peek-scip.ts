// Throwaway: dump the high-level shape of a .scip file so we know what
// the SCIP loader has to handle.
import { readFileSync } from "node:fs";
import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";

const path = process.argv[2] ?? "/tmp/metacoding-self.scip";
const bytes = readFileSync(path);
const idx = scip.Index.deserialize(bytes);

console.log("metadata:", JSON.stringify(idx.metadata?.toObject(), null, 2));
console.log("documents:", idx.documents.length);
console.log("external_symbols:", idx.external_symbols.length);

const kindCounts: Record<string, number> = {};
const roleCounts: Record<string, number> = {};
const relCounts = { ref: 0, impl: 0, type: 0, definition: 0 };
let totalSymbols = 0;
let totalOccurrences = 0;

for (const doc of idx.documents) {
  totalSymbols += doc.symbols.length;
  totalOccurrences += doc.occurrences.length;
  for (const s of doc.symbols) {
    const k = scip.SymbolInformation.Kind[s.kind] ?? `?${s.kind}`;
    kindCounts[k] = (kindCounts[k] ?? 0) + 1;
    for (const r of s.relationships) {
      if (r.is_reference) relCounts.ref++;
      if (r.is_implementation) relCounts.impl++;
      if (r.is_type_definition) relCounts.type++;
      if (r.is_definition) relCounts.definition++;
    }
  }
  for (const o of doc.occurrences) {
    const roles: string[] = [];
    if (o.symbol_roles & scip.SymbolRole.Definition) roles.push("Def");
    if (o.symbol_roles & scip.SymbolRole.Import) roles.push("Imp");
    if (o.symbol_roles & scip.SymbolRole.WriteAccess) roles.push("Wr");
    if (o.symbol_roles & scip.SymbolRole.ReadAccess) roles.push("Rd");
    const k = roles.join("|") || "Ref";
    roleCounts[k] = (roleCounts[k] ?? 0) + 1;
  }
}

console.log({ totalSymbols, totalOccurrences });
console.log("kinds:", kindCounts);
console.log("roles:", roleCounts);
console.log("relationships:", relCounts);

// Sample a few symbol strings.
console.log("\nsample symbols (first 6):");
for (const doc of idx.documents.slice(0, 1)) {
  for (const s of doc.symbols.slice(0, 6)) {
    console.log(" ", s.symbol.slice(0, 110), `(${scip.SymbolInformation.Kind[s.kind] ?? s.kind})`);
    for (const r of s.relationships.slice(0, 2)) {
      const tags: string[] = [];
      if (r.is_reference) tags.push("ref");
      if (r.is_implementation) tags.push("impl");
      if (r.is_type_definition) tags.push("type");
      console.log("    └", tags.join(","), "->", r.symbol.slice(0, 80));
    }
  }
}
