// The ONE shared wave-1 log-family store — event-sourced on the frozen kernel
// (src/kernel, v1.3, consumed via import, never vendored). All four wave-1
// features (activity / observation / harvest / input) append through this one
// store and read through its kernel-folded projections, which is why they
// serialize through one builder (the 27/27 one-mind lesson).
//
//   - ids: kernel IdMinter (replica-scoped, collision-free; no bare ordinals)
//   - ordering: kernel HLC only (no serial seq, no id-ordering)
//   - latest-wins: kernel pickLatest / compareHlc
//   - status gates: kernel STATUS_CONTRACT rows yieldTotal / pendingYieldTotal /
//     logCount / pendingLogCount / logStatus — the one chosen divergence
//     (confirmed-only official numerics + pending-only partners) is implemented
//     here, once, for the whole family.
//
// Deliberate readings taken from the observed boundary (observation/scope.md
// post-observation note) where the kernel binds nothing:
//   - yield folds are NOT as-of-gated (a future-dated done log counts now)
//   - yield folds sum ACROSS domain log kinds (observation + harvest merge)
//   - log listing order is ascending (effectiveTime, HLC) — the LogQueryFactory
//     sort with the id tie-break replaced by the kernel HLC (decision w0a-2)

import {
  HlcClock,
  IdMinter,
  EventLog,
  KindRegistry,
  pickLatest,
  compareHlc,
  gateFor,
  passesGate,
  type KernelEvent,
  type EntityId,
  type Hlc,
  type LifecycleStatus,
} from "../../../../../../src/kernel/index.ts";
import { makeWave1Registry } from "./kinds.ts";
import type { KindSpec } from "../../../../../../src/kernel/index.ts";

export type Handle = EntityId;

/** One measured quantity as recorded on a log (glossary QuantitySpec + wave-1 extras). */
export interface QuantityInput {
  measure: string;
  value: number;
  unit: string;
  label?: string;
  /** quantity bundle, e.g. "material" | "standard" (input feature). */
  quantityType?: string;
  /** material_type taxonomy terms (multi-valued, input feature). */
  materialTypes?: readonly string[];
  /**
   * The asset this quantity's inventory refers to (core-inventory
   * `inventory_asset`). The material quantity_presave fold keys off it
   * (MetaCoding-5ln): a material quantity referencing a material asset
   * inherits the asset's material type AT RECORD TIME — a snapshot copy,
   * exactly like the source's presave hook; later changes to the asset do
   * not restate recorded quantities.
   */
  inventoryAssetId?: Handle;
  /**
   * The testing methods a quantity--test states (core farm_quantity_test
   * TestQuantity.php `test_method`, a multi-valued entity_reference to
   * taxonomy_term--test_method), carried as ordered term NAMES (MetaCoding-wgy
   * lab_test_measurement). Only a `quantityType === "test"` quantity carries
   * one; the wire delivers at most a single method per quantity, wrapped as a
   * one-name list so the fold honours the source's ordered-list shape.
   */
  testMethods?: readonly string[];
}

export interface QuantityRecord extends QuantityInput {
  quantityId: Handle;
}

/** Feature-specific optional metadata carried verbatim on a log payload. */
export interface LogExtras {
  notes?: string;
  lotNumber?: string;
  method?: string;
  purchaseDate?: number; // inert metadata — NEVER an ordering key (input scope)
  source?: string;
  /** harvest: the exact recorded quantity payload incl. [null] (contract w1c). */
  quantityPayload?: readonly (QuantityInput | null)[];
  // --- lab_test bundle fields (MetaCoding-wgy) -----------------------------
  // The five attributes farm_lab_test LabTestLog.php adds to log--lab_test.
  // Verbatim boundary transcriptions (a list_string category, two absolute
  // ISO dates, a free string, a laboratory NAME): the source states each on
  // the log; the port carries each unchanged and reads it back as recorded.
  // Present only on logs that stated them (i.e. lab_test logs) — a log without
  // the field reads back the empty value, exactly as the absent-field contrast.
  /** lab_test_type — the specimen category (soil / tissue / water / …). */
  labSampleType?: string;
  /** lab — the NAME of the laboratory that performed the test. */
  laboratory?: string;
  /** lab_processed_date — absolute ISO-8601 date the lab processed the sample. */
  labProcessedDate?: string;
  /** lab_received_date — absolute ISO-8601 date the lab received the sample. */
  labReceivedDate?: string;
  /** soil_texture — free-string texture the lab reported. */
  soilTexture?: string;
}

