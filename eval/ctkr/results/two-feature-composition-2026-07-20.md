# Two-feature composition run — do per-feature ports COMPOSE? (MetaCoding-9h5.16)

> Bead MetaCoding-9h5.16 · 2026-07-20 · the second-opinion's **experiment 3 / R1**
> (second-opinion-2026-07-20.md §R1): *"Per-feature passes don't compose. All
> experiments build isolated stores. The target is one event log, one asset model,
> one ID scheme shared by features whose projections overlap."* This is the
> smallest honest model of the 147-feature fan-out: take the two features that
> already have hardened packs — **logs+quantities** (9h5.8, 17 fixtures) and
> **location+movement** (9h5.11, 10 fixtures) — hand BOTH contracts + BOTH packs +
> the target profile to ONE fresh blind Sonnet builder instructed to build a
> SINGLE unified store, then judge both packs against it, add judge-authored
> cross-feature probes on the shared state, and count how the prior isolated
> builds' design decisions agree or conflict.

## Bottom line

- **The composition worked — one store, both features, no value regression.**
  A single blind Sonnet builder, given both contracts and both packs, produced ONE
  append-only event log with two thin adapter views that scores **17/17 on the
  logs pack AND 10/10 on the location pack (27/27 total)** on the *independent*
  runners, plus **5/5 on judge-authored cross-feature probes** that exercise shared
  state the isolated runs never touched. Composition, on this 2-feature slice, is
  **feasible for a single builder in one pass** — the store idioms (event log +
  materialized views + latest-wins fold) are uniform enough that both features fall
  out of one design.
- **But that is exactly the point R1 makes: the danger is not one builder, it is
  N builders.** The composed build is coherent *because one mind made every
  overlapping decision at once*. The decision-conflict audit shows that the **seven
  prior isolated builds, given identical inputs, diverged on every shared axis** —
  and several of those divergences are silently value-incompatible when folded into
  one store. Two features can each go 17/17 and 10/10 in isolation while encoding
  **mutually incompatible** answers to "how does latest-wins work," "what is an ID,"
  and "does pending count." The composition run makes those conflicts concrete.
- **The shared kernel R1 asks for is not optional — it is the difference between
  this run's 27/27 and a fan-out of locally-valid, globally-incoherent modules.**
  Section "Shared-kernel prescription" below names the five kernel elements that
  MUST be frozen before wave 1, each justified by a specific divergence observed
  (not a hypothetical): the event schema, the ID/HLC scheme, the single latest-wins
  comparator, the status-semantics contract, and a binding CM-decision registry.

## 1. Design of this run (honesty first)

- **ONE composed blind build.** A single fresh Sonnet builder in an isolated
  sandbox, forbidden from farmOS source, the MetaCoding repo, and every prior
  build/cell dir; given only the two adapter contracts, the two fixture packs (27
  fixtures), the target profile, and a BUILD_INSTRUCTIONS demanding a single event
  log / asset model / ID scheme with both adapters as thin views. `n=1`; no spread.
- **Independent judges.** The two pack runners are the **verbatim, unmodified**
  runners from 9h5.8 (`runFixturesLogs.ts`) and 9h5.11 (`runFixturesLocation.ts`),
  driven through two 3-line shims (`logsEntry.ts`, `locationEntry.ts`) that return
  `createComposedStore().logs` / `.location`. The builder never saw the runners.
- **Cross-probes are JUDGE-AUTHORED and MECHANICAL, not new oracle observations.**
  Each of the 5 probes is a hand derivation from semantics **already observed in
  the two packs**, re-applied to ONE `createComposedStore()` to test the sharing
  property. No probe records a new value from live farmOS. Where a probe asserts a
  value (e.g. yield 5, at-location B), that value is copied from an existing fixture
  rule, only the *composition* (same handle, same store, interleaved events) is new.
  The live oracle (farmOS Docker) was **not** consulted; no `m16-` entities were
  created — no probe needed a genuinely new observation.
- **"Teaching to the test" caveat, unchanged from the 9h5 line.** The latest-wins
  and tie-break fixtures the composed build passes were literally in the packs it
  was given. The genuinely new signal here is (a) both packs pass *simultaneously
  on one store*, (b) the shared-state cross-probes pass, and (c) the decision-
  conflict audit — not "can a builder discover these unaided" (that is 9h5.8 Cell 4).

## 2. Per-pack results (independent runners, composed `.logs` / `.location`)

| pack | fixtures | non-obvious | result | via |
|---|---|---|---|---|
| **logs+quantities** (9h5.8 hardened) | 17 | ce015be4 latest-wins + 6 yield/status | **17/17** | `runFixturesLogs.ts` → `.logs` |
| **location+movement** (9h5.11) | 10 | 7 (pending/future/fixed/tie-break/…) | **10/10** | `runFixturesLocation.ts` → `.location` |
| **composed total** | **27** | 13 | **27/27** | one `createComposedStore()` per fixture |

