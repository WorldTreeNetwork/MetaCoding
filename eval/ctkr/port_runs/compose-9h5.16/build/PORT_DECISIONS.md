# Port decisions — one shared store, two feature adapters

## 1. Event schema — ONE array, several event kinds

`src/store.ts`'s `SharedStore` holds exactly one array, `events: StoreEvent[]`
(`src/types.ts`). Every mutation from either adapter — `createAsset`,
`recordLog`, `setLogStatus`, `assignToGroup`, `archiveAsset`,
`recordMovement`, `setIntrinsicGeometry` — appends to this single array.
There is no second log, no per-feature table, no in-place field mutation.

Event kinds:

| type | fields | who appends it |
|---|---|---|
| `asset_created` | assetId, entity, name, descriptor?, isLocation, isFixed, intrinsicGeometry? | both adapters' `createAsset` |
| `log_recorded` | logId, kind, name, status, assetIds[], quantities[] | logs `recordLog` |
| `log_status_changed` | targetId, status | logs `setLogStatus` **and** location `setLogStatus` |
| `group_assigned` | assetId, groupId | logs `assignToGroup` |
| `asset_archived` | assetId | logs `archiveAsset` |
| `movement_recorded` | movementId, assetIds[], locationIds[], status, geometry? | location `recordMovement` |
| `geometry_set` | assetId, wkt | location `setIntrinsicGeometry` |

**Is a movement a kind of log, or a distinct event kind?** Distinct. A
movement is `movement_recorded`, not `log_recorded`. It shares the *same
array* and the *same status-lifecycle mechanism* (`log_status_changed`
targets a `logId` **or** a `movementId` interchangeably via a generic
`targetId`, since both are "things with a pending/done lifecycle" per the two
contracts), but it is not counted as a domain "log".

**Does a movement count in `logCount`?** No. `logCount(asset, kind)` (in
`store.ts`) filters strictly on `type === "log_recorded"`, so a movement can
never satisfy it — `kind` in the logs contract only ever takes harvest/
input/activity/observation/seeding, a vocabulary a movement was never part
of. This also means `assetYieldTotal`, which sums `log_recorded.quantities`,
never picks up a movement's `geometry`/`locations` payload. The two features'
numeric aggregates stay clean while still living in the same array.

## 2. ID / handle minting — one counter, one scheme

`SharedStore` has a single private counter `seq`, incremented by
`nextSeq()`/`mintHandle()`. Every handle — asset, log, movement — is
`` `${prefix}_${seq}` `` (`asset_7`, `log_12`, `mvt_3`, ...) drawn from that
one counter, so IDs minted by the logs adapter and the location adapter are
interleaved in one identity space and can never collide. The prefix is purely
cosmetic/debugging convenience; the verifier treats handles as opaque strings
either way. `seq` doubles as the insertion-order tie-break value described in
§4.

## 3. Asset model — one record, both features' fields as optional facets

