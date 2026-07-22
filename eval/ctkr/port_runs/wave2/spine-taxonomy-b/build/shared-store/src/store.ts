// The ONE shared wave-2 taxonomy-vocabulary store — event-sourced on the frozen
// kernel (src/kernel, v1.3, consumed via import, never vendored). The four
// spine-taxonomy-b features (product_type / season / test_method / unit) are
// pure Drupal taxonomy-vocabulary shells: each of their modules declares ONLY a
// `taxonomy.vocabulary.<vid>` config (vid, name, description) and adds NO fields,
// values, measures, or workflow states (partition-2026-07-22.jsonl: vocab_new 0;
// "no new fields/values/measures"). So every feature folds through this one
// store and differs only by which vocabulary its terms live in.
//
// Kernel primitives consumed (never re-implemented):
//   - ids: IdMinter (replica-scoped, collision-free; no bare ordinals)
//   - ordering: HlcClock only (no serial seq, no id-ordering)
//   - latest-wins: pickLatest / compareHlc for term name/description/weight
//
// SCOPE (spine, honest floor): a taxonomy vocabulary is a container of terms;
// each term carries the stock Drupal core fields name / description / weight, is
// created, renamed, re-described, re-weighted (all latest-wins), and deleted, and
// is listed in Drupal's default term order (weight asc, then name asc). Term
// HIERARCHY (TermInterface::parent — ancestry, children, cycle-prevention) is a
// core-taxonomy fold NOT introduced by any of these four leaf modules; per the
// wave plan core/* is ported once as a kernel+adapter, so it is a declared GAP
// here, not silently hand-rolled. See punts.jsonl (b-shared-1).

import {
  HlcClock,
  IdMinter,
  EventLog,
  KindRegistry,
  pickLatest,
  compareHlc,
  type KernelEvent,
  type EntityId,
  type Hlc,
  type KindSpec,
} from "../../../../../../../../src/kernel/index.ts";
import { makeTaxonomyRegistry } from "./kinds.ts";
import { type VocabularySpec, VOCABULARIES } from "./vocabularies.ts";

export type Handle = EntityId;

export interface TermCreatedPayload {
  termId: Handle;
  /** the vocabulary vid the term belongs to (product_type | season | ...). */
  vocab: string;
  name: string;
  description?: string;
  /** Drupal core term weight; default 0. Lower sorts first. */
  weight: number;
}

export interface TermRenamedPayload {
  termId: Handle;
  name: string;
}

export interface TermRedescribedPayload {
  termId: Handle;
  description?: string;
}

export interface TermReweightedPayload {
  termId: Handle;
  weight: number;
}

export interface TermDeletedPayload {
  termId: Handle;
}

export type StoreEvent = KernelEvent<string, unknown>;

/** A materialized term view: latest-wins name/description/weight, or undefined
 *  when the term is unknown or deleted. */
export interface TermView {
  termId: Handle;
  vocab: string;
  name: string;
  description?: string;
  weight: number;
  hlc: Hlc;
}

export interface StoreOptions {
  replicaId?: string;
  /** override the registered vocabulary set (defaults to the four spine-b vids). */
  vocabularies?: readonly VocabularySpec[];
  /** a feature's declared kind extension, registered before freeze. */
  extraKinds?: readonly KindSpec[];
}

export class TaxonomyVocabStore {
  readonly registry: KindRegistry;
  private readonly log: EventLog<StoreEvent>;
  private readonly clock: HlcClock;
  private readonly ids: IdMinter;
  private readonly vocabs: Map<string, VocabularySpec>;

  constructor(opts: StoreOptions = {}) {
    const replicaId = opts.replicaId ?? "R1";
    this.clock = new HlcClock(replicaId);
    this.ids = new IdMinter(replicaId);
    this.registry = makeTaxonomyRegistry(opts.extraKinds ?? []);
    this.log = new EventLog<StoreEvent>(this.registry);
    this.vocabs = new Map();
    for (const v of opts.vocabularies ?? VOCABULARIES) this.vocabs.set(v.vid, v);
  }

  // ---- primitives ---------------------------------------------------------
  private emit<P>(kind: string, payload: P): KernelEvent<string, P> {
    const e: KernelEvent<string, P> = {
      id: this.ids.mint("evt"),
      hlc: this.clock.tick(),
      kind,
      payload,
    };
    this.log.append(e);
    return e;
  }

  events(): readonly StoreEvent[] {
    return this.log.all();
  }

