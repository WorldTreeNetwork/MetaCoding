// THE INGEST SEAM, as a capability rather than a lint rule — bead MetaCoding-9ed.
//
// WHAT WAS HERE BEFORE, AND WHY IT DID NOT HOLD
// =============================================
// The seam used to be a TEXT SCANNER over `import ` lines (src/ingest/seam.test.ts)
// plus the absence of the primitives from the barrels. A fresh judge tried nine
// bypass shapes and NINE went undetected — including the multi-line import that
// prettier produces on any wrapped import, `import * as`, `await import()`,
// `require`, a re-export chain, and `indexFile`, which the barrel exported and
// the guard list never mentioned. End to end the judge took a HEALTHY store from
// 24 symbols to 52 while the persisted record still read `HEALTHY, fitness 24`:
// a STALE HEALTHY, which is exactly the harm docs/design/index-fitness.md exists
// to prevent.
//
// The lesson is not "widen the regex". A scanner over import syntax is an
// instrument whose coverage is the set of shapes its author imagined, and the
// bypass is whatever shape they did not. The property has nothing to do with
// syntax:
//
//   YOU CANNOT WRITE TO THE GRAPH WITHOUT A SESSION THAT WILL JUDGE THE RESULT.
//
// WHAT THIS MODULE MAKES TRUE
// ===========================
// Every ingest primitive (`indexDirectory`, `indexFile`, `removeFile`,
// `loadScip`, `watch`) now takes an `IngestTicket` and refuses to write without
// one. The ticket is:
//
//   * NOMINAL at the type level — `IngestTicket` has a private field and a
//     private constructor, so no object literal is assignable to it and no
//     caller outside this module can `new` one. Calling a primitive without a
//     ticket, or with a hand-rolled stand-in, is a TYPE ERROR in every import
//     shape: aliasing, `import * as`, `await import()` and `require` all reach
//     the same function with the same signature.
//   * REGISTERED at runtime — a ticket forged with `as unknown as IngestTicket`
//     is not in this module's WeakSet and is rejected. Type erasure does not
//     buy a bypass.
//   * BOUND TO ITS SLICE — a ticket carries (repo, branch) and cannot be used to
//     write a different slice. Otherwise "open a session on a junk repo, write
//     into farmOS" is a one-line bypass.
//   * CHECKED AGAINST THE PERSISTED RECORD — and this is the part that is a
//     construction rather than a guard. A write into a slice whose record
//     currently reads ESTABLISHED (HEALTHY / OVERRIDDEN) is REFUSED. To write
//     into such a slice you must first move the record off HEALTHY, and the only
//     write path that does that is `runIndexSession`, which finalizes a fresh
//     verdict measured from the store it just wrote.
//
// So the reachable outcomes for anyone holding the primitives are:
//
//   (a) write through a session      -> a fresh verdict is measured and persisted;
//   (b) write into an UNKNOWN /
//       RUNNING / REFUSED slice      -> permitted, and CANNOT produce a stale
//                                       HEALTHY: the record already says the
//                                       fitness is not established, and every
//                                       reader (src/mcp/health-gate.ts) refuses;
//   (c) write into a HEALTHY slice
//       without a session            -> throws IngestSeamError.
//
// The judge's end-to-end attack is (c). It is now impossible, in every import
// shape, because the check does not look at syntax at all.
//
// HOW WOULD I FAKE THIS? (the third step of the loop, answered honestly)
//   1. FORGE THE RECORD. Nothing here stops a module from opening
//      `IndexHealthStore` and writing `status: "HEALTHY"` with numbers it made
//      up. That is not "writing around the session", it is forging the verdict,
//      and it is NOT closed. Closing it needs the record signed by something the
//      forger cannot compute — named, not hidden.
//   2. FLIP TO RUNNING, WRITE, WALK AWAY. Permitted by design, and harmless in
//      the sense that matters: the slice reads RUNNING forever and every reader
//      refuses. The graph is dirty and SAYS SO.
//   3. A STORE WITHOUT A dataDir. The record check needs `store.dataDir` to find
//      `index-health.sqlite`. A caller that hands the primitives a Store-shaped
//      object with no dataDir (test doubles do exactly this) gets the UNKNOWN
//      treatment — permitted, because there is no HEALTHY record to go stale.
//      A real `Store` always has one.
//   4. THE WATCH LANE. `metacoding watch` legitimately writes into a slice that
//      just finalized HEALTHY, so a watch-mode ticket is admitted when the
//      record carries `watching: true` and the SAME run id. Forging that state
//      is case 1. Incremental writes not being re-judged is a standing open red
//      in the design, unchanged by this file.

import { randomUUID } from "node:crypto";

import {
  isFitnessEstablished,
  readIndexHealth,
  type IndexHealthRecord,
} from "../store/health.ts";

/** Thrown when a write reaches an ingest primitive without a valid ticket. */
export class IngestSeamError extends Error {
  constructor(
    readonly code:
      | "NO_TICKET"
      | "FORGED_TICKET"
      | "WRONG_SLICE"
      | "REVOKED_TICKET"
      | "ESTABLISHED_FITNESS_WOULD_GO_STALE",
    message: string,
  ) {
    super(message);
    this.name = "IngestSeamError";
  }
}

/** How a ticket was issued. `watch` additionally permits the incremental lane. */
export type IngestMode = "session" | "watch";

/**
 * The capability to write to the graph. Nominal (private field + private
 * constructor): it cannot be produced by an object literal, only by
 * `issueIngestTicket`, and it is revoked when its session finalizes.
 */
