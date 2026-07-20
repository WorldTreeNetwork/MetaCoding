/**
 * The first-writer-wins (FWW) family, keyed on the HLC — the mirror of lww.ts.
 * Kernel v1.1 fold-library element (MetaCoding-9h5.26).
 *
 * WHY THIS EXISTS. Two of the wave-0 pilot's fresh-feature semantics
 * (wave0-pilot-2026-07-20.md) are earliest-wins, not latest-wins:
 *
 *   - ~~**Parent lineage (decision w0b-1).**~~ **REVERSED 2026-07-20** (Duke's
 *     elicitation review, MetaCoding-tkj). The source's rule was "append the
 *     mother iff the child has no parent — any existing parent is a complete
 *     veto", which is a guarded first write. Duke chose correctability over source
 *     fidelity: **a birth correction MAY overwrite parentage**, so parent lineage
 *     is an `LwwRegister` (lww.ts), not this module. `GuardedFirstWrite` below is
 *     therefore UNBOUND — retained and tested, but no current feature decision
 *     selects it. Do not reach for it without a bound CM decision naming it.
 *   - **Birth-uniqueness (kernel-bound decision, sub-decision 5a option A).** At
 *     most one birth log per asset; on merge the earliest by HLC survives and any
 *     later concurrent birth is DEMOTED TO AN OBSERVATION, never silently dropped.
 *     The 9h5.24 build only declared this as a `convergenceKey` string; no code
 *     implemented it. This module promotes the mechanic to a primitive so every
 *     bound-uniqueness feature demotes losers the SAME way.
 *
 * Both are `pickLatest`/`LwwRegister` with the comparator reversed: earliest HLC
 * wins. Sharing the HLC total order with the latest-wins family means the same
 * "replay in any order ⇒ same result" convergence property holds, keyed off the
 * one comparator the kernel sanctions — never entity id (ids.ts forbids it).
 */

import { compareHlc, type Hlc } from "./hlc.ts";

/**
 * Fold a set of HLC-stamped candidates to the single EARLIEST one — the mirror of
 * `pickLatest`. Returns `undefined` for an empty set. The HLC total order makes
 * the winner deterministic across replicas regardless of arrival order.
 */
export function pickEarliest<T>(
  items: Iterable<T>,
  hlcOf: (t: T) => Hlc,
): T | undefined {
  let best: T | undefined;
  let bestHlc: Hlc | undefined;
  for (const it of items) {
    const h = hlcOf(it);
    if (bestHlc === undefined || compareHlc(h, bestHlc) < 0) {
      best = it;
      bestHlc = h;
    }
  }
  return best;
}

/**
 * A guarded-first-write register: it accepts a value only while empty, and any
 * existing value is a complete veto.
 *
 * **UNBOUND (2026-07-20).** Its only binding was parent lineage (w0b-1), which
 * Duke reversed to latest-wins; use `LwwRegister` for that field. This class stays
 * as the tested mirror of the LWW register for a future first-writer-wins
 * decision — but a fan-out builder must not select it without one. Under replay or cross-replica merge the
 * value converges to the EARLIEST write by HLC — so `set` accepts a write iff no
 * write has been seen or the incoming HLC strictly PRECEDES the incumbent. That
 * makes sequential first-write-wins and concurrent earliest-HLC-wins the same
 * rule, and replaying events in any order lands on the same value.
 */
export class GuardedFirstWrite<V> {
  private _value: V | undefined;
  private _hlc: Hlc | undefined;

  /** Apply a write. Returns true iff it won (empty, or an HLC before the incumbent). */
  set(value: V, hlc: Hlc): boolean {
    if (this._hlc === undefined || compareHlc(hlc, this._hlc) < 0) {
      this._value = value;
      this._hlc = hlc;
      return true;
    }
    return false;
  }

  get value(): V | undefined {
    return this._value;
  }

  /** The HLC of the winning (earliest) write, or undefined if never set. */
  get hlc(): Hlc | undefined {
    return this._hlc;
  }

  /** Whether any write has been accepted (the veto is active). */
  get isSet(): boolean {
    return this._hlc !== undefined;
  }
}

/** The outcome of a bound-uniqueness demotion: the survivor and the demoted losers. */
export interface DemotionResult<E> {
  /** the earliest-HLC candidate — the one KEPT as canonical. */
  readonly kept: E;
  /** every other candidate, re-emitted through `toObservation` (never dropped). */
  readonly demoted: E[];
}

/**
 * Resolve a set of competing candidates for a hard "at most one" invariant by the
 * kernel-bound rule: the earliest by HLC is KEPT, and every loser is DEMOTED —
 * re-emitted as an observation-kind event via `toObservation`, never silently
 * dropped (sub-decision 5a option A). Deterministic under replay/merge because
 * "earliest HLC" is well-defined for any arrival order.
 *
 * `toObservation` carries the domain specifics (which observation kind, what
 * payload); this helper owns only the mechanic — who wins, who is demoted — so a
 * feature cannot re-derive it as min-UUID (option C, which ids.ts forbids) or
 * silently drop the loser. Returns `undefined` for an empty candidate set.
 */
export function demoteToObservation<E>(
  candidates: Iterable<E>,
  hlcOf: (e: E) => Hlc,
  toObservation: (loser: E) => E,
): DemotionResult<E> | undefined {
  const all = [...candidates];
  const kept = pickEarliest(all, hlcOf);
  if (kept === undefined) return undefined;
  const demoted = all.filter((e) => e !== kept).map(toObservation);
  return { kept, demoted };
}