export interface AssetCreatedPayload {
  assetId: Handle;
  entity: string;
  name: string;
  descriptor?: string;
  sex?: string;
}

/**
 * The birth of a plant_type TAXONOMY TERM (MetaCoding plant-type, farm_plant_type)
 * carrying the four planning fields the plant_type identity port reads back.
 * A plant_type is NOT a log — it is a term entity, so it births through its own
 * event rather than record_log. Present-only fields: each planning field rides
 * on the payload ONLY when the term stated it, so an unstated field materializes
 * as the recorded absent-value contrast the pack scores ("" / []), never a value
 * the term never carried.
 *   - maturityDays / harvestDays: the term's own integer fields (distinct fields,
 *     never blended — a term with a maturity but no harvest reads maturity and "").
 *   - cropFamily: the NAME of the single-valued crop_family the term references
 *     (a reproducible string the wire delivers, never a per-run term id).
 *   - companions: the ORDERED NAMES of the plant_type terms referenced as
 *     companions (reproducible strings, order preserved).
 */
export interface PlantTypeTermCreatedPayload {
  termId: Handle;
  name: string;
  maturityDays?: number;
  harvestDays?: number;
  cropFamily?: string;
  companions?: readonly string[];
}

/**
 * The birth of a SENSOR ASSET (MetaCoding-ej0, farm_sensor asset--sensor)
 * carrying the three bundle fields the sensor identity port reads back.
 * A sensor IS an asset — asset_active / archive_asset apply to its handle —
 * but it births through its own event, not asset_created, so a sensor probe
 * can refuse a non-sensor subject (unanswerable, never an empty value).
 * Present-only fields: each rides on the payload ONLY when the sensor stated
 * it, so an unstated field materializes as the recorded absent-value contrast
 * ("" / []), never a value the sensor never carried.
 *   - dataStreams: the ORDERED NAMES of the sensor's data streams, verbatim as
 *     recorded (recorded order, NOT name order — the non-alphabetical fixture).
 *     Names are the reproducible identity; two sensors naming the same stream
 *     name each carry their own recorded copy (no global stream registry).
 *   - privateKey: the recorded key string, verbatim.
 *   - public: the recorded flag. `false` is a stated VALUE distinct from
 *     unstated — the field rides whenever the flag was stated, either way.
 */
export interface SensorAssetCreatedPayload {
  assetId: Handle;
  name: string;
  dataStreams?: readonly string[];
  privateKey?: string;
  public?: boolean;
}

export interface LogRecordedPayload {
  logId: Handle;
  /** the domain log bundle: activity | observation | harvest | input | ... */
  kind: string;
  name: string;
  status: LifecycleStatus;
  assetIds: readonly Handle[];
  quantities: readonly QuantityRecord[];
  /** valid-time of the log (epoch ms). Restatements supersede it latest-wins. */
  effectiveTime: number;
  extras?: LogExtras;
  /**
   * Equipment assets the log states as used — the cross-family `equipment`
   * base field farm_equipment adds to EVERY log (MetaCoding-1cv; owned by the
   * log spine, not the asset bundle). Additive and optional: events recorded
   * before the field existed fold as [].
   */
  equipmentIds?: readonly Handle[];
}

export interface LogStatusChangedPayload {
  targetId: Handle;
  status: LifecycleStatus;
}

