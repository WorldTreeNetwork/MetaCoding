// Bodies for the stub smoke scripts that drive scripts/smoke-all.ts's bracket.
//
// These are deliberately the three shapes a real suite contains: a script that
// reaches the floors gate and publishes a record, a LEGACY script that exits 0
// having said nothing (the shape the bracket exists to refuse — it imports
// nothing from floors.ts, which is the point: it cannot be reached by a guard
// that lives in a library), and a script that fails outright.
//
// The green body's checks are `true` literals. That is honest for a stub whose
// job is to emit a record of a known size, and it is also MetaCoding-8mh
// vector A in miniature: `checks` counts call sites, not verifications.

import { beginRun } from "../../floors.ts";

/** Reaches the gate: n checks, a floor of n over the derived count, a record. */
export function greenScript(name: string, n: number): void {
  const run = beginRun(name);
  for (let i = 1; i <= n; i++) run.check(`${name} check ${i}`, true);
  run.finish([
    { min: n, measuredAs: "checks", why: `this stub declares ${n} checks; fewer is a truncation` },
  ]);
}

/** The legacy shape: exit 0, an unconditional PASS line, no record. */
export function silentScript(name: string): void {
  console.log(`${name.toUpperCase()}_SMOKE_PASS`);
}

/** Red: exits non-zero, the ordinary failure that used to shadow the bracket. */
export function redScript(name: string): never {
  console.error(`${name} blew up`);
  process.exit(1);
}

/**
 * THE SELF-CONTRADICTING SHAPE (MetaCoding-870): exits 0, publishes a real
 * record, and that record says `ok:false`.
 *
 * It is not hypothetical. A fresh adversary demonstrated that smoke-all parsed
 * the child's record, took its `published` counts, and DISCARDED its `ok` —
 * so a script could announce its own failure and still be counted as a healthy
 * reporting script, with its numbers carrying the suite-wide floor.
 *
 * Written by hand rather than through floors.ts's `finish()`, because finish()
 * exits non-zero when it refuses — and the whole point of this shape is the
 * disagreement between the exit code and the record.
 */
export function selfRefusingScript(name: string): void {
  console.log(
    "SMOKE_RECORD " +
      JSON.stringify({
        script: name,
        published: { checks: 2, pairs: 0 },
        checkLabels: [`${name} a`, `${name} b`],
        refused: [{ label: `${name} said no`, detail: "this script refuses itself" }],
        pairNames: [],
        provenance: { checks: "hand-written by the fixture" },
        floors: [],
        ok: false,
      }),
  );
  console.log(`${name.toUpperCase()}_SMOKE_PASS`);
}
