// SCIP symbol-string parser.
//
// SCIP symbol grammar (excerpt; full at https://github.com/sourcegraph/scip):
//
//   <scheme> ' ' <manager> ' ' <name> ' ' <version> ' ' <descriptors>+
//
//   namespace      ::= <name> '/'
//   type           ::= <name> '#'
//   term           ::= <name> '.'
//   method         ::= <name> '(' <disambiguator> ')' '.'
//   type-parameter ::= '[' <name> ']'
//   parameter      ::= '(' <name> ')'
//   meta           ::= <name> ':'
//   local          ::= 'local ' <id>
//
//   <name> = <identifier> | '`' <text> '`'   (backticks may contain spaces / suffix chars)
//
// We don't need to round-trip; we just need enough structure to drive the
// loader: package, descriptors with suffix, and the file path (the first
// namespace descriptor whose name has a recognized source-file extension).

import type { SymbolKind } from "../store/types";

export type ScipSuffix =
  | "namespace"
  | "type"
  | "term"
  | "method"
  | "type_parameter"
  | "parameter"
  | "meta";

export interface ScipDescriptor {
  name: string;
  suffix: ScipSuffix;
  disambiguator?: string;
}

export interface ScipSymbol {
  raw: string;
  scheme: string;
  pkg: { manager: string; name: string; version: string };
  descriptors: ScipDescriptor[];
  isLocal: boolean;
}

export function parseScipSymbol(raw: string): ScipSymbol | null {
  if (!raw) return null;
  if (raw.startsWith("local ")) {
    return {
      raw,
      scheme: "local",
      pkg: { manager: "", name: "", version: "" },
      descriptors: [{ name: raw.slice(6), suffix: "term" }],
      isLocal: true,
    };
  }

  const cursor = { i: 0, src: raw };
  const scheme = readSpaceTerm(cursor);
  const manager = readSpaceTerm(cursor);
  const pkgName = unquote(readSpaceTerm(cursor));
  const version = readSpaceTerm(cursor);
  const descriptors: ScipDescriptor[] = [];
  while (cursor.i < cursor.src.length) {
    const d = readDescriptor(cursor);
    if (!d) break;
    descriptors.push(d);
  }
  return {
    raw,
    scheme,
    pkg: { manager, name: pkgName, version },
    descriptors,
    isLocal: false,
  };
}

interface Cursor { i: number; src: string }

function readSpaceTerm(c: Cursor): string {
  let out = "";
  let inBacktick = false;
  while (c.i < c.src.length) {
    const ch = c.src[c.i]!;
    if (ch === "`") {
      inBacktick = !inBacktick;
      out += ch;
      c.i++;
      continue;
    }
    if (!inBacktick && ch === " ") {
      c.i++;
      return out;
    }
    out += ch;
    c.i++;
  }
  return out;
}

function readDescriptor(c: Cursor): ScipDescriptor | null {
  if (c.i >= c.src.length) return null;
  const first = c.src[c.i];
  // Pure-suffix descriptors.
  if (first === "[") {
    const close = findClose(c.src, c.i, "[", "]");
    const name = unquote(c.src.slice(c.i + 1, close));
    c.i = close + 1;
    return { name, suffix: "type_parameter" };
  }
  if (first === "(") {
    // Standalone (...) before any name = parameter descriptor.
    const close = findClose(c.src, c.i, "(", ")");
    const name = unquote(c.src.slice(c.i + 1, close));
    c.i = close + 1;
    return { name, suffix: "parameter" };
  }
  // Read a name until a terminator.
  const start = c.i;
  let inBacktick = false;
  while (c.i < c.src.length) {
    const ch = c.src[c.i]!;
    if (ch === "`") {
      inBacktick = !inBacktick;
      c.i++;
      continue;
    }
    if (inBacktick) {
      c.i++;
      continue;
    }
    if (ch === "/") {
      const name = unquote(c.src.slice(start, c.i));
      c.i++;
      return { name, suffix: "namespace" };
    }
    if (ch === "#") {
      const name = unquote(c.src.slice(start, c.i));
      c.i++;
      return { name, suffix: "type" };
    }
    if (ch === ":") {
      const name = unquote(c.src.slice(start, c.i));
      c.i++;
      return { name, suffix: "meta" };
    }
    if (ch === ".") {
      const name = unquote(c.src.slice(start, c.i));
      c.i++;
      return { name, suffix: "term" };
    }
    if (ch === "(") {
      const name = unquote(c.src.slice(start, c.i));
      const close = findClose(c.src, c.i, "(", ")");
      const disamb = c.src.slice(c.i + 1, close);
      const after = close + 1;
      if (c.src[after] === ".") {
        c.i = after + 1;
        return { name, suffix: "method", disambiguator: disamb };
      }
      // Malformed; treat as term and skip.
      c.i = after;
      return { name, suffix: "term" };
    }
    c.i++;
  }
  return null;
}

