/**
 * Shared kernel v1 (MetaCoding-9h5.24) — the five frozen elements every fan-out
 * port builder consumes as FIXED input. Zero runtime dependencies; Bun-native.
 *
 *   1. Event envelope + closed kind taxonomy  → events.ts   (resolves is-a-movement-a-log)
 *   2. Client id + hybrid logical clock       → ids.ts, hlc.ts
 *   3. The one latest-wins comparator         → lww.ts
 *   4. Status-semantics contract              → status.ts
 *   5. Binding CM-decision registry           → decisions.ts
 *
 * v1.1 (MetaCoding-9h5.26) extends element 3 into a full FOLD LIBRARY — the
 * wave-0 pilot found latest-wins alone cannot express 3 of 4 fresh-feature folds:
 *
 *   • Ordered reduce (reset assigns, deltas accumulate)  → fold.ts   (FoldReduce)
 *   • Grow-only ordered collection                       → gset.ts   (GSet)
 *   • First-writer-wins + bound-uniqueness demotion      → fww.ts    (GuardedFirstWrite, demoteToObservation)
 *
 * See docs/design/shared-kernel.md for the design + the provisional picks Duke
 * resolves, and eval/ctkr/results/shared-kernel-v1-2026-07-20.md for validation.
 */

export {
  type Hlc,
  compareHlc,
  hlcEqual,
  hlcToString,
  parseHlc,
  HlcClock,
} from "./hlc.ts";

export {
  type EntityId,
  REPLICA_SEP,
  IdMinter,
  isEntityId,
  replicaOf,
} from "./ids.ts";

export { pickLatest, LwwRegister } from "./lww.ts";

export { type FoldReduceSpec, FoldReduce } from "./fold.ts";

export { type GSetEntry, GSet } from "./gset.ts";

export {
  type DemotionResult,
  pickEarliest,
  GuardedFirstWrite,
  demoteToObservation,
} from "./fww.ts";

export {
  type KindSpec,
  type KernelEvent,
  KindRegistry,
  EventLog,
} from "./events.ts";

export {
  type StatusGate,
  type LifecycleStatus,
  type ProjectionName,
  CONFIRMED_STATUS,
  STATUS_CONTRACT,
  PENDING_PARTNER,
  gateFor,
  passesGate,
  admits,
} from "./status.ts";

export {
  type Sensitivity,
  type ResolutionStatus,
  type CmDecision,
  UnboundDecisionError,
  CmDecisionRegistry,
  validateCmDecision,
  loadCmDecisions,
  cmDecisionFromPortDecision,
} from "./decisions.ts";
