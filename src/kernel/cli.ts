#!/usr/bin/env bun
/**
 * Kernel version management — so that nobody has to do it by hand.
 *
 *     bun run src/kernel/cli.ts state
 *     bun run src/kernel/cli.ts bump --minor --why "promote X into the kernel"
 *
 * WHY THIS EXISTS. `version.ts` says the version is "moved by hand, deliberately,
 * when a decision changes". Measured outcome: wave 1 resolved to freeze a v1.4,
 * nobody moved it, wave 2 ran and closed on 1.3.0, and the wave-close ritual then
 * asked a HUMAN to affirm "the kernel version for this wave is frozen" — a
 * question whose true answer was computable the whole time. Duke, 2026-08-13:
 * *"I don't want to manually manage kernel versioning ... The mechanism should be
 * something that is managed automatically."*
 *
 * So the split this tool enforces:
 *
 *   - **Did the kernel hold?** A FACT. `state` answers it from the fingerprint,
 *     with no input from anyone. `wave.py` calls this; see `kernelDrift`.
 *   - **Should the kernel now change?** An INTENTION. That is a decision about
 *     what to promote into the shared substrate, it belongs on the elicitation
 *     menu with the punt-promotion candidates that motivate it, and this tool
 *     only records it after someone has made it — never asks for it as a
 *     yes/no at close time.
 *
 * THE LOCK IS A PAIR, and that is the point. `kernel.lock.json` holds a version
 * AND the fingerprint that version was correct at, written together. One without
 * the other is what already failed: a version alone drifts from the surface the
 * first time someone edits a gate without thinking of it as a release, and a
 * fingerprint alone is a number no human can cite in a design document.
 */

import { readFileSync, writeFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";

import { kernelDrift, kernelFingerprint } from "./version.ts";

const HERE = dirname(fileURLToPath(import.meta.url));
const LOCK = join(HERE, "kernel.lock.json");
const PKG = join(HERE, "package.json");

/**
 * A reason shorter than this is not a reason — the same floor `wave.py` applies
 * to a carry-forward, for the same reason: the cost of moving the substrate
 * everybody builds on should be stating why, and it should land on the person
 * moving it rather than on the next reader.
 */
const MIN_REASON_WORDS = 4;

interface Lock {
  version: string;
  fingerprint: string;
  moved_at: string;
  /** false when the number moved but the ANSWERS did not. Never inferred. */
  surface_changed: boolean;
  why: string;
}

function readLock(): Lock {
  return JSON.parse(readFileSync(LOCK, "utf8"));
}

function nextVersion(current: string, kind: "major" | "minor" | "patch"): string {
  const parts = current.split(".").map((n) => parseInt(n, 10));
  if (parts.length !== 3 || parts.some((n) => Number.isNaN(n))) {
    throw new Error(`kernel.lock.json version "${current}" is not x.y.z`);
  }
  const [maj, min, pat] = parts as [number, number, number];
  if (kind === "major") return `${maj + 1}.0.0`;
  if (kind === "minor") return `${maj}.${min + 1}.0`;
  return `${maj}.${min}.${pat + 1}`;
}

function cmdState(): number {
  const drift = kernelDrift();
  const lock = readLock();
  console.log(
    JSON.stringify(
      {
        version: drift.actual.version,
        fingerprint: drift.actual.fingerprint,
        locked_fingerprint: drift.locked.fingerprint,
        drift: drift.state,
        moved_at: lock.moved_at,
        surface_changed: lock.surface_changed,
        why: lock.why,
      },
      null,
      2,
    ),
  );
  // Exit 2 on drift so an automated caller that ignores stdout still fails. A
  // check that exits 0 when it could not vouch for the answer is read as a pass
  // (hy6.25), and this one CAN vouch — it just has bad news.
  return drift.state === "clean" ? 0 : 2;
}

function cmdBump(argv: string[]): number {
  const lock = readLock();
  const why = argvValue(argv, "--why") ?? "";
  const set = argvValue(argv, "--set");
  const kind = argv.includes("--major")
    ? "major"
    : argv.includes("--patch")
      ? "patch"
      : "minor";

  if (why.trim().split(/\s+/).filter(Boolean).length < MIN_REASON_WORDS) {
    console.error(
      `REFUSING: --why under ${MIN_REASON_WORDS} words is not a reason.\n` +
        `  This moves the substrate every port builder consumes as fixed input.\n` +
        `  Say what decision changed, in a sentence.`,
    );
    return 2;
  }

  const actualFingerprint = kernelFingerprint();
  const surfaceChanged = actualFingerprint !== lock.fingerprint;
  const version = set ?? nextVersion(lock.version, kind);

  const next: Lock = {
    version,
    fingerprint: actualFingerprint,
    moved_at: today(argv),
    surface_changed: surfaceChanged,
    why: why.trim(),
  };
  writeFileSync(LOCK, JSON.stringify(next, null, 2) + "\n");

  // The manifest is the version's second home — a consumer resolving
  // @metacoding/kernel by name reads THIS, not version.ts (MetaCoding-1gt.3).
  // They drift silently unless one write moves both.
  const pkg = JSON.parse(readFileSync(PKG, "utf8"));
  pkg.version = version;
  writeFileSync(PKG, JSON.stringify(pkg, null, 2) + "\n");

  console.log(
    `kernel ${lock.version} -> ${version} (fingerprint ${lock.fingerprint} -> ${actualFingerprint})`,
  );
  if (!surfaceChanged) {
    // Said out loud rather than silently recorded. A version move with no answer
    // change is legitimate — declaring a wave baseline, for instance — but it
    // must never be readable later as evidence that a decision was re-bound.
    console.log(
      `\nNOTE: the answer-bearing surface did NOT change. The number moved; the\n` +
        `answers did not. Recorded as "surface_changed": false so this row can\n` +
        `never later be read as a re-decision. Promoting something into the\n` +
        `kernel is what makes a version mean something.`,
    );
  }
  return 0;
}

function argvValue(argv: string[], flag: string): string | undefined {
  const i = argv.indexOf(flag);
  return i >= 0 ? argv[i + 1] : undefined;
}

/** Passed in rather than read from the clock, so a bump is reproducible. */
function today(argv: string[]): string {
  const at = argvValue(argv, "--at");
  if (!at) {
    throw new Error("--at is required (the date of the move), so a bump is reproducible");
  }
  return at;
}

const [, , action, ...rest] = process.argv;
if (action === "state") process.exit(cmdState());
else if (action === "bump") process.exit(cmdBump(rest));
else {
  console.error(
    "usage:\n" +
      "  bun run src/kernel/cli.ts state\n" +
      "  bun run src/kernel/cli.ts bump [--minor|--major|--patch|--set X] --at DATE --why '...'",
  );
  process.exit(2);
}
