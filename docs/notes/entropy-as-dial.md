# Entropy as a dial, not a gate

Working note from the 2026-05-28 session. Reframes how CTKR should treat Shannon entropy of hom-profile distributions — from a hard threshold to a tunable parameter exposed to callers. Connects to [persistent clustering](../design/ct-pipeline.md#open-theoretic-questions) and to the stochastic-CTKR direction in [the design session notes](./2026-05-28-ctkr-design-session.md).

## The starting frame (what we had)

Phase 2a's entropy-check tool treats Shannon entropy as a **gate**: ≥ 4.0 bits → PROCEED, < 4.0 → BLOCKED. The threshold expresses "the edge-type alphabet needs to produce at least ~16 effective profile shapes before downstream clustering has signal."

This framing is useful but incomplete. It treats entropy as a single number describing the corpus, when it is actually a measurement of a distribution produced by a particular *equivalence relation* on profiles.

## What's actually variable

We don't directly tune entropy — we tune the parameters that produce the profile distribution, then *measure* entropy on the result. There are at least three primary dials:

1. **Profile discretization** — L1-normalized profile vectors get rounded to nearest `1/k` step before equality comparison. Small `k` → coarse buckets, low entropy, easy clustering. Large `k` → exact matches required, high entropy, sparse clustering.
2. **Kinds filter** — which `Symbol.kind` values participate. Drop `file` and entropy jumps because 5,595 essentially-identical profiles leave the denominator. Same data, different vocabulary.
3. **Edge alphabet subset** — restrict to e.g. `{CALLS, IMPLEMENTS, INJECTS}` to get a coarser-but-more-behaviorally-meaningful distribution than using all 14 kinds.

Each dial setting produces a different entropy reading *and* a different clustering output. There is no privileged setting; the right one depends on what the caller wants downstream.

## The std-dev analogy

This is the same structure as choosing the bandwidth of a Gaussian kernel in density estimation, or the radius in DBSCAN. You're sliding along a **rate-distortion curve** (information theory's formal name for this trade-off):

- Low rate (low entropy) → high compression, few categories, distinctions smoothed away.
- High rate (high entropy) → high fidelity, many categories, real distinctions preserved.

The dial picks a point on the curve. Different downstream tasks want different points:

| Layer | Wants the dial set to |
|---|---|
| **Phase 2a — role equivalence** | a region coarse enough that `crewAI.Agent` and `autogen.ConversableAgent` cluster, fine enough that `Agent` and `Tool` don't |
| **Phase 2b — functor discovery** | finer; we map specific symbols across repos, not just buckets |
| **Phase 2c — colimit construction** | *persistence* across multiple settings; robust role classes survive different coarsenesses |

## Persistent clustering — the principled use

Picking one dial setting is fragile. The principled move is to sweep across settings and ask which pairs of symbols **persistently** cluster together:

```
For each dial setting d ∈ [coarse, fine]:
  compute role-cluster assignments at d
  track which symbol pairs cluster together

Then:
  pairs clustering together at almost every d        → deeply equivalent
  pairs clustering only at d below some threshold    → weakly similar
  pairs clustering only at d above some threshold    → spurious / overfit
```

This is persistent homology's filtration construction, applied to clustering granularity. The persistent pairs are the ones the categorical claim is *robust to dial choice*. The ephemeral pairs are honest about being resolution-dependent.

Already tracked as a follow-up in [`ct-pipeline.md`'s open theoretic questions](../design/ct-pipeline.md#open-theoretic-questions). This note reframes it as *the* recommended usage pattern rather than a v2 enhancement.

## Reframing the 4.0 threshold

The 4.0 number was being treated as a target. It's more accurately a **capability check**:

> The edge alphabet needs to be rich enough that the dial *can* be turned to varying useful entropies. If maxing out the granularity dial still yields < 4.0 bits, no downstream dial choice will recover the missing roles — the alphabet itself is too impoverished.

Below the floor, every dial setting produces a degenerate signal. Above it, entropy stops being a gate and joins the family of tunable parameters exposed to callers.

The 9le iteration plateau (3.65 bits even with the maxed-out tree-sitter edges) is therefore not a *failure* of the dial framing — it's evidence that **CALLS and REFERENCES are missing from the alphabet** (because tree-sitter doesn't populate them at scale; SCIP is the only lane). The `--scip` reindex (bead `MetaCoding-73m`) is the next test of whether the alphabet can clear the capability floor.

## Implications for the MCP surface

Several CTKR Phase 2+ tool signatures should expose dial parameters explicitly:

- `ctkr.role_equivalent(symbol, granularity?, kinds_filter?)` — let callers control profile discretization and Symbol-kind inclusion.
- `ctkr.essence(scope, persistence_threshold?)` — return only role classes that persist across a range of granularities.
- A diagnostic tool `ctkr.profile_entropy(kinds_filter?, edge_subset?)` — let callers measure entropy at proposed dial settings before committing.

This means hom-profile artifacts (`hom_profiles.parquet`, bead `MetaCoding-23q.1`) should be stored at maximal granularity. Discretization happens at query time, so the same artifact serves coarse and fine queries without regeneration.

## Stochastic generalization

Following the [stochastic CTKR thread](./2026-05-28-ctkr-design-session.md#the-users-persistent-clustering-derivation-the-surprise-of-the-session) opened earlier in the session: instead of picking a dial value, *sample* dial values from a distribution. Each sample produces a clustering. Aggregate across samples for posterior probabilities of role-equivalence.

- Persistent pairs become high-posterior pairs.
- Ephemeral pairs get honest uncertainty intervals.
- The "Gaussian with outliers" intuition becomes the rigorous Bayesian construction: the posterior over role-equivalences has both mass and spread, and we can report both.

This is roadmap material, not v1. But it follows naturally from the dial framing and should be tracked.

## What changes vs. what doesn't

- **Entropy as a corpus health check stays.** The `ctkr entropy-check` script and the BLOCKED/PROCEED verdict remain useful as a capability gate before alphabet-extension work.
- **Entropy as a single privileged threshold goes.** Downstream tools should not bake in 4.0 (or any other) as a hard cutoff. They take the dial as a parameter.
- **Persistent clustering rises in priority.** Was a future research item; should become a near-term P2 feature once the capability floor is crossed.
- **Artifact shapes hold lightly.** Profile vectors should be stored at maximal precision; quantization is query-time.

## Related

- [`2026-05-28-ctkr-design-session.md`](./2026-05-28-ctkr-design-session.md) — original stochastic-CTKR thread.
- [`../design/ct-pipeline.md`](../design/ct-pipeline.md) — Phase 2a and the open theoretic questions section.
- `MetaCoding-23q.1` — Python hom-profiles subcommand (should emit max-precision artifacts).
- `MetaCoding-o7k` — filed mitigation for filtering file/leaf kinds; this note generalizes that bead's question.
