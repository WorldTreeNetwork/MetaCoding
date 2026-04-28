// MCP tool implementations.
//
// Pure functions over a Store. server.ts wires them into the MCP SDK;
// tests and the CLI can call them directly.

import type { Store } from "../store";
import type { TokenKind, EdgeKind } from "../store/types";

// ---------- shared envelopes ----------

export interface SymbolEnvelope {
  id: string;
  kind: string;
  language: string;
  qualified_name: string;
  short_name: string;
  file: string;
  line: number;
}

export interface NeighborRow {
  symbol: SymbolEnvelope;
  edge: { kind: string };
  direction: "in" | "out";
}

// ---------- graph_neighbors ----------

const VALID_EDGE_KINDS: ReadonlyArray<EdgeKind> = [
  "CALLS", "REFERENCES", "EXTENDS", "IMPLEMENTS", "OVERRIDES",
  "INJECTS", "CONTAINS", "IMPORTS", "ANNOTATES", "TYPE_OF",
];

export interface GraphNeighborsInput {
  symbol: string;                      // id or qualified_name
  direction?: "in" | "out" | "both";   // default "out"
  edge_kinds?: EdgeKind[];              // filter; default = all
  limit?: number;                       // default 50
}

export async function graphNeighbors(
  store: Store,
  input: GraphNeighborsInput,
): Promise<NeighborRow[]> {
  const direction = input.direction ?? "out";
  const limit = clamp(input.limit ?? 50, 1, 500);
  const kinds = (input.edge_kinds ?? VALID_EDGE_KINDS).filter((k) =>
    VALID_EDGE_KINDS.includes(k),
  );
  if (kinds.length === 0) return [];

  // Resolve "symbol" — accept either id or qualified_name.
  const seed = await resolveSymbol(store, input.symbol);
  if (!seed) return [];

  const out: NeighborRow[] = [];

  for (const kind of kinds) {
    if (direction === "out" || direction === "both") {
      const rows = await store.query<{
        id: string; kind: string; language: string;
        qualified_name: string; short_name: string;
        file: string; line: number;
      }>(
        `MATCH (a:Symbol {id: $id})-[:${kind}]->(b:Symbol)
         RETURN b.id AS id, b.kind AS kind, b.language AS language,
                b.qualified_name AS qualified_name, b.short_name AS short_name,
                b.file AS file, b.line AS line
         LIMIT $lim`,
        { id: seed.id, lim: limit },
      );
      for (const r of rows) {
        out.push({ symbol: r, edge: { kind }, direction: "out" });
      }
    }
    if (direction === "in" || direction === "both") {
      const rows = await store.query<{
        id: string; kind: string; language: string;
        qualified_name: string; short_name: string;
        file: string; line: number;
      }>(
        `MATCH (a:Symbol)-[:${kind}]->(b:Symbol {id: $id})
         RETURN a.id AS id, a.kind AS kind, a.language AS language,
                a.qualified_name AS qualified_name, a.short_name AS short_name,
                a.file AS file, a.line AS line
         LIMIT $lim`,
        { id: seed.id, lim: limit },
      );
      for (const r of rows) {
        out.push({ symbol: r, edge: { kind }, direction: "in" });
      }
    }
  }

  return out.slice(0, limit);
}

// ---------- graph_callers ----------

export interface GraphCallersInput {
  symbol: string;       // target id or qualified_name
  limit?: number;
}

export async function graphCallers(
  store: Store,
  input: GraphCallersInput,
): Promise<NeighborRow[]> {
  return graphNeighbors(store, {
    symbol: input.symbol,
    direction: "in",
    edge_kinds: ["CALLS", "REFERENCES"],
    limit: input.limit,
  });
}

// ---------- graph_implementers ----------

export interface GraphImplementersInput {
  symbol: string;       // interface or class id / qualified_name
  limit?: number;
}

export async function graphImplementers(
  store: Store,
  input: GraphImplementersInput,
): Promise<NeighborRow[]> {
  return graphNeighbors(store, {
    symbol: input.symbol,
    direction: "in",
    edge_kinds: ["IMPLEMENTS", "EXTENDS"],
    limit: input.limit,
  });
}

// ---------- code_search ----------

const VALID_TOKEN_KINDS: ReadonlyArray<TokenKind> = [
  "literal", "identifier", "comment", "annotation_arg", "config_value",
];

export interface CodeSearchInput {
  query: string;
  kind?: TokenKind;
  limit?: number;
}

export interface CodeSearchHit {
  text: string;
  kind: string;
  file: string;
  line: number;
  col: number;
  symbol_id: string | null;
}