Notably the composed build passes **ce015be4** (group-reassignment latest-wins) —
the single fixture the *original* 0p7/cell-a/cell-b logs builds all FAILED (they
modeled membership additively). The composed builder, having also to satisfy the
location pack's latest-wins reads, reached for a general `pickLatest` fold and got
membership latest-wins "for free." Composition **helped** correctness on this one
axis: the second feature's semantics pushed the builder toward the general rule.

## 3. Cross-feature probes (judge-authored, mechanical; ONE shared store) — 5/5

These are the thing isolated runs never tested: shared state read by both adapters.

| # | probe | what it proves | basis (existing fixtures) | result |
|---|---|---|---|---|
| **CP1** | One asset harvested via `.logs` AND moved via `.location`; asset minted by each adapter usable by the other (both directions) | one asset model, one ID space, both projections read the same entity | logs 74303d7d + location 95de1fa8 | **PASS** |
| **CP2** | Harvest + movement on one asset: `logCount('harvest')==1`, yield unaffected; movement NOT counted as a log kind | kind-filtered folds isolated over the shared log; **surfaces a design choice** (see below) | logs fba4a962/03e4dd80 | **PASS** |
| **CP3** | Move asset, harvest it, then `archiveAsset`: `assetActive==false` yet location history + yield remain readable | one archive event flips one projection, leaves the others' history intact | logs 680138d8 extended to the shared log | **PASS** |
| **CP4** | Interleave assign→G1, move→A@10, assign→G2, move→B@20 on one log: member=G2 (not G1), location=B (not A) | two independent latest-wins folds over one interleaved log don't interfere | logs ce015be4 + location 885eecc6 | **PASS** |
| **CP5** | Same-timestamp movements → later-recorded wins; un-timestamped group reassign → insertion-order wins — in ONE store | a **single** `(timestamp,seq)` comparator serves both timestamped and un-timestamped latest-wins | location 43a074ca + logs ce015be4 | **PASS** |

**CP2 is the most informative.** The task's illustrative probe was *"a movement log
and a harvest log both count in logCount-by-kind."* The composed builder chose the
opposite: a movement is a **distinct event kind** (`movement_recorded`), NOT a
`log_recorded`, so it never appears in `logCount(asset, kind)`. That is a legitimate,
internally-consistent composition decision — but it is *a decision*, made freely,
and a different blind builder could just as easily have modeled a movement as an
`activity` log (which is what farmOS actually does — movements are activity logs
with `is_movement`). Under the fan-out, feature A's author calling movements "not
logs" and feature B's author calling them "activity logs" would **disagree on
`logCount('activity')`** for the same asset while both passing their own packs. CP2
passes here only because one builder made both calls; it is a latent conflict, not a
resolved one. (This is logged as a kernel item: the event-kind taxonomy must be
frozen, not left to per-feature discretion.)

## 4. Decision-conflict audit — identical inputs, divergent architectures

Comparing the composed build's PORT_DECISIONS.md against the seven prior **isolated**
builds' decisions (0p7 `port-decisions.jsonl`+`PORT_DECISIONS.md`; 9h5.4 cell-a,
cell-b; 9h5.8 cell1/cell2/cell4 READMEs; 9h5.11 builderN, builderG). "—" = the
build's feature/scope did not touch that axis.

