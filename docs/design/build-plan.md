# Build plan

Optimize for **agent-usable in a weekend**, then iterate. Lower-fidelity lanes ship first because they have universal coverage; higher-fidelity lanes upgrade specific languages.

## Phase 0 — scaffolding (day 0)

- Pick implementation language. **Python** is the path of least resistance: multilspy is Python, sentence-transformers is Python (if we ever add embeddings), Tree-sitter has Python bindings, MCP has a clean Python SDK. **Rust** is faster and has Tree-sitter's native API but more rope.
- Repo skeleton: `metacoding/` package with `extractors/`, `graph/`, `fts/`, `mcp/`, `cli/`.
- Pin ladybugdb (or fall back to SQLite-with-adjacency-tables until ladybug Python bindings stabilize — check current state).
- One smoke-test repo to dogfood against (something Java + something TypeScript).

## Phase 1 — Tree-sitter + FTS + ladybugdb + MCP (the MVP)

Goal: an agent can ask `graph_neighbors(OrderService)` and `code_search("orderService")` and get useful answers.

1. **Tree-sitter walker.** For TS, Python, Java to start. Per-language extractor module. Emit:
   - `Symbol` nodes (class, interface, method, function, field).
   - `CONTAINS`, `EXTENDS`, `IMPLEMENTS` edges (visible in syntax).
   - FTS rows for identifiers, literals, comments.
2. **ladybugdb writer.** Schema from [schema.md](schema.md). Idempotent writes keyed by symbol ID. Wrapper patterns and Bun finalizer mitigation in [storage-integration.md](storage-integration.md).
3. **SQLite FTS5 sidecar.** Custom code-aware splitter (camelCase + snake_case + trigram). Same try/finally discipline as the graph wrapper.
4. **MCP server.** Five tools: `graph_neighbors`, `graph_implementers`, `graph_callers`, `graph_path`, `code_search`. Use the official MCP SDK; transport over stdio for Claude Code. Ship a `describe_api` tool that generates from live schema (no hand-maintained docs).
5. **CLI.** `metacoding index <path>`, `metacoding query <cypher>`, `metacoding serve` (start MCP).

Exit criteria: the MVP correctly answers the paper's interface-consumer question on Shopizer using only Tree-sitter (lower fidelity than DKB but comparable shape).

## Phase 2 — SCIP integration (week 2)

Goal: resolved-symbol fidelity for the core languages.

1. **Per-language SCIP indexers.** Wrap `scip-typescript`, `scip-python`, `scip-java`, `scip-go` as subprocess calls.
2. **SCIP loader.** Parse the protobuf, project into our Symbol/edge schema. Mark nodes with `source='scip'`.
3. **Lane reconciliation.** When SCIP and Tree-sitter disagree about a node, prefer SCIP. Edges from both are kept; deduplicated by `(src_id, dst_id, kind)`.
4. **CALLS and REFERENCES** edges become real (Tree-sitter alone couldn't resolve these).

Exit criteria: cross-file `graph_callers` works correctly for TypeScript and Java.

## Phase 3 — LSP overlay (week 3)

Goal: dirty-buffer answers and broader language coverage.

1. **multilspy integration.** One `LSPService` class that manages a pool of language servers.
2. **Dirty-file overlay.** Maintain a set of files modified since last SCIP index. Route queries that touch those files through the live LSP for fresh answers.
3. **`symbol_hover`, `symbol_diagnostics`, `symbol_signature`** MCP tools.
4. **Coverage extension.** Languages without SCIP support (Kotlin, Swift, Elixir) get LSP-only graph population.

Exit criteria: edit a file, ask a question about the just-edited symbol, get a current answer.

## Phase 4 — incrementality and watch mode (week 4)

Goal: re-index in milliseconds, not seconds.

1. **AST-hash incremental.** For each file, store an AST hash. On change, recompute hash; if unchanged, skip. (Idea from source-atlas.)
2. **Reverse-dep closure.** When a file's symbols change, recompute edges for files that imported/referenced them.
3. **File watcher** (`watchdog` on Python). Re-index changed files automatically.
4. **Branch awareness.** Tag every node with current branch. Switching branches swaps the active partition.

## Phase 5 — Joern dataflow (when needed)

Goal: opt-in interprocedural dataflow.

1. **Joern subprocess wrapper.** Spawn `joern --server`, send CPGQL, parse paths.
2. **`graph_taint` MCP tool.** Long-running; report progress; cache results keyed by source/sink.
3. **Materialize `FLOWS_TO` edges** with provenance for any path the agent has queried.

## Phase 6 — open questions (parked)

- **Embeddings.** Add a vector lane only when a class of useful queries fails through the existing four. Likely the local-model path (`nomic-embed-text` via Ollama) — embedder lives in the MCP server, never the agent.
- **LLM-extracted soft edges.** For comment cross-references, README links to symbols, etc. Cost-justify before adding.
- **Refactoring write tools.** Rename, extract method via LSP `workspace/applyEdit`. Out of scope until the read story is solid.
- **Multi-repo / monorepo modes.** Schema supports it (file paths are repo-relative); query routing is the open part.

## Stack at a glance

| Component | Choice | Notes |
|-----------|--------|-------|
| Language | Python | Easiest integration with multilspy, MCP SDK, Tree-sitter |
| Graph DB | ladybugdb | Embedded Cypher; fall back to SQLite if Python bindings aren't ready |
| FTS | SQLite FTS5 | Universal, embedded, no extra process |
| Parsers | Tree-sitter | grammar per language |
| Symbol resolution | SCIP indexers, then LSP via multilspy | SCIP for HEAD, LSP for dirty/missing |
| Optional dataflow | Joern via subprocess | out-of-band |
| Transport | MCP stdio | for Claude Code integration |

## What "done v1" looks like

- `metacoding index` on a 5k-file Java codebase finishes in under 60s (with SCIP).
- The five core MCP tools each return useful answers under 200ms median for a warm graph.
- File-edit-then-query round trip via LSP overlay is under 500ms.
- The 2026 paper's 15-question Shopizer benchmark scores ≥13/15 correct, beating the paper's DKB by leveraging SCIP's resolved symbols over their Tree-sitter approach.
