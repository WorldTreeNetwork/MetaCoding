// identity.ts — the digest of the artifact that was ACTUALLY LOADED, never the
// version string that was declared.
//
// WHY THIS FILE EXISTS (docs/design/lessons-as-mechanism.md, mechanism 3;
// bead MetaCoding-0bm; docs/design/within-file-coverage.md Part A)
// =====================================================================
// package.json:85 pinned `tree-sitter-wasms` as a CARET range (`^0.1.13`) and
// src/extractor/parser.ts loads `out/tree-sitter-<grammar>.wasm` from whatever
// that resolved to. `web-tree-sitter` sits four lines below it pinned EXACTLY
// at 0.22.6 — one right and one wrong in the same file, which is the strongest
// available argument that it was an oversight and not a policy.
//
// A grammar upgrade changes every parse tree, therefore every symbol and every
// edge, and MOVES NO KEY. `bun install` resolves 0.1.14; every layer-2 key is
// identical; every sealed entry is a cache hit; every derived CTKR artifact is
// now about a graph built by a different parser. Today: silent. That is
// docs/design/graph-as-cache.md:165 instantiated — "an input left out of the
// key is a dimension the cache is blind to" — and the mechanism-side twin of
// MetaCoding-855, where this project's own artifacts were derived from a graph
// with 430 phantom files nobody could see.
//
// THE ONE RULE THAT MAKES THIS MORE THAN A VERSION COMPARISON
// -----------------------------------------------------------
// > The digest is computed from the BYTES THE PROGRAM READ. Nothing in this
// > file reads a declared version range and calls it identity.
//
// lessons-as-mechanism.md:262 names the way this mechanism fakes itself, and
// it is the single most important line in the design document:
//
//     "If identity.ts reads package.json versions instead of hashing the
//      loaded artifact, it is a declaration validating itself and it will pass
//      forever. F3.2 exists precisely for this ... Note the shape — it is
//      failure 7 (source reading substituting for the boundary) reproduced
//      INSIDE the mechanism designed to prevent it."
//
// So `registerLoadedArtifact` is called from src/extractor/parser.ts:loadLanguage
// with the SAME `bytes` buffer that is handed to `Parser.Language.load`. There
// is no second read and no path-to-digest indirection where a stale or
// different file could substitute. A grammar that was parsed but not digested
// is not reachable: the digest happens between `readFileSync` and the load.
//
// WHICH SURFACE THIS SITS ON (docs/design/enforceability.md)
// ----------------------------------------------------------
// THE IMPORT PATH, deliberately, and secondarily `bun test`:
//   - the digest is taken inside the only function that reads a .wasm blob, so
//     you cannot parse without registering it;
//   - `layer2Key()` REFUSES to produce a key when no artifact was measured, so
//     you cannot key a parse-derived build while blind to the parser;
//   - src/toolchain/preflight.test.ts runs the real check against the real
//     node_modules under `bun test`, which is the habitual command.
// scripts/toolchain-preflight.ts is the human-runnable form. It is NOT the
// enforcing surface and this file does not pretend otherwise: enforceability.md
// records two gates built in three days that nothing called.
//
// WHAT THIS STILL DOES NOT CATCH
// -------------------------------
// A correct key over a broken extractor — every input hashed, every seal valid,
// every edge wrong (graph-as-cache.md:164). Unchanged, and not addressed here.
// Package lanes are weaker than grammar lanes: `digestPackage` covers the
// manifest bytes plus the entry-point bytes, so an edit deep inside a package
// that neither file references moves nothing. That is disclosed, not fixed —
// the lane 0bm is about (the .wasm blob) is digested WHOLE.

import { createHash } from "node:crypto";
import { readFileSync, statSync } from "node:fs";
import { dirname, isAbsolute, join, relative } from "node:path";

export const DIGEST_PREFIX = "sha256:";

/** Kinds of artifact a lane can name. Closed vocabulary. */
export type LaneKind = "file" | "package" | "docker";

/**
 * One measured artifact. `digest` is over the artifact's own bytes; `source`
 * is where it came from and is informational only — nothing keys off it.
 */
export interface ArtifactIdentity {
  lane: string;
  kind: LaneKind;
  source: string;
  digest: string;
  bytes?: number;
}

