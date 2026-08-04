# Spec-Anchored Porting

**Status:** Design. Companion to [`port-loop-plan.md`](./port-loop-plan.md) and
[`ct-intention-extraction.md`](./ct-intention-extraction.md).
**First target:** OIDC/OAuth → `identikey-oidc` (Rust), tracked in `identikey-core` beads.
**Date:** 2026-07-28 · **Re-scoped:** 2026-08-04 after MetaCoding-d1l.6 and d1l.7
(see [`../notes/2026-08-04-rfc-citation-density-spike.md`](../notes/2026-08-04-rfc-citation-density-spike.md)
and [`../notes/2026-08-04-go-js-lane-spike.md`](../notes/2026-08-04-go-js-lane-spike.md)) —
§5 is the section that changed shape; §9 records what was falsified.

---

## 1. A second port shape

The port loop as written assumes one shape: **port *from* a source codebase**, where intent
must be *inferred* from implementation. farmOS is the exemplar, and the epistemic machinery —
[`no-oracle-fallback.md`](./no-oracle-fallback.md), the
[epistemology charter](./epistemology-charter.md), intent-vs-idiom separation via the N=2
rewrite — exists because that inference is genuinely hard and easy to fake.

There is a second shape, and it is the one IdentiKey needs:

> **There is no source codebase. There is a written specification, and N independent
> implementations of it.**

Building an OIDC provider means reading RFC 6749/6750/7636/8414/9068/9700 and OIDC Core, then
writing Rust. `ory/fosite` (Go), `zitadel/oidc` (Go) and `panva/node-oidc-provider` (JS) are
not sources to port *from* — they are **prior readings of the same text**.

The two shapes are complementary, not competing, and the second is worth building because it
is *easier in exactly the place the first is hardest*.

## 2. Why this is a calibration instrument, not just a feature

The intention-extraction program's core problem is that it has no ground truth. §7.2/§10 of the
intention doc names this. farmOS supplies N=2 rewrites of one product, which separates intent
from idiom *empirically* — but nothing external says what the intent actually **was**. The
harvest can only be checked against itself.

Spec-anchored porting supplies the missing instrument:

| | farmOS shape | Spec shape |
|---|---|---|
| Intent | Inferred from code | **Written down, normatively, in the RFC** |
| Ground truth | None external | The spec text itself |
| Independent instances | 2 (same community, sequential) | **3+ (different orgs, languages, concurrent)** |
| Validation question | "Did we separate intent from idiom?" | "Did we recover what the document says?" |

This is a **measurable oracle**. Run intention extraction over fosite; compare the harvest
against the RFC sections fosite's own comments cite. Precision and recall become computable
numbers rather than adjudicated impressions. Nothing else in the corpus offers that.

There is a second gift: the three implementations are by **different organisations, in two
languages, developed concurrently and independently**. farmOS's N=2 shares a community and a
lineage; convergence there may be habit. Convergence across fosite/zitadel/node-oidc-provider
is much stronger evidence that the *spec* is what is doing the constraining.

## 3. The core idea

Bind **spec sections** into the graph as first-class nodes, alongside the code that implements
them, across every indexed repository at once.

Then the questions that actually drive the work become graph queries:

- *What have I not implemented yet?* — sections with no `IMPLEMENTS_SPEC` edge from my repo
- *How does everyone else do §4.1.3?* — all symbols across all repos bound to that section
- *Where do the implementations disagree?* — sections where their structures diverge
- *This conformance test failed; where do I look?* — test → section → the three implementations

Coverage is tracked **against the specification**, not against a source repo. That is the
whole distinction, and it is what makes this spec-anchored rather than code-anchored porting.

## 4. Schema additions

Consistent with the existing single-polymorphic-`Symbol` approach in
[`schema.md`](./schema.md); `SpecSection` is a genuinely different kind of thing, so it gets
its own table rather than another `kind` value.

```cypher
CREATE NODE TABLE SpecSection (
  id                STRING PRIMARY KEY,  -- rfc6749#4.1.3
  doc               STRING,              -- RFC6749 | OIDC-Core-1.0 | RFC9700
  number            STRING,              -- 4.1.3
  title             STRING,
  text              STRING,
  url               STRING,
  requirement_level STRING,              -- MUST | SHOULD | MAY | none  (RFC 2119)
  normative         BOOLEAN,             -- contains any RFC 2119 keyword
  status            STRING               -- current | obsoleted | updated-by
);

CREATE REL TABLE IMPLEMENTS_SPEC FROM Symbol      TO SpecSection (confidence DOUBLE, source STRING);
CREATE REL TABLE TESTS_SPEC      FROM Symbol      TO SpecSection (source STRING);
CREATE REL TABLE CITES_SPEC      FROM Symbol      TO SpecSection (raw STRING);
CREATE REL TABLE SPEC_REFERENCES FROM SpecSection TO SpecSection (kind STRING);
```

