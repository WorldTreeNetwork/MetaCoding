// Tests for the tree-sitter behavior-edge extraction pass
// (bead MetaCoding-3s5: WRITES_FIELD, CONSTRUCTS, RETURNS_TYPE;
//  bead MetaCoding-9le: READS_FIELD, TYPE_OF on field declarations).

import { test, expect, describe, beforeAll } from "bun:test";

import { makeParser, type TsParser } from "./parser";
import { extractTypeScript } from "./typescript";
import { extractPython } from "./python";
import {
  extractEdgeCandidates,
  SymbolResolver,
  type EdgeCandidate,
} from "./edges";

let tsParser: TsParser;
let pyParser: TsParser;

beforeAll(async () => {
  tsParser = await makeParser("typescript");
  pyParser = await makeParser("python");
});

interface RunResult {
  candidates: EdgeCandidate[];
  symbolIdByQn: Map<string, string>;
  resolver: SymbolResolver;
  repo: string;
}

function runTs(source: string, file = "src/sample.ts"): RunResult {
  const tree = tsParser.parse(source);
  if (!tree) throw new Error("parse failed");
  const repo = "test";
  const ex = extractTypeScript(tree, {
    filePath: file,
    grammar: "typescript",
    branch: "main",
    repo,
  });
  const er = extractEdgeCandidates(tree, {
    language: "ts",
    filePath: file,
    symbols: ex.symbols,
  });
  const resolver = new SymbolResolver();
  for (const s of ex.symbols) resolver.add(s);
  const symbolIdByQn = new Map<string, string>();
  for (const s of ex.symbols) symbolIdByQn.set(s.qualified_name, s.id);
  tree.delete();
  return { candidates: er.candidates, symbolIdByQn, resolver, repo };
}

function runPy(source: string, file = "src/sample.py"): RunResult {
  const tree = pyParser.parse(source);
  if (!tree) throw new Error("parse failed");
  const repo = "test";
  const ex = extractPython(tree, {
    filePath: file,
    branch: "main",
    repo,
  });
  const er = extractEdgeCandidates(tree, {
    language: "py",
    filePath: file,
    symbols: ex.symbols,
  });
  const resolver = new SymbolResolver();
  for (const s of ex.symbols) resolver.add(s);
  const symbolIdByQn = new Map<string, string>();
  for (const s of ex.symbols) symbolIdByQn.set(s.qualified_name, s.id);
  tree.delete();
  return { candidates: er.candidates, symbolIdByQn, resolver, repo };
}

function resolveAll(r: RunResult): Array<{ kind: string; src_qn: string; dst_qn: string }> {
  // Inverse lookup map: id → qn (just for assertion readability).
  const qnById = new Map<string, string>();
  for (const [qn, id] of r.symbolIdByQn) qnById.set(id, qn);
  const out: Array<{ kind: string; src_qn: string; dst_qn: string }> = [];
  for (const c of r.candidates) {
    const dst = r.resolver.resolve(c.target, r.repo);
    if (!dst) continue;
    out.push({
      kind: c.kind,
      src_qn: qnById.get(c.src_id) ?? c.src_id,
      dst_qn: qnById.get(dst) ?? dst,
    });
  }
  return out;
}

// ---------------------------------------------------------------------------
// TypeScript fixtures
// ---------------------------------------------------------------------------

