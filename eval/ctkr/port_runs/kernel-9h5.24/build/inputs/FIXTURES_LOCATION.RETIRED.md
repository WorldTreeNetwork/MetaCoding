# `FIXTURES_LOCATION.jsonl` is RETIRED — synthetic, superseded 2026-07-28

**Do not cite these ten fixtures as observation-backed, and do not use them to
judge a new port.** They are hand-authored. Every row carries
`provenance: null` with zero observation refs, and the current fixture schema
rejects them outright (`oracle-validate`: "provenance Field required").

They were counted in the kernel-v1 headline — *"17/17 logs + 10/10 location +
5/5 cross-probes (27 fixtures + 5 probes)"* — which read as 27 observed and was
17 observed plus 10 synthetic. `MetaCoding-4vh` was filed for exactly that, and
the OBSERVE pass it asked for was blocked because the flow DSL had no location
verbs.

## What replaced them

`MetaCoding-b0s` added the verbs; the pass ran on 2026-07-28 against the live
farmOS 4.x oracle. Two sealed packs, both self-verified **cold**:

| pack | seal | flows | what it records |
|---|---|---|---|
| `lexicon-bind/location/observe` | `f3460165d338` | 10 | placement, latest-done-wins, pending inert, future-dated inert, multi-location, multi-asset, geometry-from-the-movement, fixed assets, place-vs-thing defaults |
| `lexicon-bind/location_asof/observe` | `d7f164e35f20` | 7 | the as-of read, and the fan-out (what is *in* a place) both now and as of a moment |

Every value in both was filled from what farmOS delivered. Nothing is authored.

## Assertion-by-assertion, so the retirement is checkable

`tests/test_retired_location_fixtures.py` asserts this table rather than
trusting it.

| assertion | uses | status |
|---|---|---|
| `is_at_location` | 12 | recorded — both packs |
| `current_location_count` | 7 | recorded — `location` |
| `current_geometry` | 2 | recorded — `location` |
| `is_location` | 2 | recorded — `location` |
| `is_fixed` | 1 | recorded — both packs |
| `assets_at_location_count` | 2 | recorded — `location_asof` |
| as-of (`at` on an assertion) | 3 | recorded — `was_at_location`, and `assets_at_location_count` with an instant |
| `has_location` | 2 | **redundant** — `current_location_count > 0`, and the count is strictly more informative |
| `has_geometry` | 2 | **redundant** — `current_geometry != ""` |
| `location_contains` | 2 | **redundant** — `is_at_location` with its two arguments swapped; same question, same two things |

The three redundant terms were deliberately not minted. A term that adds no
semantics still costs a probe binding, an adapter method, an authority
judgement and a port surface, and each one is somewhere a future implementation
can be wrong for no reason.

## Why the file is still here

Deleting it would falsify the record. `compose-9h5.16` and `kernel-9h5.24` are
records of what those runs actually scored, and they scored *these* rows; a
past run's inputs are not ours to rewrite. What was wrong was never the file's
existence — it was the claim made about it, which said "each `then` value was
recorded from the real system". That claim is corrected where it was made.
