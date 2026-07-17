# The Port Loop — from intention extraction to re-implementation

Phased plan for making [`ct-intention-extraction.md`](./ct-intention-extraction.md) real against a
live target: **farmOS (Drupal/PHP) → a local-first re-implementation** (event log, sync,
selective disclosure). Agreed in the 2026-07-17 planning session. The structural lane
([`ct-subsystem-extraction.md`](./ct-subsystem-extraction.md), T1–T6) and the intention design
stand as written; this doc sequences them and adds the port-loop-specific machinery.

## Why farmOS is the right first target

- **The N=2 instance already exists.** farmOS 1.x (Drupal 7) → 2.x (Drupal 9) was a ground-up
  rewrite of the same product by the same community, with the mapping written down in
  `farm_migrate`. Diffing the intention harvests of both versions separates intent-I (survived
  the rewrite) from idiom (didn't) *empirically* — the calibration §7.2/§10 of the intention doc
  says we lack. No other corpus hands us this.
- **Declarative intention.** In Drupal the strongest signals aren't PHP: config-entity YAML,
  entity/field annotations, routing + permissions YAML, `.info.yml` module structure, and
  update hooks are machine-enforced statements of the domain model, feature decomposition, and
  business history. Tier S, sometimes above tests.
- Independent contract instances: farmOS.py / farmOS.js / Aggregator implement the JSON:API
  contract; farmOS.org/model is near-spec prose.

## Phases

**Phase 0 — Drupal declarative lane** (parallel with PHP epic MetaCoding-8sh).
A YAML/annotation walker emitting `intention_signals` + `data_shapes` rows from config,
keyed to owning module. Independent of scip-php; covers exactly where static PHP analysis is
weakest (hooks, plugins, magic). Also: feature inventory (`features.parquet`) from
`.info.yml` + routing + permissions — module ≈ feature; the dependency graph is free.

**Phase 1 — T5a/b/c on the MetaCoding self-index** (as specified in the intention doc §9.2).
T5a harvest is LM-free and starts immediately. Self-index is ground truth — including using
MetaCoding's own tooling to upgrade MetaCoding.

**Phase 2 — Value-equivalence oracle.** NOT SQL/trace replay: source table structures are
historical cruft; acceptance is *same value delivered*, not same data model. Semantic fixtures
in domain-glossary terms ("after recording a harvest log with quantity X against asset A, A's
yield total reflects X"), derived from S1 scenarios + observed API behavior on a live farmOS
instance, with a thin adapter per implementation. The port's data model is free to differ
everywhere below that line (and will: event log + materialized views).

**Phase 3 — Target profile + intent-CM tag.** A Drupal app silently assumes central authority:
ACID transactions, unique constraints, autoincrement ids, server-side access checks, revision
locks. Every such site gets an **intent-CM (consistency-model-sensitive)** tag — mechanically
seeded, LM-adjudicated. Brief fusion takes an *optional* target-profile document and emits a
clearly-labeled "target adaptation notes" section (preserve via convergence rule / weaken to
eventual / move to disclosure layer). The system must stand alone without a target profile;
the profile only conditions the adaptation section, never the harvest or the intent.
Drupal's permission layer is harvested as its own intention channel — it is the source's
answer to "who may see what", which selective disclosure re-answers, not copies.

**Phase 4 — The vertical slice (the training loop).** Target: **logs + quantities** (the heart
of the farmOS model). Brief → builder agent implements from the brief alone (no repo access) →
verify three ways (structural port-verifier punch list; semantic fixtures; behavioral-spec
coverage) → misses feed calibration. Once this converges, scaling to the rest of farmOS is
fan-out.

## Cross-cutting machinery (added 2026-07-17)

1. **Decomposition meta-schema** — the discipline question answered once, first: every
   decomposition of any codebase produces a fixed mandatory document set —
   *Feature Inventory, Domain Glossary, Data Shapes, Behavioral Scenarios (value-level),
   Invariant Register (portability + consistency-model tagged), Seam Map, Warnings/Conflicts* —
   plus instance-flexible parts (harvest lanes used, target profile, port decisions log).
   Cards and port briefs are renderings over this set, not the set itself.
2. **Port Decisions log + verifier waivers** — every conscious divergence ("shift the
   implementation, even shift the design intent") is an ADR-style record naming the source
   intention it supersedes and why; the port-verifier treats waived elements as expected
   deltas, not failures. Disciplined divergence vs drift, made auditable.
3. **Calibration as data** — every port run emits structured records (element, predicted
   intention-load class, what the builder actually consulted, miss type) →
   `calibration.parquet`; D/R dials, tier weights, and prompts are versioned and tuned from it
   like an ML pipeline. Home: `eval/ctkr/`.
4. **Deferred lanes noted:** community exhaust (issue queue / forum / call notes → rejected
   alternatives) behind `--community-signals`; git lane stays behind `--git-signals`.

## Milestone

First externally meaningful deliverable: **the logs+quantities port brief plus its semantic
fixture pack** — buildable by any strong model or human without reading the farmOS repo.
