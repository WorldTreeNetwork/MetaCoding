# CT Intention Extraction — the intention channel for subsystem specs

How the spec-extraction pipeline harvests, ranks, and fuses **encoded intention** — the *why* carried by names, comments, tests, and strings — with the name-blind structural *what*, so that the re-implementation payload handed to a language model (or a human) specifies both the algorithm's shape and its purpose.

This is the companion to [`ct-subsystem-extraction.md`](./ct-subsystem-extraction.md). It **elevates and enriches that doc's §5** (the NL lane) from a defensive labeling pass into a first-class intention channel, and specifies the card's intent fields in full. It changes nothing upstream: the structural lane (partition, interfaces, roles, operad — companion §2–§4) remains exactly as designed.

Other companions: [`../VISION.md`](../VISION.md) (structure-first-meaning-second; the pre-conceptual horizon), [`ctkr-l3-artifacts.md`](./ctkr-l3-artifacts.md) (L3 provenance conventions, which everything here inherits), [`../notes/entropy-as-dial.md`](../notes/entropy-as-dial.md) (every threshold below is a dial).

Concurrent work: **MetaCoding-hqk** is making the current L3 labeler hierarchical and structure-grounded. This design **supersedes and extends** that direction — hqk's structure-grounded labeling becomes the per-element intent-synthesis stage (§4.2 here); the intention layer adds the mechanical harvest beneath it and the fusion/load machinery above it. Coordinate at bead contact; nothing here contradicts hqk's approach.

---

## 0. The two-stage thesis (read this before objecting)

The name-blindness rule was only ever correct for the **deterministic category-theoretic structural analysis** — the partition, hom-profile roles, functor discovery, and operad recovery. There, letting names influence the math would destroy rigor: rename-fork controls would stop meaning anything, cross-stack portability claims would collapse into vocabulary matching, and the eval story would be circular. **That layer is well dialed-in and stays name-blind. This document reaffirms companion §5.1 without qualification: no token of source text influences any boundary, membership, role quotient, or law.**

But the **spec output fed to a language model for re-implementation in a different stack** is a different artifact with a different job. Business logic lives as much in function names, comments, and test descriptions as in call paths; a strong LM re-implementing a feature makes far better judgment calls when it knows *why* something is done, not just *what* the algorithm is. Raw code paths are only one aspect of a feature. A payload that is name-blind all the way down hands the re-implementer an algorithm skeleton and dares them to guess the business rules.

So: **two stages, not one compromise.**

1. **Name-blind structural analysis** (companion §2–§4, shipped/being built) fixes *what each element is and where it ends* — identity, extent, laws. Deterministic, rigorous, stack-portable.
2. **Intention-fused synthesis** (this document) runs *downstream* of stage 1, over elements stage 1 has already frozen. It harvests every incidental indicator of intention the source carries, attaches it to structural elements, and fuses shape + intention in the re-implementation payload.

