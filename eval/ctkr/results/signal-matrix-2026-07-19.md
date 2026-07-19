# Signal-attribution matrix — logs+quantities slice, hardened pack (MetaCoding-9h5.8)

> Bead MetaCoding-9h5.8 · 2026-07-19 · judged on the **hardened** value-oracle
> pack (9h5.7: old-7 canonical + new-10 non-obvious = **17 fixtures**). Extends
> the 9h5.4 two-cell ablation to a matrix that measures the marginal signal of
> each builder input and tests the deterministic-parsing-beats-pure-LLM
> hypothesis. Blindness protocol per 9h5.4 §protocol: one fresh blind Sonnet
> builder per new cell, each confined to its own cell dir (forbidden from farmOS
> source, the MetaCoding repo, and every other cell); the independent fixture
> runner (`runFixtures.ts`, verifier-side) was driven by the orchestrator, not
> the builders. Single run per cell — stated where it matters.

## Bottom line

- **The hardened pack discriminates — but through exactly ONE new fixture.** Of
  the 10 new fixtures, 9 are corroborating (the event-log paradigm + the adapter
  method-name surface already induce them); the lone discriminator is
  **`ce015be4` group-reassignment-latest-wins** — the semantic that *no*
  canonical fixture and *no* unambiguous prose conveys. Every port built without
  a fixture that exercises it gets it wrong.
- **The fixture VALUES are the load-bearing input for the non-obvious
  semantics.** Give the builder the hardened fixtures (which include the
  latest-wins scenario) and it scores **17/17 with fully opaque method names and
  no prose** (Cell 1). Adding prose (Cell 2) changes nothing: also 17/17. The
  fixtures subsume both the naming and the prose channel.
- **Pure-LLM from raw farmOS source (Cell 4) = 14/17, and it fails on a
  DIFFERENT axis than the pipeline builds.** It fails the three *oracle-adapter
  conventions that are not present in farmOS source at all* (yield includes
  pending; yield sums across all log kinds) — because farmOS has no "yield total"
  concept; that is an adapter invention. But it **passes latest-wins**, which
  every pipeline/prior build fails, because it modeled group membership from real
  farmOS semantics.
- **The deterministic-parsing-beats-pure-LLM hypothesis is not supported on this
  slice.** Neither strictly beats the other (16/17 pipeline vs 14/17 pure-LLM),
  and the pipeline's 2-fixture edge comes entirely from the hand-authored
  **adapter contract** (its method names + prose leak the yield conventions), NOT
  from the categorical/AST machinery. The CTKR machinery's marginal contribution
  to the value pass remains **≈ 0**, consistent with the 9h5.3 audit and the
  9h5.4 ablation. Cell 3 (data-edge brief) adds **≈ 0** builder-visible value
  signal — shown by direct edge inspection (below).

## The matrix (independent runner, hardened 17-fixture pack)

old-7 = the canonical pack (9h5.4); new-10 = the 9h5.7 hardening fixtures.
The new-10 column is the discriminator — old-7 is 7/7 for everyone (confirming
9h5.4: the canonical pack cannot separate input sets).

| cell | builder inputs (value channels present) | old-7 | new-10 | total | fixtures failed |
|---|---|---|---|---|---|
| **0p7-original** (reference, full input) | brief + adapter contract (names+prose) + canonical-7 fixtures + profile | 7/7 | 9/10 | **16/17** | latest-wins |
| **9h5.4 Cell A** (brief withheld) | adapter contract + canonical-7 fixtures + profile | 7/7 | 9/10 | **16/17** | latest-wins |
| **9h5.4 Cell B** (fixtures + prose withheld) | brief + adapter **signatures** (names only) | 7/7 | 9/10 | **16/17** | latest-wins |
| **Cell 1 — opaque-names** (new) | **hardened** fixtures + opaque signatures (op1..op11, no prose) | 7/7 | **10/10** | **17/17** | none |
| **Cell 2 — prose-only** (new) | **hardened** fixtures + opaque signatures + full semantic prose | 7/7 | **10/10** | **17/17** | none |
| **Cell 3 — brief+data-edges** (new) | data-edge brief + signatures (no fixtures/prose) — *see determination* | — | — | **≈16/17 (det.)** | latest-wins (data edges do not carry it) |
| **Cell 4 — pure-LLM** (new) | raw farmOS source + signatures (no prose) + profile; **no fixtures, no brief** | 7/7 | 7/10 | **14/17** | pending-in-yield, logcount+yield, cross-kind-yield |

The three prior builds (0p7-original, Cell A, Cell B) were **re-judged** on the
hardened pack for this report; all three, previously 7/7 on canonical, land at
16/17 — each failing the *same* single fixture, `ce015be4`. Their group-
membership read is additive ("is there any assignment to this group") rather than
latest-wins ("is this group the most recent assignment"). A single assign→member
canonical fixture only tests additive; nothing tested revocation until 9h5.7.

