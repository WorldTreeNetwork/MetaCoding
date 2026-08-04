# The graph store is a cache: keyed entries, declared fidelity

**Status:** proposed, 2026-08-04. Supersedes `index-fitness.md`.
**Origin:** Duke's reframe → `MetaCoding-ev9` → fresh-architect design.
**Beads:** `ev9`, `0sd`, `hy6.16`, `0mu`, and the dissolve list below.

## The root cause the three refutation rounds were circling

Three fixes, three fresh judges, three refutations:

| round | fix | refuted by |
|---|---|---|
| 1 | write-time gate | read a repo-wide census to answer a per-run question (`4kg`); coverage compared document counts to local files (`5fi`) |
| 2 | import-scanner seam | nine bypasses undetected, incl. ordinary wrapped-import formatting; `indexFile` never guarded (`9ed`) |
| 3 | capability ticket | `Store.upsertSymbol` / `addEdge` are public on the exported barrel, no ticket, no gate (`qv0`) |

These are not three bugs, and not "one layer short" three times. They are **one mistake made three times: the cache entry has no boundary.**

A store is one mutable `graph.lbug` holding every repo, branch and commit at once, and the "key" is a set of *columns* (`repo`, `branch`, `repo_commit_sha`, `indexed_at`) that any writer may set to anything. Every fix guarded a **door** to that shared mutable resource. A shared mutable resource always has a lower door. Guarding doors cannot terminate.

### The fourth refutation, found without attacking anything

While building a fixture for something else, the architect found — and this was independently reproduced at `d8bee31`:

- 6 TypeScript files, classes with scalar fields, zero cross-references. SCIP runs clean, 6/6 documents, correspondence `exact` 1.0 → **REFUSED `[NO_RELATIONAL_EDGES]`**, exit 1.
- The same tree **plus one file that calls another** → **HEALTHY**.

The only difference is a property *of the source code*. `NO_RELATIONAL_EDGES` is **a count used as a proxy for capability**, and a proxy is always refutable by finding a subject where the count is honestly zero. Only *which lanes ran, and what edge kinds can they emit for this language* distinguishes "there are no calls" from "this lane cannot see calls." No edge count ever will. Filed as its own P1.

## The property

> **An answer may be returned only from an artifact whose key the reader recomputed from that artifact's own recorded inputs, and only for a fidelity that artifact's key declares. Anything else is a typed refusal naming what is missing and what it costs to build.**

Contrast with the superseded property ("a graph whose fitness has not been *established*…"). "Established" is a verdict *about* a mutable thing and can go stale the instant after it is rendered — which is exactly `qv0` (12 → 28 symbols under a record reading `fitness 12`). "Recomputed from its own inputs" cannot go stale, because the artifact does not change.

Trustworthiness stops being a property of **control flow** (who was allowed to write) and becomes a property of **data** (does this hash to what I asked for). There is no lower door, because there is nothing to guard: writes go to unkeyed scratch, and only **sealing** mints a key.

## Three layers, three different things

| layer | rebuild cost | what it is | on miss |
|---|---|---|---|
| 1 — `.scip` artifact | minutes; Docker for PHP | nominally cache, **in practice closer to source** | **REFUSE**, print the command and cost; `--build-missing` opts in |
| 2 — graph entry | ~90s / 30k symbols | **pure cache** | **REBUILD silently** (est. printed) — but only if every layer-1 input is a hit |
| 3 — CTKR / LLM | **dollars** | **a ledger, not a cache** | **REFUSE**, always, with estimated spend |

The composition is the point: the cheap layer auto-rebuilds, the expensive layers never do, and **layer 2 cannot silently trigger layer 1.**

### Layer 1 key

```
H( recipe_id, toolchain_digest, tree_digest, dependency_digest, build_env_digest )
```

`toolchain_digest` is the **image/binary sha256**, never a `--version` string — two differently-hacked `scip-php@0.1.0` builds must not collide. `dependency_digest` is e.g. `composer.lock` sha256, because the Drupal site build genuinely varies with resolved deps. An input that cannot be measured makes the key `…+unpinned-<uuid>`: usable **by explicit path, never a hit**. The friction is the point.

`runScip` currently writes `index.<lang>.scip` *into the repo being indexed*. That stops; artifacts live in the cache root.

### Layer 2 key

```
H( store_schema_version, extractor_version, recipe, tree_digest,
   { layer-1 KEYS of every .scip ingested },   ← keys, not sha256s
   path_mapping, achieved_fidelity_profile )
```

