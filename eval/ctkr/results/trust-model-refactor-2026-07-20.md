# Trust-model refactor — validation report

**Date:** 2026-07-20
**Commit under test:** `8a7f775` — *refactor: trust model — authority / no-pen / no-answer (VALIDATION PENDING)*
**Repo:** `/Users/dukejones/work/WorldTree/MetaCoding` (main checkout, branch `main`, clean before and after)
**Live oracle:** farmOS 4.x at `http://localhost:8095`, used read-only and for ordinary test-entity creation. `bring-up.sh`, `docker` and `drush` were never invoked destructively.
**Suites at this commit:** 626 python passed / 1 skipped, 484 TS.
**Supersedes:** the earlier draft at this path, which reviewed HEAD `ba595a5` + 39 uncommitted paths — i.e. a different tree from the one now committed. Its findings are retained where this round independently reproduced them; they are not carried forward on authority.

**Verdict: PARTIAL — the refactor achieved its stated purpose on the known case and failed to make that outcome robust. GO for Wave-1, but at reduced size and with three preconditions.**

---

## 0. For the record: the first adversarial round was void

The first attack round reported "the refactor does not exist." That report was accurate about the tree it saw and worthless as validation: the attackers ran in worktrees frozen at the pre-refactor commit while the implementer had been instructed not to commit. That was an orchestration error, not a finding.

**This document is the first real validation of these invariants against the committed refactor.** All three lenses below independently confirmed the tree before attacking:

- `git log --oneline -1` → `8a7f775`
- `ctkr/ctkr/oracle/probes.py` declares `authority: str = ""` (line 96), `BOUNDARY`/`DERIVED`, `is_evidence` (line 116), `validated_against`, `derivation_id`
- `ctkr/ctkr/oracle/data/core-pack/` contains `fixtures.jsonl`, `observations.jsonl`, `pack.seal.json`
- `ctkr/ctkr/oracle/pack.py` (sealed-pack module) and the `NO_VERDICT` lattice in `port_verify.py` are both present
- `FarmOSAdapter.group_member` at `farmos_adapter.py:414` walks the transitive closure with an effective-time gate

Every result below was produced by building and executing an attack, not by reading code and reasoning about it.

---

## 1. THE GO TEST — does the judge now rank a farmOS-matching port above an adapter-matching one?

### **YES. Decisively, and for the right reason.**

A minimal-pair experiment: two ports generated from one bridge template, `diff portA/bridge.ts portB/bridge.ts` returning **only the body of `resolveMember()`**. Nothing else differs — not manifest capabilities, not protocol, not storage model.

- **Port A** — farmOS-matching: transitive closure, effective-time gate, id tie-break
- **Port B** — adapter-matching (the pre-refactor semantics): direct membership only, latest-assignment-wins, no time gate

Judged against a sealed 7-flow / 14-assertion membership pack (`b0ecfdd3d9f8`) recorded against the live oracle:

| | Port A (matches farmOS) | Port B (matches old adapter) |
|---|---|---|
| passed | **14** | 10 |
| failed | **0** | **4** |
| NO VERDICT | 0 | 0 |
| diverged | 0 | 0 |
| coverage | 14/14 = 100.0% | 14/14 = 100.0% |
| **reproduced** | **14/14 = 100.0%** | **10/14 = 71.4%** |
| clean | **true** | false |
| **EXIT** | **0** | **1** |

The pre-refactor inversion — farmOS-matching port at 95.2% NOT-CLEAN, adapter-matching port at 100% clean — **is gone and reversed.** The farmOS-matching port scores strictly better on every axis: value score, clean flag, and exit code. Port B's four failures are exactly the four transitive assertions, each reported as `undeclared mismatch`, never silently absorbed.

**Ground truth came from farmOS's own authority, not from our adapter.** `/opt/drupal/web/profiles/farm/modules/asset/group/src/GroupMembership.php` was read inside the container, confirming `getGroupMembers(array $groups, bool $recurse = TRUE, $timestamp = NULL)`, the gate `lfd.timestamp <= :timestamp`, and the tie-break `lfd2.timestamp = lfd.timestamp AND lfd2.id > lfd.id`. That service was then executed directly via `drush php:eval` on freshly created test entities, reproducing all seven recorded scenarios independently of ctkr: **14/14 recorded assertions matched farmOS's own `getGroupMembers` exactly.** The pack is not merely self-consistent with our adapter — it is independently correct.

A second lens confirmed the same headline through the repo's own `wave1-c1` pack: `ctkr oracle-verify wave1-c1 pack --adapter farmos` → 3/3 PASS, EXIT=0.

### Three caveats that qualify the pass

**1.1 — The repo's own shipped packs cannot discriminate the two ports at all.**
`data/core-pack` carries exactly one `group_member` assertion (direct, A-in-G, true); `data/hardening-pack` carries two (reassignment latest-wins). **None is nested.** Measured: on core-pack both ports score `reproduced 1/1 = 100.0%`; on hardening-pack both score `2/2 = 100.0%`. Byte-for-byte identical verdicts. The discriminating power in the GO test came entirely from a pack authored for this validation, not from anything the refactor shipped. The corrected derivation lives in `probes.py`, but **no recorded evidence in the repo would catch its regression.**

**1.2 — The effective-time gate, half of the headline fix, is unexercised by any pack.**
`FarmOSAdapter.assign_to_group` hardcodes `timestamp: int(time.time())`, and the flow-pack schema (`_WHEN_KEYS` in `flowspec_io.py`) gives `assign_to_group` no way to express a future effective time. No fixture can distinguish a time-gated port from an ungated one; Port A and Port B tie on that axis. The semantic *is* real and observable at the source (verified via `drush php:eval`: an asset whose only assignment is stamped now+86400 is absent from `getGroupMembers([G])` but present at `getGroupMembers([G], TRUE, now+90000)`). Only the recursion half of the C1 fix is actually under test.

**1.3 — The GO-test result is forgeable.** See OPEN-1(b) in §2.3. A pack that the judge accepts with zero warnings awards the *wrong* port a clean 100.0% EXIT=0 and fails the correct one at 71.4% EXIT=1.

---

## 2. The known-attack inventory

**Standard applied:** *blocked by construction* = the shape forbids it. *Blocked by a guard* = a specific check catches it; the next adversary goes around it. *Blocked by an unrelated rule* is recorded as **not blocked**.

**Count: 4 blocked by construction, 2 blocked by a guard, 4 still open.** Two attacks (A2, A5) are blocked in their naive form and open on a one-command escalation; they are counted as open, because the escalation is a documented shipped verb.

| # | Attack | Status |
|---|---|---|
| A1 | Port marks its own fixtures `corroboration_only` in `port.manifest.json` | **Blocked by construction** |
| C2′ | Same capability applied to the *pack*, then re-sealed | **OPEN — EXIT=0, clean** |
| A2 | Tamper expected values, leave `fixture_id` | Blocked by construction (×2) |
| A2′ | Tamper + recompute `fixture_id` + `oracle-seal` | **OPEN — EXIT=0, clean, judge inverted** |
| A3 | Bridge answers `describe` then hangs | Blocked **by a guard** |
| A3b | Same bridge, port declares `timeout: 86400` | **OPEN — no verdict, external kill at 45s** |
| A4 | Bridge returns `unanswerable` exactly where it would be wrong | **Blocked by construction** (+ a named guard) |
| A5 | Run a favourable subset of a pack | Blocked naively; **OPEN with one extra command** |
| A6 | Divergence citing a real-but-unrelated `decision_id` | Blocked **by a guard** (brittle; and see A6b) |
| A6b | Divergence citing a *non-existent* `decision_id` | Blocked from clean, but **the guard inverts** |
| — | Liar port (999/True to everything) with declared divergences | **Blocked by construction (×3)** |
| — | Marks file excluding every fixture (empty denominator) | **Blocked by construction** |
| — | Under-declare the probe so failures become gaps | **Blocked by construction** |

