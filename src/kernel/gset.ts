/**
 * The ONE grow-only ordered collection primitive (G-Set), keyed on the HLC —
 * kernel v1.1 fold-library element (MetaCoding-9h5.26).
 *
 * ⚠️ **UNBOUND since 2026-07-20 (MetaCoding-ci2). Its justifying use case was
 * falsified by observation.** Nicknames — the semantic this primitive was built
 * for — are ordered ✓ and duplicate-preserving ✓, but restatement is **WHOLESALE
 * REPLACE**, not union: `['Pebble','Slate']` then `['Flint']` delivers `['Flint']`
 * (`w0b-observe`). That is an `LwwRegister<readonly V[]>` — a latest-wins register
 * over an ordered array — not a grow-only set. Nicknames now bind to `LwwRegister`.
 *
 * `GSet` is retained, tested, and correct for a genuinely grow-only field, but NO
 * current decision selects it. Do not reach for it without a bound decision naming
 * it — an unbound primitive next to a bound one is exactly the hand-roll bait the
 * kernel exists to remove. The lesson is worth more than the primitive: the mined
 * semantic said "ordered multi-value collection, not a single value that replaces",
 * source reading agreed, and the live system said otherwise.
 *
 * WHY IT WAS BUILT. The wave-0 pilot (wave0-pilot-2026-07-20.md, decision w0b-2)
 * mined the animal-nickname semantic as *"an ordered multi-value collection, not
 * a single value that replaces"* — a grow-only set. `LwwRegister` is the wrong
 * shape (it keeps one newest value and discards the rest); a hand-rolled array is
 * the divergence risk (one builder dedups, another sorts by insertion, a third by
 * id). The pilot warned: if 100+ builders hand-roll grow-only sets, "another's
 * grow-only set dedups" — re-creating the exact non-determinism the LWW freeze
 * killed.
 *
 * `GSet` removes the choice: it is append-only (no replace, no remove), it does
 * NOT dedup by value (nicknames are a multiset — the same nickname may be added
 * twice and both are kept), and it orders by the kernel HLC, so replay and
 * cross-replica merge are deterministic. Each append is identified by its HLC
 * (the total order makes every append's HLC distinct), so re-applying the same
 * append — a replayed event, a merge of an already-merged peer — is idempotent
 * without collapsing genuine duplicate VALUES. Order-by-HLC is what makes two
 * replicas that appended in different real-time orders converge on one sequence.
 */

import { compareHlc, type Hlc } from "./hlc.ts";

/** One appended element: its value plus the HLC that stamped the append. */
export interface GSetEntry<V> {
  readonly value: V;
  readonly hlc: Hlc;
}

/**
 * A grow-only, order-preserving collection. Elements are appended with the HLC of
 * the appending event and read back in HLC order. There is deliberately no
 * `remove`, no `replace`, and no value-dedup — the only mutation is growth.
 */
export class GSet<V> {
  /** Entries keyed by their HLC string — the entry identity for idempotent merge. */
  private readonly byHlc = new Map<string, GSetEntry<V>>();

  constructor(entries: Iterable<GSetEntry<V>> = []) {
    for (const e of entries) this.add(e.value, e.hlc);
  }

  /**
   * Append `value` stamped with `hlc`. Returns true iff it was newly added;
   * re-adding an entry with an HLC already present (a replay or a re-merge) is an
   * idempotent no-op that returns false. Two adds of the same VALUE with distinct
   * HLCs are BOTH kept — this is a multiset, not a deduping set.
   */
  add(value: V, hlc: Hlc): boolean {
    const key = keyOf(hlc);
    const existing = this.byHlc.get(key);
    if (existing) {
      // Same HLC ⇒ same append ⇒ idempotent. (A distinct value under an already-seen
      // HLC would be a caller bug — the HLC total order forbids two appends sharing one.)
      return false;
    }
    this.byHlc.set(key, { value, hlc });
    return true;
  }

  /** Union another G-Set into this one (idempotent, commutative — a CRDT merge). */
  merge(other: GSet<V>): this {
    for (const e of other.entries()) this.add(e.value, e.hlc);
    return this;
  }

  /** The entries in ascending HLC order — the deterministic, convergent sequence. */
  entries(): GSetEntry<V>[] {
    return [...this.byHlc.values()].sort((a, b) => compareHlc(a.hlc, b.hlc));
  }

  /** The values in ascending HLC order (duplicates preserved). */
  values(): V[] {
    return this.entries().map((e) => e.value);
  }

  /** How many appends the set holds (multiset cardinality — counts duplicates). */
  get size(): number {
    return this.byHlc.size;
  }

  /** Whether any entry carries `value` (linear scan; equality is `Object.is`). */
  has(value: V): boolean {
    for (const e of this.byHlc.values()) if (Object.is(e.value, value)) return true;
    return false;
  }
}

function keyOf(hlc: Hlc): string {
  return `${hlc.physical}:${hlc.logical}:${hlc.replicaId}`;
}
