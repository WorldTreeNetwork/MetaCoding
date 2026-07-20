# B2 completion report — `ctkr port-verify` and the probe-surface contract

> 2026-07-20 · closes the tooling half of blocker **B2** of
> `eval/ctkr/results/wave1-readiness-2026-07-20.md` (bead `MetaCoding-kgu`).
> The tool is built, in the repo, and mechanically reproduces the judgement that
> three agents hand-wrote three throwaway harnesses to reach. It is also, as
> shipped, **defeatable on two of its three honesty requirements**. This report
> leads with that.
>
> Nothing here is committed. All paths are production repo paths unless marked
> SANDBOX.

---

## Bottom line

- **The tool works and removes the artisanal-judge cost.** One command judges a
  build: `ctkr port-verify <pack> --port <dir> [--marks <file>]`. Three independent
  validators ran it for real; one of them wrote a **second port from scratch in
  Python, 95 lines, different language and module layout**, and verified it against
  the untouched w0a pack with **zero changes to the verifier**. Language-agnostic
  and layout-agnostic, confirmed by construction, not by reading.
- **The w0a build's real score is two numbers that cannot be blended:
  coverage 18/30 = 60.0%, value 17/17 = 100.0%, exit 3.** The pilot's raw
  "24/30" is dead. `unanswerable` is its own bucket with no arithmetic path to
  `PASSED`.
- **Honesty requirement 1 (gaps) holds under attack.** Two validators tried to make
  a failure vanish by undeclaring a capability. It converted 11 failures into 24
  loud GAPs, halved coverage to 20%, and kept a non-zero exit. A null port scores
  nothing. No attack made an unanswerable assertion pass.
- **Honesty requirements 2 and 3 do NOT hold.** Both were broken, for real, with
  running code. A port that gets **every single observed value wrong** was made to
  report `coverage 100.0%, value 30/30 = 100.0%, clean = true, exit 0` two
  different ways. Details in §3 — this is the lead finding and the reason **B2 is
  reduced, not closed**.