`source` on `IMPLEMENTS_SPEC` records provenance — `citation | annotation | propagated | lm |
manual` — so the epistemology charter's confidence discipline applies unchanged: mined
citations are high-confidence evidence, LM proposals are hypotheses until confirmed.

> **`propagated` added 2026-08-04** for §5.4's seed propagation. A propagated edge is neither a
> citation (nobody wrote it) nor an LM proposal (no model proposed it) — it is the seed's
> authority attenuated by graph distance, and it must record the seed edge it descended from
> and the hop count, or its confidence is unauditable.
>
> **`TESTS_SPEC.source` is not Symbol-derived.** Per §8, its bindings come from the OIDF
> conformance suite's naming, not from the reference repos' tests; the `FROM` side may not be a
> `Symbol` in this graph at all. Check that before building the table.

**`requirement_level` is what makes coverage meaningful.** "78% of sections covered" is noise;
**"3 MUST-level sections unimplemented"** is a release gate. Extract RFC 2119 keywords per
section and let every coverage query filter on them.

## 5. Binding code to spec — a seed, then propagation

> **Revised 2026-08-04 after MetaCoding-d1l.6 and d1l.7.** This section originally read as
> *three tiers, mine the citations first, and most of the mapping is free*. That ordering was
> load-bearing and the first half of it was measured false. The corrected shape is below; the
> original tier text is kept beneath it, annotated, for the record.

**The corrected shape.** Tier 1 produces a small, high-precision **seed** (~115 distinct
`(spec, section)` pairs across the whole three-repo corpus, clustered in ~58 protocol-flow
files). Coverage of the **target** comes from tier 2, which is unaffected by any measurement
here because the developer writes it. Coverage of the **reference repos** — which is what
`spec_consensus` / `spec_divergence` need — comes from **propagating the seed through the
graph** (§5.4) and/or from tier 3, and that is the epic's remaining unknown.

The ordering that follows from this:

| | what it binds | cost | status |
|---|---|---|---|
| **Tier 1** citation mining | the seed, in the references | hours (script exists) | measured: 5.6 / 8.0 / 0.3 % of exported symbols |
| **Tier 2** annotation in the target | `identikey-oidc`, exactly | ~free, written in the moment | unaffected — ship `spec_coverage` on this |
| **Tier 4** seed propagation | the references, from tier 1 | cheap, graph-native | proposed; unmeasured |
| **Tier 3** LM proposal | whatever remains | unknown $/KLOC | **unmeasured, and now load-bearing** |

Tier 3 is listed last deliberately. Under the original design it was a mop-up for what tiers
1–2 missed; with tier 1 demoted it became the only route to dense reference-repo coverage, i.e.
a much larger and riskier scope than the word "remainder" implies. **Measure it (d1l.15) before
estimating anything that depends on it (d1l.12).** That is the same discipline d1l.6 applied to
tier 1, one tier over.

### Tier 1: citation mining *(the seed and the oracle — not the backbone)*

> **Measured 2026-08-04 (MetaCoding-d1l.6) — the claims in this subsection are partly wrong.**
> Section citations run 6.6 / 4.1 / **1.6** per KLOC in fosite / zitadel / node-oidc-provider,
> and reach only **5.6% / 8.0% / 0.3%** of exported symbols within 10 lines. Tier 1 is cheap,
> precise and worth doing — as a *seed set* (~115 distinct sections) and as the **calibration
> oracle** of §2 — but it is **not** "a large mapping for free" and cannot be the coverage
> backbone. `node-oidc-provider`, named below as citing constantly, is the sparsest of the
> three. See [`../notes/2026-08-04-rfc-citation-density-spike.md`](../notes/2026-08-04-rfc-citation-density-spike.md).

**`fosite` and `node-oidc-provider` cite RFC sections in their comments constantly.** So do
most serious protocol implementations — it is how their authors keep themselves honest.

