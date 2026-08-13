import { test, expect } from "bun:test";
import {
  KERNEL_VERSION,
  KernelStalenessError,
  currentKernel,
  kernelDrift,
  kernelFingerprint,
  lockedKernel,
  requireKernel,
} from "./version.ts";
import pkg from "./package.json" with { type: "json" };
import lock from "./kernel.lock.json" with { type: "json" };

test("a build pinned to the current kernel runs", () => {
  expect(requireKernel(currentKernel(), "w0a")).toEqual(currentKernel());
});

test("a build pinned to an older kernel VERSION refuses to run", () => {
  const stale = { version: "1.2.0", fingerprint: kernelFingerprint() };
  expect(() => requireKernel(stale, "w0a")).toThrow(KernelStalenessError);
  try {
    requireKernel(stale, "w0a");
  } catch (e) {
    const msg = (e as Error).message;
    expect(msg).toContain("STALE KERNEL");
    expect(msg).toContain("may have been re-bound");
    // the pin exists so its values were CHECKED; re-pinning blind defeats it
    expect(msg).toContain("Do NOT re-pin without re-validating");
  }
});

test("an edited gate is caught even when the version did NOT move", () => {
  // The drift that actually happened: the answer-bearing surface changed while
  // someone did not think of it as a release.
  const stale = { version: KERNEL_VERSION, fingerprint: "deadbeef" };
  expect(() => requireKernel(stale, "w0a")).toThrow(KernelStalenessError);
  try {
    requireKernel(stale, "w0a");
  } catch (e) {
    expect((e as Error).message).toContain("VERSION is unchanged");
  }
});

test("the fingerprint is stable across calls", () => {
  expect(kernelFingerprint()).toBe(kernelFingerprint());
});

test("the fingerprint covers what changes ANSWERS, and it moved for v1.3", () => {
  // The v1.2 surface: yieldTotal/logCount confirmed-only with two partners, no
  // per-projection inventory or lineage rows. Recomputing it must NOT collide
  // with today's — otherwise the check would have slept through the re-bind.
  const v12Surface = JSON.stringify({
    confirmed: "done",
    gates: [
      ["assetsAtLocation", "require-confirmed"],
      ["currentGeometry", "require-confirmed"],
      ["currentLocation", "require-confirmed"],
      ["logCount", "require-confirmed"],
      ["logStatus", "count-regardless"],
      ["pendingLogCount", "pending-only"],
      ["pendingYieldTotal", "pending-only"],
      ["yieldTotal", "require-confirmed"],
    ],
    partners: [
      ["logCount", "pendingLogCount"],
      ["yieldTotal", "pendingYieldTotal"],
    ],
  });
  let h = 0x811c9dc5;
  for (let i = 0; i < v12Surface.length; i++) {
    h ^= v12Surface.charCodeAt(i);
    h = Math.imul(h, 0x01000193) >>> 0;
  }
  expect(h.toString(16).padStart(8, "0")).not.toBe(kernelFingerprint());
});

test("the lock is CLEAN — no gate was edited without a bump", () => {
  // The repo-wide version of the per-build staleness check. It matters because
  // NOTHING IN THE REPO CALLS requireKernel: the pin exists, no build sets one,
  // so until this test the drift it describes had no detector anywhere. This one
  // needs no build to have pinned and no human to have remembered.
  const drift = kernelDrift();
  expect(drift.state).toBe("clean");
  expect(drift.locked.fingerprint).toBe(kernelFingerprint());
});

test("a stale lock reads as DRIFT, not as clean", () => {
  // The contrast. Without it the check above passes for the boring reason that
  // it compares a value to itself, and would keep passing if `kernelDrift`
  // returned "clean" unconditionally.
  const edited = { ...lock, fingerprint: "deadbeef" };
  expect(edited.fingerprint === kernelFingerprint() ? "clean" : "drift").toBe("drift");
  expect(lockedKernel().fingerprint).not.toBe("deadbeef");
});

test("the version has ONE hand-authored home, and it is the lock", () => {
  // It used to be a literal in version.ts, moved by hand "when a decision
  // changes". That policy produced a v1.4 that wave 1 resolved on and never
  // landed, and a wave-2 close whose honest answer to `kernel-frozen` was no.
  expect(KERNEL_VERSION).toBe(lock.version);
});

test("the package manifest's version is the kernel's version", () => {
  // src/kernel is a real package (@metacoding/kernel) so port builds consume it
  // by name rather than by a relative climb out of the tree that contains them
  // (MetaCoding-1gt.3). That gives the version TWO homes, and a consumer that
  // resolves the dependency reads the manifest's, not this file's. They drift
  // silently unless something says they may not.
  expect(pkg.version).toBe(KERNEL_VERSION);
});

test("the package exports the entry point the port workspace imports", () => {
  expect(pkg.name).toBe("@metacoding/kernel");
  expect(pkg.exports["."]).toBe("./index.ts");
});
