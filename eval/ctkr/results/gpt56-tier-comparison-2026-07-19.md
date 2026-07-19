# GPT-5.6 tier comparison — Sol / Terra / Luna vs the Claude mix (MetaCoding-9h5.6)

**Workload:** the fixed **logs+quantities vertical slice** (MetaCoding-0p7), re-running the
four LLM-bearing CTKR pipeline stages — `intention-synthesis` (T5b), `extract-spec`
(cards), `intent-cm --adjudicate`, `port-brief` — against a per-condition copy of the
scoped 0p7 sandbox data-dir.

- **Date:** 2026-07-19
- **Worktree branch:** `worktree-agent-aa2bf6bf1361556de` (isolated git worktree; not pushed, bead not closed)
- **Conditions:** (a) `claude-baseline` = cached 0p7 outputs (haiku-4.5 cheap + sonnet-4.6 strong), **not re-spent**; (b) `gpt-5.6-luna`; (c) `gpt-5.6-terra`; (d) `gpt-5.6-sol` — all provider `openai`.
- **Runs per condition:** **1** (single run). GPT-5.6 reasoning tiers **cannot pin temperature** — the OpenAI reasoning contract rejects it — so re-runs vary. Every GPT number below is one sample, not a converged mean. This matters most for the stochastic scenario-distillation result (see Findings).
- **Budget cap:** abort any condition over **$3**. Actual peak (sol) = **$0.462**. No abort.
- **Ground truth (CM):** the slice has **1** known CM-hard seed — the birth-log `unique-constraint`. "Found it? extras?" is the CM recall/precision check.

All data-dirs are **sandbox copies**. Absolute paths + how they differ from production are in the last section.

---

## How the tiers were routed (code change)

The pipeline selects provider only through `LLMClient(default_provider=…)`; the stage
code never passes a per-call provider, and the tier is chosen via the existing
`--model` / `--adjudication-model` / `--subsystem-model` / `--fusion-model` flags. Two
minimal additions made the comparison runnable (tests included, all green):

1. **`--provider` flag** on the four command modules (`intention_synth`, `extract_spec`,
   `intent_cm`, `port_brief`), threaded into `LLMClient(default_provider=…)`. Default
   `anthropic` — zero behavior change for existing callers.
2. **Reasoning `max_completion_tokens` floor** in `llm.py`
   (`LLMClient.reasoning_max_tokens = 16000`, applied only when
   `_is_openai_reasoning_model(model)`). GPT-5.x tiers bill *reasoning* tokens against
   `max_completion_tokens`; the stage caps sized for Claude (900–2000) can be fully
   consumed by reasoning, truncating the structured payload to empty. The floor is a
   cap, not a charge — cost-safe, and leaves the Anthropic path untouched.

Invocation per GPT stage, e.g.:
`ctkr intention-synthesis --data-dir <D> --provider openai --model gpt-5.6-luna --adjudication-model gpt-5.6-luna`.

---

## Cost table (real spend — non-cached rows from each condition's `llm_cost.jsonl`)

| condition | tier price (in/out per 1M) | input tok | output tok | **total USD** | vs baseline |
|---|---|---|---|---|---|
| claude-baseline | haiku 0.80/4 + sonnet 3/15 | 71,677 | 12,959 | **$0.2207** | 1.00× |
| gpt-5.6-luna | 1.00 / 6.00 | 34,415 | 11,912 | **$0.1059** | **0.48×** |
| gpt-5.6-terra | 2.50 / 15.00 | 34,647 | 8,615 | **$0.2158** | **0.98×** |
| gpt-5.6-sol | 5.00 / 30.00 | 34,770 | 9,597 | **$0.4618** | **2.09×** |

Per-stage USD:

| stage | baseline† | luna | terra | sol |
|---|---|---|---|---|
| T5b intention-synthesis | $0.091 | $0.0542 | $0.1082 | $0.2469 |
| extract-spec (cards) | $0.060 | $0.0403 | $0.0809 | $0.1607 |
| intent-cm --adjudicate | $0.006 | $0.0011 | $0.0030 | $0.0054 |
| port-brief (ss:761b fusion) | $0.0386 | $0.0102 | $0.0237 | $0.0488 |

† Baseline per-stage figures are the published 0p7 Stage-1 table (T5b/cards/intent-cm) plus
the ss:761b fusion cost from `port_briefs/manifest.json`. The 0p7 headline "$0.2593" counts a
re-run **cached** fusion row a second time; the reproducible real (non-cached) 4-stage total in
the cost log is **$0.2207**, used above. GPT per-stage figures are from each stage's own stderr.

**Cost read:** luna is ~half the baseline; terra lands within 2% of baseline; sol is ~2× baseline.
GPT input-token counts are ~half baseline (34.4–34.8k vs 71.7k) because the Claude baseline mixed
haiku+sonnet with larger prompt framing; output tokens are comparable **despite** the GPT tiers
also spending hidden reasoning tokens (billed but not shown in `output_tokens`), which is why
sol's dollar cost climbs faster than its visible output.

