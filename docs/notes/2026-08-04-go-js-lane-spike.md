# Go and JS lanes, end to end: what actually lands in the graph

**Bead:** MetaCoding-d1l.7 (SPIKE) · **Epic:** MetaCoding-d1l · **Date:** 2026-08-04
**Gates:** MetaCoding-d1l.2 (index the three reference OIDC implementations into a shared corpus)
**Design under test:** [`../design/architecture.md`](../design/architecture.md) lanes 1 and 3
**Companion spike:** [`2026-08-04-rfc-citation-density-spike.md`](./2026-08-04-rfc-citation-density-spike.md) (d1l.6)

Two of the three OIDC reference implementations are Go and the Go lane had never been exercised.
This is the measurement. Per the lesson of MetaCoding-hy6.16 — a whole re-scoring pass ran on a
graph with `CALLS = 0` and `REFERENCES = 0` because the SCIP lane had silently produced nothing —
every claim below is an **edge count by type queried out of the store**, not an exit code.

---

## Verdict in one paragraph

**Go via SCIP works, and works well — but not through any code path MetaCoding ships.** `scip-go`
is not a supported indexer: `ScipLanguage` is `typescript | python | php`, there is no Go entry in
`INDEXERS`, `detectScipLanguages()` can never return Go, and `--scip-language` rejects the token
`go`. Driving `scip-go` by hand and feeding the result through `--load-scip --scip-language ts`
(i.e. lying about the language) produces a genuinely good fosite graph: 2,879 symbols, **CALLS
3,274 / IMPLEMENTS 586 / REFERENCES 7,065**, with Go interface satisfaction landing as real
`IMPLEMENTS` edges. **JS via `scip-typescript` works through the shipped CLI with no changes at
all.** And **the tree-sitter fallback does not exist for either language**: `detectGrammar()`
returns `null` for `.go`, `.js`, `.mjs`, `.cjs`, so `metacoding index --scip false` on both repos
scans **0 files** and writes **0 symbols, 0 edges, 0 FTS tokens**. The epic's blast-radius
argument — "citation mining survives even if scip-go disappoints" — is **false as stated**.

The single most dangerous finding: **`metacoding index <fosite> --scip` exits 0 and writes a
completely empty graph.** That is the hy6.16 failure mode, reproducible today, in the exact repo
d1l.2 is about to index.

---

## 1. Method and provenance

### Repos (shallow clones, same commits as the d1l.6 spike)

| repo | commit | tip date | files |
|---|---|---|---|
| `ory/fosite` | `a5f0b09bf31c17297b25637bb3fec2ff7a55b159` | 2025-07-03 | 262 `.go` |
| `panva/node-oidc-provider` | `4550cc3361359e20c9b86dc4ab388a26cbbbf701` | 2026-08-03 | 413 `.js` |

`zitadel/oidc` was not indexed — it is the same Go lane as fosite and adds no new information
about lane mechanics. See §7.

### Indexers

- **`scip-go` v0.2.7.** Note the module moved: `github.com/sourcegraph/scip-go` now fails to
  install (`module declares its path as: github.com/scip-code/scip-go`). The working command is
  `go install github.com/scip-code/scip-go/cmd/scip-go@latest`. Ran in **8.9s** on fosite
  (35 packages, 776 implementations, 273 documents, 6.5 MB `.scip`). Toolchain: go1.25.6 darwin/arm64.
- **`scip-typescript` v0.4.0**, the copy already bundled in `node_modules`. **3.4s** on
  node-oidc-provider with `--infer-tsconfig` (413 documents, 5.8 MB `.scip`).

### Data dirs — ALL SANDBOX, NONE PRODUCTION

Every store below lives under the session scratchpad. **None of these is the user's production
location.** Production for this project is `$ORCHESTRATORS_ROOT/.metacoding/` (what `serve`, the
MCP tools and the eval harness read by default). Nothing in this spike touched it, and no running
`serve` process was contended with.

Sandbox root:
`/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/17d5c6e7-1a89-4a7a-95b1-93f79673de57/scratchpad`