export type IdentityRefusalKind =
  | "NO_ARTIFACTS" // nothing was measured; a digest over nothing is not identity
  | "LANE_CONFLICT" // one lane, two different digests in one process
  | "MALFORMED_DIGEST" // a "digest" that is not sha256:<64 hex>
  | "EMPTY_LANE_NAME";

export class ToolchainIdentityRefused extends Error {
  readonly kind: IdentityRefusalKind;
  constructor(kind: IdentityRefusalKind, detail: string) {
    super(`${kind}: ${detail}`);
    this.name = "ToolchainIdentityRefused";
    this.kind = kind;
  }
}

/** sha256 over bytes, prefixed. The only place a digest is minted. */
export function digestBytes(bytes: Uint8Array | string): string {
  return DIGEST_PREFIX + createHash("sha256").update(bytes).digest("hex");
}

/** True for a well-formed digest string. */
export function isDigest(s: unknown): s is string {
  return typeof s === "string" && /^sha256:[0-9a-f]{64}$/.test(s);
}

// ---------------------------------------------------------------------------
// The registry: what this process actually loaded
// ---------------------------------------------------------------------------

const loaded = new Map<string, ArtifactIdentity>();

/**
 * Record an artifact this process loaded. Called from the loader itself, with
 * the same buffer the loader consumed.
 *
 * Re-registering a lane with the SAME digest is idempotent (a cached grammar
 * reload). Re-registering with a DIFFERENT digest is a LANE_CONFLICT and
 * throws: two different blobs behind one lane name in one process means every
 * key computed in it is ambiguous about which one it describes.
 */
export function registerLoadedArtifact(id: ArtifactIdentity): ArtifactIdentity {
  if (typeof id.lane !== "string" || id.lane.trim() === "") {
    throw new ToolchainIdentityRefused("EMPTY_LANE_NAME", "an artifact must name its lane");
  }
  if (!isDigest(id.digest)) {
    throw new ToolchainIdentityRefused(
      "MALFORMED_DIGEST",
      `lane "${id.lane}" was registered with ${JSON.stringify(id.digest)}, which ` +
        `is not sha256:<64 hex>. A digest-shaped string that is not a digest is ` +
        `a declaration wearing a measurement's clothes.`,
    );
  }
  const prior = loaded.get(id.lane);
  if (prior && prior.digest !== id.digest) {
    throw new ToolchainIdentityRefused(
      "LANE_CONFLICT",
      `lane "${id.lane}" was already measured as ${prior.digest} (${prior.source}) ` +
        `and is now ${id.digest} (${id.source}). Two blobs behind one lane name ` +
        `makes every key computed in this process ambiguous.`,
    );
  }
  loaded.set(id.lane, id);
  return id;
}

/** Everything measured in this process, sorted by lane. */
export function loadedArtifacts(): readonly ArtifactIdentity[] {
  return [...loaded.values()].sort((a, b) => (a.lane < b.lane ? -1 : a.lane > b.lane ? 1 : 0));
}

/** Clear the registry. For this module's own fixtures; never for a gate. */
export function resetLoadedArtifacts(): void {
  loaded.clear();
}

// ---------------------------------------------------------------------------
// Measuring artifacts
// ---------------------------------------------------------------------------

/** Digest a file by path, reading its bytes. Throws if it is not there. */
export function digestFile(path: string): { digest: string; bytes: number } {
  const bytes = readFileSync(path);
  return { digest: digestBytes(bytes), bytes: bytes.length };
}

/** Absolute path of `tree-sitter-wasms/out` as resolved from `root`. */
export function wasmDirFrom(root: string): string {
  return join(root, "node_modules", "tree-sitter-wasms", "out");
}

/** Lane name for a tree-sitter grammar. One lane per grammar, by construction. */
export function grammarLane(grammar: string): string {
  return `tree-sitter:${grammar}`;
}

/**
 * Measure an npm package: the manifest bytes plus the entry-point bytes.
 *
 * DISCLOSED WEAKNESS, repeated from the header because this is the point of
 * use: this does NOT digest the whole package tree. An edit inside a package
 * that neither the manifest nor the entry point contains moves nothing here.
 * It is still a measurement of bytes on disk rather than of the range in our
 * package.json, which is the distinction that matters for F3.2 — but it is a
 * partial one, and the grammar lanes (which 0bm is about) are digested whole.
 */
