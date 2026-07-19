# Semantic-mining pass — fixture candidates for logs+quantities (MetaCoding-9h5.10)

> Bead MetaCoding-9h5.10 · 2026-07-20 · builds the golden path from the 9h5.8
> signal-attribution matrix (`signal-matrix-2026-07-19.md`): *the lever for the
> fan-out is fixture coverage of the non-obvious semantics, not more machinery.*
> This pass inverts the pipeline — instead of writing briefs a builder ignores,
> it uses the deterministic layers to FIND the non-obvious semantics and proposes
> them as ranked fixture candidates for live-oracle observation.

## What was built

`ctkr mine-fixtures` (module `ctkr/ctkr/mine_fixtures.py`, CLI
`ctkr/ctkr/commands/mine_fixtures.py`) — given a data-dir + scoped subsystem(s) +
source root, emits `fixture_candidates.jsonl`: per candidate a scenario sketch
(given/when/then draft), why-non-obvious, the mining lane(s) that surfaced it, a
`file:line` source citation, and a rank score. Three lanes, fused:

1. **CM lane** — `intent_cm.scan_cm` + `adjudicate_cm` (gpt-5.6-luna, prescreen
   OFF per the adopted 9h5.14 default). Surfaces the UniqueBirthLog pattern.
2. **Graph lane (LM-free)** — scoped graph structures (validation constraints,
   hook implementations, workflow/state configs, Views filters, and the vju
   READS_FIELD/WRITES_FIELD field-flow edges when the export carries them),
   ranked by **reach** = distinct referrers via REFERENCES/CALLS/EXTENDS/
   IMPLEMENTS/OVERRIDES/CONSTRUCTS/INJECTS. The 0p7 export is scip-php, so it has
   **zero** field-flow edges — the lane degrades gracefully to the structural
   categories (confirmed).
3. **Source-read lane (LLM)** — gpt-5.6-terra reads each module's line-numbered
   source and returns behavioral rules a re-implementer could get wrong, each with
   a `file:line` citation. Structured pydantic (`SourceReadOut`), `repair=` retry.

Fusion key = (canonical semantic topic, owning module); a candidate surfaced by
more than one lane is merged and boosted. Rank score (deterministic, testable):

    base  = max over lanes {cm: hard 1.0 / soft 0.6; source: 0.5+0.5·conf;
                            graph: 0.7·min(reach/20,1)}
    score = base + 0.5·(n_lanes−1) + 0.15·min(reach/20,1)

**No candidate becomes a fixture without live-oracle observation** — this pass only
proposes; the observation step below is what mints fixtures.

## The honesty check — does the miner surface group-membership latest-wins?

The 9h5.8 matrix found `ce015be4` group-reassignment-**latest-wins** was the ONE
discriminator among ten hardening fixtures — the semantic no fixture and no prose
conveyed. The test for this pass: **run the miner on the logs+quantities slice; do
its top candidates surface group-membership semantics?**

### Run A — strict logs+quantities scope (the literal slice)

Source root `port-run-0p7/cm-src` (log + quantity modules); graph scope `/log/` +
`/quantity/`. **57 candidates. Latest-wins / group-membership: rank = ABSENT (0 of
57 candidates).**

The honest result: **the miner MISSES group-reassignment-latest-wins entirely on
the logs+quantities scope.** Not because the lanes are weak — because the
group-membership read logic lives in `modules/asset/group/src/GroupMembership.php`
(`getGroupAssignmentLog`: `limit=1`, `status=done`, latest timestamp), a module
**outside the logs+quantities boundary**. The CM lane scans only log+quantity
source; the source-read lane is given only log+quantity modules; the graph scope
`/log//quantity/` never reaches `modules/asset/group/`. This *deepens* the 9h5.8
finding: the sole discriminator is not just a semantic no fixture conveyed — it is
authored in a different module than the feature it discriminates.

Top of the strict ranked list (full list: `fixture_candidates_logs-quantities-9h5.10.jsonl`):

| # | score | lane | topic | citation | title |
|--|--|--|--|--|--|
| 1 | 1.00 | cm | uniqueness-constraint | log/birth/src/Hook/FieldHooks.php:31 | UniqueBirthLog — one birth log per asset (CM-hard) |
| 2 | 0.99 | source-read | (birth) | log/birth/src/Hook/EntityHooks.php:86-108 | a specified mother is appended as a child's parent |
| 4 | 0.99 | source-read | (material) | quantity/material/…/Material.php | a material quantity may reference multiple materials |
| 5 | 0.99 | source-read | uniqueness | log/…/views/filter/LogQuantityMaterial | a log matches the material filter if ANY quantity matches |
| 6 | 0.98 | source-read | views-filter | log/…/views/filter/LogQuantityMaterial | multiple selected material types match by OR |
| 12 | 0.95 | source-read | log-status-lifecycle | log/transplanting/…/Transplanting.php | transplanting identified solely by the register |
| 15 | 0.95 | source-read | uniqueness | log/birth/src/Hook/EntityHooks.php:26-84 | saving a birth log synchronizes each animal's parent |
| 17 | 0.92 | source-read | measure-unit-filter | quantity/material/…/Material.php | a material quantity inherits all default fields |
| 18–57 | 0.85→0.00 | graph | domain-logic / hook / views | (log+quantity classes) | high-reach structural elements, no value semantics |

