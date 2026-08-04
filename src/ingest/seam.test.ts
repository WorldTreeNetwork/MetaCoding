// THE INGEST SEAM — evidence that it is a CONSTRUCTION, not a scan.
//
// WHAT THIS FILE USED TO BE, AND WHY IT WAS REPLACED (bead MetaCoding-9ed)
// =======================================================================
// It used to walk src/ looking for lines starting with `import ` and matching
// the guarded identifiers with a regex. A fresh judge tried nine bypass shapes
// and NINE went undetected — including the multi-line import prettier produces
// on any wrapped import, `import { x as y }`, `import * as`, `await import()`,
// `require()`, a re-export chain, `indexFile` (which the barrel exported and the
// guard list never named), and `watch` (named in the claim, absent from the
// list). End to end the judge grew a HEALTHY store from 24 symbols to 52 while
// the record still read `HEALTHY, fitness 24`.
//
// The old instrument's own mutation test used a synthetic bypass in the ONE
// shape it already caught, which is exactly the non-discriminating fixture
// docs/design/iteration-methodology.md warns about.
//
// A text scanner over import syntax cannot be fixed by widening the regex: its
// coverage is the set of shapes its author imagined and the bypass is the shape
// they did not. So the enforcement moved OFF syntax entirely, into
// src/ingest/ticket.ts: every ingest primitive requires an `IngestTicket`, and a
// ticket cannot be used to write into a slice whose fitness currently reads
// ESTABLISHED. See that file for the full argument and its open holes.
//
// HOW THIS SUITE IS BUILT
// -----------------------
// Every test is a CONTRAST PAIR: the bypass half and the legitimate half must
// give OPPOSITE verdicts. A suite in which nothing can succeed is as blind as
// one in which nothing can fail — it would pass over a primitive that had been
// replaced by `throw new Error()`.
//
// The nine bypass shapes are reproduced HERE, from the judge's own list, and
// each one is EXECUTED rather than pattern-matched. The point of the new
// instrument is precisely that shape is irrelevant: aliasing, namespaces,
// `await import()`, `require` and a re-export chain all arrive at the same
// function with the same signature and hit the same runtime check.

import { test, expect, describe, beforeEach, afterEach } from "bun:test";
import { mkdtempSync, mkdirSync, rmSync, writeFileSync, readFileSync } from "node:fs";
import { createRequire } from "node:module";
import { tmpdir } from "node:os";
import { join } from "node:path";

import { Store } from "../store";
import { readIndexHealth } from "../store/health.ts";
import { runIndexSession, type IndexIntent } from "./session.ts";
import {
  IngestSeamError,
  issueIngestTicket,
  revokeIngestTicket,
  type IngestTicket,
} from "./ticket.ts";

const SRC = join(import.meta.dir, "..");
const REPO_ROOT = join(SRC, "..");

const REPO = "seam-fixture";
const BRANCH = "main";

let dataDir: string;
let repoDir: string;
let store: Store;

beforeEach(async () => {
  dataDir = mkdtempSync(join(tmpdir(), "seam-data-"));
  repoDir = mkdtempSync(join(tmpdir(), "seam-repo-"));
  mkdirSync(join(repoDir, "src"), { recursive: true });
  for (let i = 0; i < 6; i++) {
    writeFileSync(
      join(repoDir, "src", `f${i}.ts`),
      `export function fn${i}(): number { return ${i}; }\n`,
      "utf-8",
    );
  }
  store = await Store.open(dataDir);
});

afterEach(async () => {
  await store.close();
  rmSync(dataDir, { recursive: true, force: true });
  rmSync(repoDir, { recursive: true, force: true });
});

function intent(overrides: Partial<IndexIntent> = {}): IndexIntent {
  return {
    repo: REPO,
    branch: BRANCH,
    targetPath: repoDir,
    commitSha: "a".repeat(40),
    runStamp: new Date().toISOString(),
    wantScip: false,
    ...overrides,
  };
}

async function symbolCount(): Promise<number> {
  const rows = await store.query<{ n: number }>(
    `MATCH (s:Symbol) WHERE s.repo = $repo AND s.branch = $branch RETURN COUNT(*) AS n`,
    { repo: REPO, branch: BRANCH },
  );
  return Number(rows[0]?.n ?? 0);
}

