// The ONE shared wave-2 asset-bundle spine store — event-sourced on the frozen
// kernel (src/kernel, v1.3, consumed via import, never vendored). All seven
// concrete asset bundles (compost / equipment / material / plant / product /
// seed / water) are born through this one store's createAsset and read through
// its kernel-folded projections, exactly as the wave-1 Wave1LogStore serialized
// the four log features through one builder.
//
//   - ids: kernel IdMinter (replica-scoped, collision-free; no bare ordinals)
//   - ordering: kernel HLC only (asset_created / asset_archived carry an HLC)
//   - lifecycle: assetActive is the "no asset_archived event" fold — MONOTONIC
//     in this spine (once archived, inactive). farmOS's status field can flip
//     back to active; that reversal is NOT modeled here (punt
//     spine-asset-archive-monotonic) — the wave-1 asset spine took the same
//     monotonic reading, so this is continuity, not a new decision.
//
// The asset-bundle idiom this spine holds (cluster spine-asset):
//   - asset_created with a concrete `bundle` label
//   - archive lifecycle (assetActive / archiveAsset)
//   - is_location / is_fixed flags: per-asset booleans whose DEFAULT is the
//     bundle's farm_location third-party setting (only `water` declares them
//     true/true in this cluster; every other bundle defaults false/false). An
//     explicit per-asset override wins over the bundle default — the exact
//     LocationDefaultValues semantics (bundle setting is the *default*, source:
//     core/location/src/LocationDefaultValues.php).
//   - typed bundle fields carried verbatim on the creation event (the per-bundle
//     "typed creation surface"). Required-field constraints declared by a bundle
//     (material_type, plant_type, product_type) are enforced at creation.

import {
  HlcClock,
  IdMinter,
  EventLog,
  KindRegistry,
  type KernelEvent,
  type EntityId,
  type Hlc,
} from "../../../../../../../../src/kernel/index.ts";
import { makeSpineAssetRegistry, SPINE_ASSET_KINDS } from "./kinds.ts";
import type { KindSpec } from "../../../../../../../../src/kernel/index.ts";

export type Handle = EntityId;

/** Static, config-declared shape of one asset bundle (no per-asset state). */
export interface BundleConfig {
  bundle: string;
  /** farm_location is_location third-party setting → default for the asset field. */
  isLocationDefault: boolean;
  /** farm_location is_fixed third-party setting → default for the asset field. */
  isFixedDefault: boolean;
  /** field names this bundle's AssetType plugin declares (typed creation surface). */
  fields: readonly BundleFieldSpec[];
}

export interface BundleFieldSpec {
  name: string;
  /** required:TRUE in the AssetType field_info → creation must supply a non-empty value. */
  required: boolean;
  /** multiple:TRUE (entity_reference, cardinality unlimited) → stored as an array. */
  multiple: boolean;
}

/**
 * The seven concrete bundles of the spine-asset cluster, read straight from the
 * module sources (modules/asset/<bundle>): config/install/asset.type.<b>.yml for
 * the farm_location third-party settings, and the AssetType plugin's
 * buildFieldDefinitions() for the typed fields. NOTE: entity_reference fields
 * carry auto_create:TRUE in the source (Drupal creates a missing taxonomy term
 * on the fly); this spine stores the supplied term reference verbatim and does
 * NOT model term creation — see punt spine-asset-autocreate.
 */
export const SPINE_ASSET_BUNDLES: Readonly<Record<string, BundleConfig>> = {
  compost: { bundle: "compost", isLocationDefault: false, isFixedDefault: false, fields: [] },
  equipment: {
    bundle: "equipment",
    isLocationDefault: false,
    isFixedDefault: false,
    fields: [
      { name: "equipment_type", required: false, multiple: true },
      { name: "manufacturer", required: false, multiple: false },
      { name: "model", required: false, multiple: false },
      { name: "serial_number", required: false, multiple: false },
    ],
  },
  material: {
    bundle: "material",
    isLocationDefault: false,
    isFixedDefault: false,
    fields: [{ name: "material_type", required: true, multiple: false }],
  },
  plant: {
    bundle: "plant",
    isLocationDefault: false,
    isFixedDefault: false,
    fields: [
      { name: "plant_type", required: true, multiple: true },
      { name: "season", required: false, multiple: true },
    ],
  },
  product: {
    bundle: "product",
    isLocationDefault: false,
    isFixedDefault: false,
    fields: [{ name: "product_type", required: true, multiple: false }],
  },
  seed: {
    bundle: "seed",
    isLocationDefault: false,
    isFixedDefault: false,
    fields: [
      { name: "plant_type", required: true, multiple: true },
      { name: "season", required: false, multiple: true },
    ],
  },
  // water: the ONLY bundle in this cluster declaring farm_location third-party
  // settings (asset.type.water.yml: is_location:true, is_fixed:true).
  water: { bundle: "water", isLocationDefault: true, isFixedDefault: true, fields: [] },
};

export interface AssetCreatedPayload {
  assetId: Handle;
  bundle: string;
  name: string;
  /** resolved at creation: explicit override ?? bundle default. */
  isLocation: boolean;
  isFixed: boolean;
  /** typed bundle-field values (single string, or string[] for multiple fields). */
  fields: Readonly<Record<string, string | readonly string[]>>;
}

export interface AssetArchivedPayload {
  assetId: Handle;
}

export type StoreEvent = KernelEvent<string, unknown>;

/** Materialized asset view. */
export interface AssetView {
  assetId: Handle;
  bundle: string;
  name: string;
  active: boolean;
  isLocation: boolean;
  isFixed: boolean;
  fields: Readonly<Record<string, string | readonly string[]>>;
  hlc: Hlc;
}

