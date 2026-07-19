# CM→D coupling — the second calibration datapoint (design)

> Bead MetaCoding-9h5.12 · 2026-07-20 · **design only, no run.** Companion to `ct-intention-extraction.md` §5.3 (dial-rec #2) and the coupling implementation in `ctkr/intention.py` (`cm_discount` / `couple_cm_determinacy` / `apply_cm_coupling`).

## What is being calibrated

When the intent-CM lane grades an element CM-hard/CM-soft for a local-first target, its central-authority invariant is never truly *structure-clear* however clean its call graph — so we **discount structural determinacy before classification**:

```
D_effective = D · (1 − discount)         # ctkr.intention.couple_cm_determinacy
load_class  = classify(D_effective, R, port_critical)
```

with the shipped dials (`ctkr/data/intention_normalization.json`):

| dial | value | classifier constants |
|---|--:|---|
| `d_cm_hard_discount` | **0.5** | `d_hi = 0.55` (structure-clear floor) |
| `d_cm_soft_discount` | **0.25** | `r_min = 0.40` (intention-critical floor) |

`classify` returns `structure-clear` iff `D_eff ≥ d_hi` and not `port_critical`; else `intention-critical` iff `R ≥ r_min`; else `ambiguous`.

## Why a second datapoint is needed

**Both dials were fit to n=1.** The only empirical point is the **UniqueBirthLog** constraint from the logs+quantities port (`role:70108211…`, D=0.7493, R=0.4603, grade **CM-hard**, category **unique-constraint**). It was predicted `structure-clear` (D=0.75 ≥ 0.55) but the port *revealed* `intention-critical` — the builder had to read the CM intention to choose weaken-to-eventual (PD-001). `hard_discount=0.5` drops it to 0.375 < 0.55, catching the miss (pinned in `tests/test_intent_cm_coupling.py::test_unique_birth_log_default_flips_out_of_structure_clear`).

That single point constrains the hard dial only from **below**:

```
flip out of structure-clear  ⇔  D·(1−h) < d_hi  ⇔  h > 1 − d_hi/D = 1 − 0.55/0.7493 = 0.266
```

So n=1 tells us `h ≥ 0.266`. It tells us **nothing** about:

1. **An upper bound on `h`.** Is there any CM-hard element the port reveals *should stay* structure-clear (clean structure, and the port kept/emulated the authority so the CM intention was not consulted)? Its D would cap `h`. If none exists, `h` can be large (→1.0: "no CM-hard element is ever structure-clear"). We cannot currently distinguish `h=0.5` from `h=1.0` — they behave identically on the only point we have (both flip 0.7493).
2. **The soft dial at all.** `soft_discount=0.25` has **zero** empirical support. It flips a CM-soft element out of structure-clear iff `D < d_hi/(1−0.25) = 0.733`. No observed soft element sits near that boundary.
3. **Category generalization.** The n=1 point is `unique-constraint`. The other two dominant hard categories in the farmOS adjudication — **access-check** and **revision-lock** — are unexercised. If they behave differently (e.g. an access-check that the port keeps server-side needs no CM read), a single global `h` is wrong and the dial should be per-category.

**The second port must produce points that (a) put an upper bound on `h`, (b) place at least one CM-soft point across `D≈0.73`, and (c) cover access-check and revision-lock.**

## Which slice to port

Requirement: a **self-contained vertical slice** (clean island → cheap, blind-portable) with **>1 CM-hard element**, spanning hard categories the n=1 point missed. Candidates from the farmOS i57 adjudication (`…/i57-runs/farmos/.metacoding/ctkr/intent_cm_adjudicated.jsonl`; 125 adjudicated: 38 hard / 44 soft / 43 none):

| slice (module) | island (this eval) | CM-hard elements | categories covered | verdict |
|---|---|---|---|---|
| **`modules/core/plan`** | part of core-blob | Plan entity (revision-lock), PlanRecordAccess (access-check), PlanArchive (access-check), PlanUnarchive (revision-lock), AccessHooks (access-check) | **revision-lock + access-check** | **primary** — covers the two categories n=1 missed; ≥4 hard points; also carries CM-soft + CM-none elements for the soft/none arms |
| `modules/core/organization` | `ss:f49e059c` (118, persistence 0.991) — **clean island** | Organization entity (revision-lock **and** unique-constraint via `addConstraint('UniqueField')`) | revision-lock + unique-constraint | **secondary** — two independent hard grades on one entity, and a clean self-contained island (cheapest blind port); replicates the unique-constraint category for cross-checking against UniqueBirthLog |
| `modules/log/birth` | `ss:761b7d53` | UniqueBirthLog (unique-constraint) | unique-constraint | **avoid as primary** — this *is* the n=1 element; re-porting adds no independent hard point (useful only as a regression anchor) |

**Recommendation.** Port **`plan`** as the primary second datapoint (revision-lock + access-check + its soft/none tail in one coherent slice), and **`organization`** as a cheap secondary (a clean island; a second unique-constraint point + a revision-lock point). Together they yield ≥5 independent CM-hard points across all three hard categories, plus soft points, versus the current 1.

Two smaller notes on slice choice:
- **Spread D across `d_hi`.** The tuning boundary lives at D≈0.55 (hard) and D≈0.73 (soft). Prefer including elements whose *uncoupled* D lands in `[0.5, 0.8]` — that is where the discount changes the class and where an observation is informative. Elements with D≪0.55 are already non-structure-clear (coupling is a no-op) and D≫0.9 hard elements only re-confirm `h≥0.266`. Record D for every CM-tagged element regardless, but treat the near-boundary ones as the high-value observations.
- **Keep the target profile fixed.** Use the same local-first `TargetProfile` as port 1 so the grades are comparable; the discount is a property of (grade, target), not of the slice.

## What the second port must capture (observation protocol)

The emitter already exists (`eval/ctkr/port_run_emit.py`) and the calibration schema already carries the needed columns (`eval/ctkr/calibration_schema.py`: `structural_determinacy`, `predicted_load_class`, `drivers`, `builder_consulted_evidence`, `miss_type`). The coupling driver string (`"intent-CM hard → D discounted ×0.50 (0.7493→0.3746)"`) records both the pre- and post-coupling D, so **no schema change is required** — but the run procedure must be exact:

1. **Harvest + score the slice** → `intention_load.parquet` (D, R per element) and run the intent-CM lane → `intent_cm_adjudicated.jsonl` (grade per element). Build `cm_sensitivity = {element_id: grade}`.
2. **Apply coupling** with `apply_cm_coupling(load_df, cm_sensitivity)` → the *coupled* `intention_load` (the driver string records `D_pre → D_post` for every CM-tagged element). Persist **both** the pre-coupling and post-coupling `predicted_load_class` per element (the pre-coupling one is `classify(D_pre, …)`; compute it once and keep it — it is the counterfactual the tuning compares against).
3. **Blind port** the slice to the local-first target (builder sees the shape + evidence, not the grades). For each CM-tagged element the observer records, per the existing `observations.yaml` shape:
   - `consulted` — did the builder **read the CM intention** (the central-authority note) to port this element? This is the load-bearing signal: a CM-hard element the builder ported *without* reading its CM note was, for this port, not CM-critical (an upper-bound point on `h`).
   - `observed_class` — the class the port *revealed* (`structure-clear` if shape sufficed; `intention-critical` if the CM intention was required; `ambiguous`; `none` if out of the value slice).
   - `note` — one line on *why* (which resolution the port chose: preserve-via-convergence / move-to-coordination / weaken-to-eventual; or "kept authority, no CM read needed").
4. **Emit** with `port_run_emit.py --load-parquet <coupled intention_load> --observations <yaml> --out <obs.jsonl>`, then `calibration_ingest.py` → append to `eval/ctkr/calibration.parquet` under a new `port_run_id` (e.g. `farmos-plan-2026-…`).

### The specific rows the tuning needs (per CM-tagged element)

`(element_id, category, cm_grade, D_pre, D_post, predicted_pre_coupling, predicted_post_coupling, observed_class, consulted)`

All are present in / derivable from the emitted calibration row except an explicit `category` and `cm_grade` — carry these in the observation `note` (or, cheap optional extension, add `cm_grade`/`cm_category` columns to the observation record so `calibration_report.py` can group by category without string-parsing drivers).

## How the datapoint tunes the dials

Score each CM-tagged element by whether coupling improved the prediction:

| observed vs predictions | meaning for the dial |
|---|---|
| pre=`structure-clear`, post≠`structure-clear`, observed≠`structure-clear`, **consulted=true** | coupling **correct** — discount earned its flip (lower-bound confirmation) |
| pre=`structure-clear`, post≠`structure-clear`, observed=`structure-clear`, **consulted=false** | coupling **over-corrected** — this D is an **upper bound**: `h < 1 − d_hi/D` (hard) or `< 1 − d_hi/D` for soft. **The key falsifier the second port can produce.** |
| pre=`structure-clear`, post=`structure-clear` (D high enough), observed≠`structure-clear` | discount **too weak** — raise it |
| pre=post (D≪d_hi already) | uninformative for the dial |

Then:
- **Hard dial.** Collect every CM-hard element's `(D_pre, needed_flip?)`. `needed_flip` = observed ≠ structure-clear ∧ consulted. The admissible range is `max over "should-stay" points of (1 − d_hi/D) < h < min over "should-flip-but-high-D" bound`. If no "should-stay" CM-hard point appears across `plan`+`organization` (the likely outcome — a CM-hard invariant almost by definition needs the intention), that is itself the finding: **`h` may safely go to 1.0**, and the conservative `0.5` is under-correcting only in the sense of leaving headroom. If a should-stay point *does* appear (e.g. an access-check the port kept server-side), it caps `h` and argues for **per-category** discounts (access-check < revision-lock ≈ unique-constraint).
- **Soft dial.** Same construction over CM-soft elements; the first real soft observations either confirm `0.25` (a soft element at D≈0.7 that stayed structure-clear and needed no CM read) or move it.
- **Per-category split decision.** If access-check systematically behaves differently from unique-constraint/revision-lock (upper-bounds `h` for one category only), promote the single `d_cm_hard_discount` to a `{category: discount}` table — a one-line schema addition mirroring the existing dial structure. The second port is exactly the evidence that decides scalar-vs-table.

## Acceptance for the second datapoint

The run has succeeded when `calibration.parquet` contains, under a new `port_run_id`, **≥4 CM-hard and ≥1 CM-soft** observed elements spanning `access-check`, `revision-lock`, and `unique-constraint`, each with `D_pre`, coupled/uncoupled predicted classes, `observed_class`, and `consulted` — enough to (a) place an upper bound on `hard_discount` or prove none exists in-sample, (b) give the soft dial its first empirical point near D≈0.73, and (c) answer scalar-vs-per-category. No dial value should be changed from this design; the design fixes *what to observe* so the next run can change them with evidence instead of n=1.
