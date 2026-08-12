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

   **PRECONDITION — the oracle preflight, and it is not optional** (added
   2026-08-07, `MetaCoding-hy6.25`/`hy6.28`). A build may not begin probing while
   any resource type it names is unresolvable, or is provided by a module
   `bring-up.sh` would not re-enable. A missing module does not crash a run, it
   *degrades* it: on 2026-08-03 two ports probed bundles that were never enabled,
   got 404s and a 422 "the attribute `quick` does not exist", and recorded as
   findings about farmOS what were measurements of the oracle.

   The gate is `farmos-port/tools/oracle_preflight.py` and the way to run it is
   to **build the observe step on `tools/ledger.py`**, which calls it for you
   before the first probe. Three properties, which the ledger holds by
   construction and a hand-rolled `probes.py` must reproduce explicitly:

   - **the gate runs at all** — `ledger.run()` preflights before the body, and a
     probe on an ungated ledger raises;
   - **it is asked the right question** — the type list is DERIVED from the
     run's own `collections`/`delete_order`/`log_collections`, and any probe
     outside that set raises. A hand-written list is one a build can
     under-declare, and an under-declared preflight passes vacuously — which
     `identity-farm-org` did, live, over `taxonomy_term--animal_type`;
   - **a skipped module-drift check is a refusal** — it is required by default
     now. It used to exit 0 when it could not run, which an automated caller
     reads as a pass.

   Source-read-only observation is not an outcome this step may reach. If the
   preflight refuses, the remedy is a declared module in `bring-up.sh` and an
   operator enabling it — never a hand-run `drush en`, which vanishes on the next
   rebuild and takes the reproducibility of everything recorded against it.
5. **Decide**: registry pass; kernel-bound decisions are fixed inputs; new hard
   decisions go to the elicitation menu (batched to Duke at wave boundaries;
   decide-for-me with recorded reversal conditions when authorized).
6. **Build**: one blind builder per feature ON the kernel (KindRegistry, ids/HLC,
   `pickLatest`, status gates, bound CM registry — the primitives make the
   observed failure modes unrepresentable).
7. **Read**: independent per-feature runner + composition smoke against the
   accumulated store + prevention checks (no ad-hoc kinds, no ordinal ids).
   (Formerly "Judge" — vocabulary per `epistemology-charter.md`.)
8. **Exercise**: the port is DRIVEN and the verdict is recorded. `ctkr
   port-verify <pack> --port <build>` replays the sealed observations through the
   port's own bridge and writes a verdict of record under
   `results/port-verify/`. A build with a bridge and no recorded verdict is not
   done; a build whose observations exist only as ledger transcripts is not done
   either, because the judge cannot eat them.

   **Why this step had to be added (2026-08-11).** It was missing, and its
   absence was invisible for exactly the reason a missing step always is: it was
   never a step that could be skipped, because it was never a step. The recipe
   ended at "Read", twenty-one wave-2 builds shipped, and the last port-verify
   verdict of any kind was dated 2026-07-20 — before the wave began. Run cold on
   2026-08-11 the apparatus worked first try and scored 60/60 across the four
   builds that had a replayable pack. The other seventeen shipped 34 port
   manifests and 31 bridges — the whole apparatus for BEING judged — with nothing
   to judge them with.

   Everything wave 2 built to notice things asks whether a RUN behaved. This is
   the step that asks whether the PORT is right, and it is the only one that
   compares the destination to the source rather than to itself.

   **Not yet a step, and it should be:** the port as a RUNNING SYSTEM. There is
   no server, no entry point, no deployable artifact anywhere in the workspace —
   the destination is a library that answers a bridge when asked, and has never
   been started, served or used. A methodology whose goal is a working system has
   to make contact with one.

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

  **When it fires (added 2026-08-09).** Not on memory. The boundary ritual is
  the *scheduled* occasion; the ones that matter are unscheduled, so:

  - **PRECONDITION on the irreversible steps.** Kernel version freeze, wave-close
    sealing, an oracle re-baseline, and the elicitation menu itself may not
    proceed on a stale reading of the whole — `python3 ctkr/ctkr/elenchus.py
    --require-current` exits 2, including when it cannot tell. Same pattern as
    the observe step's preflight: gate the act you cannot take back.
  - **FLAGS, which decide nothing.** `python3 ctkr/ctkr/elenchus.py --epic
    MetaCoding-hy6` prints the reasons it may be time — findings clustering on
    one mechanism, mechanism-hardening whose measured side never leaves one
    build, builds landed since anyone read the whole — and exits 0 whatever it
    finds. Two flags are not computable and are reported as *your call*; they are
    the two strongest. See `epistemology-charter.md` §"When the Elenchus fires"
    for why flags must never become gates here.

  **By hand, when you notice it yourself:** say so and convene one. What the
  interlocutor gets is the wave whole — every build's decisions and punts, the
  friction log, the readings, the open findings — and *not* a thesis from whoever
  has been building, who is saturated by definition. What it returns is one to
  three questions. A findings list is a reader's product; if the deliverable
  reads like a checklist item, it was one, and it should be sent back.

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
