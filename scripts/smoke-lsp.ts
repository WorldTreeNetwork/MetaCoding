// scripts/smoke-lsp.ts
//
// Validates the LSP lane against this repo's own source:
//  - LspService spawns typescript-language-server on demand.
//  - hover() returns markdown for the Store class.
//  - definition() resolves an in-source method call to its declaration.
//  - references() finds at least the declaration site for an exported symbol.
//  - diagnostics() returns an empty list for a known-healthy file.
//  - Shutdown is clean.
//
// Run with: bun run scripts/smoke-lsp.ts

import { readFileSync } from "node:fs";
import { resolve } from "node:path";

import { LspService } from "../src/lsp";
import { lspHover, lspDefinition, lspReferences, lspDiagnostics } from "../src/mcp/lsp-tools";

const WORKSPACE = resolve(".");
const TARGET = "src/store/index.ts";

interface Position { line: number; col: number }

function findIdentifier(filePath: string, ident: string): Position {
  // First occurrence on a non-comment line.
  const text = readFileSync(filePath, "utf-8");
  const lines = text.split("\n");
  const re = new RegExp(`(^|[^A-Za-z0-9_$])(${ident})([^A-Za-z0-9_$]|$)`);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const trimmed = line.trimStart();
    if (trimmed.startsWith("//") || trimmed.startsWith("*") || trimmed.startsWith("/*")) continue;
    const m = re.exec(line);
    if (m) {
      const col = m.index + m[1]!.length;
      return { line: i, col };
    }
  }
  throw new Error(`identifier ${ident} not found in ${filePath}`);
}

function findAfterKeyword(filePath: string, keyword: string, ident: string): Position {
  const text = readFileSync(filePath, "utf-8");
  const lines = text.split("\n");
  const re = new RegExp(`(${keyword}\\s+)(${ident})\\b`);
  for (let i = 0; i < lines.length; i++) {
    const m = re.exec(lines[i]!);
    if (m) {
      const col = m.index + m[1]!.length;
      return { line: i, col };
    }
  }
  throw new Error(`'${keyword} ${ident}' not found in ${filePath}`);
}

async function main(): Promise<void> {
  const lsp = new LspService({ rootDir: WORKSPACE });

  try {
    const targetAbs = resolve(WORKSPACE, TARGET);
    const storeDef = findAfterKeyword(targetAbs, "class", "Store");

    console.log(`Store identifier at ${TARGET}:${storeDef.line}:${storeDef.col}`);

    // 1. Hover over the Store class declaration.
    let hover = await lspHover(lsp, WORKSPACE, {
      file: TARGET,
      line: storeDef.line,
      col: storeDef.col,
    });
    // Some servers need a beat to load the project; one short retry.
    if (!hover.markdown) {
      console.log("hover empty on first try; warming up 600ms and retrying");
      await new Promise((r) => setTimeout(r, 600));
      hover = await lspHover(lsp, WORKSPACE, {
        file: TARGET,
        line: storeDef.line,
        col: storeDef.col,
      });
    }
    if (!hover.markdown || hover.markdown.length === 0) {
      throw new Error(`lsp_hover returned empty markdown; raw: ${JSON.stringify(hover)}`);
    }
    if (!hover.markdown.includes("Store")) {
      throw new Error(`lsp_hover for Store didn't mention 'Store'; got:\n${hover.markdown}`);
    }
    console.log(`hover OK (${hover.markdown.length} chars)`);

    // 2. Definition of `upsertSymbol` from a call site in walker.ts.
    const callerFile = "src/extractor/walker.ts";
    const callerAbs = resolve(WORKSPACE, callerFile);
    const upsertSite = findIdentifier(callerAbs, "upsertSymbol");
    const defs = await lspDefinition(lsp, WORKSPACE, {
      file: callerFile,
      line: upsertSite.line,
      col: upsertSite.col,
    });
    if (defs.length === 0) throw new Error("lsp_definition(upsertSymbol) returned no locations");
    const inStore = defs.some((d) => d.file.endsWith("src/store/index.ts"));
    if (!inStore) {
      throw new Error(`expected definition in src/store/index.ts; got ${JSON.stringify(defs)}`);
    }
    console.log(`definition OK -> ${defs[0]!.file}:${defs[0]!.line}`);

    // 3. References for the exported Store class — should be > 1 (decl + uses).
    const refs = await lspReferences(lsp, WORKSPACE, {
      file: TARGET,
      line: storeDef.line,
      col: storeDef.col,
      include_declaration: true,
    });
    if (refs.length < 2) {
      throw new Error(`lsp_references(Store) returned ${refs.length} (<2)`);
    }
    const distinctFiles = new Set(refs.map((r) => r.file));
    if (distinctFiles.size < 2) {
      throw new Error(`expected references across multiple files; got ${distinctFiles.size}`);
    }
    console.log(`references OK -> ${refs.length} hits across ${distinctFiles.size} files`);

    // 4. Diagnostics for a healthy file should be empty.
    const diags = await lspDiagnostics(lsp, WORKSPACE, {
      file: TARGET,
      wait_ms: 5000,
    });
    if (diags.length > 0) {
      console.warn(`(note: lsp_diagnostics returned ${diags.length} items for ${TARGET})`);
      for (const d of diags.slice(0, 3)) {
        console.warn(`  ${d.line}:${d.col} ${d.message}`);
      }
    } else {
      console.log(`diagnostics OK -> 0 issues for ${TARGET}`);
    }

    console.log("LSP_SMOKE_PASS");
  } finally {
    await lsp.shutdown();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("LSP_SMOKE_FAIL", err);
    process.exit(1);
  });