### 2.1 Blocked BY CONSTRUCTION — these will survive the next adversary

**A1 — the manifest pen is deleted, not merely ignored.**
Adding `fixture_marks` to a copy of portA's manifest → EXIT=2, `1 validation error for PortManifest / fixture_marks / Extra inputs are not permitted [type=extra_forbidden]` (`port_contract.py:133`, `ConfigDict(extra="forbid")`). `--marks` is not an argparse option at all; `--decisions` is likewise gone. `verify_port`'s signature has no marks parameter. This is shape.

**A2 (naive) — content addressing, two independent layers.**
Flipping `then[].value` and leaving the seal → EXIT=2: *"fixtures.jsonl does not match its seal (25c2474b… vs 57edbdeb…). The pack was changed after recording: a subset, an addition, or an edited expected value. NO VERDICT."* Byte-hash over the whole file (`pack.py:283-289`). Second layer, after re-sealing: EXIT=3, *"fixture_id 2df52cc2… does not hash its own body (bc6d63b8…) — the scenario or an expected VALUE was edited after recording"* (`pack.py:209`). Both are content addressing, not per-field trust.

**A4 — selective `unanswerable`, addressed on its own terms.**
A bridge declining exactly the input where a non-transitive answer would differ from the source → EXIT=3, by two independent mechanisms: (1) the lattice — `DECLINED` is a `NO_VERDICT` cause (`port_verify.py:543-545`) and `clean` requires `score.no_verdict == 0` (`port_verify.py:259`), so a decline can never be a pass, by construction; (2) a decline-accounting guard — *"port declared probe 'group_member' and then declined 1 call(s) on it — a capability that is unavailable exactly where it is tested is not a capability, and the declines are NOT gaps in the pack"* (`port_verify.py:705-710`). And the headline is denominated on the whole pack: `reproduced 3/3 scored assertions (of 4 in the pack), 1/4 NO VERDICT`. **The quotable "24/24 = 100%" shape is gone.** Sibling case verified: in the w0a-pilot baseline, 7 undeclared + 1 declined + 5 unrunnable → EXIT=3, never 0.

**Under-declaring the probe to convert failures into gaps — blocked.**
Stripping `group_member` from Port B's manifest capabilities *and* its bridge `describe` (the two must agree or `PortAdapter.open` raises `BridgeError`, so there is no way to lie to only one) → NO VERDICT 14, passed 0, `reproduced: NOTHING SCORED — this run is evidence of nothing`, EXIT=3. Declaration is all-or-nothing per probe term.

**Liar-999 with declared divergences — dead three times over.**
`value_score`'s denominator is `scored_answered - scored_diverged`, so a divergence leaves the fraction entirely (`port_verify.py:194-197`); `clean` requires `scored_diverged == 0` (`port_verify.py:262`); `Divergence.port_value` and `decision_id` are both required, so a sanction covers one stated value and must resolve. Measured: EXIT=1, `passed 3 / failed 1 / reproduced 3/4 = 75.0%`. The old "30 divergences → 100%, clean, exit 0" cannot recur. Even with everything satisfied, a sanctioned divergence yields at best EXIT=3, never 0.

**Empty denominator — blocked by construction.**
Marking all 3 fixtures `corroboration-only` and re-sealing → EXIT=3, `scored 0 (4 answered but excluded from scoring)`, `reproduced NOTHING SCORED — this run is evidence of nothing`, `NOT A CLEAN PASS: NOTHING WAS SCORED`. `scored_nothing` is a computed property of the empty denominator (`port_verify.py:199-207`) and a `clean` clause. **Downstream hazard noted:** the exit code moves 1 → 3, so a CI gate treating 3 as soft would swallow this. The *selective* version of this same move is OPEN-1(c), which reaches EXIT=0.

**A5 (naive) — blocked.** Subset without re-seal → EXIT=2, NO VERDICT. The pack is loaded whole or not at all.

### 2.2 Blocked BY A GUARD

**A3 — the hanging bridge.**
`MODE=sleeper_describe_then_hang` with port-declared `timeout: 5.0` → EXIT=3 in 5s wall clock, `NO VERDICT 4 — 4 × the port's bridge stopped answering`, `reproduced NOTHING SCORED`. Mechanism: off-thread `_pump` + `queue.get(timeout=deadline)` + `_kill` latching `self._dead` (`port_adapter.py:117-210`). **The guard works, and its parameter is written by the defendant.** See OPEN-2.

**A6 — divergence citing a real but off-topic decision.**
Blocked: EXIT=1, *"declaration problem: decision 'birth-uniqueness' exists but says nothing about 'group_member' — a sanction must be about the thing it sanctions"*, and the assertion is scored FAILED, not DIVERGED (`port_verify.py:586-595`). This is progress — **relevance is now checked, not just existence.** But the guard is `decision_covers` = case-insensitive substring of the assertion term in the decision's JSON text (`port_contract.py:232-240`), and its precision is poor in both directions. Enumerating the registry (`eval/ctkr/port_runs/kernel-9h5.24/build/cm-decisions.jsonl`, 5 ids): **no decision covers `group_member` or `stock_on_hand`** — including `membership-model`, the one that genuinely is about membership. So today the guard blocks *every* divergence on those terms, sound ones included; and any decision whose text happens to contain the literal token passes regardless of what it says. Independently confirmed by a second lens, which gave Port B five divergences citing the genuinely-about-membership `membership-model` and bought nothing: `diverged 0, failed 4, reproduced 10/14 = 71.4%`.

The port cannot write the registry (fixed repo path, `--decisions` removed), so it cannot go around the guard from its own side. But `DEFAULT_DECISION_SOURCES` points into `eval/ctkr/port_runs/kernel-9h5.24/**build**/cm-decisions.jsonl` — a *build* directory of the party being judged. Version-controlled today; the path choice puts the registry inside the defendant's output tree and should move.

### 2.3 STILL OPEN — in full

#### **OPEN-1. `ctkr oracle-seal` is a public, unauthenticated verb that re-issues a pack's entire authority.**

Every pack-integrity result (A2, A5, C2) is blocked only against an attacker who declines to type one more command. Three executions, all reaching **EXIT=0 / clean=true / 100%**:

**(a) A5 subset + re-seal.** Pack minus the failing fixture, then `uv run python -m ctkr oracle-seal <dir>` (EXIT=0), then re-run → **EXIT=0**, `fixtures 2 (0 INVALID EVIDENCE) / passed 2 / failed 0 / coverage 2/2 = 100.0% / reproduced 2/2 = 100.0%`, clean=true, headline `reproduced 2/2 scored assertions (of 2 in the pack)`. **Nothing in the artifact reveals the pack was partial** — the report's own denominator is the truncated pack, and pack_id/seal are freshly minted (`66fc63ada974`) with no lineage to the original `e8c76084c90a`.

