# Trust-model refactor — verdict

**Date:** 2026-07-20
**Tree under test:** `/Users/dukejones/work/WorldTree/MetaCoding`, HEAD `ba595a5` + **39 uncommitted paths** (the refactor is uncommitted; see *Provenance of this review* below)
**Predecessor:** `eval/ctkr/results/wave1-readiness-v2-2026-07-20.md` (NO-GO, wave size 0)

---

## Verdict in one line

**The refactor achieved its stated purpose and is still NO-GO.** The GO test passes — the
judge now ranks a farmOS-matching port above an adapter-matching one, and the causality is
proven. But invariant 2 was enforced one artifact too low: the pens were taken away at the
*pack* and reappeared at the *flow spec* and at a newly shipped `oracle-seal` CLI. A port
carrying the exact C1 defect can still be made to exit 0 at 100% clean, with no forgery,
using only documented schema fields and shipped commands.

**Wave-1 recommendation: NO-GO. Wave size 0.** Three fixes reopen it (§7).

---

## 1. THE GO TEST — the only question that matters first

> Does the judge rank a port that matches farmOS above a port that matches our adapter?

**YES. Independently replicated, with farmOS's own service as ground truth.**

The adversary built its *own* flow pack and its *own* ports (not the implementer's),
recorded live against farmOS 4.x at `localhost:8095`, and cross-checked every recorded
expectation against farmOS's own `group.membership` service via `drush php:script`, not
against our adapter.

| Port | Membership semantics | Score | Verdict |
|---|---|---|---|
| **B** | fully recursive (= farmOS `getGroupMembers(..., recurse=TRUE)`) | **6/6 = 100.0%** | **CLEAN** |
| **D** | recurses exactly one hop | 5/6 = 83.3% | NOT CLEAN |
| **A** | non-recursive (= the pre-refactor adapter, the C1 defect) | 4/6 = 66.7% | NOT CLEAN |

The ranking is correct **and monotone in distance from farmOS**. The implementer's own
pack (`eval/ctkr/port_runs/wave1-c1/observe/`) agrees: portB 4/4 = 100.0% clean, portA
3/4 = 75.0% NOT CLEAN. The acceptance direction that v2 found *inverted* is now upright.

**Ground truth is now farmOS, not the adapter.**
`docker exec farmos-oracle-www drush php:script` calling
`\Drupal::service('group.membership')->getGroupMembers([$G], TRUE, NULL)` on the exact
UUIDs the recorder created returned **6/6 identical** to the recorded fixture values.
A separate direct probe of `FarmOSAdapter.group_member()` against the service agreed
**5/5** on recursion, the effective-time gate, and the equal-timestamp tie-break.

**Causality proved, not assumed.** Mutating a sandbox copy of the adapter back to the
pre-C1 `return gid in frontier` and re-recording the *same* flows live re-inverts the
ranking *exactly*: wrong port A → 6/6 = 100.0% CLEAN, correct port B → 4/6 = 66.7%
NOT CLEAN. Same ports, same judge, only the derivation changed. The inversion was the
adapter's derivation; the fix removed it. A repo test pins it:
`tests/test_oracle_invariants.py::test_group_member_recurses_by_default`.

**This is a real result and it should be preserved verbatim through whatever comes next.**
Everything below is about what the refactor did *not* reach.

---

## 2. Attack ledger — by construction, by guard, or open

The distinction is the point. *By construction* means the shape of the score denies the
port a lever; the next adversary has nothing to go around. *By a guard* means a
conditional that passed review; the next adversary goes around it.

### 2.1 Blocked BY CONSTRUCTION

| # | Attack | Mechanism that defeats it |
|---|---|---|
| S1 | **Liar port** — 999 to every probe, 30 declared divergences citing real decision ids | A divergence is scored `DIVERGED`, never `PASSED`. `value_score` is computed over passes only, so sanctioning everything drives the score to **0.0**, not 100%. Result: value 0.0, clean=False, EXIT=1. |
| S2 | **Exclude-everything marks file** | `scored_nothing` branch: "NOTHING WAS SCORED — this run is evidence of nothing", value 0.0, EXIT=3. (Moot now that `--marks` is deleted, but the branch remains as backstop.) |
| S3 | **Run a subset of a sealed pack (A5)** | Deleting the one fixture port A fails → `NO VERDICT — the evidence is not sound: does not match its seal (8afbf20d… vs f1e312db…). The pack was changed after recording.` Exits **before any scoring**. |
| S4 | **Port narrows scope by declaring no probes** | Port G (`probes: []` in both manifest and bridge) → coverage 0/6, 6/6 NO VERDICT, "evidence of nothing", NOT CLEAN. Port F (manifest `probes: []`, bridge advertises `group_member`) is **refused outright**: "port manifest and running bridge disagree about the probe surface — a capability claim must be unambiguous." |
| S5 | **Port-authored `fixture_marks` (C2/A1)** | The field is **deleted** and `extra="forbid"` makes a manifest that still carries it fail to load. There is no code path left. |

### 2.2 Blocked BY A GUARD (patch-shaped; the next adversary goes around)

| # | Attack | Guard | Why it is fragile |
|---|---|---|---|
| G1 | **Decline exactly where wrong (A4)** | Declines are counted as declaration problems, and NO VERDICT blocks `clean`. Port E (declares `group_member`, refuses >1-hop) scores 66.7% NOT CLEAN — *no better than answering wrongly*. | Materially improved over v2 (where the duck bought a 100.0% headline). But it remains a counter feeding a boolean, not a shape. |
| G2 | **Divergence citing a real but irrelevant `decision_id`** | Moot for now: `--decisions` is deleted, so a port author can no longer point the sanction resolver anywhere. | The *relevance* hole was never fixed — the registry check tested existence, never relevance. If any sanction path is ever reintroduced, this returns intact. |
| G3 | **Pack-carried `evidence_class` re-admission** | A later mark cannot re-admit a fixture recorded as corroboration-only. | Correct as written — and it is precisely the mechanism attack **A-NEW-1** inverts from the other side (§3.1). |

### 2.3 STILL OPEN

Six. Ranked by damage. Full detail in §3; the C-numbering is settled in §6.

| # | Attack | Status |
|---|---|---|
| **A-NEW-1** | `corroboration_only` in the port lane's own flow JSON → sealed pack stamped `corroboration-only` → C1-defective port exits 0 at 100% clean | **OPEN — blocker** |
| **A-NEW-2** | `ctkr oracle-seal` re-issues the recorder's seal on a self-chosen subset; `registered_seals()` is dead code | **OPEN — blocker** |
| **A-NEW-3** | The seal binds bytes, not meaning: re-hash a forged expected value and it loads as valid evidence | **OPEN — blocker** |
| **A-NEW-4** | `derivation_id` hashes prose, not code: the literal C1 regression is invisible to the staleness invariant | **OPEN — blocker** |
| **A-NEW-5** | Auto-detected order sensitivity is a second, quieter route to A-NEW-1 | **OPEN — secondary** |
| **A-NEW-6** | The effective-time gate is unreachable by any pack, and the recorder silently records the *opposite* value | **OPEN — correctness** |

---

## 3. What the fresh adversary found

New holes matter more than replayed ones. All four blockers were confirmed **by execution
against the live oracle, with no modification of the pipeline code**.

### 3.1 A-NEW-1 (worst) — the exclusion pen moved one file upstream

`corroboration_only: true` is a **documented, schema-legal field on a flow**
(`ctkr/ctkr/oracle/flowspec_io.py:371`). The *untampered* recorder faithfully transcribes
it into `evidence_class: corroboration-only` on the sealed pack — the very artifact
`port_verify` trusts *because a party with no stake wrote it*. The flow file is authored by
the same lane that builds the port.

Measured, zero forgery:

- **Baseline** on the repo pack `eval/ctkr/port_runs/wave1-c1/observe/`:
  portA (non-recursive = the C1 defect) → `failed: 1`, reproduced 3/4 = **75.0%, NOT A CLEAN PASS**.
  portB (correct) → 4/4 clean.
- **Attack:** copy `wave1-c1/c1-membership-flows.json`, add `"corroboration_only": true`
  plus a reason to the `c1-membership-transitive` flow, run the **unmodified** recorder:
  `uv run python -m ctkr oracle-record --flows <flows.json> --out-dir …/FRESH-c1corr`
  → `pack seal 6d3a9f2ec09a`.
- **Result:** `port-verify FRESH-c1corr/fixtures.jsonl --port wave1-c1/portA` →
  `fixtures: 3 (1 corroboration-only, 0 INVALID EVIDENCE) / NO VERDICT 0 / scored 2 /
  passed 2 / failed 0 / coverage 4/4 = 100.0% / reproduced 2/2 = 100.0%`,
  **no `NOT A CLEAN PASS` block, EXIT=0.** portB on the same pack: EXIT=0.
  **The wrong port and the right port are now byte-identical verdicts.**

The `[FAIL]` line is still *printed* (`group_member(A) expected == True, got False`) but is
`scored=False`, so it never reaches `needs_review` or `clean`. Confirmed in source:
`port_verify.py:249-264` — the `clean` property has clauses for `scored_failed`,
`no_verdict`, `declaration_problems`, `invalid_evidence`, `scored_diverged` and
`scored_nothing`, and **no clause for `excluded_corroboration` / `fixtures_excluded`**.

`--flows` additionally still lets that lane choose which flows exist at all.

### 3.2 A-NEW-2 — `oracle-seal` hands the defendant the recorder's pen

The refactor **shipped a new CLI** (`ctkr/ctkr/commands/oracle_seal.py`, 61 lines) that lets
anyone re-issue the recorder's seal.

- Baseline w0a: 12 fixtures, 13 NO VERDICT, coverage 56.7%, NOT A CLEAN PASS.
- Attack: keep only the 4 fixtures whose every outcome was `passed`
  (`303e80f5, dc7a9a07, 8b7da705, f7b9a1c9`), copy `observations.jsonl` verbatim, run
  `uv run python -m ctkr oracle-seal <dir>` → new **valid** seal `9b260308e90c`.
- Result: `fixtures 4 / assertions 10 / NO VERDICT 0 / passed 10 / coverage 100.0% /
  reproduced 10/10 = 100.0%`, **EXIT=0, clean.**

`pack.py`'s own docstring says this gap is "closed socially" by `PACKS.jsonl`. It is not:
`grep -rn registered_seals ctkr/` returns **exactly one hit — its own definition at
`pack.py:194`. Nothing ever reads the registry.** Worse, `registry_for()` (`pack.py:168`)
walks up only until a `.git`, so any pack sealed outside the repo tree returns `None` and is
silently never registered — verified: the honest live recorder run in §3.1 produced seal
`6d3a9f2ec09a` and `PACKS.jsonl` stayed at 5 lines with no warning.

Note the interaction: S3 (subset defeated by the seal) is defeated **only** because the
attacker did not re-seal. `oracle-seal` converts a by-construction win into a one-command
bypass.

### 3.3 A-NEW-3 — the seal binds bytes, not meaning

Took the w0a pack, changed fixture `f7b9a1c9`'s `stock_on_hand` expected value
`-3.0 → 999.0`, **recomputed `SemanticFixture.content_id()`** so the self-hash check at
`pack.py:209` passes, left `observations.jsonl` untouched, re-sealed. `port-verify` reports
`fixtures: 12 (… 0 INVALID EVIDENCE)` and `[FAIL] stock_on_hand(bin) expected == 999.0,
got -3.0`.

The pack loader **never re-derives an expected value from the observation it cites** —
`pack.py:215` only checks that each `observation_refs` id *exists* in `observations.jsonl`.
Provenance is name-resolution, not corroboration. The existing guard
(`tests/test_oracle_invariants.py:253 test_an_edited_expected_value_is_rejected_by_the_pack_loader`)
covers only the naive edit that forgets to re-hash. Consequence runs both ways: an incorrect
port can be made clean, and a correct port can be made to fail.

### 3.4 A-NEW-4 — `derivation_id` hashes the English sentence, not the code

`ProbeSpec.derivation_id` (`probes.py:119-135`) hashes `{assertion, derivation,
validated_against}` — three **prose strings** in the probe table.

Measured: before mutation `current_derivations()['group_member'] == 22b77a9c85a4989d`.
Reverting `farmos_adapter.py`'s `group_member` to the C1 defect (`as_of = 9999999999` to
kill the time gate, early `return gid in frontier` to kill recursion) while leaving the prose
untouched gives `group_member derivation_id AFTER : 22b77a9c85a4989d` — **identical** —
with `is_evidence: True` and `unvalidated_probes(): []`. Every pack recorded under the
"corrected" derivation still loads as **current evidence** while the adapter computes the
old wrong thing.

