# farmOS fan-out — wave plan

> 2026-07-20. The plan for scaling from the validated single-slice recipe to the
> full farmOS port. Every structural choice here traces to a measured result in
> `eval/ctkr/results/` (cited inline). Status: kernel v1 frozen; wave-0 pilot
> in flight; wave 1 pending Duke's morning review of the decided-for-me record
> (`shared-kernel.md` §Resolution record).
>
> Re-read against `epistemology-charter.md` on 2026-07-21. Most of this plan
> already was the charter, written before it was spoken: observation before
> assertion (step 4), the shared kernel, decisions-with-reversal-conditions,
> goalpost discipline, and punt-promotion — the rules evolving through play,
> the infinite game in miniature. The re-read changed vocabulary
> (judge→reader, verdict→reading), restated fresh-reading's rationale as
> saturation rather than suspicion, and added the one thing missing: the
> Elenchus at the wave boundary.

## Preconditions — all met

| prerequisite | status | evidence |
|---|---|---|
| Shared kernel (5 frozen elements) | ✅ v1 merged, decisions bound | `shared-kernel-v1-2026-07-20.md` — 27 fixtures + 5 probes + 5 prevention tests |
| Per-feature recipe validated stage-by-stage | ✅ | surface generation 8/10 (`signature-generation-…`), mining (`semantic-mining-…`), oracle discipline (`signal-matrix-…`), composition (`two-feature-composition-…`) |
| LLM routing + hardening | ✅ | Luna/Terra defaults, repair retry (`gpt56-tier-comparison-…`) |
| Structural gates advisory, decisions elicitable | ✅ | `meta-structural-pass.md`, `ctkr decisions` |
| Port ordering + scoping artifacts | ✅ | boundary map (117 clean slices), feature×kind graph |

## The per-feature production recipe (what each wave runs)

1. **Scope** by read-authoring modules (boundary map + mining read-trace;
   boundary-adjacent included — the 9h5.10 lesson, never island-membership alone).
2. **Surface**: `ctkr propose-adapter` + readback lint (a readback projection for
   every designation flag — closes the only gap 9h5.15 found).
3. **Semantics**: `ctkr mine-fixtures` (CM/luna + graph + source-read/terra).
4. **Observe**: 8–12 fixtures per feature recorded from live farmOS; no
   intuition-authored values, ever (the pure-LLM cell's wrong-guess is the
   standing proof).
5. **Decide**: registry pass; kernel-bound decisions are fixed inputs; new hard
   decisions go to the elicitation menu (batched to Duke at wave boundaries;
   decide-for-me with recorded reversal conditions when authorized).
6. **Build**: one blind builder per feature ON the kernel (KindRegistry, ids/HLC,
   `pickLatest`, status gates, bound CM registry — the primitives make the
   observed failure modes unrepresentable).
7. **Read**: independent per-feature runner + composition smoke against the
   accumulated store + prevention checks (no ad-hoc kinds, no ordinal ids).
   (Formerly "Judge" — vocabulary per `epistemology-charter.md`.)

Per-feature LLM cost, measured: **≈ $0.30–0.60** (surface ~$0.13, mining ~$0.16,
adjudication ~$0.01, builder ~$0.25). 147 features ≈ **< $100 total LLM spend**.
The binding constraints are oracle-observation throughput and Duke's decision
review, not tokens.

## Wave structure

- **Wave 0 (pilot, in flight)** — 2 fresh clean-slice features through the full
  recipe; deliverable is the friction log — read twice: as wave 1's automation
  backlog, and as Elenchus material (what one question do these frictions add
  up to?) — and a wave-readiness reading.
- **Wave 1** — first domain cluster(s), ~10–15 clean-slice features. Clusters
  come from the feature×kind graph: features sharing only kernel kinds
  parallelize; features sharing NEW (non-kernel) kinds serialize through one
  builder or wait for a kind-freeze. Before wave 2, any new shared kinds that
  emerged are frozen into the kernel registry (kernel v1.1 …), via the
  punt-promotion mechanism.
