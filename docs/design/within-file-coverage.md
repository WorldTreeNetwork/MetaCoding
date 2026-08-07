# Within-file coverage: the residual is a census, not a claim

**Status:** proposed, 2026-08-06. Amends [coverage-claims.md](./coverage-claims.md), which names this joint as its own weakest point (`coverage-claims.md:100`, `:146`).
**Origin:** Duke — fresh-architect attack on coverage-claims' open question.
**Beads:** proposed below; touches `9jt`, `ev9`, `ugm`, `hy6.16`, `5fi`, `1xd`, `vju`, `mhv`.

---

## The question, restated precisely

`coverage-claims.md:100` states the residual honestly:

> *"even a derived region rests on 'the lane, having produced a document for f, examined all of f.' Not checkable. So claims move the blindness from 'which files' — invisible today — to 'how thoroughly within a file,' still invisible."*

The question is whether the within-file residual admits the same treatment as the file-level one. **It does not, and the reason is structural, not a matter of effort.**

A file-level coverage claim works because the domain is **finite, known, and indexable by the query**. The manifest holds the canonical sorted file list; every file is in the region bitmap or it is not; and a query about symbol `X` can ask `claim ∌ (X.file, CALLS)` because it knows `X.file`. The claim is a *total function over a domain the reader already holds*.

Within a file there is no such domain. The honest within-file question is *"could any syntactic form in this file have carried a `CALLS` fact that the extractor did not emit?"* — and answering it requires a mapping from syntactic form to fact kind, which is a statement about the **grammar's semantics**, not about the artifact. Nothing in the artifact derives it. Any scheme that supplies it is a declared table, and `coverage-claims.md:147` already names declared tables as the highest-damage-per-byte failure in the design.

**So the answer is candidate direction 5**: accept the blindness and make it *enumerated* rather than invisible — mechanized by direction 1 restricted to a **set, never a ratio**, with direction 2 demoted from "coverage measure" to "a correctness fix to a derivation coverage-claims already promises and cannot currently keep." Directions 3 and 4 die, for reasons given below.

This is a weaker answer than coverage claims. It is not a claim, it does not produce a truth value, and no query consults it. It converts a blindness nobody can see into a blindness a maintainer can read, count, and rank. That is worth shipping, and calling it anything more would be the overselling `coverage-claims.md:100` warns about.

---

## The property

> **Every syntactic form that occurred in a sealed entry's inputs and produced nothing is nameable from that entry's own recorded inputs, with its occurrence count and its sites. The residual is enumerated; it is never a number, never a threshold, and never a verdict.**

Applying the well-formed-red test from `iteration-methodology.md:38` — *could the system satisfy this and still be wrong in the way that motivated it?*

**Yes, in one specific way, and it must be stated up front.** The property covers **silence**, not **wrongness**. A form that is claimed by a rule which emits the *wrong* fact satisfies the property completely. Fixture 2 below is exactly that case: an anonymous class expression whose methods are emitted as methods of the *file*. The residual census names `class` as an unclaimed form; it says nothing about the false `CONTAINS` edges standing next to it.

That residual-of-the-residual has no answer here either, and I am not going to invent one. It is the same gap `graph-as-cache.md:164` already records ("a correct key over a broken extractor — every input hashed, every seal valid, every edge wrong. **Not caught**").

---

## Two real within-file blind spots, measured

Both were reproduced against the shipped extractors at `68125f1`, by parsing with `src/extractor/parser.ts` and running the shipped `extractPhp` / `extractTypeScript` / `extractEdgeCandidates`.

### Fixture 1 — PHP 8 constructor property promotion: 376 occurrences in farmOS, zero symbols, and the reads vanish with them

```php
class Svc {
  const DEFAULT_MODE = 'fast';
  private $handler = self::DEFAULT_MODE;
  public function __construct(private LoggerInterface $logger, protected Cache $cache) {}
  public function go() { return $this->logger; }
}
```

Parses clean — `hasError: false`. Emitted symbols:

```
file:a.php | class:a.php::Svc | field:a.php::Svc::handler | method:a.php::Svc::__construct | method:a.php::Svc::go
```

No `field` for `logger`, no `field` for `cache`.

