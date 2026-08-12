// F3.5 — the PRODUCTION call site of the toolchain fold.
//
// WHY THIS FILE EXISTS
// =====================
// A judge grepped `layer2Key|toolchainDigest|loadedArtifacts` across src/ and
// scripts/ and found: src/extractor/parser.ts registering at one end,
// src/toolchain/identity.test.ts asserting at the other, and NO PATH BETWEEN
// THEM that a real index run takes. The measurement existed, the fold existed,
// the refusal existed — and no production code called any of it. That is the
// enforceability.md failure verbatim: a gate outside the surfaces that execute
// is a document with an exit code.
//
// F3.1b (src/toolchain/identity.test.ts) proves the DEFAULT ARGUMENT binds the
// registry to the digest. This file proves a real whole-tree build USES it, and
// that what the build reports is the registry rather than a value of its own.
// Both are needed and neither substitutes: F3.1b tests the link, this tests
// that anything walks it.
//
// HOW THIS WOULD BE FAKED, and what each leg does about it
// --------------------------------------------------------
//   "return a constant"        -> MOVEMENT: the digest must change when the
//                                 registry changes, and change back.
//   "return some fixed subset" -> IDENTITY: it must equal toolchainDigest()
//                                 over the registry, and DIFFER from a
//                                 plausible neighbour (a one-lane subset).
//   "measure only what parsed" -> EMPTY TREE: a build that parsed no file still
//                                 states its toolchain. This is the leg that
//                                 kills deleting the eager `getParsers()` in
//                                 indexDirectory, and it is the reason that
//                                 call is there.

