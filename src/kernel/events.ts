/**
 * Event envelope + closed kind taxonomy (kernel element 1).
 *
 * WHY THIS EXISTS. Two features that each pass their own pack can still encode
 * incompatible answers to "is a movement a log?": one calls movements a distinct
 * kind (excluded from logCount), another models them as farmOS `activity` logs
 * (included). Both are internally consistent; folded into one store they
 * DISAGREE on logCount('activity') for the same asset (CP2,
 * two-feature-composition-2026-07-20.md §3). The kernel closes the taxonomy: an
 * event's kind must be REGISTERED (with a declared family + facets) before the
 * log will accept it, and features extend the taxonomy only through an explicit
 * `register` call — never an ad-hoc string at an append site.
 *
 * The is-a-movement-a-log question is thereby resolved centrally, once, by the
 * `isLog` facet on each KindSpec (see the build's registry), not per feature.
 */

import type { Hlc } from "./hlc.ts";
import type { EntityId } from "./ids.ts";
import type { StatusGate } from "./status.ts";

/**
 * The declared shape of one event kind. `family` is a coarse grouping; `isLog`
 * is the load-bearing facet that resolves is-a-movement-a-log (a movement kind
 * declares `isLog: false`); `statusGate` names the default gate for a kind that
 * carries a pending/done lifecycle.
 */
export interface KindSpec {
  readonly kind: string;
  readonly family: string;
  /** true iff this kind counts as a domain "log" (logCount / yield folds). */
  readonly isLog: boolean;
  /** the status gate for the kind's own lifecycle, when it has one. */
  readonly statusGate?: StatusGate;
  readonly description?: string;
}

/**
 * The universal event envelope. Every event carries a client-generated id, an
 * HLC (the sole ordering key — there is no serial ordinal), a registered kind,
 * and a typed payload. `P` is refined per kind by the consuming build.
 */
export interface KernelEvent<K extends string = string, P = unknown> {
  readonly id: EntityId;
  readonly hlc: Hlc;
  readonly kind: K;
  readonly payload: P;
}

/**
 * The closed kind taxonomy. A build seeds the core kinds, `freeze()`s it, and a
 * feature may only extend it with a further explicit `register` BEFORE freezing.
 * `EventLog` consults it to reject any kind not declared here.
 */
export class KindRegistry {
  private readonly specs = new Map<string, KindSpec>();
  private frozen = false;

  register(spec: KindSpec): this {
    if (this.frozen) {
      throw new Error(
        `KindRegistry is frozen — cannot register "${spec.kind}" after freeze (the taxonomy is closed at wave-1 build time).`,
      );
    }
    if (!spec.kind) throw new Error("KindSpec.kind must be a non-empty string");
    if (this.specs.has(spec.kind)) {
      throw new Error(`duplicate kind registration "${spec.kind}"`);
    }
    this.specs.set(spec.kind, spec);
    return this;
  }

  /** Register several kinds (a feature's declared extension). */
  extend(specs: readonly KindSpec[]): this {
    for (const s of specs) this.register(s);
    return this;
  }

  freeze(): this {
    this.frozen = true;
    return this;
  }

  get isFrozen(): boolean {
    return this.frozen;
  }

  has(kind: string): boolean {
    return this.specs.has(kind);
  }

  spec(kind: string): KindSpec {
    const s = this.specs.get(kind);
    if (!s) {
      throw new Error(
        `unknown event kind "${kind}" — not in the closed taxonomy {${this.kinds().join(", ")}}. Register it via KindRegistry.register (no ad-hoc kinds).`,
      );
    }
    return s;
  }

  isLog(kind: string): boolean {
    return this.spec(kind).isLog;
  }

  kinds(): string[] {
    return [...this.specs.keys()];
  }
}

/**
 * The append-only event log. It is the single choke point through which every
 * mutation flows, and it rejects any event whose kind is not in the registry —
 * this is what makes "no ad-hoc kinds" a construction guarantee, not a
 * convention.
 */
export class EventLog<E extends KernelEvent = KernelEvent> {
  private readonly events: E[] = [];

  constructor(private readonly registry: KindRegistry) {}

  append(event: E): E {
    if (!this.registry.has(event.kind)) {
      throw new Error(
        `ad-hoc event kind "${event.kind}" rejected — not in the frozen taxonomy {${this.registry.kinds().join(", ")}}.`,
      );
    }
    this.events.push(event);
    return event;
  }

  all(): readonly E[] {
    return this.events;
  }

  /** Type-narrowing filter over the log (a thin convenience for projections). */
  select<T extends E>(pred: (e: E) => e is T): T[] {
    return this.events.filter(pred);
  }
}
