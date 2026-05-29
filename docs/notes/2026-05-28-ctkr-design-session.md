# 2026-05-28 — CTKR design session

Working notes capturing the conceptual moves in the session that established the CTKR phased plan. Companion to [`../VISION.md`](../VISION.md) and [`../design/ct-pipeline.md`](../design/ct-pipeline.md) — those are the polished outputs; this is the reasoning underneath them.

## The setup

A user of the package described "CTKR upgrades" — 11 concrete requests framed in dreamseed/bench/iteration terms (typed Bench objects, Iteration rows, Reflection rows, EthosVersion, Proposer, cross-bench edges, functorial mapping bench→iteration, MCP tools for kin-* queries, incremental indexing, worktree-awareness). The first instinct was: this is a different product on top of MetaCoding. The correction came from going back to MetaCoding's actual purpose: *truly grok code, programs, the flows and shapes of what makes computers do things — use CT to extract the essence of knowledge, including knowledge that can't be put into words.*

That reframing flipped the question. The 11 requests weren't dreamseed-specific — they were *one application* of a deeper capability. The real question: of those 11, which generalize to the categorical-grokking vision, and which are properly dreamseed-loop state?

The split that emerged:
- **Core to CTKR**: multi-tier embeddings, cross-category edge schema, provenance, functorial mapping (generalized), MCP query interface, incremental maintenance, worktree-aware reads.
- **Dreamseed-loop state**: typed Iterations, typed Reflections, Capability registry (Proposer/Axis), bench-specific identity fields. These belong in Orchestrators, optionally indexed *into* MetaCoding as another corpus member.

Nothing belongs in Dreamball proper. Dreamball is the container protocol; CTKR discoveries flow *into* Memory Palace inscriptions but don't change the protocol.

## The four-phase ladder

What started as "expose MCP tools" → "build Layer 2 categorical machinery" → "essence extraction" → "infrastructure" condensed into:

- **Phase 1 — Expose.** Typed MCP surface over existing L1 artifacts (motifs, embeddings, patterns, centrality, shape). No new math; immediate utility.
- **Phase 2 — Construct.** Layer 2 categorical machinery proper. Four sub-phases, in dependency order: hom-profiles (2a), functor discovery (2b), colimits (2c), operads (2d).
- **Phase 3 — Name.** L2 outputs labeled by L3 LLM enrichment. Three flavors of essence emerge: confirmation of known patterns, naming of unnamed ones, pre-conceptual surfacing of patterns that resist language.
- **Phase 4 — Sustain.** Multi-tier embeddings with unified KNN, incremental maintenance, provenance, worktree-aware reads. Cross-cutting, mostly independent of Phase 2/3.

Phase 1 is the highest-leverage move because the artifacts already exist and Phase 2 needs an MCP surface anyway. Phase 2a is the entry point to real CT — tractable, builds on existing graph data, validates the approach before tackling functors and colimits.

## Terminology correction: "faithful" / "lax" → "strict" / "partial"

First draft said the functor-discovery step had a hyperparameter: "faithful (edge-preservation strict) vs lax (allow some edges to violate, weighted by faithfulness)." This conflated terms.

In strict CT:
- **Faithful** functor = the action on hom-sets is injective (different morphisms stay different under F).
- **Full** functor = hom-set-surjective (every morphism in target hits something).
- **Lax functor** / pseudofunctor = composition laws hold up to 2-cells rather than on the nose.

None of those is what we mean. What we actually compute is closer to **graph homomorphism with edge-preservation fidelity score** — we don't promise the categorical composition law holds, we just count what fraction of edges in the source subcategory have witness edges in the target. We call the result a "functor" when fidelity = 1.0 and an "approximate functor" otherwise.