The only thing that caught this mutation was two bespoke live-oracle tests hand-written for
**one** of the ten derived probes. The other nine (`yield_total`, `adjustment_count`,
`stock_on_hand`, `log_count`, `quantity_recorded`, `stock_pair_count`, `parent_count`,
`has_parent`, `birth_record_count`) have no such test and can drift from their stated
derivation with **no invalidation whatsoever**.

Related: `is_evidence` is True iff `validated_against` is a **non-empty string**
(`probes.py:116`). A validation record is forged by typing a sentence; several probes
self-certify with `"|collection| adds no semantics"`.

### 3.5 A-NEW-5 — auto-detected order sensitivity (secondary)

`recorder.py:655` — `detected = detect_order_sensitivity(flow)`; if truthy the fixture is
stamped corroboration-only with no explicit flag at all. Since the flow author writes the
`when` sequence, shaping a flow so the detector fires yields the A-NEW-1 exclusion without
ever setting `corroboration_only`. Not separately executed; identical downstream mechanism
to A-NEW-1, which was confirmed live.

### 3.6 A-NEW-6 — half of `group_member`'s cited authority is untestable, and silently recorded backwards

`probes.py` cites `GroupMembership.php`'s `lfd.timestamp <= :timestamp` in `group_member`'s
`validated_against`, and farmOS demonstrably enforces it (drush: a +1d assignment gives
`B_in_G3_now=false`, `B_in_G3_after=true`).

