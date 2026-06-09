// MCP tool implementations.
//
// Pure functions over a Store. server.ts wires them into the MCP SDK;
// tests and the CLI can call them directly.

import type { Store } from "../store";
import type { TokenKind, EdgeKind } from "../store/types";
import { CTKR_TOOL_DESCRIPTIONS } from "./ctkr-tools";

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
  repo_commit_sha?: string;             // optional scope: restrict to a snapshot
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
  const seed = await resolveSymbol(store, input.symbol, input.repo_commit_sha);
  if (!seed) return [];

  const shaFilter = input.repo_commit_sha
    ? " AND b.repo_commit_sha = $sha"
    : "";
  const params: Record<string, unknown> = { id: seed.id, lim: limit };
  if (input.repo_commit_sha) params.sha = input.repo_commit_sha;

  const out: NeighborRow[] = [];

  for (const kind of kinds) {
    if (direction === "out" || direction === "both") {
      const rows = await store.query<{
        id: string; kind: string; language: string;
        qualified_name: string; short_name: string;
        file: string; line: number;
      }>(
        `MATCH (a:Symbol {id: $id})-[:${kind}]->(b:Symbol)
         WHERE 1=1${shaFilter}
         RETURN b.id AS id, b.kind AS kind, b.language AS language,
                b.qualified_name AS qualified_name, b.short_name AS short_name,
                b.file AS file, b.line AS line
         LIMIT $lim`,
        params,
      );
      for (const r of rows) {
        out.push({ symbol: r, edge: { kind }, direction: "out" });
      }
    }
    if (direction === "in" || direction === "both") {
      // Reverse-direction filter: filter the OTHER endpoint by sha.
      const reverseFilter = input.repo_commit_sha
        ? " WHERE a.repo_commit_sha = $sha"
        : "";
      const rows = await store.query<{
        id: string; kind: string; language: string;
        qualified_name: string; short_name: string;
        file: string; line: number;
      }>(
        `MATCH (a:Symbol)-[:${kind}]->(b:Symbol {id: $id})
         ${reverseFilter}
         RETURN a.id AS id, a.kind AS kind, a.language AS language,
                a.qualified_name AS qualified_name, a.short_name AS short_name,
                a.file AS file, a.line AS line
         LIMIT $lim`,
        params,
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
  repo_commit_sha?: string;
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
    repo_commit_sha: input.repo_commit_sha,
  });
}

// ---------- graph_implementers ----------

