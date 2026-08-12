// preflight.ts — compare the toolchain that is INSTALLED against the toolchain
// this repo COMMITTED, with "no answer" loudly distinct from "no drift".
//
// This is farmos-port/tools/oracle_preflight.py's shape, generalized
// (docs/design/lessons-as-mechanism.md, mechanism 3). Its five structural parts
// map one for one:
//
//   PROVIDED_BY + bring-up.sh (:319)   -> toolchain.lock.json, the committed
//                                         declaration of what a rebuild reproduces
//   installed_modules() (:360)         -> digestFile/digestPackage/dockerImageId:
//                                         the LIVE artifact, read out, not asked about
//   module_drift() closure (:388)      -> declared vs observed digest per lane
//   PreflightFailed on parse-zero(:351)-> LOCK_EMPTY: a checker that checked
//                                         nothing is a FAILURE, never a pass
//   DriftCheckUnavailable (:144)       -> SKIP_UNAVAILABLE, naming the lane
//
// The last two are the ones this file exists for, and the second of them is a
// correction the oracle itself had to make: `oracle_preflight`'s skip-is-fatal
// default was added AFTER a judge found the skip exiting 0. So the default here
// is chosen with that already known — see `requireLanes` below, and read the
// honest note about it.
//
// THE VOCABULARY IS CLOSED AND EVERY MEMBER IS NAMED
// ---------------------------------------------------
// A boolean "did the toolchain check pass" is what lets an unreachable daemon
// read exactly like a clean check. Five outcomes, three of which are not OK and
// only two of which are failures by default:
//
//   OK                — live digest == declared digest
//   DRIFT             — live digest != declared digest                 FAILURE
//   MISSING           — the declared artifact is not on disk           FAILURE
//   UNPINNED          — the lock declares no digest for this lane      loud, exit 0
//   SKIP_UNAVAILABLE  — the check could not run at all                 loud, exit 0
//
// `--require-lanes` turns UNPINNED and SKIP_UNAVAILABLE into failures. That is
// F3.4: same code path, three outcomes, three distinct tags.
//
// WHAT IT REFUSES THAT PASSES TODAY
// ----------------------------------
// `bun install` resolves tree-sitter-wasms 0.1.14 under the old caret range.
// Today: every parse tree changes, every key is identical, every sealed entry
// is a hit, and nothing anywhere says so. With this: the grammar lanes report
// DRIFT by name, and (because src/extractor/parser.ts registers the digest of
// the blob it loaded) every layer-2 key computed in that process differs too.
//
// HOW THIS IS FAKED
// ------------------
// `--write` regenerates the lock from whatever is installed. Someone facing a
// red preflight can make it green in one command. There is no structural
// defence and this file does not invent one: the mitigation is that the lock is
// a COMMITTED file, so the regeneration appears as a digest diff in review,
// which is the same standing that enforceability.md:123 gives a ratchet
// baseline entry ("only as good as the review of the diff that adds it").

import { readFileSync } from "node:fs";

import {
  type ArtifactIdentity,
  type DockerInspector,
  type LaneKind,
  digestFile,
  digestPackage,
  dockerImageId,
  isDigest,
} from "./identity.ts";

export const LOCK_VERSION = 1;

/** One lane as the committed lockfile declares it. */
export interface LaneDeclaration {
  kind: LaneKind;
  /** file: path relative to the repo root. package: npm name. docker: image tag. */
  source: string;
  /** The digest a rebuild must reproduce, or null for a deliberately unpinned lane. */
  digest: string | null;
  /** Required when `digest` is null: why this lane carries no digest. */
  why?: string;
}

export interface Lockfile {
  version: number;
  why?: string;
  lanes: Record<string, LaneDeclaration>;
}

export type LaneOutcome = "OK" | "DRIFT" | "MISSING" | "UNPINNED" | "SKIP_UNAVAILABLE";

export const FAILING_OUTCOMES: readonly LaneOutcome[] = ["DRIFT", "MISSING"];
export const LOUD_OUTCOMES: readonly LaneOutcome[] = ["UNPINNED", "SKIP_UNAVAILABLE"];

