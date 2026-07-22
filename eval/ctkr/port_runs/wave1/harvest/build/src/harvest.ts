// w1c — harvest logging port, on the shared wave-1 log-family store.
//
// Contract: wave1/harvest/adapter_contract.md. Harvest is a log (isMovement
// false); seeding/transplanting are movements (isLog:false — the bound
// movement-as-log-taxonomy decision), so movements never inflate logCount or
// yield. Status-sensitive projections go through the frozen STATUS_CONTRACT:
// location require-confirmed; yieldTotal/logCount require-confirmed with
// pending-only partners. Birth resolution is the kernel GuardedFirstWrite /
// demoteToObservation mechanic verbatim (earliest-hlc-wins, loser demoted).
//
// Feature-declared kinds (extension of the shared taxonomy):
//   movement_recorded    — 9h5.24 name reused verbatim
//   planting_plan_created — NEW w1c (punt w1c-2): remembered season defaults
//   birth_recorded        — NEW here; mirrors the w0b birth verb for plants
//   revision_marked       — NEW w1c (punt w1c-4): merge-aware revision markers

import {
  Wave1LogStore,
  type Handle,
  type QuantityInput,
} from "../../../shared-store/src/store.ts";
import {
  compareHlc,
  pickLatest,
  gateFor,
  passesGate,
  demoteToObservation,
  type KindSpec,
  type Hlc,
} from "../../../../../../../src/kernel/index.ts";

export const HARVEST_KINDS: readonly KindSpec[] = [
  { kind: "movement_recorded", family: "movement", isLog: false, statusGate: "require-confirmed", description: "a location movement — NOT a log (9h5.24 name; bound taxonomy decision)" },
  { kind: "planting_plan_created", family: "planning", isLog: false, description: "NEW w1c: planting-plan creation; nonempty seasons update actor defaults" },
  { kind: "birth_recorded", family: "lineage", isLog: false, description: "NEW w1c: birth observation for a plant; earliest-hlc-wins, loser demoted" },
  { kind: "revision_marked", family: "revision", isLog: false, description: "NEW w1c: merge-aware new-revision marker; concurrent markers retained" },
];

export type ActorHandle = Handle;
export type PlantHandle = Handle;
export type SeasonHandle = Handle;
export type CropHandle = Handle;
export type LocationHandle = Handle;
export type MovementHandle = Handle;
export type HarvestLogHandle = Handle;
export type BirthLogHandle = Handle;
export type PlantingPlanHandle = Handle;
export type RecordStatusChangeHandle = Handle;
export type RevisionHandle = Handle;

export interface LabeledRef {
  id: Handle;
  label: string;
}

export interface MovementLegInput {
  location: LocationHandle;
  occurredAt: number;
  done?: boolean;
}

export interface PlantingInput {
  customName?: string;
  customNameEnabled?: boolean;
  seasons: readonly LabeledRef[];
  crops: readonly LabeledRef[];
  seeding?: MovementLegInput;
  transplanting?: MovementLegInput;
}

interface MovementRecordedPayload {
  movementId: Handle;
  movementKind: "seeding" | "transplanting";
  assetIds: readonly Handle[];
  locationIds: readonly Handle[];
  status: string;
  effectiveTime: number;
}

interface PlantingPlanCreatedPayload {
  planId: Handle;
  actor: ActorHandle;
  seasons: readonly LabeledRef[];
  crops: readonly LabeledRef[];
}

interface BirthRecordedPayload {
  birthId: Handle;
  plantId: PlantHandle;
  occurredAt: number;
  demoted?: boolean;
}

interface RevisionMarkedPayload {
  revisionId: Handle;
  targetId: Handle;
}

export interface HarvestLogView {
  harvest: HarvestLogHandle;
  status: string;
  isMovement: false;
  lotNumber: string | null;
  /** exactly as recorded, including [null] for an absent quantity (contract). */
  quantityPayload: readonly (QuantityInput | null)[];
  occurredAt: number;
}

