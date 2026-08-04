# RFC-citation density in the three OIDC reference implementations

**Bead:** MetaCoding-d1l.6 (SPIKE) · **Epic:** MetaCoding-d1l · **Date:** 2026-08-04
**Design under test:** [`../design/spec-anchored-porting.md`](../design/spec-anchored-porting.md) §5, tier 1
**Script:** [`../../scripts/spike-citation-density.ts`](../../scripts/spike-citation-density.ts)

The design says, of tier 1 (mining RFC citations out of comments into `CITES_SPEC` edges):

> *"`fosite` and `node-oidc-provider` cite RFC sections in their comments **constantly**. […] A
> comment extractor plus a citation regex yields a large, high-quality spec↔code mapping **for
> free**. […] It is the cheapest ground truth in the entire program."*

and, in §9, flags that claim as resting on reputation rather than measurement. This is the
measurement.

**Verdict: re-scope. Tier 1 does not collapse, but it is not the backbone either.**
It yields ~115 distinct `(spec, section)` bindings across the whole corpus and touches
**3–9% of exported symbols**. "Most of the mapping for free" is false by an order of magnitude.

---

## 1. Method

Repos cloned shallow and measured at:

| repo | commit | tip date |
|---|---|---|
| `ory/fosite` | `a5f0b09bf31c17297b25637bb3fec2ff7a55b159` | 2025-07-03 |
| `zitadel/oidc` | `3c8b7045b537f185a593909a861f95608cbdc17d` | 2026-07-27 |
| `panva/node-oidc-provider` | `4550cc3361359e20c9b86dc4ab388a26cbbbf701` | 2026-08-03 |

Reproduce:

```sh
bun scripts/spike-citation-density.ts <fosite> <zitadel-oidc> <node-oidc-provider>
```

Counting rules:

- **Comment-only.** A line must lex as a comment. This keeps `rfc8628.NewHandler`, package
  paths and `//go:generate` mockgen lines out of the numbers.
- **Prod vs test split.** `_test.go`, `*.test.js`, `test/`, `testdata/` excluded from LOC and
  from the headline counts; test citations reported separately.
