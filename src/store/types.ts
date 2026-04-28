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
}

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
  file: string;
  line: number;
  col: number;
  symbol_id: string | null;
}