---

## Quality table (mechanical where possible)

| metric | baseline | luna | terra | sol |
|---|---|---|---|---|
| T5b elements | 11 | 11 | 11 | 11 |
| intent statements | 21 | 19 | 15 | 19 |
| **empty-intent count** | 0 | 0 | 0 | 0 |
| intent citations resolved | 74 | 146 | 109 | 130 |
| **unresolvable citations (dropped)** | 0 | 0 | 0 | 0 |
| **scenario distillation** | ✅ ok | ❌ **schema fail** | ✅ ok | ❌ **schema fail** |
| T5b scenarios produced | 2 | 0 | 1 | 0 |
| adjudications (flagged) | 8 | 9 | 8 | 9 |
| tension / consistent | 5 / 3 | 4 / 5 | 5 / 3 | 3 / 6 |
| confirmed contradictions | 0 | 0 | 0 | 0 |
| **CM seeds found** (GT = 1 hard) | 1 ✅ | 1 ✅ | 1 ✅ | 1 ✅ |
| CM extras / false seeds | 0 | 0 | 0 | 0 |
| CM sensitivity verdict | hard | hard ✅ | hard ✅ | hard ✅ |
| brief exports / roles / ops / shapes | 1 / 6 / 2 / 4 | 1 / 6 / 2 / 4 | 1 / 6 / 2 / 4 | 1 / 6 / 2 / 4 |
| brief scenarios | 2 | 0 | 1 | 0 |
| brief warnings | 5 | 4 | 4 | 3 |
| brief glossary terms | 13 | 16 | 10 | 14 |
| target-adaptation notes | 1 | 1 | 1 | 1 |

**Structural completeness of the brief (exports/roles/ops/shapes = 1/6/2/4) is identical
across all four conditions** — the load-bearing S-lane shape is model-invariant on this slice.
The only structural divergence is **scenarios** (which flow from T5b distillation) and a modest
drop in **warnings** (baseline 5 → 3–4 for the GPT tiers; terser conflict surfacing).

### Scenario-distillation schema failure (the one real defect)

`ScenarioDistillOut` requires a nested `then` field per scenario. **luna and sol** each
returned a scenario object shaped `{"behavior": …}` (missing `then`) → pydantic
validation error → the call degraded to **0 scenarios** (graceful; stage still exits 0,
1 `failed/degraded` call logged). **terra** produced a conforming scenario.

Because the tiers can't pin temperature and this is a single run each, treat this as a
**stochastic robustness risk on the nested-schema call, not a per-tier fixed defect**:
2 of 3 reasoning tiers tripped it this run. It is the one place the GPT tiers are not yet
drop-in for the cheap Claude labeler.

### CM adjudication — all three tiers nailed the ground truth

Every tier found **exactly** the 1 CM-hard `unique-constraint` seed, graded it **hard**,
0 false positives, with a correct, well-cited rationale:

- **terra:** *"`addConstraint('UniqueBirthLog')` assumes globally exclusive uniqueness for an
  asset's birth-log relation, which concurrent offline replicas cannot enforce without a
  conflict-resolution or coordination rule (log/birth/src/Hook/FieldHooks.php:31)."* — cites file:line.
- **sol:** *"The `UniqueBirthLog` constraint assumes globally unique birth-log assignment …
  which concurrent offline replicas can violate unless a conflict-resolution or coordination
  strategy is chosen."*
- **luna:** *"The source declares a UniqueBirthLog constraint … concurrent local writes can
  admit duplicate values, so preserving this invariant requires a chosen coordination or
  conflict-resolution strategy."*

All three are semantically equivalent to the baseline sonnet rationale. On this
highest-stakes, cheapest stage the tiers are indistinguishable from Claude in quality.

### Qualitative diff — target-adaptation notes

All four briefs render the identical structural note (source assumption → sensitivity →
decision menu: preserve-via-convergence-rule / weaken-to-eventual / move-to-disclosure-layer).
The prose rationale differs only in phrasing; **terra** is the most precise (keeps the
`addConstraint('UniqueBirthLog')` symbol + file:line), **luna/sol** are slightly more abstract
but correct. No tier hallucinated a wrong resolution or dropped the decision menu.

---

## Cost-per-quality summary

| tier | $ vs baseline | CM seed | scenario distill | adjudication vs baseline | net read |
|---|---|---|---|---|---|
| **luna** | 0.48× (cheapest) | ✅ exact | ❌ failed (0) | shifted (4/5 vs 5/3) | half price, seed-perfect, but lost scenarios this run |
| **terra** | 0.98× (≈ parity) | ✅ exact | ✅ ok (1) | **identical (5/3, 8 flagged)** | baseline-equivalent quality at baseline cost; most robust GPT tier |
| **sol** | 2.09× (dearest) | ✅ exact | ❌ failed (0) | more conservative (3/6) | 2× cost, **no measurable quality gain**, same scenario failure as luna |