The two are not in tension because information flows one way: structure → intention attachment → payload. Intention never flows back into the math. (The one deliberate exception — L3 labels as *priors* for functor search — is the VISION's "closed refinement loops" horizon, explicitly out of scope here.)

The design rule, stated once: **structure decides what to read and what the units are; intention decides what it means, what to call it, and why it exists. The payload carries both, separately attributed, fused in presentation only.**

---

## 1. Catalog of intention indicators, ranked

"Incidental indicators of intention": every place the original authors *encoded purpose* without meaning to write a spec. Ranked by **signal strength for a port** — a composite of (a) *enforcement* (is the indicator checked against behavior, or free prose?), (b) *rot rate* (does it stay true as code evolves?), and (c) *specificity* (does it pin behavior or just gesture at topic?).

### Tier S — load-bearing (the port fails without these)

| # | Indicator | What intention it encodes | Reliability | Extraction |
|---|---|---|---|---|
| S1 | **Test names + test bodies + assertion messages** | Intended behavior, edge cases, error conditions, ordering constraints — *executable* intention. `test_retry_gives_up_after_max_attempts` is a spec sentence that CI has been checking for years. | **Highest of any NL signal** — enforced against behavior on every run; can't rot silently while green. | Test-file detection (path conventions `test_*` / `*_test` / `*.test.ts` / `tests/` + framework imports); tree-sitter `function_definition` names, `describe`/`it`/`test` call-argument strings, assertion-call nodes with message args. Tests are found *from* the structural element via reverse edges (what CALLS/IMPORTS the member set from test files) plus FTS over member qualified names restricted to test paths — the 22.7% structurally-isolated floor applies to test linkage too, hence the FTS complement. |
| S2 | **Interface identifiers** — exported function/method/class names, parameter names, signatures | The contract vocabulary: what callers were promised. Public names are maintained under social pressure (breaking a name breaks callers), so they rot slowest of all prose. | High for boundary symbols; degrades with distance from the interface. | Already in `interfaces.parquet` (companion §3); the harvest adds parameter-name extraction via tree-sitter signature nodes. |
| S3 | **Error/exception semantics** — exception type names, raise/throw sites, error message strings | Invariants and failure policy: what must not happen, what the system does when it does. `"config version %d unsupported; expected ≤ %d"` encodes a compatibility rule no call graph shows. Operator/user-facing, so kept truthful. | High — error text is debugged against reality. | Tree-sitter `raise`/`throw` statement nodes + their string-literal children; exception class definitions among members; string literals matched at raise sites. |
| S4 | **Docstrings on boundary symbols** | Direct statements of purpose, parameter meaning, caller obligations. | Moderate-high; rots when signatures drift (a detectable conflict — §5). | Shipped: `evidence.py::_extract_docstring` (Python `"""`, JSDoc, generic comment-run fallback); extend from snippet-heuristic to proper tree-sitter first-statement/leading-comment nodes. |

### Tier A — strong (shape the port's judgment calls)

| # | Indicator | What it encodes | Reliability | Extraction |
|---|---|---|---|---|
| A1 | **Decorator/annotation names** — `@retry`, `@cached`, `@deprecated`, `@transaction`, route decorators | Declared cross-cutting intent, often *executable* (the decorator does what it says). Nearly tier-S; kept in A because meaning is framework-relative. | High within a known framework. | `ANNOTATES` edges (already in the alphabet) + tree-sitter decorator nodes; the name and its arguments both harvested. |
| A2 | **String literals: log messages, user-facing text, API route strings, SQL/queries** | Behavioral commitments: what the system reports, what URLs it answers, what data it touches. Route strings and SQL are contracts with the outside world. | High for routes/SQL/user-facing; moderate for logs. | Tree-sitter string nodes classified by context (argument to log call / route decorator / query call / UI render) + cheap regex classifiers (path-shaped, SQL-shaped). |
| A3 | **Enum / constant / config-key names and default values** | The domain's controlled vocabulary and its *policy*: `MAX_RETRIES = 3` is a business decision, not an implementation detail. Config keys are the operator-facing contract. | High — constants are load-bearing by definition. | Tree-sitter enum/const declarations among members; config-schema files caught by the nl-only lane (companion §5.4). |
| A4 | **Type / class names + field names** (data-shape vocabulary) | What the domain calls its things. `expires_at` vs `t2` is the difference between a spec and a puzzle. | High for boundary shapes; internal shapes freely renamed. | Already in `data_shapes.parquet`; the harvest adds the *names* as first-class intention rows, not just schema columns. |
| A5 | **Naming conventions/patterns across a role class** | Role-level intent: 14 members all matching `*Handler` + verb-first methods is the authors telling you what the role *is*. The pattern (shared morphology), not any single name, is the signal. | High when coherent (measured — §5.2); the incoherent case is itself signal. | Mechanical: tokenize member identifiers (case-split, §7.1), compute shared-token/affix distribution and its entropy per role class. |
| A6 | **WHY-comments and marker comments** — inline comments explaining rationale; `TODO`/`FIXME`/`HACK`/`NOTE`/`XXX`/`SAFETY`/`PERF` | The only place *rejected alternatives* and *non-obvious constraints* live: "do not reorder — X must init before Y", "workaround for upstream bug #123". Marker comments are meta-intention: `HACK` = intention and structure knowingly diverge here (feeds §6); `TODO` = intent not yet realized (the port may realize it — but must *decide*, not stumble). | Moderate — comments rot; but WHY-comments rot slower than WHAT-comments, and markers are self-declaring. | Tree-sitter comment nodes; marker regex `\b(TODO|FIXME|HACK|XXX|NOTE|SAFETY|PERF)\b`; position-attached to the enclosing symbol. |

### Tier B — contextual (frame the subsystem; rarely pin behavior)

| # | Indicator | What it encodes | Reliability | Extraction |
|---|---|---|---|---|
| B1 | File/directory/module names | Coarse topic + the authors' own decomposition (already a low-weight prior in the partition — companion §2.1; here it is *prose*, not partition input). | Moderate; directories accrete. | Path components of members; `CONTAINS` scaffolding read as text. |
| B2 | README / docs fragments adjacent to the subsystem | Stated purpose, usage examples, architecture claims. Aspirational — describes what the authors *meant*, which is exactly intention, but unenforced. | Low-moderate (docs drift worst of all); still uniquely valuable for non-goals and context. | FTS over doc files scored against member qualified names + subsystem label; nearest README by directory. |
| B3 | Import *sources* (which libraries a subsystem leans on) | Idiom context: importing `tenacity` or `zod` announces intent as loudly as any comment. | High as a hint, framework-relative in meaning. | Already in `interfaces.parquet` consumes rows (external packages); read as intention, not just dependency. |

### Tier C — cheap-if-available (harvest opportunistically, weight low)

| # | Indicator | What it encodes | Reliability | Extraction |
|---|---|---|---|---|
| C1 | **Git commit subjects / blame** on member files | *Why things changed*: bug-fix subjects encode invariants ("fix: dedupe before flush — duplicates corrupted totals") invisible everywhere else. | Variable; high when present. | `git log --follow --format=%s` per member file, top-k by recency + `fix\|bug` match, cached per file digest. **Optional lane** (`--git-signals`), off in v1 (§9 open decision d). |
| C2 | Local variable names inside exemplar slices | Micro-intent within an algorithm. | Noisy; never harvested standalone — they ride along inside exemplar slices, where the reading LM sees them anyway. | None (implicit in slices). |
| C3 | Commented-out code | Usually noise; occasionally a rejected design. | Low. | Not harvested as intention; large commented-out blocks near a member get flagged as a dissonance hint (§6) only. |

**Load-bearing vs. noise, summarized:** tiers S and A are load-bearing for a port — S because it is enforced or contract-facing, A because it carries the domain vocabulary and declared policy. Tier B frames; tier C garnishes. The payload budget (§4.4) allocates accordingly. The single most under-used signal in the current L3 lane is **S1**: tests are the one place intention is written down *and machine-checked*, and the current labeler never looks at them. This design makes tests the backbone of the behavioral section of every card.

All harvest is **mechanical and deterministic** (tree-sitter node kinds, FTS, regex over slices, parquet joins) — LM judgment enters only at synthesis (§8). Harvested rows land in `intention_signals.parquet` (§9.1) with file/line provenance, so every downstream intent sentence can cite its source.

---

## 2. Per-structural-element harvest

For each element type the structural lane produces, which indicators attach and how. Attachment is always **via the frozen member set** — the structural element defines the net; the harvest is what the net catches.

| Structural element | Harvested indicators | Attachment rule |
|---|---|---|
| **Subsystem** (companion §2) | B1 (directory prose), B2 (README/doc fragments), B3 (import sources), aggregate of member-level S/A rows, C1 (commit subjects) | Union over members + directory closure; doc fragments scored by FTS against member names. Subsystem intent = purpose + responsibilities + **non-goals** (B2 is the main non-goal source). |
| **Role class** (companion §4.1) | A5 (the shared naming pattern — *the* role-level signal), S4 (member docstrings, sampled round-robin as today), S1 (tests exercising ≥1 member), A6 (WHY-comments on members), A1 (shared decorators) | Pattern computed over *all* members; prose sampled per the existing evidence-pack budget. A role's intention = what its naming morphology + docstrings say the role *is for*, cross-checked against which tests exercise it. |
| **Composition op / protocol** (companion §4.3) | S1 (tests that exercise the exemplar *paths* — integration tests are composition intent), A6 (ordering/`SAFETY` comments on path steps), S3 (errors raised when the protocol is violated — "not initialized" errors are protocol docs), A2 (log lines along the path) | Attach via exemplar-path symbol sets. Protocol ops (`is_boundary_op`) get priority: the error raised on misuse is the crispest statement of the law. |
| **Interface export** (companion §3) | S2 (its own name + parameter names), S4 (its docstring), S3 (exceptions it raises + messages), S1 (tests calling it directly), **caller-site comments** (A6 harvested at the external call sites — how *users* of the export annotate their use), A1 (its decorators) | Attach via the provides row + reverse crossing edges. An export's intent = its contract as stated (S2/S4) + as enforced (S3/S1) + as understood by callers (caller-site A6). |
| **Data shape / field** (companion §3) | A4 (type + field names), S4 (type docstring, per-field doc comments), A3 (enums/constants of that type, default values), S1 (test fixtures constructing the type — fixtures are worked examples of valid instances) | Attach via the type symbol + field rows. Field flow direction (structural) pairs with field *meaning* (A4/S4): "`expires_at` — out — when the lease stops being honored". |
| **nl-only symbols** (companion §5.4) | Everything — these have *no* structural signal, so tiers S–B are their entire spec. Constants files and config schemas are usually A3-dense. | Locality attachment as designed; `spec_basis: "nl-only"` unchanged. This design upgrades their treatment from "described from names/comments" to the full ranked harvest. |

---

## 3. Formal position (kept light)

In the schema/instance framing (companion §1.1), intention is an **enrichment of the presentation, not part of it**: a second labeling functor from the extracted schema's elements into annotated text, with provenance. Two instances of the same schema (original and port) should map to *equivalent intention* even though every identifier differs — which is exactly the claim that intention is more stack-portable than implementation (§7). We do not compute in this framing; it earns its keep only by fixing the direction of dependence: the enrichment is *over* the schema, so it can never redefine it. This is the categorical restatement of "names never renegotiate the partition."

---

## 4. The re-implementation payload — the **port brief**

The core deliverable. The port brief is the object actually handed to the LM (or human) re-implementing a subsystem: the subsystem card (companion §8.1) *rendered for a builder*, with shape and intention fused. It is **derived** — regenerated from `subsystem_cards.jsonl` + `intention_signals.parquet` + evidence rows; never hand-edited.

### 4.1 The fusion rule

Every element block in the brief is a fixed triple, never blended into one unattributed paragraph:

- **SHAPE** — machine-derived structural facts (roles, arities, laws, edge kinds, cardinalities, flow directions). Deterministic; the port-verifier (companion §7) checks these.
- **INTENT** — the L3-synthesized purpose statement, distilled from the harvest. LM prose; *not* verifier-checkable; every sentence cites `intention_signals` row ids.
- **EVIDENCE** — verbatim quotes and slices (test names, error strings, docstring lines, code), budget-ranked (§4.4).

The reading LM must always be able to tell which claims are *checked* (SHAPE), which are *read* (INTENT), and which are *raw* (EVIDENCE). Fusing presentation while separating attribution is the whole trick: the builder gets one coherent narrative per element, and an epistemic label on every clause.

### 4.2 Brief structure and ordering

Ordering principle: **orientation → vocabulary → contract → internals → behavior → warnings → raw appendix.** Distilled first, raw last; the builder reads top-down and drills into evidence only where the load indicator (§5) says structure alone won't carry them.

1. **Header.** Name, intent paragraph (purpose, responsibilities, **non-goals**), `spec_basis_summary`, and the **intention-load summary** (§5.4) — up front, because it tells the builder how to read the rest: which sections are "implement the shape" and which are "read the evidence."
2. **Domain glossary.** The normalized (§7.1) domain vocabulary harvested from A3/A4/A5/S2: each term with a one-line meaning distilled from docstrings/usage. This is deliberately second — it gives the LM the *language to think in* before any structure arrives, which is precisely what a name-blind spec withholds and what the strongest re-implementation judgment calls run on.
3. **Interface contract.** Per export: SHAPE (usage modes, types, caller counts) / INTENT (contract semantics, caller obligations, error semantics from S3) / EVIDENCE (docstring, top error strings, the 1–3 most specific test names that pin it).
4. **Roles.** Per role class: SHAPE (profile summary, cardinality, interface participation, invariance tier) / INTENT (what the role is for; the naming pattern stated explicitly — "members follow `<Noun>Validator`") / EVIDENCE (one exemplar slice; docstring quotes). Structure-clear roles (§5) get one line of evidence; intention-critical roles get the full pack.
5. **Composition laws & protocol.** Per operation: SHAPE (role-path, arity, support, law notes) / INTENT ("callers must acquire before use *because* …" — protocol phrasing with the *why* attached from S3/A6) / EVIDENCE (exemplar path, the error message raised on violation).
6. **Data shapes.** Boundary shapes with per-field SHAPE (type, flow) + INTENT (meaning) fused into one table; fixture examples from S1 as EVIDENCE.
7. **Behavioral spec.** The S1 harvest distilled into given/when/then scenarios — one line per distinct behavior the tests pin, grouped by the element they exercise, each citing the source test. This section is the port's **acceptance list**: the companion's port-verifier checks shape; the behavioral spec is what the port's *new test suite* must cover. (It complements, never replaces, porting the original tests — companion §7 scope honesty stands.)
8. **Warnings.** In order: (a) structure↔intention **conflicts** (§6) — port-critical first; (b) **intention-critical** elements (§5) — "do not infer this from the algorithm; the names/tests carry the spec"; (c) **ambiguous** elements — "even intention is unclear; consult a human or the original authors"; (d) declared debt (A6 markers) — "the original contains 3 `HACK`s and 7 `TODO`s in this subsystem; the port may resolve them, but each is a conscious decision, listed here."
9. **Appendix: raw evidence.** Exemplar slices, test snippets, full docstrings — everything the distilled sections cite, materialized (self-contained per the L3 snippet convention).

### 4.3 How much rides along — distilled vs. raw

Both, with an explicit division of labor: **distilled intention statements are for orientation and judgment; raw evidence is for arbitration.** LMs porting code follow distilled claims until something underdetermines, then need ground truth to arbitrate — a brief that is all distillate can't be audited by its reader; all raw evidence and it's just "read the codebase." Rule of thumb encoded as defaults (dials): sections 1–7 target a few hundred tokens per element; the appendix carries raw evidence under a per-brief token budget (default 6× the distilled budget), allocated per §4.4.

### 4.4 Evidence budget allocation

Raw-evidence budget is allocated **proportional to intention load, not element size**: structure-clear elements get near-zero raw evidence (the shape suffices; the verifier will check it); intention-critical elements get the maximum (multiple slices, full test bodies, all error strings); ambiguous elements get everything we have plus the human flag. This inverts the naive "big element, big evidence" instinct and is the budget-level expression of the §5 indicator.

---

## 5. The intention-load indicator

The user-emphasized deliverable: an explicit, per-element marker for **where structure alone underdetermines the spec** — exactly where a re-implementer must not guess from the algorithm. This generalizes `intent_dissonance` (companion §5.3) from a defensive footnote into a positive signal: *where does intention matter most?*

### 5.1 The three classes

| Class | Meaning | Builder instruction |
|---|---|---|
| `structure-clear` | The shape pins the behavior: high structural determinacy; any reasonable implementation of the shape is correct. Parsers with grammars in types, pure pipeline stages, well-supported protocol ops. | Implement the SHAPE; skim the INTENT. |
| `intention-critical` | The shape is ambiguous/underdetermined — many intents share this structure — but the intention signal is rich. Business-rule predicates (structurally: a boolean function; the *rule* lives entirely in the name, constants, and tests), policy constants, validation logic, anything nl-only but load-bearing. | The names/comments/tests **are** the spec. Read the EVIDENCE; do not reconstruct from the algorithm's shape. |
| `ambiguous` | Structure is underdetermined *and* intention is thin or self-contradictory. | Flag for human review; the brief lists what's missing. Precedent: the pre-conceptual findings (MetaCoding-5wi) — present evidence and pressure, don't force a spec. |

### 5.2 Computation

Two orthogonal scores, both mechanical, both dial-parameterized (thresholds are dials in config, not truths — entropy-as-dial applies):

**Structural determinacy** `D ∈ [0,1]` — how much the shape alone pins down. Composed from signals we already compute:

- *Profile information mass*: total edge count and kind-diversity of the element's hom-profile, weighted by kind discriminativeness (the 2b weights). A profile that is 90% `CONTAINS` says almost nothing.
- *Bucket ambiguity*: how many structurally-distinct-purpose elements share this profile bucket corpus-wide (approximated by bucket population × label diversity where labels exist). The largest bucket is the 22.7% zero-profile class — determinacy 0 by construction; nl-only symbols are never structure-clear.
- *Persistence*: does the element survive the granularity/resolution sweep (role classes) or carry high support (operad ops)? Ephemeral elements are structurally uncertain.
- *Law coverage*: for ops, observed-law support minus violations; for roles, interface participation (boundary elements are pinned by their crossing edges).

**Intention richness** `R ∈ [0,1]` — how much tier-weighted signal the harvest found. Weighted count of `intention_signals` rows (S=1.0, A=0.6, B=0.25, C=0.1 — dials), with two multipliers: *coherence* (the A5 naming-pattern entropy across role members — a coherent pattern multiplies confidence; incoherence halves it and hints dissonance) and *test linkage* (≥1 S1 row is a floor-raiser; tested intention is qualitatively different from prose intention).

**Classification** (defaults, all dials):

```
D ≥ d_hi                        → structure-clear
D < d_hi and R ≥ r_min          → intention-critical
D < d_hi and R < r_min          → ambiguous
```

plus one override: an unresolved port-critical conflict (§6) forces the element out of `structure-clear` regardless of `D` — a determinate shape whose name contradicts it is precisely not safe to implement from shape alone.

### 5.3 Honesty about the scores

`D` and `R` are engineered composites, not theorems. Their job is triage — routing builder attention and evidence budget — and their calibration path is empirical: on the first real port, elements the porter *actually* had to read evidence for should skew intention-critical; misclassified elements adjust the dials. Ship the drivers (which sub-signals produced the score) alongside every classification so the number is auditable.

### 5.4 Surfacing

Every card element gains:

```jsonc
"intention_load": {
  "class": "intention-critical",        // structure-clear | intention-critical | ambiguous
  "structural_determinacy": 0.31,
  "intention_richness": 0.84,
  "drivers": ["low-discriminativeness profile (78% CONTAINS)",
              "coherent naming pattern (*RateRule, 11/11)",
              "6 tests pin behavior", "4 policy constants"]
}
```

The card header aggregates: `intention_load_summary: {structure_clear: 0.61, intention_critical: 0.29, ambiguous: 0.10}` — sitting next to `spec_basis_summary`, the two honesty gauges of the deck. The brief renders the classes as reading instructions (§4.2 items 1 and 8) and allocates evidence budget by them (§4.4).

---

## 6. Structure ↔ intention agreement and conflict

Companion §5.3's trust policy stands, verbatim: **structure owns identity and extent** (names never move a symbol, merge roles, or invent interface members); **names own intent**; disagreement is a first-class output. This section sharpens the third clause.

### 6.1 From dissonance to port-critical conflict

`intent_dissonance` treated disagreement as a labeling footnote. For a port it is much more: a "Cache" that mutates external state will be re-implemented as a cache — *wrongly* — by any builder who trusts the name. Conflicts are therefore split by severity:

- **`port-critical` conflict** — a strong intention signal contradicts a **tier-I structural fact** (companion §6.1): the name/docstring claims behavior the crossing edges, field-flow directions, or operad laws refute. Detection is two-stage:
  1. *Mechanical detectors* (cheap, deterministic, high precision): a curated table of claim-vs-edge checks — read-implying names (`get*`, `read*`, `*Cache`, `is*`) on symbols with `WRITES_FIELD`/`CONSTRUCTS` out-edges across the boundary; "pure"/"stateless" docstring claims vs. observed state edges; docstring parameter lists vs. actual signature arity; test names asserting an ordering the operad records as violated; `@deprecated` on exports with growing caller counts. The table is data (versioned, per-language entries), not code — same maintenance model as `normalization.json`.
  2. *LM adjudication* (strong model, §8): for each element, the synthesizer receives the structural fact sheet and the harvested intention pack and must emit `agreement ∈ {consistent, tension, contradiction}` with cited evidence — catching contradictions no table anticipates.
- **`advisory` dissonance** — everything softer: incoherent member naming, stale docs, low labeler confidence, large commented-out blocks. The old `intent_dissonance` payload, retained.

### 6.2 Resolution rule for the brief

A conflict is **never silently resolved in either direction**. The brief states both, epistemically labeled, with the builder instruction spelled out:

> ⚠ **port-critical** — `SessionCache.get()` is named and documented as a read ("returns the cached session"), but structurally writes `Session.last_seen` across the subsystem boundary on every call (interfaces row …, 312 observed edges). **Trust structure for what happens, the name for what was meant.** The port must reproduce the write (it is tier-I behavior external code observes) — and may rename honestly. Do not implement the name.

Port-critical conflicts surface in three places: the element's block (inline), the brief's Warnings section (first), and the deck preamble (count). They also force the element's load class out of `structure-clear` (§5.2) and are natural first entries on the port-verifier punch list's "confirm intentionally" checklist — a port that *fixes* the behavior has diverged from tier-I structure, which the verifier will flag; the brief must have told the builder that keeping the ugly truth is the conservative choice.

---

## 7. Cross-stack portability of intention

The under-appreciated asymmetry: **intention is often more portable than implementation.** "Retry with exponential backoff, give up after 5" survives any stack verbatim; the decorator, the loop, and the monad it was written with do not. The intention channel is therefore not merely compatible with cross-stack porting — it is the *most* invariant thing we extract, when separated from its idiom.

### 7.1 Normalization (the intention analogue of companion §6.2)

Applied at harvest time; raw text always retained alongside:

1. **Identifier tokenization** — case-fold camelCase/snake_case/PascalCase/kebab-case into token sequences (`getUserById` ≡ `get_user_by_id` ≡ `GetUserByID`). All naming-pattern computation (A5) and cross-stack intention comparison operates on token sequences, never raw strings.
2. **Convention-affix table** — per-language/framework affixes that carry convention rather than domain (`I`-prefix interfaces, `Abstract*`, `*Impl`, `use*` hooks, `*_test`), folded before pattern extraction. Data, versioned — an extension of `normalization.json`'s idiom-shim philosophy to the text lane.
3. **Marker-vocabulary map** — `TODO/FIXME/HACK/XXX` variants and per-ecosystem test-name grammars (`test_*` / `it("should …")` / `#[test]` / table-driven Go) normalized into one scenario form for the behavioral spec.

### 7.2 Universal vs. idiom-specific — intention tiers

Parallel to companion §6.1's structural tiers, every intention signal gets a portability tag:

| Tier | Meaning | Signals |
|---|---|---|
| **intent-I — universal** | Survives any stack; goes into the brief as-is | Domain vocabulary (glossary nouns/verbs), behavioral scenarios (S1 distillate), error *semantics* (the condition and policy, not the exception class name), policy constants and their values, protocol obligations, non-goals |
| **intent-N — convention-encoded** | Real signal, expressed in a source-stack convention; normalize (§7.1) before it enters the brief, and *restate* rather than copy | Naming patterns (state the role meaning, not the affix), decorator names (state the declared behavior — "memoized", not `@lru_cache`), config-key naming styles, test-framework phrasing |
| **intent-A — idiom-specific** | Meaningful only in the source stack; drop from the brief (retained in provenance) | Dunder/protocol-method names, framework lifecycle hook names, language-community naming folklore, build/tooling comments |

Tier assignment is mostly mechanical (signal kind → default tier; the affix/marker tables catch the N cases) with LM assistance for the residue, same split as structural tier assignment. The brief's glossary and behavioral spec are built from intent-I material only; intent-N appears restated; intent-A never appears. **Consequence worth stating:** a brief built this way contains no instruction like "name it `SessionCache`" — it says what the thing is *for*, and lets the target stack's conventions name it. Per companion §1.2(c), a real port supplies the second instance that corrects these tags empirically, exactly as it corrects the structural ones.

---

## 8. Cost, models, caching, determinism

The harvest is free; the synthesis is LM work, routed by difficulty:

| Stage | What | Model | Why |
|---|---|---|---|
| Harvest (§1–§2) | tree-sitter/FTS/regex/join extraction → `intention_signals.parquet`; naming-pattern stats; mechanical conflict detectors; `D`/`R` scores | **none** | Deterministic, byte-identical re-runs — the same standing as the structural artifacts. |
| Per-element intent synthesis | label + intent paragraph + evidence citations per role/op/export/shape (the existing labeler pattern, enriched with the ranked harvest in the prompt) | **cheap** (haiku-class, as today's `label_roles.py` default) | High volume (thousands of elements), narrow judgment, structured output. |
| Scenario distillation | S1 test rows → given/when/then behavioral spec | **cheap** | Mostly transcription with light normalization. |
| Conflict adjudication (§6.1 stage 2) | structural fact sheet vs. intention pack → agreement verdict + citations | **strong** (sonnet/opus-class) | Contradiction-finding is exactly where cheap models rubber-stamp. Runs per element but only where mechanical screens or low labeler confidence flag *candidates* — a filtered subset, not the corpus. |
| Brief fusion (§4) | card + signals → the port brief's distilled sections, glossary, warnings | **strong** | One call per subsystem (tens, not thousands); the highest-judgment artifact in the pipeline; where "knowing why" gets written down. |

**Caching & determinism.** Everything rides the existing `LLMClient` machinery (`ctkr/llm.py`): temperature 0 default, blake3 prompt-hash cache keyed over `(provider, model, prompt, schema, …)`, cost telemetry to JSONL. Because prompts are rendered from **structured evidence digests** (canonical serialization of the element's `intention_signals` rows + structural fact sheet), the cache key is effectively `(structured-evidence digest, prompt_version, model)` — unchanged evidence means a free re-run; any harvest change flows into the digest and invalidates precisely the affected elements. All synthesized rows carry the four mandatory provenance fields per `ctkr-l3-artifacts.md`; brief regeneration with identical inputs + `prompt_version` reproduces identical `card_id`s/brief digests (the T5 acceptance criterion, extended to the brief).

Cost envelope, order-of-magnitude: for a 5k-symbol repo at ~15 subsystems / ~300 elements — harvest free; ~300 cheap calls (cents, per the existing cost log's per-call telemetry); ~30–60 strong adjudications + 15 fusions (single-digit dollars). The expensive lane is opt-in per subsystem (`ctkr extract-spec --briefs`).

---

## 9. Artifacts, surface, and build-plan delta

### 9.1 New/extended artifacts

- **`intention_signals.parquet`** (new, mechanical): one row per `(element_id, element_kind, indicator_kind, tier, content, file, line_range, portability_tier, schema_version)`. The harvest's ground truth; everything downstream cites row ids. Columnar because it is mechanical bulk, unlike the streamed L3 JSONL. *(Open decision a — vs. folding into `evidence.jsonl`; recommended separate: different producer, different rhythm, different consumers.)*
- **`intention.jsonl`** (extends `patterns.jsonl` conventions): synthesized intent rows for the new `source_kind` values — which `evidence.py::SourceKind` already declares (`subsystem`, `role-class`, `operad-op`, `interface-export`, `data-shape`, `nl-only`), so the type-level seam exists today. Adds `agreement` and `conflict` payloads.
- **`subsystem_cards.jsonl`** (extended): per-element `intent` triples gain citations; new fields `intention_load` (§5.4), `glossary`, `behavioral_scenarios`, `conflicts`; header gains `intention_load_summary`.
- **`port_briefs/<subsystem>.md`** (new, derived): the §4 rendering. Regenerable; never authoritative; digest recorded in the card provenance.

### 9.2 Build-plan delta (against companion §9)

This layer slots into and around **T5** (which becomes three shippable slices) — nothing upstream moves:

- **T5a — harvest**: `intention_signals.parquet` + tokenizer/affix tables + `D`/`R` scoring + mechanical conflict table. No LM. Acceptance: deterministic re-run byte-identical; on the MetaCoding self-index, ≥1 known port-critical conflict candidate surfaced by the mechanical table (seed the fixture); test-linkage found for ≥70% of boundary exports.
- **T5b — synthesis** (the old T5, enriched): labeler prompts consume the ranked harvest; scenario distillation; adjudication pass; card fields land. Acceptance: old T5 criteria + human review confirms ≥1 genuine port-critical conflict or a reviewed empty set; every intent sentence in ≥3 reviewed cards resolves its citations.
- **T5c — briefs**: the fusion renderer + budget allocator. Acceptance: brief for one subsystem judged by a human "buildable without reading the repo" for structure-clear elements; intention-critical elements carry their full evidence; deterministic digest.
- **T6′ (future, flagged)**: port-verifier gains an *intention* check — the port's test names, distilled through the same S1 pipeline, covered against the brief's behavioral scenarios. Closes the loop on the one thing the structural verifier admits it cannot see (companion §7 scope honesty).

### 9.3 MCP surface

`ctkr.subsystem_card` gains the new sections via its existing `sections?` filter; one new read tool `ctkr.port_brief(repo, subsystem)` returning the rendered brief (or its sections). Extraction remains batch-runner-only, per the established read-side discipline.

---

## 10. Honest limits & open decisions

**Limits:**

- **Intention can lie; we rank, we don't verify.** Tier weights encode *expected* reliability; a wrong-but-coherent docstring on an untested element will produce confident wrong intent. The mitigations are structural cross-checks (§6), test-linkage weighting (§5.2), and epistemic labeling in the brief (§4.1) — not guarantees. The behavioral spec is only as good as the original tests.
- **`D` and `R` are triage heuristics** (§5.3), calibrated by ports, not derived. Ship drivers, keep thresholds dials.
- **The N=1 problem applies to intention too**: with one codebase we can't distinguish "this team's vocabulary" from "the domain's vocabulary." Portability tags (§7.2) are judgment until a port supplies the second instance.
- **Comment/docstring harvest quality is per-language uneven** (tree-sitter grammar coverage; the docstring extractor's heuristics) — carry a coverage note per lane, same discipline as `alphabet_coverage`.
- Nothing here weakens the structural lane. If a future reader cites this doc to argue names into the partition or the role quotient: no. Stage 1 is name-blind (§0); this entire layer exists *because* it is.

**Open decisions (new, flagged):** (a) `intention_signals.parquet` vs. folding into `evidence.jsonl` — recommend separate parquet (§9.1); (b) `D`/`R` composite weights and class thresholds — ship as config dials, calibrate on first port (§5.3); (c) port brief as rendered artifact vs. on-demand render — recommend rendered + digested, regenerable (§9.1); (d) git-signal lane (C1) in scope for v1 — recommend defer behind `--git-signals` (§1, tier C); (e) mechanical conflict-detector table location — recommend sibling of `normalization.json`, versioned data (§6.1); (f) T6′ intention-side port verification — design sketched, sequence after the first real port exercises the brief (§9.2).
