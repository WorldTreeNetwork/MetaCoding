# Where the techniques shine — measured attribution after the foundation-hardening line

> 2026-07-20. Synthesis of the 9h5 epic's controlled experiments (nine reports under
> `eval/ctkr/results/`) plus the independent fresh-eyes review
> (`second-opinion-2026-07-20.md`). This is the standing map of what each MetaCoding
> technique is *for*, on evidence rather than intention. Every claim links to a report.
> Scope conditions at the bottom are part of the map — the claims are true *within* them.

## The one-paragraph version

On a value-equivalence port with a runnable source system, the acceptance signal is
carried by the **oracle** (adapter signatures + live-observed fixtures), not by any
generated prose. The deterministic machinery earns its keep **upstream and downstream
of the build, not during it**: *scoping* (boundary/island mapping), *finding*
(semantic mining, CM detection), *deciding* (elicitation with graph-computed blast
radius), and *auditing* (divergence ledgers, pre-registered waivers). Static briefs
and interactive graph queries measured ≈0 during the build itself — because the graded
semantics live in method bodies and adapter conventions, not in edges.

## Where they shine (measured)

### 1. Boundary / island mapping — the standout
`boundary-quality-farmos-v2-2026-07-20.md`

- The islands are **real domain seams, not framework artifacts**: pruning 100% of
  Drupal framework edges leaves the partition essentially unchanged (ARI 0.9965,
  0.1% node churn), even though those edges are 88% of the boundary *composition*.
  Boundary location is 0% framework-determined.
- Nine domain-family islands at 0.99–1.00 persistence; **117 of 147 declared farmOS
  modules map 1:1 to a single island** — an automatically-derived, ranked list of
  clean vertical slices, i.e. the fan-out's port ordering.
- The **disagreement audit** is the monolith product: farmOS core is *modular on
  paper, monolithic in structure* (81 declared modules → one 0.615-persistence blob).
  On a true monolith the same code path emits the proposed decomposition with
  edge-justified moves (`ctkr restructure-proposal`).
- Earlier corroboration: subsystem decomposition was the one structural mechanism the
  introspection audit rated decision-bearing (it scoped the vertical slice to 137
  members → $0.26 total LLM spend).

**Uses:** port sequencing; monolith decomposition proposals; "aspirational vs actual
modularity" audits; identifying the shared-kernel surface (the plugin-type inheritance
seam is the one real cross-island contract).

**Caveat (second-opinion L3):** islands scope *structure*, not *read semantics*. The
sole logs+quantities discriminator (group latest-wins) is authored in a different
island, wired invisibly through DI. **Scope mining by read-authoring modules
(boundary-adjacent included), never by island membership alone.**

### 2. The value oracle — the acceptance spine
`signal-matrix-2026-07-19.md`, `ablation-brief-oracle-2026-07-19.md`

- Adapter signatures + a fixture pack covering the non-obvious semantics = **17/17
  even with method names opaqued and zero prose**. Fixture values subsume both the
  naming and prose channels.
- The independent judge, not the builder's own suite, must gate: the pure-LLM cell
  passed its own 29 tests while failing 3/17 on the oracle — its tests encoded its
  wrong inference.