Sol buys nothing over terra on this workload while costing 2×; on the one stage where a
stronger reasoner might help (adjudication) it produced *fewer* tensions than baseline and
still tripped the scenario schema.

---

## Recommendation

**Per-stage routing (this slice; confirm on a second slice before production):**

1. **`intent-cm --adjudicate` → switch to `gpt-5.6-luna`.** All tiers found the exact
   ground-truth seed with a correct rationale and zero false positives; luna is the cheapest
   ($0.001–0.005) and this is the highest-stakes, lowest-volume LLM stage. Clear win.
2. **`port-brief` fusion → `gpt-5.6-terra`.** Complete brief (1/6/2/4), correct adaptation note,
   fusion cost $0.024 vs the baseline sonnet's $0.039 — cheaper *and* on-quality.
3. **`extract-spec` / `intention-synthesis` strong (sonnet-class) role → `gpt-5.6-terra`.**
   It reproduced the baseline adjudication verdicts **exactly** (5 tension / 3 consistent, 8
   flagged) at ~baseline cost. It is the safe sonnet-fallback replacement.
4. **Cheap (haiku) labeler role → hold / conditional.** luna at half price is attractive and
   its intents/glossary/CM are sound, but **the scenario-distillation `ScenarioDistillOut`
   schema failure (luna + sol, 2/3 tiers) is a blocker** for moving the cheap labeler off haiku.
   Harden that call first (accept a `behavior`/`then` alias or add a one-shot repair retry),
   then re-test; luna becomes the cheap default once the nested-schema call is robust.
5. **Do NOT adopt `gpt-5.6-sol` for this workload.** 2× cost, no quality gain, and it failed the
   same scenario call as luna. Reserve sol (if ever) for a genuinely harder reasoning stage this
   slice doesn't exercise.

**Cross-cutting blocker filed by evidence:** `ScenarioDistillOut` parsing is brittle against
GPT-5.6 reasoning JSON output. This should be hardened regardless of the tier decision — it is
the single defect this comparison surfaced.

**Honesty notes:**
- Single run per condition; reasoning tiers cannot pin temperature, so the scenario-distillation
  pass/fail split (terra ok, luna/sol fail) is a **sample**, not a stable per-tier property.
- The GPT input-token counts (~34k) are lower than baseline (~72k) because the baseline is a
  haiku+sonnet mix with different prompt framing; dollar figures, not token counts, are the
  comparable axis. Reasoning tokens are billed but invisible in `output_tokens`.
- No stage refused or errored after retries on any tier. The only degradation was the
  scenario-distillation schema validation (graceful, logged, non-fatal).

---

## Sandbox paths (all sandbox — none is production)

Production for this pipeline = the path a downstream consumer (`serve`, MCP, eval harness)
reads by default, i.e. a real `$…/.metacoding/`. **Everything below is a scratch copy; no
production data-dir was read or mutated.**

- **Read-only baseline original (copied, never mutated):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/port-run-0p7/data-dir`
  — the scoped 0p7 slice (subsystems pruned to 2 / 137 members). Its `llm_cost.jsonl` supplied the reused `claude-baseline` costs.
- **Per-condition sandbox copies (this run):**
  - luna: `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/gpt56/luna/data-dir`
  - terra: `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/gpt56/terra/data-dir`
  - sol: `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/gpt56/sol/data-dir`
  - Each is a `cp -R` of the baseline data-dir with `llm_cost.jsonl` deleted before the run so per-condition spend is isolated. The copied `llm_cache/` contains Claude entries only; GPT calls hash to different keys (provider+model+reasoning) → all real, all logged.
- **Shared read-only inputs (not copied, not mutated):** repo-root `…/port-run-0p7/repos` (farmOS source for `extract-spec`), source-root `…/port-run-0p7/cm-src` (PHP for `intent-cm`), target profile `docs/design/target-profiles/farmos-local-first.yaml` (in-repo).
- **Driver + extractor (sandbox):** `…/7c92fede-…/scratchpad/gpt56/run_condition.sh`, `…/gpt56/metrics.py`, per-condition stage logs `…/gpt56/{luna,terra,sol}.log`.

**How each differs from a production reindex:** the data-dir is the 0p7 *scoped* slice
(subsystems pruned to logs+quantities only, 137 members, not the full 8,059-node farmOS v2
graph); only the 4 LLM stages were re-run (structural artifacts were reused from the copy, not
recomputed); `port-brief` was scoped to `--subsystem ss:761b7d53e7a231e2cf7a7782` (1 brief, not
the full deck). Nothing here should be promoted to a production `.metacoding/`.