- `src/extractor/php.ts:132-179` — `recognizeDeclaration` switches on `namespace_definition`, `class_declaration`, `trait_declaration`, `interface_declaration`, `enum_declaration`, `function_definition`, `method_declaration`, `enum_case`. The grammar node is `property_promotion_parameter` (confirmed in the parse tree: `(formal_parameters (property_promotion_parameter visibility: (visibility_modifier) type: (named_type (name)) name: (variable_name (name))))`). Not in the switch.
- The consequence is not merely a missing node. `go()` contains `$this->logger`, which `src/extractor/edges.ts:1138-1175` turns into a `READS_FIELD` candidate targeting short name `logger`, kinds `["field"]`. `isDrupalEntityField` (`edges.ts:1074-1076`) returns false because the name does not start with `field_`, so `externalFallback` is unset, so `src/extractor/walker.ts:326-329` finds no target and **drops the candidate silently**. The dependency edge disappears with the field.
- **Measured on farmOS** (`/Users/dukejones/work/WorldTree/farmos-src`, 789 PHP files by `detectGrammar`): **376 `property_promotion_parameter` occurrences.** Every one is a declared service dependency of a modern Drupal/Symfony class, and none of them is in the graph.

### Fixture 2 — PHP 8 attributes: 587 occurrences in farmOS, zero edges, and the declared capability table says otherwise

- `src/extractor/edges.ts:1040-1068` — `walkPhp` dispatches on exactly six node types: `class_declaration`, `interface_declaration`, `assignment_expression`, `augmented_assignment_expression`, `member_access_expression`, `member_call_expression`. There is no `attribute_group` case, no `object_creation_expression` case, no `throw_expression` case, no `return_type` case.
- Therefore the tree-sitter PHP lane emits **`CONTAINS`, `EXTENDS`, `IMPLEMENTS`, `USES_TRAIT`, `READS_FIELD`, `WRITES_FIELD` — and nothing else.**
- `graph-as-cache.md:81` states, without language qualification: *"the tree-sitter lane emits `CONTAINS/EXTENDS/IMPLEMENTS/USES_TRAIT/READS_FIELD/WRITES_FIELD/CONSTRUCTS/RAISES/RETURNS_TYPE/ANNOTATES/TYPE_OF`."* For PHP, **five of those eleven are false**.
- Measured on farmOS: `attribute_group` **587**, `object_creation_expression` **472**, `throw_expression` **47**, `class_constant_access_expression` **393**, `const_declaration` **35**.

This is the design's own fake-it #2 (`coverage-claims.md:147`: *"a wrong row in the static capability table does maximum damage per byte"*) — **already true, today, in the document the implementation is about to be built from.** Under coverage claims, a `complete` `ANNOTATES` claim would be minted over all 789 farmOS files, and a query asking what annotates a Drupal plugin class would receive an authoritative empty answer where 587 attribute applications exist. That is `hy6.16` with the new design's blessing, which is the failure mode `coverage-claims.md:95` warns about.

### Three more, for completeness (same probe run)

3. **TS arrow-function declarations.** `export const useThing = (a) => {...}` parses as `lexical_declaration > variable_declarator > arrow_function`. `src/extractor/typescript.ts:117-141` has no case for any of the three. Zero symbols, zero edge candidates. **1,285 `arrow_function` occurrences in MetaCoding's own `src/`.**

4. **Anonymous class expressions — misattribution, not omission.** `export default class { hidden() {} }` parses as `(export_statement value: (class body: (class_body (method_definition …))))`. Node type is `class`, not `class_declaration`, so `recognizeDeclaration` returns null (`typescript.ts:138-140`), so `walk` recurses at `typescript.ts:112-114` **with `parent` still the file symbol**. Emitted:

   ```
   file:a.ts | method:a.ts::hidden
   ```

   A `method` whose `CONTAINS` parent is the file. The same shape fires for object-literal methods: `const o = { render() {} }` emits `method:a.ts::render` contained by the file. The graph asserts a containment relation that does not exist in the source. **This is the case the whole scheme handles worst** — see fake-it #1 and "handles worse" #2.

5. **`property_declaration` swallows its own initializer's tokens.** `src/extractor/php.ts:86-90` returns *without recursing into children*. In fixture 1, `private $handler = self::DEFAULT_MODE;` contributes the token `handler` but **not** `DEFAULT_MODE` — confirmed by the token dump, where `DEFAULT_MODE` appears once (from the `const_declaration`) despite occurring twice in the source. The token table is the repo's advertised index over *the AST's blind spots*, so a blind spot in the blind-spot index is a compounding one. The comment on `php.ts:89` — *"property bodies carry no further declarations worth descending into"* — is true about declarations and false about tokens.