- **Patterns widened against the actual corpora, not invented up front.** Hand-sampling first
  found four families the obvious pattern list misses, all of which were added:
  `RFC 8693 **in** section 2.1` (connector words), `openid.net/specs/<anything>.html#anchor`
  (FAPI and `openid-financial-api-part-2-1_0-final` do not match `openid-*-1_0`), textual
  `OpenID Connect Core 1.0, section 3.1.3.6` (zitadel's dominant form — this alone took
  zitadel's OIDC-Core sections from 4 to 16), and `draft-ietf-*-NN#…`.
- **Three strictness levels** are reported: *strict* (spec and section both explicit on the
  line), *context-resolved* (a bare `Section 4.1.2.1` inside a comment block that already named
  a spec within 40 lines — what a real extractor would resolve), and *any-spec-mention*
  (includes doc-level citations with no section anchor, the coarsest usable binding).

`@see` / `@spec` tags: **none of the three repos use them.** The pattern is in the script for
tier 2 (`identikey-oidc`'s own annotations), where it will matter.

## 2. Results

### Density

| | fosite | zitadel/oidc | node-oidc-provider |
|---|---:|---:|---:|
| prod files | 160 | 114 | 235 |
| prod LOC (non-blank) | 14,818 | 15,834 | 19,774 |
| comment lines | 2,961 (20.0%) | 2,010 (12.7%) | 3,509 (17.7%) |
| **section citations / KLOC** | **6.61** | **4.11** | **1.62** |
| section citations (count) | 98 | 65 | 32 |
| context-resolved / KLOC | 7.83 | 4.17 | 1.62 |
| doc-level-only / KLOC | 3.31 | 0.95 | 5.11 |
| files with ≥1 section citation | 30 / 160 (18.8%) | 24 / 114 (21.1%) | **4 / 235 (1.7%)** |
| section citations in test code | 7 (over 19.1k test LOC) | 7 (12.3k) | **0 (34.0k)** |

### Distinct sections cited

| repo | specs | distinct sections | top specs |
|---|---:|---:|---|
| fosite | 12 | 50 (61 context-resolved) | RFC6749 (21), RFC6819 (7), RFC3986 (4), OIDC-Core (4), RFC7662 (3) |
| zitadel/oidc | 13 | 38 (39) | OIDC-Core (16), RFC6749 (4), RFC8628 (4), RFC8693 (4) |
| node-oidc-provider | 11 | 27 | OpenID4VCI (9), OIDC-Core-errata2 (5), RFC8705 (3), RFC9700 (2), RFC6749 (2) |

Union across the corpus is roughly **115 distinct `(spec, section)` pairs**, with real overlap
on the core: RFC 6749 §3.1.x/§4.1.x, RFC 8628 §3.x, RFC 7662 §2.x, RFC 8252 §7.3, and the OIDC
Core auth-request anchors appear in two or three repos each. Also present and not on the epic's
list: **RFC 6819** (threat model — fosite cites 7 sections of it) and **RFC 3986** (URI
comparison, 4 sections). RFC 7519 and RFC 8414 appear only at doc level, never with a section.

### Exported symbols within N lines of a citation

Exported = Go top-level `func`/method/`type`/`var`/`const` with a capital initial, **plus
exported interface methods and struct fields** (see §4 — this correction mattered); JS `export`
declarations. Numbers are strict / context-resolved / any-spec-mention.

| N | fosite (1,858 exported) | zitadel (2,057) | node (295) |
|---:|---|---|---|
| 3 | 2.7% / 2.9% / 3.5% | 2.7% / 2.7% / 3.1% | 0.0% / 0.0% / 0.0% |
| 5 | 3.8% / 4.0% / 4.7% | 4.8% / 4.8% / 5.4% | 0.0% / 0.0% / 0.0% |
| 10 | 5.6% / 5.8% / 6.4% | 8.0% / 8.0% / 9.7% | 0.3% / 0.3% / 0.3% |
| 20 | 8.6% / 8.6% / 9.7% | 12.5% / 12.5% / 16.0% | 0.3% / 0.3% / 0.3% |

**Why these N.** N=3 is "the citation is in this symbol's own doc comment" — the only distance
at which a `CITES_SPEC` edge is unambiguous. N=10 is a full Go doc comment (several prose lines
plus the signature) — the honest working value, and the one to quote. N=20 spans a doc comment
*and* a neighbouring declaration, so it over-attributes; it is included to show the curve is
flat, not clipped. Going 3→20 (a 6.7× wider window) only doubles coverage: citations are
genuinely clustered, not just narrowly missed.

For JS, exported-symbol proximity is misleading because node-oidc-provider exports late and
sparsely (295 exports over 19.8k LOC). Against *all* named definitions it reaches 1.8% at N=10
and 3.2% at N=20 — still the sparsest of the three by 3×.

### Where the citations are

They cluster hard in the protocol-flow files, which is the good news inside the bad:

- fosite: `oauth2.go` (28), `authorize_helper.go` (10), `authorize_request_handler.go` (6),
  `handler/openid/flow_{hybrid,implicit}.go` (4 each)
- zitadel: `pkg/op/server.go` (12), `pkg/client/rp/relying_party.go` (7), `pkg/oidc/token.go` (7)
- node: `lib/helpers/defaults.js` (16 — the config-documentation block, from which the docs site
  is generated, i.e. not symbol-adjacent), `lib/actions/credential.js` (14 — all OpenID4VCI)

## 3. The decision

The design offered a binary: density high → tier 1 is the backbone; density sparse → tier 1
collapses. The measurement lands between, and the honest read is **re-scope**:

**What survives, unchanged.**

- Tier 1 is *real and cheap*. ~195 raw citations, ~115 distinct section bindings, extracted by a
  ~350-line script that already exists (this one). Hours of work, high precision, zero
  adjudication. Do it.
- **The calibration-instrument argument in §2 of the design survives intact, and is now the
  strongest reason to do tier 1.** Comparing an intention harvest against the ~50 sections
  fosite's own comments name is a precision/recall computation over a few dozen ground-truth
  pairs; it does not need density, it needs *authority*, and the citations have that. Bead
  d1l.14 is the beneficiary.
- The sections that *are* cited are the load-bearing ones (RFC 6749 §3.1/§4.1, device flow,
  introspection, redirect-URI comparison), so the seed set is not a random 5%.

**What does not survive.**

- *"A large spec↔code mapping for free"* — **false.** 92–95% of exported symbols in the Go
  repos, and >99% in the JS repo, carry no citation within a doc comment. Tier 1 cannot be the
  coverage backbone for anything.
- *"`node-oidc-provider` cites constantly"* — **false, and it is the counter-example.** It is
  4× sparser than fosite, has section citations in 4 of 235 files, and what it does cite is
  dominated by OpenID4VCI (a recent feature), not by the core RFCs the epic targets. The design
  named this repo specifically; the reputation was wrong about it.
- *Test code as a cheap `TESTS_SPEC` source* — **dead.** 14 section citations across 65k lines
  of test code in all three repos combined. Bead **d1l.13** (bind conformance-test names to
  sections) must get its bindings from the OIDF conformance suite's own naming, not from the
  reference repos' tests. That is a finding this spike was not asked for and should be
  propagated.

**Consequent re-scoping, before anything is built:**

1. **d1l.10 (citation extractor): keep, demote, shrink.** Reframe from "backbone" to
   "seed + oracle". It must not gate anything downstream. This script is the prototype;
   productionising it is mostly the comment lexer (tree-sitter instead of the line heuristic)
   and emitting edges.
2. **Coverage for `identikey-oidc` rests on tier 2, not tier 1.** Nothing measured here touches
   tier 2 — annotations in the target are unaffected and remain cheap. `spec_coverage`
   (**d1l.11**), the tool the design calls "the one the agent will call every session", is
   therefore a tier-2 deliverable and can proceed independently of the extractor.
3. **d1l.12 (`spec_implementations` / `spec_consensus` / `spec_divergence`) is the bead that
   actually got harder.** Those tools need dense bindings *in the reference repos*, and
   citations supply 5–8% of them. They now depend on tier 3 (LM proposal) at full corpus scale,
   which is a materially larger and riskier scope than "only for what tiers 1–2 miss". Either
   re-estimate d1l.12 with that dependency explicit, or scope its first version to the ~58
   citation-bearing files, where it works today and where the flow logic actually lives.
4. **Cheap upside worth one bead: propagate along the graph.** A cited symbol's callees,
   implementers and same-file neighbours are strong candidates for the same section. Citations
   are 19–21% of *files* in the Go repos even though they are 6–8% of symbols — file-level
   coarse binding is 3× better than symbol-level, and structural propagation from a
   high-precision seed is exactly what the existing graph is for. This is a better spend than
   LM-proposing cold.

## 4. What would have made me conclude the opposite — and whether I checked

This spike was sent to test a plan and came back partially against it, which is the safer
direction; the risk is that I under-measured. Four ways the number could have been wrong low:

1. **A pattern list invented up front.** Checked — I sampled real comments in all three repos
   *before* fixing patterns and widened four times afterwards. The widenings added ~15% strict
   citations and quadrupled zitadel's OIDC-Core section count. I do not claim the list is
   complete, but the remaining misses are long-tail prose forms, not a whole family.
2. **Symbol detection blind to where citations live.** This was a real defect and the largest
   single correction. fosite's densest file, `oauth2.go` (28 citations), is one big
   `type … interface` block whose methods are indented and were invisible to `^func`. Adding
   indented exported interface methods and struct fields raised fosite's N=10 coverage from
   2.9% → 5.6% and zitadel's from 4.1% → 8.0%. **The fix moved the number in tier 1's favour,
   and I kept it.** It did not change the verdict.
3. **Citations living outside code.** They do: 44 anchored citations in fosite's markdown, 18 in
   node's, 5 in zitadel's. They are not symbol-adjacent and cannot produce `CITES_SPEC` edges
   without a separate doc-ingestion lane. Checked, excluded, noted.
4. **A too-narrow proximity window.** Checked at N = 3, 5, 10, 20 and the curve is flat
   (§2) — the symbols are not just outside the window, they are nowhere near one.

**Threshold.** "Most of the mapping is free" only reads as true if a majority — or at minimum a
large plurality, say >30% — of exported symbols get a binding at N≤10. The observed 5.6% / 8.0%
/ 0.3% is not close under any reading of "most". I did not pre-register that threshold before
running the numbers, which is a weakness of this spike; I record it so the next reader can
disagree with the threshold rather than with the counts.

**What would flip this.** If the LM tier turns out to bind the reference repos at high precision
cheaply, tier 1's demotion costs nothing and the epic shape is fine as written. That is now the
epic's load-bearing unknown, and it is unmeasured — the same failure mode this spike just
corrected, one tier over. It deserves its own spike before d1l.12 is estimated.