**(b) A2′ surgical forgery.** Edit the expected value, recompute `SemanticFixture.content_id()` with the project's own helper, `oracle-seal`. → **EXIT=0**, `fixtures 3 (0 INVALID EVIDENCE) / passed 4 / failed 0 / reproduced 4/4 = 100.0%`, clean, for the port that **diverges from farmOS**. The unmodified `observations.jsonl` still records the source answering the opposite, and **nothing cross-checks it**: `_fixture_problems` (`pack.py:207-250`) verifies only that `observation_refs` *resolve*, never what they *say*. The observation log is decorative once the two hashes are recomputed.

Reproduced independently by two lenses. The second ran it against the GO-test pair and **fully inverted the judge**: Port B (does *not* match farmOS) → `passed 14 / failed 0 / reproduced 14/14 = 100.0% / clean / EXIT=0`; Port A (matches farmOS) → `passed 10 / failed 4 / reproduced 10/14 = 71.4% / EXIT=1`. Reported as `0 could not run, 0 corroboration-only, 0 INVALID EVIDENCE, NO VERDICT 0` — **the judge emits no warning of any kind.**

**(c) C2′ — mark only the failing fixture `corroboration-only` in the pack, re-seal.** → **EXIT=0**, `scored 2 (2 answered but excluded from scoring) / passed 2 / failed 0 / reproduced 2/2 = 100.0%`, no NOT-A-CLEAN-PASS section, clean=true — **while the body still prints `[FAIL] group_member(A) expected == True, got False - undeclared mismatch`.** This is the pre-refactor C2/A1 symptom verbatim. Invariant 2 relocated the pen from `port.manifest.json` to the pack, then shipped a public verb for re-issuing the pack's authority.

**The stated mitigation is dead code.** `pack.py:22-29` concedes the gap and says it is *"closed socially, by REGISTRY_NAME … a visible diff on a file the port author does not own."* It is not: `grep -rn 'registered_seals' --include='*.py' ctkr/` returns **exactly one hit — its own definition at `pack.py:194`. Zero callers.** `load_pack` never consults `PACKS.jsonl`; `grep -c '09eff4632c3d8e09' eval/ctkr/port_runs/PACKS.jsonl` = 0 while that forged pack verified clean. And `registry_for()` returns `None` (silent no-op) for any pack outside a tree containing `PACKS.jsonl` — so an attacker simply works in `/tmp`.

#### **OPEN-2. A3b — the judge waits on a deadline the defendant writes.**

Identical hanging bridge, `"timeout": 86400.0` in the port's own manifest. `timeout 45 uv run python -m ctkr port-verify …` → **EXIT=124, elapsed 45s, no verdict produced**, killed by an external timeout. That is precisely the original reported C5 failure. `BridgeSpec.timeout` (`port_contract.py:119`) is a plain `float = 30.0` with **no upper bound and no judge-side cap.**

#### **OPEN-3. The `decision_covers` guard inverts on an unresolvable decision id.**

`port_verify.py:586` reads `if did in decisions and not decision_covers(...)`. An id that does **not** exist therefore skips the topical check entirely, and the wrong answer is scored **DIVERGED, not FAILED**. Measured on the GO-test pair: a port citing the invented id `nested-membership-not-required` on its 4 failing assertions scores `passed 10, diverged 4, failed 0, **reproduced 10/10 = 100.0%**` — numerically tying the correct port. Non-existence is caught later, as a `declaration_problem` (`port_verify.py:692-700`), by which time the assertion has already left the scoring denominator.

`clean=false` and EXIT=3 still hold (`declaration_problems` + `scored_diverged` both block clean, `port_verify.py:257-264`), so the attack does not reach green, and the composite verdict still ranks correctly in the exit code and prose. But **a fabricated warrant is treated more leniently than a real-but-off-topic one** — exactly backwards — and any consumer reading `reproduced` or `value_score` as *the* score is defeated.

#### **OPEN-4. Shipped evidence cannot discriminate the C1 fix from its regression.**

§1.1, restated here because it is an open hole and not a caveat. Both ports score identically on every pack the refactor ships. Whoever re-records tomorrow against a re-broken adapter gets a green core-pack.

---

## 3. What the fresh adversary found

Three new attacks against the refactor's own claims, all built and executed rather than reasoned about. **All are open, and two reproduce the exact C1 inversion the refactor exists to kill.**

### **FRESH-1 — DERIVATION DRIFT. `derivation_id` hashes the English prose, not the code.**

In a sandbox worktree, `FarmOSAdapter.group_member` (`farmos_adapter.py:414-432`) was reverted to the pre-C1 non-recursive form — **one line** — and `probes.py` was touched not at all. Result:

- `PROBE_CONTRACT['group_member'].derivation_id` → still `22b77a9c85a4989d`, unchanged
- `contract_gaps()` → `[]`
- `unvalidated_probes()` → `[]`

Then the repo's own flow pack was recorded against the **live** oracle (`ctkr oracle-record --flows eval/ctkr/port_runs/wave1-c1/c1-membership-flows.json`). The recorder wrote `validation issues: 0` and sealed itself (pack `8aaf9adede82`). The pack asserts `group_member(A,G2) == FALSE` — contradicting farmOS — stamped `derivations: {group_member: 22b77a9c85a4989d}`, **identical to the honest pack**. `load_pack`: valid=3, invalid=0.

Judged with the **unmodified** repo tree:
- Port B (matches farmOS): `passed 3, failed 1, NOT A CLEAN PASS, [FAIL] group_member(A) expected == False, got True`
- Port A (diverges from farmOS): `passed 4, failed 0, reproduced 4/4 = 100.0%`, **clean**

**That is the C1 inversion, reproduced end-to-end at `8a7f775`, through a door the invariants do not cover.** The staleness guard is real but blind: it fires when the *prose* changes (editing the derivation string invalidated all 3 fixtures with `CORRECTED to 05e76edaf7109a09`) and does not fire when only the computation changes. There is no link of any kind between `derivation`/`validated_against` (free text) and the adapter method that computes the value.

### **FRESH-2 — `refused` is mislabelled BOUNDARY, and the recorder manufactures it from any HTTP error.**

`probes.py:279` declares `refused` with `authority=BOUNDARY` and the comment *"the source stated 'you may not do that' at its own interface, in its own words."* It does not. `FarmOSClient.request` (`farmos_adapter.py:121-128`) converts **every** urllib `HTTPError` — 401, 403, 500, 502, 503 — into one undifferentiated `AdapterError`, and `record_flow` (`recorder.py:607-637`) treats any `AdapterError` during `when` as the refusal when the flow says `expect_refusal`.

Built and executed: a transport answering a birth POST with HTTP 500 / `{"errors":[{"detail":"PHP fatal error"}]}`, run through the real `record_flow`. Output: `THEN: [('refused','K','==',True)]`, `authority: {'refused':'boundary'}`, `evidence_class: scoring`, and the witness observation literally reads `refused: POST /api/log/birth -> 500: {"errors":[{"detail":"PHP fatal error"}]}`. **Nothing reads that witness.**

So a crashed oracle is recorded as a delivered semantic; it carries BOUNDARY authority (which by construction exempts it from every Invariant-1 check — no derivation, no validation record, no `derivation_id`, permanently un-invalidatable); and it is then scored against every port. A port that *wrongly rejects* the write passes; a correct port that accepts it (as farmOS in fact does) **fails**. This is Invariant 3 broken **at the recorder**, where no port-side rule can reach it. It is live-relevant, not theoretical: this commit's own message records OAuth failures under concurrency at the shared oracle, and a 401 takes the identical path.

