# 2-hop hom-profiles — breaking the structural symmetry that failed the gate

**2026-07-13 · GATE CLEARS · production feature (opt-in `--depth 2`) + spike re-measurement.**

The [Task-1 spike](./README.md) failed the functor-discovery gate: `rename_fork_correctness`
plateaued at **0.86 (< 0.90)** because 1-hop hom-profiles cannot distinguish symbols that are
structurally identical at one hop (68.9% in non-trivial 1-WL orbits, largest 834). This note
implements **depth-2 profiles** (one Weisfeiler-Leman color-refinement round) as an opt-in mode
on `ctkr hom-profiles` and re-runs the exact spike harness on the real scip corpus.

**Verdict: 2-hop clears the gate.** `rename_fork_correctness` **0.863 → 0.987**, structural
candidate recall **0.836 → 0.998**. The zero-profile 22.7% ceiling is real and untouched (as
predicted) but does not block the gate. 2-hop seeds unblock functor discovery.

## The scheme (edge-typed neighbor-mean, one WL round)

For each symbol `s`:

```
profile_2hop(s) = concat(
    profile_1hop(s),                                  # NDIM self dims
    for each (edge_kind, direction) block in DIMS:    # NDIM blocks …
        mean( profile_1hop(t) for t reached from s via that (kind,dir) )   # … of NDIM dims each
)
```

- Dimensionality `NDIM + NDIM*NDIM = 30 + 900 = 930` (NDIM=30 = 15 edge kinds × {in,out}).
- Float64 variant (block means are fractional), exactly like the existing `kind_weights` path.
- Keying the neighbor aggregation by the **connecting edge type** is the most orbit-discriminative
  tractable scheme — it is a lossy but faithful continuous encoding of one 1-WL refinement round
  (the multiset `{(kind,dir,color(t))}` that provably splits many 1-WL orbits). On the real corpus
  it recovers essentially the full idealized WL split (see below).
- Neighbor 1-hop vectors are drawn over the **full graph** (an excluded-`kind` neighbor still
  contributes its real profile), preserving the o7k edge-counting invariant at depth 2.
- Compute cost: **~0.4–0.6 s** for the ~4.7k-symbol corpus (negligible vs indexing).

Opt-in via `ctkr hom-profiles --depth 2`. **Default stays `--depth 1`, byte-identical** to the
historical raw-UInt32 artifact (verified: md5-stable across reg:regen, and all pre-existing
`test_hom_profiles.py` tests unchanged). Depth is recorded in the manifest (`profile_depth`).

## Corpus

Same construction as the [README](./README.md): MetaCoding self indexed with `--scip`
(`repo=base`, 4291 scip symbols / 5779 edges) and a `src/`→`lib/` rename fork (`repo=fork`,
4274 / 5709). After `--kinds-filter file`: base 4671 rows, fork 4640. Near-perfect isomorphism
(the tiny count drift is from `src/` string literals in the rename); to control for it, **depth 1
and depth 2 are both run through the identical pipeline on this corpus** — the depth-1 numbers
reproduce the original spike (`rename_fork_correctness` 0.863 ≈ 0.86; `candidate_recall_orbit_nonzero`
0.951 ≈ 0.957; zero-profile 22.7% ≈ 22.5%), so the comparison is internally consistent.

## Orbit collapse (primary success metric)

Fraction of symbols sitting in a **non-trivial profile-equivalence class** (identical profile
vector ⇒ name-blind-indistinguishable), on the base corpus:

| | depth 1 (1-hop) | depth 2 (WL round) |
|---|---|---|
| symbols in non-trivial class | **89.9%** (4198/4671) | **69.3%** (3239/4671) |
| … among **non-zero** symbols | 86.9% (3139/3612) | **60.4%** (2180/3612) |
| distinct profile classes | 664 | **1930** (2.9×) |
| largest class | 1059 | 1059 (unchanged) |
| zero-profile symbols | 22.7% (1059) | 22.7% (1059) |

- The **89.9% → 69.3%** drop is the direct attack on the symmetry. Note 69.3% ≈ the README's
  idealized "68.9% in non-trivial 1-WL orbit after one WL round" — the mean-aggregation scheme
  recovers essentially the full 1-WL split. Distinct profiles nearly tripled (664 → 1930).
- The **largest class is invariant at 1059 — and 1059 = exactly the zero-profile count.** The
  biggest equivalence class *is* the structurally-isolated symbols; every non-zero orbit shrank,
  the zero block cannot. This is the WL fixpoint boundary made concrete.

## Gate re-run (relative-cut blocking, no normalization — the pinned config)

`bun harness.ts base fork --block relcut --normalize none`:

| metric | depth 1 | depth 2 | gate |
|---|---|---|---|
| **rename_fork_correctness** | 0.863 | **0.987** | ≥0.90 → **CLEARS** ✓ |
| candidate_recall (all pairs) | 0.645 | 0.770 | bounded at 0.773 by zero-profile |
| candidate_recall **nonzero** | 0.836 | **0.998** | ✓ |
| candidate_recall orbit-nonzero | 0.951 | 0.998 | ✓ |
| exact_match | 0.509 | 0.591 | |
| fidelity | 0.925 | 0.990 | ✓ |
| ambiguity_rate (margin<0.02) | 0.792 | 0.740 | still high (intrinsic) |
| elapsed | 20 s | 10 s | (fewer tied candidates → faster) |

Orbit-correctness is scored against orbits derived from the **same** profiles under test, so at
depth 2 the equivalence relation is far **finer** — being "orbit-correct" is a strictly harder
bar — yet correctness *rose* to 0.987 and exact-match rose 0.509 → 0.591. This is genuine
sharpening, not metric inflation: finer orbits + higher score in the same move.

## Honest ceilings (what 2-hop does NOT fix)

- **Zero-profile 22.7% is untouched, as predicted.** 1059 symbols have no incident typed edges
  (in the loaded, `file`-filtered graph) → all-zero vector at any depth. They cap **all-pairs**
  candidate_recall at 0.773; observed 0.770 sits right on that ceiling. They are the entire
  largest equivalence class and are unrecoverable by any name-blind structural method. The gate
  is scored orbit-aware over the *structural* population, where 2-hop reaches 0.998 — so the
  zero-profile floor limits total coverage, not gate pass.
- **60.4% of non-zero symbols still share a 2-hop profile.** One WL round is not the WL fixpoint;
  genuine 2-WL-hard symmetries (e.g. large sibling method sets in identical container contexts)
  remain. They no longer block the gate because relative-cut blocking retains the true twin
  (recall 0.998) and similarity-flooding + orbit-aware scoring resolve within the residual classes
  on this isomorphic fork. A depth-3 round or the richer-edge upstream (MetaCoding-ijo) would
  shrink this further, but is **not required** to pass.
- **ambiguity_rate stays ~0.74** — the intrinsic tie density among structural twins. Consistent
  with the spike's finding that ambiguity is real orbit structure, not extraction-resolvable;
  keep greedy + the margin column.

## Bottom line

2-hop hom-profile seeds **unblock functor discovery**: the gate moves 0.863 → 0.987 (clears 0.90)
and structural candidate recall 0.836 → 0.998, purely from sharper seeds — no algorithm change.
No further lever is needed to pass the §8.3 gate. The residual limits (zero-profile isolates,
2-WL-hard orbits) are understood and bounded, and are addressable upstream (richer edges) rather
than in the matcher. Recommend: build Task 2 with `--depth 2` seeds as the default for
functor-discovery blocking.