function findClose(s: string, openIdx: number, open: string, close: string): number {
  let depth = 0;
  for (let i = openIdx; i < s.length; i++) {
    if (s[i] === open) depth++;
    else if (s[i] === close) {
      depth--;
      if (depth === 0) return i;
    }
  }
  return s.length - 1;
}

function unquote(s: string): string {
  if (s.length >= 2 && s.startsWith("`") && s.endsWith("`")) return s.slice(1, -1);
  return s;
}

// Heuristic: which descriptor (if any) names a source file.
const SOURCE_EXT = /\.(ts|tsx|js|jsx|mts|cts)$/;

// scip-typescript encodes a path like `src/store/index.ts` as three
// successive namespace descriptors: `src/`, `store/`, `` `index.ts`/``.
// We accumulate leading namespace segments until one matches a source-file
// extension; that joined run is the file path.
export function filePathOf(sym: ScipSymbol): string | null {
  const segments: string[] = [];
  for (const d of sym.descriptors) {
    if (d.suffix !== "namespace") return null;
    segments.push(d.name);
    if (SOURCE_EXT.test(d.name)) return segments.join("/");
  }
  return null;
}

// Build a qualified_name compatible with Tree-sitter's `<file>::<chain>` shape.
// Files: just the file path.
// Members: file path + "::" + each subsequent descriptor name joined by "::".
export function qualifiedNameOf(sym: ScipSymbol): string {
  const filePath = filePathOf(sym);
  if (filePath === null) {
    // Fallback: dot-join descriptor names.
    return sym.descriptors.map((d) => d.name).join(".");
  }
  // Skip past the descriptors that made up the file path.
  const fileSegCount = filePath.split("/").length;
  const tail = sym.descriptors
    .slice(fileSegCount)
    .filter((d) => d.suffix !== "type_parameter" && d.suffix !== "parameter")
    .map((d) => d.name);
  return tail.length === 0 ? filePath : `${filePath}::${tail.join("::")}`;
}

export function shortNameOf(sym: ScipSymbol): string {
  const meaningful = sym.descriptors.filter(
    (d) => d.suffix !== "type_parameter" && d.suffix !== "parameter",
  );
  const last = meaningful[meaningful.length - 1];
  if (!last) return sym.raw;
  if (last.suffix === "namespace") return last.name.split("/").pop() ?? last.name;
  return last.name;
}

// Map descriptor chain to one of our SymbolKind values.
// scip-typescript v0.4.0 doesn't populate SymbolInformation.kind reliably,
// so we lean on the descriptor suffix.
export function kindOf(sym: ScipSymbol, scipKindHint?: number): SymbolKind {
  const meaningful = sym.descriptors.filter(
    (d) => d.suffix !== "type_parameter" && d.suffix !== "parameter",
  );
  const last = meaningful[meaningful.length - 1];
  const insideType = meaningful.some((d) => d.suffix === "type");

  if (!last) return "function";

  // Whole symbol is just a file path.
  if (last.suffix === "namespace") {
    return SOURCE_EXT.test(last.name) ? "file" : "namespace";
  }
  if (last.suffix === "method") return "method";
  if (last.suffix === "meta") return "type_alias";
  if (last.suffix === "type") {
    // Default to "class"; SCIP doesn't natively distinguish class vs interface in the symbol.
    // SymbolInformation.kind hint can disambiguate when populated.
    if (scipKindHint === 21 /* Interface */) return "interface";
    if (scipKindHint === 11 /* Enum */) return "enum";
    return "class";
  }
  // term suffix: function vs field depending on enclosing.
  if (last.suffix === "term") {
    return insideType ? "field" : "function";
  }
  return "function";
}