Weaker second case: `asset_active` (BOUNDARY) is `not attributes['archived']`. Against the live oracle the animal bundle exposes both `archived` (bool) and `last_archived`, with no `status`. Defensible as transcription, but it is our negation and our choice of field. Flagged, not claimed.

### **FRESH-3 — authority is self-declared; relabelling any derived probe BOUNDARY exempts it forever.**

`is_evidence` (`probes.py:107-116`) returns True if `authority == BOUNDARY` **or** `validated_against` is any non-empty string. Nothing checks either against reality.

- Free text: `ProbeSpec(authority='derived', derivation='we make it up', validated_against='trust me bro').is_evidence == True`, `unvalidated_reason == ''`.
- Relabel: rewriting `group_member` as `authority=BOUNDARY` with `derivation`/`validated_against` deleted — **which is exactly what `contract_gaps` demands of a boundary probe, so the guard actively coaches the bypass** — gives `contract_gaps() == []`, `unvalidated_probes() == []`, `is_evidence == True`, and the FRESH-1 pack that the corrected derivation had just marked `invalid=3` goes straight back to `valid=3, invalid=0`, because `_fixture_problems` skips any probe whose `derivation_id` is empty and a boundary probe's is empty by definition.

Relabelling `group_member` *specifically* is caught — but only by a name-hardcoded test (`test_group_member_is_validated_against_farmos_own_authority`). **A patch, not a shape.** Proof: relabelling `adjustment_count` DERIVED → BOUNDARY instead, the **entire python suite passed (0 failures)**, `contract_gaps() == []`, the shipped core-pack loaded valid=7/invalid=0, and `adjustment_count.is_evidence == True` with no validation record and no staleness stamp. **Every one of the other nine derived probes is equally unprotected.**

### What the fresh adversary confirmed as genuinely solid

The manifest pen (`fixture_marks`) and sanction laundering are blocked by construction and will survive. No quantity of declared divergences, validly or invalidly warranted, can produce `clean` or exit 0 — the worst case is exit 3.

---

## 4. C1–C6 — what is genuinely closed

| Blocker | Status | Detail |
|---|---|---|
| **C1** — judge inverted on group membership | **CLOSED as shipped; SURVIVES IN A NEW SHAPE** | The derivation is corrected and independently verified against `GroupMembership.php` and against the live service via `drush php:eval` (14/14). The GO test passes. **But it reappears two ways:** (i) FRESH-1 — a one-line adapter revert re-records an inverting pack with an identical `derivation_id`, valid seal, zero validation issues; (ii) OPEN-1(b) — forge + re-seal fully inverts the ranking with no warning. And no shipped pack would catch the regression (OPEN-4). |
| **C2** — port re-marks its own evidence to erase failures | **RELOCATED, NOT CLOSED** | The manifest pen is genuinely deleted (`extra="forbid"`, no `--marks`, no `--decisions`) — that half is construction. But OPEN-1(c) reproduces the identical symptom one file over: mark only the failing fixture `corroboration-only` **in the pack**, re-seal, get EXIT=0 / clean=true / reproduced 100% with the `[FAIL]` line still printed in the body. |
| **C3** — divergences bought a clean 100% | **CLOSED, three times over** | `value_score` excludes divergences from the denominator; `clean` requires `scored_diverged == 0`; `port_value` and `decision_id` are both required and resolved. Ceiling is EXIT=3. Genuinely structural. |
| **C4** — tampered expected values judged as truth | **CLOSED against tampering; OPEN against re-sealing** | Two independent content-addressing layers (file seal + fixture self-hash) block the naive edit at EXIT=2 and EXIT=3. Both are defeated by recomputing the fixture id and running the shipped `oracle-seal`, because nothing cross-checks a fixture's expected value against the observation it cites. |
| **C5** — hanging bridge produced no verdict until an external timeout | **CLOSED for a cooperative port; OPEN for an adversarial one** | The `_pump`/`queue.get`/`_kill` machinery genuinely works at 5s. `BridgeSpec.timeout` has no upper bound and no judge-side cap, so `timeout: 86400` reproduces the original failure exactly (EXIT=124 at 45s, external kill). |
| **C6** — `unanswerable`/absence read as a pass; empty denominators quoted as 100% | **CLOSED on the port side; OPEN at the recorder** | The strongest result in the refactor. The `NO_VERDICT` lattice + `scored_nothing` + the `clean` clause list is a shape: selective declines, total exclusion, and dead bridges all fail to reach green for reasons that follow from the type, and the headline now carries its own denominator (`reproduced X/Y (of N in the pack)`). **But absence does not collapse at the recorder:** FRESH-2 shows a 500 or a 401 recorded as `refused: True` with BOUNDARY authority — an absence turned into positive scoring evidence that no port-side rule can reach. |

**Score: 2 of 6 genuinely closed (C3, and C6 on the port side). 4 survive in a new shape.**

---

## 5. The structural reading

Invariants 1 and 3 differ sharply in how they were built, and they behave accordingly.

**Invariant 3 was implemented as a shape and behaves like one.** The no-verdict lattice is a type, not a checklist; three unrelated attacks fail against it for the same structural reason. This is the part of the refactor that will still be holding after the next three adversaries.

**Invariant 1 was implemented as a label.** "Every value declares its authority" is a claim a probe makes about itself, satisfied by `authority == 'boundary'` or by any non-empty string in `validated_against`. `derivation_id` hashes the prose describing the computation, never the computation. So the mechanism cannot detect the two things it exists to detect: a derivation that drifts (FRESH-1) and an authority claim that is false (FRESH-2, FRESH-3). Only `group_member` is protected, by a test that names it — a patch of exactly the kind this refactor set out to replace.

**Invariant 2 was implemented as a hash plus a naming convention about who runs which command.** A content hash proves a pack is internally consistent; it cannot prove a pack is the recorder's. The refactor ships the tool that mints consistency to anyone holding the directory. Until sealing is bound to something the port author does not control, "the defendant holds no pen" is a claim about custom, not about the code.

**Minimum to close, in priority order:**

1. **Bind `derivation_id` to the code that computes the value** — hash the adapter method's source or AST, not the prose. Without this the whole staleness mechanism is decorative. *(closes FRESH-1)*
2. **Cross-check every recorded expected value against the observation it cites at load time**, so re-sealing forged bytes fails on the witness rather than on a hash the forger controls. *(closes OPEN-1 a/b/c — the single highest-leverage fix)*
3. **Make `refused` a derived probe distinguished by HTTP status class**, and refuse to record a refusal from any 5xx or 401/403. Absence must collapse at the recorder too. *(closes FRESH-2)*
4. **Actually consult `registered_seals` in `load_pack`** — require registry membership, require the seal present, and require a pack's `fixture_ids` to be a superset of any prior seal for that path (this alone kills the subset attack) — or delete the docstring claim that the registry closes the gap.
5. **Cap `BridgeSpec.timeout` judge-side** at a hard ceiling the manifest cannot raise. *(closes OPEN-2)*
6. **Apply `decision_covers` unconditionally**, treating an unresolvable id as maximally uncovering, so inventing a decision is never more lenient than citing a real one. Replace the substring test with an explicit `applies_to: [probe_terms]` field on decisions, and move the registry out of the defendant's `build/` tree. *(closes OPEN-3)*
7. **Replace the `group_member`-by-name test with a table-driven rule:** every BOUNDARY probe's adapter method performs no computation beyond field access, and every DERIVED probe's `validated_against` resolves to a citable artifact rather than free text. *(closes FRESH-3)*
8. **Ship a nested-membership fixture and a future-effective-time fixture in `core-pack`**, so the C1 fix has recorded evidence that would fail on regression. Requires extending `_WHEN_KEYS` so `assign_to_group` can express an effective time. *(closes OPEN-4 and §1.2)*

