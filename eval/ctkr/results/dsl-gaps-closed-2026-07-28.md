# Session record — the FlowSpec DSL expressibility gaps (MetaCoding-b0s, -4vh)

> 2026-07-28. Handoff for whoever picks this up next. Written to be read cold.

## What this session did

Closed twelve of the thirteen named DSL expressibility gaps from
`wave1-readiness-2026-07-20.md` §2, and with them the OBSERVE half of
MetaCoding-4vh. Five packs recorded against the live farmOS 4.x oracle, twelve
glossary terms bound, two kernel decisions bound, one carried test failure
fixed.

`MetaCoding-b0s` and `MetaCoding-4vh` are CLOSED. `MetaCoding-3jj` was split
out (see "what is left", below).

### The packs — all self-verified COLD, every value observed

| pack | seal | | what it records |
|---|---|---|---|
| `lexicon-bind/lineage_clear` | `3c5685d3d9bf` | 6/6 | clear-a-mother, the second parent |
| `lexicon-bind/ghost_subject` | `92696edac74a` | 4/4 | the UNANSWERABLE channel |
| `lexicon-bind/location` | `f3460165d338` | 10/10 | `move` + five location reads |
| `lexicon-bind/location_asof` | `d7f164e35f20` | 7/7 | the as-of read, the fan-out |
| `lexicon-bind/last_gaps` | `9b49878b6b17` | 5/5 | sterility, animal type, quantity reads |

### Terms bound (add-term → live implementation → authority refinement → sealed pack → bind-term)

`move`, `is_at_location`, `current_location_count`, `current_geometry`,
`is_location`, `is_fixed`, `was_at_location`, `assets_at_location_count`,
`is_sterile`, `animal_type`, `quantity_measured_value`, `quantity_label`.

## The three judgement calls, and why

**The as-of read is its own term, not a parameter.** `is_at_location`
TRANSCRIBES — farmOS computes the current-location rule (`AssetLocation.php`)
and publishes the answer as the asset's own `location` relationship.
`was_at_location` COMPUTES: farmOS offers no as-of read at its boundary at all
(validated live — `?timestamp=` is not a boundary parameter, the working copy
still delivers the current location). One `ProbeSpec` carries one authority, so
folding them would have let a transcription's standing launder a derivation —
and would have rotated a bound term's `derivation_id`, invalidating the pack
already recorded under it.

**The second parent was an adapter defect, not a DSL gap.** The flow could
always say two; `farmos_adapter.record_birth` sent `parent_handles[0]` and
dropped the rest silently. It now transmits what the flow stated and lets the
SOURCE answer — `422 "mother: Mother: this field cannot hold more than 1
values."` An adapter-side guard would have substituted our sentence for
farmOS's, and a refusal is only BOUNDARY evidence while the source states it.

**Three assertions were deliberately NOT minted.** `has_location`
(= `current_location_count > 0`), `has_geometry` (= `current_geometry != ""`),
`location_contains` (= `is_at_location` with its arguments swapped). A term that
adds no semantics still costs a probe binding, an adapter method, an authority
judgement and a port surface — each somewhere an implementation can be wrong
for no reason. Recorded in the retirement note and enforced by
`tests/test_retired_location_fixtures.py`.

## Live-source findings worth keeping

- **Clearing a birth's mother does NOT retract the child's parentage.**
  `farm_birth EntityHooks::syncBirthChildren` appends the mother to the child
  only when the child has NO parents at all, and never retracts. So recording a
  birth from a dam adds nothing when the child already has a stated parent. This
  is the guarded-first-write semantic, now observed in two independent packs.
- **`is_location` / `is_fixed` / `is_sterile` are genuine tri-states.** With
  nothing stated, a land asset is both a place AND fixed; an animal is neither.
  The DSL leaves all three unstated-by-default because the source's own default
  is itself an observable — defaulting them to `false` would overwrite farmOS's
  answer with ours.
