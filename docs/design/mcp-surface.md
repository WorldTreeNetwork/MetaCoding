# MCP surface

Small, typed, opinionated. Specific tools the agent will actually call rather
than a Cypher passthrough that requires the agent to author graph queries.

> **Discovery.** The live, authoritative tool list is whatever
> `describe_api` returns — it is generated from `TOOL_DESCRIPTIONS` in
> `src/mcp/tools.ts` (core + LSP) spliced with `CTKR_TOOL_DESCRIPTIONS` in
> `src/mcp/ctkr-tools.ts` (the `ctkr.*` family). A drift guard
> (`src/mcp/describe-api.test.ts`) fails if any registered tool is missing
> from that list, so an agent harness that calls `describe_api` always sees
> the full surface. This document is the human-readable companion; when the
> two disagree, `describe_api` is right and this file is stale.

Server identity: `name: "metacoding"`, stdio transport, one server per data
dir (`src/mcp/server.ts`). Read-only by design.

---

## Core graph tools

### `graph_neighbors`
```
input:  symbol (id or qualified_name), direction (in|out|both), edge_kinds? (filter), limit=50, repo_commit_sha?
output: list of Symbol with edge metadata
```
The workhorse. "What does this touch / what touches this."

### `graph_implementers`
```
input:  symbol (id or qualified_name), limit=50, repo_commit_sha?
output: list of Symbol implementing or extending it (incoming IMPLEMENTS/EXTENDS)
```
The interface-consumer trick from the 2026 paper, first-class. "Which classes
implement `IOrderService`?"

### `graph_callers`
```
input:  symbol, limit=50, repo_commit_sha?
output: list of Symbol that call or reference this one (incoming CALLS/REFERENCES)
```
"Who depends on this function?" Convenience wrapper over `graph_neighbors`.
Available only after a SCIP pass — Tree-sitter alone can't resolve cross-file
references.

### `graph_diff`
```
input:  repo, from_sha, to_sha, limit=1000
output: { added, removed, changed } Symbol rows (changed = same qualified_name, different ast_hash)
```
"What changed between these two indexed snapshots?" Requires both snapshots to
coexist in the store — usually means the repo was indexed with
`--per-commit-identity`.

### `graph_cypher`
```
input:  cypher, params?, limit=100
output: rows
```
Escape hatch. Don't lean on it; if a query type is common, promote it to a
typed tool.

---

## Text / FTS tools

### `code_search`
```
input:  query (FTS5), kind? (literal|identifier|comment|annotation_arg|config_value), limit=50, repo_commit_sha?
output: list of token hits with {file, line, col, kind, snippet, symbol_id?}
```
The string-blind-spot lane. Catches string DI, reflection, dynamic dispatch,
ORM strings, route paths — the AST/SCIP blind spots.

---

## LSP tools (live, dirty-buffer-aware)

These read the running language server, so they reflect unsaved edits.
Positions are 0-indexed.

### `lsp_hover`
```
input:  file, line, col
output: hover markdown (type, signature, docstring)
```

### `lsp_definition`
```
input:  file, line, col
output: definition locations
```

### `lsp_references`
```
input:  file, line, col, include_declaration=false
output: reference locations
```
Use when `graph_callers` might be stale (file edited after indexing).

### `lsp_diagnostics`
```
input:  file, wait_ms=3000
output: list of diagnostics with severity, message, range
```
Current type errors / lints. Poll after edits.

---

## CTKR tools — categorical knowledge over the cross-repo corpus

These read the Parquet/JSONL artifacts under `.metacoding/ctkr/` (see
[`ctkr-artifacts.md`](ctkr-artifacts.md) and [`ctkr.md`](ctkr.md)). The data
dir is resolved from `METACODING_CTKR_DATA_DIR` (mandatory — no implicit
corpus fallback).

### `ctkr.motif_search`
```
input:  min_support?, edge_kinds?, repo_coverage_min?, label?, limit=50
output: MotifRow records (frequent typed subgraphs), optionally L3-labeled
```
"What structural shapes recur across the corpus, and where?"

