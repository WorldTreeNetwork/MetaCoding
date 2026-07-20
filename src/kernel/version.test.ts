import { test, expect } from "bun:test";
import {
  KERNEL_VERSION,
  KernelStalenessError,
  currentKernel,
  kernelFingerprint,
  requireKernel,
} from "./version.ts";

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
