// MCP tool implementations for the LSP lane.
// All tools take absolute or workspace-relative file paths plus 0-indexed
// line/col (matching LSP itself). For each tool we ensure the file is open
// before issuing the request.

import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import type { LspService } from "../lsp";

export interface LspPositionInput {
  file: string;            // absolute or relative to workspace root
  line: number;            // 0-indexed
  col: number;             // 0-indexed character offset
}

interface SimpleLocation {
  file: string;
  line: number;
  col: number;
  end_line: number;
  end_col: number;
}

function resolveFile(workspace: string, file: string): string {
  return resolve(workspace, file);
}

function toSimpleLocations(
  uris: Array<{ uri: string; range: { start: { line: number; character: number }; end: { line: number; character: number } } }>,
): SimpleLocation[] {
  return uris.map((l) => ({
    file: fileURLToPath(l.uri),
    line: l.range.start.line,
    col: l.range.start.character,
    end_line: l.range.end.line,
    end_col: l.range.end.character,
  }));
}

export async function lspHover(
  lsp: LspService,
  workspace: string,
  input: LspPositionInput,
): Promise<{ markdown: string | null }> {
  const path = resolveFile(workspace, input.file);
  const client = await lsp.forFile(path);
  if (!client) return { markdown: null };
  const hover = await client.hover(path, input.line, input.col);
  if (!hover) return { markdown: null };
  const c = hover.contents;
  if (typeof c === "string") return { markdown: c };
  if (Array.isArray(c)) {
    const parts = c.map((seg) => (typeof seg === "string" ? seg : seg.value));
    return { markdown: parts.join("\n\n") };
  }
  return { markdown: c.value ?? null };
}

export async function lspDefinition(
  lsp: LspService,
  workspace: string,
  input: LspPositionInput,
): Promise<SimpleLocation[]> {
  const path = resolveFile(workspace, input.file);
  const client = await lsp.forFile(path);
  if (!client) return [];
  const locs = await client.definition(path, input.line, input.col);
  return toSimpleLocations(locs);
}

export async function lspReferences(
  lsp: LspService,
  workspace: string,
  input: LspPositionInput & { include_declaration?: boolean },
): Promise<SimpleLocation[]> {
  const path = resolveFile(workspace, input.file);
  const client = await lsp.forFile(path);
  if (!client) return [];
  const locs = await client.references(
    path,
    input.line,
    input.col,
    input.include_declaration ?? false,
  );
  return toSimpleLocations(locs);
}

export interface LspDiagnosticHit {
  file: string;
  line: number;
  col: number;
  end_line: number;
  end_col: number;
  severity: number | undefined;
  message: string;
  source: string | undefined;
  code: string | number | undefined;
}

export async function lspDiagnostics(
  lsp: LspService,
  workspace: string,
  input: { file: string; wait_ms?: number },
): Promise<LspDiagnosticHit[]> {
  const path = resolveFile(workspace, input.file);
  const client = await lsp.forFile(path);
  if (!client) return [];
  const diags = input.wait_ms !== 0
    ? await client.waitForDiagnostics(path, input.wait_ms ?? 3000)
    : client.getDiagnostics(path);
  return diags.map((d) => ({
    file: path,
    line: d.range.start.line,
    col: d.range.start.character,
    end_line: d.range.end.line,
    end_col: d.range.end.character,
    severity: d.severity,
    message: d.message,
    source: d.source,
    code: typeof d.code === "object" ? d.code.value : d.code,
  }));
}