Two properties that make this more than a decorated health record:

**(a) Recursive over input *keys*, not declared facts.** A layer-1 key already contains the tree digest of the commit its `.scip` describes. So re-ingesting yesterday's `.scip` at a new commit yields a key that is *honest about it* — the CALLS lane keyed at commit W, tree-sitter at X, and a reader asking for X does not hit. **This closes open red #2 (`19g`) by construction rather than by citation**, and it falls out for free from refusing to put declared strings in keys.

**(b) The fidelity profile is ACHIEVED, not requested.**

```jsonc
{ "lanes": [ {"lane":"tree-sitter","languages":["php"],"outcome":"complete"},
             {"lane":"scip-php","toolchain":"sha256:…","outcome":"complete"} ],
  "capabilities": { "php": ["CONTAINS","EXTENDS","IMPLEMENTS","CALLS","REFERENCES", …],
                    "go":  [] },              // ← load-bearing
  "files": { "php": {"inTree":812,"inGraph":812},
             "go":  {"inTree":262,"inGraph":0} } }   // ← reported, NEVER thresholded
```

`capabilities` is a fact about which lanes completed, cross-referenced against a static table of what each lane can emit. Verified in the code: the tree-sitter lane emits `CONTAINS/EXTENDS/IMPLEMENTS/USES_TRAIT/READS_FIELD/WRITES_FIELD/CONSTRUCTS/RAISES/RETURNS_TYPE/ANNOTATES/TYPE_OF` and **never `CALLS`/`REFERENCES`** — those come only from SCIP. That table is the entire fidelity model, and it is small.

`files` has as its denominator **the key's own input file list** — the same set that was hashed. There is no second set to substitute, so the `exact`/`suffix`/`basename`/`UNMEASURABLE` ladder and `--min-coverage` are **deleted outright**.

**A failed lane no longer fails the build — it LOWERS THE KEY.** `--scip on/off` stops being a corner case in the analysis layer.

### Sealing

Build into `graphs/<repo>/tmp-<uuid>/`; compute the seal; write `MANIFEST.json`; `rename()` into place; `chmod a-w`. **Atomic rename is the seal.** Readers open read-only and **recompute the key from the manifest's recorded inputs** — a directory named `X` whose inputs hash to `Y` is rejected.

**Measured, and it shapes the seal.** Two independent builds of one fixture: `tokens.fts.sqlite` byte-identical; `graph.lbug` same size, **different bytes**; canonical logical export **identical**. So the seal is over a canonical logical export, not raw bytes. Likely cause of the byte difference is per-run `Symbol.indexed_at` — which dissolves under this model anyway. **Verify that first**: it is a 90-second experiment that could simplify the scheme to a plain file digest.

## How a query declares fidelity

Every graph tool takes an optional `requires`, and **each has a non-empty default derived from its meaning** — `graph_callers` → `{edges:["CALLS"]}`, `graph_cypher` → kinds parsed from the query, unparseable ⇒ all. A caller who writes nothing is still protected.

```jsonc
{ "ok": false, "error": "FIDELITY_NOT_BUILT",
  "message": "graph_callers requires CALLS for php. The entry answering farmos@3fe0ce7 was built with lanes [tree-sitter@1.4], which emit no CALLS for php. This is NOT 'no callers' — this lane cannot see calls.",
  "required": {...}, "available": {...},
  "fix": "metacoding build farmos@3fe0ce7 --fidelity calls  (needs scip artifact s1c9…: Docker site build ~40min; then graph ~485s)" }
```

No `rows` property — the type-level discriminant from `health-gate.ts` is kept **verbatim**, because it is the one thing that worked.

**Two deliberate strengthenings.** (1) `gateQueryAnswer` today refuses only when `rows.length === 0`; but `hy6.16` was an aggregate over **41 rows**. A partial-fidelity answer that *returns data* is more dangerous than one that returns nothing, because it looks authoritative — so capability refusal is **unconditional**. (2) Every refusal names its cost, because the cost asymmetry must be visible at the moment someone decides whether to proceed.

## Dissolve or survive

`ev9` requires dissolved beads be closed **AS DISSOLVED with their evidence** — the original measurement is the witness for why the machinery is being deleted.

