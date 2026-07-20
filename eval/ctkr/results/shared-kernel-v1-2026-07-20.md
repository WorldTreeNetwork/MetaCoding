# Shared kernel v1 — built + validated (MetaCoding-9h5.24)

> Bead MetaCoding-9h5.24 · 2026-07-20 · the kernel-first prerequisite from
> MetaCoding-9h5.16 (Duke-approved 2026-07-20). Implements the five frozen kernel
> elements prescribed in `two-feature-composition-2026-07-20.md` §5 as a real TS
> package, re-expresses the 9h5.16 composed store ON it, and re-runs the committed
> judges + adds prevention tests that make the observed failure modes structurally
> impossible.

## Bottom line

- **The kernel is real and the composed store runs on it with no value
  regression.** `src/kernel/` (Bun, zero runtime deps) provides the five elements;
  the 9h5.16 composed store, re-expressed on those primitives with **byte-for-byte
  identical adapter surfaces**, scores **17/17 logs + 10/10 location + 5/5
  cross-probes (27 fixtures + 5 probes)** on the *verbatim committed judges*.
- **The four observed failure modes are now prevented by construction, not just
  documented.** Five prevention tests demonstrate: an ad-hoc event kind is rejected
  by the log; the store mints only replica-scoped ids (two replicas' first assets
  don't collide, unlike `asset_1`); an unresolved CM decision throws at store
  construction; and group membership can only be latest-wins via the comparator
  (additive membership is unreachable).
- **All five picks are PROVISIONAL** — implemented with recommended options, each
  bound to a named menu choice + convergence key, awaiting Duke's resolution. The
  elicitation (question / options / recommendation / rationale for all five + the
  three sub-decisions) is in `docs/design/shared-kernel.md`.

## The five provisional picks (Duke reads these)

1. **Event kind taxonomy** — closed `KindRegistry`; **a movement is a distinct
   kind with `isLog:false`** (never counts in `logCount`/`yield`). Resolves CP2's
   latent conflict; matches the composed build. *Alternative: model it as a farmOS
   `activity` log — the only pick that would change a committed judge if flipped.*
2. **ID scheme** — **replica-scoped client id `prefix_replicaId~counter`**;
   collision-free by construction without RNG, no bare ordinal mintable. Kills the
   `asset_7` regression. *Alternative: uuid-v7 (opaque, needs RNG).*
3. **HLC** — `(physical, logical, replicaId)` with a total-order `compareHlc`;
   `tick`/`receive`. Replaces the `(timestamp, seq)` placeholder all seven builds
   punted on. Serial ordinals are structurally unavailable for ordering.
4. **One latest-wins comparator** — `pickLatest`/`LwwRegister` keyed on the HLC,
   the only legal latest-wins fold. Makes additive membership (the ce015be4 bug)
   unreachable.
5. **Status contract** — declared table: `yield`/`logCount` `count-regardless`
   (pending logs count), `currentLocation` `require-confirmed` (pending movements
   inert). Freezes the two opposite readings of one status field.
   **SUPERSEDED in kernel v1.2 (Duke, 2026-07-20, MetaCoding-tkj):** the official
   numerics are now `require-confirmed` and the pending mass moved to partner
   projections (`pendingYieldTotal`/`pendingLogCount`, gate `pending-only`) — a
   deliberate divergence from observed farmOS. See docs/design/shared-kernel.md
   §Element 4. This document records v1 as built.

Plus the **binding CM-decision registry** (element 5): `requireBound` throws on an
unresolved decision or a hard invariant with no named convergence key. The
birth-uniqueness convergence mechanic is bound to **earliest-HLC-wins, loser
demoted to observation** (recommended over 0p7's weaken-to-eventual and the
min-UUID/min-seq variants).

## Validation results

| suite | result | via |
|---|---|---|
| logs+quantities pack (9h5.8 hardened, 17) | **17/17** | verbatim `runFixturesLogs.ts` → `.logs` |
| location+movement pack (9h5.11, 10) | **10/10** | verbatim `runFixturesLocation.ts` → `.location` |
| judge-authored cross-probes (5) | **5/5** | verbatim `crossProbes.ts` on one composed store |
| **composed total** | **27 fixtures + 5 probes** | one kernel-backed `createComposedStore()` |
| kernel unit tests | **27 pass** | `bun test src/kernel` (6 files) |
| prevention tests | **5 pass** | `bun test .../kernel-9h5.24/build/test` |

`bun test` grand total across the kernel + prevention suites: **32 pass / 0 fail /
75 expect() calls**. Typecheck: **0 `tsc` errors** across all authored files
(`src/kernel/**`, `kernel-9h5.24/build/src/**`, `kernel-9h5.24/build/test/**`).

### Prevention tests — the failure modes, closed

| # | prevention | closes (from §4/§5) |
|---|---|---|
| 1 | `EventLog.append` rejects an unregistered kind (`activity_log`); a frozen registry refuses re-opening | CP2 movement-as-log latent conflict |
| 2 | Two replicas' first assets don't collide; id carries a `~` replica scope, not an `asset_\d+` ordinal; no `nextOrdinal` API | the ID-scheme regression |
| 3 | Constructing a store with an unresolved (or convergence-key-less hard) CM decision throws `UnboundDecisionError` | the birth-uniqueness 3-way split |
| 4 | After assign→G1 then assign→G2, `groupMember(G1)==false` — additive membership is unreachable | the membership divergence (ce015be4) |

(A fifth test asserts `cm-decisions.jsonl` mirrors the embedded `BOUND_CM_DECISIONS`.)

## How the re-expression maps onto the kernel

The store keeps the same observable behavior as 9h5.16 but sources every kernel
concern from the frozen primitives (`kernel-9h5.24/build/src/store.ts`):

- the single log is a kernel `EventLog` gated by the frozen `KindRegistry`;
- handles come from `IdMinter` (no bare ordinals); ordering is `HlcClock.tick()`
  (no serial `seq`);
- `groupMember`, `logStatus`, `movementStatus`, fixed-asset geometry all fold via
  the kernel `pickLatest`;
- `yield`/`logCount`/`currentLocation` gate through `passesGate(status, gateFor(...))`;
- the constructor calls `CmDecisionRegistry.requireAllBound(REQUIRED_DECISIONS)`.

**One clean improvement over the composed build:** movements now carry a separate
`effectiveTime` (valid-time) payload field distinct from the HLC (record-time),
where the composed build overloaded a single `timestamp` for both. The as-of query
filters on `effectiveTime`; same-`effectiveTime` ties break on the HLC. This
resolves a latent quirk in the composed build (a `setLogStatus` on a movement
could not win against the movement's own `timestamp`), untested by any fixture but
now correct by construction.

## Honesty notes

- **Teaching-to-the-test, unchanged from the 9h5 line.** The latest-wins/tie-break
  fixtures the re-expression passes were in the packs the 9h5.16 builder saw. The
  genuine new signal here is (a) the same 27/27 + 5/5 on a store whose kernel
  concerns are now frozen primitives, and (b) the prevention tests that make the
  divergences structurally impossible.
- **No birth fixture exists**, so the birth-uniqueness convergence rule is
  *declared and enforced-as-bound at construction* but not behaviorally exercised.
  The store treats a `birth` log as an ordinary log for folding, as the composed
  build did; the kernel only guarantees the decision is bound before the store is
  usable.
- **`n=1` re-expression, one author.** This is the shared-kernel artifact itself,
  not a blind-builder trial. Whether independent wave-1 builders *stay* coherent
  when handed this kernel is the next experiment (the kernel is the fixed input
  that experiment would hold constant).
- **Judges are verbatim.** `judge/*.ts` and `build/inputs/*.jsonl` are byte-for-byte
  copies of the 9h5.16 committed judges/packs; only the `build/src` behind
  `createComposedStore()` changed. Under strict `tsc` the verbatim judges carry the
  same 26 pre-existing `X | Promise<X>` errors the 9h5.16 judges do (they are RUN
  with `bun`, not typechecked) — parity confirmed (26 == 26). All *authored* files
  typecheck clean.

## Artifacts & paths (ALL in-repo, this worktree — no data-dir produced)

- **The kernel package (production):** `src/kernel/` —
  `hlc.ts`, `ids.ts`, `lww.ts`, `events.ts`, `status.ts`, `decisions.ts`,
  `index.ts` + six `*.test.ts`. This is the reusable artifact wave-1 builders
  import.
- **Validation re-expression (eval sandbox):**
  `eval/ctkr/port_runs/kernel-9h5.24/` —
  `build/src/*` (store re-expressed on the kernel; adapter surfaces identical),
  `build/cm-decisions.jsonl` (the binding registry, provisional picks),
  `build/test/prevention.test.ts`, `judge/*` (verbatim committed judges),
  `build/inputs/*.jsonl` (verbatim packs).
- **Docs:** `docs/design/shared-kernel.md` (design + elicitation for Duke),
  `eval/ctkr/results/shared-kernel-v1-2026-07-20.md` (this report).
- **No `.metacoding/` data-dir was created or mutated.** No graph store, parquet,
  or index artifact was produced — this task is LM-free code + docs.
- **Live oracle (farmOS Docker): NOT used.** No new observations; no `m*-` entities
  created.

Worktree branch: `worktree-agent-a69c18cfa1bcc3414`. No push/merge; bead
MetaCoding-9h5.24 left open.

## Spend

LM-free (no model calls in the build or judging). Well under the $2 cap.
