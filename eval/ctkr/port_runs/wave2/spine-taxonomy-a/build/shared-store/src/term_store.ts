// The ONE shared wave-2 taxonomy-term store — event-sourced on the frozen kernel
// (src/kernel, v1.3, consumed via import, never vendored). All five spine-
// taxonomy-a vocabularies (animal_type / equipment_type / lab / log_category /
// material_type) append through this one store and read through its kernel-folded
// projections, so they serialize through one builder (the one-mind lesson).
//
// The taxonomy idiom, modeled once:
//   - a term is a kernel entity scoped to a vocabulary (the Drupal `vid`/bundle)
//   - fields (name, parent, description, weight, status) are EDITABLE — the
//     farmOS vocab configs all carry `new_revision: false`, so there is no
//     revision history: latest write wins, folded via the kernel HLC comparator
//     (pickLatest). No field is grow-only.
//   - hierarchy is a single parent reference (Drupal-core term parent is
//     multi-valued, but every farmOS consumer here — e.g. log_category's
//     loadTree/depth — assumes a tree; single-parent is the modeled case, and
//     multi-parent DAG membership is a DECLARED GAP, not silently folded).
//
// Kernel primitives consumed:
//   - ids:        IdMinter (replica-scoped, collision-free; no bare ordinals)
//   - ordering:   HLC only (deterministic tie-break; no serial seq, no id-order)
//   - latest-wins: pickLatest over HLC-stamped candidates (per-field fold)
//   - kinds:      KindRegistry / EventLog (closed kind taxonomy, frozen)
//
// NOT modeled here (punted up — see build/log_category/punts.jsonl): the
// log_category module also injects a `category` entity_reference base field onto
// every LOG entity and ships a LogCategorize bulk action with append/replace +
// dedup merge semantics. That is a fold on the LOG family, not on the term store,
// and the vocabulary scan that tiered this cluster SPINE never opened it.

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

export type Handle = EntityId;

/** The five spine-taxonomy-a vocabularies (Drupal `vid` / term bundle). */
export type Vocabulary =
  | "animal_type"
  | "equipment_type"
  | "lab"
  | "log_category"
  | "material_type";

/** Fields settable at creation and editable afterward (all latest-wins). */
export interface TermInput {
  name: string;
  /** parent term handle, or null/undefined for a root term. */
  parent?: Handle | null;
  description?: string;
  /** ordering weight (Drupal default 0); lower sorts first. */
  weight?: number;
  /** published/active flag; loadTree consumers filter on this. Default true. */
  status?: boolean;
}

/** A partial edit — only the named fields are restated (latest-wins per field). */
export interface TermPatch {
  name?: string;
  parent?: Handle | null;
  description?: string;
  weight?: number;
  status?: boolean;
}

export interface TermCreatedPayload extends Required<Pick<TermInput, "name">> {
  termId: Handle;
  vocabulary: Vocabulary;
  parent: Handle | null;
  description?: string;
  weight: number;
  status: boolean;
}

export interface TermUpdatedPayload {
  targetId: Handle;
  patch: TermPatch;
}

export interface TermDeletedPayload {
  termId: Handle;
}

export type StoreEvent = KernelEvent<string, unknown>;

/** A materialized term view (latest-wins on every field; excludes deleted). */
export interface TermView {
  termId: Handle;
  vocabulary: Vocabulary;
  name: string;
  parent: Handle | null;
  description?: string;
  weight: number;
  status: boolean;
  hlc: Hlc;
}

/** Closed kind taxonomy for the wave-2 taxonomy-term family. */
export const TAXONOMY_KINDS: readonly KindSpec[] = [
  { kind: "term_created", family: "taxonomy", isLog: false, description: "births a taxonomy term into a vocabulary" },
  { kind: "term_updated", family: "taxonomy", isLog: false, description: "latest-wins restatement of one or more editable term fields" },
  { kind: "term_deleted", family: "lifecycle", isLog: false, description: "deletion of a term; children are left dangling (parent points to a gone id)" },
];

export function makeTaxonomyRegistry(extra: readonly KindSpec[] = []): KindRegistry {
  return new KindRegistry().extend(TAXONOMY_KINDS).extend(extra).freeze();
}

export interface StoreOptions {
  replicaId?: string;
  extraKinds?: readonly KindSpec[];
}

export class TaxonomyTermStore {
  readonly registry: KindRegistry;
  private readonly log: EventLog<StoreEvent>;
  private readonly clock: HlcClock;
  private readonly ids: IdMinter;

