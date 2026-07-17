# Vertical slice — farmOS logs+quantities → local-first port (MetaCoding-0p7)

**The port-loop convergence milestone** (`docs/design/port-loop-plan.md` Phase 4):
`farmOS logs+quantities → port brief → blind build → three-way verify → calibration`.
First end-to-end run of the whole pipeline against a live target.

- **Date:** 2026-07-18
- **Source graph:** full-signal farmOS v2 (sandbox) `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2` — 8,059 nodes / 11,499 edges.
- **Target profile:** `docs/design/target-profiles/farmos-local-first.yaml` (event-log + materialized-views, eventual consistency, selective disclosure).
- **Total LLM spend:** **$0.2593** across 43 calls (haiku 29 = $0.069, sonnet-class 14 = $0.191). Budget was ≤$15; came in at **1.7%** of cap — scoping the pipeline to the two domain subsystems is what made it cheap.
- **All ports/artifacts are in a sandbox** (paths below). No production data-dir was mutated. No push/merge.

## Scope decision

The v2 graph decomposes farmOS into 11 structural subsystems. The logs+quantities
domain maps to two clean (persistence 1.0) domain subsystems:

| subsystem | members | domain |
|---|---|---|
| `ss:761b7d53e7a231e2cf7a7782` | 126 | **logs** — the log-type modules (harvest, activity, observation, seeding, input, birth, medical, maintenance, lab_test, transplanting) |
| `ss:2cb2e7ead2b5c8f988009676` | 11 | **quantities** — standard/material quantity modules |

The pipeline was **scoped** by pruning `subsystems.parquet` + `subsystem_members.parquet`
in a sandbox copy of the data-dir to just these two (137 members total), so every
downstream stage — and every LLM call — touched only the target domain. Assets
(`ss:7044…`, 319 members: land/animal/group/etc.) are a *referenced shape*, not in
scope; the port implements asset lifecycle from the **fixture pack**, not the brief.
The port brief was rendered for the **logs** subsystem (the behavioral heart).

## Stage 1 — BRIEF

Pipeline, all scoped to the two subsystems, run against the sandbox data-dir:

| stage | command | LLM | output |
|---|---|---|---|
| structural | `interfaces` → `hom-profiles` → `roles` → `operads` | — (LM-free) | 21 interfaces, 30 role rows, 2 operad rows |
| T5a harvest | `ctkr intention` | — (LM-free) | 53 signals, **11 load rows** (7 structure-clear / 3 ambiguous / 1 intention-critical), 0 conflicts |
| T5b synthesis | `ctkr intention-synthesis` | $0.091 | 21 intent statements, 2 S1 scenarios, 8 adjudications (5 tension / 3 consistent) |
| cards | `ctkr extract-spec` | $0.060 | 2 subsystem cards, 19 labels, 9 dissonance findings |
| intent-CM | `ctkr intent-cm --adjudicate --target-profile` | $0.006 | **1 CM-hard seed**: `unique-constraint` (birth-log uniqueness) |
| port-brief | `ctkr port-brief --subsystem ss:761b --target-profile --intent-cm` | $0.102 | `port_briefs/ss__761b….md` — 1 export, 6 roles, 2 ops, 2 scenarios, 5 warnings, **target-adaptation notes** |

The rendered brief is committed at `results/port-verify/logs-quantities-brief.md`.

**Key finding — the brief is a plugin-registry shape, the behavior is in the fixtures.**
The structural graph over farmOS PHP has a **THIN data-edge alphabet** (0/5 of
TYPE_OF/READS_FIELD/WRITES_FIELD/RETURNS_TYPE/CONSTRUCTS present; `scip_fraction=0.0`).
So the extracted brief for the "logs" subsystem describes the **Log Type Plugin
Registry** — a `FarmLogType` base class, concrete per-kind plugin classes that
`EXTENDS` it, a uniqueness constraint, a Views filter — and *not* the runtime
value flow (record a harvest → asset yield total). The behavioral heart therefore
lives entirely in the **semantic fixture pack** (`oracle/data/farmos_core_fixtures.jsonl`),
which was shipped to the builder alongside the brief. This is the intended
division of labor (brief = shape, oracle = value), and this run makes it concrete.

