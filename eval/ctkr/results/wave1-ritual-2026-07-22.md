# Wave 1 — boundary ritual record (2026-07-22)

> The first wave under the epistemology charter. Four log-family features
> (activity, observation, harvest, input) through the full production recipe:
> parallel prep lanes, one-mind build cluster (kind-sharing features serialize
> through one builder), fresh readers, cross-pack regression, the Elenchus.
> Run: workflow `wf_e722d141-4d4`; artifacts under `eval/ctkr/port_runs/wave1/`.

## The numbers

| feature | pack (sealed) | fixtures | reading | clean |
|---|---|---|---|---|
| activity | `761d70409a77` | 12 | 25/28 = 89.3%, 3 failures | no (exit 1) |
| observation | `edc3f5f49731` | 12 | 38/42 = 90.5%, 4 failures | no (exit 1) |
| harvest | `d3720566ae3c` | 12 | 33/37 = 89.2%, 4 failures | no (exit 1) |
| input | `d7f7ad0b8fe7` | 12 | 35/39 = 89.7%, 4 failures | no (exit 1) |

48 fixtures recorded live, 0 validation errors, 0 leaks, all seals verified.
Builds: 32/32 bun tests green on one shared `Wave1LogStore`. Regression: ctkr
pytest 638 green (1 skip), kernel 66/66, both shipped packs re-validated. No
guardrail crossed in any lane: no glossary/kernel edits, no oracle restarts, no
authored values. Readers proved their trees (HEAD `d7ec309`, seals echoed by
port-verify). No suspicious perfect scores — every port has declared gaps.
Prep LLM spend ≈ $0.85 total.

## The one mechanism behind all 15 failures

Every failure in every reading is the SAME divergence: the kernel's
confirmed-only gate on `yield_total`/`log_count` (Duke's deliberate
pending-status-gates choice, 2026-07-20) versus the observed source, which
counts pending, reopened, and future-dated logs. The divergence is *chosen and
documented* — and scored as "undeclared mismatch" anyway, because the
cm-decisions registry text names the camelCase projections
(`yieldTotal`/`logCount`) while `decision_covers()` matches the glossary terms
(`yield_total`/`log_count`). The instrument cannot currently tell the wave's
most-vetted decision from a bug. Filed as the top wave-2 blocker.

## The Elenchus — pith questions

1. **When an honest, Duke-bound divergence scores identically to an accidental
   bug — what is "reproduced 89%" actually measuring**, and why plan wave 2
   before the instrument can tell a choice from a defect?
2. **Did wave 1 verify four features, or the same shared log spine four
   times?** Each feature's distinguishing identity (harvest's `lot_number`,
   input's material-type filter, observation's selection workflow and
   cascades, the `abandoned` third status all three log preps hit) is
   glossary-unreachable and rests on builder-written tests alone — which the
   charter says are never load-bearing. What must the glossary grow before the
   wave's breadth is real rather than nominal?
3. **Authored intent keeps leaking into the sealed instruments** — flow titles
   contradicted by their own recorded values, contracts bloated through the
   fixture-candidates channel, mining ranks dominated by storage idiom in all
   four runs. Who, or what lint, audits the author's prose against the
   observed values before the seal makes the prose permanent?

## Elicitation menu (for Duke — each with its reversal condition)

**The gate question (three items, one knot):**
1. Re-affirm or re-bind pending-status-gates for the log family: keep
   confirmed-only `yield_total`/`log_count` (ports keep failing those
   fixtures, sanctioned) vs re-bind to source fidelity (ungated). *Reversal:
   re-bind and re-run port-verify against the already-sealed packs; no
   re-observation needed either way.*
2. Make the sanctioned divergence declarable: amend the registry text (and
   `src/kernelConfig.ts` mirror) to name the glossary terms so
   `decision_covers()` resolves — or extend the manifest/verifier divergence
   format. *Reversal: re-run the four readings; 15 undeclared mismatches
   become diverged(ok).*
3. Instrument ruling: should port-verify score a bound-decision divergence it
   cannot resolve as FAIL (current) or as a new sanctioned-divergence-
   undeclared category? *Reversal: verifier flag; re-score both readings.*
4. STATUS_CONTRACT: bind `log_count`/`yield_total` rows explicitly, noting the
   three newly observed axes — status-ungated, not as-of-gated, summed across
   log kinds (4/4 preps flagged it). *Reversal: a contrary oracle observation
   on any axis.*

**Glossary growth batch before wave 2** (additive; unused terms retire at next
freeze): (a) `lot_number` — shared by harvest/seeding/input, auto-promotion
threshold met; (b) material-type assertion for input's filter; (c) `abandoned`
as a third LOG_STATUS (3/4 features hit it); (d) `delete_log`/`delete_quantity`
(and optionally `clone`) verbs for the ownership cascades; (e) land descriptor
vocabulary, or bless descriptor-less land.

**Kernel v1.4 freeze agenda from punts:** no-as-of-gate on folds; unit-name
opacity (kilogram ≠ kilograms, no normalization); abandoned ≡ not-confirmed;
the two-timelines rule stated once (workflow/revision reads gate on record
time, log listing on effective time — hit as a live bug during build); new
kinds to bless or rename (`selection_started`/`selection_confirmed`,
`planting_plan_created`/`birth_recorded`/`revision_marked`,
`log_deleted`/`quantity_deleted`); family list-ordering coherence
(`getFirstLog` means "newest" in activity and "earliest" in observation);
kernel import mechanism (7-level relative paths vs a workspace alias);
birth-uniqueness stance vs source refuse-at-write (w1c-6).

**Recipe hardening (tooling-only, instrument-tier):** title/value-contradiction
lint at record time; readback lint dropping candidate-only contract methods;
CM-decision provenance stamped into contracts; enforce read-only sandbox
data-dirs (ctkr wrote `llm_cache/` into the shared graph dir); scope-yield
warning on propose-adapter; SEMANTICS-before-SURFACE stage order default.

## Charter note

The wave's texture is the charter working: no reader celebrated or softened;
the builders' one deliberate divergence was reported by the builders
themselves in their bridges and punts; every blocked expressibility gap was
filed instead of improvised; and the Elenchus's first question aims at the
instrument, not at any builder — exactly where full weight belongs.