export interface GraphImplementersInput {
  symbol: string;       // interface or class id / qualified_name
  limit?: number;
  repo_commit_sha?: string;
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
    repo_commit_sha: input.repo_commit_sha,
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
  repo_commit_sha?: string;
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
  const hits = store.searchTokens(input.query, limit * 2, undefined, input.repo_commit_sha);
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

// ---------- graph_diff ----------

export interface GraphDiffInput {
  repo: string;
  from_sha: string;
  to_sha: string;
  limit?: number;
}

export interface DiffSymbol {
  id: string;
  qualified_name: string;
  short_name: string;
  kind: string;
  file: string;
  line: number;
  ast_hash: string | null;
}

export interface GraphDiffResult {
  added: DiffSymbol[];     // present in to_sha, absent in from_sha (by qualified_name)
  removed: DiffSymbol[];   // present in from_sha, absent in to_sha
  changed: { qualified_name: string; from: DiffSymbol; to: DiffSymbol }[];
  counts: { added: number; removed: number; changed: number; unchanged: number };
}

interface DiffRow {
  id: string;
  qn: string;
  short: string;
  kind: string;
  file: string;
  line: number;
  ast_hash: string | null;
}

function toEnvelope(r: DiffRow): DiffSymbol {
  return {
    id: r.id,
    qualified_name: r.qn,
    short_name: r.short,
    kind: r.kind,
    file: r.file,
    line: r.line,
    ast_hash: r.ast_hash,
  };
}

export async function graphDiff(
  store: Store,
  input: GraphDiffInput,
): Promise<GraphDiffResult> {
  const empty: GraphDiffResult = {
    added: [], removed: [], changed: [],
    counts: { added: 0, removed: 0, changed: 0, unchanged: 0 },
  };
  if (!input.repo || !input.from_sha || !input.to_sha) return empty;
  const limit = clamp(input.limit ?? 1000, 1, 10000);

  const SNAPSHOT_QUERY =
    `MATCH (s:Symbol)
     WHERE s.repo = $repo AND s.repo_commit_sha = $sha
     RETURN s.id AS id, s.qualified_name AS qn, s.short_name AS short,
            s.kind AS kind, s.file AS file, s.line AS line, s.ast_hash AS ast_hash`;

  const [fromRows, toRows] = await Promise.all([
    store.query<DiffRow>(SNAPSHOT_QUERY, { repo: input.repo, sha: input.from_sha }),
    store.query<DiffRow>(SNAPSHOT_QUERY, { repo: input.repo, sha: input.to_sha }),
  ]);

  const fromMap = new Map<string, DiffRow>();
  for (const r of fromRows) fromMap.set(r.qn, r);
  const toMap = new Map<string, DiffRow>();
  for (const r of toRows) toMap.set(r.qn, r);

  const added: DiffSymbol[] = [];
  const removed: DiffSymbol[] = [];
  const changed: { qualified_name: string; from: DiffSymbol; to: DiffSymbol }[] = [];
  let unchanged = 0;

  for (const [qn, to] of toMap) {
    const from = fromMap.get(qn);
    if (!from) {
      added.push(toEnvelope(to));
    } else if (from.ast_hash !== to.ast_hash) {
      changed.push({ qualified_name: qn, from: toEnvelope(from), to: toEnvelope(to) });
    } else {
      unchanged++;
    }
  }
  for (const [qn, from] of fromMap) {
    if (!toMap.has(qn)) removed.push(toEnvelope(from));
  }

  return {
    added: added.slice(0, limit),
    removed: removed.slice(0, limit),
    changed: changed.slice(0, limit),
    counts: {
      added: added.length,
      removed: removed.length,
      changed: changed.length,
      unchanged,
    },
  };
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
    summary: "Find symbols that call or reference the given symbol (incoming CALLS/REFERENCES edges). Convenience wrapper over graph_neighbors. Useful for 'who depends on this'. Pass repo_commit_sha to scope to one indexed snapshot.",
    input_schema: {
      type: "object",
      required: ["symbol"],
      properties: {
        symbol: { type: "string" },
        limit: { type: "integer", minimum: 1, maximum: 500, default: 50 },
        repo_commit_sha: { type: "string", description: "Optional: restrict to a specific indexed snapshot." },
      },
    },
  },
  {
    name: "graph_implementers",
    summary: "Find symbols that implement or extend the given interface/class (incoming IMPLEMENTS/EXTENDS edges). The interface-consumer trick from the paper. Pass repo_commit_sha to scope to one indexed snapshot.",
    input_schema: {
      type: "object",
      required: ["symbol"],
      properties: {
        symbol: { type: "string" },
        limit: { type: "integer", minimum: 1, maximum: 500, default: 50 },
        repo_commit_sha: { type: "string", description: "Optional: restrict to a specific indexed snapshot." },
      },
    },
  },
  {
    name: "graph_neighbors",
    summary: "Walk one hop from a symbol along typed edges. Use for 'what does this contain', 'what extends this', 'who calls this'. Pass repo_commit_sha to scope to one indexed snapshot.",
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
        repo_commit_sha: { type: "string", description: "Optional: restrict to a specific indexed snapshot." },
      },
    },
  },
  {
    name: "code_search",
    summary: "Full-text search across identifiers, string literals, and comments. Catches the AST blind spots: string DI, reflection, dynamic dispatch. Pass repo_commit_sha to scope to one indexed snapshot.",
    input_schema: {
      type: "object",
      required: ["query"],
      properties: {
        query: { type: "string", description: "FTS5 query (supports phrase, prefix, NEAR)." },
        kind: { type: "string", enum: VALID_TOKEN_KINDS as unknown as string[] },
        limit: { type: "integer", minimum: 1, maximum: 500, default: 50 },
        repo_commit_sha: { type: "string", description: "Optional: restrict to a specific indexed snapshot." },
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
    name: "graph_diff",
    summary: "Compare two indexed snapshots of the same repo. Returns added / removed / changed symbols by qualified_name; changed = same name, different ast_hash. Requires both snapshots to coexist — usually means --per-commit-identity was used when indexing.",
    input_schema: {
      type: "object",
      required: ["repo", "from_sha", "to_sha"],
      properties: {
        repo: { type: "string" },
        from_sha: { type: "string", description: "git commit sha of the baseline snapshot." },
        to_sha: { type: "string", description: "git commit sha of the target snapshot." },
        limit: { type: "integer", minimum: 1, maximum: 10000, default: 1000 },
      },
    },
  },
  {
    name: "lsp_hover",
    summary: "Live hover info (type, signature, docstring) from the language server. Reflects current/dirty file content.",
    input_schema: {
      type: "object",
      required: ["file", "line", "col"],
      properties: {
        file: { type: "string" },
        line: { type: "integer", minimum: 0 },
        col: { type: "integer", minimum: 0 },
      },
    },
  },
  {
    name: "lsp_definition",
    summary: "Live go-to-definition from the language server.",
    input_schema: {
      type: "object",
      required: ["file", "line", "col"],
      properties: {
        file: { type: "string" },
        line: { type: "integer", minimum: 0 },
        col: { type: "integer", minimum: 0 },
      },
    },
  },
  {
    name: "lsp_references",
    summary: "Live find-all-references from the language server. Use when graph_callers might be stale.",
    input_schema: {
      type: "object",
      required: ["file", "line", "col"],
      properties: {
        file: { type: "string" },
        line: { type: "integer", minimum: 0 },
        col: { type: "integer", minimum: 0 },
        include_declaration: { type: "boolean", default: false },
      },
    },
  },
  {
    name: "lsp_diagnostics",
    summary: "Current type errors / lints for a file from the language server.",
    input_schema: {
      type: "object",
      required: ["file"],
      properties: {
        file: { type: "string" },
        wait_ms: { type: "integer", minimum: 0, maximum: 30000, default: 3000 },
      },
    },
  },
  // CTKR Phase 1+ tools, co-located with their registrations in ctkr-tools.ts
  // so describe_api can't drift from the live surface.
  ...CTKR_TOOL_DESCRIPTIONS,
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
    version: "0.1.4",
    tools: TOOL_DESCRIPTIONS,
    schema: {
      edge_kinds: VALID_EDGE_KINDS as unknown as string[],
      token_kinds: VALID_TOKEN_KINDS as unknown as string[],
    },
  };
}

