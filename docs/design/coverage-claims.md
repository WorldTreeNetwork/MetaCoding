# Coverage claims: recording what was looked at, not only what was found

**Status:** proposed, 2026-08-06. Amends [graph-as-cache.md](./graph-as-cache.md).
**Origin:** Duke — *"is there anything that's asking for a redesign?"* → fresh-architect design.
**Beads:** `9jt` (P0), `ev9`, `ugm`, `0sd`, `hy6.16`, `5fi`, `0mu`, `226`, `egx`.

## Three measured findings, in order of how much they change the plan

### 1. Incremental re-index destroys cross-file edges — shipped, today (`9jt`, P0)

Not a risk of a future design. A present defect, reproduced independently at `8b78220`:

| | relational edges | status |
|---|---|---|
| fresh index | **14** | HEALTHY |
| edit `b.ts` **method body only**, re-index same dir | **12** | HEALTHY |
| fresh index of the *identical* tree | **14** | HEALTHY |

Lost and never recovered: `RETURNS_TYPE a.ts::Child::makeOne → b.ts::Widget`, and one lane's copy of `CONSTRUCTS ::makeOne → Widget`. **The edited file was `b.ts`; the destroyed edges are owned by `a.ts`, which was never touched.**

Everything that survived — `IMPLEMENTS`, `REFERENCES`, `CONTAINS`, `CONSTRUCTS`-to-`Base` — has a target id computed *syntactically from the name*. Only the **deferred, resolver-dependent** edges die. It does not self-heal: re-indexing the source file afterwards does not restore them.

Mechanism, at the lines:
- `store/index.ts:377-385` — `deleteFileData`'s `DETACH DELETE` destroys edges **owned by other units** that point into the changed one.
- `extractor/walker.ts:242-250` — those units are then skipped, returning *before* resolver population at `:289-298`.
- `extractor/walker.ts:315-352` — so when a source file is re-walked, its callee is absent from `SymbolResolver` and `flushCandidates` **drops the candidate silently**.

Every unit must be present in the resolver for any unit's cross-file edges to resolve; the skip guarantees they are not.

**No gate sees it.** `measureGraphFreshness` passes — every `ast_hash` matches disk. The graph is per-file *current* and cross-file *wrong*. Both stores above report HEALTHY.

Note which lane is sound: **SCIP self-heals because it re-runs whole-project every time.** The whole-project lanes are accidentally correct under incremental re-index; the incremental lane is not. That is the cleanest available argument for the sealed model.

### 2. The rebuild cost is ~99% write overhead

| operation | measured |
|---|---|
| parse + extract 92 files (2,744 symbols, 6,815 candidates) | **269 ms** |
| resolve every cross-file candidate | **2 ms** |
| the same content through `Store` | **76,020 ms** |
| `upsertSymbol` × 1000 | 13,773 ms (13.8 ms each) |
| same MERGE, one reused prepared statement | 6,383 ms (6.4 ms each) |
| **`COPY` 30,000 symbols + 45,000 edges** | **218 ms** |

Layer 2's rebuild is not 90 seconds of work. It is ~1 second of work behind a 400× write penalty. `Store.query` also re-prepares on every parameterized call (`store/index.ts:234-239`) — a 2.2× penalty for free.

**The correctness and performance arguments converge.** Mutation in place is what forces `MERGE`; `MERGE` is what costs 400×. Immutable sealed entries are precisely the regime where the bulk path is available. That convergence is the signal `iteration-methodology.md` says to look for.

### 3. Merkle per-unit sealing: rejected on measurement

It caches *derivation*, and derivation is 271 ms for the whole repo. The cost is *materialization*, which Merkle does not address.

The cross-unit edge answer is worth keeping anyway, because it explains finding 1. **Every edge is owned by exactly one unit — the one containing its source.** Structural in both lanes (`walker.ts:292-296`; `loader.ts:314-323`, where a caller is always in the same document). What is cross-unit is only *target resolution*. So the correct decomposition is three levels: **A** per-unit facts + unresolved candidates; **S** the resolution surface (changes only when a *declaration* changes, not a body); **C** resolved edges keyed on `(A_key, S_digest)`.

That names the bug exactly: **today's walker does A-level skipping while pretending S never changed, and mutates C in place.** Keep the decomposition on file for a corpus 100× larger. Do not build it now.

## Coverage claims

Every fact in the graph is positive. **Absence is never recorded**, so an empty result is irreducibly ambiguous: *there are no calls* or *no lane could see calls here*. Every failure of the last four rounds is that ambiguity in a different coat — `hy6.16` at 41 rows, `ugm` refusing a relationship-free package from a count, `5fi` guessing whether the graph is about this tree, and `graph-as-cache.md`'s `capabilities` block patching over it per-entry.

