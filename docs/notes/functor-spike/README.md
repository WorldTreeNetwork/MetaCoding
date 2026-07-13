# Task 1 Spike — Functor discovery: measure the failure modes first (§8.3)

**2026-07-13 · GATE FAILS (honestly) · throwaway harness, NOT production code.**

Implements Steps 0–4 of [`ct-functor-discovery.md`](../../design/ct-functor-discovery.md) §2.2
(hom-profile KNN blocking → similarity-flooding propagation → greedy extraction → fidelity
scoring) and measures the three numbers the §8.3 review demands, on a real scip-indexed repo
and a mechanical rename fork.

- `harness.ts` — Bun/TS harness (Steps 0–4 + all measurements + per-component Hungarian).
- `prep.py` — joins `hom_profiles.parquet` + `export/nodes.jsonl` → `profiles.jsonl`.
- Run: index base+fork with `--scip`, `metacoding export`, `ctkr hom-profiles --kinds-filter file`,
  `prep.py`, then `bun harness.ts <base-datadir> <fork-datadir> [--block relcut --normalize none ...]`.

## Corpus

Base = MetaCoding self (`--scip`, `repo=base`, 4129 symbols / 5625 edges). Fork = same working
snapshot with `src/`→`lib/` renamed (48 imports rewritten) + `repo=fork` (identical counts).
`symbol_id = sha256(lang|repo|qn)` ⇒ every id and qualified_name differs while structure is
byte-identical → clean isomorphism control. The search is name-blind (consumes only
`profile_vec` + typed edges + `symbol_id`), so this is equivalent to a full α-rename and gives
an exact ground-truth bijection with zero structural drift. Twin profiles are byte-identical
(extractor name-blindness confirmed empirically).

## Headline numbers

| metric | value | gate |
|---|---|---|
| candidate_recall — fixed-k=10 (naive default) | 0.41 (nonzero) / 0.32 (all) | ✗ |
| candidate_recall — relative-cut, orbit-aware, structural | **0.957** | ✓ |
| rename_fork_correctness — best config (relcut, no-norm) | **0.86** | ✗ (<0.90) |
| fidelity — best config | 0.92 | ✓ |
| ambiguity_rate (`margin < 0.02`) | 0.80–0.89 | huge |

**gate_pass = FALSE.** Blocking recall is *recoverable* (relative-cut retains a correct-orbit
candidate for 95.7% of structural symbols); correctness plateaus at ~0.86 and cannot reach 0.90.

## Root cause — intrinsic structural symmetry, not the algorithm

- **22.5%** of symbols have a **zero profile vector** (no internal typed edges) — structurally
  isolated, unrecoverable by any name-blind method; caps all-pairs recall at ~0.775.
- Among structural symbols, **69.9% live in an identical-profile block > k_seed=10** (block
  sizes 561, 499, 288, 148…). Fixed small k truncates the tied block → recall 0.41. Exactly the
  §2.2 warning; the fix is relative-cut blocking.
- After one WL round, **68.9% sit in a non-trivial automorphism orbit** (largest = 834). The
  name-blind **exact-match ceiling is ~31%** (observed 0.50). Orbit-aware correctness tops out
  at 0.86 because injective extraction must permute within huge orbits and ~14% land on a
  profile-equal symbol in a *different* orbit.

**Matches the design's contingency (§6 Task 1 / §8.3.1): correctness is seed-bound. Fix is
upstream (MetaCoding-ijo richer edges), not algorithmic.** Build Task 2 against the (sound)
hardened algorithm; the eval gate will not pass until seeds sharpen. Re-run when ijo lands.

## Decisions pinned

- **Extraction: GREEDY, not Hungarian.** Per-component exact max-weight matching gives identical
  correctness (0.721 vs 0.721) and ≤0.006 weight gap despite ~0.85 ambiguity — the ambiguity is
  intrinsic (true orbits), not extraction-resolvable. Keep greedy + the **`margin` column**.
  Revises the design's "ambiguity>10% ⇒ LAP" rule: LAP does not help here.
- **Normalization: default OFF for high-signal pairs.** Sinkhorn *degrades* the rename-fork
  control (corr 0.68 / fid 0.75) vs no-norm (corr 0.86 / fid 0.92) — it dilutes perfect seeds.
  Keep it for genuinely-BORDERLINE cross-repo pairs (hub control); make it adaptive, and run the
  rename-fork/null-model controls with it OFF. Revises §2.2 hardening 1 to "conditional."
- **Propagation earns its keep:** seed-only corr 0.45 → 8 rounds 0.86 (no-norm); fidelity
  0.51 → 0.92. Saturation Spearman(σ,σ0) = −0.13 (not the feared ~1.0) — hardenings prevent
  saturation. It just can't overcome the symmetry.
- **Edge access:** `metacoding export` JSONL lane sufficed; no new Python export artifact needed.

## Pinned defaults (Task 2)

```
alpha=0.3  k_seed=10  rounds=8  beta=0.25  tau_seed=0.30
blocking = relative-cut (delta_rel=0.02, cap=400)   # NOT fixed top-k — this is the recall fix
normalize = off (adaptive-on for BORDERLINE cross-repo)
extraction = greedy + margin column                  # LAP does not help
delta_amb = 0.02
```

## Other confirmed properties

- **Determinism:** byte-identical output across repeated runs (equal md5 of the result blob).
- **Margin is honest (§5.7):** correct pairs mean-margin **+0.04**, wrong **−0.01**;
  Spearman(margin, correct) ≈ **+0.40**. Low margin flags the coin-flips.
- **Graceful degradation (§5.7):** collapsing q∈{10,20,30}% of seeds onto neighbors moves
  correctness only 0.862→0.854; margin signal stays honest. The map is structure-carried, so
  the low correctness is a *symmetry* limit, not a *seed-noise* limit.
- **Cost:** fixed-k ~4 s; relative-cut (cap 400) ~20–28 s for this ~4.5k-symbol pair (2× the
  §6 reference size) — within the < 60 s / ~2k-symbol budget.
