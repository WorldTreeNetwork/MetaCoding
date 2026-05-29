# CTKR bead roadmap

Living index of the full CTKR bead set. Created beads link out to `bd`; deferred-but-tracked beads are preserved here so they don't get forgotten. Update as phases ship.

Source of decisions: [`2026-05-28-ctkr-design-session.md`](./2026-05-28-ctkr-design-session.md). Plan: [`../design/ct-pipeline.md`](../design/ct-pipeline.md).

## Status legend

- ✅ **Created** — exists in `bd` (ID linked).
- 🟡 **Deferred** — intentionally not yet in `bd`; create when the prerequisite phase is closer.
- 🔬 **Research** — long-tail, P4, track only.

---

## Phase 1: CTKR MCP surface (TS) — ✓ **COMPLETE 2026-05-28**

Epic: **MetaCoding-xno** — *all children closed*

| Status | ID | Type | Title | Priority |
|---|---|---|---|---|
| ✓ closed | MetaCoding-xno.1 | decision | Parquet reader: DuckDB-Node | P1 |
| ✓ closed | MetaCoding-xno.2 | feature | `src/ctkr/artifacts.ts` Parquet loader — *16/16 tests* | P1 |
| ✓ closed | MetaCoding-xno.3 | feature | `ctkr.motif_search` MCP tool | P1 |
| ✓ closed | MetaCoding-xno.4 | feature | `ctkr.nearest_symbols` MCP tool — *brute-force, HNSW TODO* | P1 |
| ✓ closed | MetaCoding-xno.5 | feature | `ctkr.pattern_search` MCP tool | P1 |
| ✓ closed | MetaCoding-xno.6 | feature | `ctkr.shape_distance` MCP tool | P2 |
| ✓ closed | MetaCoding-xno.7 | feature | `ctkr.centrality_query` MCP tool | P2 |

## Phase 2a: Hom-profile / Yoneda role identification — *created 2026-05-28*

Epic: **MetaCoding-23q**. **⚠ BLOCKED** on `MetaCoding-e54` (richer edge types) per entropy spike finding.

| Status | ID | Type | Title | Priority |
|---|---|---|---|---|
| ✓ closed | MetaCoding-23q.6 | spike | Hom-profile entropy / edge-type discrimination — *VERDICT: BLOCKED, 2.55 bits entropy, 88.5% top-5 coverage* | P1 |
| ✓ closed | MetaCoding-e54 | feature | Extend extractor: schema + SCIP loader — *PARTIAL: SCIP-only delivered READS_FIELD* | P1 |
| ✓ closed | MetaCoding-3s5 | feature | Tree-sitter WRITES_FIELD/CONSTRUCTS/RETURNS_TYPE — *2.55 → 3.55, BLOCKED* | P1 |
| ✓ closed | MetaCoding-9le | feature | Tree-sitter READS_FIELD + TYPE_OF on fields — *3.55 → 3.65, BLOCKED at 4.0 (gap 0.35)* | P1 |
| 🛑 | MetaCoding-73m | chore | **Run --scip reindex** of 5-repo subset to populate CALLS+REFERENCES (THE remaining bottleneck — 57.5% of symbols collapse on `CONTAINS:in=1.00`, fixable only with SCIP) | P1 |
| ⛔ blocked | MetaCoding-23q.1 | feature | Python: `ctkr hom-profiles` → `hom_profiles.parquet` (blocked-by 73m) | P1 |
| ⛔ blocked | MetaCoding-23q.2 | feature | TS: hom-profile similarity + KNN | P1 |
| ✓ closed | MetaCoding-23q.5 | feature | Eval harness: 9 clusters / 48 ground-truth members, stub client wired | P1 |
| ⛔ blocked | MetaCoding-23q.3 | feature | `ctkr.role_equivalent` MCP tool | P1 |
| ⛔ blocked | MetaCoding-23q.4 | feature | L3 labeler extension: role classes | P2 |

## Cross-cutting — *created 2026-05-28*

| Status | ID | Type | Title | Priority |
|---|---|---|---|---|
| ✓ closed | MetaCoding-ux3 | chore | blake3 migration in `ctkr/` — *124 tests pass* | P1 |
| ✓ closed | MetaCoding-0pz | feature | Codegen: pydantic → JSON Schema → TS types — *types.gen.ts emitted* | P2 |
| ✓ closed | MetaCoding-5wi | spike | Pre-conceptual UX prototype — *contrast pair won; drop `label` field* | P2 |
| ✅ | MetaCoding-gc5 | chore | Code review followups (P2/P3) from 2026-05-28 round — *11 items tracked* | P3 |
| ✓ closed | MetaCoding-qy2 | decision | MCP server location: single process for all tools | P2 |
| ✓ closed | MetaCoding-p4b | decision | Language seam: TS for MCP + Phase 2; Python for L1/L3 | P2 |
| ✓ closed | MetaCoding-ebg | decision | Functor edge-preservation: partial weighted with fidelity metadata | P2 |
| ✓ closed | MetaCoding-at0 | decision | Colimit clustering: Option C (functor-guided community detection) | P2 |
| ✓ closed | MetaCoding-63v | decision | Artifact shape policy: held lightly until algorithmic contact | P3 |