---

## 6. Wave-1 recommendation

### **GO — at reduced size, with three preconditions and five abort triggers.**

**Why GO.** The GO test is the question Wave-1 turns on, and it passes decisively and for a principled reason: the derivation now matches farmOS's own published interface, verified against `GroupMembership.php` and against the running service, and the judge ranks the farmOS-matching port strictly better on value score, clean flag, and exit code. Invariant 3 is genuinely structural and kills the entire class of "absence quoted as success" results that made the pre-refactor numbers unquotable. C3 is dead three ways. The scoring headline now carries its own denominator. These are real gains and they will not erode.

**Why reduced size.** Every remaining open attack shares one property: **it requires an adversarial or careless *recorder*, not an adversarial port.** The port side is close to sound — the manifest pen is deleted, divergences cannot buy a pass, declines cannot become passes, under-declaration cannot hide failures. What is not sound is the chain of custody on the evidence itself, and the honesty of the derivation that produced it. That is a tolerable risk when the recorder is a small trusted set and every pack is reviewed; it is not tolerable at scale.

**Size: cap Wave-1 at the ports we can seat around one table, with a single named recorder.** Do not open pack recording to port authors. Do not accept an externally recorded pack in Wave-1 at all.

**Preconditions before Wave-1 starts (all three, none optional):**

1. **Fix #2 (value-vs-observation cross-check at load).** This converts the pack from "internally consistent" to "witnessed," and closes three separate open attacks at once. Without it, every Wave-1 result is worth exactly as much as the trust in whoever ran `oracle-seal`.
2. **Fix #1 (`derivation_id` binds to code).** Without it, an accidental adapter refactor mid-wave silently re-records inverting evidence with a green validation, and nobody finds out.
3. **Fix #8 (ship a discriminating nested-membership fixture in `core-pack`).** Cheap, and the only thing that makes the C1 fix regression-detectable by the repo's own evidence.

Fixes #3, #4, #5, #6, #7 can land during the wave. #5 in particular should land early — it is a two-line ceiling.

**What would stop it mid-flight:**

- **Any Wave-1 result reported `clean=true` on a pack whose seal is not in `PACKS.jsonl`.** Once #4 lands this is enforced; until then, treat it as a hard stop and re-record.
- **Any port scoring `reproduced 100%` while the report body contains a `[FAIL]` line.** That is OPEN-1(c) in the wild and it means someone marked evidence. Halt, diff the pack against its recorded ancestor.
- **A `refused` assertion whose observation log shows it was witnessed by a 5xx or a 401.** Under concurrency at the shared oracle this will happen by accident before it happens by malice. Until #3 lands, grep the observations of every refusal fixture before trusting it.
- **Any consumer or dashboard quoting `reproduced` or `value_score` as *the* score.** Divergence and no-verdict counts are load-bearing; the percentage alone is defeated by OPEN-3.
- **Exit code 3 treated as soft anywhere in CI.** EXIT=3 is where the empty-denominator and sanctioned-divergence cases land. If a gate passes on 3, the entire no-answer invariant is bypassed downstream.

---

## Appendix — artifacts and provenance

All attack artifacts are **SANDBOX**, none in the repo, nothing committed. The working tree at `8a7f775` was clean before and after all three lenses (`git status --short --branch` → `## main...origin/main`).

- `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/16b09ed7-6185-46f1-b167-14accfadbd96/scratchpad/atk/` — full replay inventory (copy of `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/port_runs/wave1-c1`), including `c1/observe_sel` (OPEN-1c), `c1/observe_a2d` (surgical forgery), `c1/observe_sub` (subset), `c1/p_hang_long` (unbounded timeout), `c1/p_fakedec` (ghost decision), `c1/observe_allcorr` (empty denominator)
- `/private/tmp/…/scratchpad/atk1/` — forged-then-resealed c1 pack
- `/private/tmp/…/scratchpad/atk2/` — pack recorded from live farmOS through the sabotaged derivation
- `/private/tmp/…/scratchpad/atk5/` — manifest with `fixture_marks`
- The scratch git worktree at `/private/tmp/…/scratchpad/wt` has been removed; `git worktree list` shows only the main checkout.

**Production paths referenced (read-only, unmodified):** `/Users/dukejones/work/WorldTree/MetaCoding/ctkr/ctkr/oracle/data/core-pack/`, `.../data/hardening-pack/`, `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/port_runs/wave1-c1/`, `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/port_runs/kernel-9h5.24/build/cm-decisions.jsonl`, `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/port_runs/PACKS.jsonl`.

**Live oracle:** `http://localhost:8095`, shared. Used for `oracle-record` (creating ordinary test animals and groups), `oracle-verify`, and read-only `drush php:eval` / container file reads against `GroupMembership.php`. `bring-up.sh` and `docker` were never invoked.

---
---

# Round 2 — 2026-07-21: the witness invariant, adversarially tested

**Tree under test:** git HEAD `444dd532b5b715b6d5bc32b7d57175052d7bbf53` on `main`, with the round-2 change present as **uncommitted working-tree modifications** (13 paths: `D ctkr/ctkr/commands/oracle_seal.py`, `M ctkr/ctkr/oracle/{pack,fixtures,recorder}.py`, `M ctkr/ctkr/commands/oracle_record.py`, `M ctkr/ctkr/oracle/data/{core,hardening}-pack/*`, `M ctkr/tests/test_oracle_invariants.py`, `M docs/design/iteration-methodology.md`). Suites on this exact tree: `uv run pytest` → **633 passed / 3 skipped** (was 626/3); `bun test` → **484 pass / 0 fail**. Two independent adversarial lenses; all attack artifacts **SANDBOX ONLY** under `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/16b09ed7-6185-46f1-b167-14accfadbd96/scratchpad/`. Nothing written to the repo, nothing committed, `eval/ctkr/port_runs/PACKS.jsonl` untouched.

## 1. Is the red true?

# NO.

**"No artifact in the pipeline can endorse a claim its own witnesses contradict" does not hold.** It is true as literally written — and it is satisfiable in two ways that cost one line each, because the witness is a *second copy*, not a *second source*, and because it covers only `then`.

**The attack that decides it — the `when`-clause exemption forgery.** The round-2 fix for attack (c) replaced *"believe the pack's `evidence_class`"* with *"re-derive the exemption from `fx.when`"* (`ctkr/ctkr/oracle/pack.py:407` → `fixtures.order_sensitivity`). That moved the pen; it did not remove it. `then` is now witnessed assertion-by-assertion. `when` is inside the same hashed body and is witnessed by **nothing** — `_witness_problem` (pack.py:330-368) compares only `probe_descriptor(t)` and the value. So the forger stops forging the label and forges the thing the label is derived from.