- Fixtures must be **observed from the live system, never authored from intuition**
  (the pure-LLM cell's plausible-and-wrong "pending is a draft" guess is the proof).

### 3. Semantic mining — the golden path
`semantic-mining-9h5.10.md`, `gpt56-tier-comparison-2026-07-19.md`

- The pipeline's highest-precision LLM stage is **CM adjudication**: exact
  ground-truth recall, zero false positives, across all three GPT-5.6 tiers — at
  ~$0.001/element on Luna. The heuristic prescreen is off by default (human-confirmed
  real false negatives; the economics no longer justify any FN rate).
- `ctkr mine-fixtures` (CM lane + LM-free graph lane + source-read lane) surfaces
  non-obvious semantics as ranked fixture candidates; the source-read lane recovered
  latest-wins at rank 2 once scope included the authoring module.
- The deterministic layer's best role is **deciding what to fixture** — finding, not
  briefing.

### 4. Decision elicitation — the human's seat
`ctkr decisions`, `docs/design/meta-structural-pass.md`, ablation evidence

- CM-hard picks are **builder judgment, not input-determined**: identical inputs
  produced `weaken-to-eventual` (0p7) and `preserve-via-convergence-rule` (both
  ablation cells). Such decisions ripple; they must be surfaced pre-build.
- The registry ranks decisions by uncertainty × **graph-computed blast radius** —
  another place the graph pays off — and every resolution becomes a pre-registered
  constraint the waiver machinery can police.

### 5. Audit & second-order discipline
`meta-structural-pass.md`, `verifyPort` advisory mode, `metric_updates.jsonl`

- For cross-paradigm ports, structural verification is **advisory**; the real
  structural signals are **unpredicted waivers** and **stale waivers** against a
  pre-build paradigm-divergence declaration. Fidelity over the mapped subgraph stays
  binding.
- Gate-authority changes go through an append-only metric-update ledger (rationale,
  replacement signal, reversal condition) — goalposts move only on the record.

### 6. Empirical calibration
`farmos-differential.md`

- The 1.x↔2.x differential is the one asset no LLM can fake: measured survival tiers
  (asset_type roots 83%, module names 30%, permissions 14%) confirmed the intent-tier
  design empirically. Undervalued use (second-opinion L4): survival tiers should
  prioritize fixture authoring directly, not just feed dials.

### 7. The deterministic LLM harness
`ctkr/ctkr/llm.py`, `gpt56-tier-comparison-2026-07-19.md`

- Blake3-keyed cache + cost JSONL makes every LLM judgment replayable and auditable —
  which is what made all of the above *measurable*. Tier routing (Luna/Terra) holds
  measured-equal quality at roughly half cost; the schema repair-retry is load-bearing
  (fired on 2/3 live attempts).

## Where they measured ≈0 (within scope conditions)

- **Static port briefs** for the build: 0% of the brief's acceptance scenarios
  implemented; ≈0 marginal value with brief withheld. Under `scip_fraction=0.0` the
  brief is shape-only by construction.
- **Interactive graph queries during the build**, *given the oracle*: 0 decision-bearing
  of 9 queries on a deliberately cross-cutting feature; +31% wall-time. Root causes are
  structural: DI wiring leaves ~0 CALLS edges into services; graded semantics are
  conditionals inside method bodies, not edges.
- **Structural gates on cross-paradigm ports**: 8/8 waived = a divergence ledger, not
  a gate. Now advisory by design.

## Scope conditions (the fresh-eyes review's core contribution)

The measurements above were all taken with four things held fixed, each of which the
fan-out or a commercial engagement will violate first:

1. **A hand-authored adapter signature surface existed in every cell** (T1). Authoring
   it is the hardest cognitive act in the port; the machinery was never asked to do
   it. "Oracle-centric" is partly definitional until the signature-generation ablation
   runs.
2. **A runnable source system existed** (T5). No live oracle → the source-read mining
   lane becomes primary and the ranking flips.
3. **The corpus is public** (T2). Pretraining familiarity with farmOS/Drupal may
   inflate every builder score; proprietary code is the untested regime where
   graphs/briefs could matter more.
4. **The graph was at its weakest** (T3): thin data alphabet, DI invisible, duplicated
   tree, behaviorally-thin codebase. "Graph ≈0" is a lower bound on this corpus, not
   a law.
5. **Per-feature isolation** (R1): nothing yet measures composition into one shared
   store — the thing the fan-out actually is.

## Standing next experiments (tracked in beads)

1. Signature-generation ablation (T1) — can the pipeline propose the adapter surface?
2. Two-feature composition run (R1) — the smallest honest model of the fan-out.
3. Renamed-farmOS run (T2) — measures pretraining's hidden contribution.
4. Cross-builder differential fuzzing (L1/L2) — discriminators per dollar vs the miner.
5. No-live-oracle cell (T5) — the commercial-legacy regime.
6. Replication of one cell 3–5× — variance before betting on the attribution ordering.

Fan-out prerequisites from R1–R4: a shared kernel (event schema, ID/HLC, binding
CM-decision registry) shipped before wave 1; an explicit core/mega-island strategy
(port plugin-type contracts once, never brief core as features); a fixture
re-verification policy; and port-side hom-profile/role coherence checks across the
accumulating target codebase.