```go
// implements the authorization code grant, see
// https://tools.ietf.org/html/rfc6749#section-4.1.3
```

A comment extractor plus a citation regex yields a large, high-quality spec↔code mapping **for
free**, and — this is the point — it is *the reference implementations' own authoritative
statement* about which section each piece of code answers to. No inference, no LM, no
adjudication. It is the cheapest ground truth in the entire program.

Patterns to cover: `rfc\d+#section-[\d.]+`, `RFC ?\d+,? [Ss]ection [\d.]+`, `§[\d.]+`,
`openid-connect-core-1_0.html#...`, `@see` / `@spec` tags, and Go doc-comment conventions.

> **Pattern list, corrected against the corpus (d1l.6).** Four families the list above misses,
> all of which changed the numbers: connector words (`RFC 8693 in section 2.1`);
> `openid.net/specs/<anything>.html#anchor` (FAPI and `openid-financial-api-*` do not match
> `openid-*-1_0`); textual `OpenID Connect Core 1.0, section 3.1.3.6` — zitadel's dominant
> form, which alone took its OIDC-Core section count from 4 to 16; and `draft-ietf-*-NN#`.
> **None of the three repos use `@see`/`@spec`** — that pattern belongs to tier 2 only.
> Attribution must also reach *indented* exported interface methods and struct fields: fosite's
> densest file (`oauth2.go`, 28 citations) is one interface block, invisible to `^func`.
>
> Two specs the epic never listed are cited anyway and should be ingested: **RFC 6819**
> (OAuth threat model — fosite cites 7 sections) and **RFC 3986** (URI comparison, 4 sections;
> redirect-URI comparison is a real correctness hazard in a port).

### Tier 2: annotation in the target

`identikey-oidc` writes its own bindings as it goes:

```rust
/// spec: rfc6749#4.1.3, rfc7636#4.4
pub fn exchange_authorization_code(...) -> Result<TokenResponse> { ... }
```

Coverage becomes authored rather than inferred, and the gate is exact. Cheap because it is
written at the moment the developer already has the section open.

### Tier 4: seed propagation through the graph *(added 2026-08-04, MetaCoding-d1l.17)*

Citations reach **19–21% of Go *files*** but only 6–8% of *symbols*. File-level binding is 3×
better than symbol-level, and the graph already holds the rest of the structure. A cited
symbol's **callees, implementers and same-file neighbours** are strong candidates for the same
section, and propagating from a high-precision seed is exactly what a typed graph is for.
d1l.6's judgement is that this is a better spend than LM-proposing cold; d1l.15 measures the
two arms against each other.

Propagated edges land as `IMPLEMENTS_SPEC` with `source='propagated'`, carrying the seed edge
they descended from and the hop count. They are neither citations (nobody wrote them) nor LM
proposals (no model proposed them) — they are the seed's authority attenuated by distance, and
conflating them with either destroys the provenance discipline §4 depends on.

### Tier 3: LM proposal — no longer "the remainder"

Originally scoped as mop-up for what tiers 1–2 miss. With tier 1 measured at 5.6/8.0/0.3% and
tier 2 confined to the target repo, **tier 3 is the only route to dense binding in the
reference repos**, which is a materially larger and riskier job than the original framing. Its
cost and precision at corpus scale are **unmeasured** — the same failure mode d1l.6 corrected
for tier 1. Measure first (d1l.15, with a pre-registered threshold), estimate second.

Proposals land as `IMPLEMENTS_SPEC` with `source='lm'` and a confidence score, never silently
promoted. Standard charter discipline.

**Hold out the oracle.** §2's calibration study scores a harvest against the sections the
references' own comments cite. If propagation or LM proposal is *seeded* from those same
citations and then scored against them, both numbers are circular. Split the citation set
before any binding pass runs.

## 6. MCP surface

New tools, composable with the existing graph surface:

| Tool | Returns |
|---|---|
| `spec_sections(doc, requirement_level?)` | sections, filterable to normative only |
| `spec_coverage(doc, repo, requirement_level?)` | **unimplemented sections** — the porting worklist |
| `spec_implementations(section_id)` | every symbol, in every indexed repo, bound to that section |
| `spec_consensus(section_id)` | CTKR structural comparison across the N implementations |
| `spec_divergence(doc)` | sections where implementations structurally disagree |

`spec_coverage` is the one the agent will call every session. It is the answer to "what's left",
and unlike a task list it cannot drift from reality.

