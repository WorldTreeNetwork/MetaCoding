// F3.1 and the half of F3.2 that is about the KEY rather than the preflight.
//
// docs/design/lessons-as-mechanism.md:162-163, bead MetaCoding-0bm evidence #8.
//
// The property under test, stated as a property rather than as a defect:
//
//   > A key computed over a parse cannot be equal across two different parsers,
//   > and cannot differ across two identical ones.
//
// Both halves are load-bearing. A key function that hashes a timestamp passes
// the first half and fails the second; a key function that ignores the toolchain
// entirely passes the second and fails the first. Neither half alone
// discriminates.

import { describe, expect, test, beforeEach } from "bun:test";
import { readFileSync } from "node:fs";
import { join } from "node:path";

import { discriminate } from "../testkit/discriminate.ts";
import {
  type ArtifactIdentity,
  type Layer2Inputs,
  ToolchainIdentityRefused,
  digestBytes,
  grammarLane,
  layer2Key,
  loadedArtifacts,
  registerLoadedArtifact,
  repoRoot,
  resetLoadedArtifacts,
  toolchainDigest,
  wasmDirFrom,
} from "./identity.ts";

const REAL_PHP_WASM = join(wasmDirFrom(repoRoot()), "tree-sitter-php.wasm");

/** Every input to the key EXCEPT the toolchain, held fixed across the pair. */
const SAME_TREE: Layer2Inputs = {
  store_schema_version: "7",
  extractor_version: "2026-08-12",
  recipe: "tree-sitter+scip",
  tree_digest: "sha256:" + "a".repeat(64),
  scip_layer1_keys: ["sha256:" + "b".repeat(64)],
  path_mapping: "identity",
  achieved_fidelity_profile: "complete",
};

function artifactFor(bytes: Uint8Array): ArtifactIdentity[] {
  return [
    {
      lane: grammarLane("php"),
      kind: "file",
      source: "tree-sitter-php.wasm",
      digest: digestBytes(bytes),
    },
  ];
}

describe("F3.1 — the key moves with the grammar, and only with the grammar", () => {
  const real = readFileSync(REAL_PHP_WASM);
  // A DIFFERENT BLOB, produced the way a grammar upgrade produces one: the same
  // file with different bytes in it. One flipped byte is enough to prove the
  // key is over content; a whole 0.1.14 blob would prove nothing extra and
  // would need a network.
  const upgraded = Uint8Array.from(real);
  upgraded[upgraded.length - 1] = upgraded[upgraded.length - 1]! ^ 0xff;
  // A byte-identical SECOND READ, standing in for "the same install, twice".
  const same = readFileSync(REAL_PHP_WASM);

  test("two different wasm blobs over one tree produce DIFFERENT keys", () => {
    const a = layer2Key(SAME_TREE, artifactFor(real));
    const b = layer2Key(SAME_TREE, artifactFor(upgraded));
    expect(a).not.toBe(b);
  });

  test("CONTRAST: identical wasm over one tree produces an IDENTICAL key", () => {
    const a = layer2Key(SAME_TREE, artifactFor(real));
    const b = layer2Key(SAME_TREE, artifactFor(same));
    expect(a).toBe(b);
    // And the contrast is not vacuous: the two byte arrays are separate reads.
    expect(real).not.toBe(same);
  });

  test("the pair, as one discrimination — MOVED vs UNMOVED, named", async () => {
    const baseline = layer2Key(SAME_TREE, artifactFor(real));
    await discriminate<Uint8Array>({
      name: "layer-2 key is a function of the grammar bytes",
      verdict: (blob) => (layer2Key(SAME_TREE, artifactFor(blob)) === baseline ? "UNMOVED" : "MOVED"),
      cases: {
        UNMOVED: same, // identical bytes, independently read
        MOVED: upgraded, // one byte different, everything else held fixed
      },
    });
  });

  test("a non-toolchain input still moves the key (the key is not JUST the toolchain)", () => {
    const a = layer2Key(SAME_TREE, artifactFor(real));
    const b = layer2Key({ ...SAME_TREE, tree_digest: "sha256:" + "c".repeat(64) }, artifactFor(real));
    expect(a).not.toBe(b);
  });
});

describe("a key over an unmeasured toolchain is refused, not computed", () => {
  test("NO_ARTIFACTS: an empty artifact set throws rather than hashing a constant", () => {
    expect(() => layer2Key(SAME_TREE, [])).toThrow(ToolchainIdentityRefused);
    try {
      layer2Key(SAME_TREE, []);
    } catch (e) {
      expect((e as ToolchainIdentityRefused).kind).toBe("NO_ARTIFACTS");
    }
  });

  test("CONTRAST: one measured artifact is enough to produce a key", () => {
    expect(layer2Key(SAME_TREE, artifactFor(readFileSync(REAL_PHP_WASM)))).toMatch(
      /^sha256:[0-9a-f]{64}$/,
    );
  });

  test("toolchainDigest is order-independent but NOT lane-name-independent", () => {
    const a: ArtifactIdentity = { lane: "x", kind: "file", source: "s", digest: digestBytes("1") };
    const b: ArtifactIdentity = { lane: "y", kind: "file", source: "s", digest: digestBytes("2") };
    expect(toolchainDigest([a, b])).toBe(toolchainDigest([b, a]));
    const renamed: ArtifactIdentity = { ...b, lane: "z" };
    expect(toolchainDigest([a, b])).not.toBe(toolchainDigest([a, renamed]));
  });
});

describe("the registry refuses what would make a key ambiguous", () => {
  beforeEach(() => resetLoadedArtifacts());

  test("LANE_CONFLICT: one lane, two blobs, in one process", () => {
    registerLoadedArtifact({ lane: "l", kind: "file", source: "a", digest: digestBytes("1") });
    expect(() =>
      registerLoadedArtifact({ lane: "l", kind: "file", source: "b", digest: digestBytes("2") }),
    ).toThrow(/LANE_CONFLICT/);
  });

  test("CONTRAST: re-registering the SAME digest is idempotent, as a cached reload is", () => {
    registerLoadedArtifact({ lane: "l", kind: "file", source: "a", digest: digestBytes("1") });
    registerLoadedArtifact({ lane: "l", kind: "file", source: "a", digest: digestBytes("1") });
    expect(loadedArtifacts().length).toBe(1);
  });

  test("MALFORMED_DIGEST: a version string cannot be registered as identity", () => {
    // The whole failure mode in one line: "0.1.13" is a declaration, not a
    // measurement, and it may not enter the registry wearing a digest's slot.
    expect(() =>
      registerLoadedArtifact({ lane: "l", kind: "file", source: "a", digest: "0.1.13" }),
    ).toThrow(/MALFORMED_DIGEST/);
  });
});

describe("the loader registers the blob it loaded (the import-path half)", () => {
  test("makeParser('php') leaves a php lane digest equal to the file on disk", async () => {
    resetLoadedArtifacts();
    const { makeParser } = await import("../extractor/parser.ts");
    await makeParser("php");
    const php = loadedArtifacts().find((a) => a.lane === grammarLane("php"));
    expect(php).toBeDefined();
    // The digest is over the SAME BYTES the parser consumed — which is why this
    // compares against a fresh read of the file rather than against the lock.
    expect(php!.digest).toBe(digestBytes(readFileSync(REAL_PHP_WASM)));
  });
});
