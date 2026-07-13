// PHP extractor.
//
// Walks a Tree-sitter PHP tree and emits Symbol/Edge/TokenRow records.
// Phase-1-equivalent scope per docs/design/schema.md, mirroring python.ts:
//   - file, namespace, class/interface/trait/enum, function, method, field
//     symbols.
//   - CONTAINS edges (file -> top-level, class -> member).
//   - Tokens: identifiers (`name`), string contents, comments.
//   - EXTENDS / IMPLEMENTS / IMPORTS and behavior edges deferred to a later
//     resolving pass (the SCIP lane would handle those, as it does for Python).
//
// Tree-sitter PHP note: traits have no dedicated SymbolKind, so a
// `trait_declaration` is recorded as kind='class' (closest analogue). Class
// members use distinct node types (method_declaration, property_declaration)
// rather than reusing function_definition, so `insideClass` is informational.

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

export interface ExtractPhpOpts {
  filePath: string;
  branch: string;
  repo: string;
  repo_commit_sha?: string | null;
  indexed_at?: string | null;
  /** When true, repo_commit_sha is folded into Symbol.id (bead MetaCoding-izn). */
  perCommitIdentity?: boolean;
}

export function extractPhp(tree: Tree, opts: ExtractPhpOpts): ExtractResult {
  const result: ExtractResult = { symbols: [], edges: [], tokens: [] };
  const fileSym = makeFileSymbol(opts);
  result.symbols.push(fileSym);
  walk(tree.rootNode, fileSym, fileSym.qualified_name, /* insideClass */ false, result, opts);
  return result;
}

function makeFileSymbol(opts: ExtractPhpOpts): Symbol {
  return {
    id: symbolId("php", opts.repo, opts.filePath, idScopeSha(opts)),
    kind: "file",
    language: "php",
    repo: opts.repo,
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
    repo_commit_sha: opts.repo_commit_sha ?? null,
    indexed_at: opts.indexed_at ?? null,
  };
}

function walk(
  node: Node,
  parent: Symbol,
  parentQn: string,
  insideClass: boolean,
  result: ExtractResult,
  opts: ExtractPhpOpts,
): void {
  collectTokens(node, parent.id, opts, result.tokens);

  // A `property_declaration` can declare several fields at once
  // (`public int $a, $b;`), so it maps to zero-or-more symbols rather than one.
  if (node.type === "property_declaration") {
    if (insideClass) emitProperties(node, parent, parentQn, result, opts);
    // property bodies carry no further declarations worth descending into.
    return;
  }

  const decl = recognizeDeclaration(node, insideClass);
  if (decl) {
    const qn = `${parentQn}::${decl.short}`;
    const sym: Symbol = {
      id: symbolId("php", opts.repo, qn, idScopeSha(opts)),
      kind: decl.kind,
      language: "php",
      repo: opts.repo,
      qualified_name: qn,
      short_name: decl.short,
      file: opts.filePath,
      line: node.startPosition.row,
      col: node.startPosition.column,
      end_line: node.endPosition.row,
      end_col: node.endPosition.column,
      signature: null,
      visibility: modifierVisibility(node),
      is_abstract: hasChildOfType(node, "abstract_modifier"),
      is_static: hasChildOfType(node, "static_modifier"),
      ast_hash: null,
      branch: opts.branch,
      source: "tree_sitter",
      repo_commit_sha: opts.repo_commit_sha ?? null,
      indexed_at: opts.indexed_at ?? null,
    };
    result.symbols.push(sym);
    result.edges.push({ src_id: parent.id, dst_id: sym.id, kind: "CONTAINS" });
    const childInsideClass =
      decl.kind === "class" || decl.kind === "interface" || decl.kind === "enum";
    for (const child of node.namedChildren) {
      if (child) walk(child, sym, qn, childInsideClass, result, opts);
    }
    return;
  }

  for (const child of node.namedChildren) {
    if (child) walk(child, parent, parentQn, insideClass, result, opts);
  }
}

function recognizeDeclaration(
  node: Node,
  insideClass: boolean,
): { kind: SymbolKind; short: string } | null {
  switch (node.type) {
    case "namespace_definition": {
      const name = node.childForFieldName("name");
      // Bodyless `namespace App\Foo;` still names a scope worth recording.
      if (!name) return null;
      return { kind: "namespace", short: name.text };
    }
    case "class_declaration":
    // Traits have no dedicated SymbolKind; treat as a class (closest match).
    case "trait_declaration": {
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: "class", short: name.text };
    }
    case "interface_declaration": {
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: "interface", short: name.text };
    }
    case "enum_declaration": {
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: "enum", short: name.text };
    }
    case "function_definition": {
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: "function", short: name.text };
    }
    case "method_declaration": {
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: "method", short: name.text };
    }
    case "enum_case": {
      if (!insideClass) return null;
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: "field", short: name.text };
    }
    default:
      return null;
  }
}

// `property_declaration` → one `field` Symbol per declared `property_element`.
function emitProperties(
  node: Node,
  parent: Symbol,
  parentQn: string,
  result: ExtractResult,
  opts: ExtractPhpOpts,
): void {
  const visibility = modifierVisibility(node);
  const isStatic = hasChildOfType(node, "static_modifier");
  for (const el of node.namedChildren) {
    if (!el || el.type !== "property_element") continue;
    const varNode = el.namedChildren.find((c) => c && c.type === "variable_name");
    if (!varNode) continue;
    const short = varNode.text.replace(/^\$/, "");
    if (!short) continue;
    const qn = `${parentQn}::${short}`;
    result.symbols.push({
      id: symbolId("php", opts.repo, qn, idScopeSha(opts)),
      kind: "field",
      language: "php",
      repo: opts.repo,
      qualified_name: qn,
      short_name: short,
      file: opts.filePath,
      line: el.startPosition.row,
      col: el.startPosition.column,
      end_line: el.endPosition.row,
      end_col: el.endPosition.column,
      signature: null,
      visibility,
      is_abstract: false,
      is_static: isStatic,
      ast_hash: null,
      branch: opts.branch,
      source: "tree_sitter",
      repo_commit_sha: opts.repo_commit_sha ?? null,
      indexed_at: opts.indexed_at ?? null,
    });
    result.edges.push({ src_id: parent.id, dst_id: result.symbols[result.symbols.length - 1]!.id, kind: "CONTAINS" });
  }
}

function modifierVisibility(node: Node): "public" | "private" | "protected" {
  for (const child of node.namedChildren) {
    if (child && child.type === "visibility_modifier") {
      const t = child.text;
      if (t === "private" || t === "protected") return t;
      return "public";
    }
  }
  return "public";
}

function hasChildOfType(node: Node, type: string): boolean {
  for (const child of node.namedChildren) {
    if (child && child.type === type) return true;
  }
  return false;
}

function idScopeSha(opts: ExtractPhpOpts): string | undefined {
  return opts.perCommitIdentity ? opts.repo_commit_sha ?? undefined : undefined;
}

function collectTokens(
  node: Node,
  symId: string,
  opts: ExtractPhpOpts,
  out: TokenRow[],
): void {
  const baseRow = {
    file: opts.filePath,
    repo: opts.repo,
    line: node.startPosition.row,
    col: node.startPosition.column,
    symbol_id: symId,
  };
  switch (node.type) {
    case "name":
      out.push({ ...baseRow, text: node.text, kind: "identifier" });
      return;
    case "string_content":
      out.push({ ...baseRow, text: node.text, kind: "literal" });
      return;
    case "comment":
      out.push({ ...baseRow, text: node.text, kind: "comment" });
      return;
    default:
      return;
  }
}