## Stage 2 — BLIND BUILD

A separate blind builder subagent (Sonnet) received **only** four files — the
rendered brief, the 7-fixture semantic pack, the target profile, and a
TypeScript translation of the oracle adapter contract — and was explicitly
forbidden from reading farmOS source or the MetaCoding repo. Fresh build dir.

It produced an **event-sourced store with materialized views** in Bun/TypeScript:
`events.ts` (append-only log), `views.ts` (each read is a pure fold over the log),
`store.ts`, `oracleAdapter.ts` (the value boundary), 5 test files, `README.md`,
`PORT_DECISIONS.md`. Client-generated UUID handles; no autoincrement; reads never
cache. `bun test`: **18 pass / 0 fail**.

**Port decision (builder-authored, CM-hard):** the `UniqueBirthLog` constraint →
**`weaken-to-eventual`**. Rationale (paraphrased): with `coordination_layer: false`
there is no write-time authority; two offline replicas can each record a birth log
for the same asset, so a write-time reject is not an available option. The builder
rejected `preserve-via-convergence-rule` (a CRDT tiebreak would silently pick a
"real" birth, hiding a genuine duplicate-vs-concurrent ambiguity that needs a human)
and `move-to-disclosure-layer` (not an access question). Recorded as PD-001. None
of the shipped fixtures exercise birth uniqueness, so this is a design-notes
deliverable, exactly as the brief's adaptation note framed it.

## Stage 3 — VERIFY (three ways)

### (a) Value-equivalence — the load-bearing check

An **independent** runner (verifier-side, not builder-written) drove the port's
adapter through the canonical 7-fixture pack:

```
PASS  A newly created land asset is active
PASS  An archived land asset is no longer active
PASS  Recording a harvest of X gives that asset a yield total of X
PASS  Two harvests sum into the yield total
PASS  A harvest recorded as pending is delivered pending
PASS  Marking a pending harvest done delivers it done
PASS  Assigning an animal to a group makes it a member
```

**7 / 7 fixtures pass.** A blind port, from brief + fixtures + adapter contract
alone, is value-equivalent to live farmOS on the logs+quantities slice.

### (b) Structural (port-verifier punch list)

The port was indexed with `metacoding index --scip ts` (170 symbols, 346 edges),
hom-profiles computed, and scored against the logs subsystem card via a
member-set-restricted functor (`verifyPort`). Full report:
`results/port-verify/logs-quantities-structural-2026-07-18.txt`.

| §7 gate | raw | net of waivers |
|---|---|---|
| role coverage | **33.3%** (2/6) ✗ | ✓ (all failures waived) |
| interface preservation | **0.0%** (0/1) ✗ | ✓ |
| composition preservation | **0.0%** (0/2 protocol) ✗ | ✓ |
| fidelity | **100.0%** ✓✓ (ceiling) | ✓✓ |
| cycle consistency | **40–50%** ✗ | ✓ |

Raw: **8 punch-list blockers/warnings**. Every one is the *same* deliberate
architectural divergence — a local-first event log is not a PHP plugin registry:
the dropped roles are `FarmLogType` (base class), `Birth`/`Maintenance` (concrete
plugin classes), `FarmLabTestTypeInterface` (config entity), and the two
`… ∘ FarmLogType` EXTENDS protocol ops. Log kinds are string-tagged **events**,
not subclasses. These are recorded as **8 port-decision waivers** (PD-002…PD-009,
`results/port-verify/logs-quantities-port-decisions.jsonl`); net of waivers, **0
unwaived punch items and 0 stale waivers**.