export interface LogTimeRestatedPayload {
  targetId: Handle;
  effectiveTime: number;
}

export interface AssetArchivedPayload {
  assetId: Handle;
}

export interface LogDeletedPayload {
  logId: Handle;
}

export interface QuantityDeletedPayload {
  quantityId: Handle;
}

export type StoreEvent = KernelEvent<string, unknown>;

/** A materialized log view (deleted quantities removed, latest status/time). */
export interface LogView {
  logId: Handle;
  kind: string;
  name: string;
  status: LifecycleStatus;
  assetIds: readonly Handle[];
  quantities: readonly QuantityRecord[];
  effectiveTime: number;
  extras?: LogExtras;
  /** Equipment stated as used; [] for logs recorded before the field existed. */
  equipmentIds: readonly Handle[];
  hlc: Hlc;
}

export interface StoreOptions {
  replicaId?: string;
  /** a feature's declared kind extension, registered before freeze. */
  extraKinds?: readonly KindSpec[];
}

export class Wave1LogStore {
  readonly registry: KindRegistry;
  private readonly log: EventLog<StoreEvent>;
  private readonly clock: HlcClock;
  private readonly ids: IdMinter;

  constructor(opts: StoreOptions = {}) {
    const replicaId = opts.replicaId ?? "R1";
    this.clock = new HlcClock(replicaId);
    this.ids = new IdMinter(replicaId);
    this.registry = makeWave1Registry(opts.extraKinds ?? []);
    this.log = new EventLog<StoreEvent>(this.registry);
  }

  // ---- primitives ---------------------------------------------------------
  mint(prefix: string): Handle {
    return this.ids.mint(prefix);
  }

  /** Append any registered event kind (feature kinds included). */
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

  now(): number {
    return Date.now();
  }

  // ---- shared mutations ----------------------------------------------------
  createAsset(input: { entity: string; name: string; descriptor?: string; sex?: string }): Handle {
    const assetId = this.ids.mint("asset");
    this.emit<AssetCreatedPayload>("asset_created", { assetId, ...input });
    return assetId;
  }

  /**
   * Birth a plant_type TAXONOMY TERM carrying its planning fields (MetaCoding
   * plant-type). Distinct terms are distinct handles. Each planning field is
   * carried ONLY when stated, so an unstated field folds back as the recorded
   * empty-value contrast ("" / []) — the store never invents a value the term
   * did not carry. crop_family and companions are recorded as the NAMES the wire
   * delivers (never per-run ids), so the readback reproduces across runs/ports.
   */
  createPlantTypeTerm(input: {
    name: string;
    maturityDays?: number;
    harvestDays?: number;
    cropFamily?: string;
    companions?: readonly string[];
  }): Handle {
    const termId = this.ids.mint("term");
    this.emit<PlantTypeTermCreatedPayload>("plant_type_term_created", {
      termId,
      name: input.name,
      ...(input.maturityDays !== undefined ? { maturityDays: input.maturityDays } : {}),
      ...(input.harvestDays !== undefined ? { harvestDays: input.harvestDays } : {}),
      ...(input.cropFamily ? { cropFamily: input.cropFamily } : {}),
      ...(input.companions?.length ? { companions: [...input.companions] } : {}),
    });
    return termId;
  }

  /**
   * Birth a SENSOR ASSET carrying its bundle fields (MetaCoding-ej0). Distinct
   * sensors are distinct handles. Each field is carried ONLY when stated:
   * an empty-string key and an empty stream list are the wire's "unstated"
   * shapes and are left off, while `public: false` is a stated VALUE and rides
   * (false !== unstated — the public-false-is-a-value fixture contrast). The
   * store copies the stream list, so the readback is materialized state, never
   * an echo of a caller-held array.
   */
  createSensorAsset(input: {
    name: string;
    dataStreams?: readonly string[];
    privateKey?: string;
    public?: boolean;
  }): Handle {
    const assetId = this.ids.mint("asset");
    this.emit<SensorAssetCreatedPayload>("sensor_asset_created", {
      assetId,
      name: input.name,
      ...(input.dataStreams?.length ? { dataStreams: [...input.dataStreams] } : {}),
      ...(input.privateKey ? { privateKey: input.privateKey } : {}),
      ...(input.public !== undefined ? { public: input.public } : {}),
    });
    return assetId;
  }

