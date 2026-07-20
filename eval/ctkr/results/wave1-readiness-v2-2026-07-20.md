# Wave-1 Readiness — v2 (2026-07-20)

Supersedes `eval/ctkr/results/wave1-readiness-2026-07-20.md`. Blockers B1–B5 in that
document are **closed and independently re-confirmed** (see §3). This document opens a new
set, **C1–C6**, found by four independent adversarial lenses run today against the frozen
worktree and the live farmOS 4.x oracle at `http://localhost:8095`.

Adjudicator note on provenance: the four lenses ran in isolated worktrees frozen at
`bc80b19`. This verdict was written in the main tree at `e770601`
(`feat(MetaCoding-9h5.22): kernel staleness pin + in-flight decision emission`), and the
load-bearing code findings below were **re-confirmed against `e770601`**, i.e. against the
newer tree, not only the frozen one. Nothing was committed.

---

## 1. Verdict

# NO-GO for wave 1.

Not "go smaller". Not "go with care". **Zero features fan out** until C1 and C2 are fixed,
because the defect is not throughput, capacity, or agent discipline — it is that **the
mechanical judge currently awards a clean, exit-0, 100% green verdict to a port that is
provably wrong about farmOS, and flags the port that is provably right as a defect.**

The wave size I would risk today: **0.**
The wave size I would risk after the §5 fix list: **4 features, sequentially fanned in one
batch**, not 10–15. Rationale in §6.

This is the third NOT-READY. Unlike the first two, the pipeline is no longer the problem —
it works. Today a third, untouched feature (group membership) went from a hand-written JSON
flow pack to 11 executable, self-verifying fixtures and a judged port with **zero
per-feature Python, in ~8 minutes of wall clock**. That is real and it is the strongest
result of the day. It is also exactly why this is a NO-GO: the pipeline is now frictionless
enough to manufacture 10–15 confidently-wrong ports, each carrying a 100% green
certificate, faster than anyone can audit them. **The failure mode is not that wave 1 jams.
It is that wave 1 succeeds loudly.**

---

## 2. Blocker-severity findings, in full

Six blockers across four lenses. The lenses did not contradict each other; they attacked
different layers and each found the layer below it unsound. Adjudication of the one
apparent tension is in §2.7.

### C1 — The judge's ground truth is the ctkr adapter, not farmOS
*(lens: wave-scale-mechanics; corroborated by decision-evidence-coherence)*

**Claim.** For any assertion farmOS does not expose at the JSON:API boundary, the
"observation" is a hand-written adapter belief re-labelled as evidence. A port that
**matches farmOS** is scored as a failure; a port that **diverges from farmOS** scores 100%.
Neither self-verification nor independent re-verification can detect this, because both
legs re-run the same adapter code.

**Proof.**
- `group_member` is not a value farmOS delivers. A live `GET /api/asset/animal` (HTTP 200)
  shows attributes `drupal_internal__id, name, archived, flag, id_tag, inventory, geometry,
  is_location, is_fixed, birthdate, is_sterile, nickname, sex` and **no `group`
  relationship**. The answer is computed entirely in
  `ctkr/ctkr/oracle/farmos_adapter.py:365 group_member()` — a hand-written query
  `filter[is_group_assignment]=1&filter[asset.id]=…&filter[status]=done&sort=-timestamp&page[limit]=1`,
  whose own comment asserts it implements "farmOS's group-membership semantics".
  *(Re-read and confirmed at `e770601`.)*
