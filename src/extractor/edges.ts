// Tree-sitter behavior-edge extraction.
//
// Emits WRITES_FIELD, CONSTRUCTS, RETURNS_TYPE, READS_FIELD, TYPE_OF,
// RAISES, and ANNOTATES (decorator application) edges.
//
// MetaCoding-3s5: initial WRITES_FIELD, CONSTRUCTS, RETURNS_TYPE pass.
// MetaCoding-9le: READS_FIELD (member-access reads in TS + Python) and
//   TYPE_OF on field declarations (annotated class fields in TS + Python).
//
// These are the high-leverage edges that the SCIP loader cannot reliably
// deliver (SCIP indexers in practice emit only ReadAccess on field
// occurrences, no WriteAccess; no is_type_definition on callable returns;
// no explicit constructor-call distinction).
//
// Pipeline shape:
//   1. Per-file: walk the parsed Tree, recognise candidate patterns, push
//      an EdgeCandidate (src is the enclosing function/method/class symbol id;
//      target is a deferred name spec).
//   2. End-of-directory: resolve targets against the in-memory symbol index
//      built by the walker. Drop dangling refs silently.
//
// We don't use tree-sitter Query strings — the existing extractor walks
// node-by-node and that pattern stays here for consistency and to avoid
// the runtime cost of compiling queries per file.

import type Parser from "web-tree-sitter";

import type { EdgeKind, Symbol, SymbolKind } from "../store/types";

type Node = Parser.SyntaxNode;
type Tree = Parser.Tree;

/**
 * A candidate edge whose source is a fully-resolved Symbol id (the enclosing
 * function/method/class extracted from the same Tree pass) and whose target is
 * a deferred lookup keyed on (kind, shortName).
 *
 * Targets are resolved at the end of an indexDirectory() pass against an
 * in-memory `(repo, kind, shortName) -> Symbol.id` index. If no symbol
 * matches, the candidate is dropped — no dangling edges in the graph.
 */
export interface EdgeCandidate {
  kind: EdgeKind;
  src_id: string;
  /** Target match spec. */
  target: TargetSpec;
}

export interface TargetSpec {
  /**
   * Acceptable symbol kinds for the target.  Resolver tries each in order
   * and picks the first match. e.g. CONSTRUCTS may match either a class
   * (Python `Foo(...)` resolves to class) or a method (`__init__`).
   */
  kinds: SymbolKind[];
  /** The short identifier to look up. */
  shortName: string;
  /**
   * Optional: when present, prefer a target whose qualified_name ENDS with
   * this scope hint. Used for `this.field` to prefer fields in the same
   * enclosing class.
   */
  scopeQn?: string;
  /**
   * When true and the target does not resolve to an in-repo symbol, the edge
   * is kept by pointing at a synthesized boundary node keyed on shortName
   * (language "external"). Used for PHP EXTENDS/IMPLEMENTS/USES_TRAIT so that a
   * base class defined outside the repo (e.g. Drupal's ContentEntityBase) still
   * appears as a shared target — the role signal lives in the name, not the
   * resolved file. bead MetaCoding-1xd.
   */
  externalFallback?: boolean;
}

export interface EdgePassOpts {
  /** Language code: "ts", "py", or "php". */
  language: "ts" | "py" | "php";
  /** File path (relative to repo root) — used for diagnostics only. */
  filePath: string;
  /**
   * Symbols emitted for this file by the main extractor pass, in the order
   * they were emitted. We walk these once to build a per-file index and to
   * find each candidate's enclosing scope by position.
   */
  symbols: Symbol[];
}

export interface EdgePassResult {
  candidates: EdgeCandidate[];
}

/**
 * Walk a parsed Tree and emit edge candidates for the given language.
 * Pure: doesn't touch the store. Resolution happens later.
 */
export function extractEdgeCandidates(
  tree: Tree,
  opts: EdgePassOpts,
): EdgePassResult {
  const candidates: EdgeCandidate[] = [];
  const scopes = buildScopeIndex(opts.symbols);
  if (opts.language === "ts") {
    walkTs(tree.rootNode, scopes, candidates);
  } else if (opts.language === "php") {
    walkPhp(tree.rootNode, scopes, candidates);
  } else {
    walkPy(tree.rootNode, scopes, candidates);
  }
  return { candidates };
}

// ---------------------------------------------------------------------------
// Scope index: for each Symbol with a position-bearing kind, expose its id
// keyed by its byte range. We resolve a candidate's enclosing scope by
// finding the smallest containing range.
// ---------------------------------------------------------------------------

interface ScopeEntry {
  id: string;
  kind: SymbolKind;
  qualifiedName: string;
  startLine: number;
  startCol: number;
  endLine: number;
  endCol: number;
  /** Area in line-column units, for sorting "innermost wins". */
  area: number;
}

interface ScopeIndex {
  /** All scopes sorted by area ascending (innermost first). */
  scopes: ScopeEntry[];
  /** Quick lookup `shortName -> ScopeEntry[]` for field/parameter resolution. */
  byShortName: Map<string, ScopeEntry[]>;
}

function buildScopeIndex(symbols: Symbol[]): ScopeIndex {
  const scopes: ScopeEntry[] = [];
  const byShortName = new Map<string, ScopeEntry[]>();
  for (const s of symbols) {
    if (s.kind === "file") continue;
    const e: ScopeEntry = {
      id: s.id,
      kind: s.kind,
      qualifiedName: s.qualified_name,
      startLine: s.line,
      startCol: s.col,
      endLine: s.end_line,
      endCol: s.end_col,
      area: (s.end_line - s.line) * 1_000_000 + (s.end_col - s.col),
    };
    scopes.push(e);
    const bucket = byShortName.get(s.short_name);
    if (bucket) bucket.push(e);
    else byShortName.set(s.short_name, [e]);
  }
  scopes.sort((a, b) => a.area - b.area);
  return { scopes, byShortName };
}

