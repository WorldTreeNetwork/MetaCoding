# Wave-1 readiness verdict — the OBSERVE bridge closed, and what it found

> 2026-07-20 · supersedes the readiness call in
> `eval/ctkr/results/wave0-pilot-2026-07-20.md`. The pilot ran the production port
> recipe on two fresh farmOS features and stopped at stage 4 (OBSERVE) because the
> live oracle was down. The oracle is now up, the OBSERVE bridge exists, and both
> features have been observed. This report replaces the pilot's NOT-wave-ready call
> with a new one **based on evidence the pilot could not obtain**.
>
> The pilot's verdict was NOT-ready on three tooling blockers. Two of those three
> are now closed. This report is still **NOT ready** — but for entirely different,
> and more serious, reasons. Observation did not merely unblock the spine; it
> **contradicted three of the kernel's bound decisions on first contact.**

---

## Bottom line

- **The OBSERVE bridge is real.** 24 flows were authored across the two features
  directly from their mined candidates, compiled through the FlowSpec DSL, and
  recorded against live farmOS 4.x with **zero hand-written Python**. 23 recorded;
  23/23 self-verify at 100%; both packs pass `ctkr oracle-validate` with 0 errors
  and 0 storage leaks. I **independently re-verified both packs in a fresh session
  against the live oracle today: w0a 12/12, w0b 11/11, 100%.** The acceptance spine
  the entire 9h5 line rests on now exists and is reproducible.
- **The first real value claim for the w0a build is possible, and it is: NOT
  value-equivalent — but exact wherever it can speak.** 9/12 fixtures, and
  **17/17 of the assertions the build's own surface can answer reproduce live
  farmOS bit-for-bit**, including the three a plausible-reasoning port gets wrong
  (overdraw is not clamped: −3.0; reset boundary is timestamp-inclusive; units are
  never summed or converted). Every failure is a **missing surface** (no count
  probe, no status read-back, no correction verbs) plus **one real representational
  divergence** (an unadjusted holding reads `0.0` from farmOS and `[]` from the
  port). No wrong arithmetic anywhere.
- **Observation CONTRADICTED three bound kernel decisions.** Parentage-is-LWW
  (w0b-1, reversed only this morning) is flatly false against the oracle;
  nicknames-are-grow-only (w0b-2) is false — they are an ordered duplicate-preserving
  list with **wholesale replace**; and the w0a-2 tie-break fixture's observed value
  **encodes farmOS insertion-id order**, so it is not tie-break-agnostic and cannot
  score a kernel port that orders by HLC. A fourth finding is worse than a
  contradiction: kernel v1.2's blanket confirmed-only pending rule is **half right** —
  farmOS excludes pending from inventory and fully honours it for lineage and date
  of birth. These are surfaced here as decisions to RE-OPEN. **I resolved none of
  them.**
- **The pilot's three blockers: two closed, one reframed.** Kernel fold vocabulary
  (F4) shipped as v1.1 (`FoldReduce`/`GSet`/`GuardedFirstWrite`, commit 49c6d2f);
  oracle reliability (F1) closed by preflight + one-command bring-up (9h5.28);
  `propose-adapter`↔CM-registry coupling (F2) is bound (commit 6947364). What
  replaced them is a harder class of blocker: the kernel's decisions were never
  observation-tested, and there is still **no mechanical way to score a build
  against observed fixtures** — all three judgements this session were hand-written
  TypeScript harnesses in a sandbox.
- **VERDICT: NOT wave-1 ready.** Five blockers, §Verdict. The dominant one is not
  the bridge — it is that the JUDGE stage is still artisanal, and at 100+ features
  a hand-written harness per feature is the whole cost of the wave.

---

## 1. Is the OBSERVE bridge real?

**Yes, for the class of feature the pilot chose, and with named human-shaped holes.**

What ran with no hand-written Python:

| stage | w0a (inventory) | w0b (animal/birth) |
|---|---|---|
| candidates in | 50 mined (11 with domain content) | 13 mined (6 with domain content) |
| flows authored | **12** | **12** |
| loads via `flowspec_io.load_flows` | 12/12, 0 storage leaks, 0 smuggled values | 12/12, 0 leaks, 0 smuggled values |
| recorded against live farmOS | **12** | **11** (1 unrecordable, below) |
| self-verify at record time | 12/12 (100%) | 11/11 (100%) |
| **independent re-verify, fresh session, today** | **12/12 (100%)** | **11/11 (100%)** |