export class IngestTicket {
  /** Nominality: makes `{...} as IngestTicket` a type error, not a bypass. */
  private readonly nonce: string;

  private constructor(
    readonly repo: string,
    readonly branch: string,
    readonly runStamp: string,
    readonly mode: IngestMode,
  ) {
    this.nonce = randomUUID();
  }

  /** @internal — the single mint, used by `issueIngestTicket`. */
  static mint(repo: string, branch: string, runStamp: string, mode: IngestMode): IngestTicket {
    return new IngestTicket(repo, branch, runStamp, mode);
  }

  toString(): string {
    return `IngestTicket(${this.repo}@${this.branch} run=${this.runStamp} ${this.mode})`;
  }
}

/** Tickets this process issued and has not revoked. */
const LIVE = new WeakSet<IngestTicket>();

/**
 * Issue a write capability for one (repo, branch) slice.
 *
 * Issuing a ticket is deliberately CHEAP and side-effect free — it is not the
 * thing that protects the property. What protects the property is that the
 * ticket cannot be used against a slice whose fitness is currently established:
 * see `assertMayIngest`. A holder who wants to write into a HEALTHY slice must
 * first take that slice off HEALTHY, and `runIndexSession` is the only path that
 * does so while also finalizing a fresh verdict.
 */
export function issueIngestTicket(opts: {
  repo: string;
  branch: string;
  runStamp: string;
  mode?: IngestMode;
}): IngestTicket {
  const t = IngestTicket.mint(
    opts.repo,
    opts.branch,
    opts.runStamp,
    opts.mode ?? "session",
  );
  LIVE.add(t);
  return t;
}

/**
 * Revoke a ticket. Called by the session on finalize, so a reference kept past
 * the end of a session cannot be used to grow the store the verdict describes.
 */
export function revokeIngestTicket(ticket: IngestTicket): void {
  LIVE.delete(ticket);
}

/** True while the ticket is a live capability of this process. */
export function isLiveIngestTicket(ticket: unknown): boolean {
  return ticket instanceof IngestTicket && LIVE.has(ticket);
}

/** The slice a write is about, after the primitive's own defaulting. */
export interface WriteTarget {
  repo: string;
  branch: string;
  /** `store.dataDir`; absent for Store doubles, which have no health record. */
  dataDir?: string | null;
}

function established(rec: IndexHealthRecord | null): boolean {
  return rec !== null && isFitnessEstablished(rec.status);
}

/**
 * THE CHECK. Called by every ingest primitive before it writes.
 *
 * Deliberately syntax-blind: it does not care how the caller got hold of the
 * function. `import { indexDirectory }`, `import { indexDirectory as x }`,
 * `import * as w`, `await import(...)`, `require(...)` and a re-export chain all
 * arrive here identically, which is the whole reason it replaces a scanner.
 */
export function assertMayIngest(
  ticket: IngestTicket | undefined | null,
  target: WriteTarget,
  primitive: string,
): void {
  if (ticket === undefined || ticket === null) {
    throw new IngestSeamError(
      "NO_TICKET",
      `${primitive}: refused — no ingest ticket. Every write to the graph must go ` +
        `through an index session (src/ingest/session.ts: runIndexSession / ` +
        `runWatchSession), which persists a fitness verdict for what it wrote. ` +
        `See docs/design/index-fitness.md and bead MetaCoding-9ed.`,
    );
  }
  if (!isLiveIngestTicket(ticket)) {
    const forged = !(ticket instanceof IngestTicket);
    throw new IngestSeamError(
      forged ? "FORGED_TICKET" : "REVOKED_TICKET",
      `${primitive}: refused — ${forged
        ? "the value passed as an ingest ticket was not issued by src/ingest/ticket.ts"
        : "this ingest ticket was revoked when its session finalized"}. ` +
        `Open a session with runIndexSession instead.`,
    );
  }
  if (ticket.repo !== target.repo || ticket.branch !== target.branch) {
    throw new IngestSeamError(
      "WRONG_SLICE",
      `${primitive}: refused — ticket is for ${ticket.repo}@${ticket.branch} but the ` +
        `write targets ${target.repo}@${target.branch}. A ticket is a capability for ` +
        `ONE slice; otherwise a session opened on a scratch repo would license writes ` +
        `into a slice whose fitness some other run established.`,
    );
  }
  const dataDir = target.dataDir;
  if (typeof dataDir !== "string" || dataDir.length === 0) return; // no record can go stale
  const rec = readIndexHealth(dataDir, target.repo, target.branch);
  if (!established(rec)) return; // UNKNOWN / RUNNING / REFUSED — already unfit; readers refuse
  // The slice currently reads ESTABLISHED. The only writes admitted are the
  // watch lane's incremental updates, which the design names as not re-judged
  // and which the record advertises with `watching: true` + the owning run id.
  const watchLane =
    ticket.mode === "watch" && rec!.watching === true && rec!.run_id === ticket.runStamp;
  if (watchLane) return;
  throw new IngestSeamError(
    "ESTABLISHED_FITNESS_WOULD_GO_STALE",
    `${primitive}: refused — ${target.repo}@${target.branch} currently reads ` +
      `${rec!.status} (run ${rec!.run_id}, ${rec!.fitness?.symbols ?? 0} symbols). ` +
      `Writing into it outside a session would leave that record describing a store ` +
      `it no longer describes — a STALE HEALTHY, the exact fake-it in ` +
      `docs/design/index-fitness.md and the bypass measured in bead MetaCoding-9ed. ` +
      `Run 'metacoding index' (runIndexSession), which moves the record to RUNNING ` +
      `first and finalizes a fresh verdict measured from what it wrote.`,
  );
}