Doc correction landed in [`ct-pipeline.md` §2b](../design/ct-pipeline.md#2b--functor-discovery-cross-repo-structural-maps).

## The shift to partial weighted functors

Initial recommendation was "strict v1, lax v2" — argued that strict admits a cleaner algorithm and Phase 2c (colimit) is much cleaner over real functors. User pushed back: *"Category theory is a beautiful theory. And when we apply it to real-life messy things I don't think it's hardly ever going to be perfect. But I would like to be able to calculate some percentage or threshold and embed that in the data."*

That changed the design. The fidelity score becomes **edge metadata on the functor edges themselves**, not a binary accept/reject. Callers filter at query time: `min_fidelity=1.0` returns pure functors; `min_fidelity=0.8` returns robust approximations; `min_fidelity=0.5` returns exploratory ones.

The discipline: be honest about what's being computed (graph homomorphism with fidelity), expose the fidelity, let the consumer choose strictness. This matches the broader "deterministic before probabilistic" principle of MetaCoding but adapts it: deterministic *structure*, probabilistic *interpretation*.

## The user's persistent-clustering derivation (the surprise of the session)

User asked: *"is the hom-profile-space clustering really a superset of the transitive functors? feels like a group of defined transitive functors would act like a hypothesis for a particular scenario/set, and then we'd see if any of the not-quite-matching (if filter is < 100%) functors breaks in that scenario..."*

The answer turned out to be: yes, and they had just re-derived **persistent clustering** (a real area in TDA / multi-resolution analysis) from first principles. The clean form:

1. The functor-fidelity graph G has weighted edges (weight = fidelity ∈ [0,1]).
2. As you sweep the threshold from 1.0 down to 0.0, the equivalence classes grow: at 1.0 you have many small strict classes, at 0.0 everything connects.
3. **Persistent** classes (stable across a wide threshold band) are robust role classes.
4. **Ephemeral** classes (only appear in a narrow band) are noise or boundary cases.
5. The persistence diagram of class merges *is itself* the answer — we don't have to pick the threshold up front.

This is the same idea as persistent homology (which we already use for repo shape signatures), applied to functor-induced equivalence instead of topological filtration. Beautiful symmetry — TDA shows up at two different layers of CTKR.

What this opens: **CTKR is naturally amenable to stochastic / probabilistic interpretation.** Concretely:
- Functor edges carry fidelity ∈ [0,1] — read as P(this is a true mapping).
- Role classes are *distributions* over symbols, not hard sets.
- Communities from weighted Louvain are *modes* in a probabilistic landscape.
- A stochastic block model over the meta-graph could give us posterior distributions over role-class assignments.
- MCMC sampling of communities could give us uncertainty quantification on every essence claim.

This is a research direction, not a v1 requirement — but it's the through-line that connects multi-resolution clustering, persistent homology, and Bayesian graphical models. Every CTKR artifact could carry not just a value but a distribution or confidence interval. The honest way to apply CT to messy real-life data.

## Colimit construction: Option C, weighted

For Phase 2c (clustering role-equivalent symbols into colimit objects), four options surfaced:

- **A. Transitive closure of pairwise functor maps.** Pure but catastrophically noise-sensitive — one bad functor edge collapses two big classes.
- **B. Hom-profile-space clustering, ignore the functors.** Fast but throws away Phase 2b's structural evidence.
- **C. Functor-guided graph clustering (community detection on the functor meta-graph).** Uses functor evidence as weighted input; community detection handles noise gracefully.
- **D. Categorical pushout** (Catlab.jl-style). Theoretically pure but requires exact functors; implementing it ourselves without Julia is real work.

Recommendation landed on **C**. With weighted edges, Louvain modularity naturally incorporates fidelity, and the persistent-clustering observation above means we don't need to commit to a threshold. Option D stays on the books as v2 once the approximate version proves signal — tracked in [`ct-pipeline.md` § Open theoretic questions](../design/ct-pipeline.md#open-theoretic-questions).

## Language seam

User asked about porting Python → Rust eventually. Audit of `ctkr/` dependencies:

- **Load-bearing Python**: `gudhi` (persistent homology, no comparable Rust/TS equivalent) and `gensim` (Word2Vec, no comparable equivalent).
- **Easy to port**: `networkx` → petgraph; `polars` already Rust-cored; `pydantic` → serde; `hnswlib` → Rust crates; `anthropic`/`openai` → TS SDKs.

That gives a natural seam:
- **TS owns the MCP surface (Phase 1) and the Layer 2 categorical machinery (Phase 2).**
- **Python owns Layer 1 mining (`embed`, `mine-motifs`, `shape`, `centrality`) and Layer 3 LLM labeling.** Gudhi keeps Python in the stack indefinitely; that's fine.

The two halves communicate through the Parquet artifact layer — Python writes, TS reads. DuckDB-Node is the recommended Parquet reader on the TS side (native, fast, SQL queries over Parquet directly).

Decision recorded in [`ct-pipeline.md` § Conventions](../design/ct-pipeline.md#conventions).

## Single MCP process

CTKR tools live in the same MCP server as the existing graph tools (`graph_neighbors`, `code_search`, etc.). No isolation reason to split. New TS modules: `src/ctkr/` (algorithms) and `src/mcp/ctkr-tools.ts` (tool definitions). Registered alongside the existing tools in `src/mcp/tools.ts`.

## Hashing: blake3

Existing CTKR Python code uses blake2b (in `label_motifs.py` for `pattern_id`, in `llm.py` for cache keys). Migrating to blake3 to match the rest of the WorldTree stack (dreamseed already uses blake3). One isolated chore.

## What this session preserved

- The phased plan (Phase 1 → Phase 4) is now in [`ct-pipeline.md`](../design/ct-pipeline.md).
- The strategic framing — what grokking means, what CTKR is for — is in [`VISION.md`](../VISION.md).
- The bead-set proposal (full, including the deferred Phases 2b–4) is in [`ctkr-bead-roadmap.md`](./ctkr-bead-roadmap.md), so the deferred work doesn't get forgotten.
- This file: the reasoning and the moments where the design changed.

## What still feels open

- The categorical pushout v2 (true colimit) — beautiful but real work. Track and revisit after Option C ships.
- Persistent-clustering as an MCP tool (`ctkr.essence_persistence`) — high value, low priority. Tracked.
- The stochastic / Bayesian generalization (sampled communities, posterior distributions over role classes). This is the deepest opening from the session. Worth a focused research note when there's time.

## Late-session execution findings (2026-05-28 evening)

After the design landed, ralph/ultrawork rolled the immediate beads in parallel. Three findings worth preserving:

### 1. Phase 1 is live

The MCP surface (motif_search, nearest_symbols, pattern_search, shape_distance, centrality_query) ships in `src/mcp/ctkr-tools.ts`, backed by `src/ctkr/artifacts.ts` (DuckDB-Node Parquet loader). 21 + 16 bun tests passing on the Orchestrators corpus. DuckDB-Node works fine under Bun on the first try.

### 2. The entropy spike paid off — current edge types do NOT discriminate roles

Running `ctkr entropy-check` on the 553k-symbol Orchestrators corpus revealed:

- Unique hom-profiles: **913 / 552,954 symbols** (0.17%)
- Shannon entropy: **2.55 bits** (threshold 4.0)
- Dominant top-5 coverage: **88.5%** — five profiles cover almost everything
- Per-kind entropy: `field` 1.1 bits (28 profiles for 152k fields — catastrophic), `function` 1.7, `method` 2.6, `class` 3.9, `interface` 3.7

**Why**: the current 10 edge types are mostly *structural containment* (CONTAINS, REFERENCES). They describe *where* a symbol lives, not *what it does*. A field, a parameter, and an enum variant all look like `CONTAINS:in=1.0` and are indistinguishable.

This is exactly the failure mode the spike was designed to catch. Without it we'd have built Phase 2a, gotten meaningless clusters, and spent weeks trying to fix the wrong layer.

The fix: extend the extractor lane with behavior-capturing edge types — WRITES_FIELD (the highest-leverage single addition), READS_FIELD, RETURNS_TYPE, CONSTRUCTS, RAISES, DECORATES.

### 3. SCIP can't deliver write-access edges in practice

First attempt to extend the lane (`MetaCoding-e54`) took the SCIP-side path: read SCIP occurrences, filter by `symbol_roles` flags, emit edges. The schema additions landed; tests passed; SCIP loader updated.

Result: `READS_FIELD` got 436 edges in crewAI; `WRITES_FIELD`, `RETURNS_TYPE`, `CONSTRUCTS` got **zero**. SCIP-typescript and SCIP-python don't emit `WriteAccess` flags or `is_type_definition` for return types in practice. The schema was right; the source data wasn't there.

Entropy moved 2.55 → 2.65 — still BLOCKED.

The actual fix is a per-language tree-sitter pass (`MetaCoding-3s5`) — pattern-match `this.field = X`, `self.attr = X`, `new ClassName(...)`, return-type annotations directly from the AST. SCIP gives us resolved symbols; tree-sitter gives us behavioral semantics. Both lanes are needed.

### 4. The pre-conceptual UX prototype produced a real design rule

Prototype spike (`MetaCoding-5wi`) tested three formats for presenting unnamed patterns. Key finding: **don't include a `label` field in the output**. A label slot creates naming pressure that forecloses the pre-conceptual state. Replace with `labeling_pressure` metadata — what words *tried* to form, without committing to any. Captured in [`../design/ct-pipeline.md` §Phase 3 — Pre-conceptual UX findings](../design/ct-pipeline.md#pre-conceptual-ux--findings-from-the-2026-05-28-prototype).

The contrast-pair format (one strong exemplar + one near-miss) was the clearest perception trigger. Side-by-side relied too heavily on annotation tables. Structural skeleton evoked naming pressure prematurely.

## What still feels open

- Pre-conceptual surfacing in Phase 3 — the prototype found the format (contrast pair), but the *selection problem* (which pattern to present?) and the *delivery surface* (how does this appear in an MCP response — text? rich object? both?) are still open.
- The categorical pushout v2 (true colimit) — beautiful but real work. Track and revisit after Option C ships.
- Persistent-clustering as an MCP tool (`ctkr.essence_persistence`) — high value, low priority. Tracked.
- The stochastic / Bayesian generalization. This is the deepest opening from the session. Worth a focused research note when there's time.

## Late addendum — entropy as a dial

After the 9le entropy plateau at 3.65 bits (BLOCKED at the 4.0 capability gate), the user reframed the gate question: could Shannon entropy itself be a dial — similar to a std-dev width — rather than a hard threshold?

The answer turned out to be yes, and it generalizes the persistent-clustering observation. Captured fully in [`entropy-as-dial.md`](./entropy-as-dial.md). Key points:

- Entropy is a measurement, not a parameter — but the *granularity* of profile equality, the *kinds filter*, and the *edge-alphabet subset* are all parameters that produce different entropies.
- The std-dev analogy is exact: each dial slides along a **rate-distortion curve** (compression vs. fidelity).
- The principled move is **persistent clustering** across dial settings — track which role-equivalence pairs are robust to dial choice vs. resolution-dependent.
- The 4.0 threshold is more honestly read as a **capability check** ("the alphabet needs to *be able to* reach useful entropies") rather than a target.
- Several Phase 2+ MCP tool signatures should expose `granularity?` and `kinds_filter?` parameters explicitly. Hom-profile artifacts (`MetaCoding-23q.1`) should be stored at maximal precision; quantization happens at query time.
