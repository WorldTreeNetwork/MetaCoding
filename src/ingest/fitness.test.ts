// Evidence for docs/design/index-fitness.md, root 1 (beads MetaCoding-4kg,
// 5fi, e6z, 0sd).
//
// THE EVIDENCE RULE THIS FILE IS WRITTEN UNDER
// ============================================
// Every load-bearing test here is a CONTRAST PAIR whose two halves give
// OPPOSITE verdicts. A test that only confirms is not yet evidence.
//
// This is not a style preference. It is the specific defect MetaCoding-e6z
// recorded: three mutations of the previous gate left the whole suite green,
// because every fixture in it was confirmatory. The floor's VALUE was untested
// (the only failing case was 0.37% and the only passing case was 100%); the
// repo scoping was untested (every fixture store held exactly ONE repo); and
// the central "measured from the store, never the accumulators" claim was
// untested (the one wired test used an empty .scip whose accumulators were also
// zero, so it could not tell the two apart).
//
// Each `describe` below names the mutation it kills. If you weaken one of these
// measurements, exactly one half of a pair must go red — and the other half
// must stay green, or the test is measuring "everything fails" instead of the
// property.

import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync } from "node:fs";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { scip } from "@sourcegraph/scip-typescript/src/scip.ts";

import { Store } from "../store";
import { loadScip } from "../scip/loader.ts";
// The ingest seam (bead MetaCoding-9ed): loadScip requires a write capability.
// These stores carry no health record, so nothing established can go stale.
import { issueIngestTicket } from "./ticket.ts";
const tk = (repo: string, branch: string, runStamp = "fitness-test") =>
  issueIngestTicket({ repo, branch, runStamp });
import {
  DEFAULT_MIN_COVERAGE,
  censusSourceFiles,
  evaluateIndexOutcome,
  hashIndexFile,
  measureCorrespondence,
  measureGraphFreshness,
  measureRunContribution,
  measureStoreFitness,
  type GateInput,
  type SourceCensus,
} from "./fitness.ts";
import { runIndexSession } from "./session.ts";

const BRANCH = "main";
const RUN_A = "2026-08-04T10:00:00.000Z";
const RUN_B = "2026-08-04T11:00:00.000Z";

let dataDir: string;
let repoDir: string;
let store: Store;

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "fitness-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "fitness-repo-"));
  store = await Store.open(dataDir);
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

// ---------------------------------------------------------------------------
// fixtures
// ---------------------------------------------------------------------------

/** A .scip index with real definitions plus a call/reference between them. */
function productiveScip(prefix = "src"): Uint8Array {
  const PKG = "scip-typescript npm fixture 1.0.0";
  const caller = `${PKG} \`${prefix}/a.ts\`/run().`;
  const callee = `${PKG} \`${prefix}/b.ts\`/helper().`;
  const base = `${PKG} \`${prefix}/b.ts\`/Base#`;
  const derived = `${PKG} \`${prefix}/a.ts\`/Derived#`;
  const docs = [
    new scip.Document({
      relative_path: `${prefix}/a.ts`,
      language: "typescript",
      occurrences: [
        new scip.Occurrence({ symbol: caller, range: [1, 9, 1, 12], symbol_roles: scip.SymbolRole.Definition }),
        new scip.Occurrence({ symbol: callee, range: [2, 4, 2, 10], symbol_roles: 0 }),
        new scip.Occurrence({ symbol: derived, range: [6, 6, 6, 13], symbol_roles: scip.SymbolRole.Definition }),
      ],
      symbols: [
        new scip.SymbolInformation({
          symbol: derived,
          relationships: [new scip.Relationship({ symbol: base, is_implementation: true })],
        }),
      ],
    }),
    new scip.Document({
      relative_path: `${prefix}/b.ts`,
      language: "typescript",
      occurrences: [
        new scip.Occurrence({ symbol: callee, range: [1, 9, 1, 15], symbol_roles: scip.SymbolRole.Definition }),
        new scip.Occurrence({ symbol: base, range: [4, 6, 4, 10], symbol_roles: scip.SymbolRole.Definition }),
      ],
      symbols: [],
    }),
  ];
  return new scip.Index({ documents: docs }).serialize();
}

/**
 * The judge's `vendor40` shape (MetaCoding-5fi): 40 documents with REAL
 * definitions and real edges, every one pathed under `node_modules/dep/`.
 */
function vendor40Scip(): Uint8Array {
  const PKG = "scip-typescript npm dep 1.0.0";
  const docs = [];
  for (let i = 0; i < 40; i++) {
    const p = `node_modules/dep/v${i}.ts`;
    const a = `${PKG} \`${p}\`/f${i}().`;
    // A real cross-document reference, exactly like the productive fixture:
    // the vendored index is a GOOD index — of the wrong tree.
    const other = `${PKG} \`node_modules/dep/v${(i + 1) % 40}.ts\`/f${(i + 1) % 40}().`;
    docs.push(new scip.Document({
      relative_path: p,
      language: "typescript",
      occurrences: [
        new scip.Occurrence({ symbol: a, range: [1, 9, 1, 12], symbol_roles: scip.SymbolRole.Definition }),
        new scip.Occurrence({ symbol: other, range: [2, 4, 2, 8], symbol_roles: 0 }),
      ],
      symbols: [],
    }));
  }
  return new scip.Index({ documents: docs }).serialize();
}