> **Which of these are actually reachable (2026-08-04).** `spec_sections` and `spec_coverage`
> read the target's own annotations (tier 2) and are untouched by either spike — build them
> first, they are the only near-term deliverables whose value rests on nothing unmeasured.
> `spec_implementations`, `spec_consensus` and `spec_divergence` all need *dense bindings in the
> reference repos*, which is exactly what tier 1 does not supply; they are gated on d1l.15's
> verdict, and their honest v1 is scoped to the ~58 citation-bearing files.

## 7. The CTKR payoff — and why divergence beats convergence

Where three independent implementations **converge** structurally on a section, that
convergence is the spec expressing itself through code. That is the highest-signal thing to
port, and CTKR motif mining scoped to a section finds it.

But the more useful signal is **divergence**. Where fosite, zitadel and node-oidc-provider
structurally disagree about one section, exactly one of these is true:

1. **The spec is ambiguous there** — and a naive port will pick one reading and be subtly wrong.
2. **The section is genuinely optional** — and the divergence is three legitimate choices.
3. **One of them has a bug** — which is worth knowing before copying its shape.

All three are things you want flagged *before* writing code, and none of them are visible from
reading the spec alone or from reading any single implementation. **This is the capability that
justifies indexing three implementations instead of one** — and it is not available in the
farmOS shape at all, because N=2 from one community cannot distinguish ambiguity from habit.

> **Three ways a divergence metric will lie, measured 2026-08-04 (d1l.7).**
> (i) `IMPLEMENTS` density is **586 in fosite vs 24 in node-oidc-provider** — that reads Go
> structural typing against JS prototypes, not spec disagreement. (ii) Symbol counts are not
> comparable either: **88% of node-oidc-provider's 12,617 symbols are inferred `type_alias`
> noise** from data literals; normalise to `function|method|class` before any ratio.
> (iii) Qualified-name *shape* differs by lane — Go is package-FQN
> (`github.com/ory/fosite.Fosite.WriteAccessError`, and `filePathOf()` returns null for 100% of
> Go definitions) while JS/TS/PHP are file-shaped (`lib/helpers/errors.js::InvalidToken`). Key
> on structure, never on string form.
>
> And the third implementation is a weaker vote than this section assumes: node-oidc-provider
> carries section citations in **4 of 235 files**, dominated by OpenID4VCI rather than the core
> RFCs targeted here. Where the data supports N=2 with a JS cross-check, say that.

## 8. Conformance-suite linkage

The OpenID Foundation conformance suite is the external referee for `identikey-oidc`. Binding
its test names to spec sections (`TESTS_SPEC`) closes the loop:

```
conformance test fails
  → the section it tests
    → my symbols bound to that section (or the absence of them)
      → how the three reference implementations handle it
```

That is a debugging path no other tool in the stack provides, and it turns a red CI run into a
navigable query instead of a search problem.

> **Where `TESTS_SPEC` edges come from — corrected 2026-08-04 (d1l.6).** Not from mining the
> reference implementations' test suites: **14 section citations across 65,000 lines of test
> code in all three repos combined**, and *zero* in node-oidc-provider's 34k. There is no cheap
> test-side harvest anywhere in this corpus. Bindings must come from the conformance suite's own
> naming — its test and test-plan identifiers and published module descriptions — which is
> external data acquisition, not graph mining, and a different kind of task from the one this
> section implies. It is deferred (d1l.13, P3) until `identikey-oidc` is actually running the
> suite; the debugging path above is still the best one in the design, it is just no longer cheap.

## 9. Prerequisites and risks

**Go lane must work end-to-end.** *(Measured 2026-08-04 —
[`../notes/2026-08-04-go-js-lane-spike.md`](../notes/2026-08-04-go-js-lane-spike.md), d1l.7.
**Both halves of the paragraph below were wrong.** Original kept for the record.)*
Two of three references are Go. `scip-go` exists and the SCIP
loader is lane-agnostic, but this has not been exercised — **verify before committing to the
epic**, because it gates everything downstream. Tree-sitter fallback covers citation mining
even if SCIP-Go disappoints, which limits the blast radius.

What was actually found:

- **There is no Go lane.** `ScipLanguage = typescript | python | php`; `INDEXERS` has no Go
  entry; `detectScipLanguages()` can never return Go; `--scip-language` rejects `go`. Every Go
  number in the spike was produced manually, out of band, ingested via
  `--load-scip --scip-language ts` — a deliberate lie, because no honest value exists.
  Production cannot reproduce any of it today. (MetaCoding-d1l.16, P1.)