But `ImplementationAdapter.assign_to_group(asset, group)` takes **no time argument**, and
`ctkr/ctkr/oracle/steps.py:54-55` calls it **without `at`** — while the flowspec still
accepts and validates an `at` field. Recording `{action: assign_to_group, ref: A, group: G1,
at: "+86400"}` validated cleanly, 1/1 recorded, 0 validation issues, emitted log timestamp
`1784577051` (= now; the `+86400` is dropped), and distilled a fixture asserting
`group_member A G1 == True` — **the opposite of what farmOS answers for the scenario
written.**

So no port can ever be scored on the time gate (a port with no notion of effective time
scores 100% clean), and an author trying to cover it gets a silently wrong fixture instead
of a loud error or NO VERDICT. This is a *fresh instance of C1* in the recorder rather than
the adapter: a derived value presented as boundary-stated.

---

## 4. What was DELETED

A refactor that only adds is a patch with better manners. This one deleted, and the deletions
are the strongest part of it. Net `+1288 / −655` across 26 tracked files.

**Deleted capabilities (each was a pen the defendant held):**

- **`PortManifest.fixture_marks`** — gone from the schema entirely. `extra="forbid"` means a
  manifest that still carries it **does not load**. This is what kills C2/A1 by construction,
  not by guard. (`port_contract.py:132`, doc at `:22-30`)