- farmOS's own authority is
  `/opt/drupal/web/profiles/farm/modules/asset/group/src/GroupMembership.php`, executed
  against the same live instance via `drush php:eval`:
  - **Transitivity.** Recorded fixture says `group_member(A, G2) == false` for A-in-G1-in-G2.
    farmOS: `getGroupMembers(G2, recurse=TRUE) = [315:Inner Flock, 314:Ewe Yarrow]`;
    `recurse=FALSE = [315:Inner Flock]`; "A in recursive members of G2 ? **TRUE**".
    `$recurse = TRUE` is the **default** in the signature.
  - **Future effective time.** For an `is_group_assignment` activity log dated `now+864000s`:
    `ADAPTER group_member(A,G) = True` vs `FARMOS hasGroup(A) = FALSE`, `getGroup(A) = []`,
    `getGroupMembers(G) = []`. The PHP gates on `lfd.timestamp <= :timestamp`; the adapter
    query has no such filter (confirmed above — lines 370–374 contain no time predicate).
- Both wrong fixtures **validated clean and self-verified 100%**
  (`ctkr oracle-verify g3-observe/fixtures.jsonl --adapter farmos` → 11/11 = 100.0%).
- Two ports differing **only** in `group_member`:
  - Port A (non-transitive LWW, kernel-conformant, **proven wrong vs farmOS**):
    `passed 21 / failed 0 / coverage 21/21 = 100.0% / reproduced 21/21 = 100.0%`.
  - Port B (recursive, **matches farmOS**):
    `passed 20 / failed 1 / reproduced 20/21 = 95.2% / NOT A CLEAN PASS: 1 value failure(s)`,
    `[FAIL] group_member(A) expected == False, got True — undeclared mismatch`.

**Why this is the decisive blocker.** Every other guarantee in the pipeline — the
observe-don't-author enforcement, the smuggling rejections, the byte-identical re-record
stability, the 100% re-verification — is a guarantee that the recorded value faithfully
reflects **the adapter**. Where the adapter is the author of the semantics, "observation"
is authorship with extra steps, and the whole evidence chain certifies a fiction. The
adapter's fidelity is not currently distinguished, in any artifact, from farmOS's.

### C2 — A port can launder its own failures to exit-0 / 100% via its own manifest
*(lens: judge-honesty-under-attack)*

**Claim.** `fixture_marks` written into the **port's own** `port.manifest.json` exclude
fixtures from the score with no resolvable warrant. Divergences require a `decision_id` and
block `clean`; marks require only free text and do **not** block `clean`. The earlier
hardening covered only the external `--marks` path.

**Proof.** Same deliberately-broken port. Baseline:
`passed 25 / failed 5 / reproduced 25/30 = 83.3% / EXIT=1`. After adding 5
`corroboration_only` marks with a plausible order-sensitivity reason to the port's own
manifest: `scored 18 (12 excluded) / failed 0 / reproduced 18/18 = 100.0%`, `--json
clean=true`, `needs_review=[]`, `declaration_problems=[]`, `marks_source=""`, **EXIT=0**.
The five FAILs still print in the detail body and are counted nowhere — the exit code
contradicts the transcript.

**Confirmed at `e770601`:** `ctkr/ctkr/oracle/port_verify.py:540`
`for m in (*manifest.fixture_marks, *extra_marks):` — port-authored and external marks are
merged into the same dict with equal authority. The one real defence is that a
**pack-carried** `evidence_class == "corroboration-only"` mark cannot be re-admitted
(lines 529–545). That defence is correct and well-written. It is also **inert on every
shipped pack**, because of C3.

### C3 — The shipped packs carry no `evidence_class`, so the only unforgeable mark is absent
*(lens: evidence-integrity; interacts with C2)*

**Claim.** The w0a/w0b packs predate in-pack order-sensitivity stamping. The default
`port-verify` invocation therefore scores the fixture the team already ruled must never
score, and protection depends on remembering an optional `--marks` flag — a per-agent
discipline that will not survive a 10–15 agent fan-out.

**Proof.**
- `port-verify w0a-observe/fixtures.jsonl --port w0a-build/build` →
  `fixtures: 12 (2 could not run, 0 corroboration-only) … scored: 17 … reproduced 17/17`.
- Same command `+ --marks w0a-fixture-marks.json` →
  `1 corroboration-only … scored: 16 … reproduced 16/16`.
