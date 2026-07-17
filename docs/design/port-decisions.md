# Port Decisions log

**Cross-cutting machinery #2** from [`port-loop-plan.md`](./port-loop-plan.md): every conscious
divergence from a source system's extracted spec is an ADR-style record naming the superseded
source intention and why; the port-verifier treats waived elements as expected deltas, not
failures. Disciplined divergence vs drift, made auditable.

---

## Why

The port-verifier (`verifyPort.ts`) checks structural shape against the extracted spec. A port
that *deliberately* reshapes a role, relaxes a contract, or replaces a composition law will
always produce punch-list failures for those elements — correct detection, wrong conclusion. The
decisions log separates "we knew and decided" from "we missed it":

- **Without waivers**: every deliberate divergence looks like a bug. Teams accumulate CI noise
  and start ignoring the verifier.
- **With waivers**: raw gate scores stay honest; net-of-waivers scores show the true picture;
  stale-waiver detection ensures the log stays current as the spec evolves.

Waivers **never weaken a check**. The raw score is computed first, unchanged. A waiver only
reclassifies a reported failure from "failure" to "waived" in the punch list and lifts the net
gate's `passed` flag. It cannot push a gate to `passedAtCeiling`.

---

## Record format

One JSONL file per subsystem at:

```
port_decisions/<subsystem_id>.jsonl
```

relative to the data directory. Subsystem ids may contain `::` or `/`; the file-name helper
`portDecisionsPath()` replaces unsafe characters with `__`. A missing file is silently treated
as an empty decisions list.

Each line is one JSON object (a `PortDecision`):

| Field | Type | Required | Description |
|---|---|---|---|
| `id` | string | yes | Stable unique id for this decision (e.g. `"PD-001"`, `"PD-auth-role-split"`). |
| `date` | string | yes | ISO-8601 date recorded (`"YYYY-MM-DD"`). |
| `subsystem` | string | yes | Matches `SubsystemSpec.subsystemId`; records for other subsystems are ignored by the verifier. |
| `targetElement` | string | yes | The punch-list `cardSection` address this decision waives (exact string match). |
| `decision` | `"supersede" \| "weaken" \| "preserve-with-note"` | yes | What the decision does to the source intention (see §Decision kinds). |
| `supersededSourceIntention` | string | yes | Free text describing the source intention being modified; cited in reports. |
| `intentionSignalRefs` | string[] | no | Optional row refs into `intention_signals.parquet` backing the source intention claim. |
| `rationale` | string | yes | Why this divergence is deliberate and acceptable. |
| `author` | string | yes | Who recorded this decision (name or email). |

### `targetElement` addressing

Uses the same scheme as `PunchListItem.cardSection` — matched by exact string equality:

```
roles[role_id=<id>]
interface.provides[symbol=<qualified_name_or_id>]
composition_rules[operation_id=<id>]
functor.fidelity
functor.cycle_consistency
```

### Decision kinds

| Value | Meaning |
|---|---|
| `supersede` | The source intention is intentionally not preserved; the port replaces it with different behavior or design. |
| `weaken` | The source intention is partially relaxed (e.g. eventual vs. strong consistency, optional vs. required). |
| `preserve-with-note` | The intention is preserved but implemented differently; the structural diff is expected and correct. |

### Example record

```json
{
  "id": "PD-logs-001",
  "date": "2026-07-17",
  "subsystem": "ss:farmOS::logs",
  "targetElement": "composition_rules[operation_id=op3]",
  "decision": "supersede",
  "supersededSourceIntention": "Log entries are committed inside a Drupal ACID transaction that holds a row lock on the asset record for the duration of the write.",
  "intentionSignalRefs": ["sig:farmOS::farm_log/src/Entity/Log.php:142"],
  "rationale": "The local-first port uses an append-only event log with optimistic merge; transactional row-locking is replaced by conflict detection at sync time. This is a deliberate consistency-model shift (intent-CM tagged), not an oversight.",
  "author": "duke@worldtree.io"
}
```

---

## Verifier integration

Pass `decisions` to `verifyPort()`:

```typescript
import { loadPortDecisions, portDecisionsPath } from "./portDecisions.ts";
import { verifyPort } from "./verifyPort.ts";

const decisions = loadPortDecisions(
  portDecisionsPath(dataDir, spec.subsystemId),
);
const report = verifyPort({ spec, source, port, decisions });
```

The report gains three new fields when decisions are supplied:

| Field | Description |
|---|---|
| `gatesNet` | Gate results net of waivers. `passed` is lifted to `true` when every punch-list item for that gate is waived. `passedAtCeiling` is never lifted. |
| `waivedCount` | Number of punch-list items matched by a decision. |
| `staleWaivers` | Decision records whose `targetElement` matched no punch-list item. Surfaced as a warning — waivers must never silently rot. |

`punchList` items gain `waivedBy?: string` (the decision id) when matched.
`gates` (raw) is always computed first and is never modified by decisions.

### Stale waivers

A decision is stale when its `targetElement` matches no item in the current punch list. This
happens when the port is fixed (the failure no longer occurs) or when the spec changes and the
address no longer exists. Stale waivers appear in `report.staleWaivers` and in `formatReport`
output. They are not errors — they are prompts to review and retire the decision record.

---

## TypeScript API

```typescript
// src/ctkr/portDecisions.ts
export type DecisionKind = "supersede" | "weaken" | "preserve-with-note";
export interface PortDecision { id, date, subsystem, targetElement, decision,
  supersededSourceIntention, intentionSignalRefs?, rationale, author }

export function validatePortDecision(raw: unknown, lineHint?: string): PortDecision
export function loadPortDecisions(path: string): PortDecision[]   // [] if file absent
export function portDecisionsPath(dataDir: string, subsystemId: string): string
```

---

## File placement decision

**Per-subsystem files** (`port_decisions/<subsystem_id>.jsonl`) rather than a single global
file, because:

1. Subsystem scoping mirrors the existing artifact conventions (cards, members, interfaces are
   all per-subsystem).
2. The verifier already operates per-subsystem; it only loads the file for the subsystem it is
   verifying — no cross-subsystem scan needed.
3. A single global file becomes a merge-conflict hot-spot when multiple ports are in-flight
   simultaneously.

The `portDecisionsPath()` helper encodes the subsystem id to a safe filename and is the
single source of truth for the naming convention.