- **`metacoding index <fosite> --scip` exits 0 with a completely empty graph.** fosite ships
  `package.json` + `tsconfig.json`, so `scip-typescript` is selected, fails with "no files got
  indexed", the failure is caught and logged, and the run reports success. `resolveScipWanted`
  guards indexer *availability*; availability was never the risk. This is hy6.16 reproduced in
  a new repo. (MetaCoding-0sd, P1.) **The only honest assertion is non-zero edge counts by
  type, queried out of the store — never process exit status.**
- **There is no tree-sitter fallback for `.go`/`.js`/`.mjs`/`.cjs` at all.** `detectGrammar()`
  returns null for every one of them: symbols 0, edges 0, and **FTS tokens 0** (the tree-sitter
  walker is the only writer of the `tokens` table). Lanes 3 *and* 4 are dark for the entire
  reference corpus. The grammars are bundled; the dispatch and extractors are missing.
  (MetaCoding-279.) **The blast-radius argument above is therefore void** — citation mining
  must own its own file walk, as `scripts/spike-citation-density.ts` already does.
- **What works, and is a windfall:** `scip-go` computes **Go interface satisfaction** — 776
  implementations in fosite landing as 586 real `IMPLEMENTS` edges at both type and method
  level, from an 8.9s indexer run. Go is structurally typed, so nothing in the source declares
  these and no syntactic pass can recover them. That is precisely the substrate §7 and the
  CTKR role-equivalence work need. Reference counts for fosite @`a5f0b09b`: CALLS 3274,
  REFERENCES 7065, IMPLEMENTS 586, READS_FIELD 3936. Use them as the regression baseline.
- **Known holes to carry forward:** 42,126 Go external refs are dropped with no boundary node
  (PHP has Pass-2b; Go gets none), so stdlib / `net/http` / `crypto/*` usage is invisible;
  budget ~3–4 min of store-load *per repo* (`loadScip` is the cost, not the indexers); and
  `scip-go` has moved to `github.com/scip-code/scip-go`.

**Spec source formats vary.** RFCs are well-structured and machine-readable (`rfc-editor.org`
publishes XML). OIDC Core is HTML with anchors, and less regular. Start with RFCs; treat OIDC
Core as its own ingestion task rather than assuming one parser serves both.

**Citation quality is unmeasured.** *(Resolved 2026-08-04 — measured in
[`../notes/2026-08-04-rfc-citation-density-spike.md`](../notes/2026-08-04-rfc-citation-density-spike.md);
density is sparse enough that tier 1 must be demoted from backbone to seed+oracle, and the epic
re-scoped accordingly. The original text is kept below for the record.)*
The claim that fosite and node-oidc-provider cite
extensively is from reading their descriptions and reputation, **not from measuring their
comment density**. If citations turn out to be sparse, tier 1's value collapses and the epic
leans much harder on tiers 2–3. **Measure this in a spike before building the extractor** — it
is a half-hour check that determines the shape of the whole epic.

**The load-bearing unknown is now tier 3.** *(New 2026-08-04.)* Tier 1 was the claim this
design rested on, it was measured, and it moved. The weight it was carrying did not disappear —
it transferred to LM proposal (and, cheaper, to seed propagation), neither of which has a
number attached. Cost per KLOC and precision against held-out citations must be measured
(d1l.15) **before** the consensus/divergence tools are estimated. If that measurement comes
back badly, the correct response is not a bigger LM budget: it is to ship `spec_divergence`
scoped to the ~58 citation-bearing files where the protocol logic actually lives, and to stop
claiming corpus-wide spec coverage of the reference implementations.

**What this design is worth, stated honestly.** It claimed a large spec↔code mapping for free
and does not have one. What it does have, after both spikes: a genuine external oracle for the
intention-extraction program (§2 — which needs *authority*, not density, and survives the
demotion intact), a divergence capability available nowhere else, free Go interface-satisfaction
edges the design did not know existed, and a target-side coverage gate (`spec_coverage`) that
nothing measured here touches. That is a smaller epic and a sharper one.

**Scope discipline.** This is a lane and a schema addition, not a new subsystem. It must not
absorb the port loop, and the port loop must not absorb it. Per the DreamBall anti-vision: if
spec-anchored porting starts growing its own graph store, we have lost the plot.