The separation the method depends on held: **a FlowSpec says what to DO and what to
PROBE; `record_flow()` filled every expected value from what farmOS actually
returned.** No expected value was authored anywhere in either pack, and the schema
has nowhere to put one.

**The independent re-verification matters more than the self-verification.** A pack
that self-verifies only proves the recorder is internally consistent. Re-running
both packs cold, in a new session, hours later, and getting 23/23 proves the
fixtures are **stable artifacts**, not a snapshot of one run's wall clock. That is
the property wave 1 actually needs, and it was not free — see the relative-`at`
defect below, which broke exactly this property and was caught only because a
self-verify was run twice.

### What still needs a human

1. **Flow authoring is an LLM stage, not a deterministic compile.** "Compiled from
   mined candidates" means an agent read 50 candidates, rejected 39 as content-free
   graph-lane templates, and distilled 5 of the remaining 11 into 12 flows. The
   selection judgement — *this candidate hides three separable non-obvious facts;
   that one is a Drupal revisioning idiom* — is real work and is not mechanized.
   It is cheap and it worked, but it is not a compiler.
2. **The DSL cannot express a large, named fraction of what was mined.** 13
   semantics across the two features were wanted and unreachable: no explicit
   as-of read; no probe naming *which* event won a tie; no multi-asset fan-out
   assertion; no quantity-level reads; no migration entry point; no way to clear a
   birth's mother (`steps.py:74` collapses `[]` to `None`, which the adapter reads
   as "leave unchanged"); no second parent (`record_birth` accepts a list, the
   adapter uses `parent_handles[0]`); no sterility; no animal-type read-back.
   Every one of those is a semantic the port will ship unobserved.
3. **A refused write destroys the run.** `record_session` aborts on the first
   `AdapterError`. `w0b-two-birth-records-one-animal` hit
   `POST /api/log/birth → 422 "…already has a birth log"` and killed the whole
   w0b recording; a human had to fork `w0b-flows-recordable.json` by hand to get
   11 fixtures out. The refusal **is** the observation — it is the sharpest
   evidence in the entire session — and the recorder throws it away.
4. **Relative `at` offsets silently produce non-reproducible fixtures.** w0b's
   first self-verify was 63.6%: every failure was `birth_date`, uniformly +24s —
   the gap between the record run and the verify run. Nine relative offsets had to
   be rewritten to absolute ISO instants by hand. Any probe returning a timestamp
   derived from a relative `at` is structurally unverifiable, and nothing in the
   DSL prevents it.
5. **The oracle needed a manual module install.** w0a uses the `equipment` asset
   bundle; the oracle had none (`POST /api/asset/equipment → 404`) until
   `drush en farm_equipment farm_inventory -y` was run by hand.
   `ctkr/ctkr/oracle/bring-up.sh` does not install `farm_equipment`, so w0a will
   not record on a fresh oracle.

**Assessment.** The bridge is real and its output is trustworthy. It is not yet
*unattended*. For an arbitrary new feature, expect: automated compile+record, plus
a human for candidate triage, plus a coin-flip on whether the feature's key
semantics fall inside the DSL's expressible set.

---

## 2. What observation did to the bound decisions

The kernel's decisions were bound from **source reading and Duke's elicitation**,
never from observation. This was the first time any of them met the oracle. Three
did not survive, and a fourth is half-wrong.

**These are surfaced for re-opening, with evidence. I have resolved none of them.**

### 2.1 w0b-1 (parent lineage = LWW, correction may overwrite parentage) — CONTRADICTED

Bound this morning, reversing the pilot's guarded-first-write, on the grounds that
correctability beats source fidelity. The oracle disagrees flatly.

`w0b-birth-correction-restates-mother`: birth names FIRSTMOTHER (child gains her);
`correct_birth` restates the mother to SECONDMOTHER. **The PATCH is accepted** —
`observations.jsonl` records
`PATCH /api/log/birth/ef947afc-… {relationships.mother → 945dbd16-…} → ok`. The
delivered state: `parent_count == 1`, `has_parent(CHILD, FIRSTMOTHER) == True`,
`has_parent(CHILD, SECONDMOTHER) == False`. The write succeeds and is **inert on
lineage**. The mechanism is corroborated by
`w0b-birth-mother-vetoed-by-existing-parent`: a child that already has a parent is
never given the birth mother at all — an existing parent is a hard veto on the
birth hook, so a correction can never take.

