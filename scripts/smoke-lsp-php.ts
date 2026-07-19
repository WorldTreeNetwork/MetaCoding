// scripts/smoke-lsp-php.ts
//
// Validates the PHP LSP lane against a small on-disk fixture:
//  - LspService spawns intelephense on demand (bunx/node_modules resolution).
//  - hover() returns markdown for the Greeter class.
//  - definition() resolves a call site to the greet() method declaration.
//  - references() finds at least the declaration site for greet().
//  - Shutdown is clean.
//
// Run with: bun run scripts/smoke-lsp-php.ts

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { LspService } from "../src/lsp";
import { lspHover, lspDefinition, lspReferences } from "../src/mcp/lsp-tools";

const FIX = resolve("./tmp-php-lsp-fixture");

function cleanup(): void {
  if (existsSync(FIX)) rmSync(FIX, { recursive: true, force: true });
}

const GREETER_PHP = `<?php
namespace App;

class Greeter {
    public function greet(string $name): string {
        return "Hello, " . $name;
    }
}
`;

const MAIN_PHP = `<?php
namespace App;

require_once __DIR__ . '/Greeter.php';

$greeter = new Greeter();
echo $greeter->greet("World");
`;

interface Position { line: number; col: number }

function findIdentifier(filePath: string, ident: string): Position {
  const text = readFileSync(filePath, "utf-8");
  const lines = text.split("\n");
  const re = new RegExp(`(^|[^A-Za-z0-9_$])(${ident})([^A-Za-z0-9_$]|$)`);
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    const m = re.exec(line);
    if (m) {
      const col = m.index + m[1]!.length;
      return { line: i, col };
    }
  }
  throw new Error(`identifier ${ident} not found in ${filePath}`);
}

async function main(): Promise<void> {
  cleanup();
  mkdirSync(FIX, { recursive: true });
  writeFileSync(join(FIX, "Greeter.php"), GREETER_PHP, "utf-8");
  writeFileSync(join(FIX, "main.php"), MAIN_PHP, "utf-8");

  const lsp = new LspService({ rootDir: FIX });

  try {
    const classDecl = findIdentifier(join(FIX, "Greeter.php"), "Greeter");
    console.log(`Greeter identifier at Greeter.php:${classDecl.line}:${classDecl.col}`);

    // 1. Hover over the Greeter class declaration.
    let hover = await lspHover(lsp, FIX, {
      file: "Greeter.php",
      line: classDecl.line,
      col: classDecl.col,
    });
    if (!hover.markdown) {
      console.log("hover empty on first try; warming up 1500ms and retrying");
      await new Promise((r) => setTimeout(r, 1500));
      hover = await lspHover(lsp, FIX, {
        file: "Greeter.php",
        line: classDecl.line,
        col: classDecl.col,
      });
    }
    if (!hover.markdown || hover.markdown.length === 0) {
      throw new Error(`lsp_hover returned empty markdown; raw: ${JSON.stringify(hover)}`);
    }
    if (!hover.markdown.includes("Greeter")) {
      throw new Error(`lsp_hover for Greeter didn't mention 'Greeter'; got:\n${hover.markdown}`);
    }
    console.log(`hover OK (${hover.markdown.length} chars)`);

    // 2. Definition of `greet` from the call site in main.php.
    const callSite = findIdentifier(join(FIX, "main.php"), "greet");
    const defs = await lspDefinition(lsp, FIX, {
      file: "main.php",
      line: callSite.line,
      col: callSite.col,
    });
    if (defs.length === 0) throw new Error("lsp_definition(greet) returned no locations");
    const inGreeter = defs.some((d) => d.file.endsWith("Greeter.php"));
    if (!inGreeter) {
      throw new Error(`expected definition in Greeter.php; got ${JSON.stringify(defs)}`);
    }
    console.log(`definition OK -> ${defs[0]!.file}:${defs[0]!.line}`);

    // 3. References for greet() — should be >= 2 (decl + call site).
    const refs = await lspReferences(lsp, FIX, {
      file: "Greeter.php",
      line: findIdentifier(join(FIX, "Greeter.php"), "greet").line,
      col: findIdentifier(join(FIX, "Greeter.php"), "greet").col,
      include_declaration: true,
    });
    if (refs.length < 2) {
      throw new Error(`lsp_references(greet) returned ${refs.length} (<2)`);
    }
    console.log(`references OK -> ${refs.length} hits`);

    console.log("LSP_PHP_SMOKE_PASS");
  } finally {
    await lsp.shutdown();
    cleanup();
  }
}

main()
  .then(() => process.exit(0))
  .catch((err) => {
    console.error("LSP_PHP_SMOKE_FAIL", err);
    cleanup();
    process.exit(1);
  });
