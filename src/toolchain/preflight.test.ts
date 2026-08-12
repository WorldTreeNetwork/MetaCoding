// F3.2, F3.3, F3.4 — and the live check that puts this mechanism on `bun test`.
//
// docs/design/lessons-as-mechanism.md:163-165. F3.2 is the one the design
// document calls "the single most important fixture in the document", because
// the failure it catches is invisible: the check runs, reports OK, and is
// measuring itself.
//
//   > "If identity.ts reads package.json versions instead of hashing the loaded
//   >  artifact, it is a declaration validating itself and it will pass forever."
//
// So F3.2 below does the real thing: it builds an install root out of a COPY of
// the real .wasm blob, mutates the BLOB, leaves package.json BYTE-IDENTICAL,
// and asserts the outcome moves. The assertion that package.json did not change
// is part of the fixture, not decoration — without it the pair proves only that
// something changed, and "something" is what a version comparison also sees.

import { afterAll, beforeAll, describe, expect, test } from "bun:test";
import { copyFileSync, mkdirSync, mkdtempSync, readFileSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { discriminate } from "../testkit/discriminate.ts";
import { digestBytes, repoRoot, wasmDirFrom } from "./identity.ts";
import {
  type LaneOutcome,
  type Lockfile,
  PreflightRefused,
  assertToolchain,
  observeToolchain,
  readLockfile,
  relock,
} from "./preflight.ts";

const ROOT = repoRoot();
const REAL_LOCK = join(ROOT, "toolchain.lock.json");
const REAL_PHP_WASM = join(wasmDirFrom(ROOT), "tree-sitter-php.wasm");
const PHP_REL = "node_modules/tree-sitter-wasms/out/tree-sitter-php.wasm";

let sandbox: string;
let sandboxLock: string;
let manifestPath: string;
let sandboxWasm: string;

beforeAll(() => {
  // A whole-repo copy is not needed and the volume is nearly full: copy exactly
  // the two files this fixture mutates and reads.
  sandbox = mkdtempSync(join(tmpdir(), "toolchain-f32-"));
  mkdirSync(join(sandbox, "node_modules", "tree-sitter-wasms", "out"), { recursive: true });
  sandboxWasm = join(sandbox, PHP_REL);
  copyFileSync(REAL_PHP_WASM, sandboxWasm);
  manifestPath = join(sandbox, "node_modules", "tree-sitter-wasms", "package.json");
  writeFileSync(manifestPath, JSON.stringify({ name: "tree-sitter-wasms", version: "0.1.13" }));

  const declared = digestBytes(readFileSync(REAL_PHP_WASM));
  const lock: Lockfile = {
    version: 1,
    lanes: { "tree-sitter:php": { kind: "file", source: PHP_REL, digest: declared } },
  };
  sandboxLock = join(sandbox, "toolchain.lock.json");
  writeFileSync(sandboxLock, JSON.stringify(lock));
});

afterAll(() => {
  rmSync(sandbox, { recursive: true, force: true });
});

function phpOutcome(root: string, lockPath: string): LaneOutcome {
  const r = observeToolchain({ root, lockPath, inspectDocker: () => null });
  return r.lanes.find((l) => l.lane === "tree-sitter:php")!.outcome;
}

describe("F3.2 — the digest comes from the ARTIFACT, not the declaration", () => {
  test("mutating the .wasm bytes with package.json untouched moves the outcome", async () => {
    const manifestBefore = readFileSync(manifestPath);

    await discriminate<"pristine" | "mutated">({
      name: "a grammar blob edited in place is seen, though its manifest never moved",
      verdict: (state) => {
        if (state === "pristine") copyFileSync(REAL_PHP_WASM, sandboxWasm);
        else {
          // A grammar upgrade, in the only form that matters to a parse: the
          // bytes the loader will read are different ones.
          const bytes = readFileSync(REAL_PHP_WASM);
          bytes[bytes.length - 1] = bytes[bytes.length - 1]! ^ 0xff;
          writeFileSync(sandboxWasm, bytes);
        }
        return phpOutcome(sandbox, sandboxLock);
      },
      cases: { OK: "pristine", DRIFT: "mutated" },
    });

    // THE HALF THAT MAKES THIS FIXTURE DISCRIMINATE. A version comparison would
    // have reported OK across both cases, because this file never changed.
    expect(readFileSync(manifestPath)).toEqual(manifestBefore);
    expect(JSON.parse(manifestBefore.toString()).version).toBe("0.1.13");
  });

  test("MISSING: the declared artifact is not on disk — a failure, not a skip", () => {
    rmSync(sandboxWasm);
    expect(phpOutcome(sandbox, sandboxLock)).toBe("MISSING");
    expect(observeToolchain({ root: sandbox, lockPath: sandboxLock }).ok).toBe(false);
    copyFileSync(REAL_PHP_WASM, sandboxWasm); // restore for the OK contrast below
    expect(phpOutcome(sandbox, sandboxLock)).toBe("OK");
  });
});

describe("F3.3 — a lock that checks nothing is a FAILURE, never a pass", () => {
  const cases: Array<[string, string, string]> = [
    ["LOCK_EMPTY", "empty.json", JSON.stringify({ version: 1, lanes: {} })],
    ["LOCK_UNPARSEABLE", "bad.json", "{not json"],
    ["LOCK_MALFORMED", "nolanes.json", JSON.stringify({ version: 1 })],
    [
      "LOCK_MALFORMED",
      "unknownkind.json",
      JSON.stringify({ version: 1, lanes: { x: { kind: "wasm", source: "s", digest: null, why: "w" } } }),
    ],
    [
      "LOCK_MALFORMED",
      "silentunpinned.json",
      JSON.stringify({ version: 1, lanes: { x: { kind: "file", source: "s", digest: null } } }),
    ],
    [
      "LOCK_MALFORMED",
      "placeholder.json",
      JSON.stringify({ version: 1, lanes: { x: { kind: "file", source: "s", digest: "TODO" } } }),
    ],
  ];

  for (const [kind, name, body] of cases) {
    test(`${name} -> ${kind}`, () => {
      const p = join(sandbox, name);
      writeFileSync(p, body);
      try {
        readLockfile(p);
        throw new Error(`expected ${kind}, got a parsed lockfile`);
      } catch (e) {
        expect(e).toBeInstanceOf(PreflightRefused);
        expect((e as PreflightRefused).kind).toBe(kind as never);
      }
    });
  }

  test("LOCK_UNREADABLE: an absent lock is a refusal, not an empty clean run", () => {
    expect(() => readLockfile(join(sandbox, "nope.json"))).toThrow(PreflightRefused);
  });

  test("CONTRAST: the real committed lock parses and declares its lanes", () => {
    const lock = readLockfile(REAL_LOCK);
    expect(Object.keys(lock.lanes).length).toBeGreaterThanOrEqual(8);
  });
});

describe("F3.4 — three outcomes from one docker code path, three distinct tags", () => {
  const image = "davidrjenni/scip-php:latest";
  const declared = "sha256:" + "d".repeat(64);
  const drifted = "sha256:" + "e".repeat(64);

  function lockWith(digest: string | null): string {
    const p = join(sandbox, `docker-${digest === null ? "unpinned" : digest.slice(7, 13)}.json`);
    const lane =
      digest === null
        ? { kind: "docker" as const, source: image, digest: null, why: "not pulled here" }
        : { kind: "docker" as const, source: image, digest };
    writeFileSync(p, JSON.stringify({ version: 1, lanes: { "docker:scip-php": lane } }));
    return p;
  }

  const pinned = () => lockWith(declared);

  test("unavailable / drifted / matching are three named outcomes", async () => {
    await discriminate<{ lock: string; inspect: () => string | null }>({
      name: "docker lane: no answer is not no drift",
      verdict: ({ lock, inspect }) =>
        observeToolchain({ root: sandbox, lockPath: lock, inspectDocker: inspect })
          .lanes[0]!.outcome,
      cases: {
        SKIP_UNAVAILABLE: { lock: pinned(), inspect: () => null },
        DRIFT: { lock: pinned(), inspect: () => drifted },
        OK: { lock: pinned(), inspect: () => declared },
        UNPINNED: { lock: lockWith(null), inspect: () => declared },
      },
    });
  });

  test("a skip exits 0 by default and FAILS under --require-lanes", () => {
    const base = { root: sandbox, lockPath: pinned(), inspectDocker: () => null };
    expect(observeToolchain(base).ok).toBe(true);
    expect(observeToolchain({ ...base, requireLanes: true }).ok).toBe(false);
    // The skip is LOUD in both: the lane is named either way.
    expect(observeToolchain(base).lanes[0]!.detail).toContain(image);
  });

  test("an UNPINNED lane also exits 0 by default and FAILS under --require-lanes", () => {
    const base = { root: sandbox, lockPath: lockWith(null), inspectDocker: () => declared };
    expect(observeToolchain(base).ok).toBe(true);
    expect(observeToolchain({ ...base, requireLanes: true }).ok).toBe(false);
  });

  test("CONTRAST: drift fails whether or not --require-lanes is set", () => {
    const base = { root: sandbox, lockPath: pinned(), inspectDocker: () => drifted };
    expect(observeToolchain(base).ok).toBe(false);
    expect(observeToolchain({ ...base, requireLanes: true }).ok).toBe(false);
  });

  test("relock does NOT unpin a lane just because the daemon is down", () => {
    const next = relock({ root: sandbox, lockPath: pinned(), inspectDocker: () => null });
    expect(next.lanes["docker:scip-php"]!.digest).toBe(declared);
  });
});

describe("the live check — this is what puts the mechanism on `bun test`", () => {
  test("the installed toolchain matches the committed toolchain.lock.json", () => {
    // If `bun install` resolves a different grammar, THIS goes red. That is the
    // whole point of bead 0bm: before it, the same event was silent and every
    // sealed entry stayed a cache hit.
    const r = assertToolchain({ root: ROOT, lockPath: REAL_LOCK });
    expect(r.counts.DRIFT).toBe(0);
    expect(r.counts.MISSING).toBe(0);
    // Every grammar the walker loads is declared AND matching.
    for (const g of ["typescript", "tsx", "python", "php"]) {
      const lane = r.lanes.find((l) => l.lane === `tree-sitter:${g}`);
      expect(lane?.outcome).toBe("OK");
    }
  });

  test("what is NOT checked here is named, not implied", () => {
    const r = observeToolchain({ root: ROOT, lockPath: REAL_LOCK });
    const loud = r.lanes.filter(
      (l) => l.outcome === "UNPINNED" || l.outcome === "SKIP_UNAVAILABLE",
    );
    // This assertion is deliberately about the SHAPE, not the count: on a
    // machine that has pulled scip-php it is 0, here it is 1. What must hold
    // everywhere is that an unchecked lane carries a reason a reader can act on.
    for (const l of loud) expect(l.detail.length).toBeGreaterThan(20);
  });
});