- **`--marks`** — the external marks file flag is gone from `port-verify`.
  (`commands/port_verify.py:70-72`)
- **`--decisions`** — gone. A port author can no longer point the sanction resolver at a
  caller-supplied registry path. (`port_contract.py:194`)
- **The `unanswerable` assertion status** — removed as a single bucket and replaced by
  `NoVerdictCause` (`BRIDGE_DEAD`, `UNRUNNABLE`, …), so the *kinds* of silence are
  distinguished and all of them block `clean`. (`port_verify.py:72-76, 147-149`)
- **`ctkr/ctkr/oracle/data/farmos_core_fixtures.jsonl`** and
  **`farmos_hardening_fixtures.jsonl`** — deleted, replaced by sealed
  `data/core-pack/` and `data/hardening-pack/` directories. Loose unsealed fixture files no
  longer exist as a concept.

`port_contract.py` is net **−45 lines**; `commands/port_verify.py` net **−17**. Those two
files got smaller, which is the right signature.

**What was added that should not have been:** `ctkr/ctkr/commands/oracle_seal.py` (§3.2).
It is the one addition that hands a pen back.

---

## 5. Invariants — did they get built?

| Invariant | Status |
|---|---|
| **1. Every value declares its authority** | **Partial.** `authority`/`boundary`/`derived` vocabulary now appears in 10 of the oracle modules, `is_evidence` and `unvalidated_probes()` exist, and an unvalidated derivation short-circuits to NO VERDICT. But the declaration is **prose, not binding** (A-NEW-4): the derivation id hashes the sentence, so the code can silently diverge from its declared authority. Nine of ten derived probes have no conformance test. |
| **2. The defendant never holds a pen that touches the verdict** | **Enforced at the pack, defeated one layer up.** `fixture_marks`, `--marks`, `--decisions` are all gone — real, by construction. But the flow spec (A-NEW-1, A-NEW-5) and `oracle-seal` (A-NEW-2) are both authored by the port lane and both reach the verdict. |
| **3. Absence of an answer is never an answer** | **Achieved.** `NoVerdictCause`, `no_verdict` blocking `clean`, `scored_nothing`, declines-as-declaration-problems, and `BridgeSpec.timeout` now applied to **every read** (`port_adapter.py:152-158` — `self._lines.get(timeout=deadline)`, with a comment naming the old unbounded `readline()`). The judge no longer trusts the defendant to reply. This invariant is the cleanest of the three. |