Against the re-recorded **shipped** hardening-pack (11 fixtures, seal `8e1665dfba25`), add `at:"-3600"` to two `assign_to_group` steps sharing one `ref` in the two fixtures a non-recursive port fails, set `evidence_class=corroboration-only`, recompute `content_id()`, re-seal via `seal_recording`. Loader result: `valid=11 INVALID=0`. End-to-end against a port that is **wrong** about farmOS:

| | headline | clean |
|---|---|---|
| HONEST `8e1665dfba25` | `reproduced 31/33` | **False** — 2 value failures |
| FORGED `75a039197f87` | `reproduced 27/27 (of 33), 0 sanctioned divergences, 0/33 NO VERDICT, 6 corroboration-only excluded` | **True**, `needs_review: NONE` |

…while `[FAIL] group-membership-recurses group_member expected True got False` is still computed inside the run. That is attack (c)'s exact signature, at full strength, against the hardened tree. **`observations.jsonl` is byte-identical**: no witness edited, no `observation_refs` edited, no orphan created, no witness contradicted. The implementation report's cost claim ("editing the fixture AND its witness AND `observation_refs` AND pruning the orphan set AND both digests") does not apply to this path at all.

**The second decider — attack (a2), the two-edit forgery.** Edit `then[i].value` *and* `r["observed"]` on the observation it already cites. On a GO-test pack recorded from the live oracle minutes earlier, this **fully re-inverted the GO test**: honest portB (matches farmOS) 4/4 = 100.0% EXIT=0 / portA 3/4 = 75.0% EXIT=1, becomes forged portA 4/4 = 100.0% EXIT=0 / portB 3/4 = 75.0% EXIT=1, header `fixtures: 3 (0 could not run, 0 corroboration-only, 0 INVALID EVIDENCE)`, no warning of any kind. `observation_refs` key on `obs_id`, which does not change; the orphan set does not change; `seal_recording` recomputes both file digests and the seal *for the attacker*.

**Why, generally.** The witness is minted from the same `_observe_probe` return as the assertion (`recorder.py:713-720`). It is a duplicate copy inside the same artifact, held by the same writer, under the same unkeyed authority. Such a copy cannot testify against that writer — it catches an editor who *forgets the copy exists*, which was exactly last round's adversary and is not the next one. And it only ever covers `then`: `given`, `when`, `glossary_terms`, `feature` are hashed but unattested. **The recorder wrote down answers, never questions or setup.**

## 2. Attack ledger

### Blocked BY CONSTRUCTION (7)

| Attack | Mechanism that kills it |
|---|---|
| **(a) SURGICAL FORGERY** — edit expected value, recompute `content_id()`, re-seal | `same_value(w["observed"], t.value)` at pack.py:362. Reproduced verbatim: *"then[0] expects group_member == False, but its own witness `e90f1332dc7fd7dc` records the source delivering True. INVALID EVIDENCE."* CLI verb `ctkr oracle-seal` is gone (`ctkr --help` → 0 hits; the file does not exist), so the re-seal had to go through the library. |
| **(b-naive) SUBSET** — drop failing fixtures, re-seal | Orphan-witness rule, `load_pack` pack.py:517-533. `PackError: 6 witness observation(s) are claimed by no assertion in this pack … A pack is judged whole. NO VERDICT.` |
| **(c) SELF-MARKING** — set `evidence_class` on the failing fixture | Two independent blocks: the class is inside `_body_for_hash` (fixtures.py:275) so the label changes the fixture id, and the loader **re-derives** the exemption via `order_sensitivity(fx.when)`. *"claims evidence_class=corroboration-only, but nothing in the fixture earns it."* (Superseded by the round-2 break above — the re-derivation is itself forgeable.) |
| **UNWITNESSED ASSERTION** — blank `then[i].witness`, delete the observation | Pre-existing `observation_refs` resolution check fires first. Note: pack.py:337's dedicated "names no witness" message is therefore **unreachable** whenever the recorder also wrote provenance refs. |
| **WITNESS DETACHED** — blank `then[i].witness`, keep the observation | Orphan rule: *"4 witness observation(s) are claimed by no assertion."* |
| **EMPTY `then[]`** — delete the failing assertions, keep the fixture | Rejected — but by provenance refs, not by the witness check. `_witness_problem` is genuinely vacuous on an empty `then[]`. |
| **DEMOTE THE WITNESS** — flip `record="witness"` → `"boundary"` | Citation dangles rather than the check skipping: *"cites witness … which is not in this pack's observations.jsonl."* |
| **BOUNDARY/DERIVED MISLABELLING** | `PROBE_CONTRACT` lives in `ctkr/ctkr/oracle/probes.py`, which no pack can edit; `current_derivations()` is read from the module, not the pack. The label is not in the artifact. |

`same_value` type handling was measured across a matrix and is careful: `3.0 == 3` True; `True == 1` **False**; `False == 0` **False**; `['a','b'] != ['b','a']` (order significant, correct for `nicknames`); `0.1+0.2 != 0.3`. Exact float comparison is right here — both sides pass through the same recorder's `json.dumps`, so no representational drift exists to tolerate.

### OPEN (6) — full statements

---

**OPEN-A. `when`-CLAUSE EXEMPTION MANUFACTURE — attack (c) reborn through the unwitnessed clause.** *Not blocked, and not by a guard either — there is no check on this path at all.*

Full detail in §1. Scripts `scratchpad/atk/attack_when.py`, `scratchpad/atk/e2e.py`; forged pack `scratchpad/atk/pack2/` (SANDBOX). Verified independently at HEAD: `order_sensitivity(when)` reads `w.at`, `w.against`, `w.ref` and nothing else, and no witness record covers any of them. Verdict flip honest `clean=False` → forged `clean=True` against a port that is wrong about farmOS. Cost: change one string in one `when` step, flip one label, recompute one hash, re-seal. The witnesses, observations, orphan set and both file digests come along for free, because none of them was ever a function of `when`.

---

**OPEN-B. TWO-EDIT FORGERY (a2) — forge the witness alongside the assertion.** *Not blocked.*

Full detail in §1. `scratchpad/invert.py a2` (SANDBOX), run on a pack recorded from the live oracle at `http://localhost:8095`. Full re-inversion of the GO test, reported as "0 INVALID EVIDENCE" — byte-for-byte the same headline the original MetaCoding-96q attack (a) produced. The escalation from the blocked attack (a) costs **one extra line**.

---

**OPEN-C. THE LEDGER IS DEAD ON EXACTLY THE TWO PACKS THAT SHIP.** *Not blocked. This is round-1 defect (C) again, one level of indirection up.*

`registry_for()` walks up from the pack and **breaks at the first parent containing `.git`** (pack.py:243-244). The only `PACKS.jsonl` in the repo is at `/Users/dukejones/work/WorldTree/MetaCoding/eval/ctkr/port_runs/PACKS.jsonl`; the shipped packs are at `/Users/dukejones/work/WorldTree/MetaCoding/ctkr/ctkr/oracle/data/{core,hardening}-pack/`. Measured at HEAD, independently, by both lenses:

```
ctkr/oracle/data/core-pack/fixtures.jsonl      -> registry_for = None   registry_problem = ''
ctkr/oracle/data/hardening-pack/fixtures.jsonl -> registry_for = None   registry_problem = ''
```