**A region is the set of files the key was computed over — nothing else.** `5fi`'s entire defect was a numerator and denominator over different sets; the fix is that there is only one set. The manifest stores the canonical sorted input file list once (already hashed into the key); a claim references it by digest plus a bitmap over its indices. 812 files → **102 bytes**.

```
{ lane, toolchain_digest,
  region:     <bitmap over manifest.files>,
  fact_kinds: [...],                       // from the static capability table
  outcome:    complete | partial | failed(reason),
  attempted:  <bitmap> }                   // attempted \ region = the uncovered set
```

### Derived, never declared — and this is the whole point

A *declared* claim is the same blindness one level up: the lane vouching for its own completeness, which is the move that produced three refutations. Nothing forces that. For every lane here the region is recoverable from the artifact:

- **SCIP** — the set of `doc.relative_path` values that **resolve into the manifest file list**. An intersection computed from the artifact. This is the structural fix for `5fi`: 40 documents at `node_modules/dep/vN.ts` intersect the census at ∅, so the claim is empty and no ratio exists to be gamed.
- **tree-sitter** — the set of files `walkFs` actually parsed without error.

The only declared thing left is the **static capability table**: which fact kinds a lane can emit *at all*. Small, versioned, fixture-testable. Confirmed independently: `CALLS` and `REFERENCES` appear nowhere in `src/extractor/`, only in `src/scip/loader.ts:355-356, 374, 389`.

### Absence gets a truth value, and no count is ever consulted

The refusal predicate stops being `count == 0` and becomes `claim ∌ (file, kind)`:

| condition | answer |
|---|---|
| a `complete` claim covers `sym.file` for `CALLS`, zero rows | `{ok:true, rows:[]}` — **a real negative, answered authoritatively** |
| no claim covers `sym.file` for `CALLS` | `{ok:false, error:"UNCOVERED", lane_that_would_cover, cost}` |

`NO_RELATIONAL_EDGES` (`fitness.ts:685-687`) dissolves structurally, closing `ugm`: the relationship-free fixture has a *complete* CALLS claim over all six files and honestly holds zero CALLS edges. Zero inside a complete claim is a fact about the code. The proxy is gone because nothing counts anything.

Partial coverage needs no special case: `outcome: partial` just means `region ⊂ attempted`. The `0sd` fosite shape becomes *representable* rather than needing an exit code to carry it.

## The four questions

**1. Claims replace fidelity-in-the-key.** `capabilities: {php:["CALLS",…]}` is exactly `∃region. claim(lane, region, CALLS)` — the claim set with **the region existentially quantified away**, and the region is precisely what `hy6.16` and `5fi` both needed. A coarse block answers "does this entry have CALLS for php?" with *yes* when SCIP covered 400 of 812 files, and `hy6.16` recurs at corpus scale with the new design's blessing. So the key's fidelity component becomes `H(sorted claim digests)`; `capabilities` survives as a derived human view, never consulted by a gate. `files:{inTree,inGraph}` is deleted — it is the region's cardinality, and a second representation is how numerator and denominator drifted apart the first time.

**2. Can a claim be trusted more than the recipe that wrote it? Plainly: not in the limit.**
- *Derivation* is the difference, and it is available for every lane here (above). The lane never asserts its own coverage.
- *Cross-check*: both lanes already write the same symbol ids, so the tree-sitter ∩ SCIP overlap exists on every SCIP build. Comparing their `EXTENDS`/`IMPLEMENTS` there costs one set-difference over in-memory data. **Record as an observation, never as a gate** — a threshold on it would be refuted like every other threshold.
- *What remains*: even a derived region rests on *"the lane, having produced a document for f, examined all of f."* Not checkable. **So claims move the blindness from "which files" — invisible today, cost `hy6.16`/`5fi`/`ugm` — to "how thoroughly within a file," still invisible.** A real, bounded reduction. Not an elimination, and anyone describing it as one is overselling.

**3. SCIP-by-default: affordable at commit granularity, not in the editor loop.** SCIP is inherently whole-project — `src/scip/run.ts` has no subset path for any indexer, and `RunScipOpts` has no file list. But once the write path is fixed, layer 2 drops to ~1 s, so the `.scip` artifact cache is the only thing between a user and SCIP-always — and it already works (the 2026-08-04 farmOS rebuild reused the 2026-07-17 artifact). Cost becomes one SCIP run per *commit that changes code*. Caveat: an observed scip-typescript OOM (exit 134, 4 GB heap) means "always on" must survive SCIP *failing*, not just being slow — which claims handle well: a failed lane yields an empty claim, lowers the key, and the build still seals.

