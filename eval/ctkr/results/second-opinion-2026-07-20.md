# Fresh-eyes second opinion — the 9h5 evidence line from altitude

> 2026-07-20 · independent Fable reviewer, clean context, read-only over the nine
> committed reports. Commissioned by Duke: "anything non-obvious we might've
> missed from our detail-oriented view from the ground."

Overall: the experimental hygiene across the nine artifacts is unusually good — blindness protocols, sandbox discipline, pre-registered predictions honestly refuted (Cell B), and the meta-structural pass design is sound. Those conclusions stand; below is what the ground view is missing.

## 1. Threats to validity the reports don't name

**T1 (most important). The hand-authored adapter contract is a hidden human oracle held constant in every experiment.** Every cell — including "pure-LLM" Cell 4 and both m11 builders — received ADAPTER_SIGNATURES.md for free. Authoring it is the hardest cognitive act in the port: someone who understood farmOS decided the read surface is `assetYieldTotal(handle, measure, unit)`, `currentLocations(atTimestamp)`, inventing concepts ("yield total") that per signal-matrix-2026-07-19.md don't exist in farmOS source at all. The ablation line (ablation-brief-oracle-2026-07-19.md) correctly relocated credit brief → fixtures → adapter naming, then stopped. "The machinery adds ~0" is measured strictly downstream of the one step the machinery was never asked to do. This is the circularity: the experiments presuppose an oracle not just in fixtures but in the signature surface, so "oracle is load-bearing" is partly definitional. At 147-feature scale, 147 signature files is the real bottleneck; whether the graph/mining/glossary machinery can generate candidate adapter surfaces is unmeasured — and is exactly where it could plausibly be decision-bearing (deciding WHAT to fixture, not how values behave).

**T2. Pretraining contamination is never mentioned in any report.** farmOS is public and well documented; the builder model has seen farmOS.org/model and Drupal idiom in pretraining. Cell 4's 14/17 from raw source and the m11 builders' 7/7 on non-obvious semantics may be inflated by prior familiarity. The commercial regime — proprietary legacy code with zero pretraining presence — is where briefs/graphs could have much higher marginal value, and it is untested.

**T3. The graph was tested at its weakest, and the conclusion is stated generally.** scip_fraction=0.0, no data edges, DI wiring invisible, duplicated source tree (graph-as-tool-2026-07-19.md §4). "Graph ~0" is confounded with "the PHP graph is broken on this codebase." farmOS is also behaviorally thin (declarative config + small services); a codebase with real algorithmic structure is a different test. One codebase, one target paradigm, one builder model, n=1 per cell — individually flagged, but the aggregate strategy conclusion rests on roughly eight unreplicated points on one corpus.

**T4. The "fixture values are load-bearing" headline rests on one fixture** — ce015be4, the single discriminator among 10 hardening fixtures. Real, but thin; a different hardening pack could shift the attribution between names/prose/values.

**T5. The strategy silently assumes a runnable legacy system.** Fixtures are observed from live Docker farmOS. Most legacy ports have no runnable instance. Remove that assumption and the ranking flips: the source-read mining lane (which recovered latest-wins verbatim from GroupMembership.php, semantic-mining-9h5.10.md Run B) becomes the primary channel and the oracle-centric strategy is unavailable. No report states this scope condition on the headline conclusion.

## 2. Non-obvious leverage being undervalued

**L1. Cross-builder differential testing as an automatic discriminator miner.** Cell 4 and the pipeline builds fail on complementary axes (pure-LLM passes latest-wins, fails yield conventions; fixture-driven builds the inverse). Build twice (once from source, once from fixtures), fuzz both adapters with generated flows: every output disagreement is a ce015be4-class discriminator found without a human or a miner lane. Cheaper and more complete than the three-lane miner; nobody has proposed it.

**L2. Property-based differential replay against live farmOS as an independent acceptance layer.** Fixtures-as-spec means unfixtured semantics fail silently. recorder.py already drives live farmOS; replaying randomized flows against both farmOS and the port converts the pack from "the spec" into "the regression floor."