export interface LaneResult {
  lane: string;
  kind: LaneKind;
  source: string;
  declared: string | null;
  observed: string | null;
  outcome: LaneOutcome;
  detail: string;
}

export type PreflightRefusalKind =
  | "LOCK_UNREADABLE" // the lockfile is not there or cannot be read
  | "LOCK_UNPARSEABLE" // it is there and is not JSON
  | "LOCK_EMPTY" // it parses to ZERO lanes — oracle_preflight.py:351
  | "LOCK_MALFORMED"; // a lane declaration this checker cannot evaluate

/**
 * Thrown when the CHECK ITSELF cannot run. Distinct, on purpose, from a lane
 * that came back DRIFT: a broken checker is a failure, never a skip and never a
 * pass. An empty answer is not a clean answer.
 */
export class PreflightRefused extends Error {
  readonly kind: PreflightRefusalKind;
  constructor(kind: PreflightRefusalKind, detail: string) {
    super(`${kind}: ${detail}`);
    this.name = "PreflightRefused";
    this.kind = kind;
  }
}

export interface PreflightOptions {
  /** Install root: the directory whose node_modules is measured. */
  root: string;
  /** Path to the committed lockfile. */
  lockPath: string;
  /** Injected so F3.4's three docker outcomes are reachable without a daemon. */
  inspectDocker?: DockerInspector;
  /** Turn UNPINNED and SKIP_UNAVAILABLE into failures. */
  requireLanes?: boolean;
}

export interface PreflightResult {
  ok: boolean;
  lanes: LaneResult[];
  /** Counts by outcome; every member of the vocabulary is present, even at 0. */
  counts: Record<LaneOutcome, number>;
  requireLanes: boolean;
}

/**
 * Read and validate the committed declaration.
 *
 * PARSE-ZERO IS A FAILURE. A lockfile with `"lanes": {}` would otherwise report
 * a clean toolchain forever while measuring nothing — the shape
 * oracle_preflight.py:351 already pays for, replayed here because the same
 * mistake is one deletion away in any file of this kind.
 */
export function readLockfile(lockPath: string): Lockfile {
  let text: string;
  try {
    text = readFileSync(lockPath, "utf-8");
  } catch (e) {
    throw new PreflightRefused(
      "LOCK_UNREADABLE",
      `${lockPath}: ${e instanceof Error ? e.message : String(e)}. A declaration ` +
        `nobody can read is not a declaration; this is a failure, not a skip.`,
    );
  }

  let parsed: unknown;
  try {
    parsed = JSON.parse(text);
  } catch (e) {
    throw new PreflightRefused(
      "LOCK_UNPARSEABLE",
      `${lockPath} is not JSON: ${e instanceof Error ? e.message : String(e)}`,
    );
  }

  if (parsed === null || typeof parsed !== "object" || Array.isArray(parsed)) {
    throw new PreflightRefused("LOCK_UNPARSEABLE", `${lockPath} is not a JSON object`);
  }
  const lock = parsed as Partial<Lockfile>;
  const lanes = lock.lanes;
  if (lanes === undefined || lanes === null || typeof lanes !== "object" || Array.isArray(lanes)) {
    throw new PreflightRefused(
      "LOCK_MALFORMED",
      `${lockPath} has no "lanes" object. Every lane this repo depends on must be ` +
        `declared; a lock with no lanes key checks nothing.`,
    );
  }
  const names = Object.keys(lanes);
  if (names.length === 0) {
    throw new PreflightRefused(
      "LOCK_EMPTY",
      `${lockPath} declares ZERO lanes. A preflight over zero lanes reports a ` +
        `clean toolchain while measuring nothing, which is exactly the silence ` +
        `it exists to break (oracle_preflight.py:351: a checker that parsed ` +
        `nothing is a FAILURE, never a skip).`,
    );
  }

  for (const name of names) {
    const decl = (lanes as Record<string, unknown>)[name] as Partial<LaneDeclaration>;
    if (decl === null || typeof decl !== "object") {
      throw new PreflightRefused("LOCK_MALFORMED", `lane "${name}" is not an object`);
    }
    if (decl.kind !== "file" && decl.kind !== "package" && decl.kind !== "docker") {
      throw new PreflightRefused(
        "LOCK_MALFORMED",
        `lane "${name}" has kind ${JSON.stringify(decl.kind)}; this checker knows ` +
          `file, package, docker. An unknown kind cannot be checked, and a lane ` +
          `nobody can check must not be silently skipped.`,
      );
    }
    if (typeof decl.source !== "string" || decl.source.trim() === "") {
      throw new PreflightRefused("LOCK_MALFORMED", `lane "${name}" has no source`);
    }
    if (decl.digest === null || decl.digest === undefined) {
      if (typeof decl.why !== "string" || decl.why.trim() === "") {
        throw new PreflightRefused(
          "LOCK_MALFORMED",
          `lane "${name}" carries no digest and does not say why. An unpinned ` +
            `lane is a hole in the key; it may exist, but it may not be silent.`,
        );
      }
    } else if (!isDigest(decl.digest)) {
      throw new PreflightRefused(
        "LOCK_MALFORMED",
        `lane "${name}" declares ${JSON.stringify(decl.digest)}, which is not ` +
          `sha256:<64 hex>. A placeholder that is not a digest would compare ` +
          `unequal forever or, worse, be read as "unpinned" by a typo.`,
      );
    }
  }

  return { version: Number(lock.version ?? 0), why: lock.why, lanes: lanes as Record<string, LaneDeclaration> };
}