**4. The analysis layer — the payoff.** Today `graph_callers` hard-wires `["CALLS","REFERENCES"]` (`tools.ts:148-155`) and over a tree-sitter-only HEALTHY graph returns `{ok:true, rows:[]}`. Worse, `ctkr/hom_profiles.py:84-89` makes `(CALLS, REFERENCES) × (in, out)` dimensions 0–3 of every role vector: without SCIP those four coordinates are identically zero for every symbol — the vector does not shrink, it **degenerates** — and KNN returns confident cosine neighbours. *That is `hy6.16`, still live.*

Under claims: a covered file answers authoritatively (including a genuine `[]`); an uncovered one refuses by name and cost. **The mixed case — SCIP covered 400 of 812 — has no representation at all today**; both cases return byte-identical `[]`. And `hom_profiles` computes dimensions only where the kind is claimed complete, recording per-dimension coverage, so a dead dimension is a declared zero-*width* dimension rather than a zero-*valued* one. Role-equivalence compares profiles restricted to jointly-covered dimensions.

**That single rule — compare only where both are covered — replaces a corner case per (lane × language × `--scip` on/off).** It also deletes `ctkr/spec_cards.py:1201-1202`, where `or bool(alphabet)` stamps `indexed_with_scip: true` on a pure tree-sitter corpus: the one honesty flag about SCIP lies in exactly the case it exists to catch.

## Order of work

0. **Bulk write path + delete in-place mutation.** These are one change: building into a fresh tmp dir with `COPY` *is* sealing. Fixes `9jt`.
1. Sealed whole-graph entries per `graph-as-cache.md`, largely unmodified.
2. Coverage claims as the fidelity component of the layer-2 key.
3. Analysis layer consumes claims.

## What changes in graph-as-cache.md

**Survives:** three layers with different miss policies; layer-1 keys on image digest; seal by atomic rename + reader-recomputed key; recursion over input *keys* (closes `19g` by construction); refusals naming cost; **unconditional capability refusal** (finding 1 supports this directly — the dangerous state is a graph returning plausible data while missing 14% of its edges); the dissolve list; layer 3 as a ledger with flag-and-keep; and *"a failed lane lowers the key rather than failing the build."*

**Changes:** `capabilities` → claim set; `files:{inTree,inGraph}` deleted; `achieved_fidelity_profile` → `H(sorted claim digests)`. **Every cost-driven decision leaning on "~90 s / 30k symbols" must be re-derived — it is off by ~400×.** Most importantly the `watch`/scratch concession largely dissolves: at ~200 ms a watch can simply re-seal, and the mutable unkeyed scratch entry was that design's own weakest joint. The seal-determinism experiment should be re-run *after* the write path changes — the prior byte-difference was most likely produced by the per-statement mutation path itself.

**Dies:** per-unit Merkle sealing, and the framing that layer 2 is expensive.

## Cost

2–6 claim rows per entry; one bitmap each (812 files → 102 bytes); under 100 KB at farmOS scale, in `MANIFEST.json` not the graph. Query cost: load once per store open into `Map<fact_kind, Set<file_index>>`, then one hash lookup. **The one real API cost:** a query must know the *file* of the symbol it answers about — `graph_callers` does not fetch it today; it becomes `RETURN b.file` in the same Cypher. Plan it, don't discover it.

## What this handles worse

1. **More machinery than a static `capabilities` table.** Region bugs are *quiet*: a wrong bitmap either over-refuses (visible) or makes an uncovered file look covered — **`hy6.16` with more confidence than today**.
2. **Over-refusal in the mixed case**, and annoyance is what gets gates disabled. Expect complaints about farmOS specifically.
3. **Cache hit rate drops** — a finer key means two builds differing only in which files a flaky SCIP run covered produce different keys. Affordable at a 1 s rebuild; would not have been at 90 s. Fixing the cost model is *load-bearing* for the correctness design.
4. **Rigor about "which files" may inflate confidence about the intra-file blindness that remains.**
5. **Rejecting Merkle leaves `watch` with only "re-seal in ~1 s"** — believed, but only the `COPY` component was measured. If ladybug open/close or the FTS rebuild dominates, `watch` gets *worse* than today's 62 ms warm path — and that warm path is the one finding 1 proves unsound, so there would be no good option left. **Measure before deleting `watch`'s incremental path.**

## Alternatives rejected