export function codeSearch(store: Store, input: CodeSearchInput): CodeSearchHit[] {
  if (!input.query || input.query.length < 2) return [];
  const limit = clamp(input.limit ?? 50, 1, 500);
  const hits = store.searchTokens(input.query, limit * 2);
  const filtered = input.kind
    ? hits.filter((h) => h.kind === input.kind)
    : hits;
  return filtered.slice(0, limit).map((h) => ({
    text: h.text,
    kind: h.kind,
    file: h.file,
    line: h.line,
    col: h.col,
    symbol_id: h.symbol_id,
  }));
}

// ---------- graph_cypher ----------

export interface GraphCypherInput {
  cypher: string;
  params?: Record<string, unknown>;
  limit?: number;
}

export async function graphCypher(
  store: Store,
  input: GraphCypherInput,
): Promise<Record<string, unknown>[]> {
  if (!input.cypher) return [];
  const limit = clamp(input.limit ?? 100, 1, 1000);
  const rows = await store.query<Record<string, unknown>>(input.cypher, input.params ?? {});
  return rows.slice(0, limit);
}

// ---------- describe_api ----------

export interface ToolDescription {
  name: string;
  summary: string;
  input_schema: Record<string, unknown>;
}

export const TOOL_DESCRIPTIONS: ToolDescription[] = [
  {
    name: "graph_callers",
    summary: "Find symbols that call or reference the given symbol (incoming CALLS/REFERENCES edges). Convenience wrapper over graph_neighbors. Useful for 'who depends on this'.",
    input_schema: {
      type: "object",
      required: ["symbol"],
      properties: {
        symbol: { type: "string" },
        limit: { type: "integer", minimum: 1, maximum: 500, default: 50 },
      },
    },
  },
  {
    name: "graph_implementers",
    summary: "Find symbols that implement or extend the given interface/class (incoming IMPLEMENTS/EXTENDS edges). The interface-consumer trick from the paper.",
    input_schema: {
      type: "object",
      required: ["symbol"],
      properties: {
        symbol: { type: "string" },
        limit: { type: "integer", minimum: 1, maximum: 500, default: 50 },
      },
    },
  },
  {
    name: "graph_neighbors",
    summary: "Walk one hop from a symbol along typed edges. Use for 'what does this contain', 'what extends this', 'who calls this'.",
    input_schema: {
      type: "object",
      required: ["symbol"],
      properties: {
        symbol: { type: "string", description: "Symbol id (16-char hash) or qualified_name." },
        direction: { type: "string", enum: ["in", "out", "both"], default: "out" },
        edge_kinds: {
          type: "array",
          items: { type: "string", enum: VALID_EDGE_KINDS as unknown as string[] },
          description: "Filter; defaults to all edge kinds.",
        },
        limit: { type: "integer", minimum: 1, maximum: 500, default: 50 },
      },
    },
  },
  {
    name: "code_search",
    summary: "Full-text search across identifiers, string literals, and comments. Catches the AST blind spots: string DI, reflection, dynamic dispatch.",
    input_schema: {
      type: "object",
      required: ["query"],
      properties: {
        query: { type: "string", description: "FTS5 query (supports phrase, prefix, NEAR)." },
        kind: { type: "string", enum: VALID_TOKEN_KINDS as unknown as string[] },
        limit: { type: "integer", minimum: 1, maximum: 500, default: 50 },
      },
    },
  },
  {
    name: "graph_cypher",
    summary: "Escape hatch: run a raw Cypher query against the graph. Prefer typed tools; use this only when no typed tool fits.",
    input_schema: {
      type: "object",
      required: ["cypher"],
      properties: {
        cypher: { type: "string" },
        params: { type: "object", additionalProperties: true },
        limit: { type: "integer", minimum: 1, maximum: 1000, default: 100 },
      },
    },
  },
  {
    name: "describe_api",
    summary: "Self-describe: returns this tool list with input schemas and usage examples.",
    input_schema: { type: "object", properties: {} },
  },
];

export interface DescribeApiResult {
  name: string;
  version: string;
  tools: ToolDescription[];
  schema: {
    edge_kinds: string[];
    token_kinds: string[];
  };
}

export function describeApi(): DescribeApiResult {
  return {
    name: "metacoding",
    version: "0.1.0",
    tools: TOOL_DESCRIPTIONS,
    schema: {
      edge_kinds: VALID_EDGE_KINDS as unknown as string[],
      token_kinds: VALID_TOKEN_KINDS as unknown as string[],
    },
  };
}

// ---------- helpers ----------

async function resolveSymbol(
  store: Store,
  ref: string,
): Promise<{ id: string } | null> {
  const rows = await store.query<{ id: string }>(
    `MATCH (s:Symbol)
     WHERE s.id = $ref OR s.qualified_name = $ref
     RETURN s.id AS id
     LIMIT 1`,
    { ref },
  );
  return rows[0] ?? null;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
