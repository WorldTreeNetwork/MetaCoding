/**
 * Hybrid Logical Clock (HLC) — the ONE cross-replica ordering key of the shared
 * kernel (MetaCoding-9h5.24, kernel element 2b).
 *
 * WHY THIS EXISTS. All seven isolated port builds in the 9h5 line independently
 * reached for a `(timestamp, insertion-seq)` tie-break AND independently wrote
 * down that the bare insertion counter is NOT multi-replica safe — a unanimous
 * deferral (two-feature-composition-2026-07-20.md §4). A bare serial ordinal
 * ("seq", "append counter") cannot order events minted on different replicas:
 * replica A's `seq=3` and replica B's `seq=3` are incomparable. The HLC replaces
 * that placeholder with a real total order:
 *
 *   (physical wall time, logical counter, replicaId)
 *
 * compared lexicographically. The `logical` counter breaks ties when two events
 * share a `physical` reading (rapid writes within one millisecond, or a remote
 * event dragging our clock forward); the `replicaId` is the final, deterministic
 * tie-break that makes the order TOTAL across replicas. There is deliberately no
 * exported "next ordinal" — a serial number usable for identity or cross-replica
 * ordering is structurally unavailable; the only ordering primitive is
 * `compareHlc`.
 */

export interface Hlc {
  /** physical clock reading (ms since epoch, or any monotonic wall source). */
  readonly physical: number;
  /** logical counter — increments when `physical` does not advance. */
  readonly logical: number;
  /** originating replica — provenance AND the final total-order tie-break. */
  readonly replicaId: string;
}

/**
 * Total order on HLCs: physical, then logical, then replicaId. Returns <0 when
 * `a` precedes `b`, >0 when `a` follows `b`, 0 only when they are identical.
 * This is the ONLY comparison the kernel sanctions for cross-replica ordering.
 */
export function compareHlc(a: Hlc, b: Hlc): number {
  if (a.physical !== b.physical) return a.physical < b.physical ? -1 : 1;
  if (a.logical !== b.logical) return a.logical < b.logical ? -1 : 1;
  if (a.replicaId !== b.replicaId) return a.replicaId < b.replicaId ? -1 : 1;
  return 0;
}

export function hlcEqual(a: Hlc, b: Hlc): boolean {
  return compareHlc(a, b) === 0;
}

/** Stable string form, e.g. "1721490000123:0:R1". Sortable-by-string within one physical/replica scale only — never rely on it for ordering; use compareHlc. */
export function hlcToString(h: Hlc): string {
  return `${h.physical}:${h.logical}:${h.replicaId}`;
}

export function parseHlc(s: string): Hlc {
  const parts = s.split(":");
  if (parts.length < 3) throw new Error(`invalid HLC string "${s}"`);
  const physical = Number(parts[0]);
  const logical = Number(parts[1]);
  const replicaId = parts.slice(2).join(":");
  if (!Number.isFinite(physical) || !Number.isFinite(logical) || !replicaId) {
    throw new Error(`invalid HLC string "${s}"`);
  }
  return { physical, logical, replicaId };
}

/**
 * A per-replica HLC generator. `tick()` stamps a locally-generated event;
 * `receive()` merges a remote event's HLC so causality survives sync. Each
 * replica owns exactly one clock; the `replicaId` is baked in at construction
 * and is never a mutable ordinal.
 */
export class HlcClock {
  private last: Hlc;

  constructor(
    public readonly replicaId: string,
    private readonly nowFn: () => number = Date.now,
  ) {
    if (!replicaId) throw new Error("HlcClock requires a non-empty replicaId");
    this.last = { physical: 0, logical: 0, replicaId };
  }

  /** The most recently issued HLC (does not advance the clock). */
  peek(): Hlc {
    return this.last;
  }

  /** Stamp a locally-generated event. Strictly greater than every prior local stamp. */
  tick(): Hlc {
    const wall = this.nowFn();
    const physical = Math.max(wall, this.last.physical);
    const logical = physical === this.last.physical ? this.last.logical + 1 : 0;
    this.last = { physical, logical, replicaId: this.replicaId };
    return this.last;
  }

  /**
   * Merge a remote event's HLC on receipt, then stamp our observation of it.
   * Guarantees the returned HLC follows BOTH our last local stamp and the
   * remote stamp — this is what keeps latest-wins convergent across replicas.
   */
  receive(remote: Hlc): Hlc {
    const wall = this.nowFn();
    const physical = Math.max(wall, this.last.physical, remote.physical);
    let logical: number;
    if (physical === this.last.physical && physical === remote.physical) {
      logical = Math.max(this.last.logical, remote.logical) + 1;
    } else if (physical === this.last.physical) {
      logical = this.last.logical + 1;
    } else if (physical === remote.physical) {
      logical = remote.logical + 1;
    } else {
      logical = 0;
    }
    this.last = { physical, logical, replicaId: this.replicaId };
    return this.last;
  }
}
