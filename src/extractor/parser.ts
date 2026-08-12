// Tree-sitter parser cache.
//
// Loads grammar .wasm files from tree-sitter-wasms once per language and
// hands out parsers configured with that grammar. Wraps the runtime init
// dance from web-tree-sitter so callers see one async makeParser().

import { readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { dirname, join } from "node:path";

import Parser from "web-tree-sitter";

import {
  type ArtifactIdentity,
  digestBytes,
  grammarLane,
  registerLoadedArtifact,
} from "../toolchain/identity.ts";

const require_ = createRequire(import.meta.url);
const wasmDir = dirname(require_.resolve("tree-sitter-wasms/package.json"));

export type TsParser = Parser;
export type TsLanguage = Parser.Language;

let initialized = false;
const languages = new Map<string, TsLanguage>();
/**
 * The identity of the blob each cached grammar was built from.
 *
 * FOUND BY THE FULL SUITE, not by the fixture (bead MetaCoding-0bm): the first
 * version registered the digest only on the cache MISS. A second caller then
 * got a grammar with no measurement behind it — so a process that had already
 * parsed could compute a layer-2 key blind to the parser, which is the defect
 * this whole change exists to remove, surviving inside the fix. Registration is
 * idempotent for the same digest, so re-registering on the hit is free.
 */
const identities = new Map<string, ArtifactIdentity>();

async function init(): Promise<void> {
  if (initialized) return;
  await Parser.init();
  initialized = true;
}

export async function loadLanguage(grammarName: string): Promise<TsLanguage> {
  await init();
  const cached = languages.get(grammarName);
  if (cached) {
    // Re-assert the measurement on the cache HIT too. Handing out a grammar
    // whose digest is not in the registry is exactly "a parse nothing measured".
    registerLoadedArtifact(identities.get(grammarName)!);
    return cached;
  }
  const path = join(wasmDir, "out", `tree-sitter-${grammarName}.wasm`);
  const bytes = readFileSync(path);
  // TOOLCHAIN IDENTITY (bead MetaCoding-0bm). The digest is taken from the SAME
  // buffer that is about to become the grammar — between the read and the load,
  // with no second read and no path-to-digest indirection where a different
  // file could substitute. A grammar upgrade changes every parse tree, every
  // symbol and every edge; before this line it moved no key.
  identities.set(
    grammarName,
    registerLoadedArtifact({
      lane: grammarLane(grammarName),
      kind: "file",
      source: path,
      digest: digestBytes(bytes),
      bytes: bytes.length,
    }),
  );
  const lang = await Parser.Language.load(bytes);
  languages.set(grammarName, lang);
  return lang;
}

export async function makeParser(grammarName: string): Promise<TsParser> {
  const lang = await loadLanguage(grammarName);
  const parser = new Parser();
  parser.setLanguage(lang);
  return parser;
}
