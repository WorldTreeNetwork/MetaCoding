# Prior art

Three projects in the adjacent space. Findings from focused research passes.

## joernio/joern

**Verdict:** wrong shape for the substrate. Borrow the schema; use it as opt-in dataflow lane.

- **What it is.** Mature security-focused static analysis platform. Builds a **Code Property Graph (CPG)** — AST + CFG + REACHING_DEF + CDG + CALL + REF fused into one graph. Apache-2.0.
- **Why it's wrong for the hot path.**
  - No incremental indexing (their own issue #5865, March 2026 — every change is a full rebuild).
  - JVM, requires JDK 21. Cold start in tens of seconds to minutes for a few thousand files; benchmark recommends 128 GB RAM for kernel-scale.
  - Custom flatgraph storage format, not externally queryable. Cypher export exists (`joern-export`) but has bugs (#4304).
  - Scala-flavored Gremlin DSL or a stringly-typed HTTP server (`joern --server`).
- **What it gives you that LSPs don't.** REACHING_DEF, CDG, taint queries (`reachableBy/reachableByFlows`). Useful for "where does this user input end up?" — niche outside security.
- **What to steal.**
  - The CPG schema (most thought-through OSS code-graph ontology, Apache-2.0).
  - The two-tier model: static structural graph (always-on) + interprocedural dataflow (opt-in, expensive).
- **Existing MCP wrappers.** `sfncat/mcp-joern` (thin), `Lekssays/codebadger` (~30 tools, containerized, hard caps: 500 MB max repo, 600s CPG generation timeout, 40 GB JVM). Both leak Joern's batch nature.
- **How we'd use it.** Spawn `joern --server` only when an agent calls `graph_taint(source, sink)`. Run query, return paths, tear down. Out of band, opt-in.

## ChrisRoyse/CodeGraph

**Verdict:** don't adopt, don't fork. Steal the schema taxonomy at most.

- **Maturity.** 4 commits on main (all 2025-04-01), single author, dead since May 2025 (~11 months). 77 stars, fork:star ratio suggests stargazers haven't actually used it. License field literally `null` in the GitHub API despite README claiming MIT.
- **Indexing.** Tree-sitter + ts-morph + Python `ast`, plus a name-heuristic cross-file resolver (no LSP, no SCIP — approximate symbol resolution).
- **Storage.** External Neo4j 5.26+ server. Not embedded.
- **MCP layer.** One stub tool that returns a command string instead of executing it. Hardcoded `neo4j/test1234` creds. Real MCP story is the external `@alanse/mcp-neo4j-server` bridge — generic Cypher passthrough, no typed graph tools.
- **Code quality.** Parsers are hand-written and considered (vitest + testcontainers, real `.spec.ts` siblings). MCP layer is shovelware.
- **What to steal.** Schema in `src/database/schema.ts` (~39 node labels, 31+ relationship types). **Antipattern to avoid:** per-language label namespacing (`PythonClass`, `JavaClass`, `GoStruct`). Flatten to one `Class` label with a `language` property.

## quyen-ngv/source-atlas

**Verdict:** closest reference design. Adopt the resolution loop and the schema; replace the storage and add MCP.

- **Maturity.** Created 2025-11-25, dormant since 2025-12-21. Single author. MIT license. README claims Java/Python/Go/TS; only Java is actually implemented.
- **Indexing approach.** **This is the architecture validation we needed.** Tree-sitter parses files locally and extracts structural elements; multilspy drives a real LSP for cross-file resolution (`request_definition`, `request_implementation`). No SCIP, no LLM extraction. AST-hash-based incremental indexing with branch/PR-aware versioning.
- **Storage.** External Neo4j 5.x. Wrong shape for our embedded vision.
- **Query interface.** Raw Cypher only. No MCP, no typed query API.
- **What to steal — three specific things.**
  1. **`lsp_service.py` (~110 lines)** — clean multilspy wrapper. Copy-pasteable.
  2. **The Tree-sitter-position → LSP-`definition` resolution pattern** in `JavaCodeAnalyzer` (~1100 lines). Working reference for the hybrid extractor.
  3. **Schema.** Node properties `ast_hash`, `branch`, `pull_request_id` — branch-aware multi-tenancy is a nice idea. Edges `CALL`/`IMPLEMENT`/`EXTEND`/`USE`/`BRANCH`.
- **Note:** their use of Tree-sitter to *find positions* before calling LSP is slightly silly — `textDocument/documentSymbol` gives both in one call. Don't mirror that.

## What's missing from the field

No project ships all of:
- Embedded graph DB (Kùzu/ladybug). Everyone reaches for Neo4j out of habit.
- Typed MCP tools. Everyone exposes raw Cypher.
- Multi-language LSP/SCIP coverage actually delivered.
- FTS lane for the string-DI / reflection / metaprogramming blind spot.

That gap is the wedge.