`registered_seals()` went from **zero callers** to **one caller that is handed `None` on every artifact the control exists to protect**. The ledger *does* work where a ledger exists — reproduced `STRICT SUBSET of registered pack 0b2c5524b62b (2 of 3 fixtures)` under a copied ledger. But the only test that proves it (`test_attack_b_a_subset_that_also_strips_the_witnesses_is_caught_by_the_ledger`, `ctkr/tests/test_oracle_invariants.py:475`) **writes its own ledger into `tmp_path`** — it proves the guard in a tree configuration the real artifacts are not in. This is precisely the failure mode the methodology names: a guard that passed review and does not run. And `pack.py` currently credits it in prose.

---

**OPEN-D. SEALING ENROLLS THE FORGER — `registry_problem`'s membership clause is vacuous.** *Not blocked.*

`seal_recording(..., register: bool = True)` (pack.py:182) calls `register_seal(seal, registry_for(fx_path))` (pack.py:231-232). The act that issues a seal writes it into the ledger that seal is later checked against. Demonstrated in a purpose-built tree that *does* keep a ledger (`scratchpad/atk/ledgered/`, `scratchpad/led.py`): honest pack registered, then the (a2) forgery re-sealed in the same tree with the default `register=True` → `registry_problem = ''`, `FORGERY UNDER LEDGER: valid 3 invalid 0`, `LOADS CLEAN: 11 valid / 0 invalid`. Any pack that survives the seal-hash check was necessarily produced by this library, and this library enrolls it. The membership clause can only fire on a pack copied in from a tree without a ledger — the `/tmp` case the module already concedes.

---

**OPEN-E. THE SUBSET RULE CATCHES DELETION ONLY.** *Not blocked.*

`registry_problem` flags a pack only when some registered entry is a **strict superset** (`theirs > mine`, pack.py:306). Any *edit* changes a fixture's `content_id`, so the edited pack contains an id no registered pack has and is never a subset. Demonstrated end to end under a live ledger (`scratchpad/atk/led2/`): honest `8e1665dfba25` registered (11 fixtures), forged `75a039197f87` registered over it (11 fixtures) → `LEDGER DID NOT STOP IT -> valid 11 invalid 0 | corroboration-only: 2`. The subset rule is a defence against attack (b) only; (a)- and (c)-shaped edits walk straight past it even where it is wired.

Also: **(b2) subset-completed** is not blocked on the shipped packs, precisely because of OPEN-C. Drop the two failing fixtures *and* prune their now-orphaned witnesses → hardening-pack loads `valid 9 invalid 0`, and nothing in the artifact says it is partial. On the GO-test pack the discriminating fixture vanishes and **both ports tie at 2/2 = 100.0% EXIT=0** — the wrong port becomes indistinguishable from the right one.

---

**OPEN-F. `clean` HAS NO TERM FOR HOW MUCH WAS EXCLUDED — the amplifier.** *Not blocked.*

`PortVerifyReport.clean` (`ctkr/ctkr/oracle/port_verify.py:249-264`, verified at HEAD) tests `scored_failed`, `no_verdict`, `declaration_problems`, `invalid_evidence`, `scored_diverged`, `scored_nothing` — and **not `excluded_corroboration`**. `scored_nothing` fires only at 100% exclusion (`(scored_answered - scored_diverged) <= 0`, line 207). Exclusion is a continuous dial and `clean` inspects only one endpoint of it, so 6/33 assertions can vanish and the run still reads green. This is what converts OPEN-A's shrunken denominator into a false green rather than merely a smaller number. `headline()` prints `6 corroboration-only excluded` as a neutral trailing clause.

Note the symmetry, which is under-attended everywhere in this artifact: exclusion is **silent in both directions**. It makes a *correct* port indistinguishable from an incorrect one just as readily as it makes an incorrect one look clean.

---

**OPEN-G (minor). SILENT SKIP — `None` expectation against a witness row with no `observed` key.** *Not blocked.*

Set 4 `group_member` values to `None` and pop `observed` from their witness rows → `valid 11 INVALID 0`. `w.get("observed")` is `None` and `same_value(None, None)` is **True** (verified at HEAD), so an absent witness value *agrees with* an absent expected value. `load_pack` never calls `validate_fixture`, so the `_ASSERT_REQUIRED` rule that `value` may not be `None` is not enforced on the judging path. Low leverage — a `None` expectation cannot be met by a real port, so it converts a failure into a different failure rather than into a pass — but it is a real hole in "absent values without a silent skip".

---

**OPEN-H (structural, conceded by the implementer). A VALID SEAL WITHOUT THE LIVE ORACLE.**

Every attack above produced a seal `load_pack` accepts as authentic **without touching `http://localhost:8095`**. `seal_recording` checks only that `observations` is non-empty (pack.py:206); it never verifies the objects came from a session, that witnesses exist, or that they are consistent with the fixtures. *"Sealing is part of the act of recording, which requires the live source"* (pack.py:196) is a description of the intended caller, **not an enforced precondition** — the same shape of claim as the old `seal_pack` docstring the refactor was written to fix. Deleting the CLI verb raised the bar from *run one shipped command* to *write six lines of Python*. It did not change what authority is.

## 3. Does the GO test still rank correctly?

**Yes — no regression.** On a pack re-recorded from the live oracle at HEAD+changes (`uv run python -m ctkr oracle-record --flows eval/ctkr/port_runs/wave1-c1/c1-membership-flows.json`, seal `0b2c5524b62b`, 3/3 flows, 23 observations, 0 validation issues), the honest ranking is:

- **portB** (RECURSIVE=1, matches farmOS): **4/4 = 100.0%, clean, EXIT=0**
- **portA** (RECURSIVE=0, matches the old adapter): **3/4 = 75.0%, NOT A CLEAN PASS, EXIT=1**

The live oracle answered `group_member(A,G1)=True`, `group_member(A,G2)=True` (transitive), `group_member(G1,G2)=True`, `group_member(A,G3)=False`. Both shipped packs re-recorded clean: core-pack 7/7 flows, 54 observations, seal `0bbedf28cd75`, 0 issues; hardening-pack 11/11 flows, 187 observations, seal `8e1665dfba25`, 0 issues. Suites green (633/3 py, 484 TS). **Nothing that worked was broken.** One caveat carried forward from the implementation: every *historical* eval pack is now correctly INVALID EVIDENCE (wave1-c1/observe 0 valid/3 invalid; wave0-pilot/w0a-observe 0/12) — they have no witnesses; any result quoted from them needs re-recording.

## 4. What an attacker must now do — plainly

**It is still cheap.** The declared residual was "hand-write a whole self-consistent recording". The measured cost is:

- **To invert a verdict by value (OPEN-B):** edit `then[i].value`, edit `r["observed"]` on the observation it already cites, call `seal_recording()`. **Two field edits and a library call, all offline.** Refs, orphan set, both file digests and the seal are recomputed for you.
- **To make failing fixtures disappear from scoring (OPEN-A):** add `at:"-3600"` to two `when` steps sharing a `ref`, set `evidence_class`, recompute `content_id()`, re-seal. **`observations.jsonl` never changes.**
- **To ship a partial pack (OPEN-E/b2):** drop the fixtures, drop their orphaned witnesses, re-seal. On the shipped packs there is no ledger to catch it; where there is one, `register=True` enrolls the forgery on the forger's behalf.