- **Per-unit Merkle sealing** — on measurement; caches the free part.
- **Keep incremental walking + a reverse-dependency index** (invalidate units whose candidates resolved into the changed unit). The *minimal* correct fix to `9jt`, cheaper to implement than sealing. Rejected because it is another door-guard on a shared mutable resource — the pattern three refutation rounds diagnosed — and full rebuild at ~1 s makes it pointless. Recorded so the weighing is visible.
- **Thresholding a coverage ratio** — claims replace it with a set; there is no number to tune, which is the point.
- **Making claims a gate on write** (refuse to seal below X coverage) — that is `NO_RELATIONAL_EDGES` again, a count as a proxy. A lowered claim set lowers the key and never fails the build.

## How would we fake this design?

1. **The sharpest attack, and it is `5fi` in a better disguise.** The region is derived from the artifact, but *the artifact's document list is itself a claim*. A SCIP run emitting a document for `f` with zero occurrences yields a **complete** claim over `f` with no CALLS edges — reported as an authoritative real negative, with *more* confidence than today's silent `[]`. Partial mitigation: require at least one *definition* occurrence resolving into `f`. But that is a count-based proxy and therefore refutable by construction. **This is the joint the next fresh reader should attack first, and there is no clean answer.**
2. **A wrong row in the static capability table does maximum damage per byte** — e.g. omitting that scip-php emits no Read/Write access roles would mint PHP `READS_FIELD` claims from a tree-sitter heuristic and read them as authoritative. The declared part being small is why it is *dangerous*, not why it is safe.
3. **Claim granularity is per-file; harm is per-symbol.**
4. **A reader that ignores the claim** — `graph_cypher` cannot know which kinds arbitrary Cypher touched. "Requires all kinds" is safe and makes it refuse constantly; the pressure will be to loosen that default, and that is where the model degrades in practice.
5. **The performance conclusion could be wrong where it matters.** `COPY` was measured on synthetic rows into a fresh DB. The real build needs an **in-memory reconciliation pass** first, because `COPY` rejects duplicate PKs and the lanes legitimately collide — SCIP's `preserveStructural` COALESCE (`store/index.ts:269-271`) is real logic preserving tree-sitter's `visibility`/`is_abstract`/`signature` under SCIP's better resolution. **That pass was not measured.** Treat 218 ms as the demonstrated floor of the write path, not as the rebuild cost.

## Evidence an implementation must ship

Contrast pairs; halves give opposite verdicts; none promoted on the builder's own run.

0. **Reproduce `9jt` first** — two-file fixture, edit the callee body, incremental vs fresh, same tree: 14 vs 12 edges, **both HEALTHY**. Converts "sealing is cleaner" into "the current model is measurably wrong." *Already done; keep it as the standing red.*
1. **Bulk-load equivalence** — `COPY`-built and per-statement-built stores over the same input produce identical canonical logical exports. Without this the performance argument is unbacked.
2. **Lane reconciliation under bulk load** — tree-sitter's `visibility`/`is_abstract`/`signature` survive SCIP's null defaults through the in-memory merge exactly as `preserveStructural` produced them. Contrast: remove the merge, duplicate-PK rejection fires. (fake-it #5 as a test.)
3. **The relationship-free fixture (`ugm`)** — 6-file tree seals HEALTHY at full TS fidelity with zero CALLS edges; 7-file version HEALTHY with nonzero. **Identical claim sets, different edge counts, both healthy.**
4. **The `5fi` vendored counterexample** — 40 documents at `node_modules/…` against a 10-file Go repo yields an **empty** CALLS region. No rung, no ratio, no 1.0.
5. **The `hy6.16` shape** — `graph_callers` against a tree-sitter-only entry ⇒ typed refusal, no `rows`; against a SCIP entry ⇒ rows. Same query, two entries, **different types**.
6. **The mixed-coverage pair — the actual payoff.** SCIP covered half the files: a covered file answers `[]` authoritatively, an uncovered one refuses. Today byte-identical.
7. **Derived-not-declared** — a lane self-reporting 812 files whose artifact intersects the manifest at 400 yields a region of **400**.
8. **Non-empty refusal** — capability refusal fires when the answer *has* rows.
9. **Cross-lane disagreement is recorded** as an observation and changes no verdict.
10. **Composite intersection** — CALLS repo + no-CALLS repo: cross-repo aggregate refuses, repo-scoped query answers.
11. **`qv0` replayed** — bare `upsertSymbol` against a sealed entry refused by the filesystem and by seal re-verification.
12. **`ae5` shape** — SIGKILL mid-build ⇒ no entry under any key.
13. **Mutation-test the instrument**, both guards.