- **Re-confirmed at `e770601`:**
  `jq -r '.provenance.evidence_class // "NONE"' eval/ctkr/port_runs/wave0-pilot/w0a-observe/fixtures.jsonl`
  → `12 NONE`. Not one fixture carries the field.
- A fresh re-record of the *identical* `w0a-flows.json` stamps `evidence_class="scoring"` on
  11 and `corroboration-only` on `d9778c65` ("Three adjustments sharing one effective
  time") with the tie-break reason inline, and produces **byte-identical `fixture_id`s and
  `then` values** for all 12.

The mechanism works; the artifact is stale. Fix is one re-record command. But until it runs,
C2's only real defence is switched off on the exact packs wave 1 would be judged against.

### C4 — No integrity check binds a pack to its observations, or a port to its pack
*(lenses: evidence-integrity + judge-honesty-under-attack, independently)*

**Claim.** `fixture_id` **is** a blake3 content hash and `content_id()` already recomputes
it — the loader and the judge simply never compare them. `observation_refs` are never
resolved. A builder with write access can edit expected values to match their port.
Separately, the **pack path is an argument supplied by the party being judged**, and
`coverage` is computed against whatever pack was passed, so 100% coverage is
self-referential.

**Proof.**
- Forged fixture (w0a `68049916`, `then[0].value` 3.0 → 999.0, `fixture_id` and provenance
  untouched): `oracle-validate` → "validated 1 fixture(s): 0 error(s), 0 leak(s) — all
  fixtures valid + storage-free." `port-verify` → judged it, scored it, "1 value
  failure(s)". Only `oracle-verify` against the **live oracle** caught it:
  `expected == 999.0, got 3.0`.
- In-process hash check: stored `fixture_id 68049916222d43746bb0ee0f386cf8ed` vs
  `content_id() 3abd3fd39b8ee40f028dc66a4d91b6ab` — **MISMATCH, undetected**; the pristine
  pack recomputes MATCH.
- **Confirmed at `e770601`:** `ctkr/ctkr/oracle/fixtures.py:200 load_fixtures()` does
  `model_validate_json` only; `content_id()`/`with_id()` are called on **write**, never on
  read. No reference to `observation_refs` in `fixtures.py`, `port_verify.py` or `runner.py`.
- Self-selected pack: `sed -n '4,7p'` of the same pack (the fixtures the broken port happens
  to satisfy) → `fixtures 4, coverage 10/10 = 100.0%, reproduced 10/10 = 100.0%, EXIT=0,
  clean`. `grep` over `eval/ scripts/ src/` shows **no automated `port-verify` invocation** —
  every invocation is hand/agent-composed, so the judged party chooses the pack path, the
  `--port` dir, `--marks` and `--decisions`.

### C5 — The judge hangs forever on an unresponsive bridge
*(lens: judge-honesty-under-attack)*

**Claim.** `PortBridge.call()` reads with `proc.stdout.readline()` and **no timeout**;
`BridgeSpec.timeout` is used only in `proc.wait()` at shutdown. A bridge that accepts a
request and never answers hangs the judge indefinitely.

**Proof.** Bridge answers `describe`, then `sleep(100000)`; manifest `bridge.timeout: 5.0`.
`timeout 45 uv run python -m ctkr port-verify …` → **exit 124**. A prior run of the same
bridge consumed the full 120s tool timeout (exit 143). No verdict, ever.
**Confirmed at `e770601`:** `ctkr/ctkr/oracle/port_adapter.py:121` `line = proc.stdout.readline()`,
with no read deadline anywhere in `call()`.

At 10–15 way fan-out this is an agent that **never reports a verdict** rather than one that
reports a failure — the worst possible outcome for an orchestrator waiting on N results.

### C6 — A bound kernel decision is stated as OBSERVED and is not
*(lens: decision-evidence-coherence)*

**Claim.** `src/kernel/status.ts` labels three location rows
`// ---- location: source-faithful (observation agrees with the original pick) ----`
(`currentLocation` / `assetsAtLocation` / `currentGeometry` = require-confirmed). **No
observation of farmOS location semantics exists anywhere in the repo.**

**Proof.** All ten `asset-location-movement` fixtures in
`eval/ctkr/port_runs/kernel-9h5.24/build/inputs/FIXTURES_LOCATION.jsonl` carry
`provenance: null` and zero `observation_refs`
(**re-confirmed at `e770601`:** `jq -r '.provenance // "NULL"' …` → `10 NULL`), and the
current schema **rejects every row** (`uv run python -m ctkr oracle-validate` →
"provenance Field required", plus legacy keys `when.assets / when.locations / when.t /
then.location` all `extra_forbidden`). Contrast: the same `jq` over
`farmos_hardening_fixtures.jsonl` → all 10 rows `farmOS 4.x` with 10–18 refs.

This is exactly the failure mode the v1.3 re-bind says it eliminated ("each row cites what
decided it: OBSERVED, or chosen") — the citation is fiction on 3 of the 13 `STATUS_CONTRACT`
rows, in the one file whose entire purpose is to say what decided each gate.

**Mitigating, and it matters:** the *decisions* are correct. Live probes today confirm
pending-movement-is-inert (`[]` then `[L2]`), multi-location
(`GEOMETRYCOLLECTION(POINT(1 1),POINT(2 2))`), future-dated (current = past location), and
fixed-asset (`[]` + `POINT (9 9)`). The remediation is **documentary plus one OBSERVE pass**,
not a redesign.

### 2.7 — Adjudication where the lenses could be read as disagreeing

Only one tension exists, and it is apparent rather than real.

**evidence-integrity** concluded the recording discipline is sound: all 23 fixtures
re-verify 100% hours later, all 22 comparable fixtures re-record byte-identically, and 4/4
value-smuggling attacks are rejected by name before any HTTP call. **wave-scale-mechanics**
concluded the recorded values can be flatly wrong about farmOS.

These are both true and they are about different things. Evidence-integrity measured
**faithfulness to the adapter** and found it excellent. Wave-scale measured **the adapter's
faithfulness to farmOS** and found it, for one probe, false in two independent ways.
I adjudicate in favour of wave-scale on the question of readiness: a perfect chain of
custody on a value the source system does not hold is not evidence. But
evidence-integrity's result is not weakened — it establishes that once the adapter is
correct or its unfaithful probes are quarantined, the recorded packs will be trustworthy.
**The fix is scoped to the adapter boundary, not to the recording machinery.**

No averaging was performed. All four lenses returned `ready: false` at `confidence: high`.

---

## 3. Genuinely proven vs. built-and-untested

**PROVEN — a recorded artifact exists and was re-measured today by a party that did not
build it:**

| Claim | Measurement |
|---|---|
| 23 recorded fixtures re-verify against the live oracle hours after recording | `oracle-verify`: w0a 12/12, w0b 11/11, order-sensitive 1/1, refusal 1/1 — **100.0% each** |
| Recorded values are reproducible, not lucky | Re-record of the same flow packs: **22/22 comparable fixtures identical in `fixture_id` and every `then` value.** Not one drifted |
| Observe-don't-author is *enforced*, not merely intended | 4/4 hand-authored-value smuggling attacks (`probes[].value`, `probes[].expected`, flow-level `then`, relative-time+instant-probe) rejected **by name, before any HTTP call**. FlowSpec has no field anywhere that can hold an expected value |
| The refusal path works | farmOS's 422 on a second birth log records as a fixture that self-verifies 1/1 |
| Zero per-feature Python is real | A third, untouched feature: one hand-written 231-line JSON pack → `flows recorded 11/11 / fixtures distilled 11 / observations logged 75 / validation issues 0` in **8.3s**, self-verify 11/11 in 7.4s, **no code changes** |
| The oracle is not the throughput ceiling (MetaCoding-d6j downgraded) | 12 concurrent recorders with `--preflight-timeout 90`: **12/12 ok in 19.6s** vs 100s serial (~5×). Canonical value signatures of all 13 runs hash to **one bucket** (`md5 -q` → `13 1655442753a616dfddf1ee9489fe2167`), per-run diffs vs solo baseline empty — **no data cross-talk** |
| Declared gaps are counted as gaps, never as passes | w0a: coverage 17/30, 13 unanswerable → "NOT A CLEAN PASS" (matches MetaCoding-ol3 exactly) |
| Provenance links resolve | All 126 `observation_refs` in w0a-observe resolve to obs_ids present in `observations.jsonl` |
| The suite is green | `uv run pytest -q` in `ctkr` → all pass, 1 skipped |
| Glossary cost estimate (MetaCoding-yph) is accurate | Undeclared term fails loudly at load; blast radius of `stock_pair_count` = 8 source + 2 test + docs + per-build manifests ≈ 10 files, **7 of them globally shared** |

**BUILT BUT NOT PROVEN — shipped today, and the first adversary through the door broke it:**

- **`ctkr port-verify` as an *adversarial* judge.** It is a correct *mechanical* judge: given
  an honest manifest and an honest pack it caught a deliberately-planted semantic bug
  (`passed 25 / failed 5 / 83.3% / EXIT=1`). Every one of six attacks then drove that same
  broken port to green or near-green (C2, C4, plus the HIGHs in §4). The three honesty rules
  are real and well-designed; two of the three have an unguarded flank.
- **The order-sensitivity detector.** Works on fresh records; **absent from every shipped
  pack** (C3).
- **The non-reproducibility guard.** Catches relative-time + instant-probe. Does **not**
  catch an absolute instant near the recording moment — demonstrated: a flow with
  `at = 2026-07-20T18:38:16Z` recorded at 18:36:58 was stamped `evidence_class: "scoring"`,
  self-verified PASS at 18:37:16 (`stock_on_hand == 0.0`), and **failed permanently at
  18:38:46** (`expected == 0.0, got 5.0`). This is the exact class that produced w0b's 63.6%
  incident.
- **The kernel's headline "27 fixtures, all green".** 10 of those 27 are the unprovenanced
  location fixtures (C6) — **37% synthetic, nowhere disclosed**. `grep` for
  `unobserved|no provenance|hand-authored|synthetic` across `shared-kernel.md` and
  `shared-kernel-v1-2026-07-20.md` returns nothing.
- **The v1.3 re-bind's completeness.** It correctly re-bound three falsified decisions. A
  **fourth** was falsified today (`membership = LWW-register on group_assigned, CONFIRMED →
  bound`, `shared-kernel.md:310`) in one untouched feature in under an hour — farmOS
  membership is transitive by default and inert for not-yet-effective assignments. This is
  the feature `src/kernel/lww.ts` names as its motivating example. The re-bind protocol is
  sound; the claim that the bindings are *now settled* is not.

---

## 4. High/medium risks a GO would accept (non-blocking, but must be written down)

1. **Per-call `unanswerable` is an uncapped, port-controlled escape hatch.** A bridge that
   declines exactly the inputs it would get wrong: `answered 24, UNANSWERABLE 6, failed 0,
   reproduced 24/24 = 100.0%, EXIT=3` — versus `5 proven-wrong values, EXIT=1` when it does
   not decline. The defendant chooses whether its own refusal is scored as a gap
   (`unanswerable`) or a failure (`unsupported`). Nothing flags "declared this probe, then
   declined 6/30 of its calls".
2. **`decision_id` sanction is existence-only.** Five stock-arithmetic divergences citing
   `decision_id: "birth-uniqueness"` (a real kernel decision *about birth logs*) were all
   accepted: `diverged 5 / failed 0 / reproduced 25/25 = 100.0%`, exit downgraded 1→3. Worse,
   `--decisions` accepts an arbitrary path, so a port author can point the resolver at a
   registry it wrote itself.
3. **Shared-oracle default fails a wave-1-sized fan-out and misdirects the remedy.** Sweep of
   concurrent `oracle-record`: N=2 → 2/2; N=4 → 4/4; **N=8 → 5/8; N=12 → 6/12**, every failure
   the 5s default `--preflight-timeout` on the OAuth token. The message reads `ORACLE DOWN …
   Bring it up with ctkr/ctkr/oracle/bring-up.sh` — **an agent following the printed remedy
   would destroy the oracle its 14 siblings are sharing.** Confirmed tunable: N=12 with
   `--preflight-timeout 90` → 12/12 in 19.6s.
4. **The flow DSL cannot reach the falsifying cases for new features.**
   `ctkr/ctkr/oracle/steps.py:54` — `assign_to_group(ref, group)` takes no `at` and no
   `status`; the adapter hardcodes `"status": "done"` and mints its own timestamp. The two
   case classes that already falsified inventory (not-yet-effective, pending) are
   **inexpressible** for group membership without the ~10-file glossary change. The adapter
   self-documents shaping the observation ("a strictly increasing timestamp per adapter
   instance so latest-wins is well-defined … and the reassignment fixture reproduces
   deterministically on self-verify") while farmOS tie-breaks on
   `lfd2.timestamp = lfd.timestamp AND lfd2.id > lfd.id`.
5. **An order-sensitive fixture of the w0a-2 class survives unflagged in the kernel build's
   inputs.** `43a074ca` asserts `is_at_location(cow, B) == true`; live probes show
   A-then-B → `[B]`, B-then-A → `[A]` — a pure function of insertion order, i.e. farmOS
   entity-id order, which kernel element 2 forbids a port from reproducing. Detection exists
   only in the FlowSpec path; this legacy pack never passes through it. The schema rejection
   quarantines it **accidentally**, and it is still shipped as build input that a wave-1
   builder reads.
6. **`movement-as-log` divergence is counted as a PASS.** `crossProbes.ts:64` registers CP2
   ("movement NOT counted as a log") as a *scoring* cross-probe whose own basis line says
   "movement-as-log is a builder design choice". Live farmOS: `logCount('activity') == 2` for
   an asset with only movement logs. This is honesty rule #2 — which `port-verify` enforces
   and the cross-probe harness that produced the kernel's published score does not.
7. **Response correlation is opt-out by the defendant.** `PortBridge.call` accepts any
   response whose id is `None` (`if resp.get("id") not in (None, req["id"])`). A bridge that
   omits `id` can answer out of order, including replaying a prior fixture's correct answer.
8. **The recorder's remedy text misdiagnoses a semantic refusal** as a missing farmOS surface
   ("enable it with `docker exec farmos-oracle-www drush en farm_birth -y`") three lines
   before the correct advice. Same destroy-the-shared-oracle hazard as (3). The surrounding
   behaviour is correct and should be credited: no fixture fabricated, flow excluded,
   reported loudly.
9. **No INTERRUPT protocol (MetaCoding-9h5.22, in flight elsewhere).** `grep` for
   `INTERRUPT|interrupt` across `docs/`, `ctkr/ctkr/`, `src/` (minus `KeyboardInterrupt`)
   returns **0 hits** in the frozen tree. Combined with the fourth falsified binding found in
   one hour on one feature, this is the operative wave risk: an agent that discovers a needed
   kernel change mid-wave has no channel to surface it, and 14 siblings roll forward on the
   stale binding. `e770601` lands the kernel staleness pin + in-flight decision emission —
   half of the answer; the agent-side interrupt is still unbuilt and untested at scale.
10. **Glossary merge hotspot.** ~10 files per new term, 7 globally shared. With 10–15 parallel
    agents this is a guaranteed conflict on the exact files that define correctness, with no
    protocol to serialize or announce the change.

Cost is not a risk here. The whole third-feature walk cost ~8 minutes wall clock and under
20s of machine time per stage; a 15-feature wave is an estimated $50–100 of model time. The
15× premature-go cost is not dollars — it is **15 confidently-wrong ports with green
certificates**, and the credibility of every green verdict issued afterwards.

---

## 5. Shortest path to GO, ordered

Fixes are ordered by *what unblocks the next one*, and each is stated with its acceptance
test. F1–F4 are the gate. F5–F7 are required before the size grows past 4.

**F1. Bind the judge to the pack. (~1h)**
Verify `fixture_id == content_id()` at load in `fixtures.py:load_fixtures`, and resolve
`observation_refs` against the pack's `observations.jsonl`. Fail loudly on mismatch.
*Accept:* the forged-999.0 pack is rejected by `oracle-validate` **and** by `port-verify`,
not only by `oracle-verify`.

**F2. Take the marks pen away from the defendant. (~1h)**
`fixture_marks` in a port's own manifest must not silently exclude from the score. Either
require the same resolvable warrant as a divergence, or — better — make the **pack** the sole
authority for `corroboration_only` (the code at `port_verify.py:529` already prefers the
pack; just stop merging port-authored marks into the same dict). Also: any excluded fixture
must block `clean` and must appear in the summary counts, never only in the detail body.
*Accept:* the A1 attack reproduces `failed 5 / EXIT=1`, not `EXIT=0 / clean=true`.

**F3. Re-record w0a and w0b so the packs carry `evidence_class`. (~10 min)**
One command each. Verified today to produce byte-identical `fixture_id`s and values, so this
is zero-risk. Without it F2's pack-authority defence is inert on the only packs that exist.
*Accept:* `jq '.provenance.evidence_class' w0a-observe/fixtures.jsonl` returns no `NONE`, and
default `port-verify` (no `--marks`) reports `1 corroboration-only excluded`.

**F4. Deadline every bridge read. (~30 min)**
Apply `BridgeSpec.timeout` to `proc.stdout.readline()` in `port_adapter.py:121`; on expiry,
kill the child and emit a `BridgeError` verdict. Also make `id` correlation mandatory
(reject `id: None`).
*Accept:* the sleeping bridge yields a non-zero **verdict** within `timeout + ε`, not exit 124.

**F5. Separate adapter-authored answers from source-observed ones. (~half day — the real work)**
This is C1 and it is the reason the wave is 4 and not 15. Every glossary probe must declare
its **fidelity class**: `boundary` (the value is read directly off farmOS's HTTP surface) vs
`derived` (computed by adapter logic). `derived` probes must be non-scoring by default until
each is validated against farmOS's own authority (drush/PHP service, or a documented farmOS
behaviour). Start with `group_member` — fix `recurse` and add the `timestamp <= now` gate to
match `GroupMembership.php` — then audit the remaining probes for the same shape.
*Accept:* Port B (matching farmOS) passes and Port A (diverging) fails, i.e. the C1 result
inverts. Until then no feature whose assertions are `derived` may enter a wave.

**F6. Close the honesty flanks. (~2h)**
(a) Cap and surface `unanswerable`: a port that declared a probe and then declines >0 calls
must be reported as a declaration problem with the count. (b) `decision_id` must be
**topically** bound — require the decision to name the probe/assertion it sanctions, and pin
`--decisions` to the repo registry rather than an arbitrary path.

**F7. Kill the destroy-the-shared-oracle remedies, and raise the default. (~30 min)**
Default `--preflight-timeout` to 90s (measured sufficient at N=12). Rewrite the two remedy
strings: contention must not read `ORACLE DOWN … bring-up.sh`, and a 422 semantic refusal
must lead with `expect_refusal`, not `drush en`. Add an explicit wave-1 standing order: **no
agent runs `bring-up.sh` or any `docker`/`drush` command against the shared oracle.**

**Then, and only then, re-run the falsification test that produced this NO-GO:** pick a
fourth untouched feature, walk it end to end, and build two ports that differ only where the
source system is authoritative. GO requires the judge to rank them correctly.

**Also required before the wave, not blocking the fixes:**
- Disclose the 37% synthetic base in `shared-kernel-v1-2026-07-20.md` and correct the
  "observation agrees with the original pick" comment in `src/kernel/status.ts`, then run one
  OBSERVE pass to replace `FIXTURES_LOCATION.jsonl` with provenanced fixtures. Four of its
  ten values were hand-checked against the live oracle today and all four agree, so this is
  documentary work, not a redesign.
- Re-bind `membership` in `shared-kernel.md:310` on today's evidence (transitivity default;
  effective-time gating), and land MetaCoding-9h5.22's agent-side INTERRUPT.
- Quarantine or re-record `43a074ca` and remove it from build inputs.
- Move CP2 from scoring to sanctioned-divergence in `crossProbes.ts`.

---

## 6. What the first wave should be, once GO is reached

**Size 4, not 10–15.** The measured constraints justify this precisely:

- The oracle supports 12-way concurrency cleanly at `--preflight-timeout 90` (12/12, 19.6s,
  no cross-talk), so **capacity is not the limit**.
- The limit is the **glossary hotspot**: 7 globally shared files per new term, with
  10–15 agents editing them concurrently and no interrupt protocol to serialize. Four agents
  is a merge surface a human can referee.
- The second limit is **audit bandwidth**: today, one lens found a falsified kernel binding
  in one untouched feature in under an hour. At four features that audit is affordable. At
  fifteen it is not, and the green certificates would go unchallenged — which is the exact
  15× cost.

**Feature selection rule:** all four must have assertions that are `boundary`-class under F5
(read directly off farmOS's HTTP surface), and must require **no new glossary term**. Prefer
features whose flow shapes already exist in `steps.py`. Do **not** put group membership in
wave 1 — it needs `at`/`status` on `assign_to_group` (§4.4) and is the feature with the
freshly falsified binding; it belongs in wave 2 as the first test of the interrupt protocol.

**Stop the wave mid-flight if any of these occur:**

1. **Any agent reports a 100% clean pass on its first judged port.** Every honest port so far
   has had declared gaps (w0a: 17/30). A first-try perfect green is the C1/C2 signature and
   must be treated as a defect report, not a success.
2. **Any agent edits a shared glossary file.** Halt, serialize, and broadcast — that is the
   merge hotspot and the stale-binding vector at once.
3. **Any agent runs `bring-up.sh`, `docker`, or `drush` against the shared oracle**, or any
   `ORACLE DOWN` message appears. Halt and check the oracle before anything else.
4. **Any agent surfaces a needed shared-kernel change.** Until 9h5.22's interrupt is proven
   at scale, this is a manual all-stop: every sibling is now potentially building on a stale
   binding, and there is no channel that tells them.
5. **A port-verify run fails to return a verdict** (timeout / no exit code). Until F4 is
   proven in anger, treat a missing verdict as a failing verdict.
6. **Two agents report contradictory values for the same glossary term.** One of them is the
   adapter, and C1 says you cannot tell which from inside the pipeline.

---

## Bottom line

The pipeline shipped an extraordinary amount today and most of it is real: the OBSERVE
bridge works, the recorded evidence is byte-reproducible and re-verifies at 100%, the
smuggling defences hold, the oracle is not the bottleneck, and a brand-new feature reaches a
judged port in eight minutes with no code. **Those are earned.**

But the judge that would certify 10–15 wave-1 ports currently certifies the wrong answer as
right, can be silenced by the party it judges, does not check the evidence it is handed, and
can be made to never answer at all. Four independent lenses, attacking four different layers,
each returned `ready: false` at high confidence. None of them had to reach.

**NO-GO.** Fix F1–F5, re-run the two-port falsification test, then go with four.

---
*Written 2026-07-20. Lenses ran at `bc80b19`; code findings re-confirmed at `e770601`.
Live oracle used, not rebuilt. Nothing committed by this review.*