6. **No ERROR check exists anywhere.** `grep -rn "hasError|isMissing" src/` returns **zero hits in non-test code**. `src/extractor/walker.ts` checks only `if (!tree)`. Measured on a PHP file with one broken method: `hasError: true`; class `Good` and its method survive; class `Broken`'s method is gone; **class `After` is absent entirely**, absorbed into the ERROR subtree. Nothing in the pipeline observes any of it.

   This matters directly to coverage claims. `coverage-claims.md:77` defines the tree-sitter region as *"the set of files `walkFs` actually parsed without error."* **That derivation does not exist in the code**, and the only quantity available at that call site is `tree != null`, which is true for the broken file above. Implemented naively, the design's flagship derived region would be a declaration.

---

## The mechanism

Three parts. Two are cheap and honest; the third is the one that carries the weight, and it is a census, not a claim.

### Part A — grammar identity in the key (prerequisite; nothing else is sound without it)

`package.json:84` pins `"tree-sitter-wasms": "^0.1.13"` — a caret range. `src/extractor/parser.ts:32-35` loads `tree-sitter-{grammar}.wasm` from whatever resolved. A grammar upgrade changes every parse tree, every symbol, every edge, and every number below — and moves no key.

That is `graph-as-cache.md:165` instantiated: *"an input left out of the key is a dimension the cache is blind to."* Fix: pin the version exactly, and fold `sha256` of each loaded `.wasm` into the layer-2 key alongside `extractor_version`.

This is a prerequisite, not an enhancement. **Constraint 5 requires that anything measured be recomputable by a reader from the artifact's recorded inputs.** Without the grammar digest, nothing derived from a parse tree is recomputable — including today's graph.

### Part B — ERROR / MISSING accounting, recorded as ranges

At the parse site in `walker.ts`, after `parse`, record per file: `has_error`, and the byte ranges of every `ERROR` node and every `isMissing` node. Store the ranges in `MANIFEST.json`, keyed by manifest file index.

- **Ranges, not a ratio.** No `error_bytes / total_bytes` figure is computed anywhere, because constraint 3 forbids it and because a ratio invites a gate.
- This makes `coverage-claims.md:77` true: the tree-sitter region becomes *"files parsed with zero ERROR and zero MISSING nodes"*, derived from the tree. Files with damage are recorded `outcome: partial` with the damaged ranges enumerated — which the claim schema (`coverage-claims.md:63-69`) already represents, since `region ⊂ attempted`.

**Be honest about what this catches: on real code, almost nothing.** Measured: **0 of 789 farmOS PHP files** and **0 of 92 MetaCoding TS files** have any ERROR or MISSING node. Its value is not as a coverage measure. Its value is that it is the *only* signal that fires when a grammar is too old for the source it is parsing — a PHP 8.4 feature against an 8.2-era grammar, a new TS syntax — which is precisely the silent-and-catastrophic case, and it is nearly free.

### Part C — the unclaimed-form census (the substance)

**Derived at runtime from dispatch, not from any table.**

Two sets per (file, grammar), both integer `typeId` sets over the grammar's node-type alphabet:

- **`seen`** — every named node type that occurred. Derived from the tree by a cursor walk. Extractor-independent; no extractor code needs to be trusted for this half.
- **`emitted_from`** — every node type that was the `node` argument at a site that actually pushed a `Symbol`, an `Edge`, a `TokenRow`, or an `EdgeCandidate`. Recorded **at the emission site**, not at the switch.

The residual is `seen \ emitted_from`, plus, for types in both, the pair `(occurrences, emissions)`.

Three properties this shape has and the rejected alternatives do not:

1. **Nothing is declared.** Constraint 1 is satisfied hard: there is no capability table, no list of "forms we handle," no version string a lane vouches for. `emitted_from` is the set of types the run *demonstrably produced output from*, on this corpus. A lane cannot claim a form it did not exercise.

2. **Recording at emission, not at dispatch, is load-bearing.** Several rules dispatch and then emit nothing: `nameOf` returns null for an unnamed declaration (`typescript.ts:143-147`); `recognizeDeclaration`'s `case "assignment"` returns null when `!insideClass` (`python.ts:152-159`); `php.ts:87` calls `emitProperties` only when `insideClass`. Instrumenting the switch would mark those types **claimed while emitting nothing** — a false claim minted by the measurement instrument itself. Emission-site recording is the difference between a derivation and a decoration.