The one prerequisite for all three is **import access to `ctkr.oracle.pack`** — i.e. anyone who can run the recorder. That is the entire pool of Wave-1 pack producers.

**What is genuinely real from round 2, and will not erode:** post-hoc edits to `then` are dead by construction; deletion leaves a hole the pack cannot close from inside; a self-applied `evidence_class` label is both unwritable and unbelievable. Removing `ctkr oracle-seal` and replacing `seal_pack(path)` with `seal_recording(objects)` is the *right shape* of fix, and the structural test that enumerates the command package and asserts only `oracle_record` reaches the sealer is the right *kind* of evidence.

**How I would fake this fix, stated plainly:** ship exactly what is shipped, run the three archived round-1 attack scripts unchanged, watch them fail, report the red closed. That is what the implementation report's evidence demonstrates. The experiments that distinguish "the forger must re-record" from "the forger types one more line" — the two-edit variant and the `when`-clause variant — were not run.

## 5. The next red, as a property

The current red is closable only in letter, because a self-consistent artifact cannot be refuted from inside itself, and every remaining attack is now exactly that shape. State the next red so that internal consistency is not a defence:

> ### **Every field a verdict depends on must be attested by a party the pack's author cannot impersonate.**

Two corollaries that make it testable:

- **Nothing hashed is unattested.** `when`, `given`, `glossary_terms` are verdict-bearing (OPEN-A proves `when` is) and must carry witnesses, or must not be readable by the loader.
- **Attestation must be non-reproducible by the recorder alone.** A key the recorder does not hold, or a co-signature from an independent lens — `drush php:eval` against the live service already served as exactly that in the round-1 report and is *not in the artifact*.

The concrete moves, in order of what they buy:

1. **Witness the `when` clause.** The recorder already holds boundary observations of every write it performed; emit the *effective time the source actually accepted* into them, and have `load_pack` re-derive `order_sensitivity` from the **witnessed writes**, not from the pack's own `when`. Then the exemption is a fact about what farmOS did — the only thing an exemption was ever supposed to be. Kills OPEN-A.
2. **Make sealing require something the forger does not hold** — a key, or a co-signature by a party that is not the recorder. This is the only move that touches OPEN-B and OPEN-H; nothing filesystem-local can.
3. **Add `excluded_corroboration == 0` to `clean`** (or a recorder-signed exclusion budget), and print exclusions as a not-green in `headline()`. Two lines; kills the amplifier OPEN-F and halves OPEN-A's payoff.
4. **Drop `register=True` as a default**, so ledger membership means *somebody else vouched*. Kills OPEN-D.
5. **Make `registry_for` reach the repo root inclusive** (or take a configured path) so the shipped packs are actually bound — and add a test that exercises the *shipped* geometry, not a `tmp_path` fabrication. Kills OPEN-C. Until then, delete the ledger's credit from `pack.py`'s prose: crediting a control that does not run on the packs it ships is the same defect the refactor was written to remove.
6. **Replace `theirs > mine` with a comparison over `provenance.flow` keys per source** — a pack presenting fewer *flows* than a registered pack for the same source is a subset regardless of fixture ids. Kills OPEN-E.
7. Enforce `_ASSERT_REQUIRED` on the judging path (`load_pack` → `validate_fixture`), or make `same_value` distinguish an absent `observed` key from a `None` value. Kills OPEN-G.

## 6. Wave-1 recommendation

### **GO — at the same reduced size as round 1, with the size cap now load-bearing rather than precautionary, and two new preconditions.**

**Why still GO.** The GO test passes decisively and for a principled reason, and round 2 did not touch it: the farmOS-matching port ranks strictly better on value score, clean flag and exit code, on a pack recorded from the live service. The port-side invariants remain sound — divergences cannot buy a pass, declines cannot become passes, under-declaration cannot hide failures. Round 2 added three genuinely structural blocks. None of that regressed; 633/3 and 484 green.

**Why the cap is now load-bearing.** Round 1's judgement was *"every remaining open attack requires an adversarial or careless recorder, not an adversarial port."* Round 2 confirms that and sharpens it: **the cost to a recorder is two field edits.** The round-1 mitigation for this — "fix the value-vs-observation cross-check at load, which converts the pack from internally consistent to witnessed" — has now landed and is **not sufficient**, because the witness is a copy, not a source. Therefore:

- **Cap Wave-1 at ports that can be seated around one table, with a single named recorder.**
- **Do not open pack recording to port authors.**
- **Do not accept an externally recorded pack in Wave-1 at all.**
- Recording remains a *trusted* act. Say so in the docs rather than implying the artifact enforces it.

**Preconditions before Wave-1 starts (all four):**

1. **Move #3 above** (`excluded_corroboration` in `clean`, exclusions printed as not-green). Two lines, and without it OPEN-A produces a silent false green in the wild.
2. **Move #1 above** (witness the `when` clause). Without it the exemption path is a one-string forgery on the artifacts that ship.
3. **Move #5 above** (bind the shipped packs to a ledger, or delete the claim). Currently `pack.py` credits a control that returns `None` on both shipped packs.
4. Carried from round 1 and still required: **`derivation_id` binds to code** — an accidental adapter refactor mid-wave silently re-records inverting evidence with a green validation.

Moves #4, #6, #7 can land during the wave.

**New mid-flight abort trigger, added to round 1's five:**

- **Any run reporting `clean=true` with a non-zero `corroboration-only excluded` count.** Until move #3 lands this is invisible in `clean` and is the exact signature of OPEN-A. Halt and diff the pack's `when` clauses against its recorded ancestor.
- Round 1's trigger *"any port scoring `reproduced 100%` while the body contains a `[FAIL]` line"* still stands and now has a second cause — verify which of OPEN-A or OPEN-B produced it before resuming.

## Appendix — round-2 artifacts and provenance

All attack artifacts are **SANDBOX**, none in the repo, nothing committed. `git status --short --branch` was identical before and after both lenses (the 13 uncommitted implementation paths, and only those). `eval/ctkr/port_runs/PACKS.jsonl` still has its original 5 rows; the copy that was ledger-tested was made into the sandbox.

- `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/16b09ed7-6185-46f1-b167-14accfadbd96/scratchpad/` — `atk_a.py`, `atk_bc.py`, `atk_d.py`, `atk_h.py`, `invert.py`, `led.py`, and pack copies `a`, `b`, `b2`, `c`, `a2`, `e`, `f`, `h`, `i`, `j`, `go`, `inv_a2`, `inv_b2`, `ledger`
- `/private/tmp/…/scratchpad/atk/` — `attack_when.py`, `e2e.py`, `pack1/` (honest), `pack2/` (forged `when`), `ledgered/`, `led2/`

**Production paths re-recorded by the implementation** (the locations `port-verify` / `oracle-validate` read by default): `/Users/dukejones/work/WorldTree/MetaCoding/ctkr/ctkr/oracle/data/core-pack/` (seal `0bbedf28cd75`) and `/Users/dukejones/work/WorldTree/MetaCoding/ctkr/ctkr/oracle/data/hardening-pack/` (seal `8e1665dfba25`). The adversarial GO-test re-recording went to `scratchpad/go`, **not** to `eval/ctkr/port_runs/wave1-c1/observe`.

**Live oracle:** `http://localhost:8095`, shared. Touched by `ctkr oracle-record` only, creating ordinary test animals and groups. No `bring-up.sh`, no `docker`, no `drush` mutation. No commit.