**L3. The mining scope finding contradicts the boundary finding — the composition is the lesson.** boundary-quality-farmos-v2-2026-07-20.md says cross-island behavioral coupling is "effectively nil"; mining showed the sole logs+quantities discriminator is authored in asset/group, a different island, coupled invisibly through DI/string wiring the graph cannot see. Island-based scoping for the fan-out will systematically miss cross-island read semantics; use the miner's read-tracing (which modules author a feature's READS) as the scoping tool, not islands alone.

**L4. The N=2 differential (farmos-differential.md) is called the strongest asset yet only feeds dials.** Survival tiers could prioritize fixture authoring directly: high-survival signals (asset_type roots, 83%) are port-critical and fixture-worthy; low-survival (permissions 14%, module names 30%) are idiom to skip.

## 3. Strategic risks for the 147-feature fan-out

**R1. Per-feature passes don't compose.** All experiments build isolated stores. The target is one event log, one asset model, one ID scheme shared by features whose projections overlap (group membership, location, inventory all fold the same logs). Two features can each go 17/17 while disagreeing about shared projections. Direct evidence of global divergence: 0p7 chose weaken-to-eventual for birth uniqueness; both ablation cells independently chose preserve-via-convergence-rule from identical inputs. 147 blind builders will produce locally-valid, mutually incompatible architectures unless the wave structure ships a shared kernel (event schema, ID/HLC scheme, binding CM-decision registry) before wave 1.

**R2. Fixture-pack economics and drift.** ~15 fixtures × 147 features = 2,000+ live-observed fixtures plus 147 hand-authored signature files; entity-prefix contamination is already accumulating (m10-, m11-) on one shared Docker instance; fixtures are point-in-time 4.x observations with no stated re-verification policy.

**R3. The two mega-islands are ~90% of nodes and outside the validated regime.** Everything validated ran on persistence-1.0 small islands; core (3,750 nodes, persistence 0.615, 81 declared modules collapsed into one blob) and the compiled profile tree (3,524, largely duplication) are where farm_entity, plugin bases, and UI live. The fan-out needs an explicit core answer — likely: port the plugin-type contracts once as the R1 shared kernel, never brief core as features — plus source dedup before counts are trusted.

**R4. Nothing measures the port's quality as a codebase.** Acceptance is value equivalence only; 147 independently generated modules can all pass fixtures and still be incoherent. Cheap fix: run the port-side hom-profile/role machinery across the accumulating target codebase — a place the CT machinery could earn keep, since the target paradigm is uniform.

## 4. What to measure next (not yet proposed by the team)

1. **Signature-generation ablation** (attacks T1). Pipeline proposes the adapter contract for a fresh feature; judge against a hand-authored reference and by whether a builder + observed fixtures over the generated surface still passes.
2. **Renamed-farmOS run** (attacks T2). Consistently obfuscate domain identifiers in the source given to a Cell 4-style builder; if 14/17 collapses, pretraining familiarity is doing hidden work and all prior numbers carry that asterisk for proprietary code.
3. **Two-feature composition run** (attacks R1). logs+quantities and location into one shared store; measure cross-feature fixture pass and count conflicting design decisions. The smallest experiment that tests what the fan-out actually is.
4. **Cross-builder differential fuzzing** (L1/L2). Count new discriminators per dollar versus the 9h5.10 miner; the winner becomes the hardening engine for all 147 packs.
5. **No-live-oracle cell** (attacks T5). Build from miner source-read candidates alone, no observed values; score on the observed pack. Measures the regime most commercial legacy ports occupy.
6. **Replicate one existing cell 3–5×.** Everything is n=1; spend the ~$1 to learn the variance before betting the fan-out on the attribution ordering.

**Verdict:** the proximate conclusions are well-earned — brief ~0, interactive graph ~0 GIVEN the oracle, fixture values carry the non-obvious semantics, mining works iff scope includes the read-authoring module. The strategic overreach is treating "oracle-centric" as a property of porting rather than of this experimental setup: a runnable system, a hand-authored signature surface, a pretrained-on public codebase, and per-feature isolation were all held fixed, and each is exactly what the 147-feature fan-out (and any commercial engagement) will violate first. Highest-value next spend: the signature-generation ablation and the two-feature composition run — they test the two assumptions the entire current story rests on.