3. **It is a set, so there is nothing to threshold.** The reader's question is never *"is the residual large?"* — it is *"is `attribute_group` in it, and how often?"* Constraint 3 is satisfied by construction: no ratio exists, so no build can fail on one.

**Payload.** Two bitmaps per file over the grammar's node-type alphabet (tree-sitter PHP: ~250 types → 32 bytes each; measured distinct *named* types actually occurring in farmOS: 104). At 789 files that is under 60 KB before compression, and it aggregates to a per-entry ranked list of maybe 80 rows — the shape a maintainer actually reads:

```
farmos@<sha>  php  unclaimed forms, by occurrence:
    19795  string                            (…noise: 82 of 104 types are unclaimed)
    14945  argument
     ...
      587  attribute_group          ← PHP 8 attributes; Drupal declares every plugin this way
      472  object_creation_expression ← `new Foo()`; PHP lane emits no CONSTRUCTS at all
      393  class_constant_access_expression
      376  property_promotion_parameter ← every promoted constructor dependency
       47  throw_expression
       35  const_declaration
```

**It goes in `MANIFEST.json` and never in the key.** Unlike a file-level claim — whose region varies with which SCIP documents happened to succeed, which nothing else keys — the census is a *pure function of* `(file digests, grammar wasm digest, extractor_version)`, all three of which are already in the key once Part A lands. Putting it in the key would add zero discrimination and cost cache hit rate. This redundancy is a feature: **a fact that cannot move the key cannot become a gate**, which structurally closes fake-it #4 below.

---

## What it costs

Measured on this machine at `68125f1`, medians of 5 runs after 2 warm-up rounds, using the shipped `parser.ts`, `extractPhp`/`extractTypeScript`, and `extractEdgeCandidates`:

| corpus | baseline (parse + extract + edges) | + full cursor census pass | overhead |
|---|---|---|---|
| MetaCoding `src/`, 92 `.ts` files, 268,546 nodes | **219 ms** | **268 ms** | **+49 ms (22%)** |
| farmOS `farmos-src/`, 789 PHP files | **333 ms** | **420 ms** | **+88 ms (26%)** |

The 219 ms baseline reproduces `coverage-claims.md:38`'s 269 ms for 92 files, so the two measurements are commensurable.

**Constraint 4's question — what does a second pass over every AST multiply to on farmOS? 88 ms**, against a sealed rebuild that `coverage-claims.md:47` puts at ~1 s once the write path is fixed. That is ~9% of the rebuild and it is the *pessimistic* figure: this measures a fully independent cursor traversal. The `seen` half can instead be folded into the recursion the extractors already perform (`typescript.ts:112`, `python.ts:125`, `php.ts:127` visit every named child anyway), at roughly one array increment per node.

Two caveats on that optimization, both real:

- The extractor walks traverse `namedChildren` only, so a folded implementation sees named `ERROR` nodes but can miss anonymous `MISSING` nodes. Keep Part B on the cursor.
- `php.ts:86-90` returns without recursing, so a folded census would *itself* be blind to the subtree at blind spot 5 above. **Ship the independent cursor pass first and pay the 88 ms**; fold it in later only with a fixture proving the two agree.

---

## Ranking the candidate directions

