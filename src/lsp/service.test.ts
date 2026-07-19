// Tests for the LSP service's PHP lane (server discovery + routing).
//
// Hermetic tests (language-id mapping, not-installed error contract) run
// unconditionally. The live-server tests spawn the real intelephense
// binary against a small on-disk fixture and are gated behind an
// availability check, mirroring how scripts/smoke-lsp-php.ts verifies the
// same lane end-to-end but as a `bun test`-integrated case.

import { existsSync, mkdirSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { join, resolve } from "node:path";

import { test, expect, describe, afterAll } from "bun:test";

import { LspService, LspServerNotInstalledError } from "./index";
import { detectLanguageId } from "./client";
import { lspHover, lspDefinition, lspReferences } from "../mcp/lsp-tools";

describe("detectLanguageId", () => {
  test("maps .php to the php language id", () => {
    expect(detectLanguageId("/repo/src/Greeter.php")).toBe("php");
  });
});

describe("LspServerNotInstalledError", () => {
  test("message includes install instructions for intelephense", () => {
    const err = new LspServerNotInstalledError("intelephense", "bunx intelephense --stdio");
    expect(err.name).toBe("LspServerNotInstalledError");
    expect(err.message).toContain("intelephense");
    expect(err.message).toContain("bun add -D intelephense");
    expect(err.message).toContain("bunx intelephense --stdio");
  });
});

const intelephenseAvailable = existsSync(
  join(process.cwd(), "node_modules", ".bin", "intelephense"),
);

describe.skipIf(!intelephenseAvailable)("PHP LSP (live intelephense)", () => {
  const FIX = resolve("./tmp-php-lsp-service-test-fixture");
  const lsp = new LspService({ rootDir: FIX });

  const GREETER_PHP = `<?php
namespace App;

class Greeter {
    public function greet(string $name): string {
        return "Hello, " . $name;
    }
}
`;

  mkdirSync(FIX, { recursive: true });
  writeFileSync(join(FIX, "Greeter.php"), GREETER_PHP, "utf-8");

  function findIdentifier(ident: string): { line: number; col: number } {
    const text = readFileSync(join(FIX, "Greeter.php"), "utf-8");
    const lines = text.split("\n");
    const re = new RegExp(`(^|[^A-Za-z0-9_$])(${ident})([^A-Za-z0-9_$]|$)`);
    for (let i = 0; i < lines.length; i++) {
      const m = re.exec(lines[i]!);
      if (m) return { line: i, col: m.index + m[1]!.length };
    }
    throw new Error(`identifier ${ident} not found`);
  }

  afterAll(async () => {
    await lsp.shutdown();
    if (existsSync(FIX)) rmSync(FIX, { recursive: true, force: true });
  });

  test("forFile() routes .php to a client that can hover the class decl", async () => {
    const client = await lsp.forFile(join(FIX, "Greeter.php"));
    expect(client).not.toBeNull();

    const pos = findIdentifier("Greeter");
    let hover = await lspHover(lsp, FIX, { file: "Greeter.php", ...pos });
    if (!hover.markdown) {
      // First hover can race server indexing; one short retry.
      await new Promise((r) => setTimeout(r, 1500));
      hover = await lspHover(lsp, FIX, { file: "Greeter.php", ...pos });
    }
    expect(hover.markdown).not.toBeNull();
    expect(hover.markdown).toContain("Greeter");
  }, 30000);

  test("definition() resolves greet() to its declaration", async () => {
    const pos = findIdentifier("greet");
    const defs = await lspDefinition(lsp, FIX, { file: "Greeter.php", ...pos });
    expect(defs.length).toBeGreaterThan(0);
    expect(defs.some((d) => d.file.endsWith("Greeter.php"))).toBe(true);
  }, 30000);

  test("references() finds the greet() declaration", async () => {
    const pos = findIdentifier("greet");
    const refs = await lspReferences(lsp, FIX, {
      file: "Greeter.php",
      ...pos,
      include_declaration: true,
    });
    expect(refs.length).toBeGreaterThan(0);
  }, 30000);
});
