#!/usr/bin/env bun
/**
 * spike-citation-density.ts — MetaCoding-d1l.6
 *
 * Measures RFC / OIDC spec-citation density in reference OAuth/OIDC
 * implementations, to decide whether tier 1 of the spec-anchored-porting epic
 * (mining CITES_SPEC edges out of code comments) is load-bearing or collapses.
 *
 * Usage:
 *   bun scripts/spike-citation-density.ts <repo-root> [<repo-root> ...]
 *
 * Each repo-root is a checkout of e.g. ory/fosite, zitadel/oidc,
 * panva/node-oidc-provider. Reports per repo:
 *   - LOC (non-blank, non-vendor), split prod / test
 *   - citations (section-level and doc-level), per KLOC
 *   - distinct specs and distinct spec sections cited
 *   - fraction of exported symbols within N lines of a citation, for several N
 *
 * Deliberately comment-only: a citation is only counted when it occurs on a
 * line the lexer classifies as a comment, so identifiers like
 * `rfc8628.NewHandler` or an import path do not inflate the numbers.
 */

import { readdirSync, readFileSync, statSync } from "node:fs";
import { join, relative, extname, sep } from "node:path";

// ---------------------------------------------------------------------------
// file discovery
// ---------------------------------------------------------------------------

const SKIP_DIRS = new Set([
  ".git",
  "node_modules",
  "vendor",
  "third_party",
  "dist",
  "build",
  ".github",
]);

const EXTS = new Set([".go", ".js", ".mjs", ".cjs", ".ts"]);

function walk(root: string): string[] {
  const out: string[] = [];
  const stack = [root];
  while (stack.length) {
    const dir = stack.pop()!;
    let entries;
    try {
      entries = readdirSync(dir, { withFileTypes: true });
    } catch {
      continue;
    }
    for (const e of entries) {
      const p = join(dir, e.name);
      if (e.isDirectory()) {
        if (SKIP_DIRS.has(e.name)) continue;
        stack.push(p);
      } else if (e.isFile() && EXTS.has(extname(e.name))) {
        out.push(p);
      }
    }
  }
  return out.sort();
}

function isTestFile(rel: string): boolean {
  const parts = rel.split(sep);
  if (parts.some((p) => p === "test" || p === "tests" || p === "testdata")) return true;
  const base = parts[parts.length - 1]!;
  return /_test\.go$/.test(base) || /\.(test|spec)\.[cm]?[jt]s$/.test(base);
}

// ---------------------------------------------------------------------------
// comment lexing (line granularity)
//
// A line index is marked "comment" if any part of it is inside a // or /* */
// comment. String-literal awareness is approximate but sufficient: the only
// false-positive risk is a `//`-containing string, and none of the citation
// patterns fire on those in these corpora (checked by hand-sampling).
// ---------------------------------------------------------------------------