| direction | verdict |
|---|---|
| **5 — enumerate the blindness** | **Adopted.** It is the only one that survives constraints 1–3 intact, and it is the direct analogue of `graph-as-cache.md:165`'s answer to a recipe that lies about its identity: record the full input list so a reader sees what was *not* keyed. |
| **1 — node coverage** | **Adopted as a set, dead as a ratio.** Two separate kills. (a) *"Visited"* is vacuous: `collectTokens` runs on every named node in all three extractors, so a visited-fraction reads ~100% today while missing arrow functions, promoted properties, and attributes. (b) *"Claimed"* as a fraction dies on constraint 2 immediately — name a codebase where the number is honestly low and the extractor is fine: **any implementation-heavy file**. One 200-statement function is thousands of `expression_statement`/`binary_expression`/`integer` nodes no extractor should ever claim. Measured: 82 of farmOS's 104 distinct named types are unclaimed and the top four by volume are `string`, `argument`, `arguments`, `array_element_initializer`. The set survives because the reader indexes into it by name; the ratio dies because it can only be compared to a threshold. |
| **2 — ERROR / MISSING accounting** | **Adopted, demoted.** Cheap, already available, and it repairs a derivation `coverage-claims.md:77` promises without code behind it. But it catches **0 of 789** farmOS files and **0 of 92** MetaCoding files. It is grammar-version insurance, not a coverage measure, and describing it as one would be a second `NO_RELATIONAL_EDGES` — a quantity that is honestly zero on healthy subjects. |
| **3 — capability table at syntax-form granularity** | **Dead.** It is not "the same idea one level down"; it collapses into declaration and gets *worse* with granularity. The edge-kind table is 11 kinds × 3 languages ≈ 33 hand-maintained cells, and `coverage-claims.md:147` argues its smallness is what makes it dangerous. A form-level table is ~250 node types × 11 kinds per grammar ≈ 2,750 cells per language, hand-written, unfixtured, and — since it would encode *"could this form have carried this fact"* — asserting things about grammar semantics that no artifact derives. Direct evidence of the failure mode: **the 33-cell table is already wrong**, claiming five edge kinds for PHP that `edges.ts:1040-1068` cannot emit. Scaling a table that is wrong at 33 cells to 2,750 is the wrong direction. |
| **4 — differential coverage between lanes** | **Dead as a manifest field; valuable, relocated.** It only helps where both lanes ran, and where both ran you would rather trust SCIP. `coverage-claims.md:99` already puts cross-lane comparison in the right slot: *"record as an observation, never as a gate."* Its real value is somewhere else entirely — as a **development instrument for the extractors**, run in CI over a fixture corpus. It is the only mechanism proposed here that catches blind spot 4 (misattribution): SCIP places `hidden` inside an anonymous class; tree-sitter places it inside the file; the symbol ids disagree, mechanically and visibly. That is worth building, in `src/extractor/`'s test suite, not in `MANIFEST.json`. |

---

## How would we fake this design?

1. **Emission-site recording is per-type; the harm is per-occurrence — and I refuted my own metric with constraint 2's method.** A type that emits *sometimes* is marked claimed by its successes. `class_declaration` with a name emits; anonymous, it does not (`typescript.ts:143-147`); the type is claimed either way. The `(occurrences, emissions)` pair is supposed to expose that — and it does not survive constraint 2. Name the codebase where the deficit is honestly large and the extractor is fine: **any Python codebase**, because `python.ts:152-159` only emits `field` for a class-level *annotated* `assignment`, so module-level and unannotated assignments are legitimate non-emissions and `assignment` shows `occurrences ≫ emissions` on healthy code. The deficit is a count used as a proxy for capability, and a proxy is refutable by finding a subject where the count is honestly bad. **So the deficit must never be a verdict.** It is a census row, ranked, read by a person. I am recording this because it is the strongest attack available on my own scheme, and it is the same attack that killed `NO_RELATIONAL_EDGES` (`graph-as-cache.md:28`).

2. **A wrong-but-valid parse — the case with no signal at all.** PHP interleaved with HTML, Twig, a `.module` file with a construct the grammar accepts under the wrong rule. `hasError` is false, every occurring type is claimed, output is wrong. Neither Part B nor Part C fires. This is the class that would most plausibly bite farmOS, given `walker.ts` routes `.module`/`.install`/`.theme`/`.profile`/`.engine` through the PHP grammar.