function writeScip(bytes: Uint8Array, name: string): string {
  const p = join(repoDir, name);
  writeFileSync(p, bytes);
  return p;
}

/** Populate the fixture repo with `n` files of a given extension under `dir`. */
function seedSourceFiles(ext: string, n: number, dir = "src", body = "// x\n"): void {
  mkdirSync(join(repoDir, dir), { recursive: true });
  for (let i = 0; i < n; i++) {
    writeFileSync(join(repoDir, dir, `f${i}${ext}`), body, "utf-8");
  }
}

const census = (byExt: Record<string, number>, files: string[] = []): SourceCensus => ({
  total: files.length || Object.values(byExt).reduce((a, b) => a + b, 0),
  byExt,
  files,
});

/** A GateInput with everything healthy; each test overrides ONE thing. */
function baseInput(over: Partial<GateInput> = {}): GateInput {
  return {
    repo: "r",
    targetPath: "/fixture",
    lanes: [
      { lane: "tree-sitter", ok: true, files: 100 },
      { lane: "scip:typescript", ok: true, files: 100 },
    ],
    source: census({ ".ts": 100 }),
    contribution: {
      symbols: 500, relationalEdges: 200,
      edgesByKind: { CALLS: 150, REFERENCES: 50 }, scipSymbols: 400,
    },
    fitness: {
      symbols: 500, relationalEdges: 200,
      edgesByKind: { CALLS: 150, REFERENCES: 50 },
    },
    correspondence: {
      level: "exact", matched: 100, sourceFiles: 100, indexedFiles: 100, ratio: 1,
    },
    scipRequested: true,
    commitSha: "aaaaaaa",
    prevCommitSha: "aaaaaaa",
    ...over,
  };
}

// ---------------------------------------------------------------------------
// PAIR 2 — repo scoping. Kills e6z/M2 (census de-scoped from (repo, branch)).
// ---------------------------------------------------------------------------

describe("PAIR 2 — a populated repo B cannot vouch for an empty repo A", () => {
  // e6z/M2: the edge census was de-scoped from (repo, branch) and every test
  // stayed green, because every fixture store held exactly ONE repo. This is
  // load-bearing for the shared corpus (MetaCoding-d1l.2), where one store
  // holds many repos by construction.
  test("SAME store, SAME measurement, two repos, OPPOSITE verdicts", async () => {
    await loadScip(store, writeScip(productiveScip(), "b.scip"), {
      ticket: tk("B", BRANCH), branch: BRANCH, repo: "B", language: "ts", indexed_at: RUN_A,
    });

    const fitB = await measureStoreFitness(store, "B", BRANCH);
    const fitA = await measureStoreFitness(store, "A", BRANCH);

    // B is real...
    expect(fitB.symbols).toBeGreaterThan(0);
    expect(fitB.edgesByKind["CALLS"]).toBeGreaterThan(0);
    expect(fitB.edgesByKind["REFERENCES"]).toBeGreaterThan(0);
    expect(fitB.edgesByKind["IMPLEMENTS"]).toBeGreaterThan(0);
    // ...and A, in the very same store, is empty.
    expect(fitA.symbols).toBe(0);
    expect(fitA.relationalEdges).toBe(0);

    const verdictB = evaluateIndexOutcome(baseInput({ repo: "B", fitness: fitB }));
    const verdictA = evaluateIndexOutcome(baseInput({
      repo: "A",
      fitness: fitA,
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
    }));
    expect(verdictB.ok).toBe(true);
    expect(verdictA.ok).toBe(false);
    expect(verdictA.failures.map((f) => f.code)).toContain("NO_SYMBOLS");
  });

  test("branch scoping too: a populated sibling BRANCH cannot vouch either", async () => {
    await loadScip(store, writeScip(productiveScip(), "m.scip"), {
      ticket: tk("R", "main"), branch: "main", repo: "R", language: "ts", indexed_at: RUN_A,
    });
    const onMain = await measureStoreFitness(store, "R", "main");
    const onFeature = await measureStoreFitness(store, "R", "feature");
    expect(onMain.relationalEdges).toBeGreaterThan(0);
    expect(onFeature.relationalEdges).toBe(0);
  });
});

// ---------------------------------------------------------------------------
// PAIR 3 — threshold bracketing. Kills e6z/M1 (DEFAULT_MIN_COVERAGE 0.1 -> 0.004).
// ---------------------------------------------------------------------------