export function digestPackage(
  name: string,
  root: string,
): { digest: string; version: string; entry: string; bytes: number } {
  const pkgDir = join(root, "node_modules", ...name.split("/"));
  const manifestPath = join(pkgDir, "package.json");
  const manifestBytes = readFileSync(manifestPath);
  const manifest = JSON.parse(manifestBytes.toString("utf-8")) as {
    version?: string;
    main?: string;
    module?: string;
    bin?: string | Record<string, string>;
  };
  const version = typeof manifest.version === "string" ? manifest.version : "";

  const candidates: string[] = [];
  if (typeof manifest.main === "string") candidates.push(manifest.main);
  if (typeof manifest.module === "string") candidates.push(manifest.module);
  if (typeof manifest.bin === "string") candidates.push(manifest.bin);
  else if (manifest.bin && typeof manifest.bin === "object") {
    candidates.push(...Object.values(manifest.bin));
  }
  candidates.push("index.js");

  let entryPath = manifestPath;
  for (const c of candidates) {
    const p = isAbsolute(c) ? c : join(pkgDir, c);
    try {
      if (statSync(p).isFile()) {
        entryPath = p;
        break;
      }
    } catch {
      // keep looking; a manifest may name a file that is not shipped
    }
  }

  const entryBytes = entryPath === manifestPath ? manifestBytes : readFileSync(entryPath);
  const entry = relative(pkgDir, entryPath) || "package.json";
  const h = createHash("sha256");
  h.update(name).update("\n");
  h.update(version).update("\n");
  h.update(entry).update("\n");
  h.update(manifestBytes);
  h.update(entryBytes);
  return {
    digest: DIGEST_PREFIX + h.digest("hex"),
    version,
    entry,
    bytes: manifestBytes.length + (entryPath === manifestPath ? 0 : entryBytes.length),
  };
}

/** Where a docker lane's identity comes from. Injectable so the three
 *  outcomes of F3.4 are reachable without a daemon. */
export type DockerInspector = (image: string) => string | null;

/**
 * Ask the local docker daemon for an image's content id. Returns null when the
 * answer is UNAVAILABLE — daemon down, image not pulled, docker not installed.
 * Null means "no answer", which the preflight reports as a LOUD SKIP naming the
 * lane. It never means "no drift" (oracle_preflight.py:144's distinction).
 */
/**
 * How long to wait for the docker CLI before calling it UNAVAILABLE.
 *
 * NOT OPTIONAL, and the reason is measured (MetaCoding-9dg). With the daemon
 * unreachable the docker CLI BLOCKS rather than erroring, and a fresh judge
 * watched `bun test` sit at 2:17 on a live `docker image inspect` child it had to
 * kill by hand — the same command returned in 0.235s once the daemon recovered.
 * `bun test` is the only enforcing surface this project has (see
 * docs/design/enforceability.md), so an unbounded call here means the mechanism
 * can produce NO VERDICT AT ALL, which is strictly worse than a red one.
 *
 * This module reasoned carefully about a checker that reports clear when it could
 * not run, and then shipped one that could not report. A timeout is how "no
 * answer" stays an answer.
 */
const DOCKER_TIMEOUT_MS = 5_000;

/** The argv this asks docker for. A SEAM, so a fixture can point the call at a
 *  command that never returns and prove the timeout is real — without it the
 *  timeout is unreachable by any test on a machine where docker answers fast,
 *  which is how the first attempt at MetaCoding-9dg's guard proved nothing. */
export const dockerArgv = (image: string): string[] => [
  "docker", "image", "inspect", "--format", "{{.Id}}", image,
];

