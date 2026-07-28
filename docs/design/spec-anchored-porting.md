# Spec-Anchored Porting

**Status:** Design. Companion to [`port-loop-plan.md`](./port-loop-plan.md) and
[`ct-intention-extraction.md`](./ct-intention-extraction.md).
**First target:** OIDC/OAuth → `identikey-oidc` (Rust), tracked in `identikey-core` beads.
**Date:** 2026-07-28

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

`source` on `IMPLEMENTS_SPEC` records provenance — `citation | annotation | lm | manual` —
so the epistemology charter's confidence discipline applies unchanged: mined citations are
high-confidence evidence, LM proposals are hypotheses until confirmed.

**`requirement_level` is what makes coverage meaningful.** "78% of sections covered" is noise;
**"3 MUST-level sections unimplemented"** is a release gate. Extract RFC 2119 keywords per
section and let every coverage query filter on them.

## 5. Binding code to spec — three tiers

### Tier 1: citation mining *(do this first — highest value per unit effort in the epic)*

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

### Tier 2: annotation in the target

`identikey-oidc` writes its own bindings as it goes:

```rust
/// spec: rfc6749#4.1.3, rfc7636#4.4
pub fn exchange_authorization_code(...) -> Result<TokenResponse> { ... }
```

Coverage becomes authored rather than inferred, and the gate is exact. Cheap because it is
written at the moment the developer already has the section open.

### Tier 3: LM proposal for the remainder

Only for what tiers 1–2 miss. Proposals land as `IMPLEMENTS_SPEC` with `source='lm'` and a
confidence score, never silently promoted. Standard charter discipline.

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

## 9. Prerequisites and risks

**Go lane must work end-to-end.** Two of three references are Go. `scip-go` exists and the SCIP
loader is lane-agnostic, but this has not been exercised — **verify before committing to the
epic**, because it gates everything downstream. Tree-sitter fallback covers citation mining
even if SCIP-Go disappoints, which limits the blast radius.

**Spec source formats vary.** RFCs are well-structured and machine-readable (`rfc-editor.org`
publishes XML). OIDC Core is HTML with anchors, and less regular. Start with RFCs; treat OIDC
Core as its own ingestion task rather than assuming one parser serves both.

**Citation quality is unmeasured.** The claim that fosite and node-oidc-provider cite
extensively is from reading their descriptions and reputation, **not from measuring their
comment density**. If citations turn out to be sparse, tier 1's value collapses and the epic
leans much harder on tiers 2–3. **Measure this in a spike before building the extractor** — it
is a half-hour check that determines the shape of the whole epic.

**Scope discipline.** This is a lane and a schema addition, not a new subsystem. It must not
absorb the port loop, and the port loop must not absorb it. Per the DreamBall anti-vision: if
spec-anchored porting starts growing its own graph store, we have lost the plot.