/**
 * Find the innermost function/method/class scope containing a position.
 * Returns null when no enclosing scope is known (e.g. the position is at
 * the file top level — we don't emit edges from "file" sources).
 */
function findEnclosingScope(
  scopes: ScopeIndex,
  line: number,
  col: number,
  acceptKinds: SymbolKind[],
): ScopeEntry | null {
  for (const s of scopes.scopes) {
    if (!acceptKinds.includes(s.kind)) continue;
    if (rangeContains(s, line, col)) return s;
  }
  return null;
}

function rangeContains(s: ScopeEntry, line: number, col: number): boolean {
  if (line < s.startLine) return false;
  if (line === s.startLine && col < s.startCol) return false;
  if (line > s.endLine) return false;
  if (line === s.endLine && col > s.endCol) return false;
  return true;
}

/**
 * Find the innermost class scope containing a position. Used by
 * `this.field`/`self.attr` resolution to disambiguate fields by class.
 */
function findEnclosingClass(scopes: ScopeIndex, line: number, col: number): ScopeEntry | null {
  return findEnclosingScope(scopes, line, col, ["class", "interface"]);
}

const CALLABLE_KINDS: SymbolKind[] = ["function", "method"];

// ---------------------------------------------------------------------------
// TypeScript walk
// ---------------------------------------------------------------------------

function walkTs(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  switch (node.type) {
    case "assignment_expression": {
      tsHandleAssignment(node, scopes, out);
      break;
    }
    case "augmented_assignment_expression": {
      // `this.x += 1` — both read and write; emit WRITES_FIELD (and READS_FIELD
      // below since it's also a read).
      tsHandleAssignment(node, scopes, out);
      tsHandleReadsField(node, scopes, out, /* isAugmented */ true);
      break;
    }
    case "new_expression": {
      tsHandleNew(node, scopes, out);
      break;
    }
    case "function_declaration":
    case "method_definition":
    case "function_signature":
    case "method_signature":
    case "abstract_method_signature":
    case "arrow_function":
    case "function_expression": {
      tsHandleReturnType(node, scopes, out);
      break;
    }
    case "throw_statement": {
      tsHandleThrow(node, scopes, out);
      break;
    }
    case "member_expression": {
      // Emit READS_FIELD for every member-expression that is NOT the direct LHS
      // of a plain assignment (augmented assignments are both read and write,
      // handled above).
      tsHandleReadsField(node, scopes, out, /* isAugmented */ false);
      break;
    }
    case "property_signature":
    case "public_field_definition": {
      // `field: SomeType;` in a class/interface body — emit TYPE_OF.
      tsHandleFieldTypeOf(node, scopes, out);
      break;
    }
    case "decorator": {
      // `@Foo` or `@Foo()` on a class/method — emit ANNOTATES.
      tsHandleDecorator(node, scopes, out);
      break;
    }
  }
  for (const child of node.namedChildren) {
    if (child) walkTs(child, scopes, out);
  }
}