### Cell 4 failure detail (pure-LLM)
```
FAIL 73ed7c69 pending contributes to yield    got 0  == 5   (excluded pending logs)
FAIL d8607818 logcount+yield include pending  got 4  == 6   (excluded the pending 2kg)
FAIL 03e4dd80 yield sums across all kinds      got 5  == 8   (summed harvest only, not input)
PASS ce015be4 group reassignment latest-wins  ✓            (modeled membership as latest-replaces)
```
The Cell 4 builder self-documented these exactly (its `README.md`): *"the
provided farmos-source/ tree does not include a yield-total computation … I
inferred: sum quantities across all logs of `kind === 'harvest'`"* and the
pending filter *"is inferred from farmOS's general convention that a pending log
is [not yet realized]."* It also noted farmOS tracks group membership via
assignment logs and chose a scalar latest-replaces model — which is why it is the
only build that passes `ce015be4`. Its failures are precisely where the oracle's
aggregation convention is **underivable from the source**; its success is where
its natural modeling matched.

## Marginal-signal attribution (per input)

| input channel | marginal signal for the VALUE pass | evidence |
|---|---|---|
| **Fixture given/when/then VALUES** | **HIGH — the load-bearing input.** With the hardened fixtures present, the port hits 17/17 regardless of names or prose. | Cell 1 (opaque names, no prose) = Cell 2 (opaque + prose) = **17/17**. |
| **Adapter method-name surface** | **Medium — carries the self-evident semantics, but NOT latest-wins.** Names alone (Cell B, no fixtures/prose) = 16/17. | 9h5.4 Cell B re-judged = 16/17; names convey yield/count/status/archive but leave membership ambiguous. |
| **Semantic prose ("Notes on semantics")** | **≈ 0 given fixtures.** Cell 1 (no prose) already 17/17; Cell 2 (prose) adds nothing. Prose is a *weaker* carrier than fixtures — the real contract's "reflects the latest membership assignment" was ambiguous enough that the original builds still failed latest-wins. | Cell 1 == Cell 2 == 17/17. |
| **Categorical port brief** | **≈ 0.** Confirmed again — 9h5.4 Cell A (brief withheld) = 16/17. | 9h5.4 Cell A re-judged = 16/17. |
| **Deterministic data-flow edges (vju READS_FIELD/WRITES_FIELD)** | **≈ 0 builder-visible for the value pass.** The edges materialize but point at Drupal/test/birthdate internals, not the graded conventions. | Cell 3 determination + direct edge inspection (below). |
| **Raw farmOS source (pure-LLM)** | **Carries what is IN the source (latest-wins) but not the oracle's arbitrary aggregation conventions.** | Cell 4 = 14/17; passes latest-wins, fails the two yield conventions farmOS source does not contain. |

## Cell 3 — deterministic-parsing delta (evidence-backed determination)