**Two asymmetries make this more than a simple reversal:**

- *Same verb, same log, opposite answers by field.*
  `w0b-birth-correction-restates-time` shows the corrected birth time **does**
  propagate: birth at 2026-07-10T12:00Z corrected to 2026-07-18T12:00Z delivers
  `birth_date == 2026-07-18T12:00:00+00:00`. The timestamp follows the correction;
  the mother does not. **`correct_birth` cannot be modelled by a single LWW rule.**
- *LWW is real, but lives in a different verb.*
  `w0b-parents-stated-directly-are-restated-wholesale`: `set_parents(FIRST)` then
  `set_parents(SECOND)` yields `parent_count == 1`, FIRST `False`, SECOND `True` —
  wholesale replace. Identical end-state shape to the birth path, opposite outcome.
  Whoever re-binds this must say **via which verb**, not "lineage is LWW".

### 2.2 w0b-2 (nicknames = grow-only ordered multiset / G-Set) — CONTRADICTED

Observed: `['Zephyr','Amber','Moss']` — order retained. `['Daisy','Daisy','Rosie']`
— **no dedup**, the repeated value survives round-trip (confirmed in both the raw
PATCH and the read-back). And `['Pebble','Slate']` then `['Flint']` delivers
`['Flint']` — **wholesale replace, not union.**

So: ordered ✓, multiset ✓, **grow-only ✗**. The kernel v1.1 `GSet` primitive was
shipped partly to serve this semantic and is the wrong shape for it; an ordered-list
LWW register is what the oracle implements. Re-open both the decision and the
primitive's justification.

### 2.3 w0a-2 (same-effective-time tie-break = HLC) — the DECISION stands, the FIXTURE does not

Duke confirmed the HLC tie-break in this morning's elicitation review, and nothing
observed challenges HLC as the right kernel rule. What observation established is
that **the fixture meant to corroborate it cannot score anything.**

`w0a-adjustments-sharing-one-effective-time`: three adjustments at one instant
(+3 kg, reset-to-4, −1 kg) created in that order. Observed `stock_on_hand == 3.0`
— exactly creation order (3 → reset 4 → 3). Reset-last gives 4.0; reset-first gives
6.0. **farmOS breaks the tie by insertion/entity id, and 3.0 is that id order's
fingerprint.**

Two judges independently permuted the identical event set against the build:
`abc→3, acb→4, bac→6, bca→6, cab→4, cba→7` — six orders, four distinct values. The
build "passes" this fixture with 3.0 **only because the harness appended in the
oracle's creation order and a single replica's HLC is monotone in append order.**
The pass carries no evidence. Under any other replica ordering it is a false
failure; under this one it is a false green.

**Decision to re-open: not HLC, but the scoring policy.** Any fixture whose value
is a function of source insertion order must be marked corroboration-only and
barred from the value score — and the fixture format currently has no way to say
so. This is a schema gap, not just a flow annotation.

### 2.4 Kernel v1.2's pending stance — HALF RIGHT (the sharpest new finding)

v1.2 binds `yieldTotal`/`logCount` to confirmed-only across the port, with
`pendingYieldTotal`/`pendingLogCount` surfacing the pending mass. farmOS is **not
uniform**:

| surface | pending log | farmOS | port's blanket rule |
|---|---|---|---|
| inventory `stock_on_hand` | pending +3 kg | **excluded** (2.0 from the done log only) | matches ✓ |
| inventory `adjustment_count` | pending +3 kg | **counted** (2) | would say 1 — sanctioned divergence |
| birth lineage | `status='pending'` | **fully effective** — `parent_count == 1`, `has_parent(MOTHER) == True` | would say no parent — **unsanctioned** |
| birth `birth_date` | `status='pending'` | **fully effective** — `2026-07-19T12:00:00+00:00` | would say absent — **unsanctioned** |

Pending is invisible to inventory and fully visible to lineage and date-of-birth.
The port's blanket confirmed-only rule therefore matches the oracle on inventory
and **diverges from it on birth in a direction v1.2 does not sanction**. Re-open:
the pending gate is per-projection, not global, and the STATUS_CONTRACT is the
right place for that — which is exactly the mechanism the w0a build bypassed
(§3).

### 2.5 Birth-uniqueness — the kernel rule has no oracle counterpart

