// Bead MetaCoding-1j5, under MetaCoding-0bm — the toolchain digest is RECORDED,
// not merely computed.
//
// WHY THIS FILE EXISTS
// ====================
// 9880f18 gave `toolchainDigest()` a production caller: every whole-tree build
// computes the digest of the grammars it parsed with, and REFUSES rather than
// reporting facts over an unmeasured toolchain. A fresh adversary confirmed the
// refusal executes in production — and then traced the digest itself:
//
//   walker.ts       computes it into WalkStats.toolchain_digest
//   session.ts      receives it inside tsStats, returns it as result.treeSitter
//   cli/main.ts     embeds it in a summary object
//   cli/main.ts     console.log(JSON.stringify(...))
//
// ...and that was the end of it. walker.ts:104 said the digest was "recorded,
// by the code path that produces the facts it describes"; it was printed and
// dropped. Nothing that later OPENED THE STORE could recover which grammar
// produced the facts inside it — a claim in a comment that the code did not
// implement, which is the second thing this project's iteration loop tells a
// judge to look for (CLAUDE.md, docs/design/iteration-methodology.md).
//
// The persisted channel already existed and was already read back:
// `index_identities` records the sha256 of every .scip a run ingested, and
// fitness.test.ts:897 opens the store after the fact and asserts it both
// matches across a repeat and MOVES when the input moves. The tree-sitter
// lane's toolchain was simply never added to it.
//
// WHAT EACH LEG KILLS. The mutation named in the bead is "persist a CONSTANT
// instead of the computed digest" — which nothing could have noticed while
// nothing persisted anything.
//   READ-BACK   the store, opened fresh, states the digest of the run that
//               wrote it, and it EQUALS toolchainDigest() over that run's
//               registry. Kills a constant, and kills recording some other
//               function of the run.
//   MOVEMENT    two runs whose REGISTRIES DIFFER record different digests, and
//               both survive in history. Kills a constant a second way, and
//               kills recording a digest of something that is not the registry.
//   AND BACK    restoring the registry restores the digest. Movement alone is
//               also satisfied by a counter, a clock, or a run id.
//
// NOT CLOSED BY THIS: the layer-2 KEY still has no manifest to live in (bead
// MetaCoding-ev9). Recording an input is not assembling a key, and this file
// claims only the former.

import { test, expect, describe, beforeEach, afterEach, afterAll } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "../store";
import { readIndexHealth, readIndexHealthHistory } from "../store/health.ts";
import { makeParser } from "../extractor/parser.ts";
import {
  digestBytes,
  isDigest,
  loadedArtifacts,
  registerLoadedArtifact,
  resetLoadedArtifacts,
  toolchainDigest,
} from "../toolchain/identity.ts";
import { runIndexSession } from "./session.ts";

const BRANCH = "main";

let dataDir: string;
let repoDir: string;
let store: Store;

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "1j5-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "1j5-repo-"));
  store = await Store.open(dataDir);
  mkdirSync(join(repoDir, "src"), { recursive: true });
  // Enough parseable source that the run has parse-derived facts in it — the
  // facts whose provenance the recorded digest is about.
  for (let i = 0; i < 4; i++) {
    writeFileSync(
      join(repoDir, "src", `m${i}.ts`),
      `export class M${i} { run() { return ${i}; } }\n`,
      "utf-8",
    );
  }
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

/** Leave the process registry as this file found it: the four grammars, measured. */
afterAll(async () => {
  resetLoadedArtifacts();
  await makeParser("typescript");
  await makeParser("tsx");
  await makeParser("python");
  await makeParser("php");
});

const run = (repo: string, stamp: string, commit: string): ReturnType<typeof runIndexSession> =>
  runIndexSession(store, dataDir, {
    repo, branch: BRANCH, targetPath: repoDir,
    commitSha: commit, runStamp: stamp, wantScip: false,
  });

describe("1j5 — a reader who opens the store can recover the toolchain behind its facts", () => {
  test("READ-BACK: the persisted record states the digest of the registry that run parsed with", async () => {
    const result = await run("1j5-readback", "2026-08-12T10:00:00.000Z", "aaaaaaa");
    expect(result.treeSitter.filesUpdated).toBeGreaterThan(0); // there ARE parsed facts

    // The store alone, opened after the fact. Not the return value — the return
    // value is what went to stdout, and stdout is what this bead is about.
    const rec = readIndexHealth(dataDir, "1j5-readback", BRANCH);
    expect(rec).not.toBeNull();
    expect(isDigest(rec!.toolchain_digest ?? "")).toBe(true);

    // It is THIS run's toolchain, not a value of the record's own: the registry
    // is untouched since the walk, so it must still agree with it.
    expect(rec!.toolchain_digest).toBe(toolchainDigest(loadedArtifacts()));
    expect(rec!.toolchain_digest).toBe(result.treeSitter.toolchain_digest);

    // CONTRAST. The nearest plausible wrong answer — a digest over one lane
    // instead of the set — is a different string, so the equality above is not
    // satisfied by just any function of the artifacts.
    expect(rec!.toolchain_digest).not.toBe(toolchainDigest([loadedArtifacts()[0]!]));
  });

  test("MOVEMENT: two runs over DIFFERENT registries record different digests, and both survive", async () => {
    const repo = "1j5-moves";
    await run(repo, "2026-08-12T10:00:00.000Z", "aaaaaaa");

    // A fifth measured artifact — the in-process stand-in for the event 0bm is
    // about (a different .wasm behind a lane), which cannot be staged live
    // because re-registering a lane with a new digest is a LANE_CONFLICT.
    registerLoadedArtifact({
      lane: "test:1j5-extra",
      kind: "file",
      source: "(fixture)",
      digest: digestBytes("a blob this process did not have a moment ago"),
    });

    await run(repo, "2026-08-12T11:00:00.000Z", "bbbbbbb");

    // Asked of the STORE, after the fact: the two runs disagree, and the
    // earlier one survived its own overwrite (the 19g property, applied here).
    const hist = readIndexHealthHistory(dataDir, repo, BRANCH);
    expect(hist).toHaveLength(2);
    expect(hist[0]!.commit_sha).toBe("bbbbbbb");
    expect(hist[1]!.commit_sha).toBe("aaaaaaa");
    expect(hist[0]!.toolchain_digest).not.toBe(hist[1]!.toolchain_digest);
    expect(hist[0]!.toolchain_digest).toBe(toolchainDigest(loadedArtifacts()));

    // AND BACK. Returning to the earlier registry must record the earlier
    // digest — a counter, a clock or the run stamp would all have moved and
    // none of them would come back.
    resetLoadedArtifacts();
    await makeParser("typescript");
    await makeParser("tsx");
    await makeParser("python");
    await makeParser("php");
    await run(repo, "2026-08-12T12:00:00.000Z", "ccccccc");

    const restored = readIndexHealthHistory(dataDir, repo, BRANCH);
    expect(restored[0]!.commit_sha).toBe("ccccccc");
    expect(restored[0]!.toolchain_digest).toBe(hist[1]!.toolchain_digest);
  });
});