| absolute path | what it is | complete? |
|---|---|---|
| `<root>/index.fosite.go.scip` | raw `scip-go` output, fosite (6.5 MB) | yes |
| `<root>/index.oidcprovider.ts.scip` | raw `scip-typescript` output, node-oidc-provider (5.8 MB) | yes |
| `<root>/data/go` | fosite, `--load-scip` of the scip-go index | **yes** — 2,879 symbols |
| `<root>/data/js` | node-oidc-provider, `--load-scip` of the scip-typescript index | **yes** — 12,617 symbols |
| `<root>/data/js-native` | node-oidc-provider, plain `metacoding index --scip` (CLI ran the indexer itself) | **yes** — 12,617 symbols, byte-identical stats to `data/js` |
| `<root>/data/go-native` | fosite, plain `metacoding index --scip` | yes, and **empty by construction** — 0 symbols (§4) |
| `<root>/data/go-ts-only` | fosite, `--scip false` (tree-sitter only) | yes, and **empty** — 0 symbols |
| `<root>/data/js-ts-only` | node-oidc-provider, `--scip false` | yes, and **empty** — 0 symbols |
| `<root>/repos/{fosite,node-oidc-provider}` | shallow clones | yes |

Every one of the six stores was opened read-only and queried after the fact; none is
half-written. The four zeros above are **measured results, not truncated runs** — each
corresponding `metacoding index` invocation ran to completion and printed its JSON summary.

### How the run differed from a production index

1. **`--data-dir` pointed at the sandbox** in every invocation; production was never opened.
2. **`--scip-language ts` was passed for a Go index** — a deliberate lie, because no honest value
   exists. See §3 defect (a).
3. **`--per-commit-identity` was not used.** Symbols are not SHA-scoped.
4. **The Go `.scip` was produced out-of-band**, by a `scip-go` binary installed into
   `<root>/bin/scip-go`, not by `runScip`. A production index cannot reproduce this today.
5. **Tests were indexed** (`scip-go` ran without `--skip-tests`), so `_test.go` symbols are in
   `data/go`.
6. **No dependencies were installed** for node-oidc-provider (no `npm install`), so
   `scip-typescript` resolved zero third-party types. This inflates `externalRefsSkipped`.

Reproduce:

```sh
S=<sandbox-root>
go install github.com/scip-code/scip-go/cmd/scip-go@latest   # GOBIN=$S/bin
(cd $S/repos/fosite && $S/bin/scip-go index ./... -o $S/index.fosite.go.scip)
bun src/cli/bin.ts index $S/repos/fosite --data-dir $S/data/go --repo fosite \
    --load-scip $S/index.fosite.go.scip --scip-language ts

bun src/cli/bin.ts index $S/repos/node-oidc-provider --data-dir $S/data/js-native \
    --repo node-oidc-provider --scip
```

---

## 2. Results: edge counts by type

### Lane 1 — SCIP

| | **fosite (Go)** `data/go` | **node-oidc-provider (JS)** `data/js`, `data/js-native` |
|---|---|---|
| documents | 273 | 413 |
| symbols upserted / distinct in store | 3,117 / **2,879** | 13,460 / **12,617** |
| `CALLS` | **3,274** | **2,557** |
| `REFERENCES` | **7,065** | **3,875** |
| `IMPLEMENTS` | **586** | **24** |
| `READS_FIELD` | 3,936 | 0 |
| `CONSTRUCTS` | 0 | 237 |
| `EXTENDS` / `OVERRIDES` / `IMPORTS` / `CONTAINS` / `TYPE_OF` / `RETURNS_TYPE` / `RAISES` / `WRITES_FIELD` / `USES_TRAIT` / `INJECTS` / `ANNOTATES` | 0 | 0 |
| total edges added | 14,928 | 6,731 |
| external refs skipped | 42,126 | 33,337 |
| external boundary edges | 0 | 0 |
| symbols by kind | method 1,450 · field 820 · function 266 · class 187 · interface 121 · namespace 35 | type_alias 11,066 · method 546 · function 516 · file 413 · field 40 · class 36 |
| indexer wall time | 8.9s | 3.4s |
| store-load wall time | 169s | 222s |

`data/js-native` (CLI drove `scip-typescript` itself) is identical to `data/js` on every number.
The shipped JS path needs no intervention.

### Lane 3 — tree-sitter fallback

| | fosite (Go) `data/go-ts-only` | node-oidc-provider (JS) `data/js-ts-only` |
|---|---|---|
| files scanned | **0** | **0** |
| symbols | **0** | **0** |
| edges | **0** | **0** |
| FTS tokens | **0** | **0** |

---

## 3. The Go lane, in detail

### It produces good qualified_names

`scip-go` names symbols by Go package FQN, e.g.

```
scip-go gomod github.com/ory/fosite a5f0b09bf31c `github.com/ory/fosite`/Fosite#WriteAccessError().
```