**Cell 3 was NOT run as a fresh blind build.** A faithful data-edge brief
requires the *full-signal* graph (scip-php `CALLS`/`REFERENCES`/`CONSTRUCTS`
**plus** the vju tree-sitter heuristic `READS_FIELD`/`WRITES_FIELD`), scoped
subsystem decomposition, and the 6-stage LLM brief pipeline — out of scope for a
single-session run. Instead the deterministic data-flow layer was rebuilt and its
**content inspected**, which settles the question the cell asks ("do the new data
edges add builder-visible value signal vs the shape-only brief, 9h5.4 Cell B?").

Rebuild (SANDBOX): `metacoding index` (tree-sitter PHP lane) over the farmOS
profile source (772 PHP files) → data-dir with the vju heuristic edges. Confirmed
the exact vju numbers: **READS_FIELD 0 → 1089, WRITES_FIELD 0 → 252** (CALLS = 0 —
the tree-sitter lane cannot emit them, confirming a real brief regen would also
need scip-php). Inspecting the edges whose source is in the **log** modules:

- `WRITES_FIELD` from log modules (6): five are **test-scaffolding** field writes
  (`setUp` writes `$this->user`, `$this->materialTypes`, `$this->testLogs`,
  `$this->quantity`) and one is `syncBirthChildren → birthdate` (the birth hook
  syncing an asset's date-of-birth).
- `READS_FIELD` from log source, non-test (11): Views-filter internals
  (`query` reads `options`, `base_table`), validators (`validate` reads
  `message`, `entityTypeManager`), `getLabel → label`, and the birth hook
  (`syncBirthChildren` reads `asset`, `parent`, `timestamp`, `birthdate`,
  `mother`).

**None of these edges encode a graded value convention** — not yield-summing,
not cross-kind aggregation, not pending-contributes, not group-membership
latest-wins. They are PHP `$this->field` accesses inside plugin/hook/test
classes; the graded semantics are **oracle-adapter conventions** (how the adapter
sums quantities and reads the latest assignment log), which are not PHP field
accesses anywhere in farmOS. A data-edge-enriched brief therefore adds
plugin/test-internal facts but still lacks the value conventions — a builder given
brief + signatures (no fixtures, no prose) would behave like 9h5.4 Cell B:
**≈ 16/17, failing latest-wins.** Deterministic-parsing delta on this slice
**≈ 0**. (This is the same root cause the 9h5.3 audit named: the value behavior
does not live in farmOS's structural graph.)

## Verdicts on Duke's three questions

1. **Does deterministic parsing beat pure-LLM?** No, not on this slice. The
   pipeline builds (16/17) and pure-LLM (14/17) fail on different axes; the 2-fixture
   gap is bought by the hand-authored **adapter contract**, not by the CT/AST
   machinery or the data edges (Cell 3 ≈ 0 delta; Cell B 16/17 shows the names
   alone carry the gap).
2. **Machinery vs pure-LLM.** Pure-LLM matches the pipeline within one axis and
   *beats* it on the semantic (latest-wins) that lives in real farmOS source. The
   machinery-attributable value on the value pass is ≈ 0; the irreplaceable
   artifact is the **oracle** (adapter contract + a fixture pack that covers the
   non-obvious semantics), which is not categorical machinery.
3. **The magic combination.** **Adapter method-name signatures + a fixture pack
   that covers the non-obvious semantics.** That pair = 17/17 (Cell 1). Prose,
   the categorical brief, and the deterministic data edges each add ≈ 0 on top.
   The lever for the fan-out is therefore *fixture coverage of non-obvious
   semantics*, not more machinery — every non-obvious rule needs a fixture that
   exercises it (as `ce015be4` proved by being the only discriminator among 10).

## Honesty notes

- **Single run per cell.** Cells 1, 2, 4 are one blind Sonnet build each; the
  3 prior builds were re-judged (read-only), not rebuilt. No statistical spread.
- **Cell 3 is a determination, not a blind run** (see above) — labeled as such;
  the full brief-pipeline regen (scip-php + heuristic merge + 6 LLM stages) was
  not performed. The reference it is compared against, 9h5.4 Cell B, is a real
  16/17 build.
- **Cells 1 & 2 both 17/17 is partly "teaching to the test":** the hardened
  fixtures they were given literally contain the latest-wins given/when/then. That
  is by design — the fixtures ARE the behavioral spec builders implement — but it
  means these cells measure "do names/prose add anything *beyond* fixtures" (answer:
  no), not "can the builder discover latest-wins unaided." The unaided discovery
  question is answered by Cell 4 (yes, from source) and Cell B (no, from names).
- **Spend (estimated, not metered):** 3 new Sonnet blind builders ≈ **$0.20 each
  (~$0.60 total)**; the tree-sitter index and all fixture-running are LM-free
  ($0); Cell 3's LLM pipeline was **not** run. No cell approached the $3 abort cap.
  Builder retries were not instrumented; all three builds passed their own
  `bun test` (25 / 24 / 29 pass) and were judged on the independent runner.
- **Cell 4 passes its own 29 tests but scores 14/17 on the independent pack** —
  its tests encode its (wrong) yield inference. This is exactly why the independent
  oracle, not the builder's suite, is the acceptance signal.

## Fixture families (ids)

- **old-7 (canonical):** 61ef8cb0, 646a3706, 74303d7d, 154c1ff9, 75956b7e, 71087c43, 2ad8f08a
- **new-10 (hardening):** 73ed7c69 (pending→yield), 6c91f0f8 (measure/unit exclusion), 265ced03 (multi-asset), d8607818 (logcount+status), fba4a962 (logcount by kind), 03e4dd80 (cross-kind yield), 680138d8 (archived retains), **ce015be4 (latest-wins — the discriminator)**, 6547dc6e (dup logs), 7d9d68a9 (multi-measure)

## Artifacts & sandbox paths (ALL sandbox unless noted)

- **Hardened pack (committed, in-repo, 9h5.7):**
  `ctkr/ctkr/oracle/data/farmos_hardening_fixtures.jsonl` (10) +
  `farmos_hardening_observations.jsonl`; canonical 7 unchanged in
  `farmos_core_fixtures.jsonl`.
- **Matrix workspace (SANDBOX):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/matrix-9h5.8/`
  — `FIXTURES_HARDENED.jsonl` (17), `runFixtures.ts`, `opaque_wrapper.ts`,
  `cell1/` `cell2/` `cell4/` (each `inputs/` + `build/`), `cell4/inputs/farmos-source/`.
- **Reused 9h5.4 builds (SANDBOX, read-only):** `…/7c92fede-…/scratchpad/cell-a`,
  `…/cell-b`; 0p7-original `…/453fbf17-…/scratchpad/port-run-0p7/port-build`.
- **Cell-3 data-edge graph (SANDBOX):** `/private/tmp/farmos-cell3-2026-07-19/`
  — `farm-src/` (farmOS profile source, docker-cp'd from farmos-oracle-www),
  `dd/` (tree-sitter data-dir: READS_FIELD 1089, WRITES_FIELD 252, CALLS 0).
  Source graph copy referenced but not mutated: `/private/tmp/farmos-rebuild-2026-07-18/farmos-data-v2`.
- **Live oracle:** farmOS 4.x Docker `farmos-oracle-www` @ `http://localhost:8095`
  (admin/admin) — used to record the 9h5.7 fixtures; read-only for 9h5.8.

The only in-repo committed artifacts from 9h5.8 are this report and (from 9h5.7)
the hardening pack + the adapter timestamp fix. No production `.metacoding/`
data-dir was created or mutated; no push/merge; beads left open.
