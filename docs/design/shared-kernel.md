# Shared kernel v1 — the five frozen elements (MetaCoding-9h5.24)

> Status: **v1, all five picks PROVISIONAL** — implemented with the kernel
> author's recommended options and validated (27 fixtures + 5 cross-probes +
> prevention tests all green), awaiting Duke's resolution. Each decision below is
> an elicitation entry: the question, the options with tradeoffs, the
> recommendation, and its rationale.
>
> Package: `src/kernel/` (Bun, zero runtime deps). Consumed as **fixed input** by
> every wave-1 fan-out port builder. Validation re-expression:
> `eval/ctkr/port_runs/kernel-9h5.24/`.

## Why this exists

The two-feature composition run (`eval/ctkr/results/two-feature-composition-2026-07-20.md`)
proved that per-feature ports **compose when one builder owns the overlap**
(27/27 + 5/5) but **diverge across independent blind builders**: identical inputs
produced value-incompatible architectures on four of five shared axes, and the
composed build itself regressed the ID scheme to a collision-prone ordinal. §5 of
that report prescribed five kernel elements that must be frozen before the
147-feature fan-out. This package is those five elements as real code, each
justified by a specific observed divergence (not a hypothetical).

The kernel does not just *document* the picks — it makes the failure modes
**structurally impossible**: an ad-hoc event kind is rejected by the log, a bare
ordinal id cannot be minted, an unresolved CM decision throws at store
construction, and membership can only be folded latest-wins through the one
comparator. See `build/test/prevention.test.ts`.

---

## The five elements + provisional picks (one-line summary)

| # | Element | Provisional pick | Kills |
|---|---|---|---|
| 1 | Event envelope + closed kind taxonomy | closed registry; **a movement is a distinct kind, `isLog:false`** | CP2's latent movement-as-log conflict |
| 2 | Client id + HLC | **replica-scoped id `prefix_replicaId~counter`** + `(physical,logical,replicaId)` HLC | the `asset_7` ordinal regression + the 7/7 HLC punt |
| 3 | One latest-wins comparator | `pickLatest`/`LwwRegister` keyed on the HLC — the only legal fold | additive membership (ce015be4 fails) |
| 4 | Status-semantics contract | declared table: yield/logCount `count-regardless`, location `require-confirmed` | cell4 gating yield on `done` |
| 5 | Binding CM-decision registry | `requireBound` throws on unresolved/unnamed-convergence | the birth-uniqueness 3-way split |

---

## Element 1 — Event envelope + closed kind taxonomy

**Question.** What is an event, and who may introduce a new event kind?

**Envelope (frozen).** Every event is `{ id, hlc, kind, payload }` (`events.ts`,
`KernelEvent`): a client id, an HLC (the sole ordering key), a **registered**
kind, and a typed payload. The append-only `EventLog` rejects any event whose
kind is not in the `KindRegistry`; the registry is `freeze()`d at build time, so
a feature may extend the taxonomy only through an explicit `register` call before
freeze — never an ad-hoc string at an append site.

### Sub-decision 1a — is a movement a log? (surfaced by CP2)

- **Question.** Does `movement_recorded` count as a domain "log" — i.e. does it
  appear in `logCount(asset, kind)`?
- **Options.**
  - **(A) Distinct kind, `isLog:false`** *(recommended)*. A movement is its own
    kind; `logCount`/`yield` fold only `family:"log"`, so a movement never
    inflates them. Matches the composed build; keeps the numeric folds clean.
    Tradeoff: diverges from farmOS, which models movements as `activity` logs
    with `is_movement`.
  - **(B) Movement IS an `activity` log, `isLog:true`** (farmOS-faithful). A
    movement contributes to `logCount(asset,'activity')`. Tradeoff: would change
    cross-probe CP2 (`logCount('activity')` becomes 1, not 0) and mixes a
    location payload into the log-kind vocabulary.
- **Recommendation: (A).** It keeps the two features' aggregates isolated and
  matches every committed judge as-is. If Duke wants farmOS fidelity, flip the
  `isLog` facet on `movement_recorded` in `kernelConfig.ts` and update CP2 — the
  taxonomy is the single place that decision lives now, not per feature.
- **Status: PROVISIONAL.**

---