import { test, expect, beforeEach, afterEach, afterAll } from "bun:test";
import { mkdtempSync, writeFileSync, rmSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "../store";
import { indexDirectory } from "./walker";
import { makeParser } from "./parser";
import { issueIngestTicket } from "../ingest/ticket.ts";
import {
  digestBytes,
  isDigest,
  loadedArtifacts,
  registerLoadedArtifact,
  resetLoadedArtifacts,
  toolchainDigest,
} from "../toolchain/identity.ts";

let dataDir: string;
let repoDir: string;
let store: Store;

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "0bm-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "0bm-repo-"));
  store = await Store.open(dataDir);
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

/**
 * Leave the process registry as this file found it: the four grammars and
 * nothing else. `resetLoadedArtifacts` then a parser load re-registers from the
 * grammar cache (that re-registration on the cache HIT is itself a fix — see
 * src/extractor/parser.ts:47), so the cleanup measures rather than declares.
 */
afterAll(async () => {
  resetLoadedArtifacts();
  await makeParser("typescript");
});

function ticketFor(repo: string): ReturnType<typeof issueIngestTicket> {
  return issueIngestTicket({ repo, branch: "main", runStamp: "0bm-toolchain-test" });
}

test("a whole-tree build REPORTS the toolchain its registry measured", async () => {
  writeFileSync(join(repoDir, "a.ts"), "export class A { m() { return 1; } }\n", "utf-8");
  const repo = "0bm-reports";
  const stats = await indexDirectory(store, repoDir, {
    repo, branch: "main", ticket: ticketFor(repo),
  });

  // It parsed something, so this is a build with parse-derived facts in it.
  expect(stats.filesUpdated).toBeGreaterThan(0);

  // IDENTITY. Well-formed, and the registry's — not a value of the walker's own.
  expect(isDigest(stats.toolchain_digest)).toBe(true);
  const measured = loadedArtifacts();
  expect(measured.length).toBeGreaterThanOrEqual(4); // four grammars, at least
  expect(stats.toolchain_digest).toBe(toolchainDigest(measured));

  // CONTRAST. The nearest plausible wrong answer — a digest over one lane
  // instead of the set — is a different string. Without this the equality above
  // is satisfied by any function of the artifacts at all.
  const oneLane = toolchainDigest([measured[0]!]);
  expect(oneLane).not.toBe(stats.toolchain_digest);
});

test("the reported digest MOVES with the registry, and moves back", async () => {
  writeFileSync(join(repoDir, "b.ts"), "export class B {}\n", "utf-8");
  const repo = "0bm-moves";
  const before = await indexDirectory(store, repoDir, {
    repo, branch: "main", ticket: ticketFor(repo),
  });

  // A fifth measured artifact. This is the in-process stand-in for the thing
  // 0bm is actually about — a different .wasm behind a lane — which cannot be
  // staged live, because registering a second digest under an existing lane is
  // a LANE_CONFLICT by construction. What is under test here is the same
  // property: a key that ignores the registry cannot move when the registry does.
  registerLoadedArtifact({
    lane: "test:extra-artifact",
    kind: "file",
    source: "(fixture)",
    digest: digestBytes("a blob this process did not have a moment ago"),
  });

  const after = await indexDirectory(store, repoDir, {
    repo, branch: "main", ticket: ticketFor(repo),
  });
  expect(after.toolchain_digest).not.toBe(before.toolchain_digest);
  expect(after.toolchain_digest).toBe(toolchainDigest(loadedArtifacts()));

  // AND BACK. Movement alone would also be satisfied by a counter or a clock;
  // returning to the earlier registry must return the earlier digest.
  resetLoadedArtifacts();
  await makeParser("typescript");
  await makeParser("tsx");
  await makeParser("python");
  await makeParser("php");
  const restored = await indexDirectory(store, repoDir, {
    repo, branch: "main", ticket: ticketFor(repo),
  });
  expect(restored.toolchain_digest).toBe(before.toolchain_digest);
});

test("a build whose measurement VANISHED mid-walk is REFUSED, not reported", async () => {
  // FOUND BY MUTATION M6. Swallowing `toolchainDigest()`'s refusal and
  // reporting "" survived the three legs above, because after the eager load
  // the registry is never empty at key time — so the production refusal, the
  // thing the whole module turns on, was computed and never exercised.
  //
  // This stages the one condition that empties it: the loader stopped
  // measuring. `indexDirectory` takes its writer by parameter, so a writer that
  // clears the registry as the first symbol is written puts the run in exactly
  // the state a de-registering loader would. The build must REFUSE. Reporting
  // parse-derived facts with no toolchain behind them is the defect, and "" is
  // not a milder version of it.
  writeFileSync(join(repoDir, "c.ts"), "export class C { m() { return 1; } }\n", "utf-8");
  const repo = "0bm-vanished";

  const saboteur = {
    dataDir: store.dataDir,
    async upsertSymbol(...args: Parameters<typeof store.upsertSymbol>) {
      resetLoadedArtifacts(); // the measurement is gone; the parse already happened
      return store.upsertSymbol(...args);
    },
    addEdge: store.addEdge.bind(store),
    writeTokens: store.writeTokens.bind(store),
  };

  await expect(
    indexDirectory(saboteur, repoDir, { repo, branch: "main", ticket: ticketFor(repo) }),
  ).rejects.toThrow(/NO_ARTIFACTS/);

  // CONTRAST, same writer shape and same tree, with the sabotage removed: it
  // returns, and returns a digest. Without this the refusal above could be the
  // fake writer failing for any reason at all.
  const honest = {
    dataDir: store.dataDir,
    upsertSymbol: store.upsertSymbol.bind(store),
    addEdge: store.addEdge.bind(store),
    writeTokens: store.writeTokens.bind(store),
  };
  const ok = await indexDirectory(honest, repoDir, {
    repo, branch: "main", ticket: ticketFor(repo),
  });
  expect(isDigest(ok.toolchain_digest)).toBe(true);
});

test("a build that parsed NOTHING still states its toolchain", async () => {
  // Not a hypothetical: a tree of docs, or an excluded-everything run. The
  // registry is emptied first so this cannot pass on residue from the tests
  // above — with the eager load removed from indexDirectory, this run reaches
  // `toolchainDigest()` over an empty registry and throws NO_ARTIFACTS.
  writeFileSync(join(repoDir, "README.md"), "# no grammar parses this\n", "utf-8");
  resetLoadedArtifacts();
  expect(loadedArtifacts().length).toBe(0); // the red is real before the run

  const repo = "0bm-empty";
  const stats = await indexDirectory(store, repoDir, {
    repo, branch: "main", ticket: ticketFor(repo),
  });

  expect(stats.filesUpdated).toBe(0); // nothing was parsed …
  expect(isDigest(stats.toolchain_digest)).toBe(true); // … and it is still keyed
  expect(stats.toolchain_digest).toBe(toolchainDigest(loadedArtifacts()));
});
