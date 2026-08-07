# Lessons as mechanism: what one session should leave behind in the instrument

**Status:** proposed, 2026-08-07. Amends [iteration-methodology.md](./iteration-methodology.md); depends on [within-file-coverage.md](./within-file-coverage.md) Part A.
**Origin:** Duke — *"design what the session's lessons should become inside MetaCoding itself, as mechanism, not as advice in a document nobody re-reads."*
**Beads:** existing `0bm`, `m7x`, `hy6.28`, `1gt.1`; new ones proposed at the end.

---

## The raw material, compressed

Nine failures and six successes from one session, sorted by the shape they share rather than the order they happened:

| shape | instances | what the shape is |
|---|---|---|
| **an instrument that cannot fail** | a mutant that died of `SyntaxError`; a regression test that passed against the broken code too; a mutation whose anchor silently did not match | the run reports a result for a test that never happened |
| **a floor calibrated from a measurement the instrument does not emit** | thresholds guessed and refused by correct runs, three times — a section's ROW count is not its CHECK count | the builder is told to calibrate and given nothing to calibrate from |
| **a guard that lives in a library the caller did not import** | a throwaway probe stranded fixtures on the shared oracle, hours after `ledger.py` fixed exactly that | enforcement by convention over a shared mutable resource |
| **a fixture smaller than production** | CSV dialect sniffing stable at 6 rows, unstable at 21,282; the pathological row visible to the sniffer until 12,000 clean rows sat ahead of it | size-sensitive components measured at a size that cannot exercise them |
| **a declaration read as a measurement** | `combinedAssetGeometries` is buildForm-only; unassigned farm is the literal id `0`; inventory has one bundle; a commented-out `drush en` parsed as a declaration | source reading, or a parse of a human-edited file, substituting for the boundary |
| **extraction loses what nobody wrote down** | the shared ledger dropped the request body and the coverage row that all four hand-written versions had | the union of independently invented guards is larger than any one build's set |

The successes are the same list read forward: contrast pairs, mutation with anchors asserted and baseline verified clean, instrument-tier weighting, extracting the union, driving the boundary instead of reading the source, and declaring what is *not* established next to what is.

**None of these are new observations.** Every one is already written down in `iteration-methodology.md` — the fake-it question, the two mutation guards, "does your evidence discriminate?", "a fix ships with the evidence that would catch its regression." They were written down and then violated, in the same session, by the agent that had read them. That is the actual finding of this document, and it sets the bar: a proposal that produces another paragraph in another document is a proposal that has already been refuted by the evidence it was written from.

---

## The property

> **An instrument in this repository cannot report a result for a check that did not run, and cannot report a verdict it is structurally incapable of withholding.**

Applying the well-formed-red test (`iteration-methodology.md:38`) — *could the system satisfy this and still be wrong in the way that motivated it?*

**Yes, in two ways, and both must be stated up front.**

1. The property covers **silence and constancy**, not **wrongness**. An instrument that runs every check, publishes every count, and applies the wrong predicate satisfies it completely. This is the same residual `within-file-coverage.md:33` names and `graph-as-cache.md:164` recorded before it ("a correct key over a broken extractor — every input hashed, every seal valid, every edge wrong. **Not caught**"). I am not going to invent an answer for it here either.
2. It says nothing about a **declaration wearing a measurement's clothes** — the source-reading failures. That half is handled separately below (mechanism 3), and only for MetaCoding's own toolchain, where the "boundary" is a resolvable artifact digest. There is no general mechanism for "you read the source and the source was not the world"; the answer there is a posture (drive the boundary) that only mechanizes where a boundary exists.

---

## The ranking, up front

Value is measured as *how many of the six shapes it makes structurally impossible*. Cost is measured in days for one implementer plus the discriminating fixtures.

