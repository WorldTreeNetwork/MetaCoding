# eval/ctkr — role_equivalent eval harness

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

**`repo`** is the directory name under `~/projects/Orchestrators/`.

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
