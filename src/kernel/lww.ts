/**
 * The ONE latest-wins (LWW) primitive, keyed on the HLC (kernel element 3).
 *
 * WHY THIS EXISTS. Given identical inputs, four of the seven isolated builds
 * folded group membership as latest-wins while three folded it ADDITIVELY (any
 * assignment ⇒ member) and got fixture ce015be4 wrong
 * (two-feature-composition-2026-07-20.md §4, "membership model" row). The kernel
 * removes the choice: `pickLatest` / `LwwRegister` are the only sanctioned way to
 * fold a latest-wins projection, and both are keyed on the HLC comparator — so a
 * feature author cannot re-derive membership additively without bypassing the
 * kernel entirely. One comparator serves every overlapping projection (group
 * membership, current location tie-break, log/movement status, geometry).
 */

import { compareHlc, type Hlc } from "./hlc.ts";

/**
 * Fold a set of HLC-stamped candidates to the single latest one. Returns
 * `undefined` for an empty set. Ties are impossible for distinct events (the HLC
 * replicaId makes the order total), so the winner is deterministic across
 * replicas regardless of arrival order — the convergence property.
 */
export function pickLatest<T>(
  items: Iterable<T>,
  hlcOf: (t: T) => Hlc,
): T | undefined {
  let best: T | undefined;
  let bestHlc: Hlc | undefined;
  for (const it of items) {
    const h = hlcOf(it);
    if (bestHlc === undefined || compareHlc(h, bestHlc) > 0) {
      best = it;
      bestHlc = h;
    }
  }
  return best;
}

/**
 * A last-writer-wins register: holds one value plus the HLC of the write that
 * set it. `set` accepts a write only if its HLC strictly follows the current
 * one, so replaying the same events in any order converges to the same value.
 */
export class LwwRegister<V> {
  private _value: V | undefined;
  private _hlc: Hlc | undefined;

  constructor(initial?: V) {
    this._value = initial;
  }

  /** Apply a write. Returns true iff it won (its HLC followed the incumbent). */
  set(value: V, hlc: Hlc): boolean {
    if (this._hlc === undefined || compareHlc(hlc, this._hlc) > 0) {
      this._value = value;
      this._hlc = hlc;
      return true;
    }
    return false;
  }

  get value(): V | undefined {
    return this._value;
  }

  /** The HLC of the winning write, or undefined if never set. */
  get hlc(): Hlc | undefined {
    return this._hlc;
  }
}