describe("TypeScript WRITES_FIELD", () => {
  test("this.field = X in a method emits WRITES_FIELD", () => {
    const src = `
class User {
  name: string;
  setName(n: string) {
    this.name = n;
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const w = edges.filter((e) => e.kind === "WRITES_FIELD");
    expect(w.length).toBeGreaterThan(0);
    expect(w[0]!.src_qn).toContain("setName");
    expect(w[0]!.dst_qn).toContain("::name");
  });

  test("obj.field = X (non-this) still emits WRITES_FIELD when target resolvable", () => {
    const src = `
class Box {
  value: number;
}
class User {
  box: Box;
  poke(): void {
    this.box.value = 1;
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const w = edges.filter((e) => e.kind === "WRITES_FIELD");
    // `this.box.value = 1` is a single assignment. tsHandleAssignment keys on
    // the LHS member_expression's `property`, which is the outermost property
    // ("value"), so exactly one WRITES_FIELD edge is emitted, targeting the
    // field "value". The intermediate `this.box` access is not itself a write.
    expect(w.length).toBeGreaterThan(0);
    const valueWrite = w.find((e) => e.dst_qn.endsWith("::value"));
    expect(valueWrite).toBeDefined();
  });

  test("augmented assignment (this.count += 1) emits WRITES_FIELD", () => {
    const src = `
class Counter {
  count: number = 0;
  bump() {
    this.count += 1;
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const w = edges.filter((e) => e.kind === "WRITES_FIELD" && e.dst_qn.endsWith("::count"));
    expect(w.length).toBeGreaterThan(0);
  });

  test("no WRITES_FIELD for local-variable writes", () => {
    const src = `
function f() {
  let x = 1;
  x = 2;
}`;
    const r = runTs(src);
    const w = r.candidates.filter((c) => c.kind === "WRITES_FIELD");
    expect(w.length).toBe(0);
  });
});

describe("TypeScript CONSTRUCTS", () => {
  test("new Foo() in a function emits CONSTRUCTS edge to class Foo", () => {
    const src = `
class Foo {
  x: number;
}
function makeFoo() {
  return new Foo();
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const c = edges.filter((e) => e.kind === "CONSTRUCTS");
    expect(c.length).toBeGreaterThan(0);
    expect(c[0]!.src_qn).toContain("makeFoo");
    expect(c[0]!.dst_qn).toContain("::Foo");
  });

  test("new Foo() in a method emits CONSTRUCTS", () => {
    const src = `
class Foo {}
class Builder {
  build(): Foo {
    return new Foo();
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const c = edges.filter((e) => e.kind === "CONSTRUCTS");
    expect(c.length).toBeGreaterThan(0);
    expect(c.some((e) => e.src_qn.includes("build") && e.dst_qn.includes("::Foo"))).toBe(true);
  });

  test("new ns.Foo() captures the namespace qualifier as scopeQn (#4)", () => {
    const src = `
function make() {
  return new ns.Foo();
}`;
    const r = runTs(src);
    const c = r.candidates.filter((e) => e.kind === "CONSTRUCTS");
    expect(c.length).toBeGreaterThan(0);
    expect(c[0]!.target.shortName).toBe("Foo");
    // The `ns` object segment is preserved so the resolver can disambiguate
    // same-named classes in different namespaces.
    expect(c[0]!.target.scopeQn).toBe("ns");
  });

  test("new a.b.Foo() captures the closest namespace segment (#4)", () => {
    const src = `
function make() {
  return new a.b.Foo();
}`;
    const r = runTs(src);
    const c = r.candidates.filter((e) => e.kind === "CONSTRUCTS");
    expect(c.length).toBeGreaterThan(0);
    expect(c[0]!.target.shortName).toBe("Foo");
    expect(c[0]!.target.scopeQn).toBe("b");
  });
});

describe("TypeScript RETURNS_TYPE", () => {
  test("function with declared return type emits RETURNS_TYPE", () => {
    const src = `
class Foo {}
function makeFoo(): Foo {
  return new Foo();
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const rt = edges.filter((e) => e.kind === "RETURNS_TYPE");
    expect(rt.length).toBeGreaterThan(0);
    expect(rt.some((e) => e.src_qn.includes("makeFoo") && e.dst_qn.includes("::Foo"))).toBe(true);
  });

  test("method with declared return type emits RETURNS_TYPE", () => {
    const src = `
class Result {}
class Service {
  fetch(): Result {
    return new Result();
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const rt = edges.filter((e) => e.kind === "RETURNS_TYPE" && e.dst_qn.includes("::Result"));
    expect(rt.length).toBeGreaterThan(0);
  });

  test("primitive return type does not emit RETURNS_TYPE", () => {
    const src = `
function plain(): string {
  return "hi";
}`;
    const r = runTs(src);
    const rt = r.candidates.filter((c) => c.kind === "RETURNS_TYPE");
    expect(rt.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Python fixtures
// ---------------------------------------------------------------------------

describe("Python WRITES_FIELD", () => {
  test("self.attr = X in a method emits WRITES_FIELD", () => {
    const src = `class User:
    name: str = ""

    def set_name(self, n: str) -> None:
        self.name = n
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const w = edges.filter((e) => e.kind === "WRITES_FIELD" && e.dst_qn.endsWith("::name"));
    expect(w.length).toBeGreaterThan(0);
    expect(w[0]!.src_qn).toContain("set_name");
  });

  test("self.attr += 1 (augmented) emits WRITES_FIELD", () => {
    const src = `class Counter:
    count: int = 0

    def bump(self):
        self.count += 1
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const w = edges.filter((e) => e.kind === "WRITES_FIELD" && e.dst_qn.endsWith("::count"));
    expect(w.length).toBeGreaterThan(0);
  });
});

describe("Python CONSTRUCTS", () => {
  test("Foo() call where Foo is a class emits CONSTRUCTS", () => {
    const src = `class Foo:
    pass

def make_foo():
    return Foo()
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const c = edges.filter((e) => e.kind === "CONSTRUCTS");
    expect(c.length).toBeGreaterThan(0);
    expect(c[0]!.src_qn).toContain("make_foo");
    expect(c[0]!.dst_qn).toContain("::Foo");
  });

  test("lowercase callable does not emit CONSTRUCTS", () => {
    const src = `def helper():
    return 1

def caller():
    return helper()
`;
    const r = runPy(src);
    const c = r.candidates.filter((c) => c.kind === "CONSTRUCTS");
    expect(c.length).toBe(0);
  });

  test("built-in exception types are NOT emitted as CONSTRUCTS", () => {
    const src = `def fail():
    raise ValueError("nope")
`;
    const r = runPy(src);
    const c = r.candidates.filter((c) => c.kind === "CONSTRUCTS");
    expect(c.length).toBe(0);
  });
});

describe("Python RETURNS_TYPE", () => {
  test("def with -> Foo annotation emits RETURNS_TYPE", () => {
    const src = `class Foo:
    pass

def make() -> Foo:
    return Foo()
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const rt = edges.filter((e) => e.kind === "RETURNS_TYPE");
    expect(rt.length).toBeGreaterThan(0);
    expect(rt[0]!.src_qn).toContain("make");
    expect(rt[0]!.dst_qn).toContain("::Foo");
  });

  test("primitive return annotation does not emit RETURNS_TYPE", () => {
    const src = `def plain() -> str:
    return "hi"
`;
    const r = runPy(src);
    const rt = r.candidates.filter((c) => c.kind === "RETURNS_TYPE");
    expect(rt.length).toBe(0);
  });

  test("Optional[Foo] return type still emits RETURNS_TYPE to Foo", () => {
    const src = `from typing import Optional

class Foo:
    pass

def maybe() -> Optional[Foo]:
    return None
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const rt = edges.filter((e) => e.kind === "RETURNS_TYPE" && e.dst_qn.includes("::Foo"));
    expect(rt.length).toBeGreaterThan(0);
  });
});

// ---------------------------------------------------------------------------
// TypeScript READS_FIELD (bead MetaCoding-9le)
// ---------------------------------------------------------------------------

describe("TypeScript READS_FIELD", () => {
  test("this.field on RHS of assignment emits READS_FIELD", () => {
    const src = `
class User {
  name: string;
  greet() {
    const x = this.name;
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const rf = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::name"));
    expect(rf.length).toBeGreaterThan(0);
    expect(rf[0]!.src_qn).toContain("greet");
  });

  test("this.field passed as argument emits READS_FIELD", () => {
    const src = `
class Logger {
  prefix: string;
  log() {
    console.log(this.prefix);
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const rf = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::prefix"));
    expect(rf.length).toBeGreaterThan(0);
  });

  test("this.field in condition emits READS_FIELD", () => {
    const src = `
class Guard {
  enabled: boolean;
  check() {
    if (this.enabled) { return; }
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const rf = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::enabled"));
    expect(rf.length).toBeGreaterThan(0);
  });

  test("augmented assignment (this.count += 1) emits both WRITES_FIELD and READS_FIELD", () => {
    const src = `
class Counter {
  count: number = 0;
  bump() {
    this.count += 1;
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const writes = edges.filter((e) => e.kind === "WRITES_FIELD" && e.dst_qn.endsWith("::count"));
    const reads = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::count"));
    expect(writes.length).toBeGreaterThan(0);
    expect(reads.length).toBeGreaterThan(0);
  });

  test("pure write LHS (this.field = X) does NOT emit READS_FIELD", () => {
    const src = `
class User {
  name: string;
  setName(n: string) {
    this.name = n;
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const reads = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::name"));
    expect(reads.length).toBe(0);
  });

  test("single read produces exactly one READS_FIELD edge (no double-counting)", () => {
    const src = `
class Foo {
  val: number;
  get() {
    return this.val;
  }
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const reads = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::val"));
    expect(reads.length).toBe(1);
  });
});

// ---------------------------------------------------------------------------
// TypeScript TYPE_OF on field declarations (bead MetaCoding-9le)
// ---------------------------------------------------------------------------

describe("TypeScript TYPE_OF on field declarations", () => {
  test("class field with type annotation emits TYPE_OF", () => {
    const src = `
class Bar {}
class Foo {
  bar: Bar;
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const to = edges.filter((e) => e.kind === "TYPE_OF" && e.dst_qn.endsWith("::Bar"));
    expect(to.length).toBeGreaterThan(0);
    expect(to[0]!.src_qn).toContain("::bar");
  });

  test("private field with type annotation emits TYPE_OF", () => {
    const src = `
class Engine {}
class Car {
  private engine: Engine;
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const to = edges.filter((e) => e.kind === "TYPE_OF" && e.dst_qn.endsWith("::Engine"));
    expect(to.length).toBeGreaterThan(0);
  });

  test("field with primitive type does NOT emit TYPE_OF", () => {
    const src = `
class Foo {
  count: number;
  label: string;
}`;
    const r = runTs(src);
    const to = r.candidates.filter((c) => c.kind === "TYPE_OF");
    expect(to.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Python READS_FIELD (bead MetaCoding-9le)
// ---------------------------------------------------------------------------

describe("Python READS_FIELD", () => {
  test("self.attr read on RHS emits READS_FIELD", () => {
    const src = `class User:
    name: str = ""

    def greet(self):
        x = self.name
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const rf = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::name"));
    expect(rf.length).toBeGreaterThan(0);
    expect(rf[0]!.src_qn).toContain("greet");
  });

  test("self.attr passed as argument emits READS_FIELD", () => {
    const src = `class Logger:
    prefix: str = ""

    def log(self):
        print(self.prefix)
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const rf = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::prefix"));
    expect(rf.length).toBeGreaterThan(0);
  });

  test("self.attr in condition emits READS_FIELD", () => {
    const src = `class Guard:
    enabled: bool = False

    def check(self):
        if self.enabled:
            return True
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const rf = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::enabled"));
    expect(rf.length).toBeGreaterThan(0);
  });

  test("augmented assignment (self.count += 1) emits both WRITES_FIELD and READS_FIELD", () => {
    const src = `class Counter:
    count: int = 0

    def bump(self):
        self.count += 1
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const writes = edges.filter((e) => e.kind === "WRITES_FIELD" && e.dst_qn.endsWith("::count"));
    const reads = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::count"));
    expect(writes.length).toBeGreaterThan(0);
    expect(reads.length).toBeGreaterThan(0);
  });

  test("pure write LHS (self.attr = X) does NOT emit READS_FIELD", () => {
    const src = `class User:
    name: str = ""

    def set_name(self, n: str):
        self.name = n
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const reads = edges.filter((e) => e.kind === "READS_FIELD" && e.dst_qn.endsWith("::name"));
    expect(reads.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Python TYPE_OF on field declarations (bead MetaCoding-9le)
// ---------------------------------------------------------------------------

describe("Python TYPE_OF on field declarations", () => {
  test("class field with type annotation emits TYPE_OF", () => {
    const src = `class Bar:
    pass

class Foo:
    bar: Bar = None
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const to = edges.filter((e) => e.kind === "TYPE_OF" && e.dst_qn.endsWith("::Bar"));
    expect(to.length).toBeGreaterThan(0);
    expect(to[0]!.src_qn).toContain("::bar");
  });

  test("annotation-only field (no value) emits TYPE_OF", () => {
    const src = `class Engine:
    pass

class Car:
    engine: Engine
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const to = edges.filter((e) => e.kind === "TYPE_OF" && e.dst_qn.endsWith("::Engine"));
    expect(to.length).toBeGreaterThan(0);
  });

  test("field with primitive annotation does NOT emit TYPE_OF", () => {
    const src = `class Foo:
    count: int = 0
    label: str = ""
`;
    const r = runPy(src);
    const to = r.candidates.filter((c) => c.kind === "TYPE_OF");
    expect(to.length).toBe(0);
  });

  test("module-level annotated assignment does NOT emit TYPE_OF", () => {
    const src = `class Bar:
    pass

x: Bar = None
`;
    const r = runPy(src);
    // Module-level `x: Bar` should not produce TYPE_OF — no field symbol at module scope.
    const to = r.candidates.filter((c) => c.kind === "TYPE_OF");
    expect(to.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// TypeScript RAISES (bead MetaCoding-ijo.1)
// ---------------------------------------------------------------------------

describe("TypeScript RAISES", () => {
  test("throw new Error() emits RAISES to Error class", () => {
    const src = `
class AppError {}
function fail() {
  throw new AppError();
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const raises = edges.filter((e) => e.kind === "RAISES" && e.dst_qn.includes("::AppError"));
    expect(raises.length).toBeGreaterThan(0);
    expect(raises[0]!.src_qn).toContain("fail");
  });

  test("throw Error() without new emits RAISES", () => {
    const src = `
class ValidationError {}
function validate() {
  throw ValidationError();
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const raises = edges.filter((e) => e.kind === "RAISES" && e.dst_qn.includes("::ValidationError"));
    expect(raises.length).toBeGreaterThan(0);
  });

  test("throw variable (re-throw) does NOT emit RAISES", () => {
    const src = `
function rethrow(e: unknown) {
  throw e;
}`;
    const r = runTs(src);
    const raises = r.candidates.filter((c) => c.kind === "RAISES");
    expect(raises.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// Python RAISES (bead MetaCoding-ijo.1)
// ---------------------------------------------------------------------------

describe("Python RAISES", () => {
  test("raise CustomError() emits RAISES", () => {
    const src = `class CustomError:
    pass

def fail():
    raise CustomError()
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const raises = edges.filter((e) => e.kind === "RAISES" && e.dst_qn.includes("::CustomError"));
    expect(raises.length).toBeGreaterThan(0);
    expect(raises[0]!.src_qn).toContain("fail");
  });

  test("raise bare class name emits RAISES when uppercase", () => {
    const src = `class StopSignal:
    pass

def halt():
    raise StopSignal
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const raises = edges.filter((e) => e.kind === "RAISES" && e.dst_qn.includes("::StopSignal"));
    expect(raises.length).toBeGreaterThan(0);
  });

  test("bare raise (re-raise) does NOT emit RAISES", () => {
    const src = `def handler():
    try:
        pass
    except Exception:
        raise
`;
    const r = runPy(src);
    const raises = r.candidates.filter((c) => c.kind === "RAISES");
    expect(raises.length).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// TypeScript ANNOTATES (decorator application, bead MetaCoding-ijo.2)
// ---------------------------------------------------------------------------

describe("TypeScript ANNOTATES (decorators)", () => {
  test("@Decorator on a method emits ANNOTATES", () => {
    const src = `
function Log() {}
class Service {
  @Log
  handle() {}
}`;
    const r = runTs(src);
    const edges = resolveAll(r);
    const ann = edges.filter((e) => e.kind === "ANNOTATES" && e.dst_qn.includes("::Log"));
    expect(ann.length).toBeGreaterThan(0);
  });

  // bead MetaCoding-mhv: imported/framework decorators must emit ANNOTATES via
  // externalFallback so the edge is preserved even when the decorator symbol is
  // not repo-local (@Component, @Injectable, @Controller, etc.).
  test("@Component (imported, not repo-local) emits ANNOTATES candidate with externalFallback", () => {
    const src = `
import { Component } from "@angular/core";

@Component({ selector: "app-root" })
class AppComponent {}`;
    const r = runTs(src);
    const ann = r.candidates.filter(
      (c) => c.kind === "ANNOTATES" && c.target.shortName === "Component",
    );
    expect(ann.length).toBeGreaterThan(0);
    expect(ann[0]!.target.externalFallback).toBe(true);
  });

  test("@Injectable() call form (imported) emits ANNOTATES candidate with externalFallback", () => {
    const src = `
import { Injectable } from "@angular/core";

@Injectable()
class MyService {}`;
    const r = runTs(src);
    const ann = r.candidates.filter(
      (c) => c.kind === "ANNOTATES" && c.target.shortName === "Injectable",
    );
    expect(ann.length).toBeGreaterThan(0);
    expect(ann[0]!.target.externalFallback).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Python ANNOTATES (decorator application, bead MetaCoding-ijo.2)
// ---------------------------------------------------------------------------

describe("Python ANNOTATES (decorators)", () => {
  test("@decorator on a function emits ANNOTATES", () => {
    const src = `def my_decorator(f):
    return f

@my_decorator
def hello():
    pass
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const ann = edges.filter((e) => e.kind === "ANNOTATES" && e.dst_qn.includes("::my_decorator"));
    expect(ann.length).toBeGreaterThan(0);
    expect(ann[0]!.src_qn).toContain("hello");
  });

  test("@decorator() with call on a class emits ANNOTATES", () => {
    const src = `def register(name):
    def wrapper(cls):
        return cls
    return wrapper

@register("foo")
class MyClass:
    pass
`;
    const r = runPy(src);
    const edges = resolveAll(r);
    const ann = edges.filter((e) => e.kind === "ANNOTATES" && e.dst_qn.includes("::register"));
    expect(ann.length).toBeGreaterThan(0);
    expect(ann[0]!.src_qn).toContain("MyClass");
  });

  // bead MetaCoding-mhv: imported/framework decorators must emit ANNOTATES via
  // externalFallback so the edge is preserved even when the decorator symbol is
  // not repo-local (@dataclass, @pytest.fixture, @app.route, etc.).
  test("@dataclass (imported, not repo-local) emits ANNOTATES candidate with externalFallback", () => {
    const src = `from dataclasses import dataclass

@dataclass
class Point:
    x: float
    y: float
`;
    const r = runPy(src);
    const ann = r.candidates.filter(
      (c) => c.kind === "ANNOTATES" && c.target.shortName === "dataclass",
    );
    expect(ann.length).toBeGreaterThan(0);
    expect(ann[0]!.target.externalFallback).toBe(true);
  });

  test("@pytest.fixture (attribute form, imported) emits ANNOTATES candidate with externalFallback", () => {
    const src = `import pytest

@pytest.fixture
def my_fixture():
    return 42
`;
    const r = runPy(src);
    const ann = r.candidates.filter(
      (c) => c.kind === "ANNOTATES" && c.target.shortName === "fixture",
    );
    expect(ann.length).toBeGreaterThan(0);
    expect(ann[0]!.target.externalFallback).toBe(true);
  });

  test("@app.route() call form (imported) emits ANNOTATES candidate with externalFallback", () => {
    const src = `from flask import Flask
app = Flask(__name__)

@app.route("/")
def index():
    return "hello"
`;
    const r = runPy(src);
    const ann = r.candidates.filter(
      (c) => c.kind === "ANNOTATES" && c.target.shortName === "route",
    );
    expect(ann.length).toBeGreaterThan(0);
    expect(ann[0]!.target.externalFallback).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// Resolver behaviour
// ---------------------------------------------------------------------------

describe("SymbolResolver", () => {
  test("returns null when target name is not in the index", () => {
    const r = new SymbolResolver();
    expect(r.resolve({ kinds: ["class"], shortName: "Missing" }, "repo")).toBeNull();
  });

  test("prefers scoped match when scopeQn is set", () => {
    const r = new SymbolResolver();
    // Two fields named "name" in two different classes.
    r.add({
      id: "id-A-name", kind: "field", language: "ts", repo: "repo",
      qualified_name: "f.ts::A::name", short_name: "name",
      file: "f.ts", line: 0, col: 0, end_line: 0, end_col: 0,
      signature: null, visibility: null, is_abstract: false, is_static: false,
      ast_hash: null, branch: "main", source: "tree_sitter",
    });
    r.add({
      id: "id-B-name", kind: "field", language: "ts", repo: "repo",
      qualified_name: "f.ts::B::name", short_name: "name",
      file: "f.ts", line: 0, col: 0, end_line: 0, end_col: 0,
      signature: null, visibility: null, is_abstract: false, is_static: false,
      ast_hash: null, branch: "main", source: "tree_sitter",
    });
    const idA = r.resolve(
      { kinds: ["field"], shortName: "name", scopeQn: "f.ts::A" }, "repo",
    );
    expect(idA).toBe("id-A-name");
    const idB = r.resolve(
      { kinds: ["field"], shortName: "name", scopeQn: "f.ts::B" }, "repo",
    );
    expect(idB).toBe("id-B-name");
  });

  test("namespace qualifier disambiguates same-named classes (new ns.Foo())", () => {
    const r = new SymbolResolver();
    // Two classes named "Foo": one inside namespace `ns`, one top-level.
    r.add({
      id: "id-ns-Foo", kind: "class", language: "ts", repo: "repo",
      qualified_name: "f.ts::ns::Foo", short_name: "Foo",
      file: "f.ts", line: 0, col: 0, end_line: 0, end_col: 0,
      signature: null, visibility: null, is_abstract: false, is_static: false,
      ast_hash: null, branch: "main", source: "tree_sitter",
    });
    r.add({
      id: "id-top-Foo", kind: "class", language: "ts", repo: "repo",
      qualified_name: "f.ts::Foo", short_name: "Foo",
      file: "f.ts", line: 0, col: 0, end_line: 0, end_col: 0,
      signature: null, visibility: null, is_abstract: false, is_static: false,
      ast_hash: null, branch: "main", source: "tree_sitter",
    });
    // `new ns.Foo()` carries scopeQn="ns" → prefer the namespaced class.
    const idNs = r.resolve(
      { kinds: ["class", "interface"], shortName: "Foo", scopeQn: "ns" }, "repo",
    );
    expect(idNs).toBe("id-ns-Foo");
    // `new Foo()` (no qualifier) falls back to best-effort first match.
    const idPlain = r.resolve(
      { kinds: ["class", "interface"], shortName: "Foo" }, "repo",
    );
    expect(idPlain).toBe("id-ns-Foo");
    // An unknown qualifier finds no namespaced match → best-effort first.
    const idMiss = r.resolve(
      { kinds: ["class", "interface"], shortName: "Foo", scopeQn: "other" }, "repo",
    );
    expect(idMiss).toBe("id-ns-Foo");
  });
});

// ---------------------------------------------------------------------------
// PHP inheritance edges (bead MetaCoding-1xd): EXTENDS / IMPLEMENTS / USES_TRAIT
// ---------------------------------------------------------------------------
import { extractPhp } from "./php";

describe("PHP inheritance edge candidates", () => {
  let phpParser: TsParser;
  beforeAll(async () => { phpParser = await makeParser("php"); });

  function candidates(src: string) {
    const tree = phpParser.parse(src)!;
    const ex = extractPhp(tree, { filePath: "src/A.php", branch: "main", repo: "r" });
    const er = extractEdgeCandidates(tree, { language: "php", filePath: "src/A.php", symbols: ex.symbols });
    tree.delete();
    return { candidates: er.candidates, symbols: ex.symbols };
  }

  const SRC = `<?php
namespace Drupal\\asset\\Entity;
class Asset extends ContentEntityBase implements AssetInterface, EntityOwnerInterface {
    use EntityChangedTrait;
    use StringTranslationTrait;
}
interface AssetInterface extends EntityInterface, EntityChangedInterface {}
`;

  test("emits EXTENDS to the base class (external boundary)", () => {
    const { candidates: cs } = candidates(SRC);
    const ext = cs.filter((c) => c.kind === "EXTENDS").map((c) => c.target.shortName);
    expect(ext).toContain("ContentEntityBase");       // class extends
    expect(ext).toContain("EntityInterface");          // interface extends
    expect(ext).toContain("EntityChangedInterface");
    for (const c of cs.filter((c) => c.kind === "EXTENDS")) {
      expect(c.target.externalFallback).toBe(true);
    }
  });

  test("emits IMPLEMENTS for each interface", () => {
    const { candidates: cs } = candidates(SRC);
    const impl = cs.filter((c) => c.kind === "IMPLEMENTS").map((c) => c.target.shortName).sort();
    expect(impl).toEqual(["AssetInterface", "EntityOwnerInterface"]);
  });

  test("emits USES_TRAIT for each trait", () => {
    const { candidates: cs } = candidates(SRC);
    const traits = cs.filter((c) => c.kind === "USES_TRAIT").map((c) => c.target.shortName).sort();
    expect(traits).toEqual(["EntityChangedTrait", "StringTranslationTrait"]);
  });

  test("src of each edge is the declaring type symbol", () => {
    const { candidates: cs, symbols } = candidates(SRC);
    const asset = symbols.find((s) => s.short_name === "Asset")!;
    const assetEdges = cs.filter((c) => c.src_id === asset.id);
    // Asset has: 1 extends + 2 implements + 2 traits = 5 candidates.
    expect(assetEdges.length).toBe(5);
  });
});

// ---------------------------------------------------------------------------
// PHP field-access edges (bead MetaCoding-vju): synthesized READS_FIELD /
// WRITES_FIELD, since scip-php emits no ReadAccess/WriteAccess roles. Covers
// $this->field / $obj->prop assignments + reads, augmented assignment,
// Drupal ->set('field',…)/->get('field') accessors, $entity->field_* idioms,
// and a negative case (local variable write is not a field edge).
// ---------------------------------------------------------------------------
describe("PHP field-access edge candidates", () => {
  let phpParser: TsParser;
  beforeAll(async () => { phpParser = await makeParser("php"); });

  function candidates(src: string) {
    const tree = phpParser.parse(src)!;
    const ex = extractPhp(tree, { filePath: "src/A.php", branch: "main", repo: "r" });
    const er = extractEdgeCandidates(tree, { language: "php", filePath: "src/A.php", symbols: ex.symbols });
    const resolver = new SymbolResolver();
    for (const s of ex.symbols) resolver.add(s);
    tree.delete();
    return { candidates: er.candidates, symbols: ex.symbols, resolver };
  }

  // Resolved edges from a declared property (`$this->bar` where bar is a field).
  const SRC = `<?php
class Widget {
    private $bar;
    private $count;
    public function m() {
        $this->bar = 1;
        $x = $this->bar;
        $this->count += 2;
        $obj->prop = 5;
        $local = 3;
    }
}
`;

  test("$this->field = X emits WRITES_FIELD resolving to the declared property", () => {
    const { candidates: cs, resolver } = candidates(SRC);
    const w = cs.filter(
      (c) => c.kind === "WRITES_FIELD" && c.target.shortName === "bar",
    );
    expect(w.length).toBe(1);
    // Resolves to the in-class field via scopeQn (Widget::bar).
    expect(resolver.resolve(w[0]!.target, "r")).not.toBeNull();
    expect(w[0]!.target.scopeQn).toContain("Widget");
  });

  test("$this->field read emits READS_FIELD (not on the assignment LHS)", () => {
    const { candidates: cs } = candidates(SRC);
    const reads = cs.filter(
      (c) => c.kind === "READS_FIELD" && c.target.shortName === "bar",
    );
    // Exactly one read of bar (the `$x = $this->bar` line); the LHS write of
    // `$this->bar = 1` must NOT also count as a read.
    expect(reads.length).toBe(1);
  });

  test("augmented assignment $this->count += 2 emits BOTH write and read", () => {
    const { candidates: cs } = candidates(SRC);
    const w = cs.filter((c) => c.kind === "WRITES_FIELD" && c.target.shortName === "count");
    const r = cs.filter((c) => c.kind === "READS_FIELD" && c.target.shortName === "count");
    expect(w.length).toBe(1);
    expect(r.length).toBe(1);
  });

  test("$obj->prop = 5 emits WRITES_FIELD (non-this receiver, no scope hint)", () => {
    const { candidates: cs } = candidates(SRC);
    const w = cs.filter((c) => c.kind === "WRITES_FIELD" && c.target.shortName === "prop");
    expect(w.length).toBe(1);
    expect(w[0]!.target.scopeQn).toBeUndefined();
  });

  test("negative: a plain local variable write ($local = 3) emits no field edge", () => {
    const { candidates: cs } = candidates(SRC);
    const bogus = cs.filter(
      (c) =>
        (c.kind === "WRITES_FIELD" || c.kind === "READS_FIELD") &&
        c.target.shortName === "local",
    );
    expect(bogus.length).toBe(0);
  });

  // Drupal accessor + entity-field idioms — kept via external boundary nodes.
  const DRUPAL = `<?php
class AssetController {
    public function handle($entity) {
        $entity->set('field_notes', 'hello');
        $note = $entity->get('field_notes');
        $entity->field_status = 'active';
        $s = $entity->field_status;
    }
}
`;

  test("->set('field', …) emits WRITES_FIELD with externalFallback keyed on the string", () => {
    const { candidates: cs } = candidates(DRUPAL);
    const w = cs.filter(
      (c) => c.kind === "WRITES_FIELD" && c.target.shortName === "field_notes",
    );
    expect(w.length).toBe(1);
    expect(w[0]!.target.externalFallback).toBe(true);
  });

  test("->get('field') emits READS_FIELD with externalFallback keyed on the string", () => {
    const { candidates: cs } = candidates(DRUPAL);
    const r = cs.filter(
      (c) => c.kind === "READS_FIELD" && c.target.shortName === "field_notes",
    );
    expect(r.length).toBe(1);
    expect(r[0]!.target.externalFallback).toBe(true);
  });

  test("$entity->field_* member access is treated as an entity field (externalFallback)", () => {
    const { candidates: cs } = candidates(DRUPAL);
    const w = cs.filter((c) => c.kind === "WRITES_FIELD" && c.target.shortName === "field_status");
    const r = cs.filter((c) => c.kind === "READS_FIELD" && c.target.shortName === "field_status");
    expect(w.length).toBe(1);
    expect(w[0]!.target.externalFallback).toBe(true);
    expect(r.length).toBe(1);
    expect(r[0]!.target.externalFallback).toBe(true);
  });
});
