// LSP client: one language-server subprocess + JSON-RPC connection,
// plus a small async-friendly diagnostics cache.
//
// Designed for our use case (one workspace, agent-driven queries):
//   - Lazy didOpen: files are opened on first hover/definition/references hit.
//   - Diagnostics arrive via push notification; we cache the latest snapshot
//     per file URI and let callers either read the snapshot or await the
//     next push.
//
// We talk LSP directly over JSON-RPC rather than going through
// vscode-languageclient, which is bound to VS Code's runtime.

import { spawn, type ChildProcess } from "node:child_process";
import { readFileSync } from "node:fs";
import { pathToFileURL } from "node:url";

import {
  createMessageConnection,
  StreamMessageReader,
  StreamMessageWriter,
  type MessageConnection,
} from "vscode-jsonrpc/node";
import type {
  Diagnostic,
  Hover,
  InitializeParams,
  InitializeResult,
  Location,
  PublishDiagnosticsParams,
  TextDocumentItem,
} from "vscode-languageserver-protocol";

export interface LspClientOpts {
  rootDir: string;
  command: string;
  args: string[];
  /** Pipe LSP stderr through to our stderr (debugging). */
  verbose?: boolean;
}

export class LspClient {
  private opened = new Set<string>();
  private diagnostics = new Map<string, Diagnostic[]>();
  private diagWaiters = new Map<string, Array<(d: Diagnostic[]) => void>>();
  private nextDocVersion = 1;

  private constructor(
    private readonly proc: ChildProcess,
    private readonly conn: MessageConnection,
    private readonly rootDir: string,
  ) {}

  static async spawn(opts: LspClientOpts): Promise<LspClient> {
    const proc = spawn(opts.command, opts.args, {
      stdio: ["pipe", "pipe", "pipe"],
    });
    if (opts.verbose) {
      proc.stderr?.on("data", (d) => process.stderr.write(`[lsp] ${d}`));
    } else {
      proc.stderr?.on("data", () => { /* swallow */ });
    }
    const conn = createMessageConnection(
      new StreamMessageReader(proc.stdout!),
      new StreamMessageWriter(proc.stdin!),
    );
    const client = new LspClient(proc, conn, opts.rootDir);

    conn.onNotification("textDocument/publishDiagnostics", (p: PublishDiagnosticsParams) => {
      client.diagnostics.set(p.uri, p.diagnostics);
      const waiters = client.diagWaiters.get(p.uri);
      if (waiters) {
        for (const w of waiters) w(p.diagnostics);
        client.diagWaiters.delete(p.uri);
      }
    });

    conn.listen();
    return client;
  }

  async initialize(): Promise<void> {
    const rootUri = pathToFileURL(this.rootDir).toString();
    const params: InitializeParams = {
      processId: process.pid,
      rootUri,
      workspaceFolders: [{ uri: rootUri, name: "metacoding" }],
      capabilities: {
        textDocument: {
          hover: { contentFormat: ["markdown", "plaintext"] },
          definition: { linkSupport: false },
          references: {},
          publishDiagnostics: { relatedInformation: true },
          synchronization: { didSave: true },
        },
        workspace: {},
      },
      clientInfo: { name: "metacoding", version: "0.1.0" },
    };
    await this.conn.sendRequest<InitializeResult>("initialize", params);
    this.conn.sendNotification("initialized", {});
  }

  private uriOf(absPath: string): string {
    return pathToFileURL(absPath).toString();
  }

  ensureFileOpen(absPath: string): void {
    if (this.opened.has(absPath)) return;
    const item: TextDocumentItem = {
      uri: this.uriOf(absPath),
      languageId: detectLanguageId(absPath),
      version: this.nextDocVersion++,
      text: readFileSync(absPath, "utf-8"),
    };
    this.conn.sendNotification("textDocument/didOpen", { textDocument: item });
    this.opened.add(absPath);
  }

  async hover(absPath: string, line: number, col: number): Promise<Hover | null> {
    this.ensureFileOpen(absPath);
    return this.conn.sendRequest<Hover | null>("textDocument/hover", {
      textDocument: { uri: this.uriOf(absPath) },
      position: { line, character: col },
    });
  }

  async definition(absPath: string, line: number, col: number): Promise<Location[]> {
    this.ensureFileOpen(absPath);
    const result = await this.conn.sendRequest<Location | Location[] | null>(
      "textDocument/definition",
      {
        textDocument: { uri: this.uriOf(absPath) },
        position: { line, character: col },
      },
    );
    if (!result) return [];
    return Array.isArray(result) ? result : [result];
  }

  async references(
    absPath: string,
    line: number,
    col: number,
    includeDeclaration = false,
  ): Promise<Location[]> {
    this.ensureFileOpen(absPath);
    const result = await this.conn.sendRequest<Location[] | null>(
      "textDocument/references",
      {
        textDocument: { uri: this.uriOf(absPath) },
        position: { line, character: col },
        context: { includeDeclaration },
      },
    );
    return result ?? [];
  }

  /** Returns the latest cached diagnostics for a file (may be stale or empty). */
  getDiagnostics(absPath: string): Diagnostic[] {
    return this.diagnostics.get(this.uriOf(absPath)) ?? [];
  }

  /** Opens the file and waits for the LSP's first publishDiagnostics for it (or timeout). */
  async waitForDiagnostics(absPath: string, timeoutMs = 5000): Promise<Diagnostic[]> {
    this.ensureFileOpen(absPath);
    const uri = this.uriOf(absPath);
    if (this.diagnostics.has(uri)) return this.diagnostics.get(uri)!;
    return new Promise<Diagnostic[]>((resolve) => {
      const arr = this.diagWaiters.get(uri) ?? [];
      const timer = setTimeout(() => {
        const idx = arr.indexOf(onPush);
        if (idx >= 0) arr.splice(idx, 1);
        resolve(this.diagnostics.get(uri) ?? []);
      }, timeoutMs);
      const onPush = (d: Diagnostic[]): void => {
        clearTimeout(timer);
        resolve(d);
      };
      arr.push(onPush);
      this.diagWaiters.set(uri, arr);
    });
  }

  /** All currently known diagnostics across opened files. */
  allDiagnostics(): Record<string, Diagnostic[]> {
    const out: Record<string, Diagnostic[]> = {};
    for (const [uri, diags] of this.diagnostics) out[uri] = diags;
    return out;
  }

  async shutdown(): Promise<void> {
    try {
      await this.conn.sendRequest("shutdown");
      this.conn.sendNotification("exit");
    } catch { /* server may have already exited */ }
    try { this.conn.dispose(); } catch {}
    try { this.proc.kill(); } catch {}
  }
}

export function detectLanguageId(absPath: string): string {
  if (absPath.endsWith(".tsx")) return "typescriptreact";
  if (absPath.endsWith(".ts") || absPath.endsWith(".mts") || absPath.endsWith(".cts"))
    return "typescript";
  if (absPath.endsWith(".jsx")) return "javascriptreact";
  if (absPath.endsWith(".js") || absPath.endsWith(".mjs") || absPath.endsWith(".cjs"))
    return "javascript";
  if (absPath.endsWith(".php")) return "php";
  return "plaintext";
}