| bead | verdict |
|---|---|
| `c03`, `7f9`, `4kg`, `ae5` | **dissolve** — all are artifacts of partial updating and a boundary-less entry |
| `5fi` | **dissolves structurally** — numerator and denominator become the same set; ladder deleted |
| `9ed`, `qv0` | **dissolve** — nothing to guard; delete `ticket.ts` and `seam.test.ts` |
| `19g` | dissolves as correctness (now in the key), survives as an append-only **build log** |
| `sih`, `226` | dissolve — no slice enumeration; artifact staleness becomes **digest equality**, not timestamp ordering |
| `e6z` | dissolves as a bead, **binding as a method** — contrast pairs govern the new implementation |
| `d1h` | **fix now, do not wait** — a false claim left standing during a redesign gets copied into the successor |
| `zpi` | survives — `index-fitness.md` gets a SUPERSEDED header and its two false claims corrected in place. **Do not delete it: its refutation history is the most valuable content in the repo on this subject.** |
| `0sd` | **survives — the one bead the cache model does not dissolve.** A lane that runs, fails, and is reported as success still seals an entry. Its AC changes: not "assert non-zero edge counts by type" (refuted by the relationship-free fixture) but "achieved capabilities equal requested, or exit non-zero and record the lowered key." |
| `hy6.16` | survives — made *cheap* (the `.scip` is a layer-1 hit) and its recurrence impossible to miss |
| `0mu` | survives, transformed — `gateCtkrAggregate` stays; predicate becomes key equality |

## Where fitness moves to: layer 3

At layer 2 every fitness measure is a proxy for capability, and proxies get refuted. At layer 3 the question is not a proxy: **which graph key was this derived from, and did that key carry the fidelity this derivation needed.** That is digest equality.

Five things layer 3 needs:

1. **The input key stamped at build time** — the Python batch runners must write the layer-2 key into `manifest.json`. Highest-value single item in the design: it converts every timestamp heuristic into an equality test.
2. **Per-artifact provenance, not per-manifest** — different artifacts derive from different entries at different times.
3. **A recorded fidelity *requirement* per derivation** — then an artifact derived from a graph lacking CALLS is **detectably wrong retrospectively**, which for a paid artifact is the whole game: you cannot prevent the spend, only invalidate the output.
4. **Cost joined to the key** — `llm_cost.jsonl` exists; join it so "what would rebuilding cost" is answerable *before* anyone proposes eviction.
5. **Sub-artifact invalidation granularity** — keyed at the granularity the LLM call was made, so a re-index invalidates only what changed. **This is where the design effort should go.** Layers 1 and 2 are mostly deletion.

## Eviction

Retention proportional to rebuild cost ÷ size. Layer 1: keep forever, never auto-pruned. Layer 2: prune freely (`metacoding gc`, plus an opportunistic prune after a *successful* build — the one moment the system knows it superseded something; never during a query). Layer 3: **never GC'd by the system** — only a human, with the dollar figure in front of them.

A store with entries for five old commits is the design working, not a leak: `graph_diff` across commits becomes a cache hit. The `farmos@?` orphan dissolves — an entry either matches a key someone asks for or is never opened, and it can never make *another* entry refuse.

## Migration

**Rebuild both live stores. Declining to eat the thesis on the first two stores would be the weakest possible start.**

1. **Adopt the `.scip` first** — the 2026-07-17 farmOS artifact becomes a layer-1 entry (pinned if its commit + image digest can be named; `unpinned` otherwise). Do this *before* layer 2, or the 485s rebuild becomes a Docker build.
2. Rebuild layer 2 — measured: MetaCoding ~90s, farmos-port 485s warm.
3. Preserve `.metacoding/ctkr/` untouched.
4. **Layer 3 gets a caveat, not a refusal** — stamp existing artifacts `derived_from: legacy-store, provenance not comparable`.

Point 4 departs from a strict reading of the cache framing, deliberately. For a cache, "if in doubt, rebuild" is right because doubt costs 90 seconds. For a **ledger**, the correct default is **flag and keep**: a false alarm costs dollars, a stale flag costs a sentence someone reads. `0mu`'s refuse-by-default is right for *newly derived* artifacts and wrong for the migration cohort.

## What this handles worse