export function makeHarvestLoggingAdapter(
  store: Wave1LogStore = new Wave1LogStore({ extraKinds: HARVEST_KINDS }),
) {
  // plant metadata is carried on asset_created via name/descriptor; the naming
  // inputs live here keyed by plant so the projection can re-derive the name.
  const plantNaming = new Map<PlantHandle, PlantingInput>();

  function movementEvents(plant: PlantHandle) {
    return store
      .eventsOf<MovementRecordedPayload>("movement_recorded")
      .filter((e) => e.payload.assetIds.includes(plant));
  }

  function movementStatus(movementId: Handle, recorded: string): string {
    const candidates: { hlc: Hlc; status: string }[] = [];
    const rec = store
      .eventsOf<MovementRecordedPayload>("movement_recorded")
      .find((e) => e.payload.movementId === movementId);
    if (rec) candidates.push({ hlc: rec.hlc, status: recorded });
    for (const e of store.eventsOf<{ targetId: Handle; status: string }>("log_status_changed")) {
      if (e.payload.targetId === movementId) {
        candidates.push({ hlc: e.hlc, status: e.payload.status });
      }
    }
    return pickLatest(candidates, (c) => c.hlc)?.status ?? recorded;
  }

  const adapter = {
    store,

    recordPlanting(
      _actor: ActorHandle,
      planting: PlantingInput,
    ): { plant: PlantHandle; movements: MovementHandle[] } {
      const plant = store.createAsset({ entity: "plant", name: "" });
      plantNaming.set(plant, planting);
      const movements: MovementHandle[] = [];
      const legs: Array<["seeding" | "transplanting", MovementLegInput | undefined]> = [
        ["seeding", planting.seeding],
        ["transplanting", planting.transplanting],
      ];
      for (const [movementKind, leg] of legs) {
        if (!leg) continue;
        const movementId = store.mint("mvt");
        store.emit<MovementRecordedPayload>("movement_recorded", {
          movementId,
          movementKind,
          assetIds: [plant],
          locationIds: [leg.location],
          status: leg.done ? "done" : "pending",
          effectiveTime: leg.occurredAt,
        });
        movements.push(movementId);
      }
      return { plant, movements };
    },

    createPlantingPlan(
      actor: ActorHandle,
      seasons: readonly LabeledRef[],
      crops: readonly LabeledRef[],
    ): PlantingPlanHandle {
      const planId = store.mint("plan");
      store.emit<PlantingPlanCreatedPayload>("planting_plan_created", {
        planId,
        actor,
        seasons: [...seasons],
        crops: [...crops],
      });
      return planId;
    },

    recordHarvest(
      _actor: ActorHandle,
      plant: PlantHandle,
      occurredAt: number,
      quantity: QuantityInput | null,
      lotNumber: string | null,
      status: "pending" | "done",
    ): HarvestLogHandle {
      // null/empty quantity is persisted as quantityPayload [null], never as a
      // zero or an omitted wrapper (contract w1c).
      return store.recordLog({
        kind: "harvest",
        name: "",
        status,
        assetIds: [plant],
        quantities: quantity === null ? [] : [quantity],
        effectiveTime: occurredAt,
        extras: {
          lotNumber: lotNumber ?? undefined,
          quantityPayload: quantity === null ? [null] : [quantity],
        },
      });
    },

    confirmRecord(_actor: ActorHandle, record: Handle): RecordStatusChangeHandle {
      const change = store.emit<{ targetId: Handle; status: string }>(
        "log_status_changed",
        { targetId: record, status: "done" },
      );
      return change.id;
    },

    recordBirth(_actor: ActorHandle, plant: PlantHandle, occurredAt: number): BirthLogHandle {
      const birthId = store.mint("birth");
      store.emit<BirthRecordedPayload>("birth_recorded", { birthId, plantId: plant, occurredAt });
      return birthId;
    },

    markNewRevision(record: Handle): RevisionHandle {
      const revisionId = store.mint("rev");
      store.emit<RevisionMarkedPayload>("revision_marked", { revisionId, targetId: record });
      return revisionId;
    },

    getPlantDisplayName(_actor: ActorHandle, plant: PlantHandle, _asOf: number): string | undefined {
      const p = plantNaming.get(plant);
      if (!p) return undefined;
      if (p.customNameEnabled && p.customName && p.customName.length > 0) {
        return p.customName;
      }
      // generated: season labels joined '/', crop labels ', ' (contract);
      // location preference transplant-over-seeding informs the located name.
      const seasons = p.seasons.map((s) => s.label).join("/");
      const crops = p.crops.map((c) => c.label).join(", ");
      return [seasons, crops].filter((s) => s.length > 0).join(" ");
    },

    getRememberedSeasonDefaults(actor: ActorHandle, asOf: number): SeasonHandle[] {
      // latest NONEMPTY seasons selection by this actor; an empty selection
      // never clears the prior default (contract).
      const candidates = store
        .eventsOf<PlantingPlanCreatedPayload>("planting_plan_created")
        .filter(
          (e) =>
            e.payload.actor === actor &&
            e.payload.seasons.length > 0 &&
            e.hlc.physical <= asOf,
        );
      const latest = pickLatest(candidates, (e) => e.hlc);
      return latest ? latest.payload.seasons.map((s) => s.id) : [];
    },

    getHarvestLog(_actor: ActorHandle, harvest: HarvestLogHandle, asOf: number): HarvestLogView | undefined {
      const v = store.logView(harvest);
      if (!v || v.kind !== "harvest" || v.effectiveTime > asOf) return undefined;
      return {
        harvest: v.logId,
        status: v.status,
        isMovement: false,
        lotNumber: v.extras?.lotNumber ?? null,
        quantityPayload: v.extras?.quantityPayload ?? [null],
        occurredAt: v.effectiveTime,
      };
    },

    getPlantLocation(_actor: ActorHandle, plant: PlantHandle, asOf: number): LocationHandle | undefined {
      // latest CONFIRMED movement at or before asOf; pending movements are
      // inert to current location (STATUS_CONTRACT.currentLocation).
      const gate = gateFor("currentLocation");
      let best: { hlc: Hlc; t: number; loc: LocationHandle } | undefined;
      for (const e of movementEvents(plant)) {
        if (e.payload.effectiveTime > asOf) continue;
        if (!passesGate(movementStatus(e.payload.movementId, e.payload.status), gate)) continue;
        const cand = { hlc: e.hlc, t: e.payload.effectiveTime, loc: e.payload.locationIds[0]! };
        if (
          best === undefined ||
          cand.t > best.t ||
          (cand.t === best.t && compareHlc(cand.hlc, best.hlc) > 0)
        ) {
          best = cand;
        }
      }
      return best?.loc;
    },

    getHarvestTotals(
      _actor: ActorHandle,
      plant: PlantHandle,
      _asOf: number,
    ): { yieldTotal: QuantityInput | null; logCount: number; pendingYieldTotal: QuantityInput | null; pendingLogCount: number } {
      // confirmed-only officials + the REQUIRED pending-only partners
      // (PENDING_PARTNER pairing); movements never contribute (isLog:false).
      const first = store
        .allLogs({ kind: "harvest" })
        .find((v) => v.assetIds.includes(plant) && v.quantities.length > 0);
      const pair = first
        ? { measure: first.quantities[0]!.measure, unit: first.quantities[0]!.unit }
        : undefined;
      const total = pair ? store.yieldTotal(plant, pair.measure, pair.unit) : 0;
      const pending = pair ? store.pendingYieldTotal(plant, pair.measure, pair.unit) : 0;
      return {
        yieldTotal: pair && total !== 0 ? { measure: pair.measure, unit: pair.unit, value: total } : null,
        logCount: store.logCount(plant, "harvest"),
        pendingYieldTotal:
          pair && pending !== 0 ? { measure: pair.measure, unit: pair.unit, value: pending } : null,
        pendingLogCount: store.pendingLogCount(plant, "harvest"),
      };
    },

    getBirthResolution(
      _actor: ActorHandle,
      plant: PlantHandle,
      asOf: number,
    ): { canonicalBirth: BirthLogHandle | undefined; demotedObservations: BirthLogHandle[] } {
      const births = store
        .eventsOf<BirthRecordedPayload>("birth_recorded")
        .filter((e) => e.payload.plantId === plant && e.hlc.physical <= asOf);
      const result = demoteToObservation(
        births,
        (e) => e.hlc,
        (loser) => ({ ...loser, payload: { ...loser.payload, demoted: true } }),
      );
      if (!result) return { canonicalBirth: undefined, demotedObservations: [] };
      return {
        canonicalBirth: result.kept.payload.birthId,
        demotedObservations: result.demoted.map((e) => e.payload.birthId),
      };
    },

    getRevisionState(
      _actor: ActorHandle,
      record: Handle,
      asOf: number,
    ): { currentRevision: RevisionHandle | undefined; revisionHistory: RevisionHandle[] } | undefined {
      const markers = store
        .eventsOf<RevisionMarkedPayload>("revision_marked")
        .filter((e) => e.payload.targetId === record && e.hlc.physical <= asOf);
      if (markers.length === 0) return undefined;
      // merge-aware: ALL markers retained, ordered by the kernel HLC; the
      // current projected marker is the latest (concurrents never excluded).
      const ordered = [...markers].sort((a, b) => compareHlc(a.hlc, b.hlc));
      return {
        currentRevision: pickLatest(markers, (e) => e.hlc)?.payload.revisionId,
        revisionHistory: ordered.map((e) => e.payload.revisionId),
      };
    },
  };
  return adapter;
}
