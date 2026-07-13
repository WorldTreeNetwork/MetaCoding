// Tests for the PHP tree-sitter extractor (extractPhp).

import { test, expect, describe, beforeAll } from "bun:test";

import { makeParser, type TsParser } from "./parser";
import { extractPhp } from "./php";
import type { Symbol } from "../store/types";

let phpParser: TsParser;

beforeAll(async () => {
  phpParser = await makeParser("php");
});

function extract(src: string) {
  const tree = phpParser.parse(src);
  if (!tree) throw new Error("parse returned null");
  const result = extractPhp(tree, {
    filePath: "src/app.php",
    branch: "main",
    repo: "fixture",
  });
  tree.delete();
  const byQn = new Map<string, Symbol>();
  for (const s of result.symbols) byQn.set(s.qualified_name, s);
  const contains = new Set(
    result.edges
      .filter((e) => e.kind === "CONTAINS")
      .map((e) => `${e.src_id}->${e.dst_id}`),
  );
  const isContained = (parentQn: string, childQn: string): boolean => {
    const p = byQn.get(parentQn);
    const c = byQn.get(childQn);
    return !!p && !!c && contains.has(`${p.id}->${c.id}`);
  };
  return { result, byQn, isContained };
}

const SRC = `<?php
namespace App\\Services;

interface Runner {
    public function run(int $x): int;
}

trait Loggable {
    public function log(string $m): void {}
}

abstract class Orchestrator implements Runner {
    public string $name = "demo";
    private int $count = 0;
    protected static $shared;

    public function __construct(string $name) {
        $this->name = $name;
    }

    public function run(int $x): int {
        return $x + 1;
    }

    public static function kind(): string {
        return "demo";
    }
}

function helper(int $x): int {
    return $x + 1;
}

enum Suit: string {
    case Hearts = 'H';
    case Spades = 'S';
}
`;

describe("extractPhp", () => {
  test("emits a file symbol", () => {
    const { byQn } = extract(SRC);
    const file = byQn.get("src/app.php");
    expect(file).toBeDefined();
    expect(file!.kind).toBe("file");
    expect(file!.language).toBe("php");
  });

  test("recognizes top-level declarations by kind", () => {
    const { result } = extract(SRC);
    const kinds = new Map(result.symbols.map((s) => [s.short_name, s.kind]));
    expect(kinds.get("Runner")).toBe("interface");
    expect(kinds.get("Loggable")).toBe("class"); // trait -> class
    expect(kinds.get("Orchestrator")).toBe("class");
    expect(kinds.get("helper")).toBe("function");
    expect(kinds.get("Suit")).toBe("enum");
    expect(kinds.get("App\\Services")).toBe("namespace");
  });

  test("class members are methods/fields contained by the class", () => {
    const { byQn, isContained } = extract(SRC);
    const cls = "src/app.php::Orchestrator";
    expect(byQn.get(`${cls}::run`)?.kind).toBe("method");
    expect(byQn.get(`${cls}::__construct`)?.kind).toBe("method");
    expect(byQn.get(`${cls}::name`)?.kind).toBe("field");
    expect(byQn.get(`${cls}::count`)?.kind).toBe("field");
    expect(isContained(cls, `${cls}::run`)).toBe(true);
    expect(isContained(cls, `${cls}::name`)).toBe(true);
  });

  test("captures visibility and static/abstract modifiers", () => {
    const { byQn } = extract(SRC);
    const cls = "src/app.php::Orchestrator";
    expect(byQn.get(`${cls}::count`)?.visibility).toBe("private");
    expect(byQn.get(`${cls}::name`)?.visibility).toBe("public");
    expect(byQn.get(`${cls}::shared`)?.is_static).toBe(true);
    expect(byQn.get(`${cls}::kind`)?.is_static).toBe(true);
    expect(byQn.get(`${cls}::run`)?.is_static).toBe(false);
  });

  test("enum cases become fields", () => {
    const { byQn } = extract(SRC);
    expect(byQn.get("src/app.php::Suit::Hearts")?.kind).toBe("field");
    expect(byQn.get("src/app.php::Suit::Spades")?.kind).toBe("field");
  });

  test("interface method is captured", () => {
    const { byQn } = extract(SRC);
    expect(byQn.get("src/app.php::Runner::run")?.kind).toBe("method");
  });

  test("collects identifier tokens for FTS", () => {
    const { result } = extract(SRC);
    const idents = result.tokens.filter((t) => t.kind === "identifier").map((t) => t.text);
    expect(idents).toContain("Orchestrator");
    expect(idents).toContain("helper");
  });
});