## Element 2 — Client id + hybrid logical clock

### Sub-decision 2a — ID scheme (the composed build's regression)

- **Question.** How are entity ids minted so they are collision-free across
  offline replicas?
- **Options.**
  - **(A) Replica-scoped counter `prefix_replicaId~counter`** *(recommended)*.
    Collision-free **by construction** (two replicas mint `asset_A~1` /
    `asset_B~1`, never the same string), no RNG, deterministic for tests. The
    counter is never exposed as a comparable number. Tradeoff: ids leak a
    replica label (fine — provenance, not ordering).
  - **(B) uuid-v7**. Opaque, globally unique, time-sortable. Tradeoff: needs a
    RNG source, and its time-sortability invites the anti-pattern of ordering by
    id instead of by the HLC.
  - **(C) bare integer counter `asset_7`** — the composed build's choice. **Reject:**
    two replicas both mint `asset_1` and collide on merge (the exact
    `autoincrement-id` anti-pattern the target profile warns against).
- **Recommendation: (A).** `IdMinter(replicaId)` (`ids.ts`) requires a non-empty
  replicaId and folds it into every id; there is no method that returns a bare
  ordinal. `EntityId` is a branded type, so a plain number can't be used where an
  id is required.
- **Status: PROVISIONAL.**

### Sub-decision 2b — the HLC (the 7/7 unanimous punt)

- **Question.** What is the cross-replica ordering key that replaces the
  `(timestamp, insertion-seq)` placeholder all seven builds flagged as unsafe?
- **Pick (recommended).** A hybrid logical clock `(physical, logical, replicaId)`
  with a **total order** via `compareHlc` (`hlc.ts`). `logical` breaks ties
  within one `physical` reading; `replicaId` is the final deterministic tie-break
  that makes the order total across replicas. `HlcClock.tick()` stamps local
  events (strictly monotonic even at a frozen wall clock); `receive()` merges a
  remote HLC so causality survives sync. There is deliberately **no** exported
  "next ordinal" — a serial number usable for identity or cross-replica ordering
  is structurally unavailable.
- **Note.** Movements also carry a domain `effectiveTime` (valid-time) payload
  field, distinct from the HLC (record/causal time). The as-of query filters on
  `effectiveTime`; latest-wins ties among same-`effectiveTime` movements break on
  the HLC. This cleanly separates the two axes the composed build conflated into
  one `timestamp`.
- **Status: PROVISIONAL.**

---

## Element 3 — One latest-wins comparator

**Question.** How is any latest-wins projection folded?

**Pick (recommended).** `pickLatest(items, hlcOf)` and `LwwRegister<V>`
(`lww.ts`), both keyed on `compareHlc`. This is the **only** sanctioned way to
fold a latest-wins projection — group membership, current-location tie-break,
log/movement status, and geometry all go through it. Because the fold is a single
register (not a growing set), a feature author cannot re-derive membership
additively (the 0p7/cell-a bug that failed ce015be4) without bypassing the kernel
entirely. Order-independence of `pickLatest` (guaranteed by the total HLC order)
is the convergence property: replay in any order, same winner.

**Status: PROVISIONAL.**

---

## Element 4 — Status-semantics contract

**Question.** `status` (pending | done) is one shared field — which projections
gate on it, and how?

**Pick (recommended).** A declared table, `STATUS_CONTRACT` (`status.ts`), maps
each projection to a `StatusGate`. Projections route their filtering through
`passesGate(status, gateFor(projection))`, so the table — not a local `if` —
decides:

| projection | gate | meaning |
|---|---|---|
| `yieldTotal`, `logCount`, `logStatus` | `count-regardless` | **pending logs count** (a pending harvest was still recorded) |
| `currentLocation`, `assetsAtLocation`, `currentGeometry` | `require-confirmed` | **pending movements are inert** (a proposed move isn't physically true) |

Both required readings are thereby expressible and enforced by construction.
Freezing the table stops a fan-out author re-litigating it (cell4 gated yield on
`done` and failed 73ed7c69/d8607818). Adding a status-bearing projection means
adding a reviewed row here, not re-deciding ad hoc.

**Status: PROVISIONAL.**

---

## Element 5 — Binding CM-decision registry

**Question.** The target profile offers a *menu* of legal options per invariant;
blind builders pick different ones from identical inputs. How is a single choice
made binding across the fan-out?

**Pick (recommended).** `CmDecisionRegistry` (`decisions.ts`) binds each invariant
to one `menuChoice` plus, for a hard invariant, a **named `convergenceKey`** (which
write wins, what happens to the loser). A build declares the invariants it depends
on and calls `requireAllBound(...)` at store construction; the call **throws
loudly** if any is unresolved, missing, or (for a hard invariant) names no
convergence key. A `provisional` decision with a convergence key passes — it is a
real, buildable binding awaiting only Duke's sign-off. This is a typed reader over
the ctkr port-decisions machinery (`src/ctkr/portDecisions.ts`);
`cmDecisionFromPortDecision` adapts the PD JSONL format and surfaces the missing
convergence key a bare PD lacks.

### Sub-decision 5a — birth-uniqueness convergence mechanic (R1's headline; 3-way split)

- **Question.** "At most one birth log per asset" is a hard invariant, but this
  target has no coordination layer. Preserve or weaken, and by what rule?
- **Options.**
  - **(A) preserve-via-convergence-rule: earliest-HLC wins, loser demoted** *(recommended)*.
    Two replicas can each record a birth offline; on merge the earliest by HLC
    survives and any later concurrent birth is **demoted to an observation**
    (never silently dropped). Keeps the invariant hard without a central gate.
  - **(B) weaken-to-eventual** (0p7's choice). Accept a transient two-births
    state reconciled on sync. Tradeoff: a synced replica can briefly show two
    births for one animal — a materially wrong farm record.
  - **(C) preserve-via-min-UUID / min-seq** (cell-a/cell-b variants). Same family
    as (A) but keyed on the id rather than the HLC. Tradeoff: re-introduces
    id-ordering, which element 2 forbids.
- **Recommendation: (A)** — it reuses the same HLC machinery every other
  latest-wins fold already uses, rather than inventing a birth-only mechanism.
- **Status: PROVISIONAL.** (Registered in `kernelConfig.ts` / `cm-decisions.jsonl`;
  no fixture exercises birth, so the store enforces only that the decision is
  *bound* at construction.)

The registry also binds `id-scheme`, `movement-as-log-taxonomy`,
`membership-model`, and `pending-status-gates` — the other four elements — so the
whole kernel is itself expressed as a set of resolvable CM decisions.

---

## What a fan-out builder consumes

```ts
import {
  HlcClock, IdMinter, EventLog, KindRegistry,
  pickLatest, LwwRegister, gateFor, passesGate,
  CmDecisionRegistry, loadCmDecisions,
} from "src/kernel";
```

A wave-1 builder receives the frozen `KindRegistry`, the `STATUS_CONTRACT`, and a
bound `CmDecisionRegistry` as fixed inputs; it writes only feature projections,
folding every latest-wins read through `pickLatest`. It cannot invent an event
kind, mint an ordinal id, or gate a projection off-contract without the kernel
throwing.

## Open items for Duke

1. Resolve each of the five picks (flip `status: "provisional" → "bound"` in
   `cm-decisions.jsonl` once approved).
2. Decide sub-decision 1a (movement-as-log) — the only pick that would change a
   committed judge (CP2) if flipped.
3. Confirm 2a (replica-counter vs uuid-v7) — both satisfy collision-freedom; the
   choice is opacity-vs-determinism.

---

## Resolution record — 2026-07-20 (decided-for-me)

Duke authorized blanket decide-for-me for the five kernel decisions before signing
off ("decide everything for me, get as far as possible, i'll check it in the
morning"). All five provisional picks above are hereby **RESOLVED: decided-for-me**,
rationales as documented per pick. Reversal condition for every entry: Duke's
morning review — any veto re-opens the decision through the metric-update /
decision-registry discipline (recorded re-decision, affected code regenerated;
no production data exists, so all five are cheaply reversible today).

| # | decision | resolution | flag |
|---|---|---|---|
| 1 | Event-kind taxonomy: movement is a distinct kind, `isLog:false` | decided-for-me | ⚠ **product-feel — review first**: the only pick whose flip changes a committed judge; farmOS itself models movements as activity logs |
| 2 | ID scheme: `prefix_replicaId~counter` | decided-for-me | routine |
| 3 | HLC `(physical, logical, replicaId)` total order | decided-for-me | routine (unanimous 7-build punt, now filled) |
| 4 | Single kernel `pickLatest` comparator | decided-for-me | routine (follows from #3) |
| 5 | Status gates: logs count-regardless / movements require-confirmed | decided-for-me | pinned by live-oracle observations |
| — | Birth-uniqueness convergence: earliest-HLC-wins, loser **demoted to observation** | decided-for-me | ⚠ **product-feel — review first**: determines whether a farmer sees a surfaced duplicate (observation record) vs nothing; data-preserving, majority-of-builders choice |

---

# Kernel v1.1 — the fold library (MetaCoding-9h5.26)

> Status: **v1.1, three additions all DECIDED-FOR-ME** (Duke's blanket decide-for-me
> authorization, same regime as the v1 resolution record above). Package:
> `src/kernel/{fold,gset,fww}.ts` (Bun, zero runtime deps). Validation
> re-expression: the wave-0 pilot's w0a inventory build folded on `FoldReduce`,
> 11/11 tests green; plus hermetic per-primitive unit tests
> (`src/kernel/{fold,gset,fww}.test.ts`) covering replay-determinism and
> cross-replica merge. Full `bun test`: 54/54 kernel, 427/427 repo, 0 fail.

## Why this exists

The v1 kernel froze exactly ONE projection fold — latest-wins (`pickLatest` /
`LwwRegister`, element 3) — because that is the axis the first two features
diverged on. The **wave-0 pilot** (`eval/ctkr/results/wave0-pilot-2026-07-20.md`,
§Kernel-gap) then ran the port recipe on two FRESH features and found the fold
vocabulary is the next divergence surface: **3 of the 4 headline fold shapes are
NOT latest-wins**, and a blind builder had to hand-roll them. Letting 100+ wave-1
builders each hand-roll a running balance, a grow-only set, or an append-if-empty
guard re-creates the exact "locally valid, globally divergent" risk the LWW freeze
killed — "one build folds from 0, another seeds from the reset and mishandles
ties; one build's grow-only set dedups, another doesn't."

v1.1 promotes the three missing folds to construction-enforced primitives, each as
sanctioned and HLC-keyed as `pickLatest`, plus the birth-uniqueness demotion
mechanic that v1 declared only as a `convergenceKey` string. Same philosophy: the
primitive is the ONLY ergonomic way to express its fold shape, and every one is
keyed on the kernel HLC total order, so replay and cross-replica merge converge —
never on entity id (`ids.ts` forbids it).

## The three additions (one-line summary)

| element | primitive | fold shape | pilot decision | file |
|---|---|---|---|---|
| 6 | `FoldReduce` | ordered reduce: `reset` ASSIGNS, deltas accumulate, over gate-passing events since the latest reset, keyed (effectiveTime, HLC) | w0a-1 / w0a-2 | `fold.ts` |
| 7 | `GSet` | grow-only ordered collection (append-only, order-preserving, no replace/remove/dedup), HLC-ordered | w0b-2 | `gset.ts` |
| 8 | `GuardedFirstWrite` + `demoteToObservation` | first-writer-wins (write iff empty; earliest-HLC across replicas) + bound-uniqueness loser demotion | w0b-1 / sub-decision 5a | `fww.ts` |

## Element 6 — `FoldReduce` (ordered reset/accumulate reduce)

**Question.** How is a running-balance-with-reset — inventory's `getInventory` —
folded, when it is neither latest-wins nor a plain additive sum?

**Pick (decided-for-me).** `FoldReduce<E, A>` (`fold.ts`): construct once with a
`FoldReduceSpec` (accessors for effectiveTime, HLC, is-reset, the reset value, the
delta accumulate, the initial, and an `admits` gate), call `fold(events, asOf)`.
It keeps events passing `admits` with `effectiveTime <= asOf`, orders them
(effectiveTime, then HLC — decision **w0a-2**, never id), locates the LATEST
reset's effectiveTime and drops everything strictly before it (inclusive
boundary), then left-folds from `initial` with reset-as-assignment. This is
exactly decision **w0a-1** (inventory-fold-semantics), and folding from `initial`
rather than seeding at the reset is what makes the same-effectiveTime tie correct
(a delta sharing the reset's timestamp is applied then overwritten). Replay- and
merge-deterministic because the (effectiveTime, HLC) order is total.

**Reversal:** an observed fixture showing reset/delta interleaving this ordering
gets wrong, OR the id-order tie-break (w0a-2) proving domain-observable in a way
HLC cannot reproduce. No production data exists; cheaply reversible.

## Element 7 — `GSet` (grow-only ordered collection)

**Question.** How is a grow-only multi-value field — animal nicknames — folded,
when it must append without replacing, dedup, or removing?

**Pick (decided-for-me).** `GSet<V>` (`gset.ts`): `add(value, hlc)` appends,
`merge(other)` unions, `values()` reads back in HLC order. It does NOT dedup by
value (nicknames are a multiset — the same nickname twice is kept twice); it
dedups only by ENTRY IDENTITY (the append's HLC), so a replayed append or a
re-merged peer is idempotent without collapsing genuine duplicate values. This is
decision **w0b-2** (nickname-multiset). Order-by-HLC makes two replicas that
appended in different real-time orders converge on one sequence — a G-Set CRDT.

**Reversal:** an observed fixture showing de-dup or removal (which would make it a
different CRDT). Routine flag. Cheaply reversible.

## Element 8 — `GuardedFirstWrite` + `demoteToObservation` (first-writer-wins family)

**Question (8a — parent lineage, w0b-1).** How is "append the mother to a child
iff the child has no parent — any existing parent is a complete veto" folded
deterministically under replay/merge?

**Pick (decided-for-me).** `GuardedFirstWrite<V>` (`fww.ts`) — the mirror of
`LwwRegister` with the comparator reversed: `set(value, hlc)` accepts iff empty OR
the incoming HLC strictly PRECEDES the incumbent, so sequential first-write-wins
and concurrent earliest-HLC-wins are the same rule. Replaying events in any order
lands on the same value. This is decision **w0b-1** (parent-lineage-append-if-empty).

**Question (8b — birth-uniqueness demotion, sub-decision 5a option A).** The bound
birth-uniqueness rule is earliest-HLC-wins with the loser demoted to an
observation. v1 declared this only as a `convergenceKey` string; no code
implemented it, so a wave-1 builder would hand-roll it (and the pilot's SURFACE
stage independently proposed the id-keyed variant option C, which element 2
forbids — friction F2).

**Pick (decided-for-me).** `demoteToObservation(candidates, hlcOf, toObservation)`
(`fww.ts`): keeps the earliest-HLC candidate, re-emits every loser through
`toObservation` (never silently dropped), returns `{ kept, demoted }`. The helper
owns only the mechanic — who wins, who is demoted — so a feature cannot re-derive
it as min-UUID or drop the loser; the domain supplies the observation-kind
transform. `pickEarliest` is exported as the mirror of `pickLatest`.

**Reversal (8a):** oracle shows a birth *correction* can later set a parent
(product-feel flag). **Reversal (8b):** Duke vetoes earliest-HLC / demote-to-
observation on morning review (product-feel — same entry as v1's birth-uniqueness
row). Cheaply reversible; no production data.

## Resolution record — 2026-07-20 (decided-for-me)

Under the same blanket decide-for-me authorization as the v1 record above, the
three v1.1 additions are hereby **RESOLVED: decided-for-me**. Reversal condition
for every entry: Duke's morning review — any veto re-opens the decision through the
decision-registry discipline (recorded re-decision, affected code regenerated). No
production data exists, so all three are cheaply reversible today.

| # | decision | resolution | flag |
|---|---|---|---|
| 6 | `FoldReduce` ordered reduce; reset assigns, ties break on HLC (w0a-1/w0a-2) | decided-for-me | routine — but w0a-2 (HLC vs id tie-break) is ⚠ minor product-feel pending oracle confirmation |
| 7 | `GSet` grow-only multiset, no dedup by value (w0b-2) | decided-for-me | routine |
| 8 | `GuardedFirstWrite` (w0b-1) + `demoteToObservation` (sub-decision 5a A) | decided-for-me | ⚠ **product-feel — review first**: w0b-1 decides whether a corrected birth can ever assign parentage; demotion decides duplicate-visible vs dropped |