export interface StoreOptions {
  replicaId?: string;
  extraKinds?: readonly KindSpec[];
}

export interface CreateAssetInput {
  bundle: string;
  name: string;
  /** per-asset override of the bundle's is_location default (LocationDefaultValues). */
  isLocation?: boolean;
  isFixed?: boolean;
  /** typed bundle-field values; validated against the bundle's declared fields. */
  fields?: Readonly<Record<string, string | readonly string[] | undefined>>;
}

export class SpineAssetStore {
  readonly registry: KindRegistry;
  private readonly log: EventLog<StoreEvent>;
  private readonly clock: HlcClock;
  private readonly ids: IdMinter;

  constructor(opts: StoreOptions = {}) {
    const replicaId = opts.replicaId ?? "R1";
    this.clock = new HlcClock(replicaId);
    this.ids = new IdMinter(replicaId);
    this.registry = makeSpineAssetRegistry(opts.extraKinds ?? []);
    this.log = new EventLog<StoreEvent>(this.registry);
  }

  // ---- primitives ---------------------------------------------------------
  mint(prefix: string): Handle {
    return this.ids.mint(prefix);
  }

  emit<P>(kind: string, payload: P): KernelEvent<string, P> {
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

  eventsOf<P>(kind: string): KernelEvent<string, P>[] {
    return this.events().filter((e) => e.kind === kind) as KernelEvent<string, P>[];
  }

  // ---- shared asset-bundle mutations --------------------------------------
  /**
   * Birth an asset into a bundle. Resolves the is_location/is_fixed flags from
   * the bundle default (override wins), validates the typed fields against the
   * bundle's declared field set, and enforces required-field constraints.
   */
  createAsset(input: CreateAssetInput): Handle {
    const config = SPINE_ASSET_BUNDLES[input.bundle];
    if (!config) throw new Error(`unknown asset bundle ${input.bundle}`);

    const fields = this.validateFields(config, input.fields ?? {});
    const assetId = this.ids.mint("asset");
    this.emit<AssetCreatedPayload>("asset_created", {
      assetId,
      bundle: input.bundle,
      name: input.name,
      isLocation: input.isLocation ?? config.isLocationDefault,
      isFixed: input.isFixed ?? config.isFixedDefault,
      fields,
    });
    return assetId;
  }

  /** Normalize + constraint-check a bundle's typed field values. */
  private validateFields(
    config: BundleConfig,
    supplied: Readonly<Record<string, string | readonly string[] | undefined>>,
  ): Record<string, string | readonly string[]> {
    const declared = new Map(config.fields.map((f) => [f.name, f]));
    for (const key of Object.keys(supplied)) {
      if (!declared.has(key)) {
        throw new Error(`bundle ${config.bundle} declares no field '${key}'`);
      }
    }
    const out: Record<string, string | readonly string[]> = {};
    for (const spec of config.fields) {
      const raw = supplied[spec.name];
      const empty =
        raw === undefined ||
        raw === "" ||
        (Array.isArray(raw) && raw.length === 0);
      if (empty) {
        if (spec.required) {
          throw new Error(
            `bundle ${config.bundle} requires field '${spec.name}'`,
          );
        }
        continue;
      }
      if (spec.multiple) {
        out[spec.name] = Array.isArray(raw) ? [...raw] : [raw as string];
      } else {
        if (Array.isArray(raw)) {
          throw new Error(
            `field '${spec.name}' on bundle ${config.bundle} is single-valued`,
          );
        }
        out[spec.name] = raw as string;
      }
    }
    return out;
  }

  archiveAsset(assetId: Handle): void {
    this.emit<AssetArchivedPayload>("asset_archived", { assetId });
  }

  // ---- folded views --------------------------------------------------------
  private createdEvent(assetId: Handle): KernelEvent<string, AssetCreatedPayload> | undefined {
    return this.eventsOf<AssetCreatedPayload>("asset_created").find(
      (e) => e.payload.assetId === assetId,
    );
  }

  /** MONOTONIC archive fold: any asset_archived event → inactive. */
  assetActive(assetId: Handle): boolean {
    if (!this.createdEvent(assetId)) return false;
    return !this.eventsOf<AssetArchivedPayload>("asset_archived").some(
      (e) => e.payload.assetId === assetId,
    );
  }

  assetView(assetId: Handle): AssetView | undefined {
    const rec = this.createdEvent(assetId);
    if (!rec) return undefined;
    const p = rec.payload;
    return {
      assetId: p.assetId,
      bundle: p.bundle,
      name: p.name,
      active: this.assetActive(assetId),
      isLocation: p.isLocation,
      isFixed: p.isFixed,
      fields: p.fields,
      hlc: rec.hlc,
    };
  }

  bundleOf(assetId: Handle): string | undefined {
    return this.createdEvent(assetId)?.payload.bundle;
  }

  assetName(assetId: Handle): string | undefined {
    return this.createdEvent(assetId)?.payload.name;
  }

  isLocation(assetId: Handle): boolean | undefined {
    return this.createdEvent(assetId)?.payload.isLocation;
  }

  isFixed(assetId: Handle): boolean | undefined {
    return this.createdEvent(assetId)?.payload.isFixed;
  }

  /** A typed bundle-field value, or undefined when unset/unknown. */
  fieldOf(assetId: Handle, name: string): string | readonly string[] | undefined {
    return this.createdEvent(assetId)?.payload.fields[name];
  }

  /** All assets of a bundle, in creation (HLC) order. */
  listByBundle(bundle: string): Handle[] {
    return this.eventsOf<AssetCreatedPayload>("asset_created")
      .filter((e) => e.payload.bundle === bundle)
      .map((e) => e.payload.assetId);
  }
}

export { SPINE_ASSET_KINDS };