Kernel-bound: two birth claims, earliest-HLC wins, loser demoted to an observation.
farmOS **refuses the second claim at write time** with a 422. There is no state in
which two birth claims coexist, therefore no converged value to observe, therefore
the kernel's resolution rule is **unobservable in principle against this source**.
That is a real semantic divergence (refuse-vs-resolve), not a pack defect, and it
is why 1 of 24 flows is unrecorded. It also means the CM "hard invariant" machinery
has, so far, zero oracle grounding.

---

## 3. Is the w0a build value-equivalent?

**No — but the shortfall is surface, not semantics, and that distinction is now
evidence-backed rather than asserted.** Three independent judges (value-equivalence,
divergence-honesty, prevention-gates) drove only the build's public adapter and
authored no expected value.

| | result |
|---|--:|
| fixtures passed | **9 / 12** |
| assertions passed (raw) | **24 / 30** |
| assertions the **port itself** answered | **17 / 23** — and 17/17 of those it can answer are **exact** |
| assertions no port surface exists for | **13** |

**Exact where it speaks.** Every `stock_on_hand` and `stock_pair_count` value
reproduces live farmOS bit-for-bit: 3.0, 0.0, 3.0, 2.0, 2.0, 3.0, 5.0/5.0,
8.0/1.0, −3.0, and pair counts 1/1/2/2/1/0. That includes the behaviours a naive
port gets wrong — **overdraw is not clamped** (farmOS carries −3.0; the build
returns −3.0), the **reset boundary is timestamp-inclusive** so a same-instant
increment is applied then overwritten, and **units never merge or convert** (kg 8.0
and lb 1.0 side by side after a lb-only reset). Stress cases beyond the fixtures
also held: a pending reset is inert; as-of cutoffs are correct either side of a
reset; the `(measure, units)` partition key uses a NUL separator so the
`('volume','fluid ounces')` / `('volume fluid','ounces')` collision could not be
forced.

**Notably, the build never invokes the v1.2 pending divergence as an excuse.**
`PORT_DECISIONS.md` claims no pending exemption anywhere, and the one place the
sanctioned divergence could have applied (`adjustment_count` on the pending
fixture) is unverifiable because the build ships no count surface. **No real bug is
hiding behind the pending label.**

**The three failures:**

1. **REAL — absent vs zero.** `w0a-a-holding-nobody-has-adjusted`: farmOS answers
   `stock_on_hand(weight, kilograms) == 0.0` for a pair with no rows; the build
   returns `[]`, so a consumer gets `undefined`. The observe run itself flagged
   that this probe cannot distinguish "no rows" from "a zero row"; the port lands
   on the other side of the ambiguity. Low severity, genuine non-equivalence,
   cheap to fix in the read model.
2. **CAPABILITY GAP — no `set_log_status`.** `w0a-confirming-a-pending-adjustment`
   is inexpressible (3 asserts). *Mitigation verified:* fed the post-mutation end
   state, the fold delivers exactly 7.0.
3. **CAPABILITY GAP — no `set_effective_time`.** `w0a-restating-when-an-adjustment-took-effect`
   inexpressible (2 asserts). *Mitigation verified:* delivers exactly 5.0.

Both verbs were explicitly out of scope in `BUILD_INSTRUCTIONS.md`. Structurally
they say something bigger: **the port models an immutable append-only log while
farmOS models mutable log entities.** Any fixture whose flow restates a prior log
is currently unrunnable. And these are field-level corrections — precisely the
`LwwRegister` shape the kernel already ships — so the one place a kernel primitive
was directly applicable is the one place the build implemented neither the verb
nor the primitive.

### The prevention gates are weaker than the build's own documentation implies

| gate | holds? | evidence |
|---|---|---|
| ids through `IdMinter` | **HOLD** | replica-scoped `R7~` in every handle; no id literal anywhere |
| no ordinal/entity-id ordering | **HOLD** | sole comparator `byOccurredThenHlc`; `.id` in no comparison |
| closed kind taxonomy | **PARTIAL** | envelope kind registered + frozen; but the behavioural sub-taxonomy `increment\|decrement\|reset` is unregistered with a **silent catch-all**: `+10` then kind `"restock"` value 4 returns **6**, not a throw. The registry is never consulted at read time; the `isLog` facet is written and never read |
| status via `STATUS_CONTRACT` | **FAIL** | the gate is a module-local constant `const INVENTORY_GATE = "require-confirmed"` in feature code; `gateFor()`/`admits()` never called; no inventory row in the contract. `status.ts`'s own doc forbids exactly this. The same fact is declared twice (`INVENTORY_ADJUSTMENT_SPEC.statusGate`) and can drift silently |
| folds through kernel primitives | **FAIL (excusable)** | `foldRunningBalance` fully hand-rolled — but `inputs/kernel/` is v1 and ships only `pickLatest`/`LwwRegister`; the v1.1 fold library was not in the inputs. Provenance excuses it; structure does not |