---

## 6. C1–C6: closed, or survived in a new shape

| | Blocker | Status |
|---|---|---|
| **C1** | Judge's ground truth is our adapter, not farmOS | **CLOSED for `group_member`, SURVIVES IN A NEW SHAPE elsewhere.** The GO test proves the inversion is gone and that farmOS is the authority. But the fix is pinned by two hand-written tests on one probe; A-NEW-4 shows the *mechanism* meant to keep it pinned (`derivation_id`) cannot detect its own regression, and A-NEW-6 shows a second live C1 in the recorder (the dropped `at`). C1 is fixed as an instance, not as a class. |
| **C2** | Port self-marks its failing fixtures | **SURVIVES IN A NEW SHAPE — the same attack, one file upstream.** `fixture_marks` is deleted (by construction). `corroboration_only` on a flow reproduces the exact outcome through the honest recorder (A-NEW-1). |
| **C3** | Shipped packs carry no `evidence_class` | **CLOSED, and now the attack surface.** Packs now carry it and the recorder writes it. The v2 complaint ("inert on every shipped pack") is resolved; the field being live is precisely what A-NEW-1 exploits. |
| **C4** | Nothing binds a pack to its observations | **PARTIALLY CLOSED.** Pack seals exist, are verified at load, and defeat a naive subset (S3). But the seal binds *bytes, not meaning* (A-NEW-3), and `oracle-seal` lets the defendant re-issue it (A-NEW-2). Provenance is no longer decorative; it is not yet corroborative. |
| **C5** | Judge hangs forever on an unresponsive bridge | **CLOSED by construction.** `BridgeSpec.timeout` now applies to every read and collapses to NO VERDICT. |
| **C6** (A4/A5) | Decline-where-wrong; run a subset | **CLOSED for the mechanisms tested (A4 by guard, A5 by construction), REOPENED by A-NEW-2.** Declining now scores no better than answering wrongly; a subset fails the seal — *unless the subset is re-sealed with the shipped CLI*, in which case it reports 100.0% at EXIT=0. |

**Score: 2 closed by construction (C5, C3), 2 partially closed (C1, C4), 2 survived in a
new shape (C2, C6).**

The pattern, stated once: **every attack that lands is an attack on an artifact the port
lane authors, and every attack that fails is one where the shape of the score denies the
port a lever.** The refactor moved the boundary of "artifacts the port lane authors" one
step back. It did not eliminate the category.

---

## 7. Wave-1 recommendation

### **NO-GO. Wave size 0.**

I would not run a single wave-1 port on this pipeline today, because a port with the exact
defect wave 1 exists to catch — non-recursive group membership — can be made to exit 0 at
100% clean using two documented schema fields and one shipped command, with no forgery and
no code modification. A green verdict from this pipeline is not yet evidence.

