// Python extractor.
//
// Walks a Tree-sitter Python tree and emits Symbol/Edge/TokenRow records.
// Phase-1-equivalent scope per docs/design/schema.md:
//   - file, class, function, method symbols.
//   - CONTAINS edges (file -> top-level, class -> method).
//   - Tokens: identifiers, string contents, comments.
//   - EXTENDS / IMPORTS edges deferred to a later pass that resolves
//     names cross-file (the SCIP lane handles those for Python).

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

export interface ExtractPyOpts {
  filePath: string;
  branch: string;
  repo: string;
  repo_commit_sha?: string | null;
  indexed_at?: string | null;
  /** When true, repo_commit_sha is folded into Symbol.id (bead MetaCoding-izn). */
  perCommitIdentity?: boolean;
}

export function extractPython(tree: Tree, opts: ExtractPyOpts): ExtractResult {
  const result: ExtractResult = { symbols: [], edges: [], tokens: [] };
  const fileSym = makeFileSymbol(opts);
  result.symbols.push(fileSym);
  walk(tree.rootNode, fileSym, fileSym.qualified_name, /* insideClass */ false, result, opts);
  return result;
}

function makeFileSymbol(opts: ExtractPyOpts): Symbol {
  return {
    id: symbolId("py", opts.repo, opts.filePath, idScopeSha(opts)),
    kind: "file",
    language: "py",
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
  opts: ExtractPyOpts,
): void {
  collectTokens(node, parent.id, opts, result.tokens);

  // `decorated_definition` wraps a class_definition or function_definition.
  // We descend to the wrapped `definition` field and treat it as the actual
  // declaration site, so the symbol's range covers the decorators too.
  let target = node;
  if (node.type === "decorated_definition") {
    const inner = node.childForFieldName("definition");
    if (inner) target = inner;
  }

  const decl = recognizeDeclaration(target, insideClass);
  if (decl) {
    const qn = `${parentQn}::${decl.short}`;
    const sym: Symbol = {
      id: symbolId("py", opts.repo, qn, idScopeSha(opts)),
      kind: decl.kind,
      language: "py",
      repo: opts.repo,
      qualified_name: qn,
      short_name: decl.short,
      file: opts.filePath,
      line: node.startPosition.row,
      col: node.startPosition.column,
      end_line: node.endPosition.row,
      end_col: node.endPosition.column,
      signature: null,
      visibility: decl.short.startsWith("_") && !decl.short.startsWith("__")
        ? "private"
        : decl.short.startsWith("__") && !decl.short.endsWith("__")
        ? "private"
        : "public",
      is_abstract: false,
      is_static: false,
      ast_hash: null,
      branch: opts.branch,
      source: "tree_sitter",
      repo_commit_sha: opts.repo_commit_sha ?? null,
      indexed_at: opts.indexed_at ?? null,
    };
    result.symbols.push(sym);
    result.edges.push({ src_id: parent.id, dst_id: sym.id, kind: "CONTAINS" });
    const childInsideClass = decl.kind === "class";
    for (const child of target.namedChildren) {
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
    case "class_definition": {
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: "class", short: name.text };
    }
    case "function_definition":
    case "async_function_definition": {
      const name = node.childForFieldName("name");
      if (!name) return null;
      return { kind: insideClass ? "method" : "function", short: name.text };
    }
    // Class-level annotated assignments are field declarations
    // (bead MetaCoding-3s5: gives WRITES_FIELD a target to resolve).
    // Pattern shape: `name: type = value` directly inside a class block.
    // Tree-sitter exposes this as an `assignment` node whose `left` is an
    // identifier AND there's a `type` field present.  We only recognise it
    // when insideClass is true; module-level assignments aren't fields.
    case "assignment": {
      if (!insideClass) return null;
      const left = node.childForFieldName("left");
      if (!left || left.type !== "identifier") return null;
      const type = node.childForFieldName("type");
      if (!type) return null;
      return { kind: "field", short: left.text };
    }
    default:
      return null;
  }
}

function idScopeSha(opts: ExtractPyOpts): string | undefined {
  return opts.perCommitIdentity ? opts.repo_commit_sha ?? undefined : undefined;
}

function collectTokens(
  node: Node,
  symId: string,
  opts: ExtractPyOpts,
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
    case "identifier":
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