which `qualifiedNameOf()` renders as:

```
github.com/ory/fosite.Fosite.WriteAccessError
github.com/ory/fosite.Fosite.writeJsonError
github.com/ory/fosite.AccessRequest.GetGrantTypes
github.com/ory/fosite.EnforcePKCEProvider.GetEnforcePKCE
github.com/ory/fosite.Config.GetTokenEndpointHandlers
```

These are stable, unambiguous, and human-legible. The `file` column is populated correctly from
`Document.relative_path` (`access_error.go`, `config.go`, `config_default.go`, …).

### Real `CALLS` edges

```
github.com/ory/fosite.Fosite.WriteAccessError  ->  github.com/ory/fosite.Fosite.writeJsonError
github.com/ory/fosite.Fosite.writeJsonError    ->  github.com/ory/fosite.ErrorToRFC6749Error
github.com/ory/fosite.Fosite.writeJsonError    ->  github.com/ory/fosite.RFC6749Error.WithLegacyFormat
github.com/ory/fosite.Fosite.NewAccessRequest  ->  github.com/ory/fosite/i18n.GetLangFromRequest
```

Cross-package calls resolve (`…/i18n.GetLangFromRequest`).

### Real `IMPLEMENTS` edges — the standout result

`scip-go` computes Go interface satisfaction (776 implementations at index time) and emits it as
`is_implementation` relationships, which the loader turns into `IMPLEMENTS` at **both** the type
and the method level:

```
github.com/ory/fosite.AccessRequest                    -> github.com/ory/fosite.AccessRequester
github.com/ory/fosite.AccessRequest                    -> github.com/ory/fosite.Requester
github.com/ory/fosite.AccessRequest.GetGrantTypes      -> github.com/ory/fosite.AccessRequester.GetGrantTypes
github.com/ory/fosite.Config                           -> github.com/ory/fosite.TokenEndpointHandlersProvider
github.com/ory/fosite.Config.GetTokenEndpointHandlers  -> github.com/ory/fosite.TokenEndpointHandlersProvider.GetTokenEndpointHandlers
github.com/ory/fosite.Fosite.WriteAccessError          -> github.com/ory/fosite.OAuth2Provider.WriteAccessError
```

Go's structural typing means this information is *not* recoverable syntactically — there is no
`implements` keyword to grep. Getting 586 of these for free is the strongest single argument for
wiring the Go lane properly: it is exactly the substrate d1l.3 (CTKR role-equivalence onto Rust
traits) needs.

### Defects, in severity order

**(a) There is no Go lane. Every step above was manual.**
`src/scip/run.ts`: `export type ScipLanguage = "typescript" | "python" | "php"`, and `INDEXERS`
has no Go entry. `src/cli/main.ts`: `detectScipLanguages()` only ever pushes `typescript` and
`python`; `normalizeScipLang()` throws on anything but `ts|typescript|py|python|php`. Nothing in
the repo can invoke `scip-go`.

**(b) `language` is recorded as `ts` for all 2,879 Go symbols.** Forced by (a) — `ts` was the
least-wrong of three wrong options. Any downstream language filter, per-language metric, or
language-conditioned CTKR comparison will silently mis-bucket the whole Go corpus.

**(c) `filePathOf()` returns `null` for 100% of Go definitions** (11,357 defs probed, 0 with a
file segment). `SOURCE_EXT` in `src/scip/symbol.ts` has no `.go`, but adding it would not help:
`scip-go` embeds no file path in the symbol string at all, exactly like `scip-php`. Consequence:
a Go `qualified_name` is `pkg.Type.Method`, **not** the `file::Type::method` shape every other
lane uses. Nothing to reconcile with today (there is no Go tree-sitter lane), but any cross-repo
or cross-language matcher that assumes qn shape will break on Go.

**(d) Package-level `namespace` symbols collapse across files.** 273 package-declaration
definitions (one per document) map to 35 distinct qns — one per package — so `file` on those
nodes is last-write-wins and effectively arbitrary (`github.com/ory/fosite` reports
`session_test.go`). Benign for `CALLS`/`IMPLEMENTS`; a trap for anything file-scoped.

**(e) 42,126 external references dropped, with no boundary node.** `scip-php` has a Pass-2b
mechanism (`externalBoundaryEdges`) that synthesizes a node for out-of-index-but-interesting
targets; Go gets 0. Every call into the Go stdlib, `golang.org/x/…`, or a dependency is invisible.
For fosite that includes `net/http`, `crypto/*`, `net/url` — a large share of what an OAuth server
actually *does*.