function tsHandleAssignment(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  const left = node.childForFieldName("left");
  if (!left) return;
  // We care about `obj.field = X` and `this.field = X` only.
  // (Plain identifier writes don't target a field symbol.)
  if (left.type !== "member_expression") return;
  const object = left.childForFieldName("object");
  const property = left.childForFieldName("property");
  if (!object || !property) return;
  if (property.type !== "property_identifier") return;
  const shortName = property.text;
  if (!shortName) return;

  // Find enclosing function/method.
  const src = findEnclosingScope(
    scopes,
    left.startPosition.row,
    left.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;

  // Scope hint: if the receiver is `this`, prefer fields in the enclosing
  // class. Otherwise leave it open and let the resolver match any class.
  const isThis = object.type === "this";
  const cls = isThis
    ? findEnclosingClass(scopes, left.startPosition.row, left.startPosition.column)
    : null;
  out.push({
    kind: "WRITES_FIELD",
    src_id: src.id,
    target: {
      kinds: ["field"],
      shortName,
      scopeQn: cls?.qualifiedName,
    },
  });
}

function tsHandleNew(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  const constructor = node.childForFieldName("constructor");
  if (!constructor) return;
  // `new Foo()` → constructor is identifier "Foo".
  // `new ns.Foo()` → member_expression; take the property as the short name and
  //   the object as a namespace/qualifier hint so the resolver can disambiguate
  //   two classes that share a short_name in different namespaces (bead
  //   MetaCoding-gc5 #4). Without the qualifier the edge target is just "Foo",
  //   which resolves non-deterministically when multiple `Foo`s exist.
  // `new ns.sub.Foo()` → nested member_expression; the innermost object segment
  //   is the most specific namespace hint available.
  // `new Foo<T>()` → identifier "Foo".
  let shortName: string | null = null;
  let scopeQn: string | undefined;
  if (constructor.type === "identifier") {
    shortName = constructor.text;
  } else if (constructor.type === "member_expression") {
    const prop = constructor.childForFieldName("property");
    if (prop?.type === "property_identifier") shortName = prop.text;
    // Use the immediate object segment as a namespace qualifier hint. For
    // `ns.Foo` the object is identifier "ns"; for `a.b.Foo` it is a nested
    // member_expression whose trailing property ("b") is the closest qualifier.
    const obj = constructor.childForFieldName("object");
    if (obj?.type === "identifier") {
      scopeQn = obj.text;
    } else if (obj?.type === "member_expression") {
      const objProp = obj.childForFieldName("property");
      if (objProp?.type === "property_identifier") scopeQn = objProp.text;
    }
  }
  if (!shortName) return;

  const src = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;
  out.push({
    kind: "CONSTRUCTS",
    src_id: src.id,
    target: { kinds: ["class", "interface"], shortName, scopeQn },
  });
}

function tsHandleThrow(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // `throw new Error(...)` → new_expression with constructor "Error".
  // `throw expr` where expr is an identifier → re-throw of a caught variable (skip).
  // We only emit RAISES for `throw new X(...)` — the constructor name is the type.
  const expr = node.namedChildren[0];
  if (!expr) return;
  let shortName: string | null = null;
  if (expr.type === "new_expression") {
    const ctor = expr.childForFieldName("constructor");
    if (ctor?.type === "identifier") {
      shortName = ctor.text;
    } else if (ctor?.type === "member_expression") {
      const prop = ctor.childForFieldName("property");
      if (prop?.type === "property_identifier") shortName = prop.text;
    }
  } else if (expr.type === "identifier") {
    // `throw X` — bare identifier throw (e.g. `throw myError`). Skip: not a type.
    return;
  } else if (expr.type === "call_expression") {
    // `throw Error(...)` — call without `new` (common in JS).
    const fn = expr.childForFieldName("function");
    if (fn?.type === "identifier") {
      shortName = fn.text;
    } else if (fn?.type === "member_expression") {
      const prop = fn.childForFieldName("property");
      if (prop?.type === "property_identifier") shortName = prop.text;
    }
  }
  if (!shortName) return;

  const src = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;
  out.push({
    kind: "RAISES",
    src_id: src.id,
    target: { kinds: ["class", "interface", "type_alias"], shortName },
  });
}

function tsHandleReturnType(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // Tree-sitter TS surfaces return type via field name "return_type".
  const rt = node.childForFieldName("return_type");
  if (!rt) return;
  // `return_type` is a `type_annotation` whose child is the actual type node.
  // We want simple references (`Foo`, `ns.Foo`, `Foo<T>`).
  const named = collectTypeReferences(rt);
  if (named.length === 0) return;

  const src = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;
  for (const name of named) {
    out.push({
      kind: "RETURNS_TYPE",
      src_id: src.id,
      target: { kinds: ["class", "interface", "type_alias", "enum"], shortName: name },
    });
  }
}

/**
 * Emit READS_FIELD for a member_expression that is a read access.
 *
 * Called in two modes:
 *  - isAugmented=false: node is a `member_expression`. We emit unless it is
 *    the direct `left` child of a plain `assignment_expression`.
 *  - isAugmented=true: node is an `augmented_assignment_expression` and its
 *    `left` is a member_expression. Augmented assignments are both read and
 *    write, so we always emit READS_FIELD here (WRITES_FIELD is emitted by
 *    tsHandleAssignment).
 */
function tsHandleReadsField(
  node: Node,
  scopes: ScopeIndex,
  out: EdgeCandidate[],
  isAugmented: boolean,
): void {
  let memberNode: Node;
  if (isAugmented) {
    // node is `augmented_assignment_expression`; extract the `left` member.
    const left = node.childForFieldName("left");
    if (!left || left.type !== "member_expression") return;
    memberNode = left;
  } else {
    // node IS the member_expression. Skip if it's the LHS of a plain assignment.
    memberNode = node;
    const parent = node.parent;
    if (parent?.type === "assignment_expression") {
      const left = parent.childForFieldName("left");
      // tree-sitter creates fresh wrapper objects per call — compare by position.
      if (
        left &&
        left.startPosition.row === node.startPosition.row &&
        left.startPosition.column === node.startPosition.column
      ) {
        return;
      }
    }
  }

  const object = memberNode.childForFieldName("object");
  const property = memberNode.childForFieldName("property");
  if (!object || !property) return;
  if (property.type !== "property_identifier") return;
  const shortName = property.text;
  if (!shortName) return;

  const src = findEnclosingScope(
    scopes,
    memberNode.startPosition.row,
    memberNode.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;

  const isThis = object.type === "this";
  const cls = isThis
    ? findEnclosingClass(scopes, memberNode.startPosition.row, memberNode.startPosition.column)
    : null;

  out.push({
    kind: "READS_FIELD",
    src_id: src.id,
    target: { kinds: ["field"], shortName, scopeQn: cls?.qualifiedName },
  });
}

/**
 * Emit ANNOTATES for a TS decorator (`@Foo` or `@Foo()`).
 *
 * The decorator node is a child of the decorated declaration. We find the
 * decorated symbol (the next sibling declaration) by looking at the parent
 * and finding the enclosing class/method/function scope that contains this
 * position.
 */
function tsHandleDecorator(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // The decorator's value is accessed via the first named child.
  // `@Foo` → child is `identifier` "Foo"
  // `@Foo()` → child is `call_expression` whose `function` is "Foo"
  // `@ns.Foo` → child is `member_expression`
  const child = node.namedChildren[0];
  if (!child) return;
  let shortName: string | null = null;
  if (child.type === "identifier") {
    shortName = child.text;
  } else if (child.type === "call_expression") {
    const fn = child.childForFieldName("function");
    if (fn?.type === "identifier") shortName = fn.text;
    else if (fn?.type === "member_expression") {
      const prop = fn.childForFieldName("property");
      if (prop?.type === "property_identifier") shortName = prop.text;
    }
  } else if (child.type === "member_expression") {
    const prop = child.childForFieldName("property");
    if (prop?.type === "property_identifier") shortName = prop.text;
  }
  if (!shortName) return;

  // The decorated symbol is the parent declaration. The decorator is a child
  // of the declaration node, so find the innermost scope at the decorator's
  // position — that's the decorated symbol itself (class or method).
  // But the decorator is INSIDE the declaration, so findEnclosingScope will
  // return the declaration. We want the decorator to point TO the decorated
  // symbol, so: src = decorator function, dst = decorated symbol.
  // Edge semantics: decorator ANNOTATES decorated_symbol.
  // We emit the candidate with src = decorator name (resolved as function/class)
  // and dst = the enclosing scope (the decorated class/method).
  const decorated = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    ["class", "interface", "method", "function"],
  );
  if (!decorated) return;

  out.push({
    kind: "ANNOTATES",
    src_id: decorated.id,  // We can't resolve the decorator to a symbol id yet,
    // so we flip: the decorated symbol is the src (known), and the decorator
    // name is the target (resolved later). This means the edge direction is
    // decorated → decorator. Semantics: "symbol is annotated by decorator".
    // Both directions carry entropy; this is consistent with how SCIP would
    // surface it (the decoration is a reference from the decorated site).
    // externalFallback: imported/framework decorators (@Component, @Injectable)
    // won't resolve to repo-local symbols — emit a boundary node so the edge
    // is preserved. bead MetaCoding-mhv.
    target: { kinds: ["function", "class"], shortName, externalFallback: true },
  });
}

/**
 * Emit TYPE_OF from a field symbol to its annotated type for TS class/interface
 * field declarations (`public_field_definition` and `property_signature`).
 *
 * The field symbol was emitted by the main extractor; we locate it by position
 * via the scope index (fields are ScopeEntries with kind "field").
 */
function tsHandleFieldTypeOf(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // Both `public_field_definition` and `property_signature` expose the type
  // via field name "type" — a `type_annotation` node.
  const typeNode = node.childForFieldName("type");
  if (!typeNode) return;

  const names = collectTypeReferences(typeNode);
  if (names.length === 0) return;

  // Find the field symbol itself. Fields have a `name` field node.
  const nameNode = node.childForFieldName("name");
  if (!nameNode) return;

  // Look up the field in the scope index by short_name and position.
  // We find the innermost field-kind scope that starts at or near this node.
  const line = node.startPosition.row;
  const col = node.startPosition.column;
  const shortName = nameNode.text;
  if (!shortName) return;

  // Locate the field symbol: it should be a scope entry with kind "field"
  // whose short name matches and whose range contains the node position.
  const bucket = scopes.byShortName.get(shortName);
  if (!bucket) return;
  const fieldEntry = bucket.find(
    (e) => e.kind === "field" && rangeContains(e, line, col),
  );
  if (!fieldEntry) return;

  for (const name of names) {
    out.push({
      kind: "TYPE_OF",
      src_id: fieldEntry.id,
      target: { kinds: ["class", "interface", "type_alias", "enum"], shortName: name },
    });
  }
}

/**
 * Walk a TS type-annotation subtree and pull out type identifier names.
 * Skips primitives like `string` / `number` (they don't resolve to a symbol).
 */
function collectTypeReferences(node: Node): string[] {
  const found: string[] = [];
  const PRIMITIVES = new Set([
    "string", "number", "boolean", "void", "any", "unknown", "never",
    "null", "undefined", "object", "symbol", "bigint",
  ]);
  const visit = (n: Node): void => {
    if (n.type === "type_identifier") {
      const t = n.text;
      if (t && !PRIMITIVES.has(t)) found.push(t);
      return;
    }
    if (n.type === "nested_type_identifier") {
      // ns.Foo → take the final identifier.
      const last = n.namedChildren[n.namedChildren.length - 1];
      if (last?.type === "type_identifier") {
        const t = last.text;
        if (t && !PRIMITIVES.has(t)) found.push(t);
      }
      return;
    }
    for (const c of n.namedChildren) {
      if (c) visit(c);
    }
  };
  visit(node);
  return found;
}

// ---------------------------------------------------------------------------
// Python walk
// ---------------------------------------------------------------------------

function walkPy(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  switch (node.type) {
    case "assignment": {
      // WRITES_FIELD for `self.attr = X` assignments.
      pyHandleAssignment(node, scopes, out);
      // TYPE_OF for class-level annotated field declarations (`field: Type [= val]`).
      pyHandleFieldTypeOf(node, scopes, out);
      break;
    }
    case "augmented_assignment": {
      // `self.x += 1` — both read and write.
      pyHandleAssignment(node, scopes, out);
      pyHandleReadsField(node, scopes, out, /* isAugmented */ true);
      break;
    }
    case "call": {
      pyHandleCall(node, scopes, out);
      break;
    }
    case "function_definition":
    case "async_function_definition": {
      pyHandleReturnType(node, scopes, out);
      break;
    }
    case "raise_statement": {
      pyHandleRaise(node, scopes, out);
      break;
    }
    case "decorated_definition": {
      pyHandleDecorators(node, scopes, out);
      break;
    }
    case "attribute": {
      // Emit READS_FIELD for every `self.attr` / `cls.attr` read access that
      // is NOT the direct LHS of a plain assignment (augmented handled above).
      pyHandleReadsField(node, scopes, out, /* isAugmented */ false);
      break;
    }
  }
  for (const child of node.namedChildren) {
    if (child) walkPy(child, scopes, out);
  }
}

function pyHandleAssignment(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  const left = node.childForFieldName("left");
  if (!left) return;
  // `self.attr = X`, `obj.attr = X` — LHS is `attribute`.
  if (left.type !== "attribute") return;
  const object = left.childForFieldName("object");
  const attribute = left.childForFieldName("attribute");
  if (!object || !attribute) return;
  if (attribute.type !== "identifier") return;
  const shortName = attribute.text;
  if (!shortName) return;

  const src = findEnclosingScope(
    scopes,
    left.startPosition.row,
    left.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;

  // Heuristic: if receiver is `self` or `cls`, prefer the enclosing class.
  const isSelf = object.type === "identifier" && (object.text === "self" || object.text === "cls");
  const cls = isSelf
    ? findEnclosingClass(scopes, left.startPosition.row, left.startPosition.column)
    : null;
  out.push({
    kind: "WRITES_FIELD",
    src_id: src.id,
    target: { kinds: ["field"], shortName, scopeQn: cls?.qualifiedName },
  });
}

function pyHandleCall(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // Python uses plain call syntax for construction: `Foo(...)`.
  // Heuristic: callee identifier starting with uppercase is treated as a
  // class candidate. The resolver further filters to symbols whose kind
  // is `class`.
  const fn = node.childForFieldName("function");
  if (!fn) return;
  let shortName: string | null = null;
  if (fn.type === "identifier") {
    shortName = fn.text;
  } else if (fn.type === "attribute") {
    const attr = fn.childForFieldName("attribute");
    if (attr?.type === "identifier") shortName = attr.text;
  }
  if (!shortName) return;
  if (!/^[A-Z]/.test(shortName)) return;  // skip lowercase callables
  // Skip well-known stdlib factories that LOOK class-like but won't resolve.
  if (BUILTIN_TYPES.has(shortName)) return;

  const src = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;
  out.push({
    kind: "CONSTRUCTS",
    src_id: src.id,
    target: { kinds: ["class"], shortName },
  });
}

const BUILTIN_TYPES = new Set([
  "True", "False", "None",
  // stdlib exceptions
  "Exception", "ValueError", "TypeError", "KeyError", "AttributeError",
  "RuntimeError", "IOError", "OSError", "StopIteration", "NotImplementedError",
  "ImportError", "FileNotFoundError", "IndexError", "ZeroDivisionError",
  "ArithmeticError", "AssertionError", "LookupError", "NameError",
  "OverflowError", "PermissionError", "TimeoutError",
  // stdlib type constructors / common factories (not user classes)
  "Path",            // pathlib.Path
  "Enum", "IntEnum", "Flag", "IntFlag", "StrEnum",
  "TypedDict", "NamedTuple", "Generic", "Protocol",
  "Decimal", "Fraction",
  "Lock", "RLock", "Thread", "Event", "Condition", "Semaphore",
  "Pool", "Process", "Queue", "Manager",
  // collections module factories — stdlib, not user classes
  "Counter", "OrderedDict", "defaultdict", "deque", "ChainMap",
  // pydantic / dataclass-style framework primitives common in many repos
  "BaseModel", "Field", "dataclass",
]);

/**
 * Emit ANNOTATES edges for Python decorators on a `decorated_definition`.
 *
 * A `decorated_definition` has `decorator` children and a `definition` child.
 * Each `decorator` has a child that is the decorator expression:
 *   `@foo` → identifier "foo"
 *   `@foo()` → call whose function is "foo"
 *   `@mod.foo` → attribute whose attribute is "foo"
 */
function pyHandleDecorators(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // Find the decorated symbol: it's the `definition` child (function_definition
  // or class_definition), which should already be in the scope index.
  const defNode = node.childForFieldName("definition");
  if (!defNode) return;

  // The decorated symbol position is the decorated_definition's position
  // (since the python.ts extractor uses node.startPosition which includes decorators).
  const decorated = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    ["class", "method", "function"],
  );
  if (!decorated) return;

  // Iterate over decorator children.
  for (const child of node.namedChildren) {
    if (child.type !== "decorator") continue;
    const expr = child.namedChildren[0];
    if (!expr) continue;
    let shortName: string | null = null;
    if (expr.type === "identifier") {
      shortName = expr.text;
    } else if (expr.type === "call") {
      const fn = expr.childForFieldName("function");
      if (fn?.type === "identifier") shortName = fn.text;
      else if (fn?.type === "attribute") {
        const attr = fn.childForFieldName("attribute");
        if (attr?.type === "identifier") shortName = attr.text;
      }
    } else if (expr.type === "attribute") {
      const attr = expr.childForFieldName("attribute");
      if (attr?.type === "identifier") shortName = attr.text;
    }
    if (!shortName) continue;

    out.push({
      kind: "ANNOTATES",
      src_id: decorated.id,
      // externalFallback: imported/framework decorators (@dataclass,
      // @pytest.fixture, @app.route) won't resolve to repo-local symbols —
      // emit a boundary node so the edge is preserved. bead MetaCoding-mhv.
      target: { kinds: ["function", "class"], shortName, externalFallback: true },
    });
  }
}

function pyHandleRaise(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // `raise X(...)` → the first named child is a `call` whose `function` is the type.
  // `raise X` → the first named child is an `identifier` (bare re-raise of variable → skip).
  // `raise` (no argument) → re-raise in except block → skip.
  const expr = node.namedChildren[0];
  if (!expr) return;
  let shortName: string | null = null;
  if (expr.type === "call") {
    const fn = expr.childForFieldName("function");
    if (fn?.type === "identifier") {
      shortName = fn.text;
    } else if (fn?.type === "attribute") {
      const attr = fn.childForFieldName("attribute");
      if (attr?.type === "identifier") shortName = attr.text;
    }
  }
  // `raise X` where X is an identifier — could be a class or a variable.
  // We emit only when it looks like a class (uppercase) to match CONSTRUCTS heuristic.
  if (!shortName && expr.type === "identifier" && /^[A-Z]/.test(expr.text)) {
    shortName = expr.text;
  }
  if (!shortName) return;

  const src = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;
  out.push({
    kind: "RAISES",
    src_id: src.id,
    target: { kinds: ["class"], shortName },
  });
}

function pyHandleReturnType(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // tree-sitter-python exposes return type via field name "return_type"
  // (its child is a `type` node whose child is the actual annotation).
  const rt = node.childForFieldName("return_type");
  if (!rt) return;
  const names = collectPyTypeReferences(rt);
  if (names.length === 0) return;

  const src = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;
  for (const name of names) {
    out.push({
      kind: "RETURNS_TYPE",
      src_id: src.id,
      target: { kinds: ["class", "type_alias"], shortName: name },
    });
  }
}

/**
 * Emit READS_FIELD for a Python `self.attr` / `cls.attr` read access.
 *
 * Called in two modes:
 *  - isAugmented=false: node is an `attribute` node. We skip if it's the
 *    direct `left` of a plain `assignment`.
 *  - isAugmented=true: node is an `augmented_assignment`; extract its `left`.
 */
function pyHandleReadsField(
  node: Node,
  scopes: ScopeIndex,
  out: EdgeCandidate[],
  isAugmented: boolean,
): void {
  let attrNode: Node;
  if (isAugmented) {
    const left = node.childForFieldName("left");
    if (!left || left.type !== "attribute") return;
    attrNode = left;
  } else {
    // node IS the attribute node. Skip if it's the LHS of a plain assignment.
    attrNode = node;
    const parent = node.parent;
    if (parent?.type === "assignment") {
      const left = parent.childForFieldName("left");
      // tree-sitter creates fresh wrapper objects per call — compare by position.
      if (
        left &&
        left.startPosition.row === node.startPosition.row &&
        left.startPosition.column === node.startPosition.column
      ) {
        return;
      }
    }
  }

  const object = attrNode.childForFieldName("object");
  const attribute = attrNode.childForFieldName("attribute");
  if (!object || !attribute) return;
  if (attribute.type !== "identifier") return;

  // Only emit for `self` / `cls` receivers.
  if (object.type !== "identifier") return;
  if (object.text !== "self" && object.text !== "cls") return;

  const shortName = attribute.text;
  if (!shortName) return;

  const src = findEnclosingScope(
    scopes,
    attrNode.startPosition.row,
    attrNode.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;

  const cls = findEnclosingClass(
    scopes,
    attrNode.startPosition.row,
    attrNode.startPosition.column,
  );

  out.push({
    kind: "READS_FIELD",
    src_id: src.id,
    target: { kinds: ["field"], shortName, scopeQn: cls?.qualifiedName },
  });
}

/**
 * Emit TYPE_OF from a Python class field symbol to its annotated type.
 *
 * tree-sitter-python represents `field: Type [= val]` inside a class body as
 * an `assignment` node (with a `type` field) wrapped in `expression_statement`
 * inside a `block` inside `class_definition`. We only emit when the enclosing
 * structure matches that pattern, so module-level annotated assignments are
 * ignored.
 */
function pyHandleFieldTypeOf(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // Must have a `type` field — distinguishes annotated from plain assignments.
  const typeNode = node.childForFieldName("type");
  if (!typeNode) return;

  // Parent chain: assignment → expression_statement → block → class_definition.
  const stmtNode = node.parent;
  if (!stmtNode || stmtNode.type !== "expression_statement") return;
  const blockNode = stmtNode.parent;
  if (!blockNode || blockNode.type !== "block") return;
  const classNode = blockNode.parent;
  if (!classNode || classNode.type !== "class_definition") return;

  // LHS must be a plain identifier (the field name).
  const lhsNode = node.childForFieldName("left") ?? node.namedChildren[0];
  if (!lhsNode || lhsNode.type !== "identifier") return;
  const shortName = lhsNode.text;
  if (!shortName) return;

  const names = collectPyTypeReferences(typeNode);
  if (names.length === 0) return;

  // Locate the field symbol in the scope index by position.
  const line = node.startPosition.row;
  const col = node.startPosition.column;
  const bucket = scopes.byShortName.get(shortName);
  if (!bucket) return;
  const fieldEntry = bucket.find(
    (e) => e.kind === "field" && rangeContains(e, line, col),
  );
  if (!fieldEntry) return;

  for (const name of names) {
    out.push({
      kind: "TYPE_OF",
      src_id: fieldEntry.id,
      target: { kinds: ["class", "type_alias"], shortName: name },
    });
  }
}

function collectPyTypeReferences(node: Node): string[] {
  const found: string[] = [];
  const PRIMITIVES = new Set([
    "str", "int", "float", "bool", "bytes", "None", "Any",
    "list", "dict", "tuple", "set", "frozenset", "object",
  ]);
  const visit = (n: Node): void => {
    if (n.type === "identifier") {
      const t = n.text;
      if (t && !PRIMITIVES.has(t)) found.push(t);
      return;
    }
    if (n.type === "attribute") {
      // `pkg.module.Foo` → take the final `identifier`.
      const attr = n.childForFieldName("attribute");
      if (attr?.type === "identifier") {
        const t = attr.text;
        if (t && !PRIMITIVES.has(t)) found.push(t);
      }
      return;
    }
    // Recurse into generic_type, subscript (List[Foo]), union, etc.
    for (const c of n.namedChildren) {
      if (c) visit(c);
    }
  };
  visit(node);
  return found;
}

// ---------------------------------------------------------------------------
// PHP walk — inheritance/relationship edges (bead MetaCoding-1xd).
//   EXTENDS      class/interface `extends X`   (base_clause)
//   IMPLEMENTS   class `implements X, Y`       (class_interface_clause)
//   USES_TRAIT   class body `use TraitName;`   (use_declaration)
// Targets resolve to in-repo symbols when present, else to a name-keyed
// boundary node (externalFallback) so out-of-repo base classes like Drupal's
// ContentEntityBase still cluster — the role signal lives in the name.
// ---------------------------------------------------------------------------
const PHP_TYPE_KINDS: SymbolKind[] = ["class", "interface", "enum"];

// Drupal / accessor field idioms recovered from method-call syntax
// (bead MetaCoding-vju). scip-php never sets ReadAccess/WriteAccess, so these
// string-keyed field accesses would otherwise vanish entirely. The field name
// lives in the first string-literal argument; the target is a boundary node
// keyed on that name (externalFallback) because config/entity fields are almost
// never declared PHP properties — the role signal is the field NAME, mirroring
// how EXTENDS clusters out-of-repo base classes (bead MetaCoding-1xd).
const PHP_FIELD_WRITE_METHODS = new Set(["set", "setValue"]);
const PHP_FIELD_READ_METHODS = new Set(["get", "getValue"]);

function walkPhp(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  switch (node.type) {
    case "class_declaration":
    case "interface_declaration":
      phpHandleInheritance(node, scopes, out);
      break;
    case "assignment_expression":
      // `$this->field = X` / `$obj->prop = X` → WRITES_FIELD on the LHS member.
      phpHandleAssignment(node, scopes, out);
      break;
    case "augmented_assignment_expression":
      // `$this->count += 1` — both a write and a read of the field.
      phpHandleAssignment(node, scopes, out);
      phpHandleReadsField(node, scopes, out, /* isAugmented */ true);
      break;
    case "member_access_expression":
      // Every `$this->field` / `$obj->prop` read that is not the direct LHS of a
      // plain assignment (augmented handled above) → READS_FIELD.
      phpHandleReadsField(node, scopes, out, /* isAugmented */ false);
      break;
    case "member_call_expression":
      // Drupal accessor idioms: `->set('field', …)` / `->get('field')`.
      phpHandleAccessorCall(node, scopes, out);
      break;
  }
  for (const child of node.namedChildren) {
    if (child) walkPhp(child, scopes, out);
  }
}

// True when a member-access name looks like a Drupal entity field
// (`$entity->field_notes`). Such fields are dynamic (defined in config, not as
// PHP properties), so we keep the edge via a name-keyed boundary node rather
// than dropping it when no declared property matches.
function isDrupalEntityField(shortName: string): boolean {
  return shortName.startsWith("field_");
}

// Field name from a member_access_expression LHS/target. Returns null for
// dynamic access (`$this->$name`) where the property is not a literal name.
function phpMemberFieldName(member: Node): {
  shortName: string;
  isThis: boolean;
} | null {
  const object = member.childForFieldName("object");
  const name = member.childForFieldName("name");
  if (!object || !name) return null;
  if (name.type !== "name") return null; // skip `$this->$dynamic`
  const shortName = name.text;
  if (!shortName) return null;
  const isThis =
    object.type === "variable_name" && object.text === "$this";
  return { shortName, isThis };
}

function phpHandleAssignment(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  const left = node.childForFieldName("left");
  if (!left || left.type !== "member_access_expression") return;
  const field = phpMemberFieldName(left);
  if (!field) return;

  const src = findEnclosingScope(
    scopes,
    left.startPosition.row,
    left.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;

  // Scope hint: `$this->field` prefers a field in the enclosing class.
  const cls = field.isThis
    ? findEnclosingClass(scopes, left.startPosition.row, left.startPosition.column)
    : null;
  out.push({
    kind: "WRITES_FIELD",
    src_id: src.id,
    target: {
      kinds: ["field"],
      shortName: field.shortName,
      scopeQn: cls?.qualifiedName,
      // Drupal entity fields aren't declared properties — keep via boundary node.
      externalFallback: isDrupalEntityField(field.shortName),
    },
  });
}

function phpHandleReadsField(
  node: Node,
  scopes: ScopeIndex,
  out: EdgeCandidate[],
  isAugmented: boolean,
): void {
  let memberNode: Node;
  if (isAugmented) {
    const left = node.childForFieldName("left");
    if (!left || left.type !== "member_access_expression") return;
    memberNode = left;
  } else {
    memberNode = node;
    // Skip when this member-access IS the LHS of an assignment. For a plain
    // assignment that's a pure write (emitted by phpHandleAssignment); for an
    // augmented assignment the read is already emitted by the isAugmented path,
    // so skipping here avoids double-counting. Compare by position because
    // tree-sitter hands out fresh wrapper objects per accessor call.
    const parent = node.parent;
    if (
      parent?.type === "assignment_expression" ||
      parent?.type === "augmented_assignment_expression"
    ) {
      const left = parent.childForFieldName("left");
      if (
        left &&
        left.startPosition.row === node.startPosition.row &&
        left.startPosition.column === node.startPosition.column
      ) {
        return;
      }
    }
  }

  const field = phpMemberFieldName(memberNode);
  if (!field) return;

  const src = findEnclosingScope(
    scopes,
    memberNode.startPosition.row,
    memberNode.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;

  const cls = field.isThis
    ? findEnclosingClass(scopes, memberNode.startPosition.row, memberNode.startPosition.column)
    : null;
  out.push({
    kind: "READS_FIELD",
    src_id: src.id,
    target: {
      kinds: ["field"],
      shortName: field.shortName,
      scopeQn: cls?.qualifiedName,
      externalFallback: isDrupalEntityField(field.shortName),
    },
  });
}

// `$obj->set('field', …)` / `$obj->get('field')` — the field name is the first
// string-literal argument. Emitted as boundary-node field edges (the accessed
// field is a dynamic config/entity field, not a declared property).
function phpHandleAccessorCall(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  const nameNode = node.childForFieldName("name");
  if (!nameNode || nameNode.type !== "name") return;
  const method = nameNode.text;
  const isWrite = PHP_FIELD_WRITE_METHODS.has(method);
  const isRead = PHP_FIELD_READ_METHODS.has(method);
  if (!isWrite && !isRead) return;

  const args = node.childForFieldName("arguments");
  if (!args) return;
  const firstArg = args.namedChildren.find((c) => c && c.type === "argument");
  if (!firstArg) return;
  const strNode = firstArg.namedChildren.find(
    (c) => c && (c.type === "string" || c.type === "encapsed_string"),
  );
  if (!strNode) return;
  const contentNode = strNode.namedChildren.find((c) => c && c.type === "string_content");
  const shortName = (contentNode?.text ?? "").trim();
  if (!shortName) return;

  const src = findEnclosingScope(
    scopes,
    node.startPosition.row,
    node.startPosition.column,
    CALLABLE_KINDS,
  );
  if (!src) return;

  out.push({
    kind: isWrite ? "WRITES_FIELD" : "READS_FIELD",
    src_id: src.id,
    // String-keyed accessors target dynamic fields — always via boundary node.
    target: { kinds: ["field"], shortName, externalFallback: true },
  });
}

function phpHandleInheritance(node: Node, scopes: ScopeIndex, out: EdgeCandidate[]): void {
  // src = the declaring class/interface (the enclosing type scope at the
  // declaration's name position).
  const nameNode = node.childForFieldName("name") ?? node;
  const src = findEnclosingClass(
    scopes,
    nameNode.startPosition.row,
    nameNode.startPosition.column,
  );
  if (!src) return;

  for (const child of node.namedChildren) {
    if (!child) continue;
    if (child.type === "base_clause") {
      // `class C extends B` or `interface I extends A, B`.
      for (const name of phpClauseNames(child)) {
        out.push({
          kind: "EXTENDS",
          src_id: src.id,
          target: { kinds: PHP_TYPE_KINDS, shortName: name, externalFallback: true },
        });
      }
    } else if (child.type === "class_interface_clause") {
      for (const name of phpClauseNames(child)) {
        out.push({
          kind: "IMPLEMENTS",
          src_id: src.id,
          target: { kinds: ["interface", "class"], shortName: name, externalFallback: true },
        });
      }
    } else if (child.type === "declaration_list") {
      // Trait usage lives in the class body: `use TraitName;`.
      for (const member of child.namedChildren) {
        if (member?.type !== "use_declaration") continue;
        for (const name of phpClauseNames(member)) {
          out.push({
            kind: "USES_TRAIT",
            src_id: src.id,
            target: { kinds: ["class"], shortName: name, externalFallback: true },
          });
        }
      }
    }
  }
}

// Names referenced in a clause: each is a `name`, or a `qualified_name` whose
// last segment is the type short name.
function phpClauseNames(clause: Node): string[] {
  const names: string[] = [];
  for (const c of clause.namedChildren) {
    if (!c) continue;
    if (c.type === "name") {
      names.push(c.text);
    } else if (c.type === "qualified_name") {
      const segs = c.namedChildren.filter((x) => x?.type === "name");
      const last = segs[segs.length - 1];
      if (last) names.push(last.text);
    }
  }
  return names;
}

// ---------------------------------------------------------------------------
// Resolver
// ---------------------------------------------------------------------------

/**
 * Repo-wide symbol index built by the walker after all files are extracted.
 * Maps `(repo, kind, shortName)` → list of Symbol ids.
 */
export class SymbolResolver {
  // key = `${repo}|${kind}|${shortName}` → list of (id, qualified_name)
  private byKindName = new Map<string, Array<{ id: string; qn: string }>>();

  add(s: Symbol): void {
    const key = `${s.repo}|${s.kind}|${s.short_name}`;
    const bucket = this.byKindName.get(key);
    const entry = { id: s.id, qn: s.qualified_name };
    if (bucket) bucket.push(entry);
    else this.byKindName.set(key, [entry]);
  }

  /**
   * Resolve a target spec to a single Symbol id. Returns null if no match
   * (caller drops the edge). When `scopeQn` is set, prefer the entry whose
   * qualified_name starts with that scope. Otherwise pick the first match —
   * acceptable noise for now (we can refine when entropy plateaus).
   */
  resolve(target: TargetSpec, repo: string): string | null {
    for (const kind of target.kinds) {
      const key = `${repo}|${kind}|${target.shortName}`;
      const bucket = this.byKindName.get(key);
      if (!bucket || bucket.length === 0) continue;
      if (target.scopeQn) {
        // (1) Full-prefix scope: prefer fields whose qualified_name starts with
        // the class qn (the class extractor uses `${parentQn}::${short}` and
        // fields are children of the class). Used by `this.field` writes/reads.
        const scoped = bucket.find((b) => b.qn.startsWith(target.scopeQn + "::"));
        if (scoped) return scoped.id;
        // (2) Interior-segment scope: prefer a target whose qualified_name
        // contains the qualifier as an enclosing namespace/module segment
        // (`...::ns::Foo`). Used by `new ns.Foo()` to disambiguate same-named
        // classes in different namespaces (bead MetaCoding-gc5 #4). Falls
        // through to best-effort when no namespaced candidate exists.
        const nsScoped = bucket.find((b) => b.qn.includes("::" + target.scopeQn + "::"));
        if (nsScoped) return nsScoped.id;
      }
      // Single match → unambiguous; or first match (best-effort).
      return bucket[0]!.id;
    }
    return null;
  }
}