  private eventsOf<P>(kind: string): KernelEvent<string, P>[] {
    return this.events().filter((e) => e.kind === kind) as KernelEvent<string, P>[];
  }

  // ---- vocabulary descriptors ---------------------------------------------
  vocabulary(vid: string): VocabularySpec | undefined {
    return this.vocabs.get(vid);
  }

  vocabularyName(vid: string): string | undefined {
    return this.vocabs.get(vid)?.name;
  }

  hasVocabulary(vid: string): boolean {
    return this.vocabs.has(vid);
  }

  // ---- mutations ----------------------------------------------------------
  createTerm(input: {
    vocab: string;
    name: string;
    description?: string;
    weight?: number;
  }): Handle {
    if (!this.vocabs.has(input.vocab)) {
      throw new Error(`no vocabulary registered under vid ${input.vocab}`);
    }
    const termId = this.ids.mint("term");
    this.emit<TermCreatedPayload>("term_created", {
      termId,
      vocab: input.vocab,
      name: input.name,
      description: input.description,
      weight: input.weight ?? 0,
    });
    return termId;
  }

  renameTerm(termId: Handle, name: string): void {
    this.emit<TermRenamedPayload>("term_renamed", { termId, name });
  }

  setTermDescription(termId: Handle, description?: string): void {
    this.emit<TermRedescribedPayload>("term_redescribed", { termId, description });
  }

  setTermWeight(termId: Handle, weight: number): void {
    this.emit<TermReweightedPayload>("term_reweighted", { termId, weight });
  }

  deleteTerm(termId: Handle): void {
    this.emit<TermDeletedPayload>("term_deleted", { termId });
  }

  // ---- folded views -------------------------------------------------------
  private createdEvent(termId: Handle): KernelEvent<string, TermCreatedPayload> | undefined {
    return this.eventsOf<TermCreatedPayload>("term_created").find(
      (e) => e.payload.termId === termId,
    );
  }

  isTermDeleted(termId: Handle): boolean {
    return this.eventsOf<TermDeletedPayload>("term_deleted").some(
      (e) => e.payload.termId === termId,
    );
  }

  termView(termId: Handle): TermView | undefined {
    const created = this.createdEvent(termId);
    if (!created || this.isTermDeleted(termId)) return undefined;
    const c = created.payload;

    const name = pickLatest(
      [
        { hlc: created.hlc, name: c.name },
        ...this.eventsOf<TermRenamedPayload>("term_renamed")
          .filter((e) => e.payload.termId === termId)
          .map((e) => ({ hlc: e.hlc, name: e.payload.name })),
      ],
      (x) => x.hlc,
    )!.name;

    const description = pickLatest(
      [
        { hlc: created.hlc, description: c.description },
        ...this.eventsOf<TermRedescribedPayload>("term_redescribed")
          .filter((e) => e.payload.termId === termId)
          .map((e) => ({ hlc: e.hlc, description: e.payload.description })),
      ],
      (x) => x.hlc,
    )!.description;

    const weight = pickLatest(
      [
        { hlc: created.hlc, weight: c.weight },
        ...this.eventsOf<TermReweightedPayload>("term_reweighted")
          .filter((e) => e.payload.termId === termId)
          .map((e) => ({ hlc: e.hlc, weight: e.payload.weight })),
      ],
      (x) => x.hlc,
    )!.weight;

    return { termId, vocab: c.vocab, name, description, weight, hlc: created.hlc };
  }

  termName(termId: Handle): string | undefined {
    return this.termView(termId)?.name;
  }

  termDescription(termId: Handle): string | undefined {
    return this.termView(termId)?.description;
  }

  termWeight(termId: Handle): number | undefined {
    return this.termView(termId)?.weight;
  }

  /**
   * Live terms in a vocabulary, in Drupal's default term order: weight ascending,
   * then name ascending, with the kernel HLC as the deterministic final tie-break
   * (never id text). Deleted terms are excluded.
   */
  listTerms(vocab: string): TermView[] {
    const views: TermView[] = [];
    for (const e of this.eventsOf<TermCreatedPayload>("term_created")) {
      if (e.payload.vocab !== vocab) continue;
      const v = this.termView(e.payload.termId);
      if (v) views.push(v);
    }
    views.sort((a, b) =>
      a.weight !== b.weight
        ? a.weight - b.weight
        : a.name !== b.name
          ? a.name < b.name
            ? -1
            : 1
          : compareHlc(a.hlc, b.hlc),
    );
    return views;
  }

  termCount(vocab: string): number {
    return this.listTerms(vocab).length;
  }
}