// ---------- helpers ----------

/**
 * Resolve a symbol reference (id or qualified_name) to its canonical id.
 *
 * When `repo_commit_sha` is provided, resolution is scoped to that exact
 * snapshot and is unambiguous.
 *
 * When `repo_commit_sha` is absent and the store was indexed with
 * `--per-commit-identity`, multiple snapshots of the same logical symbol
 * can coexist and the pick is **arbitrary**.  Callers operating against a
 * per-commit-identity store SHOULD always pass `repo_commit_sha` to avoid
 * silently returning the wrong snapshot.  A `console.warn` is emitted
 * whenever the no-sha path encounters more than one candidate.
 */
async function resolveSymbol(
  store: Store,
  ref: string,
  repo_commit_sha?: string,
): Promise<{ id: string } | null> {
  if (repo_commit_sha) {
    const rows = await store.query<{ id: string }>(
      `MATCH (s:Symbol)
       WHERE (s.id = $ref OR s.qualified_name = $ref)
         AND s.repo_commit_sha = $sha
       RETURN s.id AS id
       LIMIT 1`,
      { ref, sha: repo_commit_sha },
    );
    return rows[0] ?? null;
  }
  // Fetch up to 2 rows so we can detect ambiguity without a separate COUNT query.
  const rows = await store.query<{ id: string }>(
    `MATCH (s:Symbol)
     WHERE s.id = $ref OR s.qualified_name = $ref
     RETURN s.id AS id
     LIMIT 2`,
    { ref },
  );
  if (rows.length > 1) {
    console.warn(
      `metacoding: resolveSymbol("${ref}") matched multiple snapshots; picking arbitrarily — pass repo_commit_sha to disambiguate.`,
    );
  }
  return rows[0] ?? null;
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, n));
}