**The two gates that hold are the cheap structural ones. Both gates that guard
SEMANTIC drift are open.** Two further latent hazards: the projection filter has no
`kind ===` test, so the moment a second kind enters the same log any event carrying
`asset`/`kind`/`value` folds into stock; and result-row order is first-seen append
order (`"zz"` before `"aa"`), an observable output determined by append position —
the same class of hidden ordinal the ids gate forbids, and the build's own test
depends on it.

---

## 4. Measured cost and wall clock

| stage | metered spend | wall clock | notes |
|---|--:|--:|---|
| SCOPE + SURFACE + SEMANTICS + DECIDE (both features) | **$0.4166** | (pilot session) | gpt-5.6-terra $0.4034 + luna $0.0132, 16 calls; **$0.21/feature** |
| **COMPILE** (candidates → FlowSpec, both features) | **$0** metered | ~30 min | Claude-token agents, unmetered; 24 flows from 63 candidates |
| **OBSERVE** (record + self-verify, both features) | **$0** metered | ~10 min | deterministic HTTP to the live oracle; 23 fixtures, 201 observations |
| — of which rework | | ~5 min | one full w0b re-record after the relative-`at` defect |
| **JUDGE** (3 lenses on w0a) | **$0** metered | not separately measured | **3 hand-written TypeScript harnesses in a sandbox** — the unmeasured cost, and the large one |
| independent re-verify (this report) | $0 | ~3 min | 23/23 |

Observed window: rescue commit 15:11 → w0b fixtures 15:51:59. **~40 minutes of wall
clock took two features from mined candidates to independently-reproducible
fixtures**, including one full re-record. That part extrapolates well.

**What does not extrapolate is JUDGE.** Three judges each wrote a bespoke harness
to drive one build's adapter, resolve relative offsets, and map probe names to port
methods. There is no `ctkr port-verify <fixtures> <build>`. At 100+ features that
per-feature harness authoring is the dominant cost of the wave, and it is
unmeasured because it was never metered — which is itself the finding.

Budget discipline held: $0.42 total against a $3/feature abort and $6 total cap.

---

## 5. VERDICT — NOT wave-1 ready

The pilot's three blockers are largely closed: the fold library shipped (v1.1),
oracle reliability shipped (preflight + one-command bring-up, 9h5.28), and
`propose-adapter` now consumes the bound CM registry. The OBSERVE bridge — the
thing the pilot could not test at all — works, and works well enough that its
output survived independent re-verification.

**But the first observation run contradicted three bound kernel decisions, and the
JUDGE stage is still artisanal.** Fanning out 100+ builds now would mass-produce
ports against decisions the oracle has already falsified, and would need 100
hand-written scoring harnesses to find out. A premature go costs 15×; these are
exactly the failures that 15× would multiply.

### Blockers, in priority order

**B1 · Three bound decisions are falsified and must be re-opened before fan-out
(BLOCKER).** w0b-1 parentage-is-LWW (the PATCH succeeds and is inert), w0b-2
grow-only nicknames (wholesale replace, no dedup), and kernel v1.2's blanket
confirmed-only pending rule (right for inventory, wrong for birth). Plus the
w0a-2 fixture's non-agnostic value, and birth-uniqueness having no oracle
counterpart at all. **None of these are mine to resolve.** The structural lesson is
larger than any one of them: *every* kernel decision to date was bound from source
reading and elicitation, and the first three to meet an oracle lost. The remaining
bound decisions should be considered unvalidated until observed.