1. **`watch` / the editor loop.** Sub-second per-file updates are incompatible with sealed entries. Answer: `watch` writes to a **mutable unkeyed scratch entry**, never a hit, never feeds layer 3, reachable only with explicit `allow_scratch`. Strictly less capable than today.
2. **Cross-repo corpora.** Needs a **composite entry** keyed on `H(sorted member keys)`. Costs disk — each repo's data exists in every composite it belongs to.
3. **The rebuild path is the cache's floor, and farmOS's floor is Docker.** If that recipe rots, every entry above it is unreproducible, where today's mutable store at least still *holds* the data. **Mitigation, and it should be a bead: pin and archive layer-1 artifacts as backed-up assets, not regenerable cache.**
4. **First cold experience gets worse** — a fresh clone refuses instead of quietly producing a half-fidelity graph. Correct, and it will feel worse.

## How would we fake this design?

1. **A correct key over a broken extractor** — every input hashed, every seal valid, every edge wrong. **Not caught**, same as today. Partial credit: `extractor_version` is in the key, so a fixed extractor invalidates every entry automatically, which today's model cannot do.
2. **A recipe that lies about its own identity.** Whoever writes the recipe chooses what counts as an input, and **an input left out of the key is a dimension the cache is blind to.** *This is this design's version of "one layer short."* The answer is not another guard: the manifest records the input list **in full**, so a reader can see what was **not** keyed. Enumerated blindness beats invisible blindness — but it is still blindness, and it is the joint a fourth adversary should attack first.
3. **A composite that mixes fidelities** — a corpus where repo A has CALLS and B does not returns a confident answer complete for A and empty for B. **That is `hy6.16` at corpus scale, reintroduced by the composite design.** Rule: a composite's capability profile for a cross-repo requirement is the **intersection** over members. Must ship with a test or the composite is a regression.
4. **Scratch drift** — if any reader treats scratch as an entry, the model collapses into today's with more ceremony.
5. **`unpinned` becomes the new `UNMEASURABLE`** — exactly the trap the ladder fell into. Discipline: never a hit, must be named by explicit path.
6. **Seal verification skipped for speed** — re-digesting 117MB is 100–300ms. Cheap check on open, full re-digest under `--verify` and in CI. A real ongoing cost, not solved.

## Evidence that must ship

Contrast pairs, halves giving opposite verdicts. **None may be promoted on the builder's own run.**

0. **First, the cheap experiment that could change the design:** strip per-run `indexed_at`, rebuild one fixture twice. Byte-identical `graph.lbug` ⇒ the seal is a file digest; otherwise a canonical logical export.
1. **Key determinism/discrimination** — identical inputs ⇒ same key; differing only in an ingested `.scip`'s own layer-1 key ⇒ different keys (the open-red-#2 test).
2. **The `qv0` attack replayed** — 16 bare `upsertSymbol` calls against a sealed entry refused by the filesystem and by seal re-verification; contrast: the same writes into scratch succeed, and scratch never satisfies a lookup.
3. **The `5fi` vendored-suffix counterexample replayed** — must yield `go: {inTree:262, inGraph:0}` and an empty `go` capability set. No rung, no ratio, no 1.0.
4. **The `hy6.16` shape** — `graph_callers` against a tree-sitter-only PHP entry ⇒ `FIDELITY_NOT_BUILT`, no `rows`; against a scip-php entry ⇒ rows. Same query, two entries, **different types**. The one test that would have prevented the 41-row loss.
5. **Non-empty refusal** — the capability refusal fires when the answer *has* rows.
6. **The `0sd` fosite shape** — `--scip` on a Go repo seals an entry whose achieved fidelity is empty, exits non-zero, key names achieved not requested.
7. **The relationship-free fixture** — the 6-file tree builds **HEALTHY at full TS fidelity with zero CALLS edges**, contrasted with the 7-file version: identical capability sets, different edge counts, both healthy.
8. **The `ae5` shape** — SIGKILL mid-build ⇒ no entry under any key; next lookup is a clean miss.
9. **The `7f9` shape** — build at A then B; a query resolved to B's key cannot see A's symbols.
10. **Composite intersection** — one CALLS repo + one no-CALLS repo: cross-repo aggregate refuses, repo-scoped query answers.
11. **Mutation-test the instrument**, both guards: anchors asserted, baseline clean before *and* after, restores from sha256-verified copies.

## Net

On the order of **1,500 lines removed** against a few hundred added: `ticket.ts`, `seam.test.ts`, most of `fitness.ts`, most of `health.ts`, `--allow-empty-index`, `--min-coverage`. `health-gate.ts` is kept in shape and re-predicated.

That subtraction is the signal `iteration-methodology.md` describes — several findings collapsing into one mechanism.