| axis | 0p7 (logs) | cell-a (logs) | cell-b (logs) | cell1/2 (logs) | cell4 (logs, pure-LLM) | m11-N (loc) | m11-G (loc) | **composed (both)** | verdict |
|---|---|---|---|---|---|---|---|---|---|
| **birth-uniqueness** | **weaken-to-eventual** | preserve-via-conv (min UUID/log-id wins) | preserve-via-conv (min seq, then handle) | — | — | — | — | **preserve-via-conv** (earliest `(ts,seq)`; demote loser→observation) | **CONFLICT** on the menu choice itself (weaken vs preserve) + 3 different convergence mechanics among the "agreeing" preservers |
| **tie-break scheme** | client UUID handles; membership by event order | `(timestamp, append-seq)`; flags need HLC/UUID | `(timestamp, local seq)`; flags need UUID/HLC | last-write (insertion order) | LWW scalar | `(timestamp desc, recording-order desc)`; swap for HLC/UUID | `(timestamp, seq)`; flags need UUID/HLC | `(timestamp, seq)`, ts degenerates to seq when absent | **AGREE in shape** (all = timestamp then insertion-seq) — but **ALL SEVEN independently flag `seq` as NOT multi-replica-safe and defer the real HLC/UUID rule.** Unanimous punt = a kernel gap, not a solved problem |
| **ID minting** | client UUID-style `asset_`/`log_`, keyed on uuid, serial never crosses sync | client-gen | client-gen | ts+random+counter | client `makeId` | client handle | client handle | **plain integer counter** `asset_7` | **CONFLICT / REGRESSION**: composed's `${prefix}_${seq}` is collision-prone across replicas (two replicas both mint `asset_1`) — the exact `autoincrement-id` anti-pattern the profile warns against. 0p7/cell1 used random/uuid components; composition *lost* that property |
| **membership model** | **additive** (any assignment ⇒ member) → FAILS ce015be4 | **additive** → FAILS ce015be4 | **additive** → FAILS ce015be4 | **latest-wins scalar** → passes | latest-wins scalar → passes | — (no group in loc pack) | — | **latest-wins via `pickLatest`** → passes | **CONFLICT**: additive vs latest-wins, from identical inputs — a second concrete divergence beyond birth. Composition forced latest-wins (helped) |
| **pending/status** | pending contributes to yield & count | pending contributes | pending contributes | pending contributes | **pending EXCLUDED from yield** → FAILS 73ed7c69/d8607818 | pending movement inert (location) | pending movement inert | pending log contributes; pending movement inert — **both, on one status field** | **CONFLICT**: cell4 gates yield on `done`; all logs builds don't. AND status means *opposite* things across the two features — only the composed build had to (and did) hold both at once |

### What this quantifies for R1

R1's headline evidence was one divergence ("0p7 weaken-to-eventual vs both ablation
cells preserve-via-convergence-rule"). This audit finds that divergence **plus three
more**, all from identical inputs:

1. **birth-uniqueness**: menu choice splits (weaken vs preserve), and even the
   preservers disagree on the convergence mechanic (min-UUID vs min-seq vs
   earliest-`(ts,seq)`-then-demote). **3 distinct architectures for one invariant.**
2. **membership**: additive (3 builds) vs latest-wins (4 builds). Two builds
   (0p7, cell-a) that are otherwise "reference" builds get ce015be4 **wrong**, so a
   fan-out that reused 0p7's membership projection would be globally wrong the moment
   a location or inventory feature folded the same group events.
3. **ID scheme**: UUID/random (portable) vs integer counter (collides on merge).
   The composed build itself picked the *non-portable* option — showing the drift
   is not a "bad builder" artifact but the default attractor absent a kernel rule.
4. **status**: one build (cell4) gates yield on `done`; the composition has to carry
   two opposite readings of `status` and only works because one builder reconciled
   them.

The tie-break axis is the instructive counter-example: all seven builds *agree* on
the shape `(timestamp, insertion-seq)` — **and all seven independently write down
that this is a placeholder that must become an HLC/UUID before multi-replica sync.**
That unanimous deferral is the strongest signal in the whole 9h5 line that the
cross-replica clock belongs in the shared kernel: every isolated builder correctly
identifies the gap and correctly declines to fill it alone, because it cannot be
filled locally — it is a global decision by construction.

## 5. Shared-kernel prescription — what MUST ship before wave 1

Concrete, from what actually diverged or regressed above (not hypothetical):