**B2 · No mechanical JUDGE (BLOCKER, and the largest cost driver).** There is no
tool that replays an observed fixture pack against a built port. Three judges wrote
three sandbox harnesses for one build. Wave 1 needs `ctkr port-verify` plus a
**probe-surface contract** binding the fixture vocabulary (`stock_on_hand`,
`adjustment_count`, `log_status`, `has_parent`, …) to required adapter methods —
without it, 13 of 30 assertions are unanswerable and the raw 24/30 overstates the
build (6-7 of those "passes" tested a judge's harness, not the port).

**B3 · The recorder destroys its most valuable evidence (HIGH).** `record_session`
aborts on the first `AdapterError`, so a write the source *refuses* — the sharpest
semantic signal available — kills the run instead of becoming a fixture. An
`expect_refusal` / observed-error step would have recorded w0b 12/12 and turned
the UniqueBirthLog constraint into an asset instead of a footnote.

**B4 · The fixture schema admits non-reproducible fixtures (HIGH).** Relative `at`
plus any timestamp-returning probe yields a fixture that cannot self-verify; it was
caught by luck and fixed by hand. Either forbid relative `at` in such flows or
teach the format a flow-relative expected value. Related and equally schema-level:
there is no way to mark a fixture **corroboration-only / order-sensitive**, which
w0a-2 needs to avoid scoring as a false green.

**B5 · The prevention gates that guard semantic drift are open (HIGH).** The status
gate is a feature-local constant rather than a `STATUS_CONTRACT` row — the exact
re-litigation `status.ts` exists to forbid, and doubly bad now that §2.4 shows the
pending gate must be per-projection. The behavioural sub-taxonomy is unregistered
with a silent catch-all decrement, and the projection is not kind-guarded. At 100+
builds these are the gates that decide whether ports diverge; shipping the wave
with them open forfeits the kernel's whole purpose.

**Also required, lower severity:** add `farm_equipment` to
`ctkr/ctkr/oracle/bring-up.sh` (w0a cannot record on a fresh oracle without it);
close the named DSL expressibility gaps (clear-a-mother, second parent, explicit
as-of, which-event-won, quantity reads); complete the w0a build's surface
(`adjustment_count` built to whatever the re-opened v1.2 rule becomes, a log-status
read, and the two restatement verbs) before any further conformance claim.

### What would make it ready

Re-bind the falsified decisions against observed evidence (Duke); ship
`ctkr port-verify` + a probe-surface contract; teach the recorder to record a
refusal; forbid or fix relative-`at` fixtures and add a corroboration-only flag;
close the two semantic prevention gates. None of these is large. The pilot's
verdict was "the gap is small, specific, and mostly tooling" — that is still true
of B2-B5. **B1 is not tooling, and B1 is the one that would have cost 15×.**

The bridge's real value this session was exactly this: it took one day of
observation to falsify three decisions that months of source reading and one
elicitation review had agreed on.

---

## Artifacts & paths

**In the repo (production, not a sandbox):**
- This report: `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/results/wave1-readiness-2026-07-20.md`
- Superseded: `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/results/wave0-pilot-2026-07-20.md`
- Flow packs: `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/port_runs/wave0-pilot/w0a-flows.json`,
  `…/w0b-flows.json`, `…/w0b-flows-recordable.json` (the pack that actually recorded —
  w0b minus the flow farmOS refuses to let exist)
- Observed fixtures + observations:
  `…/w0a-observe/{fixtures.jsonl,observations.jsonl}` (12 fixtures, 126 observations),
  `…/w0b-observe/{fixtures.jsonl,observations.jsonl}` (11 fixtures, 75 observations)
- Judged build: `…/w0a-build/build/`

**Sandbox (NOT in the repo, not reproducible artifacts):** the three judge harnesses
under `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/16b09ed7-6185-46f1-b167-14accfadbd96/scratchpad/`
(`judge.ts`, `probe.ts`, `oracle_harness.ts`, `stress.ts`, `stress2.ts`). Their
existence as one-off sandbox scripts *is* blocker B2.

**Live oracle:** farmOS 4.x @ `http://localhost:8095`, UP, used for recording and
for this report's independent re-verification. **Environment change made during the
run:** `docker exec farmos-oracle-www drush en farm_equipment farm_inventory -y`
(the `equipment` bundle did not exist; `POST /api/asset/equipment → 404`).
`ctkr/ctkr/oracle/bring-up.sh` was NOT edited and does not yet install
`farm_equipment`.

**Verification commands re-run for this report (both 100%):**
`ctkr oracle-verify eval/ctkr/port_runs/wave0-pilot/w0a-observe/fixtures.jsonl` → 12/12;
`… w0b-observe/fixtures.jsonl` → 11/11.

**Metered OpenAI spend for the stages that ran this session: $0.00** (COMPILE and
JUDGE ran on unmetered Claude tokens; OBSERVE is deterministic HTTP). Upstream
pilot spend was $0.4166 for both features.

No expected value was authored anywhere. No kernel decision was changed. Nothing
committed — the caller reviews and commits.