That said, this is a **materially different NO-GO** from v2. The purpose was achieved: the
acceptance direction is upright, proven causally against farmOS's own service. Three of the
five deletions are permanent structural wins. The remaining work is bounded and specific.

### Minimum to reopen the wave

1. **Evidence class and scope must come from an artifact the port lane cannot write.**
   Derive `corroboration-only` from a repo-side registry keyed by fixture id, not from the
   flow file. **And** make a corroboration-only fixture that *contradicts* the port block
   `clean` — add the missing clause at `port_verify.py:249-264`. An excluded contradiction
   is still a contradiction. (Closes A-NEW-1, A-NEW-5.)
2. **Delete `oracle-seal`, or gate it behind the recorder.** Make `load_pack` require the
   seal to be present in `PACKS.jsonl` — `registered_seals()` must actually be *called*, and
   an unregisterable pack must be an **error**, not a silent skip. (Closes A-NEW-2, restores
   S3 to a real by-construction win.)
3. **Verify each expected value against the observation it cites**, not merely that the
   `obs_id` resolves. Re-derive, don't re-hash. (Closes A-NEW-3.)

### Should be fixed before wave 2, and cheap now

4. **Fold a hash of the adapter method's source into `derivation_id`**, or require a
   per-probe conformance test against the source's own authority. Today `is_evidence` is
   true iff someone typed a sentence. (Closes A-NEW-4; without it, C1 will regress
   invisibly.)
5. **Thread `at` through `assign_to_group`**, or make a flow that specifies `at` a hard
   validation error. Silently recording the opposite of what farmOS answers is worse than
   refusing. (Closes A-NEW-6.)

### After those five

Wave size **2–3**, chosen so that at least one port is deliberately built with a known
defect and must be *observed to fail*. Do not size a wave larger than the number of ports
for which you have an adversarial counterpart.

---

## 8. Provenance of this review

Three adversarial lenses ran. **One of them (the attack-replay lens) executed against a
stale worktree at `ba595a5` with no refactor present** and correctly reported that fact as
its headline finding — its ten replayed attacks therefore measure the *pre-refactor* code
and independently re-confirm the v2 verdict. Its results are used here only for §2.1
(the two by-construction wins, which are unchanged by the refactor and should be preserved)
and are otherwise superseded.

The GO-test lens and the fresh-adversary lens both ran against the **actual refactor**:
the fresh-adversary lens replayed the uncommitted diff into a scratch worktree via
`git diff HEAD` plus copies of the untracked files, and reverted it afterwards. Their
findings are the substance of this report and do not conflict with each other — the GO test
and A-NEW-1 are both true of the same tree.

**The refactor is uncommitted.** 39 modified/untracked paths in
`/Users/dukejones/work/WorldTree/MetaCoding`, verified unchanged by every lens. It should be
committed before any further round so that "the implementation exists" stops being a
question. The earlier "IMPLEMENTATION REPORT: Complete" was, at the time the replay lens
looked, not backed by anything on any branch.

### Artifacts

**In the repo** (the only file this review wrote):
- `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/results/trust-model-refactor-2026-07-20.md`

**Sandbox** (no production path written; all under
`/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/16b09ed7-6185-46f1-b167-14accfadbd96/scratchpad/`):
- `replay/` — pre-refactor attack replay: `port/bridge.py` (modes `broken|liar999|duck|hang`), `portF/`, `A1/`, `A6/`, `L9/`, `RA/`, `tampered.jsonl`, `subset.jsonl`, `allmarks.json`
- `advpack/`, `tgpack/`, `mutpack/`, `subset/`, `ports/`, `ctkrmut/`, `adv-flows.json`, `adv-timegate.json`, `oracle_probe.php`, `crosscheck.php`, `adapter_probe.py` — GO test
- `FRESH-c1flows.json`, `FRESH-c1corr/`, `FRESH-subset/`, `FRESH-forgeval/`, `FRESH-recorder/`, `fresh-base.json`, `refactor.patch` — fresh adversary

**Live oracle.** farmOS 4.x at `http://localhost:8095` was queried and written **only via
the normal recorder and drush entity creation** (roughly 8 `oracle-record` flows across all
lenses). Test assets and logs were left in place. The instance was **not** rebuilt and
**not** destroyed.

**No commits were made.** The caller reviews and commits.