  recordLog(input: {
    kind: string;
    name: string;
    status: LifecycleStatus;
    assetIds: readonly Handle[];
    quantities: readonly QuantityInput[];
    effectiveTime?: number;
    extras?: LogExtras;
    equipmentIds?: readonly Handle[];
  }): Handle {
    const logId = this.ids.mint("log");
    const quantities: QuantityRecord[] = input.quantities.map((q) => ({
      ...q,
      ...this.materialFold(q),
      quantityId: this.ids.mint("qty"),
    }));
    this.emit<LogRecordedPayload>("log_recorded", {
      logId,
      kind: input.kind,
      name: input.name,
      status: input.status,
      assetIds: [...input.assetIds],
      quantities,
      effectiveTime: input.effectiveTime ?? this.now(),
      extras: input.extras,
      ...(input.equipmentIds?.length
        ? { equipmentIds: [...input.equipmentIds] }
        : {}),
    });
    return logId;
  }

  setLogStatus(targetId: Handle, status: LifecycleStatus): void {
    this.emit<LogStatusChangedPayload>("log_status_changed", { targetId, status });
  }

  restateEffectiveTime(targetId: Handle, effectiveTime: number): void {
    this.emit<LogTimeRestatedPayload>("log_time_restated", { targetId, effectiveTime });
  }

  archiveAsset(assetId: Handle): void {
    this.emit<AssetArchivedPayload>("asset_archived", { assetId });
  }

  deleteLog(logId: Handle): void {
    this.emit<LogDeletedPayload>("log_deleted", { logId });
  }

  deleteQuantity(quantityId: Handle): void {
    this.emit<QuantityDeletedPayload>("quantity_deleted", { quantityId });
  }

  // ---- folded views --------------------------------------------------------
  private recordedEvent(logId: Handle): KernelEvent<string, LogRecordedPayload> | undefined {
    return this.eventsOf<LogRecordedPayload>("log_recorded").find(
      (e) => e.payload.logId === logId,
    );
  }

  isLogDeleted(logId: Handle): boolean {
    return this.eventsOf<LogDeletedPayload>("log_deleted").some(
      (e) => e.payload.logId === logId,
    );
  }

  isQuantityDeleted(quantityId: Handle): boolean {
    return this.eventsOf<QuantityDeletedPayload>("quantity_deleted").some(
      (e) => e.payload.quantityId === quantityId,
    );
  }