**(f) Tests are in the corpus.** No `--skip-tests`. `data/go` contains `_test.go` symbols mixed
with production ones and there is no marker to separate them. d1l.6 found the reference repos'
tests are useless as a citation source; they will still distort symbol-count denominators here.

---

## 4. The empty-graph trap (hy6.16, reproduced)

```
$ bun src/cli/bin.ts index <fosite> --data-dir <sandbox>/data/go-native --repo fosite --scip
error: no files got indexed. To fix this problem, make sure that the TypeScript projects [...]
{ "treeSitter": { "filesScanned": 0, "symbols": 0, "edges": 0, "tokens": 0 },
  "scip":       { "documents": 0, "symbolsUpserted": 0, "edgesAdded": 0 } }
EXIT=0
```

Mechanism: fosite ships a `package.json` and a `tsconfig.json` (for its conformance tooling), so
`detectScipLanguages()` returns `["typescript"]`. `scip-typescript` finds no TS and fails; the
failure is caught, logged to stderr as a one-line `scip-typescript failed: …`, and the run
**reports success**. Tree-sitter contributes nothing because `.go` has no grammar dispatch. The
result is a store with zero of everything and a green exit code.

`resolveScipWanted()` already refuses to index when *no* SCIP binary is resolvable, with a good
error explaining that a tree-sitter-only graph "is almost not worth building." The guard does not
fire here, because a binary *was* resolvable — it just had nothing to do. **The guard needs to be
on the outcome, not the availability.**

---

## 5. The JS lane, in detail

Works through the shipped CLI with no arguments beyond `--scip`. `scip-typescript`'s
`--infer-tsconfig` is added automatically when the target has no `tsconfig.json`, which is the
case for node-oidc-provider, and it indexes plain ESM JavaScript happily: 413 documents for 413
`.js` files — full coverage.

qualified_names are the canonical `file::member` shape:

```
lib/helpers/attention.js::info
lib/helpers/errors.js::InvalidToken
lib/helpers/errors.js::OIDCProviderError
lib/consts/client_attributes.js::CHOICES
```

`CALLS` and `IMPLEMENTS` samples:

```
CALLS       lib/helpers/attention.js::info                 -> lib/helpers/attention.js::stdout
CALLS       lib/helpers/attention.js::warn                 -> lib/helpers/attention.js::stderr
IMPLEMENTS  lib/helpers/errors.js::InvalidToken            -> lib/helpers/errors.js::OIDCProviderError
IMPLEMENTS  lib/helpers/errors.js::InvalidClientMetadata   -> lib/helpers/errors.js::OIDCProviderError
IMPLEMENTS  lib/helpers/errors.js::SessionNotFound         -> lib/helpers/errors.js::InvalidRequest
```

### Defects

**(g) 88% of the JS symbol table is noise.** 11,066 of 12,617 symbols are `type_alias` — inferred
types for individual properties of data literals (`lib/consts/dev_keystore.js::keys0`, `::alg0`,
`::d0`, `::dp0`, `::dq0`, …). Any metric normalised by symbol count (citation density per symbol,
hom-profile distributions, coverage percentages) will be off by roughly an order of magnitude on
JS relative to Go. Either filter `type_alias` at the loader or normalise per `function|method|class`.

**(h) `IMPLEMENTS` is 24 on JS vs 586 on Go.** This is a language-shape difference — Go interface
satisfaction is dense and computed; JS has prototype chains and 36 classes total — not a bug. But
it means **`IMPLEMENTS` density is not comparable across the Go and JS members of this corpus**,
and any consensus/divergence metric (d1l.12) that leans on it will read the language, not the spec.

**(i) `externalRefsSkipped` = 33,337 with no `node_modules` installed.** A production index should
`npm install` first; the numbers here understate what a real JS index would resolve.

---

## 6. The tree-sitter fallback does not exist for Go or JS

`src/extractor/walker.ts`:

```ts
type Grammar = "typescript" | "tsx" | "python" | "php";

export function detectGrammar(filename: string): Grammar | null {
  if (filename.endsWith(".d.ts")) return null;
  if (filename.endsWith(".tsx")) return "tsx";
  if (filename.endsWith(".ts")) return "typescript";
  if (filename.endsWith(".py")) return "python";
  if (/* .php .phtml .inc .module .install .theme .profile .engine */) return "php";
  return null;
}
```