---

## Phase 2b: Functor discovery (partial weighted) — *deferred*

> Create when Phase 2a ships and hom-profiles are flowing.

| Status | Type | Title | Priority |
|---|---|---|---|
| 🟡 | spike | Constraint propagation algorithm for partial weighted functor search | P1 |
| 🟡 | feature | TS: functor search implementation (uses hom-profile seeds) | P1 |
| 🟡 | feature | Emit `functors.parquet` + `functor_edges.parquet` | P1 |
| 🟡 | feature | `ctkr.functor_between(min_coverage?, min_fidelity?)` MCP tool | P1 |

## Phase 2c: Colimit (functor-guided community detection) — *deferred*

> Create when Phase 2b ships and we have a functor edge stream.

| Status | Type | Title | Priority |
|---|---|---|---|
| 🟡 | spike | Louvain implementation choice in TS (port vs. existing lib) | P1 |
| 🟡 | feature | Meta-graph build + weighted Louvain community detection | P1 |
| 🟡 | feature | Edge lifting + repo-support counting | P1 |
| 🟡 | feature | Emit `colimit.parquet` + `colimit_morphisms.parquet` | P1 |
| 🟡 | feature | `ctkr.essence(scope?, min_repo_support?, min_persistence?)` MCP tool | P1 |

## Phase 2d: Operad recovery — *deferred (design only first)*

| Status | Type | Title | Priority |
|---|---|---|---|
| 🟡 | spike | Operad recovery algorithm + artifact shape design pass | P2 |
| 🟡 | feature | TS: composition-pattern mining from call paths | P2 |
| 🟡 | feature | Emit `operads.parquet` | P2 |
| 🟡 | feature | `ctkr.composition_rules(scope?, min_support?)` MCP tool | P2 |

## Phase 3: Essence extraction — *deferred*

| Status | Type | Title | Priority |
|---|---|---|---|
| 🟡 | feature | Extend L3 labeler to colimit objects | P2 |
| 🟡 | feature | Extend L3 labeler to colimit morphisms | P2 |
| 🟡 | feature | Extend L3 labeler to operad operations | P3 |
| 🟡 | feature | `ctkr.unnamed_patterns` MCP tool for pre-conceptual surfacing | P2 |
| 🟡 | spike | UX design for pre-conceptual pattern presentation | P2 |

## Phase 4: Infrastructure — *deferred (4c provenance can come earlier)*

| Status | Type | Title | Priority |
|---|---|---|---|
| 🟡 | feature | 4a: semantic embedding tier (TS, sentence-transformer or API) | P2 |
| 🟡 | feature | 4a: diff embedding tier (port from dreamseed) | P3 |
| 🟡 | feature | 4a: unified KNN interface | P2 |
| 🟡 | feature | 4b: file-watch + partial recompute | P2 (blocked-by Phase 1) |
| 🟡 | feature | 4c: provenance metadata on all rows + writer updates + migration | P2 |
| 🟡 | feature | 4d: worktree-aware reads — extend `{repo, branch, repo_commit_sha}` → `{…, worktree}` | P3 |

---

## Research / v2 — *track only, P4*

These are the directions opened in the design session that are worth not forgetting. None block anything.

| Status | Type | Title | Notes |
|---|---|---|---|
| 🔬 | spike | Persistent clustering of role classes (fidelity-threshold sweep) | Detect persistent communities via TDA |
| 🔬 | spike | Categorical pushout — true colimit construction as v2 of Phase 2c | Catlab.jl-style, port to TS |
| 🔬 | spike | Persistent functors over git history filtration | Zigzag persistence / Reeb graphs |
| 🔬 | spike | L2/L3 closed refinement loop convergence | Fixed-point analysis |
| 🔬 | spike | 2-category structure: natural transformations between functors | The 2-cells layer |
| 🔬 | spike | Stochastic / Bayesian CTKR — fidelity-as-probability throughout | Stochastic block model over meta-graph; MCMC; posterior distributions over role classes |

---

## How to use this file

- When the next phase becomes the focus, move its rows from 🟡 to ✅ as you create them in `bd`.
- When you create a bead, append its `MetaCoding-xxx` ID inline.
- When research items get picked up, promote them out of the 🔬 section.
- If a deferred item gets cut, mark it ❌ with a one-line reason rather than deleting — preserves the audit trail.