- **Per-feature residue is right-shaped:** one manifest (declaration) + one bridge
  (the port's own code). **New domain vocabulary is not** — a new glossary term is
  still a code change in 8–9 Python files.
- **Verdict: the JUDGE stage is wave-scalable in architecture and not yet in
  practice.** Land the four contained fixes in §6 before feature ~5; do not close
  `MetaCoding-kgu` on the current numbers.

---

## 1. What the tool does

### 1.1 The probe-surface contract

`ctkr/ctkr/oracle/probes.py` is the missing binding B2 named. Two tables:

- `PROBE_CONTRACT` — 15 glossary assertion terms → the adapter method that answers
  each, plus how a fixture's `then` fields become call arguments.
- `OPERATION_CONTRACT` — 10 action terms → the methods a port must have to perform
  the fixture's setup at all.

`contract_gaps()` proves the table and the glossary cover each other **exactly**,
and `tests/test_port_verify.py::test_contract_covers_the_glossary_exactly` is the
tripwire. A validator inserted a fake `feed_ration_total` into `ASSERTION_TERMS`
and the test failed immediately. That closes the contract-level version of the bug
that produced 24/30: **it is now impossible to record a fixture asserting something
no implementation could ever be asked.**

The same table now drives the recorder side — `runner.py`'s 45-line `if/elif`
dispatch was replaced by a `PROBE_CONTRACT` lookup (47 insertions / 52 deletions,
behaviour and error strings preserved). Recorder and judge read one table, so
"which method answers `adjustment_count`" cannot drift.

### 1.2 The judge

| file | role |
|---|---|
| `ctkr/ctkr/oracle/port_contract.py` | what a port DECLARES: `PortManifest`, `PortCapabilities`, `Divergence`, `FixtureMark`, `BridgeSpec`, `load_marks()` |
| `ctkr/ctkr/oracle/port_adapter.py` | `PortAdapter(ImplementationAdapter)` + `PortBridge` — line-delimited JSON subprocess bridge; `Unanswerable` / `FalseDeclaration` / `BridgeError` |
| `ctkr/ctkr/oracle/port_verify.py` | the judge and the four-bucket score |
| `ctkr/ctkr/commands/port_verify.py` | the CLI |
| `ctkr/tests/test_port_verify.py` | 24 hermetic tests, no Docker/oracle/network |
| `docs/design/port-verify.md` | contract, bridge protocol, honesty rules, worked w0a result |
| `eval/ctkr/port_runs/wave0-pilot/w0a-build/build/port_bridge.ts` | the w0a build's own bridge |
| `eval/ctkr/port_runs/wave0-pilot/w0a-build/build/port.manifest.json` | its capability declaration |
| `eval/ctkr/port_runs/wave0-pilot/w0a-fixture-marks.json` | marks `d9778c65…` corroboration-only + order-sensitive |

Exit ladder: `0` clean · `1` value failure · `2` usage/contract/bridge error
(nothing judged) · `3` no failures but the verdict is incomplete. **Exit 3 is the
single best decision in the design** — it makes "we shipped 100 features at 100%
value score and 12% coverage" unstateable as a green build.

Deliberately **not** reusing `run_fixtures`: `AssertionResult.passed: bool` has no
room for a third and fourth outcome, and `RunSummary.pass_rate` is exactly the
blended headline requirement 1 forbids. Reused instead: `steps.apply_given` /
`apply_when` (so a port is driven exactly as the source was observed),
`compare_values`, `resolve_probe_args`, the probe contract.

---

## 2. The measured w0a score, and the three hand harnesses

Re-run today at repo paths, pack and build untouched:

```
ctkr port-verify eval/ctkr/port_runs/wave0-pilot/w0a-observe/fixtures.jsonl \
  --port eval/ctkr/port_runs/wave0-pilot/w0a-build/build/ \
  --marks eval/ctkr/port_runs/wave0-pilot/w0a-fixture-marks.json
```

```
  fixtures     : 12 (2 could not run, 1 corroboration-only)
  assertions   : 30
  answered     : 18
  UNANSWERABLE : 12   <- declared gaps, not passes
  scored       : 17   (1 answered but excluded from scoring)
    passed 17 / diverged 0 / failed 0
  coverage     : 18/30 = 60.0%
  value        : 17/17 = 100.0%
  exit 3
```

Reconciliation against the hand harnesses (9/12 fixtures, 17/17 answerable,
13/30 unanswerable):

| hand | tool | agree? |
|---|---|---|
| 9/12 fixtures | 10 ran, 1 of those corroboration-only → **9 ran AND scored** | exact |
| 17/17 answerable | `scored_passed 17 / scored_answered 17` | exact |
| 13/30 unanswerable | **12/30** | off by one — contested, see below |

The one-assertion difference is where the three validators split, and the split is
itself the most useful finding in this report.

**Two validators judged the tool MORE precise.** Fixture `d9778c65` has two
assertions: `adjustment_count` (a true gap) and `stock_on_hand == 3.0` (the port
answers it, correctly, 3.0). The hand harnesses lumped both into "unanswerable";
the tool splits them into 1 unanswerable + 1 answered-passed-but-excluded.
18 + 12 = 30 = 17 + 13, and the excluded pass contributes to neither numerator nor
denominator, which is precisely requirement 3.

**One validator located the missing 13th somewhere else entirely, and is right.**
On fixture `069dc601` ("An asset with no adjustments at all reports no holdings"),
farmOS says `stock_on_hand(bin) == 0.0` and the port's `getInventory` returns `[]`.
The tool prints `[PASS] ... got 0.0`. That `0.0` is **manufactured by the port's own
bridge** — `port_bridge.ts:130`, `return row ? row.value : 0;`, disclosed in the
bridge header. This is the one real representational divergence the hand judgement
found, and the tool scores it as a clean pass.

That validator then proved the bridge author had no honest alternative, by building
and running three sandbox variants:

- bridge throws for the absent row → `[FAIL] ... port error: no holding row for
  this pair`, value drops to 16/17
- bridge answers `{ok:false, unsupported:true}` → `[FAIL] ... port declared
  'stock_on_hand' but its bridge refuses it` (FalseDeclaration + declaration problem)
- drop `stock_on_hand` from the manifest → gaps all 13 `stock_on_hand` assertions

**Fabricating a value is the only route that is not punished.** `Unanswerable` is
raised only by `_need_operation` / `_need_probe` before the bridge is contacted
(`port_adapter.py:220-234`); a bridge can never produce one. The gap channel is
whole-probe granularity; the divergence channel requires a `port_value` and the port
has no value. So requirement 1 holds for probes a port omits **wholesale**, and
inverts for a probe that is answerable in general but not for a specific input.

So the honest reading of the coverage line is: **18/30 as the tool computes it,
17/30 once you disallow the bridge's synthesized zero.** Both numbers should be
stated when this build is discussed.

Cross-check: the w0b lineage pack against the same port reports **0/33 answered,
33/33 unanswerable, coverage 0.0%, value 0/0** — the shape of a wrong-pack run, not
a false green.

---

## 3. The honesty requirements under attack — two were broken

Every attack below was **run**, with real subprocess bridges, against the shipped
code. All mutated artifacts are SANDBOX under
`/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/16b09ed7-6185-46f1-b167-14accfadbd96/scratchpad/`.
The repo working tree is byte-identical to what the builder left; recorded packs
untouched.

### 3.1 BROKEN — a divergence declaration is an unbounded blank cheque

A validator wrote a **liar port** (25-line `python3` bridge, declares the full
glossary, answers every numeric probe `999`, every string `"LIE"`, every boolean
`true`).

Undeclared, the tool judged it correctly: `coverage 30/30 = 100.0%,
value 0/30 = 0.0%, failed 30, exit 1`.

Then 30 `Divergence` entries were generated mechanically — one per assertion,
`port_value` set to the liar's constant, `reason` the free-text string
`"kernel v1.2 sanctions this"`, **`decision_id` omitted entirely** — and pasted into
`port.manifest.json`. Same bridge, same pack:

```
passed 0 / diverged (ok) 30 / failed 0
coverage 30/30 = 100.0%
value    30/30 = 100.0%
clean = true
exit 0
```

**A port that gets every observed value wrong is indistinguishable, by exit code and
by `clean`, from a port that gets every value right.** Confirmed in the code today:

- `port_contract.py:172` requires only `d.reason.strip()`. `decision_id: str = ""`
  (line 83) is never required, never resolved, never checked against any registry —
  a sanction need not point at anything.
- `port_verify.py:144` — `value_score = (scored_passed + scored_diverged) /
  scored_answered`. Declaring is **arithmetically identical to passing**.
- `port_verify.py:172-177` — `clean` is computed from `scored_failed`,
  `unanswerable` and `declaration_problems` only. The divergence count is ignored
  by the machine verdict entirely.
- Nothing bounds what fraction of a pack may be sanctioned.

The only surviving signal is the parenthetical `(30 sanctioned divergences)` inside
`headline()` — a human-readable aside on a run whose machine verdict is green.
Requirement 2's "never let 'it's the divergence' be a runtime excuse" is enforced
against *inference at scoring time* and not at all against *unbacked declaration up
front*. And the declarer always knows what to declare, because `--json` prints every
`actual`; the 30 sanctions were generated from a prior run's output in ten lines of
Python.

### 3.2 BROKEN — a `--marks` file erases real failures and exits 0

Same liar port, divergences removed, plus a 12-line marks file marking every fixture
`{"corroboration_only": true}` with **no `reason` field at all**:

```
answered 30, scored 0 (30 answered but excluded from scoring)
passed 0 / diverged 0 / failed 0
coverage 30/30 = 100.0%
value    0/0
exit 0
```

Two compounding defects, both confirmed in the code today:

1. `load_marks()` (`port_contract.py:200-218`) does `FixtureMark.model_validate(r)`
   and **nothing else**. It never applies the reason check that `PortManifest.check()`
   applies to in-manifest marks (`port_contract.py:181`: *"excluding a fixture from
   the score requires a reason"*). The external path — which `verify_port`
   documents as the one that **wins** — is the **unvalidated** path.
2. `clean` treats an empty denominator as innocent. `scored_answered == 0` prints a
   bare `value : 0/0` and exits 0.

A partial version works on the **real** build: with a genuine bug injected
(`port_bridge.ts` `+ 1`), the honest run is `failed 11, value 6/17 = 35.3%, exit 1`;
marking the 10 fixtures containing failures corroboration-only — with the free-text
reason "value depends on source insertion order", which is simply false for those
fixtures — gives `failed 0, value 0/0, exit 3`.

Requirement 3 is enforced as *"a mark excludes"* but never as *"a mark must be
earned"*. Nothing cross-checks the claim, and nothing stops the person **running**
the tool, who need not be the port's author, from supplying the marks file.

Two related weaknesses on the same channel:

- **Marks are silently optional.** Running the same real pack and port **without**
  `--marks` gives `scored 18 / passed 18 / value 18/18 = 100.0%` and says nothing
  about a marks file existing or being expected. At 100+ features a forgotten flag
  is a 100%-green report.
- **Exclusion is fixture-granular and swallows unrelated failures.** On a liar port
  that returns 999 for `adjustment_count`, fixture `d9778c65`'s
  `[FAIL] adjustment_count expected == 3, got 999 - undeclared mismatch` is printed
  but counted nowhere. `adjustment_count` is a count and has nothing to do with the
  insertion-order fingerprint that justified the mark (`stock_on_hand == 3.0`).

### 3.3 HELD — gaps cannot become passes

Attacked twice, held twice.

Injected a real port bug (`port_bridge.ts`, `return row ? row.value : 0;` →
`+ 1`): honest verdict `passed 6 / failed 11, value 6/17 = 35.3%, exit 1`, each
failure printed as `[FAIL] stock_on_hand(bin) expected == 3.0, got 4.0 - undeclared
mismatch`. Then removed `stock_on_hand` from **both** the manifest and the bridge's
`describe` (both, because they must agree): `answered 6, UNANSWERABLE 24,
coverage 6/30 = 20.0%, value 6/6 = 100.0%`, **exit 3**. The 11 failures did not
disappear — they became 12 more printed `[GAP ]` lines, coverage halved, exit stayed
non-zero.

A null port (zero operations, zero probes): `11 of 12 fixtures could not run,
answered 0, UNANSWERABLE 30, coverage 0.0%`, exit 3. **No arithmetic path produces a
flattering number from an empty surface.**

`Unanswerable` deliberately not subclassing `AdapterError` is what makes this
structural: no `except AdapterError` can convert it to a value, and the judge has no
branch from `Unanswerable` to `PASSED`.

Residual, cosmetic: `value 6/6 = 100.0%` is quotable in isolation, but coverage is
printed on the adjacent line and the headline refuses to blend them.

Caveat carried from §2: this holds at **whole-probe** granularity only. The
sub-probe hole (a port that can answer a probe in general but not for one input) is
the requirement-1 shortfall, and it is the same failure class that inflated 24/30,
surviving at finer granularity.

### 3.4 HELD — the narrower declaration paths

All exercised by running, not reading:

- **Manifest/bridge disagreement → hard refusal.** `port bridge unusable: port
  manifest and running bridge disagree about the probe surface (...). Refusing to
  pick one: a capability claim must be unambiguous.` exit 2, nothing judged. This is
  why the undeclare attack had to edit both files, and it forecloses "declare
  little, answer much".
- **A sanction covers exactly one value.** A mis-targeted declaration produced
  `[FAIL] ... declared divergence expects 9.0 but the port delivered 2.0 — a
  sanction covers ONE stated value, not any deviation`.
- **A declared capability the bridge refuses** → `FalseDeclaration` → FAIL +
  declaration problem, never a gap.
- **Stale or orphaned declarations** → `declaration_problems`, exit 3
  (`! divergence declared for '8605ff05', which is not in this pack`).
- **Undeclared mismatch** → `[FAIL] ... undeclared mismatch`, exit 1.

---

## 4. Per-feature work for a wave-1 feature

### DECLARATION — acceptable at scale

- **`port.manifest.json`** — the port states which operations and probes it offers,
  plus any sanctioned divergences and (today) fixture marks. Pure data, reviewable,
  versioned next to the build.
- **The marks file**, where a fixture's value encodes source ordering.

Proven at scale by construction: a validator's from-scratch Python port needed a
12-line manifest and ran first try.

### CODE — the port's own, and the right place for it

- **One bridge** (`port_bridge.ts` / `bridge.py` / anything that speaks
  line-delimited JSON on stdio). ~95 lines for a full inventory port; ~30 lines for
  a small logs port.

This is the honest caveat the design does **not** close: the per-feature harness did
not disappear, it moved into the port as the bridge — where it is at least declared,
versioned and reviewable. The w0a bridge's header admits one mapping judgement (an
unreported `(measure, unit)` pair reads as stock `0`) — commendably stated rather
than buried, and §2 shows exactly how that judgement masks a port bug. **There is no
mechanism that makes a bridge author state such judgements.** At 100 bridges,
unstated ones will exist.

### CODE — the actual bottleneck, and it is not the judge

A **new glossary term** costs edits in 8–9 files: `glossary.py`, `probes.py`,
`adapter.py`, `farmos_adapter.py`, `port_adapter.py`, `fixtures.py`, `recorder.py`,
`steps.py`, `data/w0_flows.json`. History says this is the norm: w0a added 2 actions
+ 3 assertions, w0b added 4 actions + 5 assertions — **14 of the 25 current terms
came from two features.** `port_adapter.py`'s 15 probe methods are already ~150
lines of identical gate-then-call-then-coerce.

This is mechanically removable and isn't yet. Every probe method is
`self._need_probe(T); return COERCE(self._bridge.call(T, SUBJKEY=h, **params))`.
Only two things vary and neither is in `ProbeSpec`: the subject wire key
(`asset`/`log`/`animal`) and the result coercion. Add `subject_key` and
`result_type` to `ProbeSpec` and `PortAdapter` collapses to a `__getattr__` over the
table — a new term becomes **a row, not nine files**.

The write side is only half-tabled and its tabled half is **dead**:
`OPERATION_CONTRACT` is a checklist of required method names, while real dispatch is
still the 45-line `if/elif` in `steps.py:apply_when`. `methods_when_timed` and
`methods_for_action(timed=True)` are called from nowhere — `port_verify.py:252`
calls `methods_for_action(w.action)` untimed, for a truthiness check. Not a
correctness bug today (a synthetic timed fixture was caught at runtime as a GAP,
exit 3), but pre-flight and runtime now disagree about what "runnable" means, and
the next action whose helper calls an ungated method will slip through.

---

## 5. Blockers moved

**B2 — reduced from BLOCKER to a short fix list; not closed.** The tool and the
probe-surface contract both exist, the artisanal harness is gone, judgement is one
auditable command, and the hand judgement reproduces. But §3.1 and §3.2 mean a
CI-visible green from `port-verify` does not yet imply a correct port. B2 stays open
until fixes 1–4 land and the attack suite is re-run.

**B4 — partially addressed, schema half still open.** B4 has two limbs. The
corroboration-only / order-sensitive limb now has a working mechanism — the marked
fixture runs, reports its real outcome, and contributes to neither numerator nor
denominator even when it matches. But the mark lives **outside** the pack in an
external `--marks` file (deliberate: a pack is evidence and `fixture_id` hashes must
stay stable), and §3.2 shows that path is the unvalidated one and is silently
optional. **B4's schema-level flag remains open**, and B4's other limb — relative
`at` plus a timestamp-returning probe yielding non-reproducible fixtures — is
**untouched by this work**.

**B5 — untouched.** The status gate is still a feature-local constant, the
behavioural sub-taxonomy still unregistered with a silent catch-all decrement, the
projection still not kind-guarded. `port-verify` judges a port against observed
fixtures; it does not close a prevention gate. One small adjacency: `contract_gaps()`
plus the glossary tripwire test is the same *kind* of gate, in a different place, and
is a template for what B5 wants.

**B1 and B3 — untouched, and B1 is unaffected by anything here.** `port-verify`
scores a port against fixtures; it cannot tell you a bound decision is false.

**Also-required from the readiness report, now measured rather than asserted:** the
w0a build still owes `adjustment_count`, a `log_status` read, and the two
restatement verbs. The tool reports that as **12 gaps**, per fixture, by name,
instead of hiding it inside 24/30.

### The next bottleneck

**Not the judge — the glossary.** Every feature needing a new domain term is a
9-file code change, and wave-0 evidence says features do need new terms. Behind that,
two operational hazards that only bite at wave scale:

- **A bridge hang is an unbounded hang.** `BridgeSpec.timeout` is used in exactly
  one place — `PortBridge.stop()`'s `proc.wait` (`port_adapter.py:157`). `call()`
  does a bare blocking `proc.stdout.readline()` (`port_adapter.py:121`). Proven: a
  bridge that is `time.sleep(10000)` with a declared timeout of 2.0s ran until an
  external `timeout 20` killed it. One port with a blocked DB connection wedges an
  unattended CI job forever.
- **An over-declared capability is only caught if a fixture exercises it.** A
  manifest claiming `log_count` that the bridge refuses exits 0 and reports clean,
  because the w0a pack asserts no `log_count`. Harmless for the score, but the
  manifest will be read as a wave-level inventory of what a build offers, and as such
  it is unvalidated. A `ctkr port-selftest` pinging every declared op/probe once
  would close it.

---

## 6. Fixes, ranked

1. **Make `decision_id` required and non-empty on `Divergence`, and resolve it
   against the decision log.** An unresolvable id is a `declaration_problem`, not a
   sanction. (Breaks §3.1's blank cheque.)
2. **Make a green run disclose what it rode on.** Report `scored_diverged` on its
   own line, and make `clean`/exit-0 conditional on it — either exit 3 whenever
   `scored_diverged > 0`, or require an explicit `--accept-divergences N`.
3. **Have `load_marks()` apply the same reason validation `PortManifest.check()`
   applies**, record marks provenance (manifest vs file, with the path) in the
   report, print `marks: none supplied` when there are none, and look for
   `<pack>-fixture-marks.json` by convention. (Breaks §3.2 and the
   forgotten-flag hazard.)
4. **Treat `scored_answered == 0` as not-clean.** An empty denominator must never
   exit 0.
5. **Add a per-call unanswerable channel** — let a bridge return
   `{ok: true, unanswerable: true, reason: ...}` recorded as a GAP, or add
   assertion-granular gap declaration to `PortManifest`. Until then, fabricating a
   plausible value is the only unpunished route and the tool hands port authors the
   incentive that produced 24/30.
6. **Make marks assertion-granular**, so a mark excludes only the tainted probe
   rather than every assertion in the fixture.
7. **Bound `PortBridge.call()` with `manifest.bridge.timeout`** and raise
   `BridgeError`.
8. **Generate `PortAdapter` from `PROBE_CONTRACT`** (`subject_key` + `result_type`
   on `ProbeSpec`); table `apply_when` the same way or delete the unused
   `methods_when_timed`. Turns "a new term is nine files" into "a new term is a row".
9. **Require a `judgements: []` array in `port.manifest.json`** — empty means "this
   bridge is a pure pass-through and I assert it" — so bridge-author silence becomes
   a claim rather than an absence. Zero runtime cost.
10. **Document the four mandatory-but-undeclared protocol ops** (`describe`,
    `reset`, `close`, `create_asset`) as a bridge-author checklist in
    `docs/design/port-verify.md`.
11. **`ctkr port-selftest`** — ping every declared op/probe once, so an over-declared
    manifest fails before a pack ever runs.

Fixes 1–4 are the blocking set. None is architectural.

---

## 7. Test and artifact state

- Python: **564 passed, 3 skipped** (was 540/3 — the +24 hermetic `port-verify`
  tests). Re-verified independently.
- TypeScript: **472 pass, 0 fail**, unchanged. The w0a build's own `bun test`: 11 pass.
- `ruff check` clean on every file touched.
- `git status --short`: only the 10 new files plus modified
  `ctkr/ctkr/oracle/runner.py`. **Recorded fixture packs untouched.** Nothing
  committed.
- Everything in §1.2 is at a **production repo path**. Every adversarial variant is
  **SANDBOX**, under
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/16b09ed7-6185-46f1-b167-14accfadbd96/scratchpad/`
  (`liar`, `falsedecl`, `refuse`, `percall`, `atk`, `null-port`, `pyport`,
  `logport`, `hang`) — none to be promoted, all touching nothing under the repo.

---

## 8. Verdict — is the JUDGE stage wave-scalable?

**Architecturally yes. Operationally not yet. Do not close `MetaCoding-kgu` on the
current numbers.**

What is genuinely fixed. The blocker B2 named is gone: a fresh agent who did not
write the tool verified a build they had never seen with two commands and no
throwaway harness, then verified two ports of their own — one in a different
language with a different module layout — without touching a line of the verifier.
The four-bucket score is the right structure; exit 3 makes an unverified build
unable to look green; the probe-surface contract makes it impossible to record an
assertion no implementation could be asked; and honesty requirement 1 is structural
rather than conventional at whole-probe granularity, which two independent attacks
confirmed by trying to break it and failing.

What is not. Requirements 2 and 3 are enforced only against inference at scoring
time, never against the declarations themselves, and **both declaration channels are
writable by whoever runs the tool** — who need not be the port's author. Two
reproduced attacks turn a 100%-wrong port into a green, `clean: true`, exit-0 run:
30 free-text divergences with no `decision_id`, and a reason-less external marks file.
In both, the CI-visible verdict of a totally broken port is identical to that of a
correct one. Separately, the one representational divergence the hand judgement
found is scored as a PASS, because every honest way for a bridge to say "I cannot
answer THIS call" is punished with a FAIL while fabricating a plausible value is
rewarded — the same incentive that inflated 24/30, one level down.

The honest w0a headline is therefore: **coverage 18/30 = 60.0% as the tool computes
it, 17/30 once the bridge's synthesized zero is disallowed; value 17/17 = 100.0%
over what the build can answer; exit 3.** The build is exact wherever it can speak
and silent over 40% of the pack — which is what the hand judgement said, now
reproducible in one command.

Land fixes 1–4, re-run the §3 attack suite, and the JUDGE stage is ready to carry
100 features. Until then it is a very good instrument with two open channels through
which a wave could be declared green without earning it — and at 100 features,
"could be" means "will be".

---

## Addendum — the two CRITICAL holes are closed (same day)

The adversarial validator broke this tool twice. Both are fixed, and each attack is
now a regression test.

| attack | before | after |
|---|---|---|
| Liar port (answers `999`/`"LIE"`/`true`) + 30 divergences, free-text reasons, **no `decision_id`** | `value 30/30 = 100%`, `clean=true`, **exit 0** | `reproduced 0/6 = 0.0%`, 34 declaration problems, **exit 1** |
| `--marks` file excluding every fixture, **no reasons** | `failed 0`, **exit 0** | rejected at load, **exit 2** |
| …same, *with* plausible reasons | `failed 0`, exit 0 | `NOTHING SCORED — this run is evidence of nothing`, **exit 3** |
| Port fabricates `0` for an unheld pair | scored `[PASS]`, 12/30 unanswerable | **GAP**, 13/30 unanswerable — matches the hand judgement exactly |

**What changed**

1. `decision_id` is **required and resolved** against a decision registry
   (`--decisions`, default the kernel CM registry). A sanction naming a decision no
   registry knows is a declaration problem. Free-text reasoning is no longer a warrant.
2. **Divergences left the numerator.** `value_score = passed ÷ (scored − diverged)`.
   Declaring is no longer arithmetically identical to reproducing, and sanctioned
   divergences now *block* `clean`: a port that deliberately differs is value-equivalent
   **modulo a declared exception**, which is a different claim and now reads as one.
3. **An empty denominator is never innocent.** `scored_nothing` makes a run that
   excluded or sanctioned everything report *"this run is evidence of nothing"*.
4. **The external marks path is validated** — it wins over in-manifest marks, so it
   must be the best-checked path, not the unchecked one. Exclusions cost a reason, and
   the marks file's path is recorded in the report so a reader can see the score was
   shaped by a caller-supplied file.
5. **Per-call unanswerable channel** (`{"ok":false,"unanswerable":…}`). A port may
   implement a probe in general yet decline one input. Without it, every honest option
   scored as a failure and **fabricating a value was the only unpunished move** — which
   is exactly how the one real representational divergence (farmOS `0.0` vs the port's
   absent row) scored as a clean pass. The w0a bridge now declines it honestly.

Robustness, found while re-attacking: a bridge answering `describe` with a non-object
crashed with `AttributeError`, and an ambiguous sanction raised an uncaught `ValueError`
mid-run. Both are now clean errors; ambiguity degrades to "no divergence", so it can
never excuse a wrong value.

**The w0a build, re-judged honestly:** 17/30 answered, **13/30 unanswerable**,
16/16 reproduced (100%), 1 corroboration-only excluded, exit 3. The unanswerable count
now agrees with the three hand harnesses exactly — the disagreement *was* the bug.

Tests: 571 py / 3 skipped (+7 honesty regressions), 472 TS.