3. **Node *type* is coarser than semantic role.** `call_expression` (8,986 occurrences in MetaCoding's `src/`) covers ordinary calls, factory construction, and DI container lookups. A type that is claimed for one meaning is claimed for all of them. The census cannot see distinctions that live below the type.

4. **Someone will threshold the census.** A residual has a size, and a size invites a gate. This is the exact pressure `coverage-claims.md:149` predicts. Structural mitigation, not a rule: the census is **not in the key**, and Part A makes that principled rather than arbitrary — every input it depends on is already keyed, so including it would add nothing. A fact that cannot move a key cannot silently become a build gate. It is a soft defence and it will be tested.

5. **The census can be gamed by widening emission, not coverage.** A rule that emits a junk `TokenRow` for a node type moves it from `seen \ emitted` into `emitted`, and the residual shrinks with no improvement in the graph. Since the residual is not scored, there is no gradient toward this — but the moment anyone puts a number on it, there is. See #4.

6. **My own measurement is one machine, one run family, two corpora.** The 88 ms farmOS figure is a warm-cache, single-process median over an in-memory file list. It excludes the store write path entirely, which `coverage-claims.md:38-43` shows is where the real cost lives. The claim "9% of a 1 s rebuild" inherits every uncertainty in the 1 s estimate, and `coverage-claims.md:150` explicitly marks that estimate as a demonstrated floor, not a rebuild cost.

---

## What this handles worse than today

1. **It adds a number nobody asked for to a design that just deleted a ladder for having numbers.** `coverage-claims.md:141` rejects thresholding a coverage ratio precisely because "there is no number to tune, which is the point." The census reintroduces counts — bounded to a census row, unranked by any policy, unkeyed — but they are counts, and the previous four rounds of this project each began with a defensible count.

2. **It makes the misattribution case *less* visible by making the omission case more visible.** A maintainer reading a clean-looking residual will read it as "the extractor sees this corpus." Blind spot 4 — anonymous class methods emitted as methods of the *file* — produces a residual entry (`class`) that looks identical to a benign one, next to graph edges that are actively false. This is `coverage-claims.md:134`'s warning ("rigor about 'which files' may inflate confidence about the intra-file blindness that remains") pointed one level down at me.

3. **+26% on the extract path, permanently, for something no query reads.** Every other measurement in this design family pays for itself at read time. This one does not: no tool consults it, no refusal cites it, no key contains it. It is a cost borne entirely so a human can read a list. If the write path does not in fact drop to ~1 s, that 88 ms is a larger fraction of a worse number.

4. **`watch` gets a per-save cost with no per-save consumer.** `indexFile` runs the same extract path. A census over one file is sub-millisecond, but a per-file census is meaningless — the census is a corpus-level artifact — so `watch` either pays for nothing or maintains partial state, and `graph-as-cache.md:157` already lists `watch` as the thing this design family handles worst.

5. **Part A invalidates every existing entry.** Adding the grammar wasm digest to the layer-2 key is correct and it is a total cache miss on both live stores. `graph-as-cache.md:146` already commits to rebuilding both, so the cost is scheduled rather than new — but it is real, and it lands on the farmOS rebuild.

6. **It creates a maintenance surface that decays quietly.** A census that nobody reads is worse than no census, because it exists as evidence of diligence. There is no mechanism here that makes anyone read it, and `iteration-methodology.md:84` is explicit that a fix without the evidence that would catch its regression has a half-life.

---

## Evidence an implementation must ship

Contrast pairs; halves must give opposite verdicts; none promoted on the builder's own run (`epistemology-charter.md:124`).

1. **The capability-table correction, as a test, not a doc edit.** A fixture PHP file containing `new Foo()`, `throw new Bar()`, `#[Attr]`, and a typed return; assert the tree-sitter PHP lane emits **zero** `CONSTRUCTS`/`RAISES`/`ANNOTATES`/`RETURNS_TYPE`. Contrast: the same shapes in TypeScript emit all four. Same edge kinds, two languages, opposite results — which is what the table must say and currently does not.
2. **Promoted properties (fixture 1).** The promoted-constructor class yields zero `field` symbols and zero `READS_FIELD` for `$this->logger`; contrast the classically-declared equivalent, which yields both. **Identical semantics, different syntax, different graph.**
3. **The census names it.** Run the census over fixture 2's corpus; assert `property_promotion_parameter` and `attribute_group` appear in the residual with correct counts. Contrast: after the extractor is fixed, they leave the residual and the symbols appear. The residual is the thing that must move.
4. **Emission-site vs dispatch-site recording (fake-it #1 as a test).** A file with one anonymous and one named class declaration: dispatch-site instrumentation marks `class_declaration` claimed with the anonymous case emitting nothing; emission-site instrumentation records `occurrences: 2, emissions: 1`. **The two instrumentations must give different answers on the same file**, or the instrumentation is decorative.
5. **The deficit is not a verdict (fake-it #1's refutation, shipped as a test).** A Python corpus with many module-level assignments shows a large `assignment` deficit and a fully correct graph. **Asserts that nothing in the build consults the deficit.** Without this, someone builds a gate on it within a quarter.
6. **ERROR accounting discriminates.** The broken-PHP fixture: `has_error: true`, ranges recorded, region marked `partial`, and the missing `After` class provably absent. Contrast: the same file with the syntax repaired yields `complete` and the class present. **Today both are byte-identically HEALTHY.**
7. **ERROR accounting is honestly quiet.** Assert 0 error files over farmOS and MetaCoding. Prevents the next reader from reading Part B as a coverage measure.
8. **Grammar digest discrimination.** Two builds of the same tree with two different `tree-sitter-wasms` wasm blobs must produce **different layer-2 keys**. Contrast: identical wasm ⇒ identical key. Without this the census is not recomputable and constraint 5 is violated.
9. **Census determinism.** Two independent builds of one fixture produce byte-identical census payloads. This is a recomputability test, in the shape of `graph-as-cache.md:91`'s seal-determinism experiment.
10. **Token loss at `php.ts:86-90`.** A property with a non-trivial initializer contributes zero tokens from the initializer; contrast the same expression in a method body, which contributes them. **Same expression, two positions, opposite results.**
11. **Differential lane check as an extractor instrument.** Over a fixture with an anonymous default-export class, SCIP and tree-sitter place `hidden` under different parents; assert the disagreement is detected and reported. This is the only proposed evidence that touches blind spot 4.
12. **Mutation-test the census.** Delete one `case` from `recognizeDeclaration` and assert the corresponding type appears in the residual, with both guards from `iteration-methodology.md:170-176`: **assert the anchor matched**, and **verify the baseline is clean before and after**. A census that cannot report a newly-created blind spot is indistinguishable from one that reports nothing.

---

## Recommendation — the smallest shippable increment

Four steps, in this order. Steps 1 and 2 are small and would be worth doing even if the rest of this document were rejected.

**Step 1 (P0, do it before anything is implemented from `coverage-claims.md`) — correct the PHP row of the static capability table, and ship evidence 1 with it.** The table at `graph-as-cache.md:81` is wrong today about five of eleven edge kinds for PHP, and the coverage-claims design makes that table *load-bearing* (`coverage-claims.md:78`, `:147`). Minting a `complete` `ANNOTATES` claim over 789 farmOS files that hold 587 unseen `attribute_group` nodes would be `hy6.16` reproduced with a stronger warrant than today's silence. This is a doc correction plus one fixture; it is hours, not days. `iteration-methodology.md`'s definition of done applies: the correction ships with the fixture that catches its regression, or it will drift back.

**Step 2 (P1) — grammar identity.** Pin `tree-sitter-wasms` exactly; fold each loaded `.wasm` sha256 into the layer-2 key beside `extractor_version`. ~5 lines in `parser.ts` plus the key composition. Ship evidence 8. Without this nothing derived from a parse tree is recomputable and constraint 5 is unmet — including everything the graph already contains.

**Step 3 (P1) — ERROR/MISSING accounting.** ~20 lines at the parse site; ranges into `MANIFEST.json`; the tree-sitter region derivation at `coverage-claims.md:77` becomes true rather than aspirational. Ship evidence 6 and 7 together — 7 is what stops the next reader from mistaking it for a coverage measure.

**Step 4 (P2) — the unclaimed-form census.** Cursor pass for `seen`, emission-site recording for `emitted_from`, ranked residual into `MANIFEST.json`, never keyed, never a gate. +88 ms on farmOS. Ship evidence 3, 4, 5, 9, 12. **Do this after steps 1–3, and only if steps 1–3 have already paid off** — because the census's entire justification is that it would have surfaced the step-1 defect without anyone knowing PHP 8 attributes exist, and if step 1 turns out to have been findable another way, the census's value proposition weakens accordingly.

Explicitly **not** recommended now: the per-form capability table (dead), differential lane coverage as a manifest field (dead — but worth a separate bead as an extractor-development instrument in CI, where it is the only proposal that touches misattribution), and any consumption of the census by a query, a key, or a gate.

---

## Net

The honest summary is short. **The within-file residual does not admit a claim, because a claim needs a domain the reader already holds and there is none below the file.** What it admits is a census: derived from dispatch rather than declared, enumerated rather than scored, unkeyed rather than gating, and read by a maintainer rather than a query. That is strictly weaker than what coverage claims did for the file level, and calling it anything stronger would repeat the overselling `coverage-claims.md:100` warns against.

What makes it worth building anyway is that pointing it at the shipped code, once, for 88 ms, surfaced a declared capability table that is already wrong about five edge kinds for the one language the production corpus is written in — 587 unseen attribute applications and 376 unseen service dependencies in farmOS — **before the design that makes that table load-bearing has been implemented.**