1. **Frozen event schema + event-kind taxonomy.** One append-only log; a closed,
   named set of event kinds with fixed field shapes, decided centrally. Must
   explicitly resolve **is a movement a log?** (CP2's latent conflict) and the
   birth/asset/quantity event shapes. Without it, feature authors invent
   incompatible kinds (`movement_recorded` vs `activity` log) that break shared
   reads like `logCount`. — *justified by CP2 + the ID/membership divergences.*
2. **ID / identity + hybrid-logical-clock scheme.** Client-generated, collision-free
   IDs (UUID or replica-id+counter) — NOT the bare integer counter the composed
   build defaulted to. And the **HLC** that all seven builds punted on: define the
   real cross-replica ordering key once, so `(timestamp, seq)` stops being a local
   placeholder. Serial ordinals must never cross the sync boundary. — *justified by
   the ID-scheme regression + the unanimous tie-break deferral.*
3. **One latest-wins comparator, in the kernel.** A single `pickLatest`/LWW-register
   primitive keyed on the HLC above, used by EVERY overlapping projection (group
   membership, current location, log status, intrinsic geometry, and future
   inventory/lineage). The composed build already proves one comparator serves both
   timestamped and un-timestamped reads (CP5); the kernel must own it so features
   can't re-derive membership additively (the 0p7/cell-a bug). — *justified by the
   membership divergence + CP4/CP5.*
4. **Status-semantics contract.** `status` (pending|done|…) is one shared field, but
   each projection's gate is a **declared, reviewed** decision: pending logs count
   toward yield/logCount; pending movements do not apply to current location. Freeze
   which projections are status-gated so a fan-out author can't re-litigate it
   (cell4 gated yield on `done` and was wrong). — *justified by the pending/status
   conflict.*
5. **Binding CM-decision registry.** The birth-uniqueness split (weaken vs preserve,
   and three convergence mechanics) is the proof that the target-profile *menu* is
   not enough — it offers legal options and blind builders pick different ones from
   identical inputs. The kernel needs a **registry that binds each hard/soft
   invariant to ONE chosen menu option AND its exact convergence rule** (which key
   wins, what happens to the loser), consumed by every feature build. This is the
   single highest-leverage kernel artifact: it is where "locally valid, globally
   incompatible" is actually prevented. — *justified by the birth-uniqueness 3-way
   split, the R1 headline.*

**Verdict on R1.** Confirmed and sharpened. Per-feature passes **do** compose when
one builder owns the overlap — 27/27 + 5/5 here proves the target architecture is
coherent and a unified store is buildable. They **do not** compose across
independent blind builders: identical inputs produced divergent, sometimes value-
incompatible architectures on four of five shared axes, and the composed build
itself regressed the ID scheme to a non-portable ordinal. The fan-out's real
product — one log, one asset model, one ID scheme — cannot be assembled from 147
independently-decided ports. The five kernel elements above must be frozen and fed
to every wave-1 builder as fixed inputs, not menu options.

## 6. Honesty notes

- **Single composed build (`n=1`).** One blind Sonnet build; no variance measured.
  The prior seven builds are re-read (read-only) from their sandboxes, not rebuilt.
- **Cross-probes are judge-authored mechanical derivations**, labeled per-probe with
  the existing fixture they derive from; none is a new live-oracle observation. No
  `m16-` entities created; farmOS Docker not consulted this run.
- **The composed build passing latest-wins/tie-break is partly teaching-to-the-test**
  — those fixtures were in its inputs. The novel signals are simultaneous 27/27,
  shared-state cross-probes, and the conflict audit.
- **CP2 records a design choice, not a farmOS ground truth**: this builder excludes
  movements from `logCount`; farmOS itself models movements as activity logs. The
  probe passes against the builder's own consistent choice and is flagged as a latent
  cross-feature conflict, not a validated equivalence.
- **The decision-conflict audit reads prior builds' self-reported decisions**
  (PORT_DECISIONS.md / README). Where a build's pack score corroborates the decision
  (e.g. additive membership ⇒ ce015be4 fail), that is noted; a few axes (cell1/cell2
  birth) were simply not documented and are marked "—", not inferred.
- **Spend:** one Sonnet builder (~$0.20–0.35 est., not metered; 94k subagent tokens,
  22 tool calls, 30 own tests green) + LM-free judging. Well under the $3 cap.

## 7. Artifacts & paths (ALL sandbox unless noted)

- **In-repo committed (this run):**
  - `eval/ctkr/results/two-feature-composition-2026-07-20.md` (this report)
  - `eval/ctkr/port_runs/compose-9h5.16/` — committed copies of the composed build
    (`build/src/*.ts`, `build/test/*.ts`, `build/PORT_DECISIONS.md`,
    `package.json`, `tsconfig.json`), the judge (`judge/runFixturesLogs.ts`,
    `runFixturesLocation.ts`, `logsEntry.ts`, `locationEntry.ts`, `crossProbes.ts`),
    and `COMPOSED_BUILD_INSTRUCTIONS.md`. No `.metacoding/` data-dir created/mutated.
- **Composed-build workspace (SANDBOX):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/compose-9h5.16/`
  — `builder-inputs/` (both contracts + both packs + profile + instructions),
  `build/` (the blind build; `bun test` = 30 pass / 0 fail), `judge/`.
- **Inputs consumed (SANDBOX/in-repo, read-only):**
  logs pack `matrix-9h5.8/FIXTURES_HARDENED.jsonl` (17) + contract
  `453fbf17-…/port-run-0p7/builder-inputs/ADAPTER_CONTRACT.md`; location pack
  `7c92fede-…/m11/FIXTURES.jsonl` (10) + `m11/ADAPTER_SIGNATURES.md`; profile
  `docs/design/target-profiles/farmos-local-first.yaml` (in-repo).
- **Prior isolated builds audited (SANDBOX, read-only):**
  `453fbf17-…/port-run-0p7/` (0p7), `7c92fede-…/cell-a`, `cell-b`,
  `7c92fede-…/matrix-9h5.8/cell1|cell2|cell4`, `7c92fede-…/m11/builderN|builderG`.
- **Live oracle:** NOT used this run (no new observations needed).

Worktree branch: `worktree-agent-ad0d50ae24376c850`. No push/merge; bead
MetaCoding-9h5.16 left open.