export const dockerImageId = (image: string, argv: string[] = dockerArgv(image)): string | null => {
  try {
    const proc = Bun.spawnSync(argv, {
      stdout: "pipe",
      stderr: "pipe",
      timeout: DOCKER_TIMEOUT_MS,
    });
    // A timeout kill lands here as a non-zero/!null exitCode or a signal; either
    // way it maps to the SAME null the daemon-down path returns, so the lane
    // becomes a LOUD SKIP naming itself rather than a hang or a false clear.
    if (proc.exitCode !== 0) return null;
    const out = proc.stdout.toString().trim();
    return /^sha256:[0-9a-f]{64}$/.test(out) ? out : null;
  } catch {
    return null;
  }
};

// ---------------------------------------------------------------------------
// The toolchain digest, and the layer-2 key it folds into
// ---------------------------------------------------------------------------

/**
 * A single digest over every artifact measured, lane names included.
 *
 * REFUSES an empty set. A toolchain digest computed over nothing is a constant,
 * and a constant folded into a key is an input the key is blind to — which is
 * the exact defect this module exists to remove, reproduced one level up. This
 * is oracle_preflight.py:351's rule ("a checker that parsed zero things is a
 * FAILURE, never a skip") applied to identity rather than to drift.
 */
export function toolchainDigest(
  artifacts: readonly ArtifactIdentity[] = loadedArtifacts(),
): string {
  if (artifacts.length === 0) {
    throw new ToolchainIdentityRefused(
      "NO_ARTIFACTS",
      "no toolchain artifact was measured, so there is nothing to key against. " +
        "A digest over zero artifacts is a constant, and a constant in a key is " +
        "a dimension the cache is blind to (graph-as-cache.md:165).",
    );
  }
  const sorted = [...artifacts].sort((a, b) =>
    a.lane < b.lane ? -1 : a.lane > b.lane ? 1 : 0,
  );
  const h = createHash("sha256");
  for (const a of sorted) {
    if (!isDigest(a.digest)) {
      throw new ToolchainIdentityRefused(
        "MALFORMED_DIGEST",
        `lane "${a.lane}" carries ${JSON.stringify(a.digest)}`,
      );
    }
    h.update(a.lane).update("\0").update(a.kind).update("\0").update(a.digest).update("\n");
  }
  return DIGEST_PREFIX + h.digest("hex");
}

/**
 * The layer-2 key inputs (docs/design/graph-as-cache.md:58-64), with
 * `toolchain_digest` beside `extractor_version` — which is bead 0bm.
 *
 * `toolchain_digest` is NOT a field of this interface on purpose: it cannot be
 * passed in, because a caller who can pass it can pass a stale one. It is
 * measured from the registry at key time.
 */
export interface Layer2Inputs {
  store_schema_version: string;
  extractor_version: string;
  recipe: string;
  tree_digest: string;
  /** Layer-1 KEYS of every .scip ingested — keys, not sha256s. */
  scip_layer1_keys: readonly string[];
  path_mapping: string;
  achieved_fidelity_profile: string;
}

/**
 * Compute the layer-2 key over the declared inputs AND the toolchain actually
 * loaded.
 *
 * `artifacts` defaults to the process registry, so the ordinary call site
 * cannot omit the toolchain. It is a parameter only so the discriminating
 * fixture can hold every other input fixed and move exactly one .wasm blob
 * (F3.1). Passing an EMPTY set throws — see `toolchainDigest`.
 */
export function layer2Key(
  inputs: Layer2Inputs,
  artifacts: readonly ArtifactIdentity[] = loadedArtifacts(),
): string {
  const toolchain = toolchainDigest(artifacts);
  const h = createHash("sha256");
  const field = (name: string, value: string): void => {
    h.update(name).update("\0").update(value).update("\n");
  };
  field("store_schema_version", inputs.store_schema_version);
  field("extractor_version", inputs.extractor_version);
  field("toolchain_digest", toolchain);
  field("recipe", inputs.recipe);
  field("tree_digest", inputs.tree_digest);
  for (const k of [...inputs.scip_layer1_keys].sort()) field("scip_layer1_key", k);
  field("path_mapping", inputs.path_mapping);
  field("achieved_fidelity_profile", inputs.achieved_fidelity_profile);
  return DIGEST_PREFIX + h.digest("hex");
}

/** The directory `identity` treats as the install root: this repo's own. */
export function repoRoot(): string {
  // src/toolchain/identity.ts -> src/toolchain -> src -> <root>
  return dirname(dirname(import.meta.dir));
}