  constructor(opts: StoreOptions = {}) {
    const replicaId = opts.replicaId ?? "R1";
    this.clock = new HlcClock(replicaId);
    this.ids = new IdMinter(replicaId);
    this.registry = makeTaxonomyRegistry(opts.extraKinds ?? []);
    this.log = new EventLog<StoreEvent>(this.registry);
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

  // ---- mutations ----------------------------------------------------------
  createTerm(vocabulary: Vocabulary, input: TermInput): Handle {
    const termId = this.ids.mint("term");
    this.emit<TermCreatedPayload>("term_created", {
      termId,
      vocabulary,
      name: input.name,
      parent: input.parent ?? null,
      description: input.description,
      weight: input.weight ?? 0,
      status: input.status ?? true,
    });
    return termId;
  }

  /** Restate one or more editable fields; each folds latest-wins independently. */
  updateTerm(targetId: Handle, patch: TermPatch): void {
    this.emit<TermUpdatedPayload>("term_updated", { targetId, patch });
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

  isDeleted(termId: Handle): boolean {
    return this.eventsOf<TermDeletedPayload>("term_deleted").some(
      (e) => e.payload.termId === termId,
    );
  }

  /** Latest-wins value of one field, folded over creation + all restatements. */
  private latestField<K extends keyof TermPatch>(
    termId: Handle,
    field: K,
    base: NonNullable<TermView[K & keyof TermView]>,
  ): TermView[K & keyof TermView] {
    const created = this.createdEvent(termId)!;
    const candidates: { hlc: Hlc; value: unknown }[] = [
      { hlc: created.hlc, value: base },
    ];
    for (const e of this.eventsOf<TermUpdatedPayload>("term_updated")) {
      if (e.payload.targetId !== termId) continue;
      if (Object.prototype.hasOwnProperty.call(e.payload.patch, field)) {
        candidates.push({ hlc: e.hlc, value: e.payload.patch[field] });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)!.value as TermView[K & keyof TermView];
  }

  /** Materialized term view, or undefined when unknown or deleted. */
  termView(termId: Handle): TermView | undefined {
    const created = this.createdEvent(termId);
    if (!created || this.isDeleted(termId)) return undefined;
    const p = created.payload;
    const description = this.latestField(termId, "description", (p.description ?? "") as string);
    return {
      termId,
      vocabulary: p.vocabulary,
      name: this.latestField(termId, "name", p.name) as string,
      parent: this.latestField(termId, "parent", p.parent as unknown as Handle) as Handle | null,
      description: description === "" ? undefined : (description as string),
      weight: this.latestField(termId, "weight", p.weight) as number,
      status: this.latestField(termId, "status", p.status) as boolean,
      hlc: created.hlc,
    };
  }

  /**
   * Live terms in a vocabulary, ordered (weight asc, name asc) with the kernel
   * HLC as the deterministic tie-break — the Drupal default term ordering with
   * the forbidden id tie-break replaced by the HLC (the wave-1 w0a-2 rule).
   * `activeOnly` filters to published terms (status === true), matching the
   * loadTree consumers.
   */
  termsInVocabulary(
    vocabulary: Vocabulary,
    opts: { activeOnly?: boolean } = {},
  ): TermView[] {
    const views: TermView[] = [];
    for (const e of this.eventsOf<TermCreatedPayload>("term_created")) {
      if (e.payload.vocabulary !== vocabulary) continue;
      const v = this.termView(e.payload.termId);
      if (!v) continue;
      if (opts.activeOnly && !v.status) continue;
      views.push(v);
    }
    views.sort((a, b) =>
      a.weight !== b.weight
        ? a.weight - b.weight
        : a.name !== b.name
          ? a.name < b.name ? -1 : 1
          : compareHlc(a.hlc, b.hlc),
    );
    return views;
  }

  /** Direct children of a parent term (same ordering as termsInVocabulary). */
  childrenOf(parentId: Handle): TermView[] {
    const parent = this.termView(parentId);
    if (!parent) return [];
    return this.termsInVocabulary(parent.vocabulary).filter((v) => v.parent === parentId);
  }

  /** Root terms of a vocabulary (parent === null). */
  rootsOf(vocabulary: Vocabulary, opts: { activeOnly?: boolean } = {}): TermView[] {
    return this.termsInVocabulary(vocabulary, opts).filter((v) => v.parent === null);
  }

  /**
   * Ancestor chain (nearest parent first), walking the single-parent reference.
   * Cycle-guarded defensively (edited parents could form one); a repeated id
   * terminates the walk rather than looping.
   */
  ancestorsOf(termId: Handle): TermView[] {
    const chain: TermView[] = [];
    const seen = new Set<Handle>([termId]);
    let cur = this.termView(termId);
    while (cur && cur.parent !== null) {
      if (seen.has(cur.parent)) break;
      seen.add(cur.parent);
      const parent = this.termView(cur.parent);
      if (!parent) break; // dangling parent (deleted ancestor)
      chain.push(parent);
      cur = parent;
    }
    return chain;
  }

  /** Tree depth: 0 for a root term, +1 per ancestor. Matches loadTree depth. */
  depthOf(termId: Handle): number {
    return this.ancestorsOf(termId).length;
  }
}
