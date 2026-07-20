/**
 * Client-generated, collision-free entity identifiers (kernel element 2a).
 *
 * WHY THIS EXISTS. The composed 9h5.16 build regressed the ID scheme to a bare
 * integer counter (`asset_7`) drawn from one global `seq`
 * (two-feature-composition-2026-07-20.md §4, "ID minting" row). That is the exact
 * `autoincrement-id` anti-pattern the target profile warns against: two replicas
 * each mint `asset_1` offline and COLLIDE on merge. The kernel removes the
 * attractor by construction — the only id minter requires a replicaId and folds
 * it into every id, so ids are collision-free across replicas without a central
 * gate. The per-replica counter is never exposed as a comparable number: it
 * cannot be used for identity (only the whole opaque id is) or for cross-replica
 * ordering (that is the HLC's job). A serial ordinal usable for either is
 * structurally unavailable.
 */

declare const idBrand: unique symbol;

/**
 * An opaque, client-generated entity handle. Branded so a bare number or
 * arbitrary string can never be assigned where an EntityId is required — the
 * only way to obtain one is {@link IdMinter.mint}.
 */
export type EntityId = string & { readonly [idBrand]: "EntityId" };

/** The separator between a replica scope and its local counter (`asset_R1~7`). */
export const REPLICA_SEP = "~";

/**
 * A per-replica id generator. Every id is `${prefix}_${replicaId}~${counter}`:
 * client-generated (no server round-trip), collision-free across replicas (the
 * replicaId scopes the counter), and opaque (the counter carries no
 * cross-replica meaning). There is deliberately no method that returns a bare
 * ordinal.
 */
export class IdMinter {
  private counter = 0;

  constructor(public readonly replicaId: string) {
    if (!replicaId) {
      throw new Error(
        "IdMinter requires a non-empty replicaId — collision-free client ids must be replica-scoped (a bare global counter collides on merge).",
      );
    }
    if (replicaId.includes(REPLICA_SEP)) {
      throw new Error(`replicaId must not contain "${REPLICA_SEP}"`);
    }
  }

  /** Mint the next collision-free id. `prefix` is cosmetic (debugging only). */
  mint(prefix = "e"): EntityId {
    this.counter += 1;
    return `${prefix}_${this.replicaId}${REPLICA_SEP}${this.counter}` as EntityId;
  }

  /** How many ids this replica has minted (diagnostics only — NOT an identity). */
  get minted(): number {
    return this.counter;
  }
}

/** Structural check that a value looks like a replica-scoped kernel id. */
export function isEntityId(v: unknown): v is EntityId {
  return typeof v === "string" && new RegExp(`${REPLICA_SEP}\\d+$`).test(v);
}

/** The replica that minted an id (provenance). Never use this to ORDER ids. */
export function replicaOf(id: EntityId): string {
  const body = id.slice(id.indexOf("_") + 1);
  return body.slice(0, body.lastIndexOf(REPLICA_SEP));
}
