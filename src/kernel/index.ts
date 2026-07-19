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