`.go`, `.js`, `.mjs`, `.cjs`, `.jsx` all return `null`. The walker never opens them, so:

- no tree-sitter symbols,
- no behaviour edges (`extractEdgeCandidates` is only reached per parsed file),
- **and no FTS tokens** — the tree-sitter walker is the *only* writer of the `tokens` table.

So for Go and JS, lanes 3 **and 4** are both dark. Measured: `filesScanned: 0`, `tokens: 0` on
both repos.

The blockage is dispatch, not grammars. `node_modules/tree-sitter-wasms/out/` already ships
`tree-sitter-go.wasm` and `tree-sitter-javascript.wasm`. What is missing is (i) the extension
entries in `detectGrammar`, and (ii) a per-language extractor module — `walker.ts` dispatches to
`extractPython` / `extractPhp` / `extractTypeScript` and nothing else. JS is plausibly cheap
(point `.js`/`.mjs`/`.cjs` at the existing `extractTypeScript`, since the JS grammar's node types
are close to a subset of TypeScript's — **unverified, worth 30 minutes**). Go needs a new
extractor.

**Correction to the epic's blast-radius argument.** d1l.7's premise was: "Tree-sitter fallback
covers citation mining even if scip-go disappoints, which caps the blast radius." That fallback is
not there. The saving grace is that d1l.6's citation measurement never used it — it used a
standalone lexer in `scripts/spike-citation-density.ts` that walks `.go/.js/.mjs/.cjs/.ts` itself.
So **d1l.10's extractor can follow that pattern and reach Go and JS comments without the
tree-sitter lane**, but it must own its own file walk; it cannot ride the extractor, and it will
not get FTS tokens for free.

---

## 7. What the epic must now assume

1. **d1l.2 cannot proceed on Go as things stand.** The plain CLI path on fosite produces an empty
   graph and exits 0. Either wire a real Go lane, or drive `scip-go` out-of-band per repo and
   ingest with `--load-scip`, and *assert non-zero CALLS/IMPLEMENTS after every ingest*. A
   follow-up bead should add `go` to `ScipLanguage`/`INDEXERS`/`detectScipLanguages`/
   `normalizeScipLang` plus a `"go"` language code — this is a small, well-bounded change and the
   payoff (586 free `IMPLEMENTS` on one repo) is large.
2. **`metacoding index` must fail loudly on a zero-symbol outcome.** The existing
   `resolveScipWanted` guard checks binary availability; it should also check that the completed
   index produced symbols, and non-zero `CALLS`/`REFERENCES` when SCIP was supposed to run. This
   is the concrete regression-catching evidence for both hy6.16 and this spike.
3. **Go qualified_names are package-FQN shaped; JS/TS/PHP are file-shaped.** No cross-language
   matcher may assume a common shape. d1l.3 and d1l.12 must key on structure, not on string form.
4. **`language` will read `ts` for Go symbols** until (a) is fixed. Do not build a language filter
   on the current corpus.
5. **Symbol counts are not comparable across Go and JS** (88% `type_alias` inflation on JS), and
   **`IMPLEMENTS` density is not comparable either** (Go interfaces vs JS prototypes). Normalise
   to `function|method|class`, and treat cross-language edge-density comparisons as measuring the
   language until proven otherwise.
6. **Go stdlib and dependency calls are invisible** (42k dropped refs, no boundary node). Any
   "what does fosite depend on to implement §4.1.3" question is unanswerable on the current Go
   graph. PHP's Pass-2b boundary mechanism is the template if this matters.
7. **Citation mining (d1l.10) must own its file walk.** No tree-sitter, no FTS for Go or JS.
8. **Budget ~3–4 minutes of store-load per reference repo**, not per corpus. The indexers are fast
   (3–9s); `loadScip` is the cost (169s Go, 222s JS). A three-repo corpus is ~10 minutes of
   ingest — fine, but not interactive.

---

## 8. Not done

- **`zitadel/oidc` was not indexed.** It is the same Go lane as fosite with the same manual
  `scip-go` workaround; the lane mechanics are established and re-running them would add no new
  information about the *lane*. It should still be indexed as part of d1l.2 for the corpus itself,
  and its numbers checked against fosite's.
- **The "point `.js` at `extractTypeScript`" hypothesis is untested.** Stated as a cheap next step,
  not as a finding.
- **No fix was implemented.** This is a spike; every defect above is described precisely enough to
  be filed and acted on, and none was papered over.
