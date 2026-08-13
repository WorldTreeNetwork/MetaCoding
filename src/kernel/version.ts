/**
 * Kernel identity + the staleness gate (MetaCoding-9h5.22).
 *
 * WHY THIS EXISTS. On 2026-07-20 the first oracle observation falsified three
 * bound kernel decisions and the status contract was re-bound (v1.2 → v1.3). At
 * that moment the wave-0 build was carrying its own COPY of the kernel, still
 * holding the falsified blanket rule, and nothing anywhere would have said so —
 * its tests passed, its conformance claim was intact, and it was wrong. Had 15
 * builders been in flight, all 15 would have spent the day building on decisions
 * the oracle had already refuted.
 *
 * A shared kernel that can change under a running build needs two things a
 * version string alone cannot give:
 *
 *   1. **A version a human can cite** — `KERNEL_VERSION`, moved deliberately.
 *   2. **A fingerprint nobody can forget to update** — {@link kernelFingerprint},
 *      computed from the kernel's actual answer-bearing surface. A hand-bumped
 *      version drifts from reality the first time someone edits a gate and does
 *      not think of it as a release; the fingerprint cannot, because it IS the
 *      content.
 *
 * A build calls {@link requireKernel} with what it was built against. If either
 * moved, it fails LOUDLY at construction rather than producing values against a
 * decision that no longer holds. Silence is the failure mode being removed here:
 * the divergence this catches does not look like an error, it looks like output.
 */

import { STATUS_CONTRACT, PENDING_PARTNER, CONFIRMED_STATUS } from "./status.ts";
import lock from "./kernel.lock.json" with { type: "json" };

/**
 * The kernel's semantic version — READ FROM THE LOCK, never typed here.
 *
 * 1.0 five frozen elements · 1.1 fold library · 1.2 pending split
 * · 1.3 per-projection status gates, re-bound on observed evidence
 * · 1.4 wave-3 baseline; the version stopped being hand-managed
 *
 * It used to be a hand-edited constant, "moved by hand, deliberately, when a
 * decision changes". Measured outcome of that policy: wave 1 resolved to freeze
 * a v1.4 and it never landed, so wave 2 ran and closed on 1.3.0 and the honest
 * answer to the `kernel-frozen` affirmation was **no**. A version a human must
 * remember to move is a version that records the last time someone remembered,
 * not the last time a decision changed. The lock is written by `cli.ts bump`
 * together with the fingerprint it was correct at, so the two cannot drift apart
 * — which is the whole reason the pair exists.
 */
export const KERNEL_VERSION: string = lock.version;

/**
 * The answer-bearing surface: everything whose change silently changes what a
 * build DELIVERS. Deliberately not "every export" — adding a new primitive does
 * not invalidate a build that never used it, but re-deciding a projection's gate
 * does, and that is exactly the v1.2 → v1.3 case.
 */
function answerBearingSurface(): string {
  return JSON.stringify({
    confirmed: CONFIRMED_STATUS,
    // sorted so key order can never make an identical contract fingerprint twice
    gates: Object.entries(STATUS_CONTRACT).sort(([a], [b]) => (a < b ? -1 : 1)),
    partners: Object.entries(PENDING_PARTNER).sort(([a], [b]) => (a < b ? -1 : 1)),
  });
}

/** FNV-1a, 32-bit, hex. Small and dependency-free — the kernel ships no deps. */
function fnv1a(s: string): string {
  let h = 0x811c9dc5;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  return h.toString(16).padStart(8, "0");
}

/**
 * A stable digest of the kernel's answer-bearing surface. Two kernels with the
 * same fingerprint give the same answers to every gated projection.
 */
export function kernelFingerprint(): string {
  return fnv1a(answerBearingSurface());
}

/** What a build records about the kernel it was built and validated against. */
export interface KernelPin {
  /** the version the build was written against, e.g. "1.3.0". */
  version: string;
  /** the fingerprint observed at build time — the part that cannot be forgotten. */
  fingerprint: string;
}

/** The kernel this process is actually running. */
export function currentKernel(): KernelPin {
  return { version: KERNEL_VERSION, fingerprint: kernelFingerprint() };
}

/** The (version, fingerprint) pair as last written by a deliberate bump. */
export function lockedKernel(): KernelPin {
  return { version: lock.version, fingerprint: lock.fingerprint };
}

/**
 * Has the answer-bearing surface moved since the version was last moved?
 *
 * `"clean"` — the running surface is the one the current version was bumped at.
 * `"drift"` — a gate or partner was edited and nobody bumped. This is the exact
 * failure {@link KernelStalenessError} describes ("the VERSION is unchanged but
 * the answer-bearing surface is not") lifted from per-build to repo-wide, so it
 * can be caught by a wave close instead of only by a build that happens to have
 * pinned — and as of today no build pins anything, so nothing was catching it.
 *
 * There is deliberately no third "moved with a version bump" state: `bump`
 * rewrites both halves of the lock at once, so that case is `"clean"` by
 * construction. Whether the version moved *during a wave* is a different
 * question, answered by comparing against the wave's open row — not here.
 */
export function kernelDrift(): {
  state: "clean" | "drift";
  locked: KernelPin;
  actual: KernelPin;
} {
  const locked = lockedKernel();
  const actual = currentKernel();
  return {
    state: locked.fingerprint === actual.fingerprint ? "clean" : "drift",
    locked,
    actual,
  };
}

/** Thrown when a build's pinned kernel is not the kernel it is running against. */
export class KernelStalenessError extends Error {
  constructor(
    readonly pinned: KernelPin,
    readonly actual: KernelPin,
    readonly build: string,
  ) {
    const versionMoved = pinned.version !== actual.version;
    super(
      `STALE KERNEL: build ${build} pinned kernel ${pinned.version} ` +
        `(fingerprint ${pinned.fingerprint}) but is running against ` +
        `${actual.version} (fingerprint ${actual.fingerprint}).\n` +
        (versionMoved
          ? `  The kernel version moved. A decision this build depends on may have ` +
            `been re-bound — see docs/design/shared-kernel.md.\n`
          : `  The VERSION is unchanged but the answer-bearing surface is not: a gate ` +
            `or partner was edited without a version move. That is the drift this ` +
            `check exists to catch.\n`) +
        `  Re-validate the build against the current kernel, then re-pin. Do NOT ` +
        `re-pin without re-validating — the point of the pin is that its values ` +
        `were checked against that surface.`,
    );
    this.name = "KernelStalenessError";
  }
}

/**
 * Assert this build's pinned kernel is the one in the process. Call at store
 * construction, beside `requireAllBound` — a build should refuse to run on a
 * kernel it has not been validated against, exactly as it refuses to run on an
 * unresolved decision.
 */
export function requireKernel(pinned: KernelPin, build: string): KernelPin {
  const actual = currentKernel();
  if (
    pinned.version !== actual.version ||
    pinned.fingerprint !== actual.fingerprint
  ) {
    throw new KernelStalenessError(pinned, actual, build);
  }
  return actual;
}
