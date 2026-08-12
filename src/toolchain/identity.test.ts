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
  isDigest,
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

  // FOUND BY MUTATION, not by design (M0 in the session recorded on this
  // commit). Replacing `inputs.extractor_version` with a literal SURVIVED the
  // whole suite: the key would have been blind to the extractor, which is the
  // exact defect 0bm is about, one field over. A key input nobody asserts is
  // an input the key can quietly stop having.
  test("EVERY declared input moves the key — one field at a time", () => {
    const baseline = layer2Key(SAME_TREE, artifactFor(real));
    const moved: Record<string, string> = {
      store_schema_version: "8",
      extractor_version: "2026-09-01",
      recipe: "tree-sitter-only",
      tree_digest: "sha256:" + "c".repeat(64),
      path_mapping: "prefixed",
      achieved_fidelity_profile: "partial",
    };
    for (const [field, value] of Object.entries(moved)) {
      const key = layer2Key({ ...SAME_TREE, [field]: value }, artifactFor(real));
      expect(`${field}:${key === baseline ? "UNMOVED" : "MOVED"}`).toBe(`${field}:MOVED`);
    }
    // The list itself is checked: a field added to Layer2Inputs and not to this
    // table would otherwise be silently unasserted.
    const declared = Object.keys(SAME_TREE).filter((k) => k !== "scip_layer1_keys");
    expect(Object.keys(moved).sort()).toEqual(declared.sort());
  });

  // ALSO FOUND BY MUTATION (M8): dropping the .sort() on scip_layer1_keys
  // survived. Two ingests of the same .scip set in different order must key the
  // same, or the key reports drift that did not happen.
  test("scip_layer1_keys: content moves the key, ORDER does not", () => {
    const k1 = "sha256:" + "1".repeat(64);
    const k2 = "sha256:" + "2".repeat(64);
    const ab = layer2Key({ ...SAME_TREE, scip_layer1_keys: [k1, k2] }, artifactFor(real));
    const ba = layer2Key({ ...SAME_TREE, scip_layer1_keys: [k2, k1] }, artifactFor(real));
    const only = layer2Key({ ...SAME_TREE, scip_layer1_keys: [k1] }, artifactFor(real));
    expect(ab).toBe(ba);
    expect(ab).not.toBe(only);
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

  // FOUND BY THE JUDGE'S MUTATION N1, and it is the more dangerous half.
  // Loosening isDigest from /^sha256:[0-9a-f]{64}$/ to /^sha256:/ SURVIVED all
  // 31 fixtures, because BOTH cases aimed at this guard ("0.1.13" here and
  // "TODO" in preflight.test.ts) fail on the PREFIX alone. Nothing asserted the
  // 64-hex half, so `sha256:TODO` — a placeholder that has learned to dress
  // like a measurement — would have entered the registry as identity. That is
  // the module's own header failure ("a declaration wearing a measurement's
  // clothes") with the costume improved.
  //
  // Every case here CARRIES THE PREFIX, so the prefix cannot be what refuses
  // them; only the body can.
  test("MALFORMED_DIGEST: sha256:-PREFIXED non-digests are refused on the BODY", () => {
    const hex = "a".repeat(64);
    const refused: Record<string, string> = {
      placeholder: "sha256:TODO",
      empty_body: "sha256:",
      too_short: "sha256:" + "a".repeat(63),
      too_long: "sha256:" + "a".repeat(65),
      uppercase_hex: "sha256:" + "A".repeat(64),
      non_hex_char: "sha256:" + "g" + "a".repeat(63),
      trailing_space: "sha256:" + hex + " ",
      version_with_prefix: "sha256:0.1.13",
    };
    for (const [why, digest] of Object.entries(refused)) {
      let kind = "ACCEPTED";
      try {
        registerLoadedArtifact({ lane: `n1-${why}`, kind: "file", source: "a", digest });
      } catch (e) {
        kind = (e as ToolchainIdentityRefused).kind;
      }
      expect(`${why}:${kind}`).toBe(`${why}:MALFORMED_DIGEST`);
    }
    // CONTRAST, in the same shape: the one string that differs from
    // "sha256:<63 a>" by a single character IS accepted. Without this the test
    // above would pass against a guard that refuses everything.
    expect(
      registerLoadedArtifact({ lane: "n1-ok", kind: "file", source: "a", digest: "sha256:" + hex })
        .digest,
    ).toBe("sha256:" + hex);
    expect(isDigest("sha256:" + hex)).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// THE BINDING BETWEEN THE REGISTRY AND THE KEY — bead MetaCoding-0bd.
//
// Every fixture above passes `artifacts` EXPLICITLY. The ordinary call site
// does not: it relies on `artifacts = loadedArtifacts()` defaulting, and that
// default is the entire link between what the loader measured and what the key
// folds in. A fresh adversary mutated it four ways — to `[]` (N12 on
// toolchainDigest, N13 on layer2Key), to a CONSTANT ArtifactIdentity (N18), and
// by having loadedArtifacts() invent a constant when nothing was measured (N19)
// — and ALL FOUR SURVIVED all 31 fixtures. Under N18 every key at the ordinary
// call site is folded over a frozen digest and NO_ARTIFACTS can never fire:
// bead 0bm's own defect, reproduced inside the fix, with a green suite watching.
//
// identity.ts:330 stated the link as PROSE ("the ordinary call site cannot omit
// the toolchain") and no test implemented that sentence. This is that sentence,
// implemented. It needs all three legs — the refusal, the equality, and the
// difference — because each mutant survives some pair of them:
//   REFUSAL   with an empty registry kills N18 and N19 (a constant never refuses)
//   EQUALITY  to the explicit call kills N12, N13 and N18 (a wrong set never matches)
//   DIFFERENCE from another set kills a default that returns something constant
// ---------------------------------------------------------------------------
describe("F3.1b — the DEFAULT argument is the link, and it is measured", () => {
  test("empty registry -> layer2Key(inputs) with NO second argument REFUSES", () => {
    resetLoadedArtifacts();
    expect(loadedArtifacts().length).toBe(0);
    let kind = "COMPUTED";
    try {
      layer2Key(SAME_TREE);
    } catch (e) {
      kind = (e as ToolchainIdentityRefused).kind;
    }
    expect(kind).toBe("NO_ARTIFACTS");
    // and the same for the digest itself, which carries the refusal
    expect(() => toolchainDigest()).toThrow(ToolchainIdentityRefused);
  });

  test("after makeParser('php'), the DEFAULT key equals the EXPLICIT php key", async () => {
    resetLoadedArtifacts();
    const { makeParser } = await import("../extractor/parser.ts");
    await makeParser("php");

    const measured = loadedArtifacts();
    expect(measured.map((a) => a.lane)).toEqual([grammarLane("php")]);

    // THE LOAD-BEARING LINE: no second argument. If the default is `[]` this
    // throws; if the default is a constant this is unequal; if the default is
    // the registry this is the same key by construction.
    const viaDefault = layer2Key(SAME_TREE);
    const viaExplicit = layer2Key(SAME_TREE, artifactFor(readFileSync(REAL_PHP_WASM)));
    expect(viaDefault).toBe(viaExplicit);
    expect(toolchainDigest()).toBe(toolchainDigest(measured));

    // CONTRAST: and it is not equal to just any set. A default that returned a
    // constant would satisfy the equality above only by accident and would fail
    // here — this is the leg that refuses "make them all the same".
    const upgraded = Uint8Array.from(readFileSync(REAL_PHP_WASM));
    upgraded[0] = upgraded[0]! ^ 0xff;
    expect(viaDefault).not.toBe(layer2Key(SAME_TREE, artifactFor(upgraded)));
    expect(viaDefault).not.toBe(
      layer2Key(SAME_TREE, [
        { lane: "other", kind: "file", source: "s", digest: digestBytes("other") },
      ]),
    );
  });

  test("the default TRACKS the registry: registering a second lane moves the key", async () => {
    resetLoadedArtifacts();
    const { makeParser } = await import("../extractor/parser.ts");
    await makeParser("php");
    const before = layer2Key(SAME_TREE);
    registerLoadedArtifact({
      lane: "zz:extra",
      kind: "file",
      source: "s",
      digest: digestBytes("extra"),
    });
    const after = layer2Key(SAME_TREE);
    expect(after).not.toBe(before);
    resetLoadedArtifacts();
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

  // THE REGRESSION FIXTURE FOR THE HOLE THE FULL SUITE FOUND. The first version
  // of parser.ts registered only on the cache MISS, so this test passed alone
  // and failed in `bun test` — a php grammar loaded by an earlier file meant the
  // second caller got a parser with NO measurement behind it, and a key computed
  // there would have been blind to the grammar. Loading twice around a reset is
  // that situation, made deliberate.
  test("a CACHED grammar is still measured — the second load registers too", async () => {
    const { makeParser } = await import("../extractor/parser.ts");
    await makeParser("php"); // populate the language cache
    resetLoadedArtifacts(); // the registry now knows nothing
    await makeParser("php"); // served from cache — must still register
    const php = loadedArtifacts().find((a) => a.lane === grammarLane("php"));
    expect(php?.digest).toBe(digestBytes(readFileSync(REAL_PHP_WASM)));
  });
});