  /** Latest-wins lifecycle status (STATUS_CONTRACT.logStatus: count-regardless). */
  logStatus(logId: Handle): LifecycleStatus | undefined {
    const rec = this.recordedEvent(logId);
    if (!rec) return undefined;
    const candidates: { hlc: Hlc; status: LifecycleStatus }[] = [
      { hlc: rec.hlc, status: rec.payload.status },
    ];
    for (const e of this.eventsOf<LogStatusChangedPayload>("log_status_changed")) {
      if (e.payload.targetId === logId) {
        candidates.push({ hlc: e.hlc, status: e.payload.status });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)?.status;
  }

  /** Latest-wins effective time: the recorded time superseded by restatements. */
  effectiveTimeOf(logId: Handle): number | undefined {
    const rec = this.recordedEvent(logId);
    if (!rec) return undefined;
    const candidates: { hlc: Hlc; t: number }[] = [
      { hlc: rec.hlc, t: rec.payload.effectiveTime },
    ];
    for (const e of this.eventsOf<LogTimeRestatedPayload>("log_time_restated")) {
      if (e.payload.targetId === logId) {
        candidates.push({ hlc: e.hlc, t: e.payload.effectiveTime });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)?.t;
  }

  /** Materialized log view, or undefined when unknown or deleted. */
  logView(logId: Handle): LogView | undefined {
    const rec = this.recordedEvent(logId);
    if (!rec || this.isLogDeleted(logId)) return undefined;
    const p = rec.payload;
    return {
      logId: p.logId,
      kind: p.kind,
      name: p.name,
      status: this.logStatus(logId)!,
      assetIds: p.assetIds,
      quantities: p.quantities.filter((q) => !this.isQuantityDeleted(q.quantityId)),
      effectiveTime: this.effectiveTimeOf(logId)!,
      extras: p.extras,
      equipmentIds: p.equipmentIds ?? [],
      hlc: rec.hlc,
    };
  }

  /**
   * Whether `equipmentId` is among the equipment the log states as used
   * (MetaCoding-1cv, the has_parent house form: membership, never a raw id).
   * `undefined` when the log is unknown or deleted — unanswerable, not false.
   */
  equipmentUsed(logId: Handle, equipmentId: Handle): boolean | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    return v.equipmentIds.includes(equipmentId);
  }

  /**
   * The material quantity_presave fold (MetaCoding-5ln), applied at record
   * time exactly as the source's hook applies it at save: a MATERIAL-bundle
   * quantity referencing a MATERIAL asset with a stated material type
   * inherits that type; any guard failing leaves the quantity untouched.
   * A snapshot copy — later asset changes never restate recorded quantities.
   * Feature-local for now; promotion to a kernel denormalize-on-write
   * primitive is the punted kernel_candidate decision.
   */
  private materialFold(q: QuantityInput): Partial<QuantityInput> {
    if ((q.quantityType ?? "") !== "material" || !q.inventoryAssetId) return {};
    const a = this.eventsOf<AssetCreatedPayload>("asset_created").find(
      (e) => e.payload.assetId === q.inventoryAssetId,
    );
    if (!a || a.payload.entity !== "material" || !a.payload.descriptor) return {};
    return { materialTypes: [a.payload.descriptor] };
  }

  /**
   * The ordered material_type names on the log's first MATERIAL-bundle
   * quantity; [] when the log carries none or it records no type.
   * `undefined` when the log is unknown or deleted — unanswerable, not [].
   */
  materialTypeRecorded(logId: Handle): readonly string[] | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    const q = v.quantities.find((x) => (x.quantityType ?? "") === "material");
    return q ? (q.materialTypes ?? []) : [];
  }

  // ---- lab_test bundle-field readbacks (MetaCoding-wgy) --------------------
  //
  // Four boundary transcriptions (sample type, two dates, soil texture) and
  // one laboratory NAME read straight off the log's recorded extras; the sixth
  // (lab_test_measurement) folds the test methods off the log's first
  // quantity--test — the material_type_recorded house form. Each returns the
  // empty value ("" or []) when the log recorded no such field, and `undefined`
  // when the log is unknown or deleted (unanswerable, never the empty value).