/** Measure one lane live. Returns null when the check COULD NOT RUN. */
function observeLane(
  lane: string,
  decl: LaneDeclaration,
  opts: Required<Pick<PreflightOptions, "root">> & { inspectDocker: DockerInspector },
): { digest: string | null; unavailable: string | null; missing: string | null } {
  if (decl.kind === "file") {
    const path = decl.source.startsWith("/") ? decl.source : `${opts.root}/${decl.source}`;
    try {
      return { digest: digestFile(path).digest, unavailable: null, missing: null };
    } catch (e) {
      return {
        digest: null,
        unavailable: null,
        missing: `${path}: ${e instanceof Error ? e.message : String(e)}`,
      };
    }
  }
  if (decl.kind === "package") {
    try {
      return { digest: digestPackage(decl.source, opts.root).digest, unavailable: null, missing: null };
    } catch (e) {
      return {
        digest: null,
        unavailable: null,
        missing: `package ${decl.source}: ${e instanceof Error ? e.message : String(e)}`,
      };
    }
  }
  const id = opts.inspectDocker(decl.source);
  if (id === null) {
    return {
      digest: null,
      unavailable:
        `docker could not answer for ${decl.source} (daemon unreachable, docker ` +
        `absent, or the image is not pulled). This is NO ANSWER, which is not ` +
        `the same as no drift.`,
      missing: null,
    };
  }
  return { digest: id, unavailable: null, missing: null };
}

/**
 * Run the preflight and RETURN the result without throwing.
 *
 * Refusals of the CHECK ITSELF (an unreadable or empty lock) still throw —
 * those are not results, they are the absence of one, and "absence of an answer
 * is never a pass" is the rule this whole module is built on.
 */