- **Waves 2…n** — remaining clean slices (117 total candidates), wave size set by
  observed wave-1 throughput. The four open validation experiments
  (renamed-farmOS 9h5.17, differential fuzzing 9h5.18, no-live-oracle 9h5.19,
  variance 9h5.20) run opportunistically alongside wave 1 — informative, no
  longer gating.
- **Explicitly NOT features** (the mega-island strategy, per boundary +
  second-opinion R3): `core/*` is ported exactly once — its plugin-type
  contracts ARE the kernel + the per-family adapter surfaces; it is never
  briefed or built as 81 separate features. The compiled `web/profiles/farm`
  tree is duplication — excluded from all counts. UI is a separate
  post-domain-layer decision, not part of this plan.
- **Deferred**: role/permission modules — 14% cross-version survival (idiom, not
  domain), CM-soft access gates; handled later as selective-disclosure policies,
  per the target profile, not as ports.

## Coordination layer (from the 9h5.21–.23 beads)

- **Kernel-keeper**: one long-lived resumed agent owns the kernel (schema, HLC,
  comparator, kind registry). All kind-registration requests route through it.
- **Wave-builders**: each owns a cluster of kind-sharing features sequentially
  (one-mind coherence where it pays — the 27/27 lesson). Fresh builders across
  clusters.
- **Readers & oracle observers: always fresh, never the builder.** Not
  suspicion — saturation: a builder is too deep in its own weeds to see, and a
  fresh reading is the gift that catches what the builder cannot (charter,
  principle 5). The practice is unchanged from the courtroom era; the rationale
  determines what we build next, so it is stated correctly here.
- **Punt-promotion**: deferred-with-dependency decisions are extracted from every
  build (`ctkr decisions` extraction — bead 9h5.22); N punts on one topic
  auto-promote it to a kernel candidate on the wave-boundary elicitation menu.
- **Interrupt**: when a pending shared decision blocks in-flight work (per the
  feature×kind graph), the orchestrator messages the affected builder to
  checkpoint and pause; its decisions are extracted, not lost.
- **Wave-boundary ritual**: full cross-pack regression (all accumulated packs
  against the accumulated store) + target-side coherence check (hom-profile/role
  consistency across the growing codebase — second-opinion R4) + **the
  Elenchus** + elicitation menu to Duke + kernel version freeze.

  **The Elenchus (added 2026-07-21, per the charter).** Before the elicitation
  menu is drawn up, one fresh interlocutor — not a builder, not the
  kernel-keeper — reads the wave WHOLE: every build's extracted decisions and
  punts (the thesis material), the friction log, and the regression results.
  Its deliverable is not a finding list but the **pith**: the one to three
  antithesis questions that say what the wave's scattered frictions were
  trying to say. The synthesis of those questions shapes the elicitation menu
  and the kernel-freeze agenda — so promotion into kernel v1.1 is informed by
  *significance*, not only by the punt-promotion count (frequency catches the
  common punt; the Elenchus catches the important punt that occurred once).
  Kind and forthright: the reading is addressed to colleagues, and it names
  the question the wave's work is avoiding, plainly.

## Standing policies

- **Fixture re-verification**: every pack re-runs against the live oracle on
  farmOS minor-version bumps; drift = fixture update with new observation refs
  (packs are point-in-time observations — second-opinion R2).
- **Oracle hygiene**: per-lane entity prefixes (w0a-, w1-…); periodic oracle
  reset + full pack re-observation when contamination accumulates.
- **Everything sandboxed until promoted**: no production `.metacoding/` writes;
  the accumulated target store lives in-repo under version control.
- **Goalpost discipline**: any change to gates/metrics goes through
  `metric_updates.jsonl` with rationale, replacement signal, and reversal
  condition — no silent redefinition of done.