The graph lane (ranks 18–57) surfaces high-reach structural elements
(`FarmLogType`, `QuantityInterface`, the hooks) but **no value semantics** — exactly
the 9h5.3/9h5.8 verdict that graph structure alone is ≈ 0 for the value pass. The
signal that IS non-obvious and port-relevant comes from the CM lane (rank 1,
UniqueBirthLog) and the source-read lane (the birth/material/transplanting rules).

### Run B — extended scope (+ the group module)

`BUILD_INSTRUCTIONS.md` line 29 lists group membership as required domain coverage
of the logs+quantities port, so the faithful "as the port implements it" scope adds
`modules/asset/group`. Graph scope `/log/ /quantity/ asset/group`; source-read given
the group module. **Latest-wins now SURFACES near the top:**

| # | score | lane | topic | detail |
|--|--|--|--|--|
| 2 | 0.965 | source-read | **group-membership-latest-wins** | *"only one latest log is read, and its entire group-reference list is the current value (including an empty list). Names such as `getGroup` and 'assignment' can suggest additive membership records."* — cited `src/GroupMembership.php:51-61, 78-97` |
| 10 | 0.26 | graph | **group-membership-latest-wins** | `GroupMembershipInterface` tagged membership-logic (reach 5) |

The source-read lane recovered the exact latest-wins semantic verbatim from source
— the same recovery the 9h5.8 pure-LLM cell (Cell 4) demonstrated, now made a
first-class ranked candidate. **Conclusion: the miner surfaces latest-wins iff the
group module is in scope. On the nominal logs+quantities scope it is missed; the
lever is therefore not only fixture coverage but *scope coverage* — the fan-out must
scope a feature to the modules that author its reads, not just its writes.**

(Caveat, reported honestly: `scan_cm`/`rglob` did not follow the symlinked
log+quantity dirs in the combined extended tree, so Run B's CM lane saw 0 seeds and
its source-read lane covered the group module only; the graph lane used all three
real scopes. Strict Run A + extended Run B together give the complete picture.)

## Observation — top unfixtured candidates against the live oracle

Per the Phase-2 discipline, candidates were OBSERVED against live farmOS
(`farmos-oracle-www` @ http://localhost:8095, admin/admin) via
`ctkr/ctkr/oracle/recorder.py`. Five previously-**unfixtured**, in-DSL corners the
miner's top topics point at were recorded (entities prefixed `m10-` to avoid
collision with concurrent lanes). Every `then` was filled by observation — nothing
hand-authored — and all 5 **self-verify 5/5** against the oracle.

| fixture_id | miner topic | observed value (the non-obvious fact) |
|--|--|--|
| `1ac3abe75e752057c78c0afff3e96b96` | log-status-lifecycle | a **done** harvest re-marked pending is delivered **pending** — reverse transition is allowed |
| `46d45292c7d1d0ef16dad33ad45102a8` | measure-unit-filter | a quantity with **no unit**: unit-agnostic yield = 5.0 but unit-filtered yield(kg) = **0.0** — a unitless quantity is invisible to a unit-filtered read |
| `92b80f3e937d03baff438c3a7bf96457` | group-membership | re-assigning to the **same** group keeps membership (idempotent) |
| `43d28238149481813d4398d682a60d93` | group-membership-latest-wins | after G1→G2→**G1**, member of G1 only (G2 False) — true latest-wins, not a toggle (extends the pack's 2-step ce015be4) |
| `389eeb00f52cefb43f0e46db0a6048d7` | archival-retains-history | an **archived** asset still accepts a new log that counts toward yield (5.0) and log_count (1) |

Pack files: `m10_hardening_fixtures.jsonl` (5) + `m10_hardening_observations.jsonl`
(50). These are a validation deliverable of this pass; they are **not** merged into
the canonical 17-fixture pack (kept separate to avoid disturbing work that depends
on it).

## Spend, tests, provenance

- **LLM spend: $0.162 total** (Run A $0.1084 — 1 luna CM call + 12 terra source
  reads; Run B $0.0535 — 7 terra reads). Well under the $3 cap. Observation +
  self-verify are LM-free.
- **Tests: `ctkr/tests/test_mine_fixtures.py` = 19 passed** (hermetic graph/rank/
  schema + mock-provider LLM lanes). **Full suite: 422 passed, 3 skipped, 0
  failed.** Ruff clean.
- **Data-dir provenance (all SANDBOX):**
  - Graph read from `…/453fbf17-…/scratchpad/port-run-0p7/data-dir/ctkr/export`
    (scip-php export, symlinked into `/private/tmp/m10-scratch/data-dir` so the
    llm_cache/cost_log were isolated from the shared 0p7 sandbox).
  - Source: `…/port-run-0p7/cm-src` (log+quantity) and
    `…/port-run-0p7/repos/farmos/modules/asset/group` (extended).
  - Live oracle: farmOS 4.x Docker `farmos-oracle-www` @ localhost:8095 — m10-
    prefixed entities only.
  - No production `.metacoding/` data-dir was created or mutated. Candidate JSONLs
    and the m10 pack committed under `eval/ctkr/results/`.