- **farmOS's log timestamp is a 32-bit column.** A year-2099 movement produces a
  500 inside farmOS's own SQL (`value "4070908800" is out of range for type
  integer`). Date future-dated flows before 2038, or use a relative offset.
- **`filter[location.id]` answers on a LOG and 500s on an ASSET** — the log's
  location is stored, the asset's is computed. That asymmetry is what makes the
  fan-out tractable.
- **`quantity_recorded` SUMS.** Two quantities of the same measure and unit on
  one log read back as one number (3 + 7 → 10.0). That was the whole
  quantity-level-reads gap.

## Instrument defects found on the way (all fixed)

1. **`term_codegen`'s anchor is fragile.** It inserts class-body methods before
   `"\ndef _iso("`, treating it as "the first module-level def after the adapter
   class". A helper defined above `_iso` silently emits every generated adapter
   stub at MODULE scope. Caught by `test_add_term`; `_epoch` now sits below
   `_iso` with a comment saying why. **If you add a module-level helper to
   `farmos_adapter.py`, put it after `_iso`.**
2. **The WHEN clause had no silent-drop guard.** `_GIVEN_KEYS` had one (it caught
   the w4a sensor recording minting random keys); `_WHEN_KEYS` did not, and
   `clear_parents` would have been the next victim. Added.
3. **The flow loader and the fixture validator disagreed** about whether a
   quantity alias is a probeable subject. That disagreement WAS the
   quantity-reads gap.
4. **`add-term` writes every declared param into `_ASSERT_REQUIRED`.** It cannot
   know which are optional. `assets_at_location_count`'s `as_of` had to be
   removed by hand after generation.
5. **`add-term` always emits `DERIVED` with no `validated_against`.** Refining
   authority post-generation is a REQUIRED step, not a nicety: a bound term whose
   `ProbeSpec` cannot score is NO VERDICT on every assertion in its name, and it
   is silent. The generated `test_term_*.py` skeletons pin the pre-refinement
   state; they must be inverted, not deleted.

## Kernel decisions bound this session

- **Sub-decision 2b, the HLC** — was `PROVISIONAL` for eight days while
  `pickLatest`, `LwwRegister`, `FoldReduce`, `GSet` and `GuardedFirstWrite` were
  all keyed on it. It was never on the open-items list, which is how it was
  missed. Bound: no alternative was ever proposed, and what it replaces was
  flagged unsafe by all seven builds.
- **`GuardedFirstWrite`** — the v1.1 table said UNBOUND (Duke's morning reversal
  of w0b-1); `fww.ts` had said bound-on-evidence since the same afternoon. Doc
  was stale, code was right. Bound on two independently recorded packs. **Scope
  is the VERB, never the field:** birth → `GuardedFirstWrite`, `set_parents` →
  `LwwRegister`, birth time → `LwwRegister`.
- **The carried `bun test` failure** — `cm-decisions.jsonl` gained
  `sanctions: ["yield_total", "log_count"]` in `b0b45db` and
  `kernelConfig.ts BOUND_CM_DECISIONS` did not. Fixed on the jsonl's side:
  without the field the port's ONE deliberate divergence is unsanctioned and
  `goal_fit` scores the port's own chosen target as a failure. Deleting it from
  the jsonl would have made the test pass by silently un-declaring the divergence.

## What is left, honestly

**On this thread:**

- `MetaCoding-3jj` (P3) — the migration entry point, the thirteenth gap. Split
  out rather than built because it is UNDERSPECIFIED: the phrase appears once in
  the list of thirteen and nowhere else. The likely reading questions the `given`
  clause itself and collides with two properties the oracle relies on
  (reproducibility, and the no-ids rule). The bead lays out three directions and
  says to pick the question first. **Do not start it without deciding which
  question is being answered.**
- `which-event-won` is WONTFIX (Duke, 2026-07-28): such flows are
  order-sensitive and the recorder already marks them corroboration-only, so the
  value could never score anything.
- The three unminted redundant assertions, if a port wants them for ergonomics.

**Where the project actually is** — read this before assuming the instrument's
health means the port is far along:

- The **instrument** (oracle, glossary, probe contract, pack seals, judge,
  kernel) is mature. 43 sealed packs in `PACKS.jsonl`; as of today there is no
  known DSL expressibility gap blocking observation of a farmOS semantic.
- The **port itself has barely begun.** `MetaCoding-hy6` — "port the app:
  risk-partitioned bulk port of the farmOS clean slices" — is an open epic with
  NO children. Everything under `eval/ctkr/port_runs/` is pilots and
  instrument-validation runs (`wave0-pilot`, `wave1`, `wave1-c1`, `wave2`,
  `compose-9h5.16`, `kernel-9h5.24`, `lexicon-bind`), not the 147-feature
  fan-out. The instrument is sharp; the thing it measures is mostly unbuilt.
- `MetaCoding-9h5` (foundation hardening) is still open but its wave-1 blockers
  were cleared 2026-07-20; the six remaining children are P2/P3 research
  (contamination measurement, differential fuzzing, ablation replication,
  oracle throughput).
- **A second program opened mid-session.** `MetaCoding-d1l` — "spec-anchored
  porting", landed by Duke at 12:51 today (`ad9459a`) with two **P0 spikes**
  (`d1l.6`, `d1l.7`). It is a different port shape: no source codebase, a
  normative RFC plus three independent OIDC implementations, argued as a
  CALIBRATION INSTRUMENT for the intention-extraction program (which lacks
  external ground truth). **If you are picking up work by priority, the P0s are
  there, not here.**

## Conventions this session followed (worth keeping)

- Every new term goes `add-term --apply` → implement against the live boundary →
  **refine authority** → record a sealed pack → `bind-term`. There is no other
  path to a scorable term.
- Every pack gets an adversary: a plausible port with ONE rule flipped per
  variant. A correct port must score full marks and each bug must be caught by
  exactly the fixture stating its rule. Assumed discrimination is not
  discrimination.
- Golden fixture ids are computed by checking the PRE-change code out of git into
  a clean tree and running it there — never derived from the code under test.
- Any new optional field must be dropped at its default in
  `_dump_given_for_hash` / `_dump_when_for_hash` / `_dump_then_for_hash`, or it
  silently re-ids every sealed pack at once.
- `probe_descriptor` adds a new key ONLY when set: it is compared key-for-key
  against witnesses already on disk.

## State at handoff

`main` == `origin/main`, working tree clean, Dolt pushed.
**pytest 1021 passed, 3 skipped. bun 698 pass, 0 fail** (was 697/1 at session
start — the fixed drift above).

The shared farmOS oracle at `localhost:8095` is UP and was written to heavily by
this session. It is SHARED: do not run `bring-up.sh`, docker, or drush against
it — restarting it is an operator decision. Note that `assets_at_location_count`
counts every asset the source publishes at a location, including ones a flow did
not create, so a fan-out flow must use a location no other flow touches.
