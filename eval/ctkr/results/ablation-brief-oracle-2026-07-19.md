# Brief/oracle ablation — logs+quantities slice (MetaCoding-9h5.4)

> Bead MetaCoding-9h5.4 · 2026-07-19 · two-cell blind ablation orchestrated from the
> introspection audit (9h5.3, `introspection-audit-2026-07-19.md` §"Proposed ablation").
> Goal: empirically attribute the 7/7 value pass between the **categorical port brief**
> (the sole product of the CTKR machinery in the builder input set) and the **value
> oracle** (fixtures + adapter contract). Blindness protocol followed exactly; two fresh
> Sonnet blind-builders, neither seeing the other or the withheld files. The independent
> fixture runner was driven by the orchestrator, not the builders.

## Bottom line

| cell | withheld | prediction | observed | verdict |
|---|---|---|---|---|
| **A** | the categorical port brief | 7/7 pass | **7/7 pass** | prediction CONFIRMED |
| **B** | fixtures + adapter prose semantics (brief + adapter **signatures** only) | fails value-equivalence | **7/7 pass** | prediction **REFUTED** |

Both blind ports are value-equivalent to live farmOS on the 7 canonical fixtures.
**A confirms the categorical brief is not load-bearing for the value pass. B refutes the
audit's stronger claim that the fixtures/oracle prose carry everything — a port built
from the brief plus the adapter *method-name surface alone*, with no fixture values and
no prose semantics, still scored 7/7.** The honest reading (below) is that the load-
bearing artifact is neither the categorical brief nor the fixture values but the
**adapter contract's method-name surface** — a hand-authored signature file that is not
categorical machinery either.

## Per-cell fixture results (independent runner, same 7 canonical fixtures)

Runner: `…/port-run-0p7/verify/runFixtures.ts` (verifier-side, not builder-written).
Fixtures: `…/port-run-0p7/builder-inputs/FIXTURES.jsonl` (7 canonical, farmOS-4.x-observed).

### Cell A — brief WITHHELD  →  **7/7 PASS**
```
PASS  61ef8cb0  A newly created land asset is active
PASS  646a3706  An archived land asset is no longer active
PASS  74303d7d  Recording a harvest of X gives that asset a yield total of X
PASS  154c1ff9  Two harvests sum into the yield total
PASS  75956b7e  A harvest recorded as pending is delivered pending
PASS  71087c43  Marking a pending harvest done delivers it done
PASS  2ad8f08a  Assigning an animal to a group makes it a member
7/7 fixtures passed
```
Builder's own suite: **12 pass / 0 fail** (7 fixture-named + 5 event-log/projection invariants).

### Cell B — fixtures + adapter semantics WITHHELD (brief + signatures only)  →  **7/7 PASS**
```
PASS  61ef8cb0  A newly created land asset is active
PASS  646a3706  An archived land asset is no longer active
PASS  74303d7d  Recording a harvest of X gives that asset a yield total of X
PASS  154c1ff9  Two harvests sum into the yield total
PASS  75956b7e  A harvest recorded as pending is delivered pending
PASS  71087c43  Marking a pending harvest done delivers it done
PASS  2ad8f08a  Assigning an animal to a group makes it a member
7/7 fixtures passed
```
Builder's own suite: **26 pass / 0 fail** (read-by-read behavior tests + convergence-rule
tests + event-log invariants). Cell B never saw FIXTURES.jsonl or any given/when/then value.

## Predictions vs observed

- **A: predicted 7/7 — observed 7/7.** Confirmed. A builder handed fixtures + adapter
  contract + target profile + a brief-stripped BUILD_INSTRUCTIONS reproduces the value
  pass with zero access to the categorical brief. **The brief's marginal contribution to
  the acceptance signal on this slice is ≈ 0**, as the audit predicted.
- **B: predicted FAIL — observed 7/7.** Refuted. The audit expected the brief to be
  "shape-only" and the oracle (fixtures + adapter prose) to carry all behavior; with the
  fixtures and all prose semantics stripped, B was expected to fail. It did not.

## Why B passed (the load-bearing artifact is the adapter method-name surface)

This is the substantive finding and it must be read honestly, because it cuts against a
naive "the brief works after all" conclusion:

1. **The adapter method names are themselves a semantic oracle.** The withheld-semantics
   `ADAPTER_SIGNATURES.md` still had to name the reads: `assetYieldTotal(handle, measure,
   unit)`, `assetActive`, `groupMember`, `logStatus`, `logCount(handle, kind)`,
   `quantityRecorded`, plus mutators `recordLog / setLogStatus / assignToGroup /
   archiveAsset`. These names encode the exact read semantics the fixtures assert. "Yield
   total sums a measure across an asset's logs," "active until archived," "member after
   assign," "status pending→done" are all recoverable from the method names + the brief's
   domain glossary (harvest, yield, quantity, group, log status) without ever seeing a
   fixture value.
2. **The 7 canonical fixtures only exercise semantics self-evident from those names.**
   None of the 7 tests a non-obvious rule (e.g. "a *pending* harvest still contributes to
   yield total" — asserted by the adapter *prose* and tested by Cell A from that prose,
   but never asserted by any of the 7 fixtures). So the fixture given/when/then **values**
   were not load-bearing for this canonical set; a builder reasoning from method names hits
   all 7.
