# MetaCoding — design docs

A local-first code-graph DB for AI coding agents. Walk a codebase, build a typed graph of symbols and their relationships, expose it over MCP. Replaces (or complements) vector RAG for multi-hop architectural reasoning.

## TL;DR

The agent reads code through five complementary lanes:

1. **SCIP** — at-rest, resolved symbol graph (committed code).
2. **LSP** — live/dirty buffer overlay; languages SCIP doesn't index well.
3. **Tree-sitter** — configs, broken code, pattern queries, bootstrap.
4. **SQLite FTS5** — string DI, metaprogramming, reflection — the AST/LSP/SCIP blind spots.
5. **ladybugdb (Kùzu fork)** — embedded graph store under all of it.

Exposed via MCP with a small typed surface (`graph_neighbors`, `graph_implementers`, `graph_callers`, `graph_path`, `code_search`, `graph_cypher`).

Embeddings deferred until a query comes up that the other four lanes can't answer.

## Layout

- [VISION.md](VISION.md) — the strategic layer: why MetaCoding exists, what "grokking code" means, the four-phase ladder.
- [design/ct-pipeline.md](design/ct-pipeline.md) — the categorical analysis pipeline (Phase 1 → Phase 4) with CT references.
- [design/ctkr.md](design/ctkr.md) — Category-Theoretic Knowledge Representation theoretics (Layer 0 → Layer 3).
- [notes/](notes/) — working notes, design sessions, living roadmap material.
- [research/paper-2601.08773v1.md](research/paper-2601.08773v1.md) — the 2026 paper that motivated this (deterministic AST graphs vs LLM-extracted KGs for code RAG), with critique.
- [research/prior-art.md](research/prior-art.md) — Joern, ChrisRoyse/CodeGraph, quyen-ngv/source-atlas. What to steal, what to skip.
- [design/architecture.md](design/architecture.md) — the five-lane stack and why each lane earns its slot.
- [design/schema.md](design/schema.md) — graph node/edge schema (Joern CPG flattened) and FTS table.
- [design/mcp-surface.md](design/mcp-surface.md) — concrete MCP tools.
- [design/ctkr-artifacts.md](design/ctkr-artifacts.md) — L1 artifact schema (`.metacoding/ctkr/`).
- [design/ctkr-l3-artifacts.md](design/ctkr-l3-artifacts.md) — L3 artifact schema (patterns + evidence).
- [design/storage-integration.md](design/storage-integration.md) — ladybugdb + FTS5 wrapper patterns; Bun finalizer mitigation; storage-format compatibility (lessons from Dreamball's ADR).
- [design/build-plan.md](design/build-plan.md) — MVP order of operations.

## Design principles

- **Deterministic before probabilistic.** AST/SCIP/LSP first; LLM extraction only for edges the type system can't see.
- **Local-first, embedded, beads-shaped.** No servers, no cloud dependencies. One process, one on-disk DB.
- **Typed MCP surface.** Specific tools (`graph_implementers`, `graph_callers`) over raw Cypher passthrough. Lets the agent compose; doesn't make it write Cypher to find a caller.
- **Layered fidelity.** Tree-sitter ships immediately at low fidelity; SCIP and LSP upgrade specific languages without reshaping the API.
- **Defer what isn't load-bearing.** No embeddings v0. No taint analysis v0. Add lanes when queries demand them.