function commentMask(src: string): { lines: string[]; isComment: boolean[] } {
  const lines = src.split("\n");
  const isComment = new Array<boolean>(lines.length).fill(false);
  let inBlock = false;
  for (let i = 0; i < lines.length; i++) {
    const line = lines[i]!;
    if (inBlock) {
      isComment[i] = true;
      if (line.includes("*/")) inBlock = false;
      continue;
    }
    // strip simple string literals so `"http://..."` isn't read as a comment
    const stripped = line
      .replace(/`[^`]*`/g, "``")
      .replace(/"(?:[^"\\]|\\.)*"/g, '""')
      .replace(/'(?:[^'\\]|\\.)*'/g, "''");
    const lineIdx = stripped.indexOf("//");
    const blockIdx = stripped.indexOf("/*");
    if (blockIdx !== -1 && (lineIdx === -1 || blockIdx < lineIdx)) {
      isComment[i] = true;
      if (stripped.indexOf("*/", blockIdx + 2) === -1) inBlock = true;
    } else if (lineIdx !== -1) {
      isComment[i] = true;
    }
  }
  return { lines, isComment };
}

// ---------------------------------------------------------------------------
// citation patterns
//
// Widened after hand-sampling all three corpora. Forms actually observed:
//   fosite:  https://tools.ietf.org/html/rfc6749#section-4.1.3
//            [RFC3986] Section 6.2.1.
//   zitadel: https://datatracker.ietf.org/doc/html/rfc6749#section-4.4
//            [RFC 6749, section 4.4]: https://...   (Go doc link syntax)
//            RFC 6749 §2.3:
//            RFC 7662, section 2.2
//   node:    https://www.rfc-editor.org/rfc/rfc9396.html#section-2
//            https://openid.net/specs/openid-connect-core-1_0.html#AuthRequest
//            https://www.rfc-editor.org/rfc/rfc7636#appendix-B
//            draft-ietf-oauth-*-NN anchors
// ---------------------------------------------------------------------------

type Hit = { spec: string; section: string | null; raw: string };

/** canonical spec id for the non-RFC (OpenID Foundation) family */
function normSpec(raw: string): string {
  let s = raw.trim().toLowerCase().replace(/\s+/g, "-");
  s = s.replace(/-(final|draft)$/, "").replace(/-(1_0|2_0|1\.0)$/, "");
  if (s === "oidc-core" || s === "openid-connect-core") return "OIDC-CORE";
  if (s.startsWith("openid-4-verifiable-credential-issuance") || s === "openid4vci") return "OPENID4VCI";
  return s.toUpperCase();
}

const SECTION_PATTERNS: { re: RegExp; spec: (m: RegExpExecArray) => string; sec: (m: RegExpExecArray) => string }[] = [
  // rfc6749#section-4.1.3 / rfc7636.html#appendix-B / rfc9396.html#name-request-parameter
  {
    re: /rfc[\s-]?(\d{3,5})(?:\.html|\.txt|\.xml|\/)?#(?:section[-.]|appendix[-.]|name-|page-)?([\w.\-]+)/gi,
    spec: (m) => `RFC${m[1]}`,
    sec: (m) => m[2]!.replace(/[.\-]+$/, ""),
  },
  // "RFC 6749, section 4.4" / "RFC6749 Section 3.1.2.3" / "RFC 8693 in section 2.1"
  {
    re: /rfc[\s-]?(\d{3,5})\]?,?\s+(?:(?:in|at|of|see|says?|specifies)\s+)?(?:§\s*|sections?\s+|appendix\s+)([\d]+(?:\.[\dA-Za-z]+)*|[A-Z])\b/gi,
    spec: (m) => `RFC${m[1]}`,
    sec: (m) => m[2]!,
  },
  // "[RFC3986] Section 6.2.1"  (reference-style, spec and section separated)
  {
    re: /\[rfc[\s-]?(\d{3,5})\][^\n]{0,40}?\b(?:§\s*|sections?\s+|appendix\s+)([\d]+(?:\.[\dA-Za-z]+)*|[A-Z])\b/gi,
    spec: (m) => `RFC${m[1]}`,
    sec: (m) => m[2]!,
  },
  // "RFC 6749 §2.3"
  {
    re: /rfc[\s-]?(\d{3,5})\s*§\s*([\d]+(?:\.[\dA-Za-z]+)*)/gi,
    spec: (m) => `RFC${m[1]}`,
    sec: (m) => m[2]!,
  },
  // openid.net/specs/openid-connect-core-1_0.html#AuthRequest (and OpenID4VCI etc.)
  {
    re: /(?:openid\.net\/specs\/)?([a-z][a-z0-9_.-]*(?:-1_0|-2_0|-1\.0)[a-z0-9_.-]*|openid[a-z0-9_.-]*)\.html#([\w.\-]+)/gi,
    spec: (m) => normSpec(m[1]!),
    sec: (m) => m[2]!.replace(/[.\-]+$/, ""),
  },
  // textual OIDC-family citation: "OpenID Connect Core 1.0, section 3.1.3.6",
  // "OpenID4VCI 1.0, Section 12.2.4"
  {
    re: /(OpenID\s?Connect\s+[A-Za-z]+(?:\s+[A-Za-z]+)?|OpenID4VCI|OIDC\s+Core)\s*(?:1\.0)?,?\s+(?:in\s+)?sections?\s+([\d]+(?:\.[\dA-Za-z]+)*)/gi,
    spec: (m) => normSpec(m[1]!.trim()),
    sec: (m) => m[2]!,
  },
  // IETF drafts with an anchor
  {
    re: /(draft-[a-z0-9-]+?-(?:\d{2}))(?:\.html)?#(?:section[-.]|name-)?([\w.\-]+)/gi,
    spec: (m) => m[1]!.toUpperCase(),
    sec: (m) => m[2]!.replace(/[.\-]+$/, ""),
  },
  // @spec / spec: tags (tier-2 style annotation, counted if a codebase uses it)
  {
    re: /@?spec:?\s+rfc[\s-]?(\d{3,5})#([\d]+(?:\.[\dA-Za-z]+)*)/gi,
    spec: (m) => `RFC${m[1]}`,
    sec: (m) => m[2]!,
  },
];

// doc-level: an RFC / OIDC spec named without a section anchor
const DOC_PATTERNS: { re: RegExp; spec: (m: RegExpExecArray) => string }[] = [
  { re: /\brfc[\s-]?(\d{3,5})\b/gi, spec: (m) => `RFC${m[1]}` },
  {
    re: /(?:openid\.net\/specs\/)?([a-z][a-z0-9_.-]*(?:-1_0|-2_0|-1\.0)[a-z0-9_.-]*|openid[a-z0-9_.-]*)\.html\b/gi,
    spec: (m) => normSpec(m[1]!),
  },
  { re: /\b(draft-[a-z0-9-]+-\d{2})\b/gi, spec: (m) => m[1]!.toUpperCase() },
  { re: /\b(OpenID\s?Connect\s+Core|OIDC\s+Core|OpenID4VCI)\b/g, spec: (m) => normSpec(m[1]!) },
];

/**
 * A bare "Section 4.1.2.1" inside a comment block that already names a spec.
 * Reference implementations quote RFC prose verbatim and then refer to sections
 * without repeating the RFC number; a real extractor resolves these against the
 * nearest preceding spec mention. Counted separately so the strict number stays
 * honest and the resolvable upside stays visible.
 */
const BARE_SECTION = /(?<!rfc[\s-]?\d{3,5}[\],]?\s)(?:§\s*|sections?\s+)([\d]+(?:\.[\dA-Za-z]+)+)\b/gi;

function scanBare(line: string): string[] {
  BARE_SECTION.lastIndex = 0;
  const out: string[] = [];
  let m: RegExpExecArray | null;
  while ((m = BARE_SECTION.exec(line))) out.push(m[1]!);
  return out;
}

function scanLine(line: string): { sections: Hit[]; docs: Hit[] } {
  const sections: Hit[] = [];
  const covered: [number, number][] = [];
  for (const p of SECTION_PATTERNS) {
    p.re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = p.re.exec(line))) {
      const spec = p.spec(m);
      const sec = p.sec(m);
      // de-dup: same spec+section already found on this line
      if (sections.some((h) => h.spec === spec && h.section === sec)) continue;
      sections.push({ spec, section: sec, raw: m[0] });
      covered.push([m.index, m.index + m[0].length]);
    }
  }
  const docs: Hit[] = [];
  for (const p of DOC_PATTERNS) {
    p.re.lastIndex = 0;
    let m: RegExpExecArray | null;
    while ((m = p.re.exec(line))) {
      const inSection = covered.some(([a, b]) => m!.index >= a && m!.index < b);
      if (inSection) continue;
      const spec = p.spec(m);
      if (docs.some((h) => h.spec === spec)) continue;
      docs.push({ spec, section: null, raw: m[0] });
    }
  }
  return { sections, docs };
}

// ---------------------------------------------------------------------------
// exported symbols
// ---------------------------------------------------------------------------

const GO_EXPORTED = [
  /^func\s+([A-Z]\w*)\s*[<(]/,
  /^func\s+\([^)]*\)\s+([A-Z]\w*)\s*[<(]/,
  /^type\s+([A-Z]\w*)\b/,
  /^(?:var|const)\s+([A-Z]\w*)\b/,
  // exported interface methods and struct fields — indented one tab inside a
  // type block. These matter: in fosite the densest citation cluster
  // (oauth2.go) is doc comments on interface methods, and SCIP emits them as
  // symbols, so leaving them out would bias the measurement against tier 1.
  /^\t([A-Z]\w*)\(/,
  /^\t([A-Z]\w*)\s+[\w*[\]./]/,
];

const JS_EXPORTED = [
  /^export\s+(?:default\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)/,
  /^export\s+(?:default\s+)?class\s+([\w$]+)/,
  /^export\s+(?:const|let|var)\s+([\w$]+)/,
  /^export\s+\{/,
  /^module\.exports\s*=/,
];

/** broader net: any named definition, exported or not (JS modules export late) */
const JS_DEFS = [
  /^\s*(?:export\s+)?(?:async\s+)?function\s*\*?\s*([\w$]+)\s*\(/,
  /^\s*(?:export\s+)?class\s+([\w$]+)/,
  /^\s{2,}(?:async\s+)?(?:\*\s*)?([\w$]+)\s*\([^)]*\)\s*\{/, // object/class methods
];

const GO_DEFS = [
  /^func\s+(\w+)\s*[<(]/,
  /^func\s+\([^)]*\)\s+(\w+)\s*[<(]/,
  /^type\s+(\w+)\b/,
];

function findSymbols(lines: string[], isGo: boolean, exportedOnly: boolean): number[] {
  const pats = isGo ? (exportedOnly ? GO_EXPORTED : GO_DEFS) : exportedOnly ? JS_EXPORTED : JS_DEFS;
  const out: number[] = [];
  for (let i = 0; i < lines.length; i++) {
    for (const p of pats) {
      if (p.test(lines[i]!)) {
        out.push(i);
        break;
      }
    }
  }
  return out;
}

// ---------------------------------------------------------------------------
// per-repo measurement
// ---------------------------------------------------------------------------

const NS = [3, 5, 10, 20];

type RepoStats = {
  name: string;
  files: number;
  loc: number;
  testLoc: number;
  commentLines: number;
  sectionCitations: number;
  resolvedCitations: number;
  docCitations: number;
  testSectionCitations: number;
  specs: Map<string, Set<string>>; // spec -> sections (strict)
  resolvedSpecs: Map<string, Set<string>>; // spec -> sections (context-resolved)
  docOnlySpecs: Map<string, number>;
  exported: number;
  exportedNear: Record<number, number>;
  exportedNearR: Record<number, number>;
  exportedNearAny: Record<number, number>;
  defs: number;
  defsNear: Record<number, number>;
  citedFiles: number;
  topFiles: [string, number][];
};

function measure(root: string): RepoStats {
  const name = root.split(sep).filter(Boolean).pop()!;
  const files = walk(root);
  const st: RepoStats = {
    name,
    files: 0,
    loc: 0,
    testLoc: 0,
    commentLines: 0,
    sectionCitations: 0,
    resolvedCitations: 0,
    docCitations: 0,
    testSectionCitations: 0,
    specs: new Map(),
    resolvedSpecs: new Map(),
    docOnlySpecs: new Map(),
    exported: 0,
    exportedNear: Object.fromEntries(NS.map((n) => [n, 0])),
    exportedNearR: Object.fromEntries(NS.map((n) => [n, 0])),
    exportedNearAny: Object.fromEntries(NS.map((n) => [n, 0])),
    defs: 0,
    defsNear: Object.fromEntries(NS.map((n) => [n, 0])),
    citedFiles: 0,
    topFiles: [],
  };
  const perFile: [string, number][] = [];

  for (const f of files) {
    const rel = relative(root, f);
    const isGo = extname(f) === ".go";
    let src: string;
    try {
      src = readFileSync(f, "utf8");
    } catch {
      continue;
    }
    const { lines, isComment } = commentMask(src);
    const nonBlank = lines.filter((l) => l.trim().length > 0).length;
    const test = isTestFile(rel);

    if (test) {
      st.testLoc += nonBlank;
    } else {
      st.files++;
      st.loc += nonBlank;
      st.commentLines += isComment.filter(Boolean).length;
    }

    const citationLines: number[] = []; // strict: an explicit spec+section on this line
    const resolvedLines: number[] = []; // strict PLUS context-resolved bare section refs
    const anyLines: number[] = []; // any spec mention at all, including doc-level-only
    let fileSection = 0;
    let ctxSpec: string | null = null;
    let ctxLine = -1e9;
    const CTX_WINDOW = 40;

    for (let i = 0; i < lines.length; i++) {
      if (!isComment[i]) continue;
      const { sections, docs } = scanLine(lines[i]!);

      if (test) {
        st.testSectionCitations += sections.length;
        continue;
      }

      if (sections.length) {
        citationLines.push(i);
        resolvedLines.push(i);
        anyLines.push(i);
        fileSection += sections.length;
        st.sectionCitations += sections.length;
        st.resolvedCitations += sections.length;
        for (const h of sections) {
          if (!st.specs.has(h.spec)) st.specs.set(h.spec, new Set());
          st.specs.get(h.spec)!.add(h.section!);
          if (!st.resolvedSpecs.has(h.spec)) st.resolvedSpecs.set(h.spec, new Set());
          st.resolvedSpecs.get(h.spec)!.add(h.section!);
        }
        ctxSpec = sections[sections.length - 1]!.spec;
        ctxLine = i;
      } else {
        // bare "Section 4.1.2.1" resolved against the nearest named spec above
        const bare = scanBare(lines[i]!);
        if (bare.length && ctxSpec && i - ctxLine <= CTX_WINDOW) {
          resolvedLines.push(i);
          anyLines.push(i);
          st.resolvedCitations += bare.length;
          for (const b of bare) {
            if (!st.resolvedSpecs.has(ctxSpec)) st.resolvedSpecs.set(ctxSpec, new Set());
            st.resolvedSpecs.get(ctxSpec)!.add(b);
          }
          ctxLine = i; // keep the chain alive through a run of quoted prose
        }
      }

      if (docs.length) {
        if (anyLines[anyLines.length - 1] !== i) anyLines.push(i);
        st.docCitations += docs.length;
        for (const h of docs) st.docOnlySpecs.set(h.spec, (st.docOnlySpecs.get(h.spec) ?? 0) + 1);
        if (!sections.length) {
          ctxSpec = docs[docs.length - 1]!.spec;
          ctxLine = i;
        }
      }
    }
    if (test) continue;
    if (fileSection > 0) {
      st.citedFiles++;
      perFile.push([rel, fileSection]);
    }

    for (const [exportedOnly, cnt, near] of [
      [true, "exported", st.exportedNear] as const,
      [false, "defs", st.defsNear] as const,
    ]) {
      const syms = findSymbols(lines, isGo, exportedOnly);
      if (exportedOnly) st.exported += syms.length;
      else st.defs += syms.length;
      for (const s of syms) {
        for (const n of NS) {
          if (citationLines.some((c) => Math.abs(c - s) <= n)) near[n]!++;
          if (exportedOnly && resolvedLines.some((c) => Math.abs(c - s) <= n)) st.exportedNearR[n]!++;
          if (exportedOnly && anyLines.some((c) => Math.abs(c - s) <= n)) st.exportedNearAny[n]!++;
        }
      }
      void cnt;
    }
  }

  perFile.sort((a, b) => b[1] - a[1]);
  st.topFiles = perFile.slice(0, 8);
  return st;
}

// ---------------------------------------------------------------------------
// report
// ---------------------------------------------------------------------------

function pct(a: number, b: number): string {
  return b === 0 ? "n/a" : `${((100 * a) / b).toFixed(1)}%`;
}

const roots = process.argv.slice(2);
if (roots.length === 0) {
  console.error("usage: bun scripts/spike-citation-density.ts <repo-root> [...]");
  process.exit(1);
}

for (const root of roots) {
  try {
    statSync(root);
  } catch {
    console.error(`skip (not found): ${root}`);
    continue;
  }
  const s = measure(root);
  const kloc = s.loc / 1000;
  const totalSections = [...s.specs.values()].reduce((a, v) => a + v.size, 0);

  console.log(`\n=== ${s.name} ===`);
  console.log(`prod files: ${s.files}   prod LOC (non-blank): ${s.loc}   test LOC: ${s.testLoc}`);
  console.log(`comment lines: ${s.commentLines} (${pct(s.commentLines, s.loc)} of prod LOC)`);
  console.log(
    `section-level citations: ${s.sectionCitations}  ->  ${(s.sectionCitations / kloc).toFixed(2)} / KLOC`,
  );
  console.log(
    `doc-level-only citations: ${s.docCitations}  ->  ${(s.docCitations / kloc).toFixed(2)} / KLOC`,
  );
  console.log(
    `context-resolved citations (strict + bare "Section X.Y" bound to nearest spec): ${s.resolvedCitations}  ->  ${(s.resolvedCitations / kloc).toFixed(2)} / KLOC`,
  );
  console.log(`section citations in tests: ${s.testSectionCitations}`);
  const totalResolved = [...s.resolvedSpecs.values()].reduce((a, v) => a + v.size, 0);
  console.log(
    `distinct specs with a section anchor: ${s.specs.size}; distinct sections: ${totalSections} (context-resolved: ${totalResolved})`,
  );
  const bySpec = [...s.specs.entries()].sort((a, b) => b[1].size - a[1].size);
  for (const [spec, secs] of bySpec.slice(0, 14)) {
    console.log(`   ${spec.padEnd(22)} ${String(secs.size).padStart(3)} sections  ${[...secs].sort().slice(0, 8).join(", ")}`);
  }
  console.log(`files containing >=1 section citation: ${s.citedFiles} / ${s.files} (${pct(s.citedFiles, s.files)})`);
  console.log(`exported symbols: ${s.exported}`);
  for (const n of NS)
    console.log(
      `   within ${String(n).padStart(2)} lines of a citation: ${s.exportedNear[n]} (${pct(s.exportedNear[n]!, s.exported)})   context-resolved: ${s.exportedNearR[n]} (${pct(s.exportedNearR[n]!, s.exported)})   any-spec-mention: ${s.exportedNearAny[n]} (${pct(s.exportedNearAny[n]!, s.exported)})`,
    );
  console.log(`all named defs: ${s.defs}`);
  for (const n of NS) console.log(`   within ${String(n).padStart(2)} lines of a citation: ${s.defsNear[n]} (${pct(s.defsNear[n]!, s.defs)})`);
  const topDoc = [...s.docOnlySpecs.entries()].sort((a, b) => b[1] - a[1]).slice(0, 8);
  console.log(`doc-level-only specs (no section anchor): ${topDoc.map(([k, v]) => `${k}x${v}`).join(", ")}`);
  console.log(`top cited files:`);
  for (const [f, c] of s.topFiles) console.log(`   ${String(c).padStart(4)}  ${f}`);
}
