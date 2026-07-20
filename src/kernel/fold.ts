/**
 * The ONE ordered-reduce primitive, keyed on (effectiveTime, HLC tie-break) —
 * kernel v1.1 fold-library element (MetaCoding-9h5.26).
 *
 * WHY THIS EXISTS. The wave-0 pilot (eval/ctkr/results/wave0-pilot-2026-07-20.md
 * §Kernel-gap) ran the port recipe on two FRESH features and found the kernel's
 * fold vocabulary is latest-wins-only: `pickLatest`/`LwwRegister` collapse a set
 * to a single newest write and discard order. Inventory's running-balance is not
 * that — it is a stateful left fold over an ORDER in which a `reset` ASSIGNS the
 * running value and increments/decrements accumulate. The blind builder had to
 * hand-roll it (w0a-build), and reached, unprompted, the same conclusion the LWW
 * freeze was built on: "leaving it hand-rolled per feature reintroduces exactly
 * the 'locally valid, globally divergent' risk the kernel exists to remove — one
 * build folding from 0, another seeding from the reset and mishandling ties."
 *
 * `FoldReduce` removes the choice the same way `pickLatest` does: it is the only
 * sanctioned way to express a reset/accumulate ordered reduce, and it is keyed on
 * the kernel HLC (decision w0a-2 — same-effectiveTime ties break on the HLC, the
 * kernel-legal total order, NEVER on entity id, which ids.ts forbids). Because the
 * order is total across replicas, the fold is replay- and merge-deterministic:
 * the same events in any input order fold to the same value.
 */

import { compareHlc, type Hlc } from "./hlc.ts";

/**
 * The declared shape of a reset/accumulate ordered reduce over events of type `E`
 * producing an accumulator of type `A`. Every field is an accessor, so the
 * primitive never assumes a concrete event or payload shape — a feature supplies
 * how to read the ordering keys, how a `reset` yields its assigned value, and how
 * a delta accumulates.
 */
export interface FoldReduceSpec<E, A> {
  /** valid-time / effective-time of an event — the domain ordering key. */
  effectiveTimeOf: (e: E) => number;
  /** the event's HLC — the kernel tie-break for equal effectiveTime (w0a-2). */
  hlcOf: (e: E) => Hlc;
  /** true iff this event RESETS (assigns) the accumulator rather than adjusting it. */
  isReset: (e: E) => boolean;
  /** the value a reset event ASSIGNS to the accumulator. */
  reset: (e: E) => A;
  /** apply one non-reset (delta) event to the running accumulator. */
  accumulate: (acc: A, e: E) => A;
  /** the accumulator's starting value when no reset governs the fold. */
  initial: A;
  /**
   * Eligibility gate — typically the kernel status gate (`passesGate`) plus any
   * per-event predicate (e.g. same-asset). An event that fails is not folded.
   * Defaults to admitting every event.
   */
  admits?: (e: E) => boolean;
}

/**
 * An ordered reduce with reset-assignment, keyed on (effectiveTime, HLC).
 *
 * Construct it once with a {@link FoldReduceSpec} and call {@link fold} for each
 * as-of query. The fold, for a set of events:
 *   1. keeps only events that pass `admits` AND have `effectiveTime <= asOf`;
 *   2. sorts them ascending by (effectiveTime, HLC) — HLC breaks ties, not id;
 *   3. locates the LATEST reset's effectiveTime and drops every event strictly
 *      before it (the reset boundary is timestamp-INCLUSIVE);
 *   4. left-folds from `initial`: a reset ASSIGNS, a delta accumulates.
 *
 * Folding from `initial` (rather than seeding with the reset's value and skipping
 * to strictly-after) is what makes the same-effectiveTime case correct: a delta
 * sharing the reset's timestamp but sorting before it is applied and then
 * overwritten by the reset, exactly as an ordered ledger sequences ties.
 */
export class FoldReduce<E, A> {
  constructor(private readonly spec: FoldReduceSpec<E, A>) {}

  /**
   * Fold `events` to a single accumulator as of `asOf` (default: no cutoff —
   * every eligible event participates). Order-independent of the input: the
   * (effectiveTime, HLC) sort makes replay and cross-replica merge converge.
   */
  fold(events: Iterable<E>, asOf: number = Number.POSITIVE_INFINITY): A {
    const { spec } = this;
    const admits = spec.admits ?? (() => true);

    const eligible: E[] = [];
    for (const e of events) {
      if (admits(e) && spec.effectiveTimeOf(e) <= asOf) eligible.push(e);
    }
    eligible.sort((a, b) => this.compare(a, b));

    // The latest reset's effectiveTime governs the boundary (inclusive). Because
    // `eligible` is ascending, the last reset seen has the greatest effectiveTime.
    let latestResetTime: number | undefined;
    for (const e of eligible) {
      if (spec.isReset(e)) latestResetTime = spec.effectiveTimeOf(e);
    }

    let acc = spec.initial;
    for (const e of eligible) {
      // Keep events at-or-after the latest reset time; drop strictly-before ones.
      if (latestResetTime !== undefined && spec.effectiveTimeOf(e) < latestResetTime) {
        continue;
      }
      acc = spec.isReset(e) ? spec.reset(e) : spec.accumulate(acc, e);
    }
    return acc;
  }

  /** Ascending domain order: effectiveTime, ties broken by the kernel HLC. */
  private compare(a: E, b: E): number {
    const ta = this.spec.effectiveTimeOf(a);
    const tb = this.spec.effectiveTimeOf(b);
    if (ta !== tb) return ta < tb ? -1 : 1;
    // Same effectiveTime — break on the HLC (w0a-2), never on entity id.
    return compareHlc(this.spec.hlcOf(a), this.spec.hlcOf(b));
  }
}
