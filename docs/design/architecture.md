# Architecture

Five lanes, one graph store, one MCP surface.

```
                     ┌──────────────────────────────────┐
                     │  MCP Tools (typed)               │
                     │  graph_neighbors / implementers  │
                     │  graph_callers / path / cypher   │
                     │  code_search                     │
                     └────────────┬─────────────────────┘
                                  │
                     ┌────────────▼─────────────────────┐
                     │  ladybugdb (Kùzu fork)           │
                     │  embedded Cypher graph DB        │
                     │      ┌───────────────────────┐   │
                     │      │ SQLite FTS5 sidecar   │   │
                     │      │ tokens(text,kind,...) │   │
                     │      └───────────────────────┘   │
                     └────────────▲─────────────────────┘
                                  │ writes
        ┌───────────┬─────────────┼─────────────┬───────────────┐
        │           │             │             │               │
   ┌────▼────┐ ┌────▼────┐ ┌──────▼──────┐ ┌────▼─────┐ ┌───────▼───────┐
   │  SCIP   │ │   LSP   │ │ Tree-sitter │ │ FTS      │ │ Joern (opt-in)│
   │ at-rest │ │  live   │ │  configs    │ │  string  │ │  taint/dflow  │
   │ HEAD    │ │ buffers │ │  fallback   │ │  tokens  │ │  out-of-band  │
   └─────────┘ └─────────┘ └─────────────┘ └──────────┘ └───────────────┘
```

## Lane 1 — SCIP (primary, at-rest)

- Run a per-language SCIP indexer at index time (`scip-typescript`, `scip-java`, `scip-python`, `scip-go`, `scip-clang`, `scip-ruby`).
- Output: a `.scip` protobuf file per repo per language.
- Load definitions, references, and symbol relationships into the graph.
- **Strengths:** resolved symbols, generics, overrides, cross-module refs. Stable artifact, no warmup at query time.
- **Use for:** the canonical graph of HEAD.

## Lane 2 — LSP (live overlay, dirty buffers)

- Drive headless language servers via [multilspy](https://github.com/microsoft/multilspy) or similar.
- For files modified since the last SCIP index, query the live LSP for definitions/references and overlay onto the SCIP-derived graph.
- Also the primary lane for languages SCIP doesn't cover well (Kotlin, Swift, Elixir, Scala, etc.).
- Also the source for hover, signature help, diagnostics — exposed as separate MCP tools rather than graph edges.
- **Strengths:** answers about uncommitted code; broad language coverage.
- **Cost:** cold-start tax (jdt.ls, rust-analyzer 30–90s warmup); per-language setup.

## Lane 3 — Tree-sitter (fallback, configs, patterns, bootstrap)

- Parses any file with a grammar in milliseconds, no warmup, no toolchain.
- **Use for:**
  - Bootstrap pass before SCIP/LSP is ready.
  - File types SCIP/LSP can't read: Dockerfile, HCL, YAML/JSON, Bash, Nix, Markdown.
  - Pattern queries: "find all `@RequestMapping` annotations and pull their path strings," "find every SQL literal."
  - Broken/mid-edit buffers (Tree-sitter's error recovery).
- Also the *extractor* feeding the FTS lane: walks every file, emits identifiers, string literals, comments with positions.

## Lane 4 — SQLite FTS5 (string blind spots)

The AST/SCIP/LSP stack misses everything that lives in *strings*:
- DI by name: `context.getBean("orderService")`, Spring XML, `@Component("foo")`.
- Reflection: `Class.forName`, `getattr`, `Object.GetType`.
- Dynamic dispatch through `Object`/`any`.
- ORM/SQL: table names, column names, raw queries.
- Routes/RPC: `"/api/orders"`, `"users.create"`.
- Config-driven wiring: YAML/properties referencing fully-qualified classes.

SQLite FTS5 sidecar: one table, kind-tagged tokens with positions. Code-aware splitter (camelCase + snake_case) at write time. Trigram tokenizer for partial matches.

Used as a **fall-through** from the graph: "no edges to `OrderService`? FTS for `\"orderService\"` across literals."

## Lane 5 — Joern (opt-in dataflow)

Out-of-band, on demand. When the agent invokes `graph_taint(source, sink)`:
- Spawn `joern --server`.
- Build CPG (or load cached one).
- Run `reachableByFlows` query.
- Return paths, tear down.

Pattern proven by `Lekssays/codebadger`. Treat Joern as a single-purpose engine for interprocedural dataflow, not the substrate.

## Storage — ladybugdb

[Ladybugdb](https://github.com/ladybugdb/ladybugdb) is the maintained fork of Kùzu after the original maintainers went silent. Embedded, columnar, Cypher, single binary, file-on-disk. Same role SQLite plays for relational data.

For projects we expect to scale beyond ~1M edges, the columnar layout matters; for everything else, SQLite-with-adjacency-tables would also work and we could swap.

## What we deliberately defer

- **Embeddings / vector search.** Graph + FTS already cover multi-hop reasoning (graph) and string match (FTS). The remaining vector use case is fuzzy semantic match ("find rate-limiting logic"). Defer until we can name a query the other lanes can't answer.
- **LLM-extracted edges.** The 2026 paper's central finding is that probabilistic extraction is dominated by deterministic on cost, latency, and recall. Don't add it back gratuitously. Maybe revisit for a "soft edges" lane (e.g., natural-language references in comments) once everything else is solid.

## Why this order

| Lane          | Fidelity | Cost | Coverage  | When ready |
|---------------|----------|------|-----------|------------|
| SCIP          | High     | Mid  | 5–6 langs | At commit  |
| LSP           | High     | High | ~all langs| Live       |
| Tree-sitter   | Low      | Low  | ~all      | Always     |
| FTS           | N/A      | Low  | Universal | Always     |
| Joern         | High*    | High | 10+ langs | On demand  |

*High for taint/dataflow specifically.

The agent always has *some* answer because Tree-sitter + FTS are universal and cheap. SCIP and LSP are upgrades for the languages they cover well. Joern is a niche power tool.