### `ctkr.nearest_symbols`
```
input:  symbol_id | qualified_name, k=10, cross_repo_only=false, embedding_kind=structural
output: k nearest symbols by structural-embedding cosine distance
```
Similarity by learned structural embedding (DeepWalk/GraphSAGE).

### `ctkr.role_equivalent`
```
input:  symbol_id | qualified_name, k=10, scope? (repo), cross_repo_only=false
output: k symbols playing the same structural role, by hom-profile cosine KNN
```
The **categorically-honest "same role" query** (Phase 2a). Matches turn on the
shape of a symbol's typed-edge neighbourhood — `hom_profiles.parquet` — so they
are independent of name and of a repo's naming conventions. `cross_repo_only`
is the cross-repo role-equivalence predicate. `scope` disambiguates a
`qualified_name` that appears in several repos. Distinct from
`nearest_symbols`: that uses learned embeddings; this uses the raw typed-edge
count vector at maximal precision (see [entropy-as-dial](../notes/entropy-as-dial.md)).

### `ctkr.pattern_search`
```
input:  label?, source_kind? (motif|role-cluster|analogy), min_confidence?, instances_in_repo?, limit=50
output: PatternRow records (L3-labeled) with attached evidence
```
The labeled-knowledge lane. `source_kind='role-cluster'` surfaces the output of
`ctkr label-roles` (the L3 role-class labeler); `source_kind='motif'` the
labeled motifs.

### `ctkr.shape_distance`
```
input:  repo_a (+ repo_b for a pair | + k_nearest for top-k)
output: bottleneck H₁ Wasserstein distance(s) between repos
```
Topological similarity between whole repos. Distance `-1` = pair absent from
`wasserstein_h1.parquet`.

### `ctkr.centrality_query`
```
input:  metric (pagerank|betweenness|eigenvector), repo?, kind?, top_k?
output: per-symbol centrality scores joined with spectral cluster assignments
```

---

## `describe_api`
```
input:  {}
output: { name, version, tools[], schema: { edge_kinds, token_kinds } }
```
Self-describe. Agents (and harnesses) should call this first to discover the
live surface and exact input schemas.

---

## Tools we deliberately do NOT expose

- `vector_search` (raw) — exposed instead as the purpose-built
  `ctkr.nearest_symbols` / `ctkr.role_equivalent`. No generic kNN endpoint.
- `extract_with_llm` — out of scope at query time. The graph is deterministic;
  LLM labeling happens offline in the L3 build (`ctkr label-roles`,
  `ctkr label-motifs`) and is read back via `ctkr.pattern_search`.
- Generic `db_query` — let the agent compose typed tools instead of writing
  SQL/Cypher; `graph_cypher` is the one reluctant escape hatch.
- Anything write-side — read-only by design. Refactoring tools, if ever added,
  go through the LSP's `workspace/applyEdit`, not raw graph mutations.

## Not yet implemented (vision)

Named in earlier drafts and still wanted, but not currently registered —
compose the shipped tools for now:

- `graph_callees`, `graph_path` — walk-out and pathfinding (compose
  `graph_neighbors`).
- `code_search_regex` — ripgrep-backed regex over the indexed file set.
- `graph_taint` — Joern `reachableByFlows` source→sink (slow, out-of-band).

## Design notes

- **Keep the surface small.** The temptation is 20 tools; the agent reliably
  uses 5. Ship the small set, watch which the agent reaches for, promote common
  `graph_cypher` patterns to typed tools.
- **Return symbol IDs, not full content.** Let the agent fetch source via
  `Read`. Tool outputs should fit comfortably in context.
- **Compose, don't bloat.** "Controllers that call services that touch the
  orders table" is the agent composing `graph_callers` + `code_search` +
  `graph_neighbors`, not a single bespoke tool.
- **Predictable shapes.** Every result that references a symbol returns the same
  `{id, qualified_name, file, line, kind}` envelope.
- **Co-locate descriptions with registration.** A new tool's `describe_api`
  entry lives next to its `registerTool` call (core tools in `tools.ts`, CTKR
  tools in `ctkr-tools.ts`), and `describe-api.test.ts` enforces parity.
