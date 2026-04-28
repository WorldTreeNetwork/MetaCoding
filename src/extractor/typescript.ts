// TypeScript extractor.
//
// Walks a parsed Tree-sitter tree and emits Symbol / Edge / TokenRow records
// per the schema in docs/design/schema.md. Phase-1 scope:
//   - Symbol nodes: file, class, interface, enum, function, method, field,
//     type_alias.
//   - CONTAINS edges (file -> top-level, class -> method, etc.).
//   - Tokens: identifiers, string literals, comments.
//   - EXTENDS / IMPLEMENTS edges deferred to a later pass that can resolve
//     cross-file names (Tree-sitter alone can't).

import type Parser from "web-tree-sitter";

import type { Edge, Symbol, SymbolKind, TokenRow } from "../store/types";
import { symbolId } from "./identity";

type Tree = Parser.Tree;
type Node = Parser.SyntaxNode;

export interface ExtractResult {
  symbols: Symbol[];
  edges: Edge[];
  tokens: TokenRow[];
}

export interface ExtractOpts {
  filePath: string;
  grammar: "typescript" | "tsx";
  branch: string;
}

export function extractTypeScript(tree: Tree, opts: ExtractOpts): ExtractResult {
  const result: ExtractResult = { symbols: [], edges: [], tokens: [] };
  const fileSym = makeFileSymbol(opts);
  result.symbols.push(fileSym);
  walk(tree.rootNode, fileSym, fileSym.qualified_name, result, opts);
  return result;
}

function makeFileSymbol(opts: ExtractOpts): Symbol {
  return {
    id: symbolId("ts", opts.filePath),
    kind: "file",
    language: "ts",
    qualified_name: opts.filePath,
    short_name: opts.filePath.split("/").pop() ?? opts.filePath,
    file: opts.filePath,
    line: 0,
    col: 0,
    end_line: 0,
    end_col: 0,
    signature: null,
    visibility: null,
    is_abstract: false,
    is_static: false,
    ast_hash: null,
    branch: opts.branch,
    source: "tree_sitter",
  };
}

function walk(
  node: Node,
  parent: Symbol,
  parentQn: string,
  result: ExtractResult,
  opts: ExtractOpts,
): void {
  collectTokens(node, parent.id, opts, result.tokens);

  const decl = recognizeDeclaration(node);
  if (decl) {
    const qn = `${parentQn}::${decl.short}`;
    const sym: Symbol = {
      id: symbolId("ts", qn),
      kind: decl.kind,
      language: "ts",
      qualified_name: qn,
      short_name: decl.short,
      file: opts.filePath,
      line: node.startPosition.row,
      col: node.startPosition.column,
      end_line: node.endPosition.row,
      end_col: node.endPosition.column,
      signature: null,
      visibility: null,
      is_abstract: false,
      is_static: false,
      ast_hash: null,
      branch: opts.branch,
      source: "tree_sitter",
    };
    result.symbols.push(sym);
    result.edges.push({ src_id: parent.id, dst_id: sym.id, kind: "CONTAINS" });
    for (const child of node.namedChildren) {
      if (child) walk(child, sym, qn, result, opts);
    }
    return;
  }

  for (const child of node.namedChildren) {
    if (child) walk(child, parent, parentQn, result, opts);
  }
}

function recognizeDeclaration(node: Node): { kind: SymbolKind; short: string } | null {
  switch (node.type) {
    case "class_declaration":
    case "abstract_class_declaration":
      return nameOf(node, "class");
    case "interface_declaration":
      return nameOf(node, "interface");
    case "enum_declaration":
      return nameOf(node, "enum");
    case "function_declaration":
    case "function_signature":
      return nameOf(node, "function");
    case "method_definition":
    case "method_signature":
    case "abstract_method_signature":
      return nameOf(node, "method");
    case "public_field_definition":
    case "property_signature":
      return nameOf(node, "field");
    case "type_alias_declaration":
      return nameOf(node, "type_alias");
    default:
      return null;
  }
}

function nameOf(node: Node, kind: SymbolKind): { kind: SymbolKind; short: string } | null {
  const name = node.childForFieldName("name");
  if (!name) return null;
  return { kind, short: name.text };
}

function collectTokens(
  node: Node,
  symId: string,
  opts: ExtractOpts,
  out: TokenRow[],
): void {
  switch (node.type) {
    case "identifier":
    case "type_identifier":
    case "property_identifier":
      out.push({
        text: node.text,
        kind: "identifier",
        file: opts.filePath,
        line: node.startPosition.row,
        col: node.startPosition.column,
        symbol_id: symId,
      });
      return;
    case "string_fragment":
      out.push({
        text: node.text,
        kind: "literal",
        file: opts.filePath,
        line: node.startPosition.row,
        col: node.startPosition.column,
        symbol_id: symId,
      });
      return;
    case "comment":
      out.push({
        text: node.text,
        kind: "comment",
        file: opts.filePath,
        line: node.startPosition.row,
        col: node.startPosition.column,
        symbol_id: symId,
      });
      return;
    default:
      return;
  }
}