describe("PAIR 3 — the correspondence floor's VALUE is pinned, not just its existence", () => {
  // e6z/M1: DEFAULT_MIN_COVERAGE could be silently dropped from 10% to 0.4% —
  // gutting the rule the previous author chose OVER a bare `> 0` check — with
  // every test green, because the only failing case was 1/273 = 0.37% and the
  // only passing case was 100%. These two cases BRACKET the floor.
  const bracket = (matched: number, total: number) =>
    evaluateIndexOutcome(baseInput({
      source: census({ ".ts": total }),
      correspondence: {
        level: "exact", matched, sourceFiles: total, indexedFiles: matched,
        ratio: matched / total,
      },
    }));

  test("9% is REFUSED and 11% is ESTABLISHED — the floor is at 10%", () => {
    expect(DEFAULT_MIN_COVERAGE).toBe(0.1);

    const below = bracket(9, 100);
    const above = bracket(11, 100);

    expect(below.ok).toBe(false);
    expect(below.failures.map((f) => f.code)).toEqual(["LOW_CORRESPONDENCE"]);
    expect(above.ok).toBe(true);

    // And the message must name the actual numbers, or an operator cannot act.
    expect(below.failures[0]!.message).toContain("9/100");
    expect(below.failures[0]!.message).toContain("floor 10%");
  });

  test("an explicit --min-coverage moves the verdict in BOTH directions", () => {
    const nine = {
      source: census({ ".ts": 100 }),
      correspondence: {
        level: "exact" as const, matched: 9, sourceFiles: 100, indexedFiles: 9, ratio: 0.09,
      },
    };
    expect(evaluateIndexOutcome(baseInput({ ...nine, minCoverage: 0.05 })).ok).toBe(true);
    expect(evaluateIndexOutcome(baseInput({ ...nine, minCoverage: 0.5 })).ok).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// PAIR 4 — same-commit vs commit-advancing zero contribution. The CORRECTED 4kg.
// ---------------------------------------------------------------------------

describe("PAIR 4 — zero contribution is fine at the SAME commit and fatal at a NEW one", () => {
  // MetaCoding-4kg said "a run that contributed NOTHING passes when the store
  // already holds that repo". Half of that is right and half is not, and the
  // difference is the COMMIT:
  //   * same commit, already-fit store  -> defensible. The store genuinely IS
  //     fit, and a rule that false-alarms on the most common invocation (a
  //     re-index of unchanged content) is a rule people disable.
  //   * new commit                      -> a lie. Fitness was established at W,
  //     the run claims X, and every reader now believes it is looking at X.
  const barren = {
    contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
    lanes: [{ lane: "scip:load-scip", ok: true, files: 40 }],
    scipRequested: false, // isolate the commit rule from the SCIP rule
  };

  test("IDENTICAL barren run: passes at commit W, REFUSED when it claims X", () => {
    const sameCommit = evaluateIndexOutcome(baseInput({
      ...barren, commitSha: "wwwwwww", prevCommitSha: "wwwwwww",
    }));
    const advancing = evaluateIndexOutcome(baseInput({
      ...barren, commitSha: "xxxxxxx", prevCommitSha: "wwwwwww",
    }));

    expect(sameCommit.ok).toBe(true);
    expect(sameCommit.commitAdvanced).toBe(false);
    // The contribution is RECORDED as zero either way — it is a measurement,
    // never silently substituted for the store's fitness.
    expect(sameCommit.contribution.symbols).toBe(0);
    expect(sameCommit.fitness.symbols).toBe(500);

    expect(advancing.ok).toBe(false);
    expect(advancing.commitAdvanced).toBe(true);
    expect(advancing.failures.map((f) => f.code)).toEqual(["ZERO_CONTRIBUTION_AT_NEW_COMMIT"]);
    expect(advancing.failures[0]!.message).toContain("wwwwwww");
    expect(advancing.failures[0]!.message).toContain("xxxxxxx");
  });

  test("a PRODUCTIVE run at a new commit is not touched by the rule", () => {
    expect(evaluateIndexOutcome(baseInput({
      commitSha: "xxxxxxx", prevCommitSha: "wwwwwww",
    })).ok).toBe(true);
  });

  test("contribution and fitness are measured SEPARATELY out of one real store", async () => {
    // Run A writes. Run B writes nothing. The store is full either way; only
    // the per-run measure can tell them apart, and it does — this is the
    // quantity the old gate did not have (it substituted the repo-wide census).
    await loadScip(store, writeScip(productiveScip(), "runA.scip"), {
      ticket: tk("R", BRANCH), branch: BRANCH, repo: "R", language: "ts", indexed_at: RUN_A,
    });

    const fitness = await measureStoreFitness(store, "R", BRANCH);
    const contribA = await measureRunContribution(store, "R", BRANCH, RUN_A);
    const contribB = await measureRunContribution(store, "R", BRANCH, RUN_B);

    expect(fitness.symbols).toBeGreaterThan(0);
    expect(fitness.relationalEdges).toBeGreaterThan(0);
    expect(contribA.symbols).toBe(fitness.symbols);
    expect(contribA.scipSymbols).toBeGreaterThan(0);
    // OPPOSITE answer for a run that wrote nothing, against the SAME full store.
    expect(contribB.symbols).toBe(0);
    expect(contribB.relationalEdges).toBe(0);
    expect(contribB.scipSymbols).toBe(0);
  });

  test("SCIP requested + no store-visible SCIP symbols THIS RUN is refused", () => {
    // The other half of 4kg, which IS a straight failure: an empty document is
    // a document, so counting documents could never catch it. This counts
    // symbols this run's SCIP lane put in the STORE.
    const r = evaluateIndexOutcome(baseInput({
      scipRequested: true,
      lanes: [{ lane: "scip:load-scip", ok: true, files: 40 }], // 40 documents!
      contribution: { symbols: 12, relationalEdges: 3, edgesByKind: {}, scipSymbols: 0 },
    }));
    expect(r.ok).toBe(false);
    expect(r.failures.map((f) => f.code)).toContain("NO_SCIP_SYMBOLS_THIS_RUN");

    // ...and one store-visible SCIP symbol flips it.
    expect(evaluateIndexOutcome(baseInput({
      scipRequested: true,
      lanes: [{ lane: "scip:load-scip", ok: true, files: 40 }],
      contribution: { symbols: 12, relationalEdges: 3, edgesByKind: {}, scipSymbols: 1 },
    })).ok).toBe(true);
  });
});

// ---------------------------------------------------------------------------
// PAIR c03 — a docs-only commit vs a graph that has actually drifted.
// ---------------------------------------------------------------------------

describe("PAIR c03 — zero contribution at a new commit: skipped-unchanged vs drifted", () => {
  // MetaCoding-c03, measured by a fresh judge with a RE-RUN OF THE LANE (not a
  // query against a store, which is how the false claim survived): the walker
  // skips a file whose content hash matches the stored ast_hash, and a skipped
  // file never calls upsertSymbol, so a commit that touched only README.md
  // re-stamped NOTHING — contribution 0, commitAdvanced true,
  // REFUSED [ZERO_CONTRIBUTION_AT_NEW_COMMIT] — on a graph that was correct and
  // complete. The control (one real edit) split the stamps 20/4, which is what
  // proved the zero was the SKIP and not a measurement artifact.
  //
  // The two halves below share EVERYTHING — same store, same lane, same run-1
  // graph, same zero contribution, same commit advance — and differ only in
  // whether the .ts files on disk still match the graph.
  const RUN_1 = "2026-08-04T09:00:00.000Z";

  async function runOne(stamp: string, commit: string) {
    return runIndexSession(store, dataDir, {
      repo: "R", branch: BRANCH, targetPath: repoDir,
      commitSha: commit, runStamp: stamp, wantScip: false,
    });
  }

  /** DISTINCT indexed_at buckets — the judge's own instrument. */
  async function stampBuckets(): Promise<Record<string, number>> {
    const rows = await store.query<{ t: unknown; c: number | bigint }>(
      `MATCH (s:Symbol) WHERE s.repo = 'R' AND s.branch = $b AND s.file <> ''
       RETURN s.indexed_at AS t, count(s) AS c`,
      { b: BRANCH },
    );
    const out: Record<string, number> = {};
    for (const r of rows) out[String(r.t)] = (out[String(r.t)] ?? 0) + Number(r.c);
    return out;
  }

  test("half A: a docs-only commit re-stamps NOTHING and is HEALTHY anyway", async () => {
    seedSourceFiles(".ts", 6, "src", "export function f() { return 1; }\n");
    const first = await runOne(RUN_1, "aaaaaaa");
    expect(first.health.status).toBe("HEALTHY");
    expect(first.gate.contribution.symbols).toBeGreaterThan(0);

    // A commit that touches NO indexed source file. This is the most common
    // real invocation there is: docs, CI config, lockfiles, images.
    writeFileSync(join(repoDir, "README.md"), "# docs only\n", "utf-8");
    const second = await runOne(RUN_B, "bbbbbbb");

    // THE MEASUREMENT THAT WAS MISSING: run 2 really did re-stamp nothing.
    expect(second.gate.contribution.symbols).toBe(0);
    expect(second.gate.commitAdvanced).toBe(true);
    const buckets = await stampBuckets();
    expect(Object.keys(buckets)).toHaveLength(1);   // ONE bucket: run 1's.
    expect(Object.values(buckets)[0]).toBe(first.gate.contribution.symbols);

    // ...and the verdict is HEALTHY, because the graph was shown to still BE
    // the tree. Before c03 this was REFUSED [ZERO_CONTRIBUTION_AT_NEW_COMMIT].
    expect(second.gate.verifiedCurrent).toBe(true);
    expect(second.health.freshness!.checked).toBeGreaterThan(0);
    expect(second.health.freshness!.stale).toBe(0);
    expect(second.health.status).toBe("HEALTHY");
    expect(second.gate.failures).toEqual([]);
  });

  test("half B: the SAME zero contribution over a DRIFTED tree is refused", async () => {
    seedSourceFiles(".ts", 6, "src", "export function f() { return 1; }\n");
    await runOne(RUN_1, "aaaaaaa");

    // The real-world harm the rule exists for: the tree moved on and the lane
    // did not write it. Two source files change; nothing re-indexes them.
    writeFileSync(join(repoDir, "src", "f0.ts"), "export function f0() { return 99; }\n", "utf-8");
    writeFileSync(join(repoDir, "src", "f1.ts"), "export function f1() { return 99; }\n", "utf-8");

    const source = censusSourceFiles(repoDir);
    const freshness = await measureGraphFreshness(store, "R", BRANCH, repoDir);
    expect(freshness.stale).toBe(2);
    expect(freshness.fresh).toBe(4);

    const drifted = evaluateIndexOutcome(baseInput({
      source, freshness, scipRequested: false,
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
      commitSha: "bbbbbbb", prevCommitSha: "aaaaaaa",
    }));
    expect(drifted.verifiedCurrent).toBe(false);
    expect(drifted.ok).toBe(false);
    expect(drifted.failures.map((f) => f.code)).toEqual(["ZERO_CONTRIBUTION_AT_NEW_COMMIT"]);
    // The refusal must NAME the drift, or an operator cannot act on it.
    expect(drifted.failures[0]!.message).toContain("src/f0.ts");

    // CONTRAST from the same store and the same tree: re-index the two files,
    // and the identical zero-contribution shape passes.
    await runOne(RUN_B, "bbbbbbb");
    const after = await measureGraphFreshness(store, "R", BRANCH, repoDir);
    expect(after.stale).toBe(0);
    expect(evaluateIndexOutcome(baseInput({
      source, freshness: after, scipRequested: false,
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
      commitSha: "ccccccc", prevCommitSha: "bbbbbbb",
    })).ok).toBe(true);
  });

  test("freshness cannot vouch for a store that verified NOTHING", async () => {
    // The escape hatch, closed: `checked === 0` is not `stale === 0`. A store
    // whose file rows all point somewhere that is not this tree (container
    // paths, an alien index) has verified nothing and stays refused.
    const empty = { checked: 0, fresh: 0, stale: 0, absent: 12, staleExamples: [] };
    const r = evaluateIndexOutcome(baseInput({
      freshness: empty, scipRequested: false,
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
      commitSha: "bbbbbbb", prevCommitSha: "aaaaaaa",
    }));
    expect(r.ok).toBe(false);
    expect(r.failures[0]!.message).toContain("NOT ONE");
    // ...and one verified file is still not enough on its own to make anything
    // ELSE pass: freshness only ever disarms this one rule.
    const verified = { checked: 6, fresh: 6, stale: 0, absent: 0, staleExamples: [] };
    const stillBroken = evaluateIndexOutcome(baseInput({
      freshness: verified,
      fitness: { symbols: 0, relationalEdges: 0, edgesByKind: {} },
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
    }));
    expect(stillBroken.ok).toBe(false);
    expect(stillBroken.failures.map((f) => f.code)).toContain("NO_SYMBOLS");
  });

  test("an UNNAMEABLE commit degrades SAFE, not permissive", async () => {
    // `commitSha = null` meant the commit rule COULD NOT FIRE, so the case we
    // know least about got the most lenient reading. It now asks the same
    // question the advancing case asks.
    const barren = {
      scipRequested: false,
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
      commitSha: null,
      prevCommitSha: "aaaaaaa",
    };
    const unverified = evaluateIndexOutcome(baseInput(barren));
    expect(unverified.commitUncertain).toBe(true);
    expect(unverified.ok).toBe(false);
    expect(unverified.failures.map((f) => f.code)).toEqual(["ZERO_CONTRIBUTION_AT_UNKNOWN_COMMIT"]);

    // OPPOSITE half: the same unnameable commit over a tree the graph matches.
    // A no-op re-index of an unchanged non-git tree must not false-alarm.
    const verified = evaluateIndexOutcome(baseInput({
      ...barren,
      freshness: { checked: 6, fresh: 6, stale: 0, absent: 0, staleExamples: [] },
    }));
    expect(verified.ok).toBe(true);

    // And `commitSha = ""` keeps counting as advancement — the safe side.
    expect(evaluateIndexOutcome(baseInput({ ...barren, commitSha: "" })).ok).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// PAIR 5 — correspondence vs document count. Kills 5fi.
// ---------------------------------------------------------------------------

describe("PAIR 5 — 40 vendored documents vs 40 real ones over the SAME tree", () => {
  // MetaCoding-5fi, measured by the judge: `index <10-file .go repo>
  // --load-scip vendor40.scip` gave scip.documents 40, symbolsUpserted 40,
  // edgesAdded 78, coverage 1.0 (clamped), EXIT 0 — with ZERO of the 10 repo
  // files indexed. Numerator and denominator measured different SETS.
  test("vendor40 is UNMEASURABLE; a real 40-document index of the same tree is 100%", async () => {
    seedSourceFiles(".ts", 40);
    const source = censusSourceFiles(repoDir);
    expect(source.total).toBe(40);

    // (a) the vendored index — real definitions, real edges, wrong tree.
    await loadScip(store, writeScip(vendor40Scip(), "vendor40.scip"), {
      ticket: tk("vendored", BRANCH), branch: BRANCH, repo: "vendored", language: "ts", indexed_at: RUN_A,
    });
    const vendored = await measureCorrespondence(store, "vendored", BRANCH, source);

    // Everything a "> 0" or count-ratio measure looks at is HEALTHY here:
    const vendorFitness = await measureStoreFitness(store, "vendored", BRANCH);
    expect(vendorFitness.symbols).toBeGreaterThan(0);
    expect(vendorFitness.relationalEdges).toBeGreaterThan(0);
    expect(vendored.indexedFiles).toBe(40);
    expect(vendored.sourceFiles).toBe(40);
    // ...and the correspondence is ZERO at every rung of the ladder.
    expect(vendored.level).toBe("unmeasurable");
    expect(vendored.matched).toBe(0);
    expect(vendored.ratio).toBeNull();

    // (b) an index of the SAME tree, same document count, correct paths.
    const realDocs = new scip.Index({
      documents: source.files.map((f, i) =>
        new scip.Document({
          relative_path: f,
          language: "typescript",
          occurrences: [
            new scip.Occurrence({
              symbol: `scip-typescript npm fixture 1.0.0 \`${f}\`/fn${i}().`,
              range: [1, 9, 1, 12],
              symbol_roles: scip.SymbolRole.Definition,
            }),
          ],
          symbols: [],
        }),
      ),
    }).serialize();
    await loadScip(store, writeScip(realDocs, "real40.scip"), {
      ticket: tk("real", BRANCH), branch: BRANCH, repo: "real", language: "ts", indexed_at: RUN_A,
    });
    const real = await measureCorrespondence(store, "real", BRANCH, source);

    expect(real.level).toBe("exact");
    expect(real.matched).toBe(40);
    expect(real.ratio).toBe(1);

    // OPPOSITE VERDICTS from the same gate on the same tree.
    const gateInput = { source, scipRequested: true, lanes: [{ lane: "scip:load-scip", ok: true, files: 40 }] };
    expect(evaluateIndexOutcome(baseInput({ ...gateInput, correspondence: real })).ok).toBe(true);
    const vendorVerdict = evaluateIndexOutcome(baseInput({ ...gateInput, correspondence: vendored }));
    expect(vendorVerdict.ok).toBe(false);
    expect(vendorVerdict.failures.map((f) => f.code)).toEqual(["UNMEASURABLE_CORRESPONDENCE"]);
  });
});

// ---------------------------------------------------------------------------
// PAIR 6 — the granularity ladder.
// ---------------------------------------------------------------------------

describe("PAIR 6 — a container prefix degrades the granularity; an unrelated tree is UNMEASURABLE", () => {
  // --load-scip is NOT structurally unmeasurable: an out-of-band Docker build
  // (farmOS's full-site scip-php) prefixes every path with the container root.
  // The ladder measures it at a weaker granularity AND RECORDS WHICH RUNG,
  // which is what distinguishes it from a vendored-dependency index.
  async function loadPaths(repo: string, paths: string[]): Promise<void> {
    const docs = paths.map((p, i) =>
      new scip.Document({
        relative_path: p,
        language: "typescript",
        occurrences: [
          new scip.Occurrence({
            symbol: `scip-typescript npm fixture 1.0.0 \`${p}\`/fn${i}().`,
            range: [1, 9, 1, 12],
            symbol_roles: scip.SymbolRole.Definition,
          }),
        ],
        symbols: [],
      }),
    );
    await loadScip(store, writeScip(new scip.Index({ documents: docs }).serialize(), `${repo}.scip`), {
      ticket: tk(repo, BRANCH), branch: BRANCH, repo, language: "ts", indexed_at: RUN_A,
    });
  }

  test("SUFFIX for a container-prefixed build, UNMEASURABLE for an unrelated one", async () => {
    seedSourceFiles(".ts", 10);
    const source = censusSourceFiles(repoDir);

    await loadPaths("docker", source.files.map((f) => `/app/web/${f}`));
    const docker = await measureCorrespondence(store, "docker", BRANCH, source);
    expect(docker.level).toBe("suffix");
    expect(docker.matched).toBe(10);
    expect(docker.ratio).toBe(1);

    await loadPaths("alien", ["zzz/qqq.ts", "zzz/www.ts"]);
    const alien = await measureCorrespondence(store, "alien", BRANCH, source);
    expect(alien.level).toBe("unmeasurable");
    expect(alien.reason).toContain("basename");

    // Opposite verdicts, and the RUNG is part of the record either way.
    const g = { source, scipRequested: true, lanes: [{ lane: "scip:load-scip", ok: true, files: 10 }] };
    expect(evaluateIndexOutcome(baseInput({ ...g, correspondence: docker })).ok).toBe(true);
    expect(evaluateIndexOutcome(baseInput({ ...g, correspondence: alien })).ok).toBe(false);
  });

  test("BASENAME is still MEASURED and RECORDED — it just stops being a pass", async () => {
    seedSourceFiles(".ts", 10);
    const source = censusSourceFiles(repoDir);
    // scip-php without the PSR-4 sidecar: namespace-derived paths, real files.
    await loadPaths("php-ish", source.files.map((f) => `Drupal/farm/${f.split("/").pop()}`));
    const c = await measureCorrespondence(store, "php-ish", BRANCH, source);
    expect(c.level).toBe("basename");
    expect(c.matched).toBe(10);
    // The rung is KEPT (this case stays legible in the record as "the names
    // correspond and nothing else does") but it earns NO ratio: see PAIR 5fi.
    expect(c.ratio).toBeNull();
  });

  // -------------------------------------------------------------------------
  // PAIR 5fi — the judge's re-opened counterexample, and what it must NOT break.
  // -------------------------------------------------------------------------
  //
  // MetaCoding-5fi was addressed by set intersection and RE-OPENED by a fresh
  // judge, because the BASENAME rung reproduced the bead's literal headline: a
  // local tree of 6 `.go` files (nothing indexes `.go`, so the tree-sitter lane
  // contributes nothing — the fosite shape) plus a `.scip` describing
  // `vendor/github.com/other/project/…` sharing ONLY basenames came out
  // `{ level: 'basename', matched: 6, ratio: 1 }` -> HEALTHY, with zero local
  // files in the graph. The old defence rested on `vendor40`'s INVENTED
  // filenames; real vendored trees are copies, and basename collision is the
  // norm, so that fixture could not discriminate the case the bead is about.
  //
  // The two halves are both FOREIGN-PATH graphs of the same 6 file names. The
  // only difference is whether an indexed path CONTAINS a local path.
  test("PAIR 5fi — a vendored copy is refused; a container-prefixed build still passes", async () => {
    seedSourceFiles(".go", 6, "src", "package main\n");
    const source = censusSourceFiles(repoDir);
    expect(source.total).toBe(6);
    const names = source.files.map((f) => f.split("/").pop()!);

    // (a) THE JUDGE'S FIXTURE: a different tree that shares only basenames.
    await loadPaths("vendored", names.map((n) => `vendor/github.com/other/project/internal/${n}`));
    const vendored = await measureCorrespondence(store, "vendored", BRANCH, source);
    expect(vendored.level).toBe("basename");
    expect(vendored.matched).toBe(6);   // the names DO all correspond...
    expect(vendored.ratio).toBeNull();  // ...and that earns no coverage credit.

    // (b) THE CASE THE LADDER EXISTS FOR: the SAME file names, but each indexed
    // path contains the local path under a container prefix.
    await loadPaths("docker", source.files.map((f) => `/app/web/${f}`));
    const docker = await measureCorrespondence(store, "docker", BRANCH, source);
    expect(docker.level).toBe("suffix");
    expect(docker.ratio).toBe(1);

    // OPPOSITE VERDICTS from one gate over one tree.
    const g = { source, scipRequested: true, lanes: [{ lane: "scip:load-scip", ok: true, files: 6 }] };
    const refused = evaluateIndexOutcome(baseInput({ ...g, correspondence: vendored }));
    expect(refused.ok).toBe(false);
    expect(refused.failures.map((f) => f.code)).toEqual(["BASENAME_ONLY_CORRESPONDENCE"]);
    expect(refused.failures[0]!.message).toContain("FILE NAME ONLY");
    expect(evaluateIndexOutcome(baseInput({ ...g, correspondence: docker })).ok).toBe(true);
  });

  test("a tree-sitter lane that indexed the local files keeps the graph on EXACT", async () => {
    // Why refusing basename does not break farmOS: every session runs the
    // tree-sitter lane over the local tree first, so a --load-scip run whose
    // documents are container-prefixed still has local relative paths in the
    // store, and the two rungs are counted TOGETHER rather than the first one
    // winning and under-reporting.
    seedSourceFiles(".ts", 10);
    const source = censusSourceFiles(repoDir);
    await loadPaths("mixed", [
      ...source.files.slice(0, 3),                       // local, exact
      ...source.files.slice(3).map((f) => `/app/web/${f}`), // container-prefixed
    ]);
    const mixed = await measureCorrespondence(store, "mixed", BRANCH, source);
    expect(mixed.level).toBe("exact");
    expect(mixed.matched).toBe(10);   // NOT 3 — the suffix rung is not discarded
    expect(mixed.ratio).toBe(1);
  });

  test("UNMEASURABLE never counts as a pass ON ITS OWN", () => {
    // The weakest joint in the design, named. Even with a full store and a
    // productive run, an unmeasurable correspondence is a FAILURE, not a shrug.
    const r = evaluateIndexOutcome(baseInput({
      correspondence: {
        level: "unmeasurable", matched: 0, sourceFiles: 100, indexedFiles: 40,
        ratio: null, reason: "nothing corresponds",
      },
    }));
    expect(r.ok).toBe(false);
    expect(r.failures.map((f) => f.code)).toEqual(["UNMEASURABLE_CORRESPONDENCE"]);
  });
});

// ---------------------------------------------------------------------------
// Lane failure + nothing-read, kept from the previous suite as contrasts.
// ---------------------------------------------------------------------------

describe("lane outcomes", () => {
  test("a lane that DIES fails the run even though a sibling filled the store", () => {
    const alive = evaluateIndexOutcome(baseInput());
    const dead = evaluateIndexOutcome(baseInput({
      lanes: [
        { lane: "tree-sitter", ok: true, files: 100 },
        { lane: "scip:python", ok: false, error: "scip-python exited 1", files: 0 },
      ],
    }));
    expect(alive.ok).toBe(true);
    expect(dead.ok).toBe(false);
    expect(dead.failures.map((f) => f.code)).toContain("LANE_FAILED");
    expect(dead.failures.map((f) => f.message).join()).toContain("scip-python exited 1");
  });

  test("'no lane read anything' and 'read but produced nothing' stay distinguishable", () => {
    const nothingRead = evaluateIndexOutcome(baseInput({
      lanes: [{ lane: "tree-sitter", ok: true, files: 0 }],
      source: census({ ".go": 262 }),
      scipRequested: false,
      fitness: { symbols: 0, relationalEdges: 0, edgesByKind: {} },
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
      correspondence: { level: "unmeasurable", matched: 0, sourceFiles: 262, indexedFiles: 0, ratio: null, reason: "empty" },
    }));
    expect(nothingRead.failures.map((f) => f.code)).toContain("NO_FILES_SCANNED");
    expect(nothingRead.failures.map((f) => f.code)).toContain("NO_SYMBOLS");
    // The message must name the language nobody indexed.
    expect(nothingRead.failures.map((f) => f.message).join()).toContain(".go");

    const readButBarren = evaluateIndexOutcome(baseInput({
      lanes: [{ lane: "tree-sitter", ok: true, files: 100 }],
      scipRequested: false,
      fitness: { symbols: 0, relationalEdges: 0, edgesByKind: {} },
      contribution: { symbols: 0, relationalEdges: 0, edgesByKind: {}, scipSymbols: 0 },
    }));
    expect(readButBarren.failures.map((f) => f.code)).toContain("NO_SYMBOLS");
    expect(readButBarren.failures.map((f) => f.code)).not.toContain("NO_FILES_SCANNED");
  });

  test("the hy6.16 shape — symbols, zero relational edges — is refused when SCIP was requested", () => {
    const withEdges = evaluateIndexOutcome(baseInput({
      fitness: { symbols: 4800, relationalEdges: 7, edgesByKind: { CONTAINS: 4800, CALLS: 7 } },
    }));
    const withoutEdges = evaluateIndexOutcome(baseInput({
      fitness: { symbols: 4800, relationalEdges: 0, edgesByKind: { CONTAINS: 4800 } },
    }));
    expect(withEdges.ok).toBe(true);
    expect(withoutEdges.ok).toBe(false);
    expect(withoutEdges.failures.map((f) => f.code)).toContain("NO_RELATIONAL_EDGES");
  });
});

// ---------------------------------------------------------------------------
// Index identity — CITATION for the standing open red, not a closure of it.
// ---------------------------------------------------------------------------

describe("index identity (open red #2: yesterday's .scip at a new commit)", () => {
  test("two different .scip files hash differently; the same file hashes the same", async () => {
    const a = writeScip(productiveScip("src"), "id-a.scip");
    const b = writeScip(productiveScip("other"), "id-b.scip");
    const ha = await hashIndexFile(a);
    const hb = await hashIndexFile(b);
    const ha2 = await hashIndexFile(a);
    expect(ha.sha256).toHaveLength(64);
    expect(ha.sha256).toBe(ha2.sha256);
    expect(ha.sha256).not.toBe(hb.sha256);
    expect(ha.size).toBeGreaterThan(0);
    // NOT CLOSED: a reader can SEE that two runs ingested the same bytes at
    // different commits. Nothing here PREVENTS it. Citation, not prevention.
  });
});
