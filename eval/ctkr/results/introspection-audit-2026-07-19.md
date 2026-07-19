# CTKR value audit — logs+quantities port run (MetaCoding-0p7)

> Bead MetaCoding-9h5.3 · 2026-07-19 · read-only adversarial audit (Opus architect lane)
> Mandate (Duke): "Is the graph analysis, AST work, category-theoretic knowledge
> representation actually providing the value it could? Or are we having an LLM
> hand-wave at it and go around all the gates?"

## Bottom line

On this run the categorical/AST machinery was **mostly corroborating-to-decorative**. The one load-bearing acceptance signal — the 7/7 value-equivalence pass — was carried by the **value oracle (fixtures + adapter contract)**, which is *not* categorical machinery: the fixtures are observed from a live farmOS instance (`provenance.source_system: farmOS 4.x`, observation_refs) and `ADAPTER_CONTRACT.md` restates every read semantic in prose. A plain-LLM baseline handed the same four builder-input files, minus the brief, would almost certainly also have scored 7/7. The machinery's genuine differential value (structural role-equivalence, functor preservation, data-flow-bearing briefs) was **not exercised**, because the precondition that gives categorical structure something to say — a populated data-edge alphabet — was absent (`scip_fraction=0.0`, 0/5 data-edge kinds). All three named confounders are confirmed.

The decisive fact: the builder's inputs were `BUILD_INSTRUCTIONS.md` + `ADAPTER_CONTRACT.md` + `FIXTURES.jsonl` + `TARGET_PROFILE.yaml`. The brief — the sole product of the categorical machinery in that set — is the **least** load-bearing of the four. The adapter contract even instructs "derive these from the fixtures too," and BUILD_INSTRUCTIONS pre-states the architecture AND the CM-hard constraint AND its resolution menu.

## Ledger (mechanism | verdict | evidence)

| Mechanism | Verdict | Evidence |
|---|---|---|
| Structural subsystem decomposition (→ scoping) | **DECISION-BEARING (weak)** | Scoped run to 2 subsystems / 137 members → $0.26 cost (1.7% of cap). `vertical-slice §Scope`. But derivable from module names by a human; clustering only automated it. |
| hom-profiles / roles | **CORROBORATING** | Roles became the *keys* for waivers PD-002…009, but the build followed fixtures+adapter, not roles. Organized the audit; changed nothing built. |
| operads (composition ops) | **DECORATIVE (this run)** | Both protocol ops (`Birth ∘ FarmLogType`, `Maintenance ∘ FarmLogType`) waived (PD-007/008). Consumed only by the waiver ledger. |
| Interfaces | **DECORATIVE (this run)** | 1 provided export (`FarmLogType`), waived (PD-006). 0/1 preserved. |
| T5a harvest + T5b synthesis ($0.091) | **CORROBORATING→DECORATIVE** | Builder evidence-consult rate = **0.09** (`observations.json`): ~1 of 11 elements consulted harvested evidence. Glossary overlaps the adapter contract's own vocabulary. |
| Cards (extract-spec, $0.060) | **CORROBORATING** | Fed brief + functor scoring; no independent downstream decision traces to a card. |
| intent-CM lane ($0.006 → CM-hard seed) | **CORROBORATING** | Origin of "weaken-to-eventual" content, but BUILD_INSTRUCTIONS §6 already names the constraint AND the resolution menu, and any LLM derives the same conflict under `coordination_layer:false`. PD-001 touched **zero fixtures** — a design note nothing verified. |
| Port-brief rendering ($0.102) | **DECORATIVE for the port** (decision-bearing only via the CM note) | Brief describes a "Log Type Plugin Registry"; port implemented **0%** of its S1 acceptance list (`§3c`). Its one used output = the CM note (already in BUILD_INSTRUCTIONS). |
| Structural verifyPort functor | **DECORATIVE as a gate** | 8/8 gates failed raw, 8/8 waived. Doc's own words: *"the structural verifier added no independent acceptance evidence this run; it functioned only as a divergence ledger"* (`§3b`). |
| **Value oracle (fixtures + adapter + runner)** | **DECISION-BEARING — the only real gate** | 7/7 pass is the sole acceptance signal. **Not categorical machinery**: live-instance-observed fixtures + prose-specified adapter semantics. |
| Calibration (parquet, 11 rows) | **Not-yet-decision-bearing (instrumentation)** | Precision 0.545, 4 dial recs — all still open questions to Duke. Nothing downstream consumed them. n=1 builder. |
| N=2 farmOS 1.x↔2.x differential | **DECISION-BEARING (for design/dials)** | Strongest genuine asset. Empirically confirmed intent-I/N/A survival (asset_type 83% domain-root, module 30%, permission 14%), vindicated the A4 name-vs-thing split, produced concrete dial changes. No LLM can fake this — it comes from a real rewrite corpus. |
| Functor eval (rename-fork / null-model) | **CORROBORATING (validates the tool, not this port)** | Lift 0.58 over edge-rewire, 0.94 over random map, orbit−exact gap 0.667. Real — but on **synthetic** fixtures; the functor it validates gated nothing in the live run. |