There is one `AssetCreatedEvent` (and therefore one conceptual "asset
record", reconstructed by the fold in `findAsset`) carrying: `entity`,
`name`, `descriptor?` (logs vocabulary) *and* `isLocation`, `isFixed`,
`intrinsicGeometry?` (location vocabulary), side by side on the same event.
Neither feature's `createAsset` needs to know about the other's fields:

- The logs adapter's `createAsset(entity, name, descriptor?)` calls
  `store.createAsset({entity, name, descriptor})`, leaving `isLocation`/
  `isFixed` to default to `false` and `intrinsicGeometry` to `undefined`.
- The location adapter's `createAsset(spec: AssetSpec)` passes all five
  fields through.

Because both funnel into the same `SharedStore.createAsset`, an asset created
by one adapter is a first-class, fully-formed asset from the other adapter's
point of view — e.g. `location.isLocation(assetCreatedViaLogs)` is a
well-defined `false` rather than throwing/undefined (see
`test/logs.test.ts`'s "composed store sharing" block).

## 4. The ONE latest-wins fold + tie-break rule

Both "latest wins" reads — group reassignment (`groupMember`) and current
location (`currentLocations`/`assetsAtLocation`) — go through the **same**
private helper, `SharedStore.pickLatest<T>()`:

```ts
pickLatest(candidates) picks the candidate with the greatest `timestamp`,
breaking ties by the greatest `seq`.
```

Every event carries a `timestamp` and a `seq`. For events with a real domain
timestamp (movements, via `MovementSpec.timestamp`), `timestamp` is that
value. For events with no domain timestamp at all (`assignToGroup`,
`archiveAsset`, `setLogStatus`, `setIntrinsicGeometry`, `createAsset`),
`timestamp` is simply set to that event's own `seq` at insertion time — i.e.
the monotonically increasing counter acts as a logical clock when no wall
time is supplied. `seq` is always strictly increasing regardless, so it is
always available as the tie-break.

This single rule is what "latest wins" means everywhere in the store:
- `groupMember(asset, group)`: fold all `group_assigned` events for `asset`
  through `pickLatest`; membership is `latest.groupId === group`. Since these
  events have no domain timestamp, `timestamp == seq`, so this reduces to
  "the last `assignToGroup` call wins" — exactly the fixture
  ("group-reassignment-latest-wins").
- `currentLocations(asset, atTimestamp)`: fold all `movement_recorded` events
  for `asset` with `timestamp <= atTimestamp` and effective status `"done"`
  through `pickLatest`; the winning movement's `locationIds` is the answer.
  Same-timestamp movements (fixture "tie-break to later-recorded one") are
  resolved by `seq`, which is exactly insertion order.

## 5. Tie-break scheme — one scheme, everywhere

Stated once, used everywhere: **compare by `(timestamp, seq)` ascending;
whichever candidate has the greater pair wins; `seq` is the eternal
tie-break because it is unique and strictly increasing.** For timestamped
events (movements) this is a per-asset last-writer-wins by domain time with
insertion order as the tie-break (matches the same-timestamp movement
fixture). For un-timestamped mutations (group/status/archive/geometry
changes on the logs side) `timestamp` degenerates to `seq`, so ordering is
simply insertion order — a plain event-sourced LWW. This is the "hybrid"
part: a real timestamp when the caller supplies one, the logical (insertion)
clock otherwise, one comparator for both.

## 6. Pending / status semantics — the deliberate divergence

Both `log_recorded` and `movement_recorded` events (and their
`log_status_changed` overrides) share the exact same `status: string` field
(`"pending" | "done"`) and the exact same status-fold logic
(`logStatus`/`movementStatus`, both built on `pickLatest`). The two
projections read that shared field **oppositely on purpose**, and this is
consistent with a single event schema because the *aggregation semantics*
differ, not the *status representation*:

- **Yield/logCount (logs feature):** `assetYieldTotal` and `logCount` sum/
  count over `log_recorded` events **regardless of status**. A pending
  harvest already asserted that the harvest happened (i.e. was recorded) —
  its lifecycle state answers "has this record been reconciled/approved
  yet?", not "did this event occur?". So it always contributes.
- **Current location (location feature):** `latestMovement` filters
  `movement_recorded` events down to `status === "done"` before folding.
  Here "pending" means "this movement is proposed/in-flight, physically not
  yet true" — a planned-but-unconfirmed relocation must not change where the
  asset currently *is*, or every write ahead of confirmation would
  incorrectly reposition assets across the whole replica.

In one sentence: `status` universally means "has this event's real-world
occurrence been confirmed," and each projection decides for itself whether
its answer is about historical bookkeeping (logs — pending records still
count) or present physical state (location — pending movements don't apply
yet). Nothing about the event schema changes between the two adapters; only
the read-time filter differs, which is exactly what "thin projection views
over one log" is supposed to allow.

## 7. Birth-log uniqueness (design note only — not fixture-exercised)

No fixture in either pack exercises a `birth` log kind or a
"one birth log per asset" invariant, and this store does not special-case
`kind === "birth"` beyond treating it as an ordinary `log_recorded.kind`
string. If this port grew that invariant, the chosen menu answer (per
`TARGET_PROFILE.yaml`, `decision_menu.hard`, since "at most one" is a hard
uniqueness constraint and this target has `coordination_layer: false`) would
be:

**`preserve-via-convergence-rule`.**

Rationale: a birth log is keyed by the same UUID-style handle scheme as
everything else in this store (§2), so two replicas can each independently
record a `birth` log for the same asset offline. Rather than weakening the
invariant to "eventually true" (which would let a synced replica show two
births for one animal, a materially wrong farm record) or moving it to the
disclosure layer (this isn't an access-control question), the convergence
rule is: on sync/merge, `birth` logs are deterministically merged per-asset
by the same `(timestamp, seq)` order already used everywhere else in the
store — the earliest-effective `birth` log for a given asset wins and any
later-arriving concurrent `birth` log for the same asset is demoted to an
`observation`-kind record (or otherwise flagged, but never silently
dropped) rather than being allowed to coexist as a second birth. This keeps
the invariant *hard* (never more than one authoritative birth log survives
convergence) while requiring no central authority to enforce it at write
time — exactly the `preserve-via-convergence-rule` menu option, applying the
same UUID/HLC-ordering machinery this port already uses for every other
latest-wins fold (§4), rather than introducing a new mechanism just for
this one invariant.