/** Establish HEALTHY fitness the legitimate way, and return the state it left. */
async function establishHealthy(): Promise<{ symbols: number; runId: string }> {
  const res = await runIndexSession(store, dataDir, intent());
  expect(res.health.status).toBe("HEALTHY");
  const symbols = await symbolCount();
  expect(symbols).toBeGreaterThan(0);
  return { symbols, runId: res.health.run_id };
}

/** A ticket a bypasser can legitimately mint — the strongest attacker position. */
function attackerTicket(): IngestTicket {
  return issueIngestTicket({ repo: REPO, branch: BRANCH, runStamp: "attacker" });
}

// ---------------------------------------------------------------------------
// THE NINE SHAPES. Each is executed against a store the session just left
// HEALTHY, with a ticket the attacker minted for himself — the best case for
// the attacker, since the type system alone would only have stopped the
// no-ticket call.
// ---------------------------------------------------------------------------

describe("all nine of the judge's bypass shapes reach the same refusal", () => {
  test("A — MULTI-LINE import (what prettier produces on any wrapped import)", async () => {
    const before = await establishHealthy();
    // prettier-ignore
    const {
      indexDirectory,
    } = await import("../extractor/walker.ts");
    await expect(
      indexDirectory(store, repoDir, {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(/ESTABLISHED_FITNESS_WOULD_GO_STALE|STALE HEALTHY/);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("B — RENAMED import: `indexDirectory as ingest`", async () => {
    const before = await establishHealthy();
    const { indexDirectory: ingest } = await import("../extractor/walker.ts");
    await expect(
      ingest(store, repoDir, { ticket: attackerTicket(), repo: REPO, branch: BRANCH }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("C — NAMESPACE import: `import * as walker`", async () => {
    const before = await establishHealthy();
    const walker = await import("../extractor/walker.ts");
    await expect(
      walker.indexDirectory(store, repoDir, {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("D — DYNAMIC import(): the specifier built at runtime", async () => {
    const before = await establishHealthy();
    const spec = ["..", "extractor", "walker.ts"].join("/");
    const m = (await import(spec)) as typeof import("../extractor/walker.ts");
    await expect(
      m.indexDirectory(store, repoDir, {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("E — require() through node:module's createRequire", async () => {
    const before = await establishHealthy();
    const req = createRequire(import.meta.url);
    const m = req("../extractor/walker.ts") as typeof import("../extractor/walker.ts");
    await expect(
      m.indexDirectory(store, repoDir, {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("F — RE-EXPORT CHAIN through a shim module written at test time", async () => {
    const before = await establishHealthy();
    // The judge's shape F: a shim that re-exports the primitive under a new
    // name, and a consumer that imports the new name. Nothing about the
    // consumer's source text mentions the guarded identifier at all.
    const shimDir = mkdtempSync(join(tmpdir(), "seam-shim-"));
    const walkerPath = join(SRC, "extractor", "walker.ts");
    writeFileSync(
      join(shimDir, "shim.ts"),
      `export { indexDirectory as ingestTree } from ${JSON.stringify(walkerPath)};\n`,
      "utf-8",
    );
    writeFileSync(
      join(shimDir, "consumer.ts"),
      `import { ingestTree } from "./shim.ts";\n` +
        `export async function run(store: any, root: string, opts: any) {\n` +
        `  return ingestTree(store, root, opts);\n}\n`,
      "utf-8",
    );
    try {
      const consumer = (await import(join(shimDir, "consumer.ts"))) as {
        run: (s: unknown, r: string, o: unknown) => Promise<unknown>;
      };
      await expect(
        consumer.run(store, repoDir, {
          ticket: attackerTicket(),
          repo: REPO,
          branch: BRANCH,
        }),
      ).rejects.toThrow(IngestSeamError);
      expect(await symbolCount()).toBe(before.symbols);
    } finally {
      rmSync(shimDir, { recursive: true, force: true });
    }
  });

  test("G — indexFile: a PUBLIC barrel export that writes symbols, edges and tokens", async () => {
    const before = await establishHealthy();
    // The judge's deepest hole: no evasion was needed at all. It is still
    // exported from src/extractor/index.ts — and now it refuses like the rest.
    const { indexFile } = await import("../extractor/index.ts");
    await expect(
      indexFile(store, repoDir, join(repoDir, "src", "f0.ts"), {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("G' — removeFile: DELETING a file's symbols is a write too", async () => {
    const before = await establishHealthy();
    const { removeFile } = await import("../extractor/index.ts");
    await expect(
      removeFile(store, repoDir, join(repoDir, "src", "f0.ts"), {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("H — watch: never in the old guard list, though the claim named it", async () => {
    const before = await establishHealthy();
    const { watch } = await import("../extractor/watcher.ts");
    await expect(
      watch(store, repoDir, {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("I — loadScip: the SCIP lane's write primitive", async () => {
    const before = await establishHealthy();
    const { loadScip } = await import("../scip/loader.ts");
    const scipPath = join(repoDir, "empty.scip");
    writeFileSync(scipPath, new Uint8Array([]));
    await expect(
      loadScip(store, scipPath, {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
        language: "ts",
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });

  test("Z (the old control) — the single-line import, the ONE shape the scanner caught", async () => {
    const before = await establishHealthy();
    const { indexDirectory } = await import("../extractor/walker.ts");
    await expect(
      indexDirectory(store, repoDir, {
        ticket: attackerTicket(),
        repo: REPO,
        branch: BRANCH,
      }),
    ).rejects.toThrow(IngestSeamError);
    expect(await symbolCount()).toBe(before.symbols);
  });
});

// ---------------------------------------------------------------------------
// THE MIRROR HALVES. Without these the suite could pass with every primitive
// replaced by `throw`, which is the confirmatory-evidence failure e6z named.
// ---------------------------------------------------------------------------

describe("the same primitives, through the seam, DO write (the opposite verdict)", () => {
  test("a session writes, finalizes, and the record describes what it wrote", async () => {
    const res = await runIndexSession(store, dataDir, intent());
    expect(res.health.status).toBe("HEALTHY");
    const n = await symbolCount();
    expect(n).toBeGreaterThan(0);
    expect(res.health.fitness?.symbols).toBe(n);
  });

  test("a SECOND session may grow the store — and the record advances with it", async () => {
    const first = await establishHealthy();
    writeFileSync(
      join(repoDir, "src", "extra.ts"),
      "export function extraFn(): number { return 99; }\n",
      "utf-8",
    );
    const res = await runIndexSession(
      store,
      dataDir,
      intent({ commitSha: "b".repeat(40), runStamp: new Date(Date.now() + 1_000).toISOString() }),
    );
    expect(res.health.status).toBe("HEALTHY");
    const after = await symbolCount();
    expect(after).toBeGreaterThan(first.symbols);
    // THE POINT: the record is not stale. It describes the store as it now is.
    expect(res.health.fitness?.symbols).toBe(after);
  });

  test("a ticket DOES write into a slice that is not established — and cannot make it stale", async () => {
    // The honest boundary of the construction: writing into an UNKNOWN /
    // RUNNING / REFUSED slice is PERMITTED, because there is no established
    // record for it to falsify. Readers already refuse such a slice
    // (src/mcp/health-gate.ts), so no stale HEALTHY can be manufactured here.
    const { indexDirectory } = await import("../extractor/walker.ts");
    expect(readIndexHealth(dataDir, REPO, BRANCH)).toBeNull(); // UNKNOWN
    const stats = await indexDirectory(store, repoDir, {
      ticket: attackerTicket(),
      repo: REPO,
      branch: BRANCH,
    });
    expect(stats.symbols).toBeGreaterThan(0);
    expect(await symbolCount()).toBeGreaterThan(0);
    // ...and the slice STILL reads unestablished, which is the whole defence.
    expect(readIndexHealth(dataDir, REPO, BRANCH)).toBeNull();
  });
});

// ---------------------------------------------------------------------------
// THE END-TO-END ATTACK the judge actually ran, reproduced.
// ---------------------------------------------------------------------------

describe("the judge's end-to-end bypass (24 -> 52 symbols under a stale HEALTHY)", () => {
  test("two DIFFERENT shapes at a DIFFERENT commit leave the record and the store in agreement", async () => {
    const before = await establishHealthy();
    const record0 = readIndexHealth(dataDir, REPO, BRANCH)!;
    expect(record0.status).toBe("HEALTHY");
    expect(record0.fitness?.symbols).toBe(before.symbols);

    // New files, a different commit, and the two shapes the judge used to grow
    // the store from 24 -> 40 -> 52: a wrapped `indexDirectory` import and the
    // public `indexFile`.
    for (let i = 0; i < 4; i++) {
      writeFileSync(
        join(repoDir, "src", `sneak${i}.ts`),
        `export function sneak${i}(): number { return ${i}; }\n`,
        "utf-8",
      );
    }
    const walker = await import("../extractor/walker.ts");
    const { indexFile } = await import("../extractor/index.ts");
    const opts = { ticket: attackerTicket(), repo: REPO, branch: BRANCH, repo_commit_sha: "c".repeat(40) };

    await expect(walker.indexDirectory(store, repoDir, opts)).rejects.toThrow(IngestSeamError);
    await expect(
      indexFile(store, repoDir, join(repoDir, "src", "sneak0.ts"), opts),
    ).rejects.toThrow(IngestSeamError);

    // The store did not move, so the record cannot have gone stale.
    expect(await symbolCount()).toBe(before.symbols);
    const record1 = readIndexHealth(dataDir, REPO, BRANCH)!;
    expect(record1.status).toBe("HEALTHY");
    expect(record1.fitness?.symbols).toBe(before.symbols);
    expect(record1.commit_sha).toBe(record0.commit_sha);
  });

  test("the only way to write into that slice moves it OFF healthy first", async () => {
    await establishHealthy();
    // A determined bypasser CAN write — by flipping the record to RUNNING, which
    // is what runIndexSession does on entry. What he cannot do is write while
    // the record still reads HEALTHY. So we assert the observable consequence:
    // during any window in which writes are possible, the slice is unestablished.
    let statusDuringWrite: string | null = null;
    const spy = new Proxy(store, {
      get(target, prop, recv) {
        if (prop === "upsertSymbol") {
          return async (...args: unknown[]) => {
            statusDuringWrite ??= readIndexHealth(dataDir, REPO, BRANCH)?.status ?? "UNKNOWN";
            return (target as unknown as Record<string, (...a: unknown[]) => Promise<unknown>>)
              .upsertSymbol.apply(target, args);
          };
        }
        return Reflect.get(target, prop, recv);
      },
    });
    writeFileSync(
      join(repoDir, "src", "more.ts"),
      "export function moreFn(): number { return 1; }\n",
      "utf-8",
    );
    await runIndexSession(
      spy as unknown as Store,
      dataDir,
      intent({ runStamp: new Date(Date.now() + 1_000).toISOString() }),
    );
    expect(statusDuringWrite).toBe("RUNNING");
  });
});

// ---------------------------------------------------------------------------
// THE INSTRUMENT'S OWN MUTATION TESTS. Each input class must produce a DIFFERENT
// refusal code, so a check that had collapsed into "always throw" — or into
// "never throw" — would be visible here.
// ---------------------------------------------------------------------------

describe("the ticket check discriminates between input classes", () => {
  test("no ticket / forged ticket / revoked ticket / wrong slice / stale-healthy", async () => {
    const { indexDirectory } = await import("../extractor/walker.ts");
    const codeOf = async (opts: Record<string, unknown>): Promise<string> => {
      try {
        await indexDirectory(store, repoDir, opts as never);
        return "NO_THROW";
      } catch (e) {
        return e instanceof IngestSeamError ? e.code : `OTHER:${(e as Error).message}`;
      }
    };

    // 1. no ticket at all — the type error, executed past the type system.
    expect(await codeOf({ repo: REPO, branch: BRANCH })).toBe("NO_TICKET");

    // 2. a hand-rolled object cast to the nominal type.
    const forged = { repo: REPO, branch: BRANCH, runStamp: "x", mode: "session" };
    expect(await codeOf({ ticket: forged, repo: REPO, branch: BRANCH })).toBe("FORGED_TICKET");

    // 3. a REAL ticket, revoked (what a session does on finalize).
    const revoked = attackerTicket();
    revokeIngestTicket(revoked);
    expect(await codeOf({ ticket: revoked, repo: REPO, branch: BRANCH })).toBe("REVOKED_TICKET");

    // 4. a real live ticket for ANOTHER slice — "open a session on a scratch
    //    repo, write into the real one" is otherwise a one-line bypass.
    const elsewhere = issueIngestTicket({ repo: "other", branch: BRANCH, runStamp: "y" });
    expect(await codeOf({ ticket: elsewhere, repo: REPO, branch: BRANCH })).toBe("WRONG_SLICE");

    // 5. a real live ticket for THIS slice, against an UNKNOWN record: allowed.
    expect(await codeOf({ ticket: attackerTicket(), repo: REPO, branch: BRANCH })).toBe("NO_THROW");

    // 6. the same call once the slice reads HEALTHY: refused.
    await runIndexSession(store, dataDir, intent({ runStamp: new Date(Date.now() + 1_000).toISOString() }));
    expect(await codeOf({ ticket: attackerTicket(), repo: REPO, branch: BRANCH })).toBe(
      "ESTABLISHED_FITNESS_WOULD_GO_STALE",
    );
  });
});

// ---------------------------------------------------------------------------
// THE TYPE-LEVEL HALF. `bun test` does not typecheck, so the claim "calling a
// primitive without a ticket is a TYPE ERROR" is asserted by running tsc over
// two fixtures whose only difference is the ticket.
// ---------------------------------------------------------------------------

async function tscErrorsFor(source: string): Promise<string[]> {
  const dir = mkdtempSync(join(tmpdir(), "seam-tsc-"));
  try {
    writeFileSync(join(dir, "probe.ts"), source, "utf-8");
    writeFileSync(
      join(dir, "tsconfig.json"),
      JSON.stringify({
        compilerOptions: {
          lib: ["ESNext"], target: "ESNext", module: "Preserve",
          moduleResolution: "bundler", allowImportingTsExtensions: true,
          verbatimModuleSyntax: true, noEmit: true, strict: true,
          skipLibCheck: true, types: [],
        },
        files: ["probe.ts"],
      }),
      "utf-8",
    );
    const tsc = join(REPO_ROOT, "node_modules", ".bin", "tsc");
    const proc = Bun.spawn([tsc, "-p", join(dir, "tsconfig.json")], {
      stdout: "pipe", stderr: "pipe", cwd: dir,
    });
    const out = await new Response(proc.stdout).text();
    await proc.exited;
    // Only diagnostics about the PROBE ITSELF; the fixture tsconfig has no
    // bun/node ambient types, so src/ reports unrelated environment errors.
    const lines = out.split("\n");
    const kept: string[] = [];
    let inProbe = false;
    for (const l of lines) {
      if (l.includes("probe.ts(")) { inProbe = true; kept.push(l); continue; }
      // tsc puts the elaboration ("Property 'ticket' is missing...") on the
      // following INDENTED lines; dropping them would throw away the very text
      // that says WHY the probe failed.
      if (inProbe && /^\s+\S/.test(l)) { kept.push(l.trim()); continue; }
      inProbe = false;
    }
    return kept;
  } finally {
    rmSync(dir, { recursive: true, force: true });
  }
}

describe("the seam is enforced by the TYPE, not only at runtime", () => {
  const walkerPath = join(SRC, "extractor", "walker.ts");
  const storePath = join(SRC, "store", "index.ts");
  const ticketPath = join(SRC, "ingest", "ticket.ts");

  test("a call WITHOUT a ticket does not compile; the same call WITH one does", async () => {
    const withoutTicket = await tscErrorsFor(
      `import { indexDirectory } from ${JSON.stringify(walkerPath)};\n` +
        `import type { Store } from ${JSON.stringify(storePath)};\n` +
        `export const go = (s: Store) => indexDirectory(s, "/tmp/x", { repo: "r", branch: "main" });\n`,
    );
    expect(withoutTicket.join("\n")).toMatch(/ticket/);
    expect(withoutTicket.length).toBeGreaterThan(0);

    // THE MIRROR: identical but for the ticket. If this also failed, the test
    // above would prove nothing about tickets — only that the fixture is broken.
    const withTicket = await tscErrorsFor(
      `import { indexDirectory } from ${JSON.stringify(walkerPath)};\n` +
        `import { issueIngestTicket } from ${JSON.stringify(ticketPath)};\n` +
        `import type { Store } from ${JSON.stringify(storePath)};\n` +
        `const t = issueIngestTicket({ repo: "r", branch: "main", runStamp: "s" });\n` +
        `export const go = (s: Store) =>\n` +
        `  indexDirectory(s, "/tmp/x", { ticket: t, repo: "r", branch: "main" });\n`,
    );
    expect(withTicket).toEqual([]);
  }, 60_000);

  test("an OBJECT LITERAL is not assignable to IngestTicket (the type is nominal)", async () => {
    // Structural typing would let any {repo, branch, runStamp, mode} stand in
    // for a ticket, and then "forge one" would be a two-line bypass with no
    // cast to make it conspicuous. The private `nonce` field makes the class
    // NOMINAL: only `issueIngestTicket` produces a value of the type.
    const errs = await tscErrorsFor(
      `import type { IngestTicket } from ${JSON.stringify(ticketPath)};\n` +
        `export const bad: IngestTicket =\n` +
        `  { repo: "r", branch: "main", runStamp: "s", mode: "session" };\n`,
    );
    expect(errs.join("\n")).toMatch(/nonce|not assignable/);

    // THE MIRROR: the value the mint returns IS assignable, so the check above
    // is about forgery and not about the type being unusable.
    const ok = await tscErrorsFor(
      `import { issueIngestTicket, type IngestTicket } from ${JSON.stringify(ticketPath)};\n` +
        `export const good: IngestTicket =\n` +
        `  issueIngestTicket({ repo: "r", branch: "main", runStamp: "s" });\n`,
    );
    expect(ok).toEqual([]);
  }, 60_000);
});

// ---------------------------------------------------------------------------
// BARREL HYGIENE. This IS a text check, and it is deliberately NOT load-bearing
// any more: the primitives refuse without a ticket wherever they are imported
// from. It is kept because a barrel that hands out ingest entry points invites
// the next reader to try, and because `indexFile` staying exported is a
// deliberate decision that should break loudly if reversed by accident.
// ---------------------------------------------------------------------------

describe("barrel hygiene (defence in depth, not the enforcement)", () => {
  test("the public barrels still do not re-export the raw ingest entries", () => {
    const extractor = readFileSync(join(SRC, "extractor/index.ts"), "utf-8");
    const scipIndex = readFileSync(join(SRC, "scip/index.ts"), "utf-8");
    expect(/export\s*{[^}]*\bindexDirectory\b/.test(extractor)).toBe(false);
    expect(/export\s*{[^}]*\bwatch\b/.test(extractor)).toBe(false);
    expect(/export\s*{[^}]*\bloadScip\b/.test(scipIndex)).toBe(false);
    // CONTRAST: the same regex on what they DO export must be true, or it is
    // simply broken and would report "clean" over anything at all.
    expect(/export\s*{[^}]*\bindexFile\b/.test(extractor)).toBe(true);
    expect(/export\s*{[^}]*\brunScip\b/.test(scipIndex)).toBe(true);
  });

  test("indexFile being public is now harmless — proved above, restated here", async () => {
    // Shape G needed no evasion because the barrel exported it. It still does.
    // The difference is that the export is no longer a write capability.
    const before = await establishHealthy();
    const { indexFile } = await import("../extractor/index.ts");
    await expect(
      indexFile(store, repoDir, join(repoDir, "src", "f1.ts"), {
        ticket: attackerTicket(), repo: REPO, branch: BRANCH,
      }),
    ).rejects.toThrow(/STALE HEALTHY/);
    expect(await symbolCount()).toBe(before.symbols);
  });
});
