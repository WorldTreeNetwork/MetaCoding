// Shared types for the graph + FTS store.
// Schema reference: docs/design/schema.md.

export type SymbolKind =
  | "file"
  | "module"
  | "class"
  | "interface"
  | "enum"
  | "function"
  | "method"
  | "field"
  | "parameter"
  | "annotation"
  | "type_alias"
  | "namespace";

export type Visibility = "public" | "private" | "protected" | "internal";

export type ExtractorSource = "scip" | "lsp" | "tree_sitter" | "joern";

export interface Symbol {
  id: string;
  kind: SymbolKind;
  language: string;
  repo: string;             // e.g. "cline", "crewAI" — cross-repo dimension
  qualified_name: string;
  short_name: string;
  file: string;
  line: number;
  col: number;
  end_line: number;
  end_col: number;
  signature: string | null;
  visibility: Visibility | null;
  is_abstract: boolean;
  is_static: boolean;
  ast_hash: string | null;
  branch: string;
  source: ExtractorSource;
  // Added by Orchestrators-2ez. NULLable for backward compatibility
  // with rows written before the schema migration; backfilled
  // out-of-band by scripts/backfill-temporal-cols.ts.
  indexed_at?: string | null;        // ISO-8601 (UTC); when the row was first written
  repo_commit_sha?: string | null;   // git rev-parse HEAD at index time
  repo_commit_date?: string | null;  // ISO-8601 (UTC); committer date of that sha
  partition?: Partition | null;      // see docs/research/.../h5-eval-contamination
}

export type Partition = "proposer" | "judge" | "harness_bench";

export type EdgeKind =
  | "CALLS"
  | "REFERENCES"
  | "EXTENDS"
  | "IMPLEMENTS"
  | "OVERRIDES"
  | "INJECTS"
  | "CONTAINS"
  | "IMPORTS"
  | "ANNOTATES"
  | "TYPE_OF";

export interface Edge {
  src_id: string;
  dst_id: string;
  kind: EdgeKind;
  count?: number;
}

export type TokenKind =
  | "literal"
  | "identifier"
  | "comment"
  | "annotation_arg"
  | "config_value";

export interface TokenRow {
  text: string;
  kind: TokenKind;
  repo: string;
  file: string;
  line: number;
  col: number;
  symbol_id: string | null;
}
