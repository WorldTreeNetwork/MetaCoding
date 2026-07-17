# eval/ctkr — CTKR eval harnesses

This directory holds eval harnesses and the calibration pipeline:

- **`functor_eval.ts` / `run_functor_eval.ts` / `functor_eval.test.ts`** —
  Phase-2b functor-discovery eval (§5 + §8.2 of
  `docs/design/ct-functor-discovery.md`). See
  [Functor-discovery eval](#functor-discovery-eval-phase-2b) below.
- **`run_role_equivalent_eval.ts`** — Phase-2a `ctkr.role_equivalent` retrieval
  eval (documented from [role_equivalent eval](#role_equivalent-eval-harness) on).
- **`calibration_schema.py` / `calibration_ingest.py` / `calibration_report.py`** —
  The port-loop calibration pipeline (see [Calibration](#calibration) below).

---

## Functor-discovery eval (Phase 2b)

Validates the production functor search (`src/ctkr/functorSearch.ts`) against
the §5 control suite with **depth-2 hom-profile seeds** (the lever that clears
the discovery gate — see `docs/notes/functor-spike/2hop-findings.md`).

### How to run

```sh
# CI gate (asserts the must-pass thresholds):
bun test eval/ctkr/functor_eval.test.ts

# full report (prints tables, writes eval/ctkr/results/functor-<ts>.md):
bun run eval/ctkr/run_functor_eval.ts
```

### CI-runnable fixtures (no SCIP index)

The spike measured the gate on the real ~4.7k-symbol scip-indexed MetaCoding
corpus. That is not CI-runnable (needs `--scip` indexing + `ctkr hom-profiles
--depth 2` + the runner). This harness instead **synthesizes** a small,
deterministic multi-module "codebase" graph in-process (`buildBaseGraph`),
computes its depth-2 hom-profiles with an exact TS mirror of
`ctkr/ctkr/hom_profiles.py` (`computeDepth2Profiles`), and derives the rename
fork / dropout forks / null-model shuffles / degraded seeds / cross-framework
variants from it. Everything is seeded and byte-stable.

### Controls (§5 + §8.2)

| control | §  | must-pass? | what it checks |
|---|---|---|---|
| rename fork | 5.1 | yes | cov ≥ 0.95, fid ≥ 0.98, **automorphism-aware** correctness ≥ 0.90 (orbits via one color-refinement round) |
| automorphism demo | 5.1/8.2 | yes | a reversed-order orbit forces exact-match < orbit-correct, proving the WL machinery is load-bearing |
| null model | 5.3 | yes | fidelity as **LIFT** over (a) degree-matched edge-rewire, (b) random kind-compatible map, (c) permuted-seed control |
| cycle consistency | 5.6 | yes | `G(F(s)) = s` fraction on the rename fork ≥ 0.90 |
| edge-dropout | 5.2 | tracked | fidelity/coverage degrade gracefully as p ∈ {5,15,30}% |
| seed-degradation | 5.7 | tracked | correctness is structure-carried; margin honest (wrong ≤ correct) |
| determinism / anytime | 5.5 | yes | byte-identical reruns; zero-budget subset-or-equal |
| cross-framework | 5.4 | tracked baseline | same-role recall/precision across analogous "frameworks" |

### Latest numbers (synthesized fixture, depth-2)

- rename fork: coverage **1.000**, fidelity **1.000**, orbit-correctness
  **1.000**, cycle-consistency **1.000** — reproduces the spike's depth-2 gate.
- null model: real fidelity **1.000** vs rewire **0.42**, random-map **0.06**
  (lift 0.58 / 0.94) — clear separation from the noise floor.
- automorphism demo: exact **0.333** vs orbit **1.000** (gap 0.667).
- cross-framework baseline: recall **0.65**, precision **1.00** (analogous, not
  isomorphic — the number the sharper-seed re-run improves on).

The **real** 9-cluster corpus (`role_equivalent_truth.yaml`) is the production
baseline target; re-run the controls against its depth-2 functor artifacts once
they exist. The synthetic cross-framework fixture is the CI stand-in.

---

## role_equivalent eval harness

Evaluation harness for `ctkr.role_equivalent` (Phase 2a of the CT pipeline).
The tool finds symbols across the corpus with structurally similar hom-profiles
to a query symbol.  This harness measures how well that retrieval recovers
known ground-truth equivalences.

## How to run

```sh
# from the MetaCoding project root
bun run eval/ctkr/run_role_equivalent_eval.ts
```

The harness writes a Markdown report to `eval/ctkr/results/<timestamp>.md`.

**Until `ctkr.role_equivalent` is implemented**, the harness runs against a
stub client that returns empty results.  All metrics will be 0.0.  This is
expected — it proves the plumbing works.

When the tool ships, swap in `McpRoleEquivalentClient` (see the comment block
in `run_role_equivalent_eval.ts` marked `TODO(23q.3)`).

## Ground truth

The ground-truth corpus lives in `role_equivalent_truth.yaml`.  It defines
clusters of symbols from different repos that a human analyst judges to occupy
the same structural role.

### Format

```yaml
clusters:
  - id: agent
    description: "..."
    members:
      - { repo: "crewAI", qualified_name: "crewai.agent.core.Agent" }
      - { repo: "ag2",    qualified_name: "autogen.agentchat.conversable_agent.ConversableAgent" }
      ...
```

**`repo`** is the directory name under `$ORCHESTRATORS_ROOT/` (defaults to
`~/projects/Orchestrators/`; set the env var to point harness + tests at a
different corpus root).

**`qualified_name`** follows the convention:

- Python: `<top_level_package>.<dotted.module.path>.<ClassName>`
  e.g. `crewai.agent.core.Agent` comes from
  `~/projects/Orchestrators/crewAI/lib/crewai/src/crewai/agent/core.py`,
  class `Agent`.

- TypeScript: `<npm-package-name>.<relative.module.path>.<ClassName>`
  e.g. `@mastra/core.agent.agent.Agent` comes from
  `~/projects/Orchestrators/mastra/packages/core/src/agent/agent.ts`,
  class `Agent`.

### How to update the ground truth

1. Find the symbol in the source tree (grep for `^class Foo` in `*.py` / `*.ts`).
2. Confirm the module path produces the right `qualified_name` under the
   convention above.
3. Decide which cluster it belongs to by checking structural role, not name:
   does it own the LLM call loop? → `agent`.  Does it coordinate multiple
   agents? → `orchestrator`.  Etc.
4. Add the member to `role_equivalent_truth.yaml`.
5. Re-run the harness to verify the YAML loads cleanly.

### Selection criteria

Each cluster was selected by these rules (enforced by the curator, not by code):

- **Span**: the cluster must have members from ≥ 3 repos (or ≥ 2 repos where
  one repo has multiple distinct variants).
- **Primary role**: each member must be a *primary* structural entity in its
  framework — not a utility, mixin, or adapter.
- **Structural position**: members should occupy the same position in their
  framework's object graph (similar hom-profile: in-degree mix, out-degree mix,
  neighbor-kind frequencies).  Name similarity is neither required nor
  sufficient.
- **Existence confirmed**: every `qualified_name` was confirmed to exist by
  direct `grep` of the source tree before being added.

Current clusters: `agent`, `orchestrator`, `task`, `tool`, `memory`, `context`,
`step_node`, `planner`, `session`.

## How precision and recall are computed

For a query member `m` in cluster `C`:

- **relevant set** = all other members of `C` (i.e., `C \ {m}`).
- **retrieved set @k** = the top-k results returned by `ctkr.role_equivalent(m, k, cross_repo_only=true)`.

```
precision@k(m) = |retrieved@k ∩ relevant| / k
recall@k(m)    = |retrieved@k ∩ relevant| / |relevant|
```

These are averaged over all members of the cluster (macro-average within
cluster), then averaged over all clusters (macro-average across clusters) to
produce corpus-level metrics.

**Why cross_repo_only=true?**  The hom-profile similarity metric will
trivially find the symbol itself and same-repo variants.  Cross-repo retrieval
is the harder and more useful case — it tests whether the metric generalises
across naming and style differences.

**Why k = 5, 10, 20?**  k=5 is strict (only high-confidence hits count);
k=20 is lenient (tests recall depth).  All three are reported so the report
shows the full precision-recall tradeoff.

## Caveats

1. **Human-curated, not an oracle.**  The ground truth reflects the analyst's
   judgement about structural equivalence.  It is inherently incomplete and
   potentially inconsistent.  Use it to detect gross failures and track
   improvement over time, not as a definitive correctness criterion.

2. **Qualified-name lookup may not match the graph's `symbol_id`.**  The
   MetaCoding graph builds `symbol_id` from SCIP descriptors, which may differ
   from the Python/TS module path.  The harness currently passes `qualified_name`
   directly to the tool; the tool implementation must handle the mapping.
   If the tool uses FTS5 prefix search internally, most names will resolve
   correctly, but aliases, re-exports, and `__init__.py` re-exports may cause
   mismatches.  Document any such mismatches when flipping the stub.

3. **Cross-repo only is approximate.**  Some repos share code (e.g. `ag2` is
   the maintained fork of `autogen`).  Marking those as distinct repos is
   correct for the eval but the hom-profile metric may see them as trivially
   similar — they share code history.  Flag such pairs in the cluster
   description if relevant.

4. **Cluster boundaries are debatable.**  `planner` overlaps with `agent`
   (TaskWeaver's `Planner` IS-A `Role`).  `orchestrator` overlaps with `session`.
   These are known ambiguities.  The eval still works because precision/recall
   is computed within clusters: a hit in the wrong cluster simply doesn't count
   as a hit.

## What's needed to flip the stub to real

See `run_role_equivalent_eval.ts` for the `McpRoleEquivalentClient` skeleton.
To activate it:

1. `ctkr.role_equivalent` must be registered in `src/mcp/ctkr-tools.ts` (Phase 2a).
2. The tool must accept `{ qualified_name, k, cross_repo_only }` and return
   `[{ qualified_name, repo, score }]`.
3. Uncomment `McpRoleEquivalentClient` and replace `StubRoleEquivalentClient`
   in the `main()` function.
4. Set `mcpServerUrl` to wherever the MCP server is listening.
5. Run the harness and check that metrics are non-zero.

The first non-zero run establishes the baseline.  Subsequent runs track
regression and improvement as the hom-profile algorithm is refined.

---

## Calibration

Implements cross-cutting #3 from `docs/design/port-loop-plan.md`: treat every
port run as a training step. The pipeline tracks whether the intention-load
classifier's predictions match what the builder actually did, and uses that
signal to tune the D/R dials and prompt versions.

### The loop

```
predict (intention_load.parquet)
    → port (builder works from the brief)
    → observe (record builder_consulted_evidence per element)
    → ingest (calibration_ingest.py → calibration.parquet)
    → report (calibration_report.py → precision/recall + dial sweep)
    → tune (adjust d_hi, r_min in intention_normalization.json)
    → version prompts
    → re-run harvest → repeat
```

### Files

| File | Purpose |
|---|---|
| `calibration_schema.py` | Schema, reader, writer, `append_calibration` |
| `calibration_ingest.py` | CLI: port-run JSONL + `intention_load.parquet` → append to `calibration.parquet` |
| `calibration_report.py` | CLI: per-class precision/recall + dial-sensitivity sweep |
| `tests/test_calibration.py` | Hermetic pytest suite (synthetic fixtures) |

### calibration.parquet schema

One row per (port_run, element) observation.

| Column | Type | Meaning |
|---|---|---|
| `calibration_row_id` | str | Deterministic blake3 id |
| `port_run_id` | str | Identifies the port-run batch |
| `element_id` | str | FK → `intention_load.parquet` |
| `predicted_load_class` | str | `structure-clear` \| `intention-critical` \| `ambiguous` |
| `structural_determinacy` | float | D score from `intention_load` |
| `intention_richness` | float | R score from `intention_load` |
| `drivers` | list[str] | Driver explanations from `intention_load` |
| `builder_consulted_evidence` | bool\|null | Did the builder read the evidence section? |
| `miss_type` | str\|null | `none` \| `needed-evidence-not-given` \| `evidence-given-not-needed` \| `wrong-class` \| `builder-error` |
| `source` | str | `port-run` \| `human-review` |
| `recorded_at` | str | ISO-8601 |
| `schema_version` | int | |

### Observation JSONL format

Each line is a JSON object emitted by the port runner (or entered manually
during human review):

```json
{"element_id": "...", "builder_consulted_evidence": true, "miss_type": "needed-evidence-not-given", "source": "port-run"}
```

`miss_type` is derived automatically when absent:

| predicted | builder_consulted_evidence | derived miss_type |
|---|---|---|
| `structure-clear` | `false` | `none` |
| `structure-clear` | `true` | `needed-evidence-not-given` |
| `intention-critical` | `true` | `none` |
| `intention-critical` | `false` | `evidence-given-not-needed` |
| `ambiguous` | `true` | `none` |
| `ambiguous` | `false` | `evidence-given-not-needed` |
| any | `null` | `null` (unknown) |

### How to run

```sh
# From eval/ctkr/

# Ingest a port run's observations:
uv run python calibration_ingest.py \
    --port-run-id run-2026-07-17-001 \
    --observations path/to/obs.jsonl \
    --load-parquet /path/to/.metacoding/ctkr/intention_load.parquet \
    --out calibration.parquet

# Generate the report:
uv run python calibration_report.py \
    --calibration calibration.parquet \
    --load-parquet /path/to/.metacoding/ctkr/intention_load.parquet \
    --out-json calibration_report.json

# Run tests:
uv run pytest tests/
```

### What the report shows

- **Per-class precision** — fraction of predictions for each load class confirmed
  correct by the builder's actual consultation behaviour (`miss_type == "none"`).
  Recall is not directly computable without an explicit `observed_class` label;
  add that field to the observation record when available.

- **Dial-sensitivity sweep** — re-classifies all elements across a grid of
  `(d_hi, r_min)` values. Shows how many elements fall into each class at each
  setting, and (where calibration data exists) the precision the new thresholds
  would have achieved. Use this to find the Pareto frontier of
  ambiguity-rate vs precision before bumping the dials in
  `ctkr/ctkr/data/intention_normalization.json`.