## Confounders, adjudicated

**(a) Did categorical machinery contribute to the 7/7?** Essentially no. Behavior lives in `FIXTURES.jsonl` (exact given/when/then numbers) + `ADAPTER_CONTRACT.md` (re-specifies every semantic). Both are oracle artifacts, not graph-derived. Machinery contribution to the value pass: **~0**.

**(b) Did functor verification gate anything?** No. 8/8 waived; the report says so.

**(c) Would a plain LLM + fixtures alone have done as well?** Almost certainly 7/7, and it would very likely produce an equivalent PD-001 (weaken-to-eventual), because BUILD_INSTRUCTIONS hands it the constraint and the menu.

## No-CTKR baseline estimate

**LLM + BUILD_INSTRUCTIONS + ADAPTER_CONTRACT + FIXTURES + TARGET_PROFILE, brief withheld → 7/7 value pass, equivalent weaken-to-eventual decision. Delta from the entire categorical machinery on this slice: near zero.** The machinery's only irreplaceable contributions this run were (1) automating the 2-subsystem scoping and (2) producing the auditable divergence ledger — neither of which changed what got built, only cost and paperwork.

## Top 3 to CUT or fix

1. **Stop rendering (and paying for) full role/operad/brief prose when `scip_fraction=0.0`.** Under a thin data alphabet the brief is plugin-registry shape the value port discards (0% S1 coverage). Gate brief generation on a minimum data-edge fraction; below it emit a shape-only stub and lean on the oracle. Saves ~$0.16/subsystem (port-brief + cards) across the 147-feature fan-out.
2. **Demote structural verifyPort from gate to advisory ledger for cross-paradigm ports** (doc's own rec #3). When target consistency_model/coordination_layer differ from source, auto-suppress pass/fail. A "gate" that is 100% waived is theater.
3. **Fix the calibration classifier's source-idiom over-fire before scaling.** intention-critical and ambiguous fired at **0% useful precision** — flagged plugin/Views-filter idiom a value port never implements. Pre-filter to elements with a path to a glossary value term, else the fan-out generates 147× the noise.

## Top 3 to DOUBLE DOWN on

1. **The value oracle** — the only thing that actually gated. Invest in fixture coverage and live-instance observation. Be honest that this is the product and it is *not* the categorical layer.
2. **The N=2 differential calibration** — genuinely unique empirical leverage. Feed its `cross_version_rename` signal and per-project namespace affix into the dials before fan-out.
3. **Close the scip-php data-edge gap** (TYPE_OF/READS_FIELD/WRITES_FIELD). This is the *only* path by which the categorical brief becomes decision-bearing rather than shape-only. Make-or-break for the whole CTKR premise.

## Proposed ablation (settles the baseline empirically, ~$0.05–0.10, no reindex)

Two cells, same slice, one Sonnet builder each — all inputs already exist in `builder-inputs/`:

- **Cell A — brief WITHHELD:** builder gets only FIXTURES + ADAPTER_CONTRACT + TARGET_PROFILE + a brief-stripped BUILD_INSTRUCTIONS. **Prediction: 7/7 pass, equivalent weaken-to-eventual.** If it passes, the categorical brief contributed ~0 — proven, not argued.
- **Cell B — fixtures + adapter semantics WITHHELD, brief ONLY:** builder gets the brief + adapter *signatures* but not fixture values or prose semantics. **Prediction: fails value-equivalence** — proving the brief is shape-only and the oracle carries everything.

Together they fully attribute the value: A measures the brief's marginal contribution (expected ≈0), B measures whether the categorical layer can carry a port alone (expected: no, under scip_fraction=0.0). If A fails or B passes, the machinery is doing more than this audit credits — either way you get a number before committing to the 147-feature fan-out.

**Data-dir note:** all audited artifacts are **sandbox** (`/private/tmp/claude-501/…/port-run-0p7/`, `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2`, unmutated). Only in-repo committed artifacts are under `eval/ctkr/` (calibration.parquet, port_runs/, results/port-verify/, results/vertical-slice-logs-quantities.md). This audit read-only; no production data-dir touched.