**Key finding — structure-preservation provides no independent acceptance signal
for a cross-paradigm port.** When the whole architecture is a conscious divergence
(central-authority plugin system → local-first event log), 8/8 structural failures
are all waived; the verifier confirms *disciplined divergence, not drift*, but it
cannot itself vouch for correctness. The value-equivalence oracle carries the
acceptance weight; the structural verifier's role here is auditability, not a gate.

### (c) Behavioral coverage

| baseline | scenarios | port covers | % |
|---|---|---|---|
| brief's S1 acceptance list | 2 (both "log-type plugin can be instantiated / implements interface") | 0 | **0%** |
| semantic fixture pack | 7 (value flows) | 7 | **100%** |

The port's 18 tests cover all 7 fixture value-flows plus 11 more (event-log
invariants, pending-contributes-to-yield, measure+unit matching, logCount-by-kind,
group non-membership). **Key finding:** the brief's S1 lane distilled *plugin-
mechanics* scenarios (instantiation, interface compliance) from the farmOS log-
subsystem tests, not value flows — so the S1 baseline and the value port barely
intersect. This is direct evidence that the Phase-2 value oracle is **not
redundant** with S1 distillation: for this subsystem, S1 gave plugin ceremony and
the oracle gave the behavior a port actually has to satisfy.

## Stage 4 — CALIBRATE

Per-element observations (whether the blind builder had to consult harvested
evidence, and the load class the run *revealed*) were emitted with the new
`eval/ctkr/port_run_emit.py`, ingested into `calibration.parquet`, and reported.
Observations + provenance: `port_runs/logs-quantities-2026-07-18.observations.json`.

| predicted class | n | precision (miss=none) | evidence-consult rate |
|---|---|---|---|
| structure-clear | 7 | **0.857** (6/7) | 0.143 |
| intention-critical | 1 | **0.0** (0/1) | 0.0 |
| ambiguous | 3 | **0.0** (0/3) | 0.0 |
| **overall** | 11 | **0.545** (6/11) | 0.09 |

Current dials (`d_hi≈0.5–0.75`, `r_min≈0.3`) reproduce the observed 7/1/3 split.

**Reading the misses:**
- The one **structure-clear miss** is the real signal: `role:70108211…` (the
  UniqueBirthLog constraint attachment) scored `D=0.75` → structure-clear, but
  porting it *required* reading the consistency-model intention (the CM-hard note)
  to choose weaken-to-eventual. The structural determinacy score underweighted a
  consistency-model-bearing intention. → miss type `needed-evidence-not-given`.
- The **intention-critical (1/1) and ambiguous (3/3) misses** are all
  `evidence-given-not-needed`: those classes fired on **source-idiom** elements —
  the Views filter plugin (intention-critical) and the ambiguous log-type plugin
  classes — that a *value-equivalence* port never implements. The flags were not
  wrong *in the source paradigm*; they were irrelevant to a value port.

## Dial recommendations

1. **Condition the load classifier on the value line, or on the target paradigm.**
   The intention-critical/ambiguous flags fired at 0% useful precision here because
   they scored source-idiom structural roles (plugin registry, Views filter) that
   carry no value load. Recommend a pre-filter: an element that is pure source-
   idiom (no path to a glossary value term / no boundary morphism to a value shape)
   should be down-weighted or excluded before D/R scoring, so calibration measures
   the classifier on elements a port must actually satisfy.
2. **Add a consistency-model term to structural determinacy.** The lone
   structure-clear miss was a CM-sensitive element scored `D=0.75`. When intent-CM
   tags an element CM-hard/CM-soft, cap or discount its D-score — a central-
   authority invariant is never "structure-clear" for a local-first target, no
   matter how clean its call graph. This directly couples the (already-computed)
   intent-CM lane into the load classifier.
3. **Don't gate cross-paradigm ports on structure-preservation.** Make the value
   oracle the required gate and the structural punch list an *advisory* audit
   (disciplined-divergence ledger) whenever the target profile's paradigm differs
   from the source's (`consistency_model`/`coordination_layer` mismatch). 8/8
   waived here is the signature of that situation.
