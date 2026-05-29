// Tree-sitter behavior-edge extraction.
//
// Emits WRITES_FIELD, CONSTRUCTS, RETURNS_TYPE, READS_FIELD, TYPE_OF edges.
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
}

export interface EdgePassOpts {
  /** Language code: "ts" or "py". */
  language: "ts" | "py";
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
  // `new ns.Foo()` → member_expression; take the property.
  // `new Foo<T>()` → identifier "Foo".
  let shortName: string | null = null;
  if (constructor.type === "identifier") {
    shortName = constructor.text;
  } else if (constructor.type === "member_expression") {
    const prop = constructor.childForFieldName("property");
    if (prop?.type === "property_identifier") shortName = prop.text;
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
    target: { kinds: ["class", "interface"], shortName },
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
  // pydantic / dataclass-style framework primitives common in many repos
  "BaseModel", "Field", "dataclass",
]);

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
        // Prefer fields whose qualified_name starts with the class qn
        // (the class extractor uses `${parentQn}::${short}` and fields
        // are children of the class).
        const scoped = bucket.find((b) => b.qn.startsWith(target.scopeQn + "::"));
        if (scoped) return scoped.id;
      }
      // Single match → unambiguous; or first match (best-effort).
      return bucket[0]!.id;
    }
    return null;
  }
}