export function observeToolchain(opts: PreflightOptions): PreflightResult {
  const lock = readLockfile(opts.lockPath);
  const inspectDocker = opts.inspectDocker ?? dockerImageId;
  const requireLanes = opts.requireLanes === true;

  const lanes: LaneResult[] = [];
  for (const name of Object.keys(lock.lanes).sort()) {
    const decl = lock.lanes[name]!;
    const seen = observeLane(name, decl, { root: opts.root, inspectDocker });

    let outcome: LaneOutcome;
    let detail: string;
    if (seen.missing !== null) {
      outcome = "MISSING";
      detail = seen.missing;
    } else if (seen.unavailable !== null) {
      outcome = "SKIP_UNAVAILABLE";
      detail = seen.unavailable;
    } else if (decl.digest === null || decl.digest === undefined) {
      outcome = "UNPINNED";
      detail = `no digest declared (${decl.why}); observed ${seen.digest}`;
    } else if (decl.digest === seen.digest) {
      outcome = "OK";
      detail = `matches ${decl.digest}`;
    } else {
      outcome = "DRIFT";
      detail =
        `declared ${decl.digest}, installed ${seen.digest}. Every fact derived ` +
        `from this artifact was produced by a different one than the lock names.`;
    }

    lanes.push({
      lane: name,
      kind: decl.kind,
      source: decl.source,
      declared: decl.digest ?? null,
      observed: seen.digest,
      outcome,
      detail,
    });
  }

  const counts: Record<LaneOutcome, number> = {
    OK: 0,
    DRIFT: 0,
    MISSING: 0,
    UNPINNED: 0,
    SKIP_UNAVAILABLE: 0,
  };
  for (const l of lanes) counts[l.outcome] += 1;

  const failing = lanes.filter(
    (l) =>
      FAILING_OUTCOMES.includes(l.outcome) ||
      (requireLanes && LOUD_OUTCOMES.includes(l.outcome)),
  );

  return { ok: failing.length === 0, lanes, counts, requireLanes };
}

/** Human-readable report. Every lane is named, including the ones that passed. */
export function explainToolchain(r: PreflightResult): string {
  const lines = [`toolchain ${r.ok ? "OK" : "REFUSED"} (${r.lanes.length} lanes declared)`];
  for (const l of r.lanes) lines.push(`  ${l.outcome.padEnd(17)} ${l.lane} — ${l.detail}`);
  const loud = r.lanes.filter((l) => LOUD_OUTCOMES.includes(l.outcome));
  if (loud.length > 0) {
    lines.push(
      `  ! ${loud.length} lane(s) NOT CHECKED: ${loud.map((l) => l.lane).join(", ")}. ` +
        (r.requireLanes
          ? `--require-lanes is set, so this is a FAILURE.`
          : `This is not the same as clean; re-run with --require-lanes to refuse it.`),
    );
  }
  return lines.join("\n");
}

export class ToolchainDrift extends Error {
  readonly result: PreflightResult;
  constructor(result: PreflightResult) {
    super(explainToolchain(result));
    this.name = "ToolchainDrift";
    this.result = result;
  }
}

/** The enforcing verb: run the preflight and THROW when it does not hold. */
export function assertToolchain(opts: PreflightOptions): PreflightResult {
  const r = observeToolchain(opts);
  if (!r.ok) throw new ToolchainDrift(r);
  return r;
}

/**
 * Measure every declared lane live and produce the lockfile content that
 * describes what is installed RIGHT NOW. Used by `--write`.
 *
 * Lanes whose live identity cannot be read keep their declared digest rather
 * than silently becoming unpinned — regeneration must not be a way to delete a
 * pin by unplugging a daemon.
 */
export function relock(opts: PreflightOptions & { lock?: Lockfile }): Lockfile {
  const lock = opts.lock ?? readLockfile(opts.lockPath);
  const inspectDocker = opts.inspectDocker ?? dockerImageId;
  const lanes: Record<string, LaneDeclaration> = {};
  for (const name of Object.keys(lock.lanes).sort()) {
    const decl = lock.lanes[name]!;
    const seen = observeLane(name, decl, { root: opts.root, inspectDocker });
    lanes[name] =
      seen.digest !== null
        ? { kind: decl.kind, source: decl.source, digest: seen.digest }
        : { ...decl };
  }
  return { version: LOCK_VERSION, why: lock.why, lanes };
}

/** The artifacts a preflight run measured, in the shape the key folds in. */
export function artifactsFrom(r: PreflightResult): ArtifactIdentity[] {
  return r.lanes
    .filter((l) => l.observed !== null)
    .map((l) => ({ lane: l.lane, kind: l.kind, source: l.source, digest: l.observed! }));
}