4. **Enrich the PHP data-edge alphabet before trusting a farmOS behavioral brief.**
   `scip_fraction=0.0` on the log subsystem meant the brief captured plugin
   structure, not data flow. The value behavior had to come from the oracle. Until
   the scip-php lane populates TYPE_OF/READS_FIELD/WRITES_FIELD, treat farmOS
   briefs as shape-only and require the fixture pack as the behavioral spec (which
   is what the port-loop already does — this run confirms the dependency is real,
   not belt-and-suspenders).

## Misses / honesty notes

- **Coverage against the brief's own S1 list is 0%** — the port satisfies the
  fixture pack, not the brief's plugin-instantiation scenarios. Reported as-is.
- **8/8 structural punch items waived** means the structural verifier added no
  independent acceptance evidence this run; it functioned only as a divergence
  ledger. Not hidden — see Stage 3(b).
- The calibration `observed_class` / `consulted` judgments are the observer's
  reading of a single port run (n=11 elements, 1 builder); they are the honest
  first data point, not a converged statistic. Precision numbers should be read as
  "what this one port revealed," not a stable classifier score.
- Quantities subsystem (`ss:2cb2…`) got a card + brief but the value slice folds
  quantities into logs (quantity-on-log), so it was not separately verified.

## Artifacts (all sandbox unless noted)

- **Scoped pipeline data-dir (sandbox):** `/private/tmp/claude-501/…/scratchpad/port-run-0p7/data-dir` — pruned copy of the v2 graph + all pipeline outputs (intention/cards/briefs/intent-cm). *Sandbox, not production:* the shipped v2 graph at `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2` was never mutated.
- **Blind port implementation (sandbox):** `/private/tmp/claude-501/…/scratchpad/port-run-0p7/port-build` — Bun/TS event-sourced store. `bun test` 18/18.
- **Port index data-dir (sandbox):** `/private/tmp/claude-501/…/scratchpad/port-run-0p7/port-dd` — metacoding scip-ts index of the port.
- **Verification harnesses (sandbox):** `…/port-run-0p7/verify/runFixtures.ts` (value-equivalence), `…/verify/port_verify_slice.ts` (structural). Committed copies under `eval/ctkr/port_runs/`.
- **Committed (this worktree, in-repo):**
  - `eval/ctkr/port_run_emit.py` — the port-run observation emitter (the deferred calibration half).
  - `eval/ctkr/calibration.parquet` — first real port-run calibration data (11 rows).
  - `eval/ctkr/port_runs/logs-quantities-2026-07-18.observations.json` + `.obs.jsonl` — observer judgments + emitted observations.
  - `eval/ctkr/results/port-verify/` — rendered brief, structural report, port-decisions JSONL.
  - `eval/ctkr/results/vertical-slice-logs-quantities.md` — this document.

## Open questions for Duke

1. **Structural gate policy for cross-paradigm ports.** Agree that structure-
   preservation should be advisory (not a gate) when `target.consistency_model` /
   `coordination_layer` differ from the source's? If so, `verifyPort` could emit a
   "paradigm-divergence" banner and auto-suppress the pass/fail verdict.
2. **CM→D coupling.** Want dial recommendation #2 (discount D for intent-CM-tagged
   elements) implemented now, or held until a second port confirms the single
   structure-clear miss generalizes?
3. **Value-line filter for calibration.** The 0% precision on intention-critical/
   ambiguous is entirely source-idiom over-fire. Should calibration only score
   elements with a path to a glossary value term, or keep scoring everything and
   track the idiom-over-fire rate as its own metric?
4. **farmOS data-edge coverage.** The THIN PHP data alphabet (`scip_fraction=0.0`)
   is the root cause behind "brief = plugin shape, not behavior." Is closing the
   scip-php data-edge gap in scope before the fan-out to the rest of farmOS, or do
   we accept oracle-carried behavior as the standing design?
