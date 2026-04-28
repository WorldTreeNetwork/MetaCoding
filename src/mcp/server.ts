// MCP server — wires tool implementations into @modelcontextprotocol/sdk
// over stdio. Designed for Claude Code: one MCP server per stdio session,
// owning one Store, serving one indexed data dir.

import { McpServer } from "@modelcontextprotocol/sdk/server/mcp.js";
import { StdioServerTransport } from "@modelcontextprotocol/sdk/server/stdio.js";
import { z } from "zod";

import { Store } from "../store";
import {
  graphNeighbors,
  codeSearch,
  graphCypher,
  describeApi,
} from "./tools";
import type { EdgeKind, TokenKind } from "../store/types";

export interface ServeOpts {
  dataDir: string;
}

export async function serveMcp(opts: ServeOpts): Promise<void> {
  const store = await Store.open(opts.dataDir);

  const server = new McpServer(
    { name: "metacoding", version: "0.1.0" },
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
    "graph_neighbors",
    {
      description:
        "Walk one hop from a symbol along typed edges. Use for 'what does this contain', 'what does this extend', 'who calls this'. " +
        "`symbol` accepts either a 16-char Symbol id or a qualified_name.",
      inputSchema: {
        symbol: z.string().min(1),
        direction: z.enum(["in", "out", "both"]).optional(),
        edge_kinds: z.array(EDGE_KIND).optional(),
        limit: z.number().int().min(1).max(500).optional(),
      },
    },
    async (args) => {
      const rows = await graphNeighbors(store, {
        symbol: args.symbol,
        direction: args.direction,
        edge_kinds: args.edge_kinds as EdgeKind[] | undefined,
        limit: args.limit,
      });
      return { content: [{ type: "text", text: JSON.stringify(rows, null, 2) }] };
    },
  );

  server.registerTool(
    "code_search",
    {
      description:
        "Full-text search over identifiers, string literals, and comments. Catches AST/SCIP blind spots: string DI, reflection, dynamic dispatch, ORM strings, route paths. " +
        "Query syntax is SQLite FTS5 (supports phrase \"...\", prefix x*, NEAR(a b 5)).",
      inputSchema: {
        query: z.string().min(1),
        kind: TOKEN_KIND.optional(),
        limit: z.number().int().min(1).max(500).optional(),
      },
    },
    async (args) => {
      const rows = codeSearch(store, {
        query: args.query,
        kind: args.kind as TokenKind | undefined,
        limit: args.limit,
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

  const transport = new StdioServerTransport();
  await server.connect(transport);

  // Graceful shutdown on signal — close Store before process exits so
  // both stores flush and we don't leave WAL files behind.
  const shutdown = async () => {
    try { await store.close(); } catch {}
    process.exit(0);
  };
  process.on("SIGINT", shutdown);
  process.on("SIGTERM", shutdown);
}
