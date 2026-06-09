// MCP server — wires tool implementations into @modelcontextprotocol/sdk
// over stdio. Designed for Claude Code: one MCP server per stdio session,
// owning one Store, serving one indexed data dir.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { Store } from "../store";
import { LspService } from "../lsp";
import {
  graphNeighbors,
  graphCallers,
  graphImplementers,
  codeSearch,
  graphCypher,
  graphDiff,
  describeApi,
} from "./tools";
import {
  lspHover,
  lspDefinition,
  lspReferences,
  lspDiagnostics,
} from "./lsp-tools";
import { registerCtkrTools } from "./ctkr-tools";
import type { EdgeKind, TokenKind } from "../store/types";

export interface ServeOpts {
  dataDir: string;
  workspace: string;
}

export async function serveMcp(opts: ServeOpts): Promise<void> {
  const store = await Store.open(opts.dataDir);
  const lsp = new LspService({ rootDir: opts.workspace });

  const server = new McpServer(
    { name: "metacoding", version: "0.1.3" },
    { capabilities: { tools: {} } },
  );

  const EDGE_KIND = z.enum([
    "CALLS", "REFERENCES", "EXTENDS", "IMPLEMENTS", "OVERRIDES",
    "INJECTS", "CONTAINS", "IMPORTS", "ANNOTATES", "TYPE_OF",
  ]);
  const TOKEN_KIND = z.enum([
    "literal", "identifier", "comment", "annotation_arg", "config_value",
  ]);

  server.registerTool(
    "graph_callers",
    {
      description:
        "Find symbols that call or reference the given symbol (incoming CALLS/REFERENCES edges). " +
        "Available after a SCIP pass; before that, this returns nothing because Tree-sitter alone can't resolve cross-file references. " +
        "Pass repo_commit_sha to restrict results to one indexed snapshot (omit for no scope filter).",
      inputSchema: {
        symbol: z.string().min(1),
        limit: z.number().int().min(1).max(500).optional(),
        repo_commit_sha: z.string().optional(),
      },
    },
    async (args) => {
      const rows = await graphCallers(store, args);
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "graph_implementers",
    {
      description:
        "Find symbols that implement or extend the given interface/class (incoming IMPLEMENTS/EXTENDS edges). " +
        "This is the interface-consumer query from the 2026 paper — the thing pure vector search can't do. " +
        "Pass repo_commit_sha to restrict results to one indexed snapshot.",
      inputSchema: {
        symbol: z.string().min(1),
        limit: z.number().int().min(1).max(500).optional(),
        repo_commit_sha: z.string().optional(),
      },
    },
    async (args) => {
      const rows = await graphImplementers(store, args);
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "graph_neighbors",
    {
      description:
        "Walk one hop from a symbol along typed edges. Use for 'what does this contain', 'what does this extend', 'who calls this'. " +
        "`symbol` accepts either a 16-char Symbol id or a qualified_name. " +
        "Pass repo_commit_sha to restrict results to one indexed snapshot.",
      inputSchema: {
        symbol: z.string().min(1),
        direction: z.enum(["in", "out", "both"]).optional(),
        edge_kinds: z.array(EDGE_KIND).optional(),
        limit: z.number().int().min(1).max(500).optional(),
        repo_commit_sha: z.string().optional(),
      },
    },
    async (args) => {
      const rows = await graphNeighbors(store, {
        symbol: args.symbol,
        direction: args.direction,
        edge_kinds: args.edge_kinds as EdgeKind[] | undefined,
        limit: args.limit,
        repo_commit_sha: args.repo_commit_sha,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "code_search",
    {
      description:
        "Full-text search over identifiers, string literals, and comments. Catches AST/SCIP blind spots: string DI, reflection, dynamic dispatch, ORM strings, route paths. " +
        "Query syntax is SQLite FTS5 (supports phrase \"...\", prefix x*, NEAR(a b 5)). " +
        "Pass repo_commit_sha to restrict to one indexed snapshot.",
      inputSchema: {
        query: z.string().min(1),
        kind: TOKEN_KIND.optional(),
        limit: z.number().int().min(1).max(500).optional(),
        repo_commit_sha: z.string().optional(),
      },
    },
    async (args) => {
      const rows = codeSearch(store, {
        query: args.query,
        kind: args.kind as TokenKind | undefined,
        limit: args.limit,
        repo_commit_sha: args.repo_commit_sha,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "graph_cypher",
    {
      description:
        "Escape hatch: run a raw Cypher query against the ladybugdb graph. Prefer typed tools (graph_neighbors, etc.); use this only when no typed tool fits. " +
        "Parameters via $name placeholders; pass values in `params`.",
      inputSchema: {
        cypher: z.string().min(1),
        params: z.record(z.unknown()).optional(),
        limit: z.number().int().min(1).max(1000).optional(),
      },
    },
    async (args) => {
      const rows = await graphCypher(store, {
        cypher: args.cypher,
        params: args.params,
        limit: args.limit,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "graph_diff",
    {
      description:
        "Compare two indexed snapshots of the same repo, returning added / removed / changed Symbol rows. " +
        "`changed` = same qualified_name in both snapshots but different ast_hash. " +
        "Requires both snapshots to coexist in the store — this usually means the repo was indexed with --per-commit-identity. " +
        "Without that, only the most recent snapshot exists and the older one returns empty.",
      inputSchema: {
        repo: z.string().min(1),
        from_sha: z.string().min(1),
        to_sha: z.string().min(1),
        limit: z.number().int().min(1).max(10000).optional(),
      },
    },
    async (args) => {
      const r = await graphDiff(store, args);
      return { content: [{ type: "text", text: JSON.stringify(r, null, 2) }] };
    },
  );

  server.registerTool(
    "describe_api",
    {
      description:
        "Self-describe: returns the live tool list with input schemas, edge kinds, and token kinds. Use first to discover what this server can do.",
      inputSchema: {},
    },
    async () => {
      return { content: [{ type: "text", text: JSON.stringify(describeApi(), null, 2) }] };
    },
  );

  // ---------- LSP tools (live, dirty-buffer-aware) ----------

  server.registerTool(
    "lsp_hover",
    {
      description:
        "Live hover info from the language server: type, signature, docstring. " +
        "Reflects current file content (including unsaved edits made via the LSP didChange path). " +
        "Position is 0-indexed.",
      inputSchema: {
        file: z.string().min(1),
        line: z.number().int().min(0),
        col: z.number().int().min(0),
      },
    },
    async (args) => {
      const r = await lspHover(lsp, opts.workspace, args);
      return { content: [{ type: "text", text: JSON.stringify(r, null, 2) }] };
    },
  );

  server.registerTool(
    "lsp_definition",
    {
      description: "Live go-to-definition from the language server. Position is 0-indexed.",
      inputSchema: {
        file: z.string().min(1),
        line: z.number().int().min(0),
        col: z.number().int().min(0),
      },
    },
    async (args) => {
      const rows = await lspDefinition(lsp, opts.workspace, args);
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "lsp_references",
    {
      description:
        "Live find-all-references from the language server. Use when graph_callers might be stale (file was edited after indexing). Position is 0-indexed.",
      inputSchema: {
        file: z.string().min(1),
        line: z.number().int().min(0),
        col: z.number().int().min(0),
        include_declaration: z.boolean().optional(),
      },
    },
    async (args) => {
      const rows = await lspReferences(lsp, opts.workspace, args);
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "lsp_diagnostics",
    {
      description:
        "Current type errors / lints for a file from the language server. Opens the file (didOpen) if not already, then waits up to wait_ms (default 3000) for the first diagnostics push.",
      inputSchema: {
        file: z.string().min(1),
        wait_ms: z.number().int().min(0).max(30000).optional(),
      },
    },
    async (args) => {
      const rows = await lspDiagnostics(lsp, opts.workspace, args);
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  // ---------- CTKR Phase 1 tools ----------
  registerCtkrTools(server);

  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Graceful shutdown on signal — close Store and LSP before process exits.
  const shutdown = async () => {
    try { await lsp.shutdown(); } catch {}
    try { await store.close(); } catch {}
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}