  /** lab_test_type recorded on the log; "" when none. */
  labSampleType(logId: Handle): string | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    return v.extras?.labSampleType ?? "";
  }

  /** The recorded laboratory NAME (the log's single-valued `lab`); "" when none. */
  laboratory(logId: Handle): string | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    return v.extras?.laboratory ?? "";
  }

  /** lab_processed_date recorded on the log (verbatim ISO); "" when none. */
  labProcessingDate(logId: Handle): string | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    return v.extras?.labProcessedDate ?? "";
  }

  /** lab_received_date recorded on the log (verbatim ISO); "" when none. */
  sampleReceivedDate(logId: Handle): string | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    return v.extras?.labReceivedDate ?? "";
  }

  /** soil_texture recorded on the log (verbatim string); "" when none. */
  soilTexture(logId: Handle): string | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    return v.extras?.soilTexture ?? "";
  }

  /**
   * The ordered test_method names on the log's FIRST quantity--test; [] when
   * the log carries no test quantity or that quantity records no method (the
   * 'first test quantity' selection is our unambiguity convention, sound while
   * a flow carries at most one test quantity per log — the material_type_recorded
   * 'two firsts' caveat). `undefined` when the log is unknown or deleted.
   */
  labTestMeasurement(logId: Handle): readonly string[] | undefined {
    const v = this.logView(logId);
    if (!v) return undefined;
    const q = v.quantities.find((x) => (x.quantityType ?? "") === "test");
    return q ? (q.testMethods ?? []) : [];
  }

  // ---- plant_type term planning-field readbacks (MetaCoding plant-type) ----
  //
  // The four planning fields the plant_type identity port reads off a plant_type
  // TERM. Each folds off the term's recorded birth event — the MATERIALIZED
  // state, never an echo of a caller-held input object. The day counts deliver
  // the recorded integer verbatim, or "" when the term stated none; crop_family
  // delivers the recorded family NAME or ""; companion_plants delivers the
  // ordered companion NAMES or []. Every readback returns `undefined` when the
  // handle is not a plant_type term (an asset, a log, an unknown handle) — a
  // non-plant_type subject is UNANSWERABLE, never the empty value. maturityDays
  // and harvestDays are separate payload fields, so they cannot bleed into each
  // other: reading one never surfaces the other.

  private plantTypeTerm(termId: Handle): PlantTypeTermCreatedPayload | undefined {
    return this.eventsOf<PlantTypeTermCreatedPayload>("plant_type_term_created").find(
      (e) => e.payload.termId === termId,
    )?.payload;
  }

  /** The plant_type term's recorded maturity_days integer; "" when none. */
  daysToMaturity(termId: Handle): number | string | undefined {
    const t = this.plantTypeTerm(termId);
    if (!t) return undefined;
    return t.maturityDays ?? "";
  }

  /** The plant_type term's recorded harvest_days integer; "" when none. */
  daysToHarvest(termId: Handle): number | string | undefined {
    const t = this.plantTypeTerm(termId);
    if (!t) return undefined;
    return t.harvestDays ?? "";
  }

  /** The NAME of the crop_family the plant_type term references; "" when none. */
  cropFamily(termId: Handle): string | undefined {
    const t = this.plantTypeTerm(termId);
    if (!t) return undefined;
    return t.cropFamily ?? "";
  }

  /** The ordered NAMES of the plant_type term's companions; [] when none. */
  companionPlants(termId: Handle): readonly string[] | undefined {
    const t = this.plantTypeTerm(termId);
    if (!t) return undefined;
    return t.companions ?? [];
  }

  // ---- sensor bundle-field readbacks (MetaCoding-ej0) ----------------------
  //
  // The three bundle fields the sensor identity port reads off a SENSOR asset.
  // Each folds off the sensor's recorded birth event — the MATERIALIZED state,
  // never an echo of a caller-held input. sensor_data_stream delivers the
  // ordered recorded stream NAMES or []; sensor_private_key the recorded key
  // verbatim or ""; publicly_readable the recorded flag (true/false are both
  // stated VALUES) or "" when the sensor stated no flag. Every readback returns
  // `undefined` when the handle is not a sensor asset (a plain asset, a log, a
  // plant_type term, an unknown handle) — a non-sensor subject is UNANSWERABLE,
  // never the empty value.

  private sensorAsset(assetId: Handle): SensorAssetCreatedPayload | undefined {
    return this.eventsOf<SensorAssetCreatedPayload>("sensor_asset_created").find(
      (e) => e.payload.assetId === assetId,
    )?.payload;
  }

  /** The ordered NAMES of the sensor's recorded data streams; [] when none. */
  sensorDataStreams(assetId: Handle): readonly string[] | undefined {
    const s = this.sensorAsset(assetId);
    if (!s) return undefined;
    return s.dataStreams ?? [];
  }

  /** The sensor's recorded private key, verbatim; "" when none stated. */
  sensorPrivateKey(assetId: Handle): string | undefined {
    const s = this.sensorAsset(assetId);
    if (!s) return undefined;
    return s.privateKey ?? "";
  }

  /**
   * The sensor's recorded public flag: true or false when STATED (false is a
   * value, not absence), "" when the sensor stated no flag — the recorded
   * absent-value contrast the pack scores.
   */
  publiclyReadable(assetId: Handle): boolean | string | undefined {
    const s = this.sensorAsset(assetId);
    if (!s) return undefined;
    return s.public ?? "";
  }

  // ---- structure kind readback (MetaCoding-xq7) ----------------------------
  //
  // A structure is a plain ASSET (farmOS asset--structure) born through the
  // pre-existing generic asset_created path with entity "structure" — it needs
  // no dedicated birth event (unlike the sensor, whose three bundle fields
  // motivate one). Its single bundle field is the structure_type machine id,
  // carried as the asset's recorded descriptor. Zero new event kinds, zero new
  // kernel surface.

  /**
   * The structure's kind machine id: the recorded descriptor when stated,
   * "other" when the structure was born without one — the source's default
   * structure_type, a stated FALLBACK VALUE, never an empty string. Wire ""
   * is the unstated shape and falls back too (the bridge normalizes "" off
   * before recording, and the fold guards it here as well so a direct store
   * caller cannot materialize an empty kind). Answers ONLY for an asset born
   * with entity "structure": any other handle — a non-structure asset (even
   * one carrying a descriptor, e.g. a typed material), a sensor, a log, a
   * plant_type term, a ghost — is `undefined`: UNANSWERABLE, never "other"
   * and never "". Archive never touches it: kind folds off the birth event,
   * asset_active off the lifecycle events — independent by construction.
   */
  structureKind(assetId: Handle): string | undefined {
    const a = this.eventsOf<AssetCreatedPayload>("asset_created").find(
      (e) => e.payload.assetId === assetId,
    );
    if (!a || a.payload.entity !== "structure") return undefined;
    return a.payload.descriptor || "other";
  }

  /**
   * Logs referencing an asset, ascending (effectiveTime, HLC) — the source's
   * LogQueryFactory order with the forbidden id tie-break replaced by the
   * kernel HLC (decision w0a-2). Deleted logs excluded; `asOf` (epoch ms)
   * bounds effectiveTime when supplied.
   */
  logsForAsset(
    assetId: Handle,
    opts: { kind?: string; status?: LifecycleStatus; asOf?: number } = {},
  ): LogView[] {
    const views: LogView[] = [];
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      if (!e.payload.assetIds.includes(assetId)) continue;
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (opts.kind !== undefined && v.kind !== opts.kind) continue;
      if (opts.status !== undefined && v.status !== opts.status) continue;
      if (opts.asOf !== undefined && v.effectiveTime > opts.asOf) continue;
      views.push(v);
    }
    views.sort((a, b) =>
      a.effectiveTime !== b.effectiveTime
        ? a.effectiveTime - b.effectiveTime
        : compareHlc(a.hlc, b.hlc),
    );
    return views;
  }

  /** All live (non-deleted) log views, ascending (effectiveTime, HLC). */
  allLogs(opts: { kind?: string } = {}): LogView[] {
    const views: LogView[] = [];
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (opts.kind !== undefined && v.kind !== opts.kind) continue;
      views.push(v);
    }
    views.sort((a, b) =>
      a.effectiveTime !== b.effectiveTime
        ? a.effectiveTime - b.effectiveTime
        : compareHlc(a.hlc, b.hlc),
    );
    return views;
  }

  // ---- kernel-gated numeric folds -----------------------------------------
  //
  // The official numerics are confirmed-only (the ONE chosen divergence from
  // the source, decision pending-status-gates / MetaCoding-tkj); the excluded
  // pending mass is surfaced through the pending-only partners, never blended.
  // Folds sum across domain log kinds (observed: observation 3 + harvest 9 →
  // 12.0) and are NOT as-of-gated (observed: future-dated done log counts now).

  yieldTotal(assetId: Handle, measure: string, unit: string): number {
    return this.yieldUnder("yieldTotal", assetId, measure, unit);
  }

  pendingYieldTotal(assetId: Handle, measure: string, unit: string): number {
    return this.yieldUnder("pendingYieldTotal", assetId, measure, unit);
  }

  private yieldUnder(
    projection: "yieldTotal" | "pendingYieldTotal",
    assetId: Handle,
    measure: string,
    unit: string,
  ): number {
    const gate = gateFor(projection);
    let total = 0;
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      if (!this.registry.isLog(e.kind)) continue; // movements never contribute
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (!v.assetIds.includes(assetId)) continue;
      if (!passesGate(v.status, gate)) continue;
      for (const q of v.quantities) {
        if (q.measure === measure && q.unit === unit) total += q.value;
      }
    }
    return total;
  }

  logCount(assetId: Handle, kind: string): number {
    return this.countUnder("logCount", assetId, kind);
  }

  pendingLogCount(assetId: Handle, kind: string): number {
    return this.countUnder("pendingLogCount", assetId, kind);
  }

  private countUnder(
    projection: "logCount" | "pendingLogCount",
    assetId: Handle,
    kind: string,
  ): number {
    const gate = gateFor(projection);
    let count = 0;
    for (const e of this.eventsOf<LogRecordedPayload>("log_recorded")) {
      const v = this.logView(e.payload.logId);
      if (!v) continue;
      if (v.kind !== kind) continue;
      if (!v.assetIds.includes(assetId)) continue;
      if (!passesGate(v.status, gate)) continue;
      count += 1;
    }
    return count;
  }

  /** Σ of a (measure, unit) pair on ONE log — the log's own recorded values,
   *  never status-gated (it reports what the event says, not a fold over many). */
  quantityRecorded(logId: Handle, measure: string, unit: string): number {
    const v = this.logView(logId);
    if (!v) return 0;
    let total = 0;
    for (const q of v.quantities) {
      if (q.measure === measure && q.unit === unit) total += q.value;
    }
    return total;
  }

  /**
   * Whether SOME birth event minted this asset handle: any event whose
   * registered kind is in the "asset" family and whose payload carries this
   * assetId — asset_created and every feature-local *_asset_created (the
   * sensor form), derived from the registry so a future asset birth kind is
   * covered by construction, not by remembering to edit a list.
   */
  private assetBorn(assetId: Handle): boolean {
    return this.events().some(
      (e) =>
        this.registry.spec(e.kind).family === "asset" &&
        (e.payload as { assetId?: Handle }).assetId === assetId,
    );
  }

  /**
   * MetaCoding-5xa: previously this answered `true` for ANY unarchived
   * handle — including never-created and ghost handles — so the probe could
   * not distinguish "active asset" from "no asset at all" (the trivially
   * satisfiable check the iteration methodology targets). A handle with no
   * birth event is now UNANSWERABLE (undefined), never a value; the bridge
   * maps it to the unanswerable channel like every unknown-subject probe.
   */
  assetActive(assetId: Handle): boolean | undefined {
    if (!this.assetBorn(assetId)) return undefined;
    return !this.eventsOf<AssetArchivedPayload>("asset_archived").some(
      (e) => e.payload.assetId === assetId,
    );
  }

  assetName(assetId: Handle): string | undefined {
    return this.eventsOf<AssetCreatedPayload>("asset_created").find(
      (e) => e.payload.assetId === assetId,
    )?.payload.name;
  }
}
