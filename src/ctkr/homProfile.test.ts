/**
 * Tests for src/ctkr/homProfile.ts — math primitives.
 *
 * E2E coverage of homProfilesKnn lives in src/ctkr/artifacts.test.ts and
 * runs against /tmp/metacoding-scip/ctkr/ when available.
 */

import { expect, test, describe } from "bun:test";
import {
  cosineDistance,
  cosineSimilarity,
  discretizeProfile,
  l1Normalize,
  profileBucketKey,
} from "./homProfile.ts";

describe("cosineSimilarity", () => {
  test("identical non-zero vectors → 1", () => {
    const v = [1, 2, 3, 4];
    expect(cosineSimilarity(v, v)).toBeCloseTo(1, 10);
  });

  test("orthogonal vectors → 0", () => {
    expect(cosineSimilarity([1, 0, 0], [0, 1, 0])).toBeCloseTo(0, 10);
  });

  test("zero vector on either side → 0 (not NaN)", () => {
    expect(cosineSimilarity([0, 0, 0], [1, 2, 3])).toBe(0);
    expect(cosineSimilarity([1, 2, 3], [0, 0, 0])).toBe(0);
    expect(cosineSimilarity([0, 0, 0], [0, 0, 0])).toBe(0);
  });

  test("scale-invariance", () => {
    const a = [1, 2, 3];
    const b = [2, 4, 6];
    expect(cosineSimilarity(a, b)).toBeCloseTo(1, 10);
  });

  test("dim mismatch throws", () => {
    expect(() => cosineSimilarity([1, 2], [1, 2, 3])).toThrow(/dim mismatch/);
  });
});

describe("cosineDistance", () => {
  test("range [0, 1] for non-negative inputs", () => {
    expect(cosineDistance([1, 0, 0], [1, 0, 0])).toBeCloseTo(0, 10);
    expect(cosineDistance([1, 0, 0], [0, 1, 0])).toBeCloseTo(1, 10);
  });
});

describe("l1Normalize", () => {
  test("sums to 1 for non-zero input", () => {
    const out = l1Normalize([1, 2, 1]);
    const s = out.reduce((a, b) => a + b, 0);
    expect(s).toBeCloseTo(1, 10);
    expect(out).toEqual([0.25, 0.5, 0.25]);
  });

  test("zero vector stays zero (does NOT collapse to uniform)", () => {
    expect(l1Normalize([0, 0, 0, 0])).toEqual([0, 0, 0, 0]);
  });
});

describe("discretizeProfile", () => {
  test("k=2 buckets components to {0, 0.5, 1}", () => {
    const out = discretizeProfile([0.1, 0.4, 0.6, 0.9], 2);
    expect(out).toEqual([0, 0.5, 0.5, 1]);
  });

  test("k=10 buckets to 0.1 steps", () => {
    const out = discretizeProfile([0.12, 0.47, 0.55], 10);
    expect(out[0]).toBeCloseTo(0.1, 10);
    expect(out[1]).toBeCloseTo(0.5, 10);
    expect(out[2]).toBeCloseTo(0.6, 10);
  });

  test("k=1 maps any non-trivial component to 0 or 1", () => {
    const out = discretizeProfile([0.1, 0.49, 0.51, 0.9], 1);
    expect(out).toEqual([0, 0, 1, 1]);
  });

  test("non-positive or non-finite k throws", () => {
    expect(() => discretizeProfile([0.5], 0)).toThrow(/positive/);
    expect(() => discretizeProfile([0.5], -1)).toThrow(/positive/);
    expect(() => discretizeProfile([0.5], Number.POSITIVE_INFINITY)).toThrow(
      /finite/,
    );
  });
});

describe("profileBucketKey", () => {
  test("identical raw counts produce identical bucket keys", () => {
    expect(profileBucketKey([1, 2, 3], 4)).toBe(profileBucketKey([1, 2, 3], 4));
  });

  test("scaled counts collapse to the same key (L1-normalisation is the right invariant)", () => {
    expect(profileBucketKey([1, 1, 2], 4)).toBe(
      profileBucketKey([10, 10, 20], 4),
    );
  });

  test("different shapes get different keys", () => {
    expect(profileBucketKey([1, 0, 0], 4)).not.toBe(
      profileBucketKey([0, 1, 0], 4),
    );
  });

  test("higher k can separate profiles that lower k collapses", () => {
    // a normalises to [0.4, 0.6], b to [0.45, 0.55].
    // k=2: both → [0.5, 0.5] (collapsed). k=10: distinct.
    const a = [4, 6];
    const b = [45, 55];
    expect(profileBucketKey(a, 2)).toBe(profileBucketKey(b, 2));
    expect(profileBucketKey(a, 10)).not.toBe(profileBucketKey(b, 10));
  });

  test("zero counts produce a stable all-zero key", () => {
    expect(profileBucketKey([0, 0, 0, 0], 4)).toBe("0|0|0|0");
  });
});