| # | mechanism | where it lands | shapes closed | cost | verdict |
|---|---|---|---|---|---|
| 1 | **`discriminate()`** — contrast pairs and non-constancy as one primitive | `src/testkit/discriminate.ts` | cannot-fail; declaration-read-as-measurement (for parsers) | ~1 day + 4 fixtures | **do first** |
| 2 | **Custody bracket** — a before/after census around every oracle-touching build, run by the *runner*, not imported by the probe | `ctkr/ctkr/oracle/custody.py`, called from `ctkr/ctkr/oracle/runner.py` | guard-not-imported | ~1–2 days | **do** |
| 3 | **Toolchain identity** — every lane's artifact digested, folded into the key, drift-checked against a committed declaration | `src/toolchain/identity.ts`, `toolchain.lock.json`, `scripts/toolchain-preflight.ts` | declaration-read-as-measurement; unrecomputable facts | ~2 days | **do** (closes `0bm`) |
| 4 | **Floors that carry their measurement** — a floor is a struct that names the field the instrument publishes | `src/testkit/floors.ts`, applied to `scripts/smoke-*.ts` | guessed thresholds; cannot-fail (truncation half) | ~1 day + 22 small edits | **do** |
| 5 | **Mutation harness with the two guards** — mutant must parse, anchor must match, baseline clean before *and* after | `src/testkit/mutate.ts` | cannot-fail (the expensive, general form) | ~2 days | **do last, instrument tier only** |
| — | a first-class `Checker` framework in MetaCoding | — | — | weeks | **NOT doing** |
| — | a threshold registry | — | — | ~1 day | **NOT doing** |
| — | a production-size-fixture detector | — | — | ~1 day | **NOT doing** |
| — | any of it as the primary home in `CLAUDE.md` | — | — | minutes | **NOT doing as a primary home** |

Mechanisms 1 and 4 are worth shipping even if 2, 3 and 5 are rejected entirely.

---

## Mechanism 1 — `discriminate()`: contrast pairs and non-constancy, as one primitive

**The observation that makes this small.** A contrast pair and a mutation test are the same operation pointed in opposite directions: *a contrast pair is a mutation applied to the subject; a mutation test is a contrast pair applied to the instrument.* Both are "two inputs, one verdict function, the verdicts must differ, and the difference must be **named**." That is one function, not a framework.

The pattern already exists in this repo, hand-rolled, exactly once — `src/ingest/seam.test.ts:440-486`, whose own comment states the principle better than a document can:

> *"Each input class must produce a DIFFERENT refusal code, so a check that had collapsed into 'always throw' — or into 'never throw' — would be visible here."*

Six input classes, six distinct verdicts, and an `OTHER:${message}` fallthrough so that a crash cannot masquerade as a refusal. That file also carries the argument against the alternative (`seam.test.ts:1-36`): the previous instrument was a text scanner over import syntax, a fresh judge found **nine of nine** bypass shapes undetected, and the conclusion recorded there is that a scanner's coverage is the set of shapes its author imagined.

**The mechanism.** `src/testkit/discriminate.ts` exports one function:

```ts
discriminate({
  name,                      // what property this pair is about
  verdict: (input) => Tag,   // must return a NAMED tag, never a boolean
  cases: { [tag]: input },   // one input per expected tag
})
```

Three rules, each of which refuses something that passes today:

1. **The verdict must be a tag from a closed vocabulary, not a boolean and not an exception.** Anything that arrives as an uncaught throw is classified `OTHER:<message>` and **fails the pair**. A boolean verdict makes every non-constancy check trivially satisfiable by an unrelated crash; a refusal code does not.
2. **Every declared tag must be reached**, and no two cases may produce the same tag. A verdict function that has collapsed to a constant fails on the first duplicate.
3. **The pair itself is recorded**, with its tags, into the run's published record (see mechanism 4). A pair that was deleted stops appearing.

**What it refuses that today passes.** `scripts/smoke-incremental.ts` runs five passes and prints `INCREMENTAL_SMOKE_PASS` at line 151. Delete assertions from passes 2 and 3 and it prints the same line, exit 0. Under `discriminate`, each pass declares its tags; a deleted assertion produces an unreached tag and a named failure.

More sharply, it refuses the shape of failure 3: a regression test whose "broken" half and "fixed" half give the same verdict. Today that is a green suite; under `discriminate` it is a duplicate-tag failure by construction, because the two halves are *the same pair*.

**The comment-invariance exemplar (failure 5), as a fixture rather than a rule.** Failure 5 — a commented-out `drush en` parsed as a declaration, blocking every port — generalizes to: *any gate that parses a human-edited file must have a pair proving comments do not move the verdict and content does.* That is three lines under `discriminate`, not a new mechanism:

```
cases: {
  BASELINE:        f,
  UNCHANGED:       f + "\n# a comment explaining why\n",   // must equal BASELINE
  CHANGED:         f + "\ndrush en -y farm_new\n",         // must differ
}
```

MetaCoding owns three such parsers today: `ctkr/ctkr/oracle/bring-up.sh`'s consumer, `port.toml`, and the tsconfig readers. `tools/oracle_preflight.py:344` already carries the fix and its reasoning; what it does not carry is the pair, so the fix has the half-life `iteration-methodology.md:84` describes.

**Discriminating fixtures for `discriminate()` itself** (the instrument tier applies to the testkit before anything else):

- **F1.1** A pair whose halves differ only by an unrelated `TypeError` must be **REFUSED** (`OTHER:` is not a verdict); a pair differing by refusal code must **PASS**. Without this, mechanism 1 is a pair-counter.
- **F1.2** A verdict function collapsed to `() => "REFUSED"` must fail on duplicate tags; the same function restored must pass. Same suite, two implementations, opposite results.
- **F1.3** Replay `seam.test.ts`'s six classes through `discriminate` and assert byte-identical tags to the hand-rolled version. Migration evidence, not decoration.

---

## Mechanism 2 — the custody bracket: the guard that does not depend on being imported

**This is the one I would attack a naive design over, so let me state the naive design and kill it.** The naive fix to failure 4 (a throwaway probe stranded fixtures on the shared oracle) is: put the guards in `ledger.py`, make `get_token` private, and require every probe to go through the guarded session. **That fails for a reason the session already measured.** The OAuth password grant is six lines of `urllib`; nothing can make a token unobtainable. Enforcement-by-import over a shared external resource is exactly the text-scanner failure of `seam.test.ts:1-36` in a different medium: its coverage is the set of entry points its author imagined, and the stranding probe was the one they did not.

`src/ingest/ticket.ts` solves the analogous problem for the graph store because MetaCoding *owns the store's write path* — a ticket can be made structurally necessary. Nobody owns farmOS's write path. So the guard must sit **outside** the probe, in the thing that brackets it.

**The mechanism.** `ctkr/ctkr/oracle/custody.py`, invoked by `ctkr/ctkr/oracle/runner.py` around every build, and by `metacoding oracle custody --begin/--end` for a human doing anything by hand:

- **`--begin`** takes a paginated census (reusing `ledger.py:70`'s `paginate`, which is the fix for the 50-row cap) of every collection the build's declared resource types resolve to — the same list `oracle_preflight` already requires the build to name (`tools/oracle_preflight.py:417`). Stores `{collection: {id: name}}` in the run directory.
- **`--end`** re-censuses and diffs. Any id present at end and absent at begin, **which no ledger in this run tracked**, is reported by id, collection and name.
- The report is **loud and advisory, never a deletion.** Deleting a row this bracket did not create is the failure `ledger.py:357` already refuses by name; a shared oracle makes "clean up what you find" the most dangerous possible behavior.

**What it refuses that today passes.** A probe script that POSTs a fixture and exits: today, exit 0, silence, and the fixture is discovered by whole-collection diff hours later. Under the bracket, `--end` names it. Crucially, **the probe needs to change nothing** — the guard is not in its import graph.

**Discriminating fixtures:**

- **F2.1** A probe that creates one fixture and does not delete it → `--end` reports exactly that id. The same probe with cleanup → clean. **Both exit 0 today.**
- **F2.2** A probe that creates a **derived-name** log (`Transplanting log 1234`, matching no fixture prefix — the case `ledger.py:373` proves a name scan cannot see) → `--end` reports it. This is the fixture that proves the census is by id and not by prefix.
- **F2.3** A ledger run that creates and correctly deletes 70 rows across a 50-row page boundary → clean, with no false positive from pagination. Contrast: the same run with `MAX_PAGES = 1` → the leak is invisible, proving the census actually paginates.

**What it handles worse, stated plainly.** The census cannot attribute. Two concurrent runs mean each one's bracket sees the other's rows as unexplained. Mitigations, in order of preference: (a) the report ranks by whether the name matches *any* known run prefix, so a labeled concurrent fixture is separated from a genuinely orphaned one; (b) the bracket records the concurrent run ids it was told about; (c) accept the noise, because a noisy report about a shared resource is what the session actually needed and did not have. **I would ship (a) and be honest that (c) is the fallback.** A false positive here costs a minute of reading; a false negative cost hours and recurred.

---

## Mechanism 3 — toolchain identity: `oracle_preflight`'s shape, generalized

The session's preflight has five structural parts, and all five generalize:

| `oracle_preflight.py` | the general form |
|---|---|
| `PROVIDED_BY` + `bring-up.sh` (`:319`) | a committed **declaration** of what a rebuild would reproduce |
| `installed_modules()` via `drush php:eval` (`:360`) | the **live artifact**, read out, not asked about |
| `module_drift()` reachability closure (`:388`) | live ∖ reachable-from-declaration = **hand-enabled, and gone on the next rebuild** |
| `PreflightFailed` on parse-zero (`:351`) | **a broken checker is a failure, never a skip** |
| `DriftCheckUnavailable` (`:144`) | **"no answer" is loudly distinct from "no drift"** |

MetaCoding's external dependencies have exactly this problem and no such check. Every one of them changes every fact in the graph and **moves no key**:

- `package.json:84` — `"tree-sitter-wasms": "^0.1.13"`, a caret range, loaded by path at `src/extractor/parser.ts:32-35`. (`web-tree-sitter` is pinned exactly at `0.22.6`; the two sit adjacent in the same file, one right and one wrong, which is the strongest available argument that this is an oversight and not a policy.)
- `@sourcegraph/scip-typescript ^0.4.0`, `@sourcegraph/scip-python ^0.6.6` — caret.
- `SCIP_PHP_IMAGE` at `src/scip/run.ts:60` — a docker tag, which is mutable by definition.
- `intelephense ^1.18.5`, `typescript-language-server ^5.1.3`, `@ladybugdb/core ^0.15.4`.

**The mechanism.** `src/toolchain/identity.ts` resolves, for each lane, a **digest of the artifact actually loaded** — `sha256` of each `.wasm` blob, the `version` field from the resolved `node_modules` package plus a digest of its entry point, `docker image inspect --format '{{.Id}}'` for the scip-php image. `toolchain.lock.json` is the committed declaration. `scripts/toolchain-preflight.ts` compares and refuses on drift, with `oracle_preflight`'s two distinctions preserved: a lockfile that parses to zero lanes is a **failure**, and an unreachable docker daemon is a loud **SKIP** that names the lane it could not check.

The digest folds into the layer-2 key beside `extractor_version` — which is `within-file-coverage.md` Part A and bead `0bm`, already filed at P1, already carrying its evidence (#8: two builds of one tree with two different wasm blobs must produce different keys; identical wasm ⇒ identical key).

**What it refuses that today passes.** `bun install` resolves `tree-sitter-wasms@0.1.14`; every parse tree changes; every layer-2 key is identical; every sealed entry is a cache hit; every derived CTKR artifact is now about a graph built by a different parser. Today: silent. This is `graph-as-cache.md:165` instantiated — *"an input left out of the key is a dimension the cache is blind to"* — and it is the mechanism-side twin of `MetaCoding-855`, where MetaCoding's own artifacts were derived from a graph with 430 phantom files nobody could see.

**Discriminating fixtures:**

- **F3.1** Two builds of one fixture tree with two different wasm blobs ⇒ **different keys**; identical wasm ⇒ identical key. (`0bm`'s evidence #8.)
- **F3.2** **The digest must come from the artifact, not the declaration.** Replace the bytes of a `.wasm` in `node_modules` without touching `package.json`; the digest must move. This is the fixture that separates mechanism 3 from a version-string comparison, and without it the whole thing is a declaration in a measurement's clothes — the failure `coverage-claims.md:73` calls "the same blindness one level up."
- **F3.3** A lockfile that parses to zero lanes ⇒ **failure**, not pass. (`oracle_preflight.py:351` replayed.)
- **F3.4** Docker unavailable ⇒ **SKIP naming scip-php**, exit 0, and `--require-lanes` turns that skip into a failure. Contrast: docker available with a drifted image id ⇒ failure. Same code path, three outcomes, three distinct tags.

---

## Mechanism 4 — floors carry their measurement

This is failure 1, and it is the smallest fix in the document.

The root cause was not that thresholds were guessed. It is that **the instrument did not publish the quantity the builder was told to calibrate from**: a section's ROW count is not its CHECK count, and only rows were visible. The fix that worked was three lines — `ledger.py:425-431` publishes a `coverage` object on the `SUMMARY` row, and `ledger.py:421-424` records why:

> *"the comments tell a builder to set floors from a measurement, so the measurement has to be in the file."*

Note that the *shared* ledger initially lost this, which every hand-written version had. That is failure 8, and it is why the rule must be structural rather than remembered.

**The generalized rule, stated so it can refuse things:**

> **A floor is not a number. It is a pair — a value and the name of the field the instrument publishes it against — and the instrument's own record must contain that field.**

**The mechanism.** `src/testkit/floors.ts`:

```ts
type Floor = { min: number; measuredAs: string; why: string };
evaluateFloors(floors, published)   // fails if `published[f.measuredAs]` is absent
                                    // — a floor over a field nobody emits is an
                                    // INSTRUMENT failure, not a pass
```

Applied to `scripts/smoke-*.ts`. Measured today: **22 smoke scripts, 4 to 11 assertions each, and zero of them publish how many checks they ran.** `grep -l "checks\|checked\|assertions" scripts/smoke-*.ts` returns nothing. A truncated run and a complete run are byte-identical — `INCREMENTAL_SMOKE_PASS` either way.

This composes with mechanism 1: `discriminate()` registers each pair it ran, so `checks` is a *derived* count, not a hand-maintained one, and the floors that matter (per-section, `ledger.py:111-137`'s strictly-stronger form) come free.

**Discriminating fixtures:**

- **F4.1** A smoke script with three checks deleted fails the floor **by name**; the complete script passes. **Both print PASS today.**
- **F4.2** A floor whose `measuredAs` names a field the script does not publish fails as an **INSTRUMENT** error, distinct from a check failure. This is the fixture that closes failure 1 at the root — it makes "you were told to calibrate from a measurement that does not exist" a build failure rather than three rounds of guessing.
- **F4.3** An **empty** run — zero checks, zero pairs — fails, not passes. (`ledger.py:176-186`: the cheapest green is an empty run.)

---

## Mechanism 5 — the mutation harness, with both guards

Last, and deliberately last, because it is the expensive general form of what mechanisms 1 and 4 buy cheaply.

`src/testkit/mutate.ts` applies a named mutation to a source file and runs a suite, with the three guards the session paid for:

1. **The mutant must parse.** Failure 2 — a mutant that died of `SyntaxError` proved nothing, and the fix was `ast.parse` before trusting the kill. The TypeScript analogue is a `Bun.Transpiler().scan()` (or `ts.createSourceFile` diagnostics) check before the run. `bun test` does not typecheck, so parse — not typecheck — is the correct bar; requiring the mutant to typecheck would reject legitimate mutants.
2. **The anchor must have matched.** `iteration-methodology.md:172` — a replacement string with wrong indentation silently did not match, the suite ran unmodified, and "0 fail" read exactly like *the suite cannot catch this*.
3. **The baseline must be clean before and after.** Same passage: a `git checkout` restore reverted an unrelated uncommitted change and added one constant failure to every subsequent count, hiding a genuine zero-catch in the noise. Mutate in a **temporary worktree**, never in place, and assert the baseline both ways.

**Scope: instrument tier only.** `iteration-methodology.md:72` is explicit that full weight applied uniformly costs more than the work. The instruments in this repo are enumerable: `src/ingest/fitness.ts`, `src/ingest/ticket.ts`, `src/store/build.ts`, `src/toolchain/identity.ts` (new), the census (`m7x`), and `src/testkit/` itself. That is a list, not a policy.

**Discriminating fixtures:**

- **F5.1** A mutant that does not parse is reported **UNPARSEABLE**, never **KILLED**. Contrast: a parseable mutant that fails the suite is **KILLED**. Today the two are indistinguishable — this is failure 2 as a test.
- **F5.2** A mutation whose anchor does not match reports **NOT_APPLIED**, never **SURVIVED**. Contrast: a matching anchor whose mutant survives reports **SURVIVED**, which is a finding. Today both read "0 fail."
- **F5.3** A dirty baseline is refused before any mutation runs.
- **F5.4** Delete one `case` from `recognizeDeclaration` and assert the census names the type. (`within-file-coverage.md` evidence #12, which already specifies both guards; this mechanism is what makes that evidence writable.)

---

## What I am NOT building, and why

**A first-class `Checker` concept in MetaCoding — the ledger generalized.** No. The ledger is three orthogonal things wearing one class: floors-with-published-coverage (→ mechanism 4), the structural guard that a row carrying no expectation is itself drift (→ mechanism 1, as a tag vocabulary with no unnamed member), and custody over a shared external resource (→ mechanism 2). Each generalizes on its own; the *class* does not, because its remaining substance — JSON:API pagination, `links.next`, farmOS delete ordering, the 403-reach-through — is knowledge about farmOS's boundary, and moving that into MetaCoding is the inversion `MetaCoding-1gt.1` exists to prevent (instrument / lens / source / ledger). The right home for the ledger is **the scaffold `metacoding port init` emits** (bead `1gt`) — a template a port copies and owns, not a library it imports. That also makes failure 8 (extraction quietly loses guards) a *diff* against the template rather than a rediscovery.

And the repo's own record says the framework version loses: `graph-as-cache.md`, `coverage-claims.md` and `within-file-coverage.md` are three consecutive rounds in which the general scheme was cut down and the surviving mechanism was small.

**A threshold registry.** The generalized rule — *any threshold not derived from a published measurement is a defect* — is correct, and a registry is the wrong mechanism for it. Measured: the repo has almost no thresholds left (`min_support: int = 5`, `min_cluster_size: int = 2`, `threshold: int = 2` in `ctkr/ctkr/feature_kinds.py:426`, `am >= 0.5` at `src/mcp/ctkr-tools.ts:1408`), because the design line has been actively killing them — `coverage-claims.md:141` rejects thresholding a coverage ratio *"because there is no number to tune, which is the point"*, and `within-file-coverage.md:179` kills the ratio and keeps the set. A registry would be a maintained table over a shrinking population, and `coverage-claims.md:147` and `within-file-coverage.md:181` both argue that a small declared table is dangerous rather than safe. Mechanism 4 covers the case that actually bit — a floor inside an instrument — and the general rule stays a rule.

**A production-size-fixture detector.** The failure is real and expensive (dialect sniffing stable at 6 rows and unstable at 21,282; a regression test that needed 12,000 clean rows ahead of the pathological one). Every detector I can construct is a scanner over an open set of size-sensitive call sites — `COPY`, sniff, sample, paginate, `LIMIT`, batch — and `seam.test.ts:1-36` measured that shape at nine-of-nine bypassed. What survives: `src/store/build.test.ts:211-227` is the exemplar, it is excellent, and it should be *cited by name* from the testkit's docstring so the next builder reads it at the point of use. That is the honest version, and it is weaker than a mechanism. I am recording it as weaker rather than dressing it up.

**Any of this as a primary home in `CLAUDE.md`, a skill, or a bead template.** Documentation is the weakest of the three and this session is the proof: `iteration-methodology.md` already contains the two mutation guards (`:170-176`), the fake-it question, and "does your evidence discriminate?" — and the session violated all three, having read them. But one documentation artifact *did* work, and the difference is mechanical: `ledger.py`'s and `oracle_preflight.py`'s module docstrings were read, because the builder had to import the module to do the job. **So the rule is: documentation goes where the code is imported from, never in a file whose only job is to be read.** Concretely — the testkit's docstring is where the contrast-pair argument lives; `CLAUDE.md` gets at most three lines pointing at `src/testkit/`; a bead template beats `CLAUDE.md` because `bd show` is read at claim time, and it should carry one line only: *"what would this fix's regression look like, and which fixture catches it?"*

---

## What it costs

| item | cost |
|---|---|
| `src/testkit/discriminate.ts` + its own 3 fixtures | ~1 day |
| Migrating `seam.test.ts:440-486` to it (evidence, not cleanup) | ~2 hours |
| `src/testkit/floors.ts` + 22 smoke scripts × ~5 lines | ~1 day |
| `ctkr/ctkr/oracle/custody.py` + runner call + 3 fixtures | ~1–2 days |
| `src/toolchain/identity.ts` + `toolchain.lock.json` + preflight + 4 fixtures | ~2 days |
| `src/testkit/mutate.ts` + 4 fixtures | ~2 days |

**Runtime cost.** The custody bracket is two paginated censuses per build over the collections the build already names — on farmOS's largest at-rest collection (`asset/land`, 48 rows) that is one page each way; the 70-row seeding case is two. Seconds, against builds measured in minutes. The toolchain digest is a handful of `sha256` calls over `.wasm` blobs plus one `docker image inspect`, once per process. Both are noise against the ~1 s sealed rebuild `coverage-claims.md:47` projects — **and both inherit every uncertainty in that projection**, which `coverage-claims.md:150` marks as a demonstrated floor rather than a rebuild cost.

**The cost nobody counts:** mechanism 1 makes every test in the repo slightly more verbose, because a boolean becomes a tag. That is the whole mechanism — a boolean is what lets a crash pass for a refusal — but it will feel like ceremony, and ceremony is what gets removed.

---

## How would we fake this design?

**1. `discriminate()` satisfied by an irrelevant difference — and this is the one I would attack first.** The rule is "the tags must differ." Make half A throw and half B pass, and the tags differ. The mitigation is rule 1 (an uncaught throw classifies as `OTHER:` and *fails* the pair) and fixture F1.1 — but `OTHER:` only catches *uncaught* throws. A verdict function that catches broadly and maps an unrelated error onto a real refusal tag defeats it completely, and that is a two-line edit in the verdict function, which is code the pair's author writes. **There is no clean answer here**, for the same reason `coverage-claims.md:146` has none: the thing deriving the verdict is the thing under test. The partial mitigation is that the tag vocabulary is a closed union declared next to the gate rather than in the test, so the mapping is visible in the gate's own source and moves under review. Fresh readers should attack this joint first.

**2. Someone will make the custody report advisory-in-practice.** It runs at the end of a build, it is noisy under concurrency, and the first time it fires on a colleague's fixture the pressure will be to `|| true` it. This is `coverage-claims.md:149`'s prediction — *"the pressure will be to loosen that default, and that is where the model degrades in practice"* — and I have no structural defence, only the ranking in mitigation (a).

**3. The toolchain digest computed from the declaration.** If `identity.ts` reads `package.json` versions instead of hashing the loaded artifact, it is a declaration validating itself and it will pass forever. F3.2 exists precisely for this and it is the single most important fixture in the document, because this failure is invisible: the check runs, reports OK, and is measuring itself. Note the shape — it is failure 7 (source reading substituting for the boundary) reproduced *inside the mechanism designed to prevent it*.

**4. Floors get set from whatever the run happened to produce.** `measuredAs` proves the field exists; nothing proves the `min` was derived from a *deliberate* measurement rather than copied from yesterday's output. A floor set to last night's number is a ratchet that never fires. The `why` field is a prose mitigation and prose mitigations are what this document is arguing against. Honest status: **open, and cheaper to live with than the alternative**, because the failure mode is a floor that under-fires, which is where we already are.

**5. Mechanism 5 mutates a copy, so the mutant may be running against a stale build.** The worktree isolation that gives us guard 3 is the same thing that can leave the suite pointed at the wrong tree. This is `iteration-methodology.md:22`'s "a validation workflow graded a tree that did not contain the change" — the orchestrator's own failure — and the mitigation is the one recorded there: **the harness must print the tree digest it tested**, and F5.3 must assert it matches the mutated tree.

**6. My cost figures are estimates, not measurements.** Unlike `within-file-coverage.md`'s +88 ms, nothing above was benchmarked. The custody census in particular is projected from `ledger.py`'s pagination behavior and the 48-row at-rest count, not measured against a loaded oracle.

---

## What this handles worse than today

1. **Five new files in `src/testkit/` and `ctkr/ctkr/oracle/` that nobody is required to use.** Mechanisms 1, 4 and 5 are opt-in by construction — a test that does not call `discriminate` is not checked by it. That is failure 4's exact shape (a guard in a library the caller did not import), reproduced in three of my own five proposals. **Mechanism 2 is the only one that is structurally not opt-in**, which is why it ranks above the others despite costing more, and it is why I would not extend `discriminate`'s scope by making it enforce anything about tests that do not call it — a scanner over test files is the failure `seam.test.ts` already measured.
2. **It adds ceremony to a repo whose recent design work has been about deleting ceremony.** `coverage-claims.md` deleted a fidelity block and a ladder; `within-file-coverage.md` killed two of four candidate directions. This document adds five mechanisms, and the honest read is that mechanisms 1 and 4 have earned their place and 2, 3, 5 are bets.
3. **The toolchain digest is a total cache miss on both live stores**, on top of the one `within-file-coverage.md:212` already schedules. Same rebuild, so the cost is shared — but it lands on the farmOS rebuild either way.
4. **Custody reports will be wrong under concurrency**, and a report that is wrong often enough gets ignored, at which point it is worse than nothing because it exists as evidence of diligence. `within-file-coverage.md:214` makes the same admission about the census, and the same answer applies: there is no mechanism here that makes anyone read it.
5. **Nothing here touches wrongness.** Mechanisms 1–5 make an instrument unable to be silent or constant. An instrument that runs every check and applies the wrong predicate passes all five. Source-reading failures (7) are addressed only where a boundary is digestible; there is no mechanism proposed for "you read `buildForm` and concluded a value was recorded."

---

## The smallest shippable increment

Four steps. Steps 1 and 2 are worth doing even if the rest of this document is rejected.

**Step 1 (P1) — `src/testkit/discriminate.ts`, plus migrating `seam.test.ts:440-486` onto it.** One file, three rules, three fixtures (F1.1–F1.3). The migration is the evidence that the primitive is at least as strong as the hand-rolled version it generalizes. Ship the comment-invariance pair for `bring-up.sh`'s consumer in the same change — it is three lines and it is failure 5's regression fixture, which `tools/oracle_preflight.py:344` currently ships without.

**Step 2 (P1) — `src/testkit/floors.ts` and the smoke suite publishes what it ran.** 22 scripts, ~5 lines each, and `bun run smoke` starts emitting a machine-readable record with a check count derived from the pairs registered in step 1. Ship F4.1–F4.3. **Do this before step 3**, because step 3's preflight is itself an instrument and should be born with published floors rather than acquire them.

**Step 3 (P1) — toolchain identity, folded into the layer-2 key.** This is bead `0bm`, already filed, already carrying its evidence. Pin `tree-sitter-wasms` exactly; digest each loaded artifact; `toolchain.lock.json`; `scripts/toolchain-preflight.ts` with the parse-zero failure and the loud-skip distinction. Ship F3.1–F3.4, and **F3.2 is not optional** — without it the mechanism validates its own declaration.

**Step 4 (P2) — the custody bracket.** `ctkr/ctkr/oracle/custody.py`, called from `ctkr/ctkr/oracle/runner.py`, reported loudly, deleting nothing. Ship F2.1–F2.3. It is the highest-value item in the document and it is fourth because it is the only one whose *value depends on a judgment call* — whether the concurrency noise is tolerable — and that judgment is cheaper to make after steps 1–3 have made the noise measurable.

**Step 5 (P2, and only if steps 1–4 paid off) — `src/testkit/mutate.ts`.** It is the general form of what steps 1 and 2 buy narrowly. If steps 1 and 2 turn out to catch the cases that mattered, the mutation harness earns much less than the session's experience suggests, and that should change the decision rather than be argued away.

**Explicitly not in the increment:** a `Checker` class, a threshold registry, a size-sensitivity scanner, and any expansion of `CLAUDE.md` beyond three lines pointing at `src/testkit/`.

---

## Net

The session's lessons are already written down. They were written down before the session and violated during it, which means another document is the one intervention measurably known not to work here.

What converts them is small and mostly already invented in this repo, once each, by hand: the refusal-code non-constancy test at `src/ingest/seam.test.ts:440`, the published coverage row at `farmos-port/tools/ledger.py:425`, the production-size dialect fixture at `src/store/build.test.ts:211`, the parse-zero-is-a-failure guard at `farmos-port/tools/oracle_preflight.py:351`, and the ticket at `src/ingest/ticket.ts`. Each exists in exactly one place and is a discipline everywhere else. **The whole proposal is: make each of them the cheapest available option, once, and let the second use be an import rather than a rediscovery** — which is precisely the diagnosis `ledger.py:28` reached about the four ledgers, applied one level up to the instrument that measured them.

The one thing here that is genuinely new, and the one I would defend hardest, is mechanism 2's shape: **over a resource we do not own the write path to, the guard cannot be a library — it has to be the bracket.** That is the only proposal in the document that a careless agent cannot bypass by not reading it, and it is the one whose failure cost the session hours twice.
