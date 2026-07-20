# Port decisions — Asset Inventory ON the shared kernel v1

Blind build. Only `inputs/` was consulted (kernel v1, the generated adapter
contract, the unobserved candidate semantics, the target profile). Scope was the
**inventory-core** methods only (`appendInventoryAdjustment`, `getInventory`);
the quantity/quantity-type/rendering methods were ignored per instructions.

## Kernel primitives used directly

| Kernel primitive | Where / how used |
|---|---|
| `KindRegistry` (+ `freeze`) | One kind, `inventory_adjustment`, registered via `INVENTORY_ADJUSTMENT_SPEC` (`family: "asset-log"`, `isLog: true`, `statusGate: "require-confirmed"`), then **frozen** at adapter construction so no ad-hoc kind can appear later. |
| `EventLog` | The single append choke point. Every `appendInventoryAdjustment` builds a `KernelEvent` and calls `log.append`, which rejects any unregistered kind — "no ad-hoc kinds" is a construction guarantee, not a convention. |
| `IdMinter` | Mints **both** asset handles (`createAsset`, prefix `asset`) and per-event adjustment handles (prefix `invadj`), replica-scoped. No bare ordinal/integer ids anywhere. |
| `HlcClock` / `compareHlc` | `clock.tick()` stamps every appended event; `compareHlc` is the **sole** tie-break for adjustments sharing an `occurredAt`. |
| `passesGate` + `StatusGate` | Status filtering in `getInventory` routes through `passesGate(logStatus, "require-confirmed")` — the kernel contract decides, not a local `if`. |

Deliberately **not** used: `pickLatest` / `LwwRegister` — inventory's fold is not
latest-wins (see below); `CmDecisionRegistry` — no cross-replica invariant in the
inventory-core scope required binding a CM decision here.

## The fold I had to hand-roll: running-balance-with-reset

The kernel ships exactly one fold family — latest-wins, keyed on the HLC
(`pickLatest`, `LwwRegister`). Inventory is **not** latest-wins. Its value is a
stateful **left fold over an order**:

```
sort eligible events ascending by (occurredAt, compareHlc)
latestResetTs := max occurredAt among reset events
running := 0
for each event with occurredAt >= latestResetTs, in order:
    reset     → running  = value    (ordered ASSIGNMENT, not a delta)
    increment → running += value
    decrement → running -= value
```

`pickLatest`/`LwwRegister` cannot express this: they collapse a set to a single
newest write and discard order, whereas here every increment/decrement between
the latest reset and `asOf` contributes, and their **sequence** matters (a
decrement must be applied after the reset it follows). The reset is the only
assignment; it resembles a latest-wins pick of "the newest reset", but even that
is insufficient because deltas at-or-after the reset timestamp still apply.

Implementation notes that fell out of the candidate semantics:

- **Timestamp-inclusive reset boundary (semantic n4).** I keep events with
  `occurredAt >= latestResetTs` (not `>`), and fold from `0` with reset as an
  in-fold assignment. This is why an increment sharing the reset's timestamp but
  sorting *before* it (`+3`, then `reset 4`, then `-1` → **3**) is applied and
  then correctly overwritten by the reset. Seeding `running` with the reset's
  value and skipping to strictly-after-the-reset would give the same answer for
  n4's specific ordering, but folding-from-0 is the robust general form.
- **done-only + as-of (semantic n1)** and **per-exact-(measure,units) (n5)** are
  pre-fold filters/partitions; **new asset → `[]` (n3)** falls out for free (an
  asset with no eligible events produces no groups, hence no rows).

**Should the kernel ship this as a sanctioned primitive?** Yes — recommend a
kernel `foldOrdered(events, hlcOf, step, initial)` (an HLC-ordered left fold), or
a named `runningBalanceWithReset` reducer. Every ledger-style projection
(inventory, and any future stock/quantity balance) needs an HLC-ordered fold that
is *not* latest-wins; leaving it hand-rolled per feature reintroduces exactly the
"locally valid, globally divergent" risk the kernel exists to remove (e.g. one
build folding from 0, another seeding from the reset and mishandling ties).

## Same-`occurredAt` tie-break: HLC, not id (kernel requirement 3)

The source's apparent rule (per the adapter contract + semantic n4's prose) is
**id-ascending**: "processed by (occurredAt, adjustment ID ascending)". I did
**not** port that. Per kernel requirement 3 and `ids.ts` (which explicitly
forbids ordering by id — a per-replica counter is incomparable across replicas),
I break ties with `compareHlc(a.hlc, b.hlc)`.

- **How it differs from id-ascending.** A naive id-ascending tie-break orders by
  the local mint counter, which is meaningless across replicas: replica A's
  `invadj_A~3` and replica B's `invadj_B~3` are incomparable, so two replicas
  replaying the same two same-timestamp events could disagree on order and
  diverge. The HLC `(physical, logical, replicaId)` is a **total** order across
  replicas, so the fold converges regardless of arrival order.
- **Why the tests still match the source's numbers.** Within a single replica,
  `HlcClock.tick()` is monotonic in append order, so appending in the source's
  id-ascending order reproduces the same sequence the source intended — the
  divergence only manifests across replicas, which is precisely where
  id-ascending is wrong and HLC is right. The dedicated tie-break test
  (`reset then +5` = 9 vs `+5 then reset` = 4) confirms the fold is driven by
  HLC/append order, not by any id comparison.

## Status gate — a required kernel addition

`STATUS_CONTRACT` has **no `currentInventory` row**. Inventory needs a
`require-confirmed` gate (pending adjustments are inert — semantic n1 excludes the
pending `+3`), identical in reading to `currentLocation`. Because the row is
missing, I:

1. Name the gate locally (`INVENTORY_GATE = "require-confirmed"`), and
2. still route the actual decision through the kernel's `passesGate(status,
   "require-confirmed")`, so no bespoke status `if` re-litigates the contract.

**Recommended kernel addition:** add a `currentInventory: "require-confirmed"`
row (and likely `assetsInventory`/related) to `STATUS_CONTRACT`, after which the
adapter should call `gateFor("currentInventory")` instead of a local constant.
This is the only place the kernel felt under-provisioned besides the missing
ordered-fold primitive.

## Under-provisioned observations (summary)

1. **No ordered (non-LWW) fold primitive** — the running-balance-with-reset had
   to be hand-rolled. Highest-value addition.
2. **No `currentInventory` status row** — gate named locally as a stopgap.

Everything else (kind registry + freeze, EventLog rejection, IdMinter, HLC
tie-break) fit inventory naturally and required no workaround.

## Test result

```
$ bun test
bun test v1.3.14 (0d9b296a)

 11 pass
 0 fail
 18 expect() calls
Ran 11 tests across 1 file. [18.00ms]
```

Coverage: candidate semantics n1–n5 each have a dedicated test, plus HLC
tie-break (both orderings), as-of reset exclusion, no-reset additive fold, and
the kernel gates (IdMinter replica-scoping, registered-kind append, cross-replica
non-collision).