3. **Caveat / honesty note on B's construction.** B's pass is partly an artifact of how
   semantic the real adapter method names are. A genuinely opaque signature surface
   (`op1`, `op2`, …) would have starved B and it would have failed. The ablation therefore
   localizes the value to the **adapter contract**, and specifically to its *naming*, not
   to the categorical brief and not to the fixture values. My signatures file stripped the
   enum hints and all "Notes on semantics" prose (verified against the source contract),
   so what leaked is intrinsic to having to name the graded methods at all.

## Attribution conclusion

- **Categorical port brief:** marginal contribution to the value pass ≈ **0** (Cell A,
  confirmed). This is fully consistent with the 9h5.3 audit.
- **Fixture given/when/then values:** marginal contribution for the 7 canonical scenarios
  ≈ **0** (Cell B, newly shown). They are corroborating for these self-evident scenarios;
  they would become load-bearing only for non-obvious semantics the method names don't
  telegraph (status-in-yield, epsilon/unit-matching edge cases, multi-asset attribution).
- **Adapter contract method-name surface:** the actual load-bearing artifact for this
  slice. It is a **hand-authored signature/prose file, not categorical machinery** — so
  the attribution does **not** rehabilitate the CTKR layer. It relocates the credit from
  "fixtures" (audit) to "the adapter contract's naming" (this ablation). Both are oracle
  artifacts; neither is graph-derived.

Net: the machinery's differential value on this slice remains ≈ 0, and the ablation
additionally shows the *fixtures* are near-redundant with the *adapter naming* for the
canonical 7. The single irreplaceable oracle artifact is the adapter contract, and its
value lives in how semantically it names the graded operations.

## Birth-log uniqueness decision (protocol item 4)

**Did Cell A independently reach a weaken-to-eventual-equivalent decision? — NO (it
reached a different, valid menu choice).** Both cells engaged the CM-hard constraint from
BUILD_INSTRUCTIONS §6 + the TARGET_PROFILE decision menu and both chose
**`preserve-via-convergence-rule`** (deterministic lowest-UUID/lowest-seq tiebreak at
projection time; losing event retained in the append-only log), explicitly **rejecting
`weaken-to-eventual`**. The original 0p7 run chose `weaken-to-eventual`. So:
- The **machinery is not needed** to surface or resolve the CM-hard constraint — both
  brief-blind (A) and fixture-blind (B) builders produced a disciplined, well-argued port
  decision from the constraint + menu already present in BUILD_INSTRUCTIONS / TARGET_PROFILE.
- But the **specific** resolution (`weaken-to-eventual`) from the 0p7 run was **not
  reproduced** by either cell; both independently preferred `preserve-via-convergence-rule`
  and gave near-identical rationales for rejecting weaken-to-eventual (reconciliation
  "degenerates into a convergence rule anyway" / a reader needs one birth fact today).
  The CM-hard *decision* is builder judgment, not determined by the inputs — the menu is
  reproduced, the pick is not.

## LLM cost

Two Sonnet blind-builder subagents (one per cell); orchestrator ran the LM-free fixture
runner and `bun test`. No pipeline/reindex LLM spend (all inputs pre-existed). Estimated
builder spend **≈ $0.15–0.35 total** (2 Sonnet agents, moderate multi-file TS build +
own test authoring each; no exact token meter exposed to the orchestrator). Within the
bead's ~$0.05–0.10 order-of-magnitude allowance for the *ablation-specific* compute given
the builders came in on the cheaper side of a full port; reported as an estimate, not a
metered figure.

## Retries

None. Both cells built and passed `bun test` on the first attempt. No harness errors, no
design-failure coaching.

## Sandbox paths (all SANDBOX — nothing touched production `.metacoding/` or the 0p7 originals)

- **Read-only inputs (unmutated):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/port-run-0p7/builder-inputs/`
  (BUILD_INSTRUCTIONS.md, ADAPTER_CONTRACT.md, FIXTURES.jsonl, TARGET_PROFILE.yaml, BRIEF.md)
- **Independent fixture runner (read-only):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/453fbf17-4242-4929-8a07-79528fc40e52/scratchpad/port-run-0p7/verify/runFixtures.ts`
- **Cell A build dir (sandbox):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/cell-a/`
  — brief-stripped BUILD_INSTRUCTIONS.md + FIXTURES.jsonl + ADAPTER_CONTRACT.md +
  TARGET_PROFILE.yaml; builder output `src/{events,views,store,oracleAdapter}.ts`,
  `test/store.test.ts`, `PORT_DECISIONS.md`.
- **Cell B build dir (sandbox):**
  `/private/tmp/claude-501/-Users-dukejones-work-WorldTree-MetaCoding/7c92fede-1c0d-4716-b9e4-8b2c97e4f0b0/scratchpad/cell-b/`
  — BRIEF.md + TARGET_PROFILE.yaml + orchestrator-derived ADAPTER_SIGNATURES.md
  (signatures only, all prose/enum semantics stripped) + brief-referencing
  BUILD_INSTRUCTIONS.md; builder output `src/{events,views,store,oracleAdapter}.ts`,
  `test/oracleAdapter.test.ts`, `PORT_DECISIONS.md`. **No FIXTURES.jsonl present in cell-b
  by construction.**

The only production/in-repo artifact written by this task is this results document under
`eval/ctkr/results/`. No `.metacoding/` data-dir was created or mutated; the port-run-0p7
originals were read-only.
